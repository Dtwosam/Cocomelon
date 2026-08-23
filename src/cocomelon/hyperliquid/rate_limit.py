from __future__ import annotations

from collections import deque
from collections.abc import Callable
from time import monotonic, sleep


class RollingRateBudget:
    def __init__(
        self,
        *,
        limit: int = 1000,
        window_seconds: float = 60.0,
        monotonic: Callable[[], float] = monotonic,
        sleep: Callable[[float], None] = sleep,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._limit = limit
        self._window_seconds = window_seconds
        self._monotonic = monotonic
        self._sleep = sleep
        self._events: deque[tuple[float, int]] = deque()
        self._used_weight = 0

    @property
    def used_weight(self) -> int:
        self._purge(self._monotonic())
        return self._used_weight

    def acquire(self, weight: int) -> None:
        if weight <= 0:
            raise ValueError("weight must be positive")
        if weight > self._limit:
            raise ValueError("single request weight exceeds rolling budget limit")

        while True:
            now = self._monotonic()
            self._purge(now)
            if self._used_weight + weight <= self._limit:
                self._events.append((now, weight))
                self._used_weight += weight
                return

            oldest_at, _ = self._events[0]
            wait_seconds = max(0.0, oldest_at + self._window_seconds - now)
            self._sleep(wait_seconds)

    def _purge(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._events and self._events[0][0] <= cutoff:
            _, weight = self._events.popleft()
            self._used_weight -= weight
