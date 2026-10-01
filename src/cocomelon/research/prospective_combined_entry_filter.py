from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.profit_lock_counterfactual import ProfitLockTradeOutcome
from cocomelon.research.prospective_allowed_residual import (
    AllowedResidualItem,
    prospective_allowed_residual_attribution,
)
from cocomelon.research.prospective_entry_filter import (
    ProspectiveEntryFilterState,
)
from cocomelon.research.prospective_filter_fixed_schedule import (
    ProspectiveFilterPortfolioItem,
    prospective_filter_fixed_schedule_portfolio,
)
from cocomelon.research.prospective_filter_robustness import (
    prospective_filter_robustness,
)
from cocomelon.research.prospective_residual_profit_lock import (
    prospective_residual_profit_lock_summary,
)
from cocomelon.research.prospective_top10_rank_filter import (
    ProspectiveTop10RankFilterState,
)

COMBINED_FILTER_STATE_SCHEMA_VERSION: Final = 1
COMBINED_FILTER_CANDIDATE_ID: Final = (
    "prospective-top10-no-long-trend-v1"
)
TOP10_MAX_ORDINAL: Final = 10
MAX_ACCEPTED_RANK_AGE_MS: Final = 300_000
MIN_PROSPECTIVE_CLOSED_TRADES: Final = 30
MIN_BLOCKED_TRADES: Final = 10
MIN_ALLOWED_TRADES: Final = 10
ZERO: Final = Decimal("0")


class ProspectiveCombinedEntryFilterError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveCombinedEntryFilterState:
    started_at_ms: int
    schema_version: int = COMBINED_FILTER_STATE_SCHEMA_VERSION
    candidate_id: str = COMBINED_FILTER_CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if self.schema_version != COMBINED_FILTER_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported combined-filter state schema")
        if self.candidate_id != COMBINED_FILTER_CANDIDATE_ID:
            raise ValueError("unsupported combined-filter candidate")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "rule": {
                "max_admitted_ordinal": TOP10_MAX_ORDINAL,
                "max_rank_age_ms": MAX_ACCEPTED_RANK_AGE_MS,
                "reject_direction": Direction.LONG.value,
                "reject_lead_strategy": "trend",
                "combination": "all_conditions_must_pass",
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveCombinedEntryFilterState:
        if not isinstance(raw, dict):
            raise ProspectiveCombinedEntryFilterError(
                "combined-filter state must be an object"
            )
        expected_rule = {
            "max_admitted_ordinal": TOP10_MAX_ORDINAL,
            "max_rank_age_ms": MAX_ACCEPTED_RANK_AGE_MS,
            "reject_direction": Direction.LONG.value,
            "reject_lead_strategy": "trend",
            "combination": "all_conditions_must_pass",
        }
        if raw.get("rule") != expected_rule:
            raise ProspectiveCombinedEntryFilterError(
                "combined-filter rule does not match frozen candidate"
            )
        schema_version = raw.get("schema_version")
        started_at_ms = raw.get("started_at_ms")
        candidate_id = raw.get("candidate_id")
        if isinstance(schema_version, bool) or not isinstance(
            schema_version,
            int,
        ):
            raise ProspectiveCombinedEntryFilterError(
                "schema_version must be an integer"
            )
        if isinstance(started_at_ms, bool) or not isinstance(
            started_at_ms,
            int,
        ):
            raise ProspectiveCombinedEntryFilterError(
                "started_at_ms must be an integer"
            )
        if not isinstance(candidate_id, str):
            raise ProspectiveCombinedEntryFilterError(
                "candidate_id must be a string"
            )
        try:
            return cls(
                started_at_ms=started_at_ms,
                schema_version=schema_version,
                candidate_id=candidate_id,
            )
        except ValueError as exc:
            raise ProspectiveCombinedEntryFilterError(
                str(exc)
            ) from exc


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
    if (
        fact.market != trade.market
        or fact.direction is not trade.direction
        or fact.feature_snapshot_id != trade.feature_snapshot_id
    ):
        raise ProspectiveCombinedEntryFilterError(
            "combined-filter decision lineage does not match trade"
        )
    return fact


def _rank_for_trade(
    trade: TradeJournalEntry,
    store: ContinuousPaperOpeningRankStore,
) -> ContinuousPaperOpeningRankEvidence | None:
    evidence = store.load(trade.opening_plan_id)
    if evidence is None:
        return None
    if (
        evidence.market != trade.market.canonical
        or evidence.opened_at_ms != trade.opened_at_ms
    ):
        raise ProspectiveCombinedEntryFilterError(
            "combined-filter rank lineage does not match trade"
        )
    return evidence


def prospective_combined_block_reason(
    *,
    direction: Direction,
    lead_strategy: str,
    ordinal: int,
) -> str | None:
    long_trend = (
        direction is Direction.LONG
        and lead_strategy == "trend"
    )
    below_rank_cut = ordinal > TOP10_MAX_ORDINAL
    if long_trend and below_rank_cut:
        return "long_trend_and_rank_above_10"
    if long_trend:
        return "long_trend"
    if below_rank_cut:
        return "rank_above_10"
    return None


def _block_reason(
    trade: TradeJournalEntry,
    lead_strategy: str,
    ordinal: int,
) -> str | None:
    return prospective_combined_block_reason(
        direction=trade.direction,
        lead_strategy=lead_strategy,
        ordinal=ordinal,
    )


def _mean_decimal(
    values: tuple[Decimal, ...],
) -> str | None:
    if not values:
        return None
    return str(sum(values, ZERO) / Decimal(len(values)))


def prospective_combined_entry_filter_summary(
    trades: tuple[TradeJournalEntry, ...],
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    state: ProspectiveCombinedEntryFilterState,
    *,
    profit_lock_outcomes: tuple[ProfitLockTradeOutcome, ...] = (),
) -> dict[str, object]:
    prospective = tuple(
        trade
        for trade in trades
        if trade.opened_at_ms >= state.started_at_ms
    )

    attributed: list[
        tuple[
            TradeJournalEntry,
            ContinuousPaperOpeningRankEvidence,
            str,
            str | None,
        ]
    ] = []
    decision_attribution_misses = 0
    missing_rank_evidence = 0
    stale_rank_evidence = 0

    for trade in prospective:
        fact = _fact_for_trade(trade, fact_store)
        if fact is None or fact.lead_strategy is None:
            decision_attribution_misses += 1
            continue
        rank = _rank_for_trade(trade, rank_store)
        if rank is None:
            missing_rank_evidence += 1
            continue
        if rank.rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            stale_rank_evidence += 1
            continue
        attributed.append(
            (
                trade,
                rank,
                fact.lead_strategy,
                _block_reason(
                    trade,
                    fact.lead_strategy,
                    rank.ordinal,
                ),
            )
        )

    allowed = tuple(
        (trade, rank, lead_strategy)
        for trade, rank, lead_strategy, reason in attributed
        if reason is None
    )
    blocked = tuple(
        (trade, rank, lead_strategy, reason)
        for trade, rank, lead_strategy, reason in attributed
        if reason is not None
    )

    actual_net_pnl = sum(
        (trade.net_pnl for trade, _, _, _ in attributed),
        ZERO,
    )
    allowed_net_pnl = sum(
        (trade.net_pnl for trade, _, _ in allowed),
        ZERO,
    )
    blocked_net_pnl = sum(
        (trade.net_pnl for trade, _, _, _ in blocked),
        ZERO,
    )
    robustness = prospective_filter_robustness(
        tuple(
            (
                trade,
                reason is not None,
            )
            for trade, _rank, _lead_strategy, reason in attributed
        )
    )
    allowed_residual_items = tuple(
        AllowedResidualItem(
            trade,
            lead_strategy=lead_strategy,
            ordinal=rank.ordinal,
        )
        for trade, rank, lead_strategy in allowed
    )
    allowed_residual = prospective_allowed_residual_attribution(
        allowed_residual_items
    )
    residual_profit_lock = prospective_residual_profit_lock_summary(
        allowed_residual_items,
        profit_lock_outcomes,
    )
    fixed_schedule_portfolio = (
        prospective_filter_fixed_schedule_portfolio(
            tuple(
                ProspectiveFilterPortfolioItem(
                    trade,
                    admitted=reason is None,
                )
                for trade, _rank, _lead_strategy, reason in attributed
            )
        )
    )

    reason_names = (
        "long_trend",
        "rank_above_10",
        "long_trend_and_rank_above_10",
    )
    by_block_reason: dict[str, dict[str, object]] = {}
    for reason_name in reason_names:
        cohort = tuple(
            (trade, rank)
            for trade, rank, _lead_strategy, reason in blocked
            if reason == reason_name
        )
        by_block_reason[reason_name] = {
            "trades": len(cohort),
            "wins": sum(
                1 for trade, _ in cohort if trade.net_pnl > ZERO
            ),
            "losses": sum(
                1 for trade, _ in cohort if trade.net_pnl < ZERO
            ),
            "net_pnl": str(
                sum(
                    (trade.net_pnl for trade, _ in cohort),
                    ZERO,
                )
            ),
            "mean_net_r": _mean_decimal(
                tuple(trade.net_r for trade, _ in cohort)
            ),
            "mean_ordinal": (
                None
                if not cohort
                else str(
                    Decimal(
                        sum(
                            rank.ordinal
                            for _, rank in cohort
                        )
                    )
                    / Decimal(len(cohort))
                )
            ),
        }

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
    integrity_clean = (
        decision_attribution_misses == 0
        and missing_rank_evidence == 0
        and stale_rank_evidence == 0
    )
    ready = (
        integrity_clean
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
        "rule": state.payload()["rule"],
        "claim_scope": "prospective_closed_trade_contribution_only",
        "portfolio_counterfactual": False,
        "prospective_closed_trades": len(prospective),
        "attributed_trades": len(attributed),
        "decision_attribution_misses": (
            decision_attribution_misses
        ),
        "missing_rank_evidence": missing_rank_evidence,
        "stale_rank_evidence": stale_rank_evidence,
        "allowed_trades": len(allowed),
        "blocked_trades": len(blocked),
        "allowed_wins": sum(
            1 for trade, _, _ in allowed if trade.net_pnl > ZERO
        ),
        "allowed_losses": sum(
            1 for trade, _, _ in allowed if trade.net_pnl < ZERO
        ),
        "blocked_wins": sum(
            1 for trade, _, _, _ in blocked
            if trade.net_pnl > ZERO
        ),
        "blocked_losses": sum(
            1 for trade, _, _, _ in blocked
            if trade.net_pnl < ZERO
        ),
        "allowed_net_pnl": str(allowed_net_pnl),
        "blocked_net_pnl": str(blocked_net_pnl),
        "decision_block_reason_by_trade_id": {
            trade.trade_id: reason
            for trade, _rank, _lead_strategy, reason in attributed
        },
        "robustness": robustness,
        "allowed_residual": allowed_residual,
        "residual_profit_lock": residual_profit_lock,
        "fixed_schedule_portfolio": fixed_schedule_portfolio,
        "actual_net_pnl": str(actual_net_pnl),
        "candidate_trade_contribution_pnl": str(
            allowed_net_pnl
        ),
        "delta_trade_contribution_pnl": str(
            allowed_net_pnl - actual_net_pnl
        ),
        "actual_mean_net_r": _mean_decimal(
            tuple(
                trade.net_r
                for trade, _, _, _ in attributed
            )
        ),
        "allowed_mean_net_r": _mean_decimal(
            tuple(trade.net_r for trade, _, _ in allowed)
        ),
        "blocked_mean_net_r": _mean_decimal(
            tuple(
                trade.net_r
                for trade, _, _, _ in blocked
            )
        ),
        "allowed_mean_ordinal": (
            None
            if not allowed
            else str(
                Decimal(
                    sum(
                        rank.ordinal
                        for _, rank, _ in allowed
                    )
                )
                / Decimal(len(allowed))
            )
        ),
        "blocked_mean_ordinal": (
            None
            if not blocked
            else str(
                Decimal(
                    sum(
                        rank.ordinal
                        for _, rank, _, _ in blocked
                    )
                )
                / Decimal(len(blocked))
            )
        ),
        "by_block_reason": by_block_reason,
        "readiness": {
            "ready_for_review": ready,
            "integrity_clean": integrity_clean,
            "min_prospective_closed_trades": (
                MIN_PROSPECTIVE_CLOSED_TRADES
            ),
            "min_blocked_trades": MIN_BLOCKED_TRADES,
            "min_allowed_trades": MIN_ALLOWED_TRADES,
            "missing_prospective_closed_trades": missing_total,
            "missing_blocked_trades": missing_blocked,
            "missing_allowed_trades": missing_allowed,
            "requires_zero_decision_attribution_misses": True,
            "requires_zero_missing_rank_evidence": True,
            "requires_zero_stale_rank_evidence": True,
        },
    }


def evaluate_prospective_combined_entry_filter(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    state: ProspectiveCombinedEntryFilterState,
    *,
    profit_lock_outcomes: tuple[ProfitLockTradeOutcome, ...] = (),
) -> dict[str, object]:
    return prospective_combined_entry_filter_summary(
        tuple(journal.iter_trades()),
        fact_store,
        rank_store,
        state,
        profit_lock_outcomes=profit_lock_outcomes,
    )


def prospective_combined_matched_overlap_summary(
    trades: tuple[TradeJournalEntry, ...],
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    entry_filter_state: ProspectiveEntryFilterState,
    top10_rank_filter_state: ProspectiveTop10RankFilterState,
) -> dict[str, object]:
    overlap_started_at_ms = max(
        entry_filter_state.started_at_ms,
        top10_rank_filter_state.started_at_ms,
    )
    overlap = prospective_combined_entry_filter_summary(
        trades,
        fact_store,
        rank_store,
        ProspectiveCombinedEntryFilterState(
            started_at_ms=overlap_started_at_ms,
        ),
    )
    readiness = overlap.get("readiness", {})
    if not isinstance(readiness, dict):
        raise ProspectiveCombinedEntryFilterError(
            "matched overlap readiness must be an object"
        )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "fresh_combined_gate_credit": 0,
        "claim_scope": (
            "matched_standalone_overlap_closed_trade_contribution_only"
        ),
        "entry_filter_started_at_ms": (
            entry_filter_state.started_at_ms
        ),
        "top10_rank_filter_started_at_ms": (
            top10_rank_filter_state.started_at_ms
        ),
        "overlap_started_at_ms": overlap_started_at_ms,
        "closed_trades_since_overlap_start": overlap[
            "prospective_closed_trades"
        ],
        "matched_trades": overlap["attributed_trades"],
        "decision_attribution_misses": overlap[
            "decision_attribution_misses"
        ],
        "missing_rank_evidence": overlap["missing_rank_evidence"],
        "stale_rank_evidence": overlap["stale_rank_evidence"],
        "integrity_clean": readiness.get("integrity_clean", False),
        "allowed_trades": overlap["allowed_trades"],
        "blocked_trades": overlap["blocked_trades"],
        "allowed_wins": overlap["allowed_wins"],
        "allowed_losses": overlap["allowed_losses"],
        "blocked_wins": overlap["blocked_wins"],
        "blocked_losses": overlap["blocked_losses"],
        "allowed_net_pnl": overlap["allowed_net_pnl"],
        "blocked_net_pnl": overlap["blocked_net_pnl"],
        "actual_net_pnl": overlap["actual_net_pnl"],
        "candidate_trade_contribution_pnl": overlap[
            "candidate_trade_contribution_pnl"
        ],
        "delta_trade_contribution_pnl": overlap[
            "delta_trade_contribution_pnl"
        ],
        "by_block_reason": overlap["by_block_reason"],
        "robustness": overlap["robustness"],
        "allowed_residual": overlap["allowed_residual"],
        "fixed_schedule_portfolio": overlap[
            "fixed_schedule_portfolio"
        ],
    }


def evaluate_prospective_combined_matched_overlap(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    entry_filter_state: ProspectiveEntryFilterState,
    top10_rank_filter_state: ProspectiveTop10RankFilterState,
) -> dict[str, object]:
    return prospective_combined_matched_overlap_summary(
        tuple(journal.iter_trades()),
        fact_store,
        rank_store,
        entry_filter_state,
        top10_rank_filter_state,
    )

