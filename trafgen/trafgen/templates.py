"""Template resolution and prompt rendering.

Resolves ${persona.X}, ${now}, ${last.X}, and inline sample directives in
scenario step arguments. Also renders agent prompts with persona-specific values.
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from typing import Any

from .config import SampleDirective
from .personas import Persona
from .sampling import weighted_pick


class TemplateError(Exception):
    """Raised when a template reference cannot be resolved."""


def render_prompt(template: str, persona: Persona, rng: random.Random) -> str:
    """Render an agent prompt template with persona-specific values.

    Substitutes {cat_name} with the persona's first cat_id (or "unknown").
    """
    cat_name = persona.cat_ids[0] if persona.cat_ids else "unknown"
    return template.replace("{cat_name}", cat_name)


def select_prompt(prompts: list[str], persona: Persona, rng: random.Random) -> str:
    """Select and render a prompt from a list using uniform weights."""
    if not prompts:
        raise TemplateError("No prompts available")
    # Uniform weight selection
    template = weighted_pick(prompts, by=lambda _: 1.0, rng=rng)
    return render_prompt(template, persona, rng)


def resolve_templates(
    value: Any,
    persona: Persona,
    last_result: dict[str, Any] | None,
    rng: random.Random,
) -> Any:
    """Resolve template directives in a step body/params value.

    Handles:
    - ${persona.X} — persona field access (cat_ids[0], device_ids[0], etc.)
    - ${last.X} — access to previous step's response
    - {sample: {dist: ...}} — inline sampling directives
    - Plain values pass through unchanged
    """
    if value is None:
        return None

    if isinstance(value, dict):
        # Check if this is a sample directive
        if "sample" in value and isinstance(value["sample"], dict):
            return _resolve_sample(value["sample"], rng)
        # Recursively resolve dict values
        return {k: resolve_templates(v, persona, last_result, rng) for k, v in value.items()}

    if isinstance(value, list):
        return [resolve_templates(item, persona, last_result, rng) for item in value]

    if isinstance(value, str):
        return _resolve_string(value, persona, last_result, rng)

    # Numbers, booleans, etc. pass through
    return value


def _resolve_string(
    s: str,
    persona: Persona,
    last_result: dict[str, Any] | None,
    rng: random.Random,
) -> Any:
    """Resolve template references in a string value."""
    # Check for ${...} patterns
    pattern = re.compile(r"\$\{([^}]+)\}")

    def replacer(match: re.Match) -> str:
        expr = match.group(1)

        # ${persona.X} references
        if expr.startswith("persona."):
            return _resolve_persona_ref(expr[8:], persona)

        # ${last.X} references
        if expr.startswith("last."):
            if last_result is None:
                raise TemplateError(f"No previous result for reference: ${{{expr}}}")
            key = expr[5:]
            if key in last_result:
                return str(last_result[key])
            raise TemplateError(f"Key '{key}' not found in last result")

        # ${now} reference
        if expr == "now":
            return datetime.now(timezone.utc).isoformat()

        raise TemplateError(f"Unresolved template reference: ${{{expr}}}")

    result = pattern.sub(replacer, s)
    return result


def _resolve_persona_ref(ref: str, persona: Persona) -> str:
    """Resolve a persona field reference like cat_ids[0], device_ids[0]."""
    # Handle indexed access: cat_ids[0], device_ids[1]
    idx_match = re.match(r"(\w+)\[(\d+)\]", ref)
    if idx_match:
        field_name = idx_match.group(1)
        index = int(idx_match.group(2))
        field_val = _get_persona_field(field_name, persona)
        if isinstance(field_val, list):
            if index < len(field_val):
                return str(field_val[index])
            raise TemplateError(
                f"Index {index} out of range for persona.{field_name} "
                f"(length {len(field_val)})"
            )
        raise TemplateError(f"persona.{field_name} is not a list")

    # Simple field access
    field_val = _get_persona_field(ref, persona)
    if isinstance(field_val, list):
        return str(field_val[0]) if field_val else ""
    return str(field_val)


def _get_persona_field(field_name: str, persona: Persona) -> Any:
    """Get a field value from a Persona."""
    if field_name == "cat_ids":
        return persona.cat_ids
    elif field_name == "device_ids":
        return persona.device_ids
    elif field_name == "persona_id":
        return persona.persona_id
    elif field_name == "session_id":
        return persona.session_id
    elif field_name == "locale":
        return persona.locale
    else:
        raise TemplateError(f"Unknown persona field: {field_name}")


def _resolve_sample(sample_spec: dict[str, Any], rng: random.Random) -> Any:
    """Resolve an inline sample directive."""
    directive = SampleDirective.model_validate(sample_spec)

    if directive.dist == "uniform":
        return rng.uniform(directive.min, directive.max)  # type: ignore[arg-type]
    elif directive.dist == "normal":
        val = rng.gauss(directive.mean, directive.std)  # type: ignore[arg-type]
        # Clip to min/max if provided
        if directive.min is not None:
            val = max(directive.min, val)
        if directive.max is not None:
            val = min(directive.max, val)
        return val
    elif directive.dist == "choices":
        choices = directive.choices  # type: ignore[assignment]
        if directive.weights:
            # Weighted choice
            total = sum(directive.weights)
            r = rng.random() * total
            cumulative = 0.0
            for choice, weight in zip(choices, directive.weights):
                cumulative += weight
                if r <= cumulative:
                    return choice
            return choices[-1]
        else:
            return rng.choice(choices)
    else:
        raise TemplateError(f"Unknown sample distribution: {directive.dist}")
