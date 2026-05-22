"""Token bucket rate limiter for pacing traffic generation."""
from __future__ import annotations

import asyncio
import time
from typing import Callable


class TokenBucket:
    """Async token bucket rate limiter.

    Args:
        rate: Tokens per second to refill.
        capacity: Maximum tokens the bucket can hold.
        now_fn: Injectable clock for testing (returns float seconds).
    """

    def __init__(
        self,
        rate: float,
        capacity: int,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._rate = rate
        self._capacity = capacity
        self._now_fn = now_fn or time.monotonic
        self._tokens = float(capacity)
        self._last_refill = self._now_fn()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """Add tokens based on elapsed time."""
        now = self._now_fn()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    async def acquire(self, n: int = 1) -> None:
        """Wait until n tokens are available, then consume them."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= n:
                    self._tokens -= n
                    return
            # Wait a bit before retrying
            wait_time = n / self._rate if self._rate > 0 else 0.1
            await asyncio.sleep(min(wait_time, 0.1))

    @property
    def available(self) -> float:
        """Current available tokens (approximate, no lock)."""
        self._refill()
        return self._tokens
