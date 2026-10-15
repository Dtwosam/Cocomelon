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
        self._events: deque[tuple[float, int, str]] = deque()
        self._used_weight = 0
        self._used_by_origin = {"required": 0, "shadow": 0, "other": 0}
        self._peak_total_weight = 0
        self._peak_required_weight = 0
        self._peak_shadow_weight = 0
        self._shadow_denied_lifetime = 0
        self._shadow_admitted_lifetime = 0
        self._lock = Lock()

    @property
    def used_weight(self) -> int:
        with self._lock:
            self._purge(self._monotonic())
            return self._used_weight

    @property
    def limit(self) -> int:
        return self._limit

    def try_acquire(
        self, weight: int, *,
        reserve_remaining: int = 0,
        origin: str = "other",
    ) -> bool:
        """Atomically reserve weight or return False; NEVER sleep or retry.

        A low-priority observer must call this rather than block the trading
        worker. Reservations are charged even if the ensuing HTTP read fails.
        """
        self._validate(weight)
        if isinstance(reserve_remaining, bool) or reserve_remaining < 0:
            raise ValueError("reserve_remaining must be nonnegative")
        if origin not in {"other", "shadow"}:
            raise ValueError("nonblocking request origin must be shadow or other")
        with self._lock:
            now = self._monotonic()
            self._purge(now)
            if self._used_weight + weight + reserve_remaining > self._limit:
                if origin == "shadow":
                    self._shadow_denied_lifetime += 1
                return False
            self._record(now, weight, origin)
            if origin == "shadow":
                self._shadow_admitted_lifetime += 1
            return True

    def acquire(self, weight: int) -> None:
        """Retain blocking semantics for existing required public-info reads."""
        self._validate(weight)
        while True:
            with self._lock:
                now = self._monotonic()
                self._purge(now)
                if self._used_weight + weight <= self._limit:
                    self._record(now, weight, "required")
                    return
                oldest_at, _, _ = self._events[0]
                wait_seconds = max(0.0, oldest_at + self._window_seconds - now)
            # NEVER hold the lock across the sleep. In-flight observations
            # may still release slots and mandatory worker reads may proceed.
            self._sleep(wait_seconds)

    def snapshot(self) -> dict[str, int | bool]:
        """Read-only, atomic in-process rolling ledger and observed peaks.

        This accounts ONLY for this ledger's own callers, not co-located
        processes or other jobs sharing the venue public egress IP.
        """
        with self._lock:
            self._purge(self._monotonic())
            return {
                "rolling_window_seconds": round(self._window_seconds),
                "rolling_weight_limit": self._limit,
                "total_rolling_weight": self._used_weight,
                "required_rolling_weight": self._used_by_origin["required"],
                "shadow_rolling_weight": self._used_by_origin["shadow"],
                "other_rolling_weight": self._used_by_origin["other"],
                "peak_total_rolling_weight": self._peak_total_weight,
                "peak_required_rolling_weight": self._peak_required_weight,
                "peak_shadow_rolling_weight": self._peak_shadow_weight,
                "shadow_admitted_lifetime": self._shadow_admitted_lifetime,
                "shadow_denied_lifetime": self._shadow_denied_lifetime,
                "external_process_ip_weight_verified": False,
                "source_or_execution_authority": False,
            }

    def _record(self, now: float, weight: int, origin: str) -> None:
        self._events.append((now, weight, origin))
        self._used_weight += weight
        self._used_by_origin[origin] += weight
        self._peak_total_weight = max(self._peak_total_weight, self._used_weight)
        self._peak_required_weight = max(
            self._peak_required_weight, self._used_by_origin["required"]
        )
        self._peak_shadow_weight = max(
            self._peak_shadow_weight, self._used_by_origin["shadow"]
        )

    def _validate(self, weight: int) -> None:
        if weight <= 0:
            raise ValueError("weight must be positive")
        if weight > self._limit:
            raise ValueError("single request weight exceeds rolling budget limit")

    def _purge(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._events and self._events[0][0] <= cutoff:
            _, weight, origin = self._events.popleft()
            self._used_weight -= weight
            self._used_by_origin[origin] -= weight
