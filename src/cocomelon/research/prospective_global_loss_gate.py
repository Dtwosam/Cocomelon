from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.prospective_filter_economic_readiness import (
    prospective_filter_economic_readiness,
)
from cocomelon.research.prospective_filter_robustness import (
    prospective_filter_robustness,
)

STATE_SCHEMA_VERSION: Final = 1
CANDIDATE_ID: Final = "prospective-global-two-loss-skip-next-v1"
LOSS_THRESHOLD: Final = 2
EMBARGO_MS: Final = 6 * 60 * 60 * 1_000
MIN_PROSPECTIVE_CLOSED_TRADES: Final = 30
MIN_BLOCKED_TRADES: Final = 5
MIN_ADMITTED_TRADES: Final = 10
MIN_DIRECTION_CLOSED_TRADES: Final = 5
ZERO: Final = Decimal("0")


class ProspectiveGlobalLossGateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveGlobalLossGateState:
    frozen_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.frozen_at_ms < 0:
            raise ValueError("frozen_at_ms must be non-negative")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("unsupported global-loss-gate schema")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("unsupported global-loss-gate candidate")

    @property
    def started_at_ms(self) -> int:
        return self.frozen_at_ms + EMBARGO_MS

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "frozen_at_ms": self.frozen_at_ms,
            "started_at_ms": self.started_at_ms,
            "embargo_ms": EMBARGO_MS,
            "rule": {
                "scope": "global_candidate_admitted_closes",
                "qualifying_close_pnl": "negative",
                "loss_threshold": LOSS_THRESHOLD,
                "action": "skip_next_opening_once_then_reset",
                "time_window_ms": None,
                "direction_specific": False,
                "market_specific": False,
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveGlobalLossGateState:
        if not isinstance(raw, dict):
            raise ProspectiveGlobalLossGateError(
                "global-loss-gate state must be an object"
            )
        expected_rule = cls(frozen_at_ms=0).payload()["rule"]
        if raw.get("rule") != expected_rule:
            raise ProspectiveGlobalLossGateError(
                "global-loss-gate rule does not match frozen candidate"
            )
        if raw.get("embargo_ms") != EMBARGO_MS:
            raise ProspectiveGlobalLossGateError(
                "global-loss-gate embargo does not match frozen candidate"
            )

        schema_version = raw.get("schema_version")
        frozen_at_ms = raw.get("frozen_at_ms")
        started_at_ms = raw.get("started_at_ms")
        candidate_id = raw.get("candidate_id")
        if isinstance(schema_version, bool) or not isinstance(
            schema_version,
            int,
        ):
            raise ProspectiveGlobalLossGateError(
                "schema_version must be an integer"
            )
        if isinstance(frozen_at_ms, bool) or not isinstance(
            frozen_at_ms,
            int,
        ):
            raise ProspectiveGlobalLossGateError(
                "frozen_at_ms must be an integer"
            )
        if isinstance(started_at_ms, bool) or not isinstance(
            started_at_ms,
            int,
        ):
            raise ProspectiveGlobalLossGateError(
                "started_at_ms must be an integer"
            )
        if not isinstance(candidate_id, str):
            raise ProspectiveGlobalLossGateError(
                "candidate_id must be a string"
            )

        try:
            state = cls(
                frozen_at_ms=frozen_at_ms,
                schema_version=schema_version,
                candidate_id=candidate_id,
            )
        except ValueError as exc:
            raise ProspectiveGlobalLossGateError(str(exc)) from exc
        if started_at_ms != state.started_at_ms:
            raise ProspectiveGlobalLossGateError(
                "started_at_ms does not match frozen embargo"
            )
        return state


def _direction_summary(
    trades: tuple[TradeJournalEntry, ...],
    blocked_ids: set[str],
    direction: Direction,
) -> dict[str, object]:
    values = tuple(
        trade for trade in trades if trade.direction is direction
    )
    blocked = tuple(
        trade for trade in values if trade.trade_id in blocked_ids
    )
    admitted = tuple(
        trade for trade in values if trade.trade_id not in blocked_ids
    )
    actual_pnl = sum((trade.net_pnl for trade in values), ZERO)
    candidate_pnl = sum(
        (trade.net_pnl for trade in admitted),
        ZERO,
    )
    actual_r = sum((trade.net_r for trade in values), ZERO)
    candidate_r = sum(
        (trade.net_r for trade in admitted),
        ZERO,
    )
    return {
        "closed_trades": len(values),
        "admitted_trades": len(admitted),
        "blocked_trades": len(blocked),
        "blocked_winners": sum(
            trade.net_pnl > ZERO for trade in blocked
        ),
        "blocked_losses": sum(
            trade.net_pnl < ZERO for trade in blocked
        ),
        "blocked_net_pnl": str(
            sum((trade.net_pnl for trade in blocked), ZERO)
        ),
        "actual_net_pnl": str(actual_pnl),
        "candidate_net_pnl": str(candidate_pnl),
        "delta_net_pnl": str(candidate_pnl - actual_pnl),
        "actual_net_r": str(actual_r),
        "candidate_net_r": str(candidate_r),
        "delta_net_r": str(candidate_r - actual_r),
    }


def prospective_global_loss_gate_summary(
    trades: Sequence[TradeJournalEntry],
    state: ProspectiveGlobalLossGateState,
) -> dict[str, object]:
    prospective = tuple(
        sorted(
            (
                trade
                for trade in trades
                if trade.opened_at_ms >= state.started_at_ms
            ),
            key=lambda trade: (
                trade.opened_at_ms,
                trade.closed_at_ms,
                trade.trade_id,
            ),
        )
    )
    trade_ids = tuple(trade.trade_id for trade in prospective)
    if len(set(trade_ids)) != len(trade_ids):
        raise ProspectiveGlobalLossGateError(
            "prospective trades contain duplicate trade ids"
        )

    consecutive_losses = 0
    admitted_ids: set[str] = set()
    blocked_ids: set[str] = set()
    decision_prior_losses: dict[str, int] = {}
    events: list[tuple[int, int, TradeJournalEntry]] = []
    for trade in prospective:
        events.append((trade.closed_at_ms, 0, trade))
        events.append((trade.opened_at_ms, 1, trade))
    events.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2].opened_at_ms,
            item[2].trade_id,
        )
    )

    for _event_ms, event_kind, trade in events:
        if event_kind == 1:
            decision_prior_losses[trade.trade_id] = (
                consecutive_losses
            )
            if consecutive_losses >= LOSS_THRESHOLD:
                blocked_ids.add(trade.trade_id)
                consecutive_losses = 0
            else:
                admitted_ids.add(trade.trade_id)
            continue

        if trade.trade_id not in admitted_ids:
            continue
        if trade.net_pnl < ZERO:
            consecutive_losses += 1
        else:
            consecutive_losses = 0

    if admitted_ids & blocked_ids:
        raise ProspectiveGlobalLossGateError(
            "trade cannot be both admitted and blocked"
        )
    if len(admitted_ids | blocked_ids) != len(prospective):
        raise ProspectiveGlobalLossGateError(
            "candidate decisions do not cover prospective trades"
        )

    blocked = tuple(
        trade for trade in prospective if trade.trade_id in blocked_ids
    )
    admitted = tuple(
        trade for trade in prospective if trade.trade_id in admitted_ids
    )
    actual_pnl = sum(
        (trade.net_pnl for trade in prospective),
        ZERO,
    )
    candidate_pnl = sum(
        (trade.net_pnl for trade in admitted),
        ZERO,
    )
    actual_r = sum(
        (trade.net_r for trade in prospective),
        ZERO,
    )
    candidate_r = sum(
        (trade.net_r for trade in admitted),
        ZERO,
    )
    delta_pnl = candidate_pnl - actual_pnl
    delta_r = candidate_r - actual_r
    filter_items = tuple(
        (trade, trade.trade_id in blocked_ids)
        for trade in prospective
    )
    robustness = prospective_filter_robustness(filter_items)
    economic_readiness = prospective_filter_economic_readiness(
        filter_items
    )

    by_direction = {
        direction.value: _direction_summary(
            prospective,
            blocked_ids,
            direction,
        )
        for direction in (Direction.LONG, Direction.SHORT)
    }
    blocked_by_market: dict[str, dict[str, object]] = {}
    for market in sorted(
        {trade.market.canonical for trade in blocked}
    ):
        cohort = tuple(
            trade
            for trade in blocked
            if trade.market.canonical == market
        )
        blocked_by_market[market] = {
            "trades": len(cohort),
            "wins": sum(
                trade.net_pnl > ZERO for trade in cohort
            ),
            "losses": sum(
                trade.net_pnl < ZERO for trade in cohort
            ),
            "net_pnl": str(
                sum((trade.net_pnl for trade in cohort), ZERO)
            ),
            "net_r": str(
                sum((trade.net_r for trade in cohort), ZERO)
            ),
        }

    long_closed = by_direction[Direction.LONG.value][
        "closed_trades"
    ]
    short_closed = by_direction[Direction.SHORT.value][
        "closed_trades"
    ]
    if (
        isinstance(long_closed, bool)
        or not isinstance(long_closed, int)
        or isinstance(short_closed, bool)
        or not isinstance(short_closed, int)
    ):
        raise ProspectiveGlobalLossGateError(
            "direction counts must be integers"
        )

    missing_total = max(
        0,
        MIN_PROSPECTIVE_CLOSED_TRADES - len(prospective),
    )
    missing_blocked = max(
        0,
        MIN_BLOCKED_TRADES - len(blocked),
    )
    missing_admitted = max(
        0,
        MIN_ADMITTED_TRADES - len(admitted),
    )
    missing_long = max(
        0,
        MIN_DIRECTION_CLOSED_TRADES - long_closed,
    )
    missing_short = max(
        0,
        MIN_DIRECTION_CLOSED_TRADES - short_closed,
    )
    sample_complete = (
        missing_total == 0
        and missing_blocked == 0
        and missing_admitted == 0
        and missing_long == 0
        and missing_short == 0
    )
    candidate_profitable = (
        economic_readiness["candidate_profitable"] is True
    )
    improvement_positive = (
        economic_readiness["improvement_positive"] is True
    )
    candidate_trade_robust = (
        economic_readiness["candidate_single_trade_robust"] is True
    )
    candidate_market_robust = (
        economic_readiness["candidate_single_market_robust"] is True
    )
    delta_trade_robust = (
        economic_readiness["delta_single_trade_robust"] is True
    )
    delta_market_robust = (
        economic_readiness["delta_single_market_robust"] is True
    )
    economics_positive = (
        candidate_profitable and improvement_positive
    )
    robust_trade = candidate_trade_robust and delta_trade_robust
    robust_market = candidate_market_robust and delta_market_robust
    ready_for_review = (
        sample_complete
        and economics_positive
        and robust_trade
        and robust_market
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "candidate_id": state.candidate_id,
        "frozen_at_ms": state.frozen_at_ms,
        "started_at_ms": state.started_at_ms,
        "embargo_ms": EMBARGO_MS,
        "rule": state.payload()["rule"],
        "claim_scope": "prospective_closed_trade_contribution_only",
        "portfolio_counterfactual": False,
        "replacement_trades_modeled": False,
        "prospective_closed_trades": len(prospective),
        "admitted_trades": len(admitted),
        "blocked_trades": len(blocked),
        "blocked_wins": sum(
            trade.net_pnl > ZERO for trade in blocked
        ),
        "blocked_losses": sum(
            trade.net_pnl < ZERO for trade in blocked
        ),
        "blocked_net_pnl": str(
            sum((trade.net_pnl for trade in blocked), ZERO)
        ),
        "actual_net_pnl": str(actual_pnl),
        "candidate_net_pnl": str(candidate_pnl),
        "delta_net_pnl": str(delta_pnl),
        "actual_net_r": str(actual_r),
        "candidate_net_r": str(candidate_r),
        "delta_net_r": str(delta_r),
        "decision_prior_losses": {
            trade_id: decision_prior_losses[trade_id]
            for trade_id in sorted(decision_prior_losses)
        },
        "by_direction": by_direction,
        "blocked_by_market": blocked_by_market,
        "robustness": robustness,
        "economic_readiness": economic_readiness,
        "readiness": {
            "ready_for_review": ready_for_review,
            "sample_complete": sample_complete,
            "candidate_profitable": candidate_profitable,
            "improvement_positive": improvement_positive,
            "economics_positive": economics_positive,
            "candidate_single_trade_robust": (
                candidate_trade_robust
            ),
            "candidate_single_market_robust": (
                candidate_market_robust
            ),
            "delta_single_trade_robust": delta_trade_robust,
            "delta_single_market_robust": delta_market_robust,
            "single_trade_robust": robust_trade,
            "single_market_robust": robust_market,
            "min_prospective_closed_trades": (
                MIN_PROSPECTIVE_CLOSED_TRADES
            ),
            "min_blocked_trades": MIN_BLOCKED_TRADES,
            "min_admitted_trades": MIN_ADMITTED_TRADES,
            "min_direction_closed_trades": (
                MIN_DIRECTION_CLOSED_TRADES
            ),
            "missing_prospective_closed_trades": missing_total,
            "missing_blocked_trades": missing_blocked,
            "missing_admitted_trades": missing_admitted,
            "missing_long_closed_trades": missing_long,
            "missing_short_closed_trades": missing_short,
        },
    }


def evaluate_prospective_global_loss_gate(
    journal: JournalStore,
    state: ProspectiveGlobalLossGateState,
) -> dict[str, object]:
    return prospective_global_loss_gate_summary(
        tuple(journal.iter_trades()),
        state,
    )
