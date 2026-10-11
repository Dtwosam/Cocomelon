from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

UTC_DAY_MS: Final = 86_400_000
ZERO: Final = Decimal("0")
METRICS: Final = (
    "baseline_marked",
    "baseline_realized",
    "candidate_marked",
    "candidate_realized",
)


class PairedAccountWindowError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Checkpoint:
    at_ms: int
    amounts: tuple[Decimal, Decimal, Decimal, Decimal]


@dataclass(slots=True)
class PairedAccountUtcWindowLedger:
    """Conservative measured changes between independent account checkpoints.

    A movement whose two observations straddle midnight stays unallocated.
    It must NOT be assigned to the more flattering day. Four separate cash
    series reconcile to actual full-account marked and realized totals.
    """

    started_at_ms: int
    starting_cash: Decimal
    _last: _Checkpoint = field(init=False)
    _by_day: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = field(
        default_factory=dict
    )
    _unallocated: tuple[Decimal, Decimal, Decimal, Decimal] = (
        ZERO, ZERO, ZERO, ZERO,
    )
    checkpoint_count: int = 0
    crossing_count: int = 0

    def __post_init__(self) -> None:
        if type(self.started_at_ms) is not int or self.started_at_ms < 0:
            raise PairedAccountWindowError("window start timestamp is invalid")
        if (
            not isinstance(self.starting_cash, Decimal)
            or not self.starting_cash.is_finite()
            or self.starting_cash <= ZERO
        ):
            raise PairedAccountWindowError("starting cash must be finite and positive")
        self._last = _Checkpoint(
            self.started_at_ms,
            (self.starting_cash, ZERO, self.starting_cash, ZERO),
        )

    @staticmethod
    def _sum(
        a: tuple[Decimal, Decimal, Decimal, Decimal],
        b: tuple[Decimal, Decimal, Decimal, Decimal],
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3])

    def record(
        self,
        *,
        at_ms: int,
        baseline_equity: Decimal,
        baseline_realized: Decimal,
        candidate_equity: Decimal,
        candidate_realized: Decimal,
    ) -> None:
        if type(at_ms) is not int or at_ms < self._last.at_ms:
            raise PairedAccountWindowError(
                "UTC paired checkpoints must be chronological"
            )
        new = (
            baseline_equity,
            baseline_realized,
            candidate_equity,
            candidate_realized,
        )
        if any(not v.is_finite() for v in new):
            raise PairedAccountWindowError(
                "nonfinite paired account balance cannot be reconciled"
            )
        movement = tuple(new[i] - self._last.amounts[i] for i in range(4))
        delta = (movement[0], movement[1], movement[2], movement[3])
        previous_day = self._last.at_ms // UTC_DAY_MS
        current_day = at_ms // UTC_DAY_MS
        if previous_day != current_day:
            self._unallocated = self._sum(self._unallocated, delta)
            self.crossing_count += 1
        else:
            day = datetime.fromtimestamp(at_ms / 1_000, tz=UTC).date().isoformat()
            self._by_day[day] = self._sum(
                self._by_day.get(day, (ZERO, ZERO, ZERO, ZERO)), delta
            )
        self._last = _Checkpoint(at_ms, new)
        self.checkpoint_count += 1

    @staticmethod
    def _payload(
        values: tuple[Decimal, Decimal, Decimal, Decimal],
    ) -> dict[str, str]:
        return {
            **{name: str(value) for name, value in zip(METRICS, values, strict=True)},
            "candidate_minus_baseline_marked": str(values[2] - values[0]),
            "candidate_minus_baseline_realized": str(values[3] - values[1]),
        }

    def reconciled_payload(
        self,
        *,
        baseline_equity: Decimal,
        baseline_realized: Decimal,
        candidate_equity: Decimal,
        candidate_realized: Decimal,
    ) -> dict[str, object]:
        account_end = (
            baseline_equity, baseline_realized,
            candidate_equity, candidate_realized,
        )
        if self._last.amounts != account_end:
            raise PairedAccountWindowError(
                "last signed checkpoint diverges from paired account state"
            )
        allocated = (ZERO, ZERO, ZERO, ZERO)
        for amounts in self._by_day.values():
            allocated = self._sum(allocated, amounts)
        full = (
            baseline_equity - self.starting_cash,
            baseline_realized,
            candidate_equity - self.starting_cash,
            candidate_realized,
        )
        if self._sum(allocated, self._unallocated) != full:
            raise PairedAccountWindowError(
                "allocated plus unallocated cash fails paired-account reconciliation"
            )
        return {
            "window_timezone": "UTC",
            "source": "two_observed_paper_account_checkpoints",
            "elapsed_movements_across_midnight_unallocated": True,
            "checkpoint_count": self.checkpoint_count,
            "midnight_crossing_interval_count": self.crossing_count,
            "by_fixed_utc_day": {
                day: self._payload(values)
                for day, values in sorted(self._by_day.items())
            },
            "unallocated_cross_day": self._payload(self._unallocated),
            "allocated_sum": self._payload(allocated),
            "full_account_change": self._payload(full),
            "all_four_account_metrics_reconciled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }
