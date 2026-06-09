"""Prompt loader with versioning, canary routing, and SSM support.

Two-tier design:
- Local dev: reads prompts.json (Omni-compatible, versions inline)
- Production: reads from SSM Parameter Store (manifest + versioned prompt)

The loader supports canary traffic splitting via session-hash routing.
OTel span attributes track which prompt version served each request.
"""

import json
import os
import time
from pathlib import Path
from contextvars import ContextVar

try:
    from opentelemetry.sdk.trace import SpanProcessor
except ImportError:
    class SpanProcessor:  # type: ignore[no-redef]
        def on_start(self, span, parent_context=None): pass
        def on_end(self, span): pass
        def shutdown(self): pass
        def force_flush(self, timeout_millis=None): pass

PROMPT_SOURCE = os.environ.get("PROMPT_SOURCE", "local")  # "local" or "ssm"
SSM_PREFIX = os.environ.get("SSM_PROMPT_PREFIX", "/aiops-cat-demo/prompts")
SSM_TTL_SECONDS = int(os.environ.get("SSM_PROMPT_TTL", "300"))

_file_cache = None
_file_cache_mtime = 0.0
_ssm_cache: dict = {}
_ssm_cache_time: float = 0.0
_active: ContextVar[tuple[str, str] | None] = ContextVar("active", default=None)


# ---------------------------------------------------------------------------
# Local file loader (Omni-compatible)
# ---------------------------------------------------------------------------

def _load_file():
    global _file_cache, _file_cache_mtime
    override = os.environ.get("OMNI_PROMPTS_OVERRIDE")
    p = Path(override) if override else Path(__file__).parent / "prompts.json"
    if p.exists():
        mtime = p.stat().st_mtime
        if _file_cache is None or mtime != _file_cache_mtime:
            _file_cache = json.loads(p.read_text())
            _file_cache_mtime = mtime
    elif _file_cache is None:
        _file_cache = {}
    return _file_cache


def _get_prompt_local(name: str, session_id: str = "", version: int | None = None) -> tuple[str, str]:
    """Load prompt from local prompts.json with version/canary support."""
    data = _load_file().get(name, {})

    # New format with explicit versions
    if "versions" in data:
        active = data.get("active", {})

        if version is not None:
            # Explicit version override
            ver_data = data["versions"].get(str(version), {})
            ver_label = f"v{version}"
        elif active.get("canary") and session_id:
            canary = active["canary"]
            canary_ver = canary["version"] if isinstance(canary, dict) else canary
            canary_weight = canary.get("weight", 20) if isinstance(canary, dict) else 20
            if _in_canary_cohort(session_id, canary_weight):
                ver_data = data["versions"].get(str(canary_ver), {})
                ver_label = f"v{canary_ver}-canary"
            else:
                stable_ver = active.get("stable", 1)
                ver_data = data["versions"].get(str(stable_ver), {})
                ver_label = f"v{stable_ver}-stable"
        else:
            stable_ver = active.get("stable", 1)
            ver_data = data["versions"].get(str(stable_ver), {})
            ver_label = f"v{stable_ver}-stable"

        msgs = ver_data.get("messages", [])
        prompt_text = next((m["content"] for m in msgs if m["role"] == "system"), "")
        return prompt_text, ver_label

    # Legacy format (flat messages + history) — backwards compatible with Omni
    msgs = data.get("messages", [])
    history = data.get("history", [])
    if history:
        ver_id = history[-1].get("versionId", f"{name}-v{len(history)}")
        latest_msgs = history[-1].get("messages")
        if latest_msgs is not None:
            compare_msgs = data.get("_templateMessages", msgs)
            def _normalize(m):
                return [(x.get("role"), x.get("content")) for x in m]
            if _normalize(compare_msgs) != _normalize(latest_msgs):
                ver_id += "-draft"
    else:
        ver_id = f"{name}-v1"

    prompt_text = next((m["content"] for m in msgs if m["role"] == "system"), "")
    return prompt_text, ver_id


# ---------------------------------------------------------------------------
# SSM loader (production)
# ---------------------------------------------------------------------------

def _get_ssm_client():
    import boto3
    return boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _load_ssm_manifest(agent_name: str) -> dict:
    """Load manifest from SSM with TTL caching."""
    global _ssm_cache, _ssm_cache_time
    cache_key = f"manifest:{agent_name}"
    now = time.time()

    if cache_key in _ssm_cache and (now - _ssm_cache_time) < SSM_TTL_SECONDS:
        return _ssm_cache[cache_key]

    ssm = _get_ssm_client()
    param_name = f"{SSM_PREFIX}/{agent_name}/manifest"
    try:
        resp = ssm.get_parameter(Name=param_name)
        manifest = json.loads(resp["Parameter"]["Value"])
    except Exception:
        manifest = {"stable": 1, "canary": None, "previous": None}

    _ssm_cache[cache_key] = manifest
    _ssm_cache_time = now
    return manifest


def _load_ssm_prompt_version(agent_name: str, version: int) -> str:
    """Load a specific prompt version from SSM."""
    cache_key = f"prompt:{agent_name}:v{version}"
    if cache_key in _ssm_cache:
        return _ssm_cache[cache_key]

    ssm = _get_ssm_client()
    param_name = f"{SSM_PREFIX}/{agent_name}/system:{version}"
    try:
        resp = ssm.get_parameter(Name=param_name)
        text = resp["Parameter"]["Value"]
    except Exception:
        # Fallback: try without version suffix (get latest)
        try:
            resp = ssm.get_parameter(Name=f"{SSM_PREFIX}/{agent_name}/system")
            text = resp["Parameter"]["Value"]
        except Exception:
            text = ""

    _ssm_cache[cache_key] = text
    return text


def _get_prompt_ssm(agent_name: str, session_id: str = "", version: int | None = None) -> tuple[str, str]:
    """Load prompt from SSM with manifest-based routing."""
    manifest = _load_ssm_manifest(agent_name)

    if version is not None:
        prompt_text = _load_ssm_prompt_version(agent_name, version)
        return prompt_text, f"v{version}"

    canary = manifest.get("canary")
    if canary and session_id:
        canary_ver = canary["version"] if isinstance(canary, dict) else canary
        canary_weight = canary.get("weight", 20) if isinstance(canary, dict) else 20
        if _in_canary_cohort(session_id, canary_weight):
            prompt_text = _load_ssm_prompt_version(agent_name, canary_ver)
            return prompt_text, f"v{canary_ver}-canary"

    stable_ver = manifest.get("stable", 1)
    prompt_text = _load_ssm_prompt_version(agent_name, stable_ver)
    return prompt_text, f"v{stable_ver}-stable"


# ---------------------------------------------------------------------------
# Canary routing
# ---------------------------------------------------------------------------

def _in_canary_cohort(session_id: str, weight: int) -> bool:
    """Deterministic routing: same session always gets same version."""
    return (hash(session_id) % 100) < weight


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_prompt(name: str, session_id: str = "", version: int | None = None) -> str:
    """Load prompt text for the given name, with canary/version routing.

    Args:
        name: Prompt identifier (e.g., "cat_care_assistant")
        session_id: Used for deterministic canary routing
        version: Explicit version override (bypasses canary logic)

    Returns:
        Prompt text string. Also sets OTel span attributes via _active context var.
    """
    if PROMPT_SOURCE == "ssm":
        agent_name = _infer_agent_name()
        prompt_text, ver_label = _get_prompt_ssm(agent_name, session_id, version)
    else:
        prompt_text, ver_label = _get_prompt_local(name, session_id, version)

    # Set context for OmniPromptProcessor to read
    _active.set((prompt_text[:500], ver_label))

    # Fallback if nothing loaded
    if not prompt_text:
        prompt_text, ver_label = _get_prompt_local(name, session_id, version)
        _active.set((prompt_text[:500], ver_label))

    return prompt_text


def get_model_config(name: str) -> dict | None:
    """Returns model config from local prompts.json."""
    data = _load_file().get(name, {})
    return data.get("model")


def _infer_agent_name() -> str:
    """Infer agent name from the directory containing this file."""
    return Path(__file__).parent.name


# ---------------------------------------------------------------------------
# OTel Span Processor — tags spans with prompt version
# ---------------------------------------------------------------------------

class OmniPromptProcessor(SpanProcessor):
    def on_start(self, span, parent_context=None):
        if (p := _active.get()) and span.is_recording():
            span.set_attribute("llm.prompt_template.template", p[0])
            span.set_attribute("llm.prompt_template.version", p[1])
    def on_end(self, span): pass
    def shutdown(self): pass
    def force_flush(self, timeout_millis=None): pass
