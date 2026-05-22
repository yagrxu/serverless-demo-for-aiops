"""Persona management and seeded RNG for deterministic traffic generation."""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from .config import PersonaSpec, Scenario


@dataclass(frozen=True)
class Persona:
    """A resolved persona instance with a deterministic session_id."""
    persona_id: str
    session_id: str
    cat_ids: list[str]
    device_ids: list[str]
    locale: str


class PersonaPool:
    """Pool of personas constructed from specs with a seeded RNG."""

    def __init__(self, specs: list[PersonaSpec], seed: int) -> None:
        self._rng = random.Random(seed)
        self._personas: dict[str, Persona] = {}
        for spec in specs:
            # Deterministic session_id from persona id + seed
            raw = f"{spec.id}:{seed}"
            session_id = hashlib.sha256(raw.encode()).hexdigest()[:16]
            self._personas[spec.id] = Persona(
                persona_id=spec.id,
                session_id=session_id,
                cat_ids=list(spec.cat_ids),
                device_ids=list(spec.device_ids),
                locale=spec.locale,
            )

    def get(self, persona_id: str) -> Persona:
        """Get a persona by id."""
        return self._personas[persona_id]

    def pick(self, scenario: Scenario) -> Persona:
        """Pick a random persona from the scenario's allowed list."""
        choice = self._rng.choice(scenario.allowed_personas)
        return self._personas[choice]
