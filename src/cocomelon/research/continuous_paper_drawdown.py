from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry

ZERO: Final = Decimal("0")
DRAWDOWN_STATE_SCHEMA_VERSION: Final = 1


class ContinuousPaperDrawdownError(RuntimeError):
    pass


def _require_positive(value: Decimal, field: str) -> None:
    if not value.is_finite() or value <= ZERO:
        raise ValueError(f"{field} must be positive and finite")


def _drawdown_fraction(
    peak: Decimal,
    equity: Decimal,
) -> Decimal:
    _require_positive(peak, "peak")
    _require_positive(equity, "equity")
    return max(ZERO, (peak - equity) / peak)


@dataclass(slots=True)
class ContinuousPaperDrawdownTracker:
    started_at_ms: int
    observation_count: int = 0
    first_equity: Decimal | None = None
    first_timestamp_ms: int | None = None
    last_equity: Decimal | None = None
    last_timestamp_ms: int | None = None
    peak_equity: Decimal | None = None
    peak_timestamp_ms: int | None = None
    max_drawdown_fraction: Decimal = ZERO
    max_drawdown_amount: Decimal = ZERO
    max_drawdown_peak_equity: Decimal | None = None
    max_drawdown_trough_equity: Decimal | None = None
    max_drawdown_peak_timestamp_ms: int | None = None
    max_drawdown_trough_timestamp_ms: int | None = None
    state_restored: bool = False
    state_restore_error: str | None = None

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if self.observation_count < 0:
            raise ValueError("observation_count must be non-negative")
        if self.max_drawdown_fraction < ZERO:
            raise ValueError(
                "max_drawdown_fraction must be non-negative"
            )
        if self.max_drawdown_amount < ZERO:
            raise ValueError(
                "max_drawdown_amount must be non-negative"
            )

    def observe(
        self,
        equity: Decimal,
        *,
        timestamp_ms: int,
    ) -> None:
        _require_positive(equity, "equity")
        if timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        if (
            self.last_timestamp_ms is not None
            and timestamp_ms < self.last_timestamp_ms
        ):
            raise ContinuousPaperDrawdownError(
                "drawdown observation time regressed"
            )

        if self.first_equity is None:
            self.first_equity = equity
            self.first_timestamp_ms = timestamp_ms
            self.peak_equity = equity
            self.peak_timestamp_ms = timestamp_ms

        if self.peak_equity is None or self.peak_timestamp_ms is None:
            raise ContinuousPaperDrawdownError(
                "drawdown peak state is incomplete"
            )

        if equity > self.peak_equity:
            self.peak_equity = equity
            self.peak_timestamp_ms = timestamp_ms

        drawdown = _drawdown_fraction(
            self.peak_equity,
            equity,
        )
        amount = self.peak_equity - equity
        if drawdown > self.max_drawdown_fraction:
            self.max_drawdown_fraction = drawdown
            self.max_drawdown_amount = amount
            self.max_drawdown_peak_equity = self.peak_equity
            self.max_drawdown_trough_equity = equity
            self.max_drawdown_peak_timestamp_ms = (
                self.peak_timestamp_ms
            )
            self.max_drawdown_trough_timestamp_ms = timestamp_ms

        if self.last_timestamp_ms != timestamp_ms:
            self.observation_count += 1
        self.last_equity = equity
        self.last_timestamp_ms = timestamp_ms

    def current_drawdown_fraction(self) -> Decimal | None:
        if self.last_equity is None or self.peak_equity is None:
            return None
        return _drawdown_fraction(
            self.peak_equity,
            self.last_equity,
        )

    def current_drawdown_amount(self) -> Decimal | None:
        if self.last_equity is None or self.peak_equity is None:
            return None
        return max(ZERO, self.peak_equity - self.last_equity)

    def state_payload(self) -> dict[str, object]:
        def decimal(value: Decimal | None) -> str | None:
            return None if value is None else str(value)

        return {
            "schema_version": DRAWDOWN_STATE_SCHEMA_VERSION,
            "started_at_ms": self.started_at_ms,
            "observation_count": self.observation_count,
            "first_equity": decimal(self.first_equity),
            "first_timestamp_ms": self.first_timestamp_ms,
            "last_equity": decimal(self.last_equity),
            "last_timestamp_ms": self.last_timestamp_ms,
            "peak_equity": decimal(self.peak_equity),
            "peak_timestamp_ms": self.peak_timestamp_ms,
            "max_drawdown_fraction": str(
                self.max_drawdown_fraction
            ),
            "max_drawdown_amount": str(
                self.max_drawdown_amount
            ),
            "max_drawdown_peak_equity": decimal(
                self.max_drawdown_peak_equity
            ),
            "max_drawdown_trough_equity": decimal(
                self.max_drawdown_trough_equity
            ),
            "max_drawdown_peak_timestamp_ms": (
                self.max_drawdown_peak_timestamp_ms
            ),
            "max_drawdown_trough_timestamp_ms": (
                self.max_drawdown_trough_timestamp_ms
            ),
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ContinuousPaperDrawdownTracker:
        if not isinstance(raw, dict):
            raise ContinuousPaperDrawdownError(
                "drawdown state must be an object"
            )
        if raw.get("schema_version") != (
            DRAWDOWN_STATE_SCHEMA_VERSION
        ):
            raise ContinuousPaperDrawdownError(
                "unsupported drawdown state schema"
            )

        def integer(name: str) -> int | None:
            value = raw.get(name)
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, int):
                raise ContinuousPaperDrawdownError(
                    f"{name} must be an integer or null"
                )
            return int(value)

        def decimal(name: str) -> Decimal | None:
            value = raw.get(name)
            if value is None:
                return None
            result = Decimal(str(value))
            if not result.is_finite():
                raise ContinuousPaperDrawdownError(
                    f"{name} must be finite"
                )
            return result

        started_at_ms = integer("started_at_ms")
        observation_count = integer("observation_count")
        if started_at_ms is None or observation_count is None:
            raise ContinuousPaperDrawdownError(
                "drawdown required integer state is missing"
            )

        tracker = cls(
            started_at_ms=started_at_ms,
            observation_count=observation_count,
            first_equity=decimal("first_equity"),
            first_timestamp_ms=integer("first_timestamp_ms"),
            last_equity=decimal("last_equity"),
            last_timestamp_ms=integer("last_timestamp_ms"),
            peak_equity=decimal("peak_equity"),
            peak_timestamp_ms=integer("peak_timestamp_ms"),
            max_drawdown_fraction=(
                decimal("max_drawdown_fraction") or ZERO
            ),
            max_drawdown_amount=(
                decimal("max_drawdown_amount") or ZERO
            ),
            max_drawdown_peak_equity=decimal(
                "max_drawdown_peak_equity"
            ),
            max_drawdown_trough_equity=decimal(
                "max_drawdown_trough_equity"
            ),
            max_drawdown_peak_timestamp_ms=integer(
                "max_drawdown_peak_timestamp_ms"
            ),
            max_drawdown_trough_timestamp_ms=integer(
                "max_drawdown_trough_timestamp_ms"
            ),
            state_restored=True,
        )
        tracker._validate_restored_state()
        return tracker

    def _validate_restored_state(self) -> None:
        paired = (
            (self.first_equity, self.first_timestamp_ms),
            (self.last_equity, self.last_timestamp_ms),
            (self.peak_equity, self.peak_timestamp_ms),
            (
                self.max_drawdown_peak_equity,
                self.max_drawdown_peak_timestamp_ms,
            ),
            (
                self.max_drawdown_trough_equity,
                self.max_drawdown_trough_timestamp_ms,
            ),
        )
        for value, timestamp in paired:
            if (value is None) != (timestamp is None):
                raise ContinuousPaperDrawdownError(
                    "drawdown state value/timestamp mismatch"
                )
            if value is not None:
                _require_positive(value, "drawdown equity state")
            if timestamp is not None and timestamp < 0:
                raise ContinuousPaperDrawdownError(
                    "drawdown timestamp must be non-negative"
                )
        if self.observation_count == 0:
            if any(
                value is not None
                for value in (
                    self.first_equity,
                    self.last_equity,
                    self.peak_equity,
                )
            ):
                raise ContinuousPaperDrawdownError(
                    "empty drawdown state cannot contain observations"
                )
            return
        if (
            self.first_equity is None
            or self.last_equity is None
            or self.peak_equity is None
            or self.first_timestamp_ms is None
            or self.last_timestamp_ms is None
            or self.peak_timestamp_ms is None
        ):
            raise ContinuousPaperDrawdownError(
                "observed drawdown state is incomplete"
            )
        if self.first_timestamp_ms < self.started_at_ms:
            raise ContinuousPaperDrawdownError(
                "drawdown first observation predates start"
            )
        if self.last_timestamp_ms < self.first_timestamp_ms:
            raise ContinuousPaperDrawdownError(
                "drawdown last timestamp precedes first"
            )
        if self.peak_equity < self.last_equity:
            raise ContinuousPaperDrawdownError(
                "drawdown peak cannot be below latest equity"
            )
        if self.max_drawdown_fraction > ZERO:
            if any(
                value is None
                for value in (
                    self.max_drawdown_peak_equity,
                    self.max_drawdown_trough_equity,
                    self.max_drawdown_peak_timestamp_ms,
                    self.max_drawdown_trough_timestamp_ms,
                )
            ):
                raise ContinuousPaperDrawdownError(
                    "maximum drawdown state is incomplete"
                )

    def mark_state_restore_error(self, error: str) -> None:
        if not error.strip():
            raise ValueError("restore error must not be empty")
        self.state_restore_error = error


def realized_closed_trade_drawdown(
    trades: Sequence[TradeJournalEntry],
    *,
    starting_equity: Decimal,
) -> dict[str, object]:
    _require_positive(starting_equity, "starting_equity")
    ordered = tuple(
        sorted(
            trades,
            key=lambda trade: (
                trade.closed_at_ms,
                trade.trade_id,
            ),
        )
    )
    running = starting_equity
    peak = starting_equity
    peak_timestamp_ms: int | None = None
    max_fraction = ZERO
    max_amount = ZERO
    max_peak = starting_equity
    max_trough = starting_equity
    max_peak_timestamp_ms: int | None = None
    max_trough_timestamp_ms: int | None = None

    for trade in ordered:
        running += trade.net_pnl
        _require_positive(
            running,
            "realized closed-trade equity",
        )
        if running > peak:
            peak = running
            peak_timestamp_ms = trade.closed_at_ms
            continue
        drawdown = _drawdown_fraction(peak, running)
        if drawdown > max_fraction:
            max_fraction = drawdown
            max_amount = peak - running
            max_peak = peak
            max_trough = running
            max_peak_timestamp_ms = peak_timestamp_ms
            max_trough_timestamp_ms = trade.closed_at_ms

    return {
        "closed_trades": len(ordered),
        "starting_equity": str(starting_equity),
        "ending_realized_equity": str(running),
        "peak_realized_equity": str(peak),
        "max_drawdown_fraction": str(max_fraction),
        "max_drawdown_amount": str(max_amount),
        "max_drawdown_peak_equity": str(max_peak),
        "max_drawdown_trough_equity": str(max_trough),
        "max_drawdown_peak_timestamp_ms": (
            max_peak_timestamp_ms
        ),
        "max_drawdown_trough_timestamp_ms": (
            max_trough_timestamp_ms
        ),
    }


def drawdown_summary(
    tracker: ContinuousPaperDrawdownTracker,
    trades: Sequence[TradeJournalEntry],
    *,
    starting_equity: Decimal,
    checkpoint_seconds: int,
) -> dict[str, object]:
    if checkpoint_seconds <= 0:
        raise ValueError("checkpoint_seconds must be positive")
    realized = realized_closed_trade_drawdown(
        trades,
        starting_equity=starting_equity,
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "sampled_account": {
            "definition": "prospective_runtime_checkpoint_equity",
            "checkpoint_seconds": checkpoint_seconds,
            "started_at_ms": tracker.started_at_ms,
            "state_restored": tracker.state_restored,
            "state_restore_error": tracker.state_restore_error,
            "observation_count": tracker.observation_count,
            "first_timestamp_ms": tracker.first_timestamp_ms,
            "last_timestamp_ms": tracker.last_timestamp_ms,
            "peak_timestamp_ms": tracker.peak_timestamp_ms,
            "mean_observation_interval_ms": (
                None
                if tracker.observation_count <= 1
                or tracker.first_timestamp_ms is None
                or tracker.last_timestamp_ms is None
                else (
                    tracker.last_timestamp_ms
                    - tracker.first_timestamp_ms
                )
                // (tracker.observation_count - 1)
            ),
            "first_equity": (
                None
                if tracker.first_equity is None
                else str(tracker.first_equity)
            ),
            "last_equity": (
                None
                if tracker.last_equity is None
                else str(tracker.last_equity)
            ),
            "peak_equity": (
                None
                if tracker.peak_equity is None
                else str(tracker.peak_equity)
            ),
            "current_drawdown_fraction": (
                None
                if tracker.current_drawdown_fraction() is None
                else str(tracker.current_drawdown_fraction())
            ),
            "current_drawdown_amount": (
                None
                if tracker.current_drawdown_amount() is None
                else str(tracker.current_drawdown_amount())
            ),
            "max_drawdown_fraction": str(
                tracker.max_drawdown_fraction
            ),
            "max_drawdown_amount": str(
                tracker.max_drawdown_amount
            ),
            "max_drawdown_peak_equity": (
                None
                if tracker.max_drawdown_peak_equity is None
                else str(tracker.max_drawdown_peak_equity)
            ),
            "max_drawdown_trough_equity": (
                None
                if tracker.max_drawdown_trough_equity is None
                else str(tracker.max_drawdown_trough_equity)
            ),
            "max_drawdown_peak_timestamp_ms": (
                tracker.max_drawdown_peak_timestamp_ms
            ),
            "max_drawdown_trough_timestamp_ms": (
                tracker.max_drawdown_trough_timestamp_ms
            ),
        },
        "realized_closed_trade": realized,
    }
