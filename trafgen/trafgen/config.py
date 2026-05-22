"""Profile schema and validation for trafgen."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, field_validator, model_validator

PERSONA_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class SampleDirective(BaseModel):
    """Inline sampling directive for dynamic values."""
    dist: Literal["uniform", "normal", "choices"]
    # uniform
    min: float | None = None
    max: float | None = None
    # normal
    mean: float | None = None
    std: float | None = None
    # choices
    choices: list[Any] | None = None
    weights: list[float] | None = None

    @model_validator(mode="after")
    def validate_params(self):
        if self.dist == "uniform":
            if self.min is None or self.max is None:
                raise ValueError("uniform requires min and max")
            if self.min > self.max:
                raise ValueError("min must be <= max")
        elif self.dist == "normal":
            if self.mean is None or self.std is None:
                raise ValueError("normal requires mean and std")
        elif self.dist == "choices":
            if not self.choices:
                raise ValueError("choices requires a non-empty choices list")
            if self.weights and len(self.weights) != len(self.choices):
                raise ValueError("weights length must match choices length")
        return self


class ScenarioStep(BaseModel):
    """One step in a REST scenario."""
    call: str
    path_params: dict[str, Any] | None = None
    query_params: dict[str, Any] | None = None
    body: dict[str, Any] | None = None


class Scenario(BaseModel):
    """A traffic scenario definition."""
    id: str
    surface: Literal["rest", "agent"]
    weight: float = 1.0
    allowed_personas: list[str]
    # REST scenarios
    steps: list[ScenarioStep] | None = None
    # Agent scenarios
    via: Literal["chatbot", "langgraph_direct", "strands_direct"] | None = None
    prompts: list[str] | None = None

    @field_validator("weight")
    @classmethod
    def weight_non_negative(cls, v):
        if v < 0:
            raise ValueError("weight must be >= 0")
        return v

    @model_validator(mode="after")
    def validate_surface_fields(self):
        if self.surface == "rest" and not self.steps:
            raise ValueError("REST scenarios require steps")
        if self.surface == "agent":
            if not self.via:
                raise ValueError("agent scenarios require via")
            if not self.prompts:
                raise ValueError("agent scenarios require prompts")
        return self


class PersonaSpec(BaseModel):
    """A persona definition."""
    id: str
    cat_ids: list[str] = []
    device_ids: list[str] = []
    locale: str = "en-US"

    @field_validator("id")
    @classmethod
    def validate_id(cls, v):
        if not PERSONA_ID_PATTERN.match(v):
            raise ValueError(f"persona id must match {PERSONA_ID_PATTERN.pattern}")
        return v


class Defaults(BaseModel):
    """Default run parameters."""
    rps: float = 1.0
    duration: str = "55m"
    seed: int = 42


class Profile(BaseModel):
    """Top-level traffic profile."""
    defaults: Defaults = Defaults()
    personas: list[PersonaSpec]
    scenarios: list[Scenario]

    @model_validator(mode="after")
    def validate_references(self):
        persona_ids = {p.id for p in self.personas}
        # Check uniqueness
        if len(persona_ids) != len(self.personas):
            raise ValueError("persona ids must be unique")
        # Check scenario references
        for scenario in self.scenarios:
            for pid in scenario.allowed_personas:
                if pid not in persona_ids:
                    raise ValueError(f"scenario '{scenario.id}' references unknown persona '{pid}'")
        # Check sum of weights > 0
        total_weight = sum(s.weight for s in self.scenarios)
        if total_weight <= 0:
            raise ValueError("sum of scenario weights must be > 0")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> "Profile":
        """Load and validate a profile from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    def persona(self, persona_id: str) -> PersonaSpec:
        """Look up a persona by id."""
        for p in self.personas:
            if p.id == persona_id:
                return p
        raise KeyError(f"persona '{persona_id}' not found")
