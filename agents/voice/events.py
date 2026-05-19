"""Nova Sonic input/output event builders and parsers.

Copied from reference/nova-sonic-demo/events.py — no import changes needed
since this module is self-contained.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Literal, Union


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_INFERENCE_CONFIG: dict = {
    "maxTokens": 1024,
    "topP": 0.9,
    "temperature": 0.7,
}


# ---------------------------------------------------------------------------
# Input event builders
# ---------------------------------------------------------------------------


def session_start_event(inference_config: dict | None = None) -> dict:
    config = inference_config if inference_config is not None else DEFAULT_INFERENCE_CONFIG
    return {
        "event": {
            "sessionStart": {
                "inferenceConfiguration": config,
            }
        }
    }


def prompt_start_event(
    prompt_name: str,
    tool_config: dict,
    system_prompt: str | None = None,
) -> dict:
    inner: dict[str, Any] = {
        "promptName": prompt_name,
        "textOutputConfiguration": {"mediaType": "text/plain"},
        "audioOutputConfiguration": {
            "mediaType": "audio/lpcm",
            "sampleRateHertz": 24000,
            "sampleSizeBits": 16,
            "channelCount": 1,
            "voiceId": "matthew",
            "encoding": "base64",
            "audioType": "SPEECH",
        },
        "toolUseOutputConfiguration": {"mediaType": "application/json"},
        "toolConfiguration": tool_config,
    }
    if system_prompt:
        inner["system"] = system_prompt
    return {"event": {"promptStart": inner}}


def content_start_audio_input_event(prompt_name: str, content_name: str) -> dict:
    return {
        "event": {
            "contentStart": {
                "promptName": prompt_name,
                "contentName": content_name,
                "type": "AUDIO",
                "interactive": True,
                "role": "USER",
                "audioInputConfiguration": {
                    "mediaType": "audio/lpcm",
                    "sampleRateHertz": 16000,
                    "sampleSizeBits": 16,
                    "channelCount": 1,
                    "audioType": "SPEECH",
                    "encoding": "base64",
                },
            }
        }
    }


def audio_input_event(prompt_name: str, content_name: str, audio_b64: str) -> dict:
    return {
        "event": {
            "audioInput": {
                "promptName": prompt_name,
                "contentName": content_name,
                "content": audio_b64,
            }
        }
    }


def content_end_event(prompt_name: str, content_name: str) -> dict:
    return {
        "event": {
            "contentEnd": {
                "promptName": prompt_name,
                "contentName": content_name,
            }
        }
    }


def prompt_end_event(prompt_name: str) -> dict:
    return {"event": {"promptEnd": {"promptName": prompt_name}}}


def session_end_event() -> dict:
    return {"event": {"sessionEnd": {}}}


# ---------------------------------------------------------------------------
# Text input helpers
# ---------------------------------------------------------------------------


def content_start_text_input_event(
    prompt_name: str,
    content_name: str,
    role: Literal["SYSTEM", "USER"] = "SYSTEM",
) -> dict:
    return {
        "event": {
            "contentStart": {
                "promptName": prompt_name,
                "contentName": content_name,
                "type": "TEXT",
                "interactive": False,
                "role": role,
                "textInputConfiguration": {"mediaType": "text/plain"},
            }
        }
    }


def text_input_event(prompt_name: str, content_name: str, content: str) -> dict:
    return {
        "event": {
            "textInput": {
                "promptName": prompt_name,
                "contentName": content_name,
                "content": content,
            }
        }
    }


# ---------------------------------------------------------------------------
# Tool-result helpers
# ---------------------------------------------------------------------------


def content_start_tool_result_event(
    prompt_name: str,
    content_name: str,
    tool_use_id: str,
) -> dict:
    return {
        "event": {
            "contentStart": {
                "promptName": prompt_name,
                "contentName": content_name,
                "interactive": False,
                "type": "TOOL",
                "role": "TOOL",
                "toolResultInputConfiguration": {
                    "toolUseId": tool_use_id,
                    "type": "TEXT",
                    "textInputConfiguration": {"mediaType": "text/plain"},
                },
            }
        }
    }


def tool_result_event(prompt_name: str, content_name: str, content_json: str) -> dict:
    return {
        "event": {
            "toolResult": {
                "promptName": prompt_name,
                "contentName": content_name,
                "content": content_json,
            }
        }
    }


# ---------------------------------------------------------------------------
# Output event parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudioOutEvent:
    pcm: bytes


@dataclass(frozen=True)
class TranscriptEvent:
    role: Literal["USER", "ASSISTANT"]
    text: str
    is_final: bool


@dataclass(frozen=True)
class ToolUseEvent:
    tool_use_id: str
    tool_name: str
    arguments: dict


OutputEvent = Union[AudioOutEvent, TranscriptEvent, ToolUseEvent]


def _unwrap(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    if "event" in raw and isinstance(raw["event"], dict):
        return raw["event"]
    return raw


def _parse_audio_output(payload: dict) -> AudioOutEvent | None:
    content = payload.get("content")
    if not isinstance(content, str):
        return None
    try:
        pcm = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError):
        return None
    return AudioOutEvent(pcm=pcm)


def _parse_text_output(payload: dict) -> TranscriptEvent | None:
    role = payload.get("role")
    text = payload.get("content")
    if role not in ("USER", "ASSISTANT"):
        return None
    if not isinstance(text, str):
        return None
    return TranscriptEvent(role=role, text=text, is_final=True)


def _parse_tool_use(payload: dict) -> ToolUseEvent | None:
    tool_use_id = payload.get("toolUseId")
    tool_name = payload.get("toolName")
    if not isinstance(tool_use_id, str) or not isinstance(tool_name, str):
        return None
    raw_input = payload.get("content")
    if raw_input is None:
        raw_input = payload.get("input")
    if raw_input is None:
        raw_input = payload.get("arguments")

    if isinstance(raw_input, dict):
        arguments = raw_input
    elif isinstance(raw_input, str):
        try:
            arguments = json.loads(raw_input)
        except (ValueError, TypeError):
            return None
    else:
        return None

    if not isinstance(arguments, dict):
        return None
    return ToolUseEvent(
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        arguments=arguments,
    )


def parse_output_event(raw: dict) -> OutputEvent | None:
    """Parse a Nova Sonic output event into a typed dataclass. Returns None for unknown events."""
    try:
        inner = _unwrap(raw)
        if not isinstance(inner, dict):
            return None

        if "audioOutput" in inner:
            payload = inner["audioOutput"]
            if not isinstance(payload, dict):
                return None
            return _parse_audio_output(payload)

        if "textOutput" in inner:
            payload = inner["textOutput"]
            if not isinstance(payload, dict):
                return None
            return _parse_text_output(payload)

        if "toolUse" in inner:
            payload = inner["toolUse"]
            if not isinstance(payload, dict):
                return None
            return _parse_tool_use(payload)

        return None
    except Exception:
        return None
