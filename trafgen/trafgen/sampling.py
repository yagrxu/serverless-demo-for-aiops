"""Weighted random sampling utilities."""
from __future__ import annotations

import random
from typing import Callable, Sequence, TypeVar

T = TypeVar("T")


def weighted_pick(
    items: Sequence[T],
    by: Callable[[T], float],
    rng: random.Random,
) -> T:
    """Pick one item with probability proportional to its weight.

    Args:
        items: Non-empty sequence of items.
        by: Function that extracts the weight from an item.
        rng: Seeded random.Random instance for determinism.

    Returns:
        The selected item.

    Raises:
        ValueError: If items is empty or all weights are zero.
    """
    if not items:
        raise ValueError("items must not be empty")

    weights = [by(item) for item in items]
    total = sum(weights)
    if total <= 0:
        raise ValueError("sum of weights must be > 0")

    r = rng.random() * total
    cumulative = 0.0
    for item, weight in zip(items, weights):
        cumulative += weight
        if r <= cumulative:
            return item

    # Fallback (shouldn't reach here due to floating point)
    return items[-1]
