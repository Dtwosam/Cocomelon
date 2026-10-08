from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import PaperExecutionConfig, PaperOrderPlan
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_filter_economic_readiness import (
    prospective_filter_economic_readiness,
)

ZERO: Final = Decimal("0")
BPS: Final = Decimal("10000")
SCHEMA_VERSION: Final = 1
CANDIDATE_ID: Final = "prospective-ex-ante-round-trip-cost-over-quarter-r-v1"
MAX_PREDICTED_COST_R: Final = Decimal("0.25")
FUNDING_RESERVE_PER_HOUR: Final = Decimal("0.0001")
FIXED_FUNDING_HOURS: Final = 1
EMBARGO_MS: Final = 30 * 60_000
MIN_SAMPLE: Final = 40
MIN_DIRECTION_RETAINED: Final = 8
MIN_DIRECTION_BLOCKED: Final = 3
MIN_MARKETS: Final = 4
BLOCKS: Final = 4
MIN_BLOCK_TRADES: Final = 10


class ProspectiveEntryCostRError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveEntryCostRState:
    frozen_at_ms: int
    execution_config_version: str
    taker_fee_rate: Decimal
    max_ioc_slippage_bps: Decimal
    schema_version: int = SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.frozen_at_ms < 0:
            raise ValueError("frozen entry cost gate timestamp invalid")
        if not self.execution_config_version.strip():
            raise ValueError("entry cost gate config version missing")
        if (
            not self.taker_fee_rate.is_finite()
            or self.taker_fee_rate < ZERO
            or self.taker_fee_rate >= Decimal("0.1")
        ):
            raise ValueError("entry cost gate taker fee invalid")
        if (
            not self.max_ioc_slippage_bps.is_finite()
            or self.max_ioc_slippage_bps < ZERO
            or self.max_ioc_slippage_bps > Decimal("10000")
        ):
            raise ValueError("entry cost gate IOC slippage invalid")
        if self.schema_version != SCHEMA_VERSION or self.candidate_id != CANDIDATE_ID:
            raise ValueError("entry cost gate frozen policy identity drift")

    @property
    def started_at_ms(self) -> int:
        return self.frozen_at_ms + EMBARGO_MS

    @classmethod
    def freeze(
        cls,
        config: PaperExecutionConfig,
        *,
        frozen_at_ms: int,
    ) -> ProspectiveEntryCostRState:
        return cls(
            frozen_at_ms=frozen_at_ms,
            execution_config_version=config.config_version,
            taker_fee_rate=config.taker_fee_rate,
            max_ioc_slippage_bps=config.max_ioc_slippage_bps,
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": CANDIDATE_ID,
            "frozen_at_ms": self.frozen_at_ms,
            "started_at_ms": self.started_at_ms,
            "execution_config_version": self.execution_config_version,
            "taker_fee_rate": str(self.taker_fee_rate),
            "max_ioc_slippage_bps": str(self.max_ioc_slippage_bps),
            "max_predicted_round_trip_cost_r": str(MAX_PREDICTED_COST_R),
            "fee_side_count": 2,
            "slippage_side_count": 2,
            "funding_reserve_per_hour": str(FUNDING_RESERVE_PER_HOUR),
            "fixed_funding_hours": FIXED_FUNDING_HOURS,
            "direction_policy": "symmetric_long_short",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }

    @classmethod
    def from_payload(cls, raw: object) -> ProspectiveEntryCostRState:
        if not isinstance(raw, dict):
            raise ProspectiveEntryCostRError("entry cost gate state must be object")
        try:
            state = cls(
                frozen_at_ms=raw["frozen_at_ms"],
                execution_config_version=raw["execution_config_version"],
                taker_fee_rate=Decimal(raw["taker_fee_rate"]),
                max_ioc_slippage_bps=Decimal(raw["max_ioc_slippage_bps"]),
                schema_version=raw["schema_version"],
                candidate_id=raw["candidate_id"],
            )
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ProspectiveEntryCostRError(
                f"entry cost gate state invalid: {type(exc).__name__}"
            ) from exc
        if raw != state.payload():
            raise ProspectiveEntryCostRError(
                "entry cost gate state policy or cost reserve drift"
            )
        return state


def _estimate_cost_r(
    trade: TradeJournalEntry,
    plan: PaperOrderPlan,
    state: ProspectiveEntryCostRState,
) -> Decimal:
    if (
        plan.plan_id != trade.opening_plan_id
        or plan.market != trade.market
        or plan.reduce_only
        or plan.execution_config_version != state.execution_config_version
        or plan.stop_price != trade.initial_stop
        or plan.created_at_ms > trade.opened_at_ms
        or plan.side.value != (
            "buy" if trade.direction is Direction.LONG else "sell"
        )
        or plan.max_slippage_bps != state.max_ioc_slippage_bps
        or trade.filled_quantity > plan.requested_quantity
    ):
        raise ProspectiveEntryCostRError(
            "entry cost gate original opening plan lineage or frozen cost drift"
        )
    risk_ceiling = plan.approved_risk_amount_ceiling
    if risk_ceiling is None or risk_ceiling <= ZERO:
        raise ProspectiveEntryCostRError(
            "entry cost gate opening plan missing original approved risk ceiling"
        )
    if (
        trade.initial_risk_amount > risk_ceiling
        or plan.requested_quantity <= ZERO
        or plan.execution_reference_price <= ZERO
    ):
        raise ProspectiveEntryCostRError(
            "entry cost gate original risk or notional inconsistent"
        )
    # Only entry-known, pre-execution quantities; never use exit, MFE or
    # final profit to predict the cost floor or choose a threshold.
    notional = (
        plan.requested_quantity * plan.execution_reference_price
    )
    estimate = notional * (
        state.taker_fee_rate * 2
        + state.max_ioc_slippage_bps * 2 / BPS
        + FUNDING_RESERVE_PER_HOUR * FIXED_FUNDING_HOURS
    )
    return estimate / risk_ceiling


def _positive(review: dict[str, object]) -> bool:
    return (
        review["candidate_profitable"] is True
        and review["improvement_positive"] is True
    )


def prospective_entry_cost_r_comparison(
    trades: Sequence[TradeJournalEntry],
    plan_loader: Callable[[str], PaperOrderPlan | None],
    state: ProspectiveEntryCostRState,
    execution_config: PaperExecutionConfig,
) -> dict[str, object]:
    if (
        execution_config.config_version != state.execution_config_version
        or execution_config.taker_fee_rate != state.taker_fee_rate
        or execution_config.max_ioc_slippage_bps != state.max_ioc_slippage_bps
    ):
        raise ProspectiveEntryCostRError(
            "entry cost gate execution configuration drift since freeze"
        )
    journal = tuple(trades)
    if len({t.trade_id for t in journal}) != len(journal):
        raise ProspectiveEntryCostRError(
            "entry cost gate journal contains duplicate trades"
        )
    cohort = tuple(sorted(
        (trade for trade in journal if trade.opened_at_ms >= state.started_at_ms),
        key=lambda trade: (
            trade.opened_at_ms, trade.closed_at_ms, trade.trade_id
        ),
    ))
    rows: list[tuple[TradeJournalEntry, bool, Decimal]] = []
    for trade in cohort:
        plan = plan_loader(trade.opening_plan_id)
        if plan is None:
            raise ProspectiveEntryCostRError(
                "entry cost gate missing original durable opening plan"
            )
        estimate_r = _estimate_cost_r(trade, plan, state)
        rows.append((trade, estimate_r > MAX_PREDICTED_COST_R, estimate_r))

    def assess(
        subset: Sequence[tuple[TradeJournalEntry, bool, Decimal]],
    ) -> dict[str, object]:
        return prospective_filter_economic_readiness(tuple(
            (trade, skipped) for trade, skipped, _ in subset
        ))

    overall = assess(rows)
    sides = {
        side: tuple(
            row for row in rows if row[0].direction.value == side
        )
        for side in ("long", "short")
    }
    per_direction = {
        side: {
            **assess(side_rows),
            "retained_trades": sum(not skipped for _, skipped, _ in side_rows),
            "blocked_trades": sum(skipped for _, skipped, _ in side_rows),
        }
        for side, side_rows in sides.items()
    }
    periods = []
    for index in range(BLOCKS):
        subset = rows[
            len(rows) * index // BLOCKS:
            len(rows) * (index + 1) // BLOCKS
        ]
        economic = assess(subset)
        periods.append({
            "period": index + 1,
            "trades": len(subset),
            "first_opened_at_ms": (
                None if not subset else subset[0][0].opened_at_ms
            ),
            "last_opened_at_ms": (
                None if not subset else subset[-1][0].opened_at_ms
            ),
            "passes": (
                len(subset) >= MIN_BLOCK_TRADES
                and _positive(economic)
            ),
            **economic,
        })
    retained = tuple(row for row in rows if not row[1])
    blocked = tuple(row for row in rows if row[1])
    markets = {row[0].market.canonical for row in rows}
    side_counts = all(
        len(sides[side]) >= MIN_DIRECTION_RETAINED + MIN_DIRECTION_BLOCKED
        and per_direction[side]["retained_trades"] >= MIN_DIRECTION_RETAINED
        and per_direction[side]["blocked_trades"] >= MIN_DIRECTION_BLOCKED
        for side in ("long", "short")
    )
    return {
        "schema_version": 1,
        "candidate_id": state.candidate_id,
        "frozen_rule": state.payload(),
        "frozen_at_ms": state.frozen_at_ms,
        "started_at_ms": state.started_at_ms,
        "closed_prospective_trades": len(rows),
        "markets": len(markets),
        "retained_trades": len(retained),
        "hypothetically_blocked_trades": len(blocked),
        "blocked_actual_winners": sum(
            row[0].net_pnl > ZERO for row in blocked
        ),
        "blocked_actual_losers": sum(
            row[0].net_pnl <= ZERO for row in blocked
        ),
        "cost_r_min": (
            None if not rows else str(min(row[2] for row in rows))
        ),
        "cost_r_max": (
            None if not rows else str(max(row[2] for row in rows))
        ),
        "overall": overall,
        "by_direction": per_direction,
        "chronological_periods": periods,
        "strict_descriptive_screen_passes": (
            len(rows) >= MIN_SAMPLE
            and len(markets) >= MIN_MARKETS
            and side_counts
            and overall["economics_ready"] is True
            and all(
                _positive(per_direction[side])
                for side in ("long", "short")
            )
            and all(period["passes"] is True for period in periods)
        ),
        "selected_winner": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready_for_review": False,
        "account_level_profitability_proven": False,
        "warning": (
            "Precommitted plan-time worst-case round-trip friction / R "
            "gate. Skipped trade contribution is zero, with no modeled "
            "margin reallocation, replacement entries, position overlap "
            "or altered drawdown. No exit/entry decisions change."
        ),
    }
