"""WebSocket message types and validation for the voice agent protocol."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Literal, Optional, Union


# ---------------------------------------------------------------------------
# Server → Browser message types
# ---------------------------------------------------------------------------


@dataclass
class TranscriptMessage:
    role: Literal["USER", "ASSISTANT"]
    text: str
    type: Literal["transcript"] = "transcript"


@dataclass
class ToolCallMessage:
    name: str
    arguments: dict
    type: Literal["tool_call"] = "tool_call"


@dataclass
class ToolResultMessage:
    name: str
    result: dict
    type: Literal["tool_result"] = "tool_result"


@dataclass
class StatusMessage:
    state: Literal["ready", "connecting", "active", "error", "closed"]
    type: Literal["status"] = "status"


@dataclass
class ErrorMessage:
    message: str
    type: Literal["error"] = "error"


ServerMessage = Union[
    TranscriptMessage,
    ToolCallMessage,
    ToolResultMessage,
    StatusMessage,
    ErrorMessage,
]


# ---------------------------------------------------------------------------
# Browser → Server command types
# ---------------------------------------------------------------------------


@dataclass
class StartCommand:
    type: Literal["start"] = "start"


@dataclass
class StopCommand:
    type: Literal["stop"] = "stop"


ClientCommand = Union[StartCommand, StopCommand]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_server_message(msg: ServerMessage) -> str:
    return json.dumps(asdict(msg), separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_client_command(text: str) -> Optional[ClientCommand]:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    msg_type = data.get("type")
    if msg_type == "start":
        return StartCommand()
    elif msg_type == "stop":
        return StopCommand()
    else:
        return None


# ---------------------------------------------------------------------------
# Audio validation
# ---------------------------------------------------------------------------


def validate_audio_bytes(data: bytes) -> bool:
    """Check that binary audio data is valid PCM (16-bit samples)."""
    return len(data) > 0 and len(data) % 2 == 0
