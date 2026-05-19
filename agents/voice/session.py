"""SonicSession: Bedrock bidirectional stream wrapper for Nova Sonic.

Adapted from reference/nova-sonic-demo/session.py with adjusted imports
to work within agents/voice/.
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import AsyncIterator, Callable, Optional, Protocol, Set

from config import (
    MODEL_ID,
    SESSION_OPEN_TIMEOUT_S,
    BedrockOpenError,
)
from events import (
    OutputEvent,
    ToolUseEvent,
    TranscriptEvent,
    audio_input_event,
    content_end_event,
    content_start_audio_input_event,
    content_start_text_input_event,
    content_start_tool_result_event,
    parse_output_event,
    prompt_end_event,
    prompt_start_event,
    session_end_event,
    session_start_event,
    text_input_event,
    tool_result_event,
)
from logging_utils import ConsoleLogger


# ---------------------------------------------------------------------------
# Bidirectional RPC abstraction
# ---------------------------------------------------------------------------


class BidirectionalRpc(Protocol):
    async def send_input(self, event: dict) -> None: ...
    async def close_input(self) -> None: ...
    def output(self) -> AsyncIterator[dict]: ...


def _default_client_factory(region: str):
    """Build the default Nova Sonic Bedrock-runtime adapter."""

    import boto3

    from aws_sdk_bedrock_runtime.client import (
        BedrockRuntimeClient,
        InvokeModelWithBidirectionalStreamOperationInput,
    )
    from aws_sdk_bedrock_runtime.config import Config
    from aws_sdk_bedrock_runtime.models import (
        BidirectionalInputPayloadPart,
        InvokeModelWithBidirectionalStreamInputChunk,
    )
    from smithy_aws_core.identity.components import AWSCredentialsIdentity
    from smithy_core.aio.interfaces.identity import IdentityResolver

    session = boto3.Session()
    creds = session.get_credentials()
    if creds is None:
        raise BedrockOpenError(
            "auth",
            "AWS credentials could not be resolved from the standard SDK chain",
        )

    frozen = creds.get_frozen_credentials()
    aws_identity = AWSCredentialsIdentity(
        access_key_id=frozen.access_key,
        secret_access_key=frozen.secret_key,
        session_token=frozen.token,
    )

    class _Boto3BridgeCredentialsResolver(IdentityResolver):
        async def get_identity(self, *, properties=None):
            return aws_identity

    config = Config(
        endpoint_uri=f"https://bedrock-runtime.{region}.amazonaws.com",
        region=region,
        aws_credentials_identity_resolver=_Boto3BridgeCredentialsResolver(),
    )
    client = BedrockRuntimeClient(config=config)

    class _SdkClientAdapter:
        async def invoke_model_with_bidirectional_stream(self, *, modelId, body=b""):
            stream = await client.invoke_model_with_bidirectional_stream(
                InvokeModelWithBidirectionalStreamOperationInput(model_id=modelId)
            )
            return _SdkRpcAdapter(
                stream,
                InvokeModelWithBidirectionalStreamInputChunk,
                BidirectionalInputPayloadPart,
            )

    return _SdkClientAdapter()


class _SdkRpcAdapter:
    """Translate BidirectionalRpc calls into the SDK's wire shape."""

    def __init__(self, stream, input_chunk_cls, payload_part_cls) -> None:
        self._stream = stream
        self._input_chunk_cls = input_chunk_cls
        self._payload_part_cls = payload_part_cls
        self._input_closed = False

    async def send_input(self, event: dict) -> None:
        payload = json.dumps(event).encode("utf-8")
        chunk = self._input_chunk_cls(value=self._payload_part_cls(bytes_=payload))
        await self._stream.input_stream.send(chunk)

    async def close_input(self) -> None:
        if self._input_closed:
            return
        self._input_closed = True
        try:
            await self._stream.input_stream.close()
        except Exception:
            pass

    async def output(self):
        """Yield raw event dicts decoded from the SDK's typed output stream."""
        while True:
            try:
                output = await self._stream.await_output()
            except Exception:
                return
            try:
                result = await output[1].receive()
            except Exception:
                return
            value = getattr(result, "value", None)
            raw_bytes = getattr(value, "bytes_", None) if value is not None else None
            if not raw_bytes:
                continue
            try:
                yield json.loads(raw_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue


# ---------------------------------------------------------------------------
# SonicSession
# ---------------------------------------------------------------------------

_AUTH_ERROR_CODES = frozenset(
    {
        "UnrecognizedClientException",
        "InvalidSignatureException",
        "AccessDeniedException",
        "ExpiredTokenException",
    }
)


class SonicSession:
    """Bedrock bidirectional stream wrapper for Nova Sonic."""

    def __init__(
        self,
        region: str,
        registry,  # MCPToolRegistry or ToolRegistry — needs to_bedrock_config()
        logger: ConsoleLogger,
        dispatcher,  # MCPToolDispatcher or ToolDispatcher — needs dispatch()
        *,
        client_factory: Optional[Callable[[str], object]] = None,
        system_prompt: Optional[str] = None,
        prompt_id_factory: Optional[Callable[[], str]] = None,
        content_id_factory: Optional[Callable[[], str]] = None,
        open_timeout_s: float = SESSION_OPEN_TIMEOUT_S,
    ) -> None:
        self._region = region
        self._registry = registry
        self._logger = logger
        self._dispatcher = dispatcher
        self._client_factory = client_factory or _default_client_factory
        self._system_prompt = system_prompt
        self._prompt_id_factory = prompt_id_factory or (lambda: str(uuid.uuid4()))
        self._content_id_factory = content_id_factory or (lambda: str(uuid.uuid4()))
        self._open_timeout_s = open_timeout_s

        self._client: object | None = None
        self._rpc: Optional[BidirectionalRpc] = None
        self._prompt_name: str = ""
        self._content_name: str = ""
        self._opened: bool = False
        self._closed: bool = False
        self._write_lock: asyncio.Lock = asyncio.Lock()
        self._tool_tasks: Set[asyncio.Task] = set()

    async def open(self) -> None:
        if self._opened or self._closed:
            return
        try:
            await asyncio.wait_for(self._open_inner(), timeout=self._open_timeout_s)
        except asyncio.TimeoutError as exc:
            await self._safe_close_rpc()
            raise BedrockOpenError("timeout", exc) from exc
        except BedrockOpenError:
            await self._safe_close_rpc()
            raise
        except Exception as exc:
            category = self._classify_open_error(exc)
            await self._safe_close_rpc()
            raise BedrockOpenError(category, exc) from exc

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if self._closed:
            raise RuntimeError("session closed")
        if not self._opened or self._rpc is None:
            raise RuntimeError("session not open")

        b64 = base64.b64encode(pcm_bytes).decode("ascii")
        evt = audio_input_event(self._prompt_name, self._content_name, b64)
        async with self._write_lock:
            await self._rpc.send_input(evt)

    async def stream_events(self) -> AsyncIterator[OutputEvent]:
        if self._rpc is None:
            return
        assistant_stage = "SPECULATIVE"
        async for raw in self._rpc.output():
            inner = raw.get("event", raw) if isinstance(raw, dict) else None

            if isinstance(inner, dict) and "contentStart" in inner:
                cs = inner["contentStart"]
                if isinstance(cs, dict):
                    extra = cs.get("additionalModelFields")
                    if isinstance(extra, str):
                        try:
                            extra = json.loads(extra)
                        except (TypeError, ValueError):
                            extra = None
                    if isinstance(extra, dict) and isinstance(
                        extra.get("generationStage"), str
                    ):
                        assistant_stage = extra["generationStage"]
                    else:
                        assistant_stage = "SPECULATIVE"
                continue

            event = parse_output_event(raw)
            if event is None:
                continue
            if isinstance(event, ToolUseEvent):
                task = asyncio.create_task(self._handle_tool_use(event))
                self._tool_tasks.add(task)
                task.add_done_callback(self._tool_tasks.discard)
                continue

            if (
                isinstance(event, TranscriptEvent)
                and event.role == "ASSISTANT"
                and assistant_stage == "FINAL"
            ):
                continue

            yield event

    async def send_tool_result(self, tool_use_id: str, result: dict) -> None:
        if self._closed:
            raise RuntimeError("session closed")
        if not self._opened or self._rpc is None:
            raise RuntimeError("session not open")

        fresh_content_name = self._content_id_factory()
        try:
            content_json = json.dumps(result)
        except (TypeError, ValueError):
            content_json = json.dumps({"error": "non_serializable_result"})

        async with self._write_lock:
            await self._rpc.send_input(
                content_start_tool_result_event(
                    self._prompt_name, fresh_content_name, tool_use_id
                )
            )
            await self._rpc.send_input(
                tool_result_event(self._prompt_name, fresh_content_name, content_json)
            )
            await self._rpc.send_input(
                content_end_event(self._prompt_name, fresh_content_name)
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        for task in list(self._tool_tasks):
            task.cancel()

        if self._opened and self._rpc is not None:
            terminators = (
                content_end_event(self._prompt_name, self._content_name),
                prompt_end_event(self._prompt_name),
                session_end_event(),
            )
            async with self._write_lock:
                for evt in terminators:
                    try:
                        await self._rpc.send_input(evt)
                    except Exception:
                        pass

        if self._rpc is not None:
            try:
                await self._rpc.close_input()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _open_inner(self) -> None:
        self._client = self._client_factory(self._region)
        invoke = getattr(self._client, "invoke_model_with_bidirectional_stream")
        rpc = await invoke(modelId=MODEL_ID, body=b"")
        self._rpc = rpc

        self._prompt_name = self._prompt_id_factory()
        self._content_name = self._content_id_factory()

        async with self._write_lock:
            await rpc.send_input(session_start_event())
            await rpc.send_input(
                prompt_start_event(
                    self._prompt_name,
                    self._registry.to_bedrock_config(),
                    None,
                )
            )
            if self._system_prompt:
                sys_content_name = self._content_id_factory()
                await rpc.send_input(
                    content_start_text_input_event(
                        self._prompt_name, sys_content_name, role="SYSTEM"
                    )
                )
                await rpc.send_input(
                    text_input_event(
                        self._prompt_name, sys_content_name, self._system_prompt
                    )
                )
                await rpc.send_input(
                    content_end_event(self._prompt_name, sys_content_name)
                )
            await rpc.send_input(
                content_start_audio_input_event(
                    self._prompt_name, self._content_name
                )
            )

        self._opened = True

    async def _handle_tool_use(self, event: ToolUseEvent) -> None:
        try:
            result = await self._dispatcher.dispatch(
                event.tool_use_id, event.tool_name, event.arguments
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return

        try:
            await self.send_tool_result(event.tool_use_id, result)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def _safe_close_rpc(self) -> None:
        rpc = self._rpc
        if rpc is None:
            return
        try:
            await rpc.close_input()
        except Exception:
            pass

    @staticmethod
    def _classify_open_error(exc: Exception) -> str:
        ClientError = None
        EndpointConnectionError = None
        try:
            from botocore.exceptions import (
                ClientError as _ClientError,
                EndpointConnectionError as _EndpointConnectionError,
            )
            ClientError = _ClientError
            EndpointConnectionError = _EndpointConnectionError
        except Exception:
            pass

        if ClientError is not None and isinstance(exc, ClientError):
            response = getattr(exc, "response", {}) or {}
            err = response.get("Error", {}) if isinstance(response, dict) else {}
            code = err.get("Code", "") if isinstance(err, dict) else ""
            message = err.get("Message", "") if isinstance(err, dict) else ""

            if code in _AUTH_ERROR_CODES:
                return "auth"
            if code == "ValidationException" and "region" in (message or "").lower():
                return "region"
            if code == "ResourceNotFoundException":
                return "model"
            return "model"

        if EndpointConnectionError is not None and isinstance(exc, EndpointConnectionError):
            return "network"
        if isinstance(exc, (ConnectionError, OSError)):
            return "network"

        return "model"
