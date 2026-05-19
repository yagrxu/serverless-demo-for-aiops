"""Voice agent server — FastAPI app with WebSocket endpoint for Nova Sonic.

Integrates Nova Sonic bidirectional audio streaming with MCP tools from
the cat-care MCP Server at localhost:8083.

Run with:
    uvicorn server:app --host 0.0.0.0 --port 8084
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

from config import (
    SHUTDOWN_DEADLINE_S,
    BedrockOpenError,
    MissingCredentialsError,
    UnsupportedRegionError,
    assert_credentials_resolvable,
    resolve_region,
    validate_region,
)
from events import AudioOutEvent, TranscriptEvent
from logger import WebLogger
from mcp_tools import MCPToolDispatcher, MCPToolRegistry
from messages import (
    ErrorMessage,
    StatusMessage,
    ToolCallMessage,
    ToolResultMessage,
    TranscriptMessage,
    parse_client_command,
    serialize_server_message,
    StartCommand,
    StopCommand,
    validate_audio_bytes,
)
from session import SonicSession

logger = logging.getLogger("voice_agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8083/mcp")

SYSTEM_PROMPT = (
    "You are a friendly cat-care voice assistant. You help users manage their "
    "cats' feeding schedules, health monitoring, and IoT devices (feeders, "
    "fountains, trackers). Use the available tools to look up real data before "
    "answering. Be concise and conversational — keep responses to one or two "
    "sentences since this is a voice interface. When the user refers to a cat "
    "by name, resolve it to a cat_id first before calling other tools."
)

# Session state type
SessionState = Literal["ready", "connecting", "active", "error", "closed"]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Cat-Care Voice Agent")

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "ok"}, status_code=200)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    index_path = _STATIC_DIR / "index.html"
    html_content = index_path.read_text(encoding="utf-8")
    return HTMLResponse(content=html_content)


# ---------------------------------------------------------------------------
# Session Manager (inline — simplified from the demo's separate file)
# ---------------------------------------------------------------------------


class VoiceSessionManager:
    """Manages the lifecycle of a SonicSession bound to a WebSocket."""

    def __init__(
        self,
        send_text,
        send_bytes,
        mcp_url: str = MCP_SERVER_URL,
    ) -> None:
        self._send_text = send_text
        self._send_bytes = send_bytes
        self._mcp_url = mcp_url
        self._state: SessionState = "ready"
        self._session: SonicSession | None = None
        self._logger: WebLogger | None = None

    @property
    def state(self) -> SessionState:
        return self._state

    async def _transition(self, new_state: SessionState) -> None:
        self._state = new_state
        msg = serialize_server_message(StatusMessage(state=new_state))
        await self._send_text(msg)

    async def _send_error(self, message: str) -> None:
        error_msg = serialize_server_message(ErrorMessage(message=message))
        await self._send_text(error_msg)
        await self._transition("error")

    async def start(self) -> None:
        if self._state not in ("ready", "error"):
            return

        await self._transition("connecting")

        # 1. Resolve credentials
        try:
            assert_credentials_resolvable()
            logger.info("Credentials resolved OK")
        except MissingCredentialsError:
            logger.error("Missing AWS credentials")
            await self._send_error(
                "AWS credentials are not configured. Please set "
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY or "
                "configure a default profile."
            )
            return

        # 2. Resolve and validate region
        try:
            region = resolve_region()
            validate_region(region)
            logger.info("Region resolved: %s", region)
        except UnsupportedRegionError as exc:
            logger.error("Unsupported region: %s", exc)
            await self._send_error(str(exc))
            return

        # 3. Load MCP tools
        registry = MCPToolRegistry(mcp_url=self._mcp_url)
        await registry.load()
        logger.info("MCP tools loaded: %s", registry.names())

        # 4. Create WebLogger
        async def _logger_send_fn(payload: dict) -> None:
            msg = serialize_server_message(_dict_to_server_message(payload))
            await self._send_text(msg)

        self._logger = WebLogger(_logger_send_fn)

        # 5. Create dispatcher
        dispatcher = MCPToolDispatcher(
            registry=registry,
            logger_instance=self._logger,
            mcp_url=self._mcp_url,
        )

        # 6. Create session
        self._session = SonicSession(
            region=region,
            registry=registry,
            logger=self._logger,
            dispatcher=dispatcher,
            system_prompt=SYSTEM_PROMPT,
        )

        # 7. Open the session
        try:
            logger.info("Opening Bedrock session...")
            await self._session.open()
            logger.info("Bedrock session opened successfully")
        except BedrockOpenError as exc:
            logger.error("Bedrock open failed: %s - %s", exc.category, exc.underlying)
            await self._send_error(
                f"Failed to connect to Bedrock: {exc.category} - {exc.underlying}"
            )
            return

        # 8. Mark active
        self._logger.mark_session_active()
        await self._transition("active")
        logger.info("Session is now ACTIVE")

    async def handle_audio(self, pcm_bytes: bytes) -> None:
        if self._state != "active":
            return
        if not validate_audio_bytes(pcm_bytes):
            return
        if self._session is not None:
            await self._session.send_audio(pcm_bytes)

    async def run_event_loop(self) -> None:
        if self._session is None:
            return

        try:
            async for event in self._session.stream_events():
                if isinstance(event, AudioOutEvent):
                    await self._send_bytes(event.pcm)
                elif isinstance(event, TranscriptEvent):
                    msg = serialize_server_message(
                        TranscriptMessage(role=event.role, text=event.text)
                    )
                    await self._send_text(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._state == "active":
                await self._send_error(
                    f"Session stream error: {type(exc).__name__}: {str(exc)[:200]}"
                )

    async def stop(self) -> None:
        if self._state in ("closed", "ready"):
            return

        if self._logger is not None:
            self._logger.mark_session_closed()

        if self._session is not None:
            try:
                await asyncio.wait_for(
                    self._session.close(), timeout=SHUTDOWN_DEADLINE_S
                )
            except (asyncio.TimeoutError, Exception):
                pass

        self._session = None
        self._logger = None
        await self._transition("ready")


def _dict_to_server_message(payload: dict):
    """Convert a WebLogger dict payload to a ServerMessage."""
    msg_type = payload.get("type")
    if msg_type == "tool_call":
        return ToolCallMessage(
            name=payload.get("name", ""),
            arguments=payload.get("arguments", {}),
        )
    elif msg_type == "tool_result":
        return ToolResultMessage(
            name=payload.get("name", ""),
            result=payload.get("result", {}),
        )
    return ErrorMessage(message=f"Unknown logger event: {msg_type}")


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@app.websocket("/ws/session")
async def websocket_session(ws: WebSocket) -> None:
    """Bidirectional audio + control WebSocket endpoint."""
    await ws.accept()

    async def _send_text(text: str) -> None:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_text(text)

    async def _send_bytes(data: bytes) -> None:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_bytes(data)

    manager = VoiceSessionManager(
        send_text=_send_text,
        send_bytes=_send_bytes,
        mcp_url=MCP_SERVER_URL,
    )

    # Send initial ready status
    await _send_text(serialize_server_message(StatusMessage(state="ready")))

    event_loop_task: asyncio.Task | None = None

    try:
        while True:
            message = await ws.receive()

            if message["type"] == "websocket.receive":
                if "bytes" in message and message["bytes"]:
                    await manager.handle_audio(message["bytes"])
                elif "text" in message and message["text"]:
                    command = parse_client_command(message["text"])
                    if isinstance(command, StartCommand):
                        logger.info("Received START command")
                        await manager.start()
                        if manager.state == "active" and event_loop_task is None:
                            event_loop_task = asyncio.create_task(
                                manager.run_event_loop()
                            )
                    elif isinstance(command, StopCommand):
                        logger.info("Received STOP command")
                        await manager.stop()
                        if event_loop_task is not None:
                            event_loop_task.cancel()
                            try:
                                await event_loop_task
                            except (asyncio.CancelledError, Exception):
                                pass
                            event_loop_task = None
            elif message["type"] == "websocket.disconnect":
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as exc:
        logger.error("WebSocket handler error: %s: %s", type(exc).__name__, exc)
    finally:
        if event_loop_task is not None:
            event_loop_task.cancel()
            try:
                await event_loop_task
            except (asyncio.CancelledError, Exception):
                pass
        await manager.stop()
        logger.info("WebSocket session cleaned up")
