from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.prospective_allowed_residual import (
    AllowedResidualItem,
    prospective_allowed_residual_attribution,
)
from cocomelon.research.prospective_filter_robustness import (
    prospective_filter_robustness,
)

ENTRY_FILTER_STATE_SCHEMA_VERSION: Final = 1
ENTRY_FILTER_CANDIDATE_ID: Final = "prospective-reject-long-trend-v1"
MIN_PROSPECTIVE_CLOSED_TRADES: Final = 30
MIN_BLOCKED_TRADES: Final = 10
MIN_ALLOWED_TRADES: Final = 10
ZERO: Final = Decimal("0")


class ProspectiveEntryFilterError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveEntryFilterState:
    started_at_ms: int
    schema_version: int = ENTRY_FILTER_STATE_SCHEMA_VERSION
    candidate_id: str = ENTRY_FILTER_CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if self.schema_version != ENTRY_FILTER_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported entry-filter state schema")
        if self.candidate_id != ENTRY_FILTER_CANDIDATE_ID:
            raise ValueError("unsupported entry-filter candidate")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "rule": {
                "direction": Direction.LONG.value,
                "lead_strategy": "trend",
                "action": "reject",
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveEntryFilterState:
        if not isinstance(raw, dict):
            raise ProspectiveEntryFilterError(
                "entry-filter state must be an object"
            )
        rule = raw.get("rule")
        expected_rule = {
            "direction": Direction.LONG.value,
            "lead_strategy": "trend",
            "action": "reject",
        }
        if rule != expected_rule:
            raise ProspectiveEntryFilterError(
                "entry-filter rule does not match frozen candidate"
            )
        schema_version = raw.get("schema_version")
        started_at_ms = raw.get("started_at_ms")
        candidate_id = raw.get("candidate_id")
        if isinstance(schema_version, bool) or not isinstance(
            schema_version,
            int,
        ):
            raise ProspectiveEntryFilterError(
                "entry-filter schema_version must be an integer"
            )
        if isinstance(started_at_ms, bool) or not isinstance(
            started_at_ms,
            int,
        ):
            raise ProspectiveEntryFilterError(
                "entry-filter started_at_ms must be an integer"
            )
        if not isinstance(candidate_id, str):
            raise ProspectiveEntryFilterError(
                "entry-filter candidate_id must be a string"
            )
        try:
            return cls(
                started_at_ms=started_at_ms,
                schema_version=schema_version,
                candidate_id=candidate_id,
            )
        except ValueError as exc:
            raise ProspectiveEntryFilterError(str(exc)) from exc


def _fact_for_trade(
    trade: TradeJournalEntry,
    fact_store: EvaluationFactStore,
) -> DecisionEvaluationFact | None:
    if trade.replay_run_id is None:
        return None
    fact = fact_store.load_decision_by_strategy_id(
        trade.strategy_decision_id,
        trade.replay_run_id,
    )
    if fact is None:
        return None
    if fact.market != trade.market:
        raise ProspectiveEntryFilterError(
            "entry-filter decision market does not match trade"
        )
    if fact.direction is not trade.direction:
        raise ProspectiveEntryFilterError(
            "entry-filter decision direction does not match trade"
        )
    if fact.feature_snapshot_id != trade.feature_snapshot_id:
        raise ProspectiveEntryFilterError(
            "entry-filter feature lineage does not match trade"
        )
    return fact


def _rejects(trade: TradeJournalEntry, lead_strategy: str) -> bool:
    return (
        trade.direction is Direction.LONG
        and lead_strategy == "trend"
    )


def prospective_entry_filter_summary(
    trades: tuple[TradeJournalEntry, ...],
    fact_store: EvaluationFactStore,
    state: ProspectiveEntryFilterState,
) -> dict[str, object]:
    prospective = tuple(
        trade
        for trade in trades
        if trade.opened_at_ms >= state.started_at_ms
    )
    attributed: list[tuple[TradeJournalEntry, bool]] = []
    lead_strategy_by_trade_id: dict[str, str] = {}
    attribution_misses = 0

    for trade in prospective:
        fact = _fact_for_trade(trade, fact_store)
        if fact is None or fact.lead_strategy is None:
            attribution_misses += 1
            continue
        attributed.append(
            (trade, _rejects(trade, fact.lead_strategy))
        )
        lead_strategy_by_trade_id[trade.trade_id] = (
            fact.lead_strategy
        )

    blocked = tuple(
        trade for trade, rejected in attributed if rejected
    )
    allowed = tuple(
        trade for trade, rejected in attributed if not rejected
    )
    actual_net_pnl = sum(
        (trade.net_pnl for trade, _ in attributed),
        ZERO,
    )
    allowed_net_pnl = sum(
        (trade.net_pnl for trade in allowed),
        ZERO,
    )
    blocked_net_pnl = sum(
        (trade.net_pnl for trade in blocked),
        ZERO,
    )
    robustness = prospective_filter_robustness(
        tuple(attributed)
    )
    allowed_residual = prospective_allowed_residual_attribution(
        tuple(
            AllowedResidualItem(
                trade,
                lead_strategy=lead_strategy_by_trade_id[
                    trade.trade_id
                ],
            )
            for trade in allowed
        )
    )
    actual_net_r = sum(
        (trade.net_r for trade, _ in attributed),
        ZERO,
    )
    candidate_net_r_contribution = sum(
        (trade.net_r for trade in allowed),
        ZERO,
    )
    count = len(attributed)
    actual_mean_r = (
        None
        if count == 0
        else actual_net_r / Decimal(count)
    )
    candidate_mean_r_contribution = (
        None
        if count == 0
        else candidate_net_r_contribution / Decimal(count)
    )

    missing_total = max(
        0,
        MIN_PROSPECTIVE_CLOSED_TRADES - len(prospective),
    )
    missing_blocked = max(
        0,
        MIN_BLOCKED_TRADES - len(blocked),
    )
    missing_allowed = max(
        0,
        MIN_ALLOWED_TRADES - len(allowed),
    )
    ready = (
        attribution_misses == 0
        and missing_total == 0
        and missing_blocked == 0
        and missing_allowed == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": state.candidate_id,
        "started_at_ms": state.started_at_ms,
        "rule": {
            "direction": Direction.LONG.value,
            "lead_strategy": "trend",
            "action": "reject",
        },
        "claim_scope": "closed_trade_contribution_only",
        "portfolio_counterfactual": False,
        "prospective_closed_trades": len(prospective),
        "attributed_trades": count,
        "attribution_misses": attribution_misses,
        "allowed_trades": len(allowed),
        "blocked_trades": len(blocked),
        "blocked_wins": sum(
            1 for trade in blocked if trade.net_pnl > ZERO
        ),
        "blocked_losses": sum(
            1 for trade in blocked if trade.net_pnl < ZERO
        ),
        "blocked_net_pnl": str(blocked_net_pnl),
        "robustness": robustness,
        "allowed_residual": allowed_residual,
        "allowed_net_pnl": str(allowed_net_pnl),
        "actual_net_pnl": str(actual_net_pnl),
        "candidate_trade_contribution_pnl": str(
            allowed_net_pnl
        ),
        "delta_trade_contribution_pnl": str(
            allowed_net_pnl - actual_net_pnl
        ),
        "actual_mean_net_r": (
            None
            if actual_mean_r is None
            else str(actual_mean_r)
        ),
        "candidate_mean_net_r_contribution": (
            None
            if candidate_mean_r_contribution is None
            else str(candidate_mean_r_contribution)
        ),
        "readiness": {
            "ready_for_review": ready,
            "min_prospective_closed_trades": (
                MIN_PROSPECTIVE_CLOSED_TRADES
            ),
            "min_blocked_trades": MIN_BLOCKED_TRADES,
            "min_allowed_trades": MIN_ALLOWED_TRADES,
            "missing_prospective_closed_trades": missing_total,
            "missing_blocked_trades": missing_blocked,
            "missing_allowed_trades": missing_allowed,
        },
    }


def evaluate_prospective_entry_filter(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
    state: ProspectiveEntryFilterState,
) -> dict[str, object]:
    return prospective_entry_filter_summary(
        tuple(journal.iter_trades()),
        fact_store,
        state,
    )
