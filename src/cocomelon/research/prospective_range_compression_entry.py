from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_filter_economic_readiness import (
    prospective_filter_economic_readiness,
)
from cocomelon.research.prospective_filter_robustness import (
    prospective_filter_robustness,
)

STATE_SCHEMA_VERSION: Final = 1
CANDIDATE_ID: Final = "prospective-range-compression-entry-v1"
MAX_RANGE_EXPANSION_15M: Final = Decimal("0.80")
EMBARGO_MS: Final = 6 * 60 * 60 * 1_000
MIN_PROSPECTIVE_CLOSED_TRADES: Final = 30
MIN_BLOCKED_TRADES: Final = 5
MIN_ADMITTED_TRADES: Final = 10
MIN_DIRECTION_CLOSED_TRADES: Final = 5
ZERO: Final = Decimal("0")


class ProspectiveRangeCompressionEntryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveRangeCompressionEntryState:
    frozen_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.frozen_at_ms < 0:
            raise ValueError("frozen_at_ms must be non-negative")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("unsupported range-compression state schema")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("unsupported range-compression candidate")

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
                "scope": "all_prospective_trades",
                "max_range_expansion_15m": str(MAX_RANGE_EXPANSION_15M),
                "block_if": "range_expansion_15m_at_or_below_max",
                "missing_feature_action": "admit_fail_open",
                "direction_specific": False,
                "historical_discovery_only": True,
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> "ProspectiveRangeCompressionEntryState":
        if not isinstance(raw, dict):
            raise ProspectiveRangeCompressionEntryError(
                "range-compression state must be an object"
            )
        expected_rule = cls(frozen_at_ms=0).payload()["rule"]
        if raw.get("rule") != expected_rule:
            raise ProspectiveRangeCompressionEntryError(
                "range-compression rule does not match frozen candidate"
            )
        if raw.get("embargo_ms") != EMBARGO_MS:
            raise ProspectiveRangeCompressionEntryError(
                "range-compression embargo does not match frozen candidate"
            )

        schema_version = raw.get("schema_version")
        frozen_at_ms = raw.get("frozen_at_ms")
        started_at_ms = raw.get("started_at_ms")
        candidate_id = raw.get("candidate_id")
        if isinstance(schema_version, bool) or not isinstance(
            schema_version,
            int,
        ):
            raise ProspectiveRangeCompressionEntryError(
                "schema_version must be an integer"
            )
        if isinstance(frozen_at_ms, bool) or not isinstance(
            frozen_at_ms,
            int,
        ):
            raise ProspectiveRangeCompressionEntryError(
                "frozen_at_ms must be an integer"
            )
        if isinstance(started_at_ms, bool) or not isinstance(
            started_at_ms,
            int,
        ):
            raise ProspectiveRangeCompressionEntryError(
                "started_at_ms must be an integer"
            )
        if not isinstance(candidate_id, str):
            raise ProspectiveRangeCompressionEntryError(
                "candidate_id must be a string"
            )
        try:
            state = cls(
                frozen_at_ms=frozen_at_ms,
                schema_version=schema_version,
                candidate_id=candidate_id,
            )
        except ValueError as exc:
            raise ProspectiveRangeCompressionEntryError(
                str(exc)
            ) from exc
        if started_at_ms != state.started_at_ms:
            raise ProspectiveRangeCompressionEntryError(
                "started_at_ms does not match frozen embargo"
            )
        return state


def prospective_range_compression_snapshot_decision(
    feature_store: LearningFeatureSnapshotStore,
    *,
    market: MarketId,
    direction: Direction,
    timestamp_ms: int,
    feature_snapshot_id: str,
) -> dict[str, object]:
    del direction
    detail: dict[str, object] = {
        "feature_snapshot_id": feature_snapshot_id,
        "feature_record_sha256": None,
        "decision": "ADMIT",
        "reason": "missing_feature_fail_open",
    }
    try:
        verified = feature_store.load(feature_snapshot_id)
    except Exception as exc:
        raise ProspectiveRangeCompressionEntryError(
            "opening feature snapshot could not be verified"
        ) from exc
    if verified is None:
        return detail

    snapshot = verified.snapshot
    detail["feature_record_sha256"] = verified.record_sha256
    if snapshot.market != market:
        raise ProspectiveRangeCompressionEntryError(
            "opening feature market does not match trade"
        )
    if snapshot.as_of_ms > timestamp_ms:
        raise ProspectiveRangeCompressionEntryError(
            "opening feature snapshot is from the future"
        )
    range_expansion = snapshot.range_expansion_15m
    if range_expansion is None:
        detail["reason"] = "incomplete_feature_fail_open"
        return detail

    should_block = range_expansion <= MAX_RANGE_EXPANSION_15M
    detail.update(
        {
            "range_expansion_15m": str(range_expansion),
            "decision": "BLOCK" if should_block else "ADMIT",
            "reason": (
                "range_compression"
                if should_block
                else "range_compression_pass"
            ),
        }
    )
    return detail


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
    candidate_r = sum((trade.net_r for trade in admitted), ZERO)
    return {
        "closed_trades": len(values),
        "admitted_trades": len(admitted),
        "blocked_trades": len(blocked),
        "blocked_winners": sum(
            1 for trade in blocked if trade.net_pnl > ZERO
        ),
        "blocked_losses": sum(
            1 for trade in blocked if trade.net_pnl < ZERO
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


def prospective_range_compression_entry_summary(
    trades: Sequence[TradeJournalEntry],
    feature_store: LearningFeatureSnapshotStore,
    state: ProspectiveRangeCompressionEntryState,
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
        raise ProspectiveRangeCompressionEntryError(
            "prospective trades contain duplicate trade ids"
        )

    blocked_ids: set[str] = set()
    admitted_ids: set[str] = set()
    missing_feature_ids: set[str] = set()
    decision_details: dict[str, dict[str, object]] = {}

    for trade in prospective:
        detail = prospective_range_compression_snapshot_decision(
            feature_store,
            market=trade.market,
            direction=trade.direction,
            timestamp_ms=trade.opened_at_ms,
            feature_snapshot_id=trade.feature_snapshot_id,
        )
        if detail["reason"] in {
            "missing_feature_fail_open",
            "incomplete_feature_fail_open",
        }:
            missing_feature_ids.add(trade.trade_id)
        if detail["decision"] == "BLOCK":
            blocked_ids.add(trade.trade_id)
        else:
            admitted_ids.add(trade.trade_id)
        decision_details[trade.trade_id] = detail

    if admitted_ids & blocked_ids:
        raise ProspectiveRangeCompressionEntryError(
            "trade cannot be both admitted and blocked"
        )
    if len(admitted_ids | blocked_ids) != len(prospective):
        raise ProspectiveRangeCompressionEntryError(
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
    actual_r = sum((trade.net_r for trade in prospective), ZERO)
    candidate_r = sum((trade.net_r for trade in admitted), ZERO)
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
                1 for trade in cohort if trade.net_pnl > ZERO
            ),
            "losses": sum(
                1 for trade in cohort if trade.net_pnl < ZERO
            ),
            "net_pnl": str(
                sum((trade.net_pnl for trade in cohort), ZERO)
            ),
            "net_r": str(
                sum((trade.net_r for trade in cohort), ZERO)
            ),
        }

    long_closed = by_direction[Direction.LONG.value]["closed_trades"]
    short_closed = by_direction[Direction.SHORT.value]["closed_trades"]
    if (
        isinstance(long_closed, bool)
        or not isinstance(long_closed, int)
        or isinstance(short_closed, bool)
        or not isinstance(short_closed, int)
    ):
        raise ProspectiveRangeCompressionEntryError(
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
    feature_integrity_clean = not missing_feature_ids
    sample_complete = (
        missing_total == 0
        and missing_blocked == 0
        and missing_admitted == 0
        and missing_long == 0
        and missing_short == 0
        and feature_integrity_clean
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
    economics_positive = candidate_profitable and improvement_positive
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
        "changes_execution": False,
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
            1 for trade in blocked if trade.net_pnl > ZERO
        ),
        "blocked_losses": sum(
            1 for trade in blocked if trade.net_pnl < ZERO
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
        "feature_evaluated_trades": (
            len(prospective) - len(missing_feature_ids)
        ),
        "missing_feature_trades": len(missing_feature_ids),
        "missing_feature_trade_ids": sorted(missing_feature_ids),
        "decision_details": {
            trade_id: decision_details[trade_id]
            for trade_id in sorted(decision_details)
        },
        "by_direction": by_direction,
        "blocked_by_market": blocked_by_market,
        "robustness": robustness,
        "economic_readiness": economic_readiness,
        "readiness": {
            "ready_for_review": ready_for_review,
            "sample_complete": sample_complete,
            "feature_integrity_clean": feature_integrity_clean,
            "candidate_profitable": candidate_profitable,
            "improvement_positive": improvement_positive,
            "economics_positive": economics_positive,
            "candidate_single_trade_robust": candidate_trade_robust,
            "candidate_single_market_robust": candidate_market_robust,
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
            "missing_feature_trades": len(missing_feature_ids),
        },
    }


def evaluate_prospective_range_compression_entry(
    journal: JournalStore,
    feature_store: LearningFeatureSnapshotStore,
    state: ProspectiveRangeCompressionEntryState,
) -> dict[str, object]:
    return prospective_range_compression_entry_summary(
        tuple(journal.iter_trades()),
        feature_store,
        state,
    )
