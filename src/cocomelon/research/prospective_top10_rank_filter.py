from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.prospective_filter_robustness import (
    prospective_filter_robustness,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
    ContinuousPaperOpeningRankStore,
)

TOP10_RANK_FILTER_STATE_SCHEMA_VERSION: Final = 1
TOP10_RANK_FILTER_CANDIDATE_ID: Final = "prospective-admit-top10-rank-v1"
TOP10_MAX_ORDINAL: Final = 10
MAX_ACCEPTED_RANK_AGE_MS: Final = 300_000
MIN_PROSPECTIVE_CLOSED_TRADES: Final = 30
MIN_BLOCKED_TRADES: Final = 10
MIN_ALLOWED_TRADES: Final = 10
ZERO: Final = Decimal("0")


class ProspectiveTop10RankFilterError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveTop10RankFilterState:
    started_at_ms: int
    schema_version: int = TOP10_RANK_FILTER_STATE_SCHEMA_VERSION
    candidate_id: str = TOP10_RANK_FILTER_CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if self.schema_version != TOP10_RANK_FILTER_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported top10-rank-filter state schema")
        if self.candidate_id != TOP10_RANK_FILTER_CANDIDATE_ID:
            raise ValueError("unsupported top10-rank-filter candidate")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "rule": {
                "max_admitted_ordinal": TOP10_MAX_ORDINAL,
                "action_above_threshold": "reject",
                "max_rank_age_ms": MAX_ACCEPTED_RANK_AGE_MS,
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveTop10RankFilterState:
        if not isinstance(raw, dict):
            raise ProspectiveTop10RankFilterError(
                "top10-rank-filter state must be an object"
            )
        expected_rule = {
            "max_admitted_ordinal": TOP10_MAX_ORDINAL,
            "action_above_threshold": "reject",
            "max_rank_age_ms": MAX_ACCEPTED_RANK_AGE_MS,
        }
        if raw.get("rule") != expected_rule:
            raise ProspectiveTop10RankFilterError(
                "top10-rank-filter rule does not match frozen candidate"
            )
        schema_version = raw.get("schema_version")
        started_at_ms = raw.get("started_at_ms")
        candidate_id = raw.get("candidate_id")
        if isinstance(schema_version, bool) or not isinstance(
            schema_version,
            int,
        ):
            raise ProspectiveTop10RankFilterError(
                "schema_version must be an integer"
            )
        if isinstance(started_at_ms, bool) or not isinstance(
            started_at_ms,
            int,
        ):
            raise ProspectiveTop10RankFilterError(
                "started_at_ms must be an integer"
            )
        if not isinstance(candidate_id, str):
            raise ProspectiveTop10RankFilterError(
                "candidate_id must be a string"
            )
        try:
            return cls(
                started_at_ms=started_at_ms,
                schema_version=schema_version,
                candidate_id=candidate_id,
            )
        except ValueError as exc:
            raise ProspectiveTop10RankFilterError(str(exc)) from exc


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
        raise ProspectiveTop10RankFilterError(
            "opening-rank evidence does not match trade"
        )
    return evidence


def _mean_decimal(
    values: tuple[Decimal, ...],
) -> str | None:
    if not values:
        return None
    return str(sum(values, ZERO) / Decimal(len(values)))


def prospective_top10_rank_filter_summary(
    trades: tuple[TradeJournalEntry, ...],
    store: ContinuousPaperOpeningRankStore,
    state: ProspectiveTop10RankFilterState,
) -> dict[str, object]:
    prospective = tuple(
        trade
        for trade in trades
        if trade.opened_at_ms >= state.started_at_ms
    )
    attributed: list[
        tuple[TradeJournalEntry, ContinuousPaperOpeningRankEvidence]
    ] = []
    missing_rank_evidence = 0
    stale_rank_evidence = 0

    for trade in prospective:
        evidence = _rank_for_trade(trade, store)
        if evidence is None:
            missing_rank_evidence += 1
            continue
        if evidence.rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            stale_rank_evidence += 1
            continue
        attributed.append((trade, evidence))

    allowed = tuple(
        (trade, evidence)
        for trade, evidence in attributed
        if evidence.ordinal <= TOP10_MAX_ORDINAL
    )
    blocked = tuple(
        (trade, evidence)
        for trade, evidence in attributed
        if evidence.ordinal > TOP10_MAX_ORDINAL
    )

    actual_net_pnl = sum(
        (trade.net_pnl for trade, _ in attributed),
        ZERO,
    )
    allowed_net_pnl = sum(
        (trade.net_pnl for trade, _ in allowed),
        ZERO,
    )
    blocked_net_pnl = sum(
        (trade.net_pnl for trade, _ in blocked),
        ZERO,
    )
    robustness = prospective_filter_robustness(
        tuple(
            (
                trade,
                evidence.ordinal > TOP10_MAX_ORDINAL,
            )
            for trade, evidence in attributed
        )
    )
    actual_net_r = tuple(
        trade.net_r for trade, _ in attributed
    )
    allowed_net_r = tuple(
        trade.net_r for trade, _ in allowed
    )
    blocked_net_r = tuple(
        trade.net_r for trade, _ in blocked
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
        missing_rank_evidence == 0
        and stale_rank_evidence == 0
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
            "max_admitted_ordinal": TOP10_MAX_ORDINAL,
            "action_above_threshold": "reject",
            "max_rank_age_ms": MAX_ACCEPTED_RANK_AGE_MS,
        },
        "claim_scope": "closed_trade_contribution_only",
        "portfolio_counterfactual": False,
        "prospective_closed_trades": len(prospective),
        "attributed_trades": len(attributed),
        "missing_rank_evidence": missing_rank_evidence,
        "stale_rank_evidence": stale_rank_evidence,
        "allowed_trades": len(allowed),
        "blocked_trades": len(blocked),
        "allowed_wins": sum(
            1 for trade, _ in allowed if trade.net_pnl > ZERO
        ),
        "allowed_losses": sum(
            1 for trade, _ in allowed if trade.net_pnl < ZERO
        ),
        "blocked_wins": sum(
            1 for trade, _ in blocked if trade.net_pnl > ZERO
        ),
        "blocked_losses": sum(
            1 for trade, _ in blocked if trade.net_pnl < ZERO
        ),
        "allowed_net_pnl": str(allowed_net_pnl),
        "blocked_net_pnl": str(blocked_net_pnl),
        "robustness": robustness,
        "actual_net_pnl": str(actual_net_pnl),
        "candidate_trade_contribution_pnl": str(
            allowed_net_pnl
        ),
        "delta_trade_contribution_pnl": str(
            allowed_net_pnl - actual_net_pnl
        ),
        "actual_mean_net_r": _mean_decimal(actual_net_r),
        "allowed_mean_net_r": _mean_decimal(allowed_net_r),
        "blocked_mean_net_r": _mean_decimal(blocked_net_r),
        "allowed_mean_ordinal": (
            None
            if not allowed
            else str(
                Decimal(
                    sum(
                        evidence.ordinal
                        for _, evidence in allowed
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
                        evidence.ordinal
                        for _, evidence in blocked
                    )
                )
                / Decimal(len(blocked))
            )
        ),
        "mean_rank_age_ms": (
            None
            if not attributed
            else sum(
                evidence.rank_age_ms
                for _, evidence in attributed
            )
            // len(attributed)
        ),
        "max_rank_age_ms": (
            None
            if not attributed
            else max(
                evidence.rank_age_ms
                for _, evidence in attributed
            )
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
            "requires_zero_missing_rank_evidence": True,
            "requires_zero_stale_rank_evidence": True,
        },
    }


def evaluate_prospective_top10_rank_filter(
    journal: JournalStore,
    store: ContinuousPaperOpeningRankStore,
    state: ProspectiveTop10RankFilterState,
) -> dict[str, object]:
    return prospective_top10_rank_filter_summary(
        tuple(journal.iter_trades()),
        store,
        state,
    )
