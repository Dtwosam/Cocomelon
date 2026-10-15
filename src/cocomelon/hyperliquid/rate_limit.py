from __future__ import annotations

from collections import deque
from collections.abc import Callable
from threading import Lock
from time import monotonic, sleep


class RollingRateBudget:
    """Thread-safe per-process rolling request-weight limit.

    All clients that share a public IP must be given the SAME budget object to
    share this ledger. This does not observe requests in other processes or on
    other machines behind the same NAT, and cannot certify venue-wide quota.
    """

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
        self._lock = Lock()

    @property
    def used_weight(self) -> int:
        with self._lock:
            self._purge(self._monotonic())
            return self._used_weight

    @property
    def limit(self) -> int:
        return self._limit

    def try_acquire(self, weight: int) -> bool:
        """Atomically reserve weight or return False; NEVER sleep or retry.

        A low-priority observer must call this rather than block the trading
        worker. Reservations are charged even if the ensuing HTTP read fails.
        """
        self._validate(weight)
        with self._lock:
            now = self._monotonic()
            self._purge(now)
            if self._used_weight + weight > self._limit:
                return False
            self._events.append((now, weight))
            self._used_weight += weight
            return True

    def acquire(self, weight: int) -> None:
        """Retain blocking semantics for existing required public-info reads."""
        self._validate(weight)
        while True:
            with self._lock:
                now = self._monotonic()
                self._purge(now)
                if self._used_weight + weight <= self._limit:
                    self._events.append((now, weight))
                    self._used_weight += weight
                    return
                oldest_at, _ = self._events[0]
                wait_seconds = max(0.0, oldest_at + self._window_seconds - now)
            # NEVER hold the lock across the sleep. In-flight observations
            # may still release slots and mandatory worker reads may proceed.
            self._sleep(wait_seconds)

    def _validate(self, weight: int) -> None:
        if weight <= 0:
            raise ValueError("weight must be positive")
        if weight > self._limit:
            raise ValueError("single request weight exceeds rolling budget limit")

    def _purge(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._events and self._events[0][0] <= cutoff:
            _, weight = self._events.popleft()
            self._used_weight -= weight
