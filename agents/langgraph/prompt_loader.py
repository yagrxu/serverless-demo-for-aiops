import json
import os
from pathlib import Path
from contextvars import ContextVar
try:
    from opentelemetry.sdk.trace import SpanProcessor
except ImportError:
    # Allow running without opentelemetry (e.g., in CI tests)
    class SpanProcessor:  # type: ignore[no-redef]
        def on_start(self, span, parent_context=None): pass
        def on_end(self, span): pass
        def shutdown(self): pass
        def force_flush(self, timeout_millis=None): pass

_cache = None
_cache_mtime = 0
_active: ContextVar[tuple[str, str] | None] = ContextVar("active", default=None)

def _load():
    global _cache, _cache_mtime
    override = os.environ.get("OMNI_PROMPTS_OVERRIDE")
    if override:
        p = Path(override)
    else:
        p = Path(__file__).parent / "prompts.json"
    if p.exists():
        mtime = p.stat().st_mtime
        if _cache is None or mtime != _cache_mtime:
            _cache = json.loads(p.read_text())
            _cache_mtime = mtime
    elif _cache is None:
        _cache = {}
    return _cache

def get_prompt(name: str) -> str:
    data = _load().get(name, {})
    msgs = data.get("messages", [])
    history = data.get("history", [])
    tpl = "\n".join(f"[{m['role']}]: {m['content']}" for m in msgs)
    if history:
        ver_id = history[-1].get("versionId", f"{name}-v{len(history)}")
        latest_msgs = history[-1].get("messages")
        if latest_msgs is not None:
            compare_msgs = data.get("_templateMessages", msgs)
            def normalize(m):
                return [(x.get("role"), x.get("content")) for x in m]
            if normalize(compare_msgs) != normalize(latest_msgs):
                ver_id += "-draft"
    else:
        ver_id = f"{name}-v1"
    _active.set((tpl, ver_id))
    return next((m["content"] for m in msgs if m["role"] == "system"), "")

def get_model_config(name: str) -> dict | None:
    """Returns model config: {"providerId": "...", "modelId": "...", "parameters": {...}} or None."""
    data = _load().get(name, {})
    return data.get("model")

class OmniPromptProcessor(SpanProcessor):
    def on_start(self, span, parent_context=None):
        if (p := _active.get()) and span.is_recording():
            span.set_attribute("llm.prompt_template.template", p[0])
            span.set_attribute("llm.prompt_template.version", p[1])
    def on_end(self, span): pass
    def shutdown(self): pass
    def force_flush(self, timeout_millis=None): pass
