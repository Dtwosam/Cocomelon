from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import FeatureSnapshot
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")
LOSS_STREAK_CONTEXT_SCHEMA_VERSION = 2
DEFAULT_MIN_STREAK_LENGTH = 3
DOMINANT_SHARE_MIN = Decimal("0.75")
RECURRING_STREAK_MIN = 2


class LossStreakContextAuditError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ResolvedLoss:
    trade: TradeJournalEntry
    fact: DecisionEvaluationFact
    feature: FeatureSnapshot
    rank: ContinuousPaperOpeningRankEvidence | None


def _sign(value: Decimal | None) -> str:
    if value is None:
        return "missing"
    if value > ZERO:
        return "positive"
    if value < ZERO:
        return "negative"
    return "flat"


def _rank_band(rank: ContinuousPaperOpeningRankEvidence | None) -> str:
    if rank is None:
        return "missing"
    if rank.ordinal <= 3:
        return "top3"
    if rank.ordinal <= 10:
        return "top10"
    return "outside10"


def _loss_streaks(
    trades: tuple[TradeJournalEntry, ...],
) -> tuple[tuple[TradeJournalEntry, ...], ...]:
    ordered = tuple(
        sorted(
            trades,
            key=lambda item: (item.closed_at_ms, item.trade_id),
        )
    )
    streaks: list[tuple[TradeJournalEntry, ...]] = []
    current: list[TradeJournalEntry] = []
    for trade in ordered:
        if trade.net_pnl < ZERO:
            current.append(trade)
            continue
        if current:
            streaks.append(tuple(current))
            current = []
    if current:
        streaks.append(tuple(current))
    return tuple(streaks)


def _try_resolve(
    trade: TradeJournalEntry,
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
) -> tuple[_ResolvedLoss | None, str | None]:
    run_id = trade.replay_run_id
    if run_id is None:
        return None, "missing replay_run_id"
    fact = facts.load_decision_by_strategy_id(
        trade.strategy_decision_id,
        run_id,
    )
    if fact is None:
        return None, "missing decision fact"
    if (
        fact.market != trade.market
        or fact.direction is not trade.direction
        or fact.feature_snapshot_id != trade.feature_snapshot_id
    ):
        raise LossStreakContextAuditError(
            "loss-streak decision lineage mismatch"
        )

    verified = features.load(trade.feature_snapshot_id)
    if verified is None:
        return None, "missing feature snapshot"
    feature = verified.snapshot
    if feature.market != trade.market:
        raise LossStreakContextAuditError(
            "loss-streak feature market mismatch"
        )
    if (
        feature.as_of_ms > trade.opened_at_ms
        or feature.source_received_at_ms > trade.opened_at_ms
    ):
        raise LossStreakContextAuditError(
            "loss-streak feature is from after entry"
        )

    rank = ranks.load(trade.opening_plan_id)
    if rank is not None and (
        rank.market != trade.market.canonical
        or rank.opened_at_ms != trade.opened_at_ms
    ):
        raise LossStreakContextAuditError(
            "loss-streak opening rank lineage mismatch"
        )
    return (
        _ResolvedLoss(
            trade=trade,
            fact=fact,
            feature=feature,
            rank=rank,
        ),
        None,
    )


def _resolve(
    trade: TradeJournalEntry,
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
) -> _ResolvedLoss:
    resolved, unresolved_reason = _try_resolve(
        trade,
        facts,
        features,
        ranks,
    )
    if resolved is None:
        raise LossStreakContextAuditError(
            "loss-streak trade is "
            f"{unresolved_reason or 'unresolved'}"
        )
    return resolved

def _row(item: _ResolvedLoss) -> dict[str, object]:
    trade = item.trade
    fact = item.fact
    feature = item.feature
    rank = item.rank
    return {
        "trade_id": trade.trade_id,
        "market": trade.market.canonical,
        "direction": trade.direction.value,
        "opened_at_ms": trade.opened_at_ms,
        "closed_at_ms": trade.closed_at_ms,
        "holding_duration_ms": trade.holding_duration_ms,
        "exit_reason": trade.exit_reason,
        "net_pnl": str(trade.net_pnl),
        "net_r": str(trade.net_r),
        "lead_strategy": fact.lead_strategy or "unknown",
        "decision_score": str(fact.score),
        "decision_reason_codes": fact.reason_codes,
        "trend_regime": feature.trend_regime.value,
        "volatility_regime": feature.volatility_regime.value,
        "return_15m_sign": _sign(feature.return_15m),
        "return_1h_sign": _sign(feature.return_1h),
        "funding_sign": _sign(feature.funding),
        "book_imbalance_sign": _sign(feature.book_imbalance),
        "spread_bps": (
            None if feature.spread_bps is None else str(feature.spread_bps)
        ),
        "book_age_ms": feature.book_age_ms,
        "rank_ordinal": None if rank is None else rank.ordinal,
        "rank_score": None if rank is None else str(rank.score),
        "rank_band": _rank_band(rank),
    }


def _dominant(
    rows: tuple[dict[str, object], ...],
    field: str,
) -> dict[str, object]:
    counts = Counter(str(row[field]) for row in rows)
    if not counts:
        return {
            "field": field,
            "value": None,
            "count": 0,
            "share": None,
            "dominant": False,
        }
    value, count = sorted(
        counts.items(),
        key=lambda item: (-item[1], item[0]),
    )[0]
    share = Decimal(count) / Decimal(len(rows))
    return {
        "field": field,
        "value": value,
        "count": count,
        "share": str(share),
        "dominant": share >= DOMINANT_SHARE_MIN,
    }


DOMINANT_FIELDS: Final = (
    "direction",
    "exit_reason",
    "lead_strategy",
    "trend_regime",
    "volatility_regime",
    "return_15m_sign",
    "return_1h_sign",
    "funding_sign",
    "book_imbalance_sign",
    "rank_band",
)


def _streak_payload(
    streak_index: int,
    resolved: tuple[_ResolvedLoss, ...],
) -> dict[str, object]:
    rows = tuple(_row(item) for item in resolved)
    dominant = tuple(
        _dominant(rows, field)
        for field in DOMINANT_FIELDS
    )
    trade_count = len(rows)
    return {
        "streak_index": streak_index,
        "length": trade_count,
        "started_at_ms": resolved[0].trade.closed_at_ms,
        "ended_at_ms": resolved[-1].trade.closed_at_ms,
        "net_pnl": str(
            sum((item.trade.net_pnl for item in resolved), ZERO)
        ),
        "net_r": str(
            sum((item.trade.net_r for item in resolved), ZERO)
        ),
        "market_count": len(
            {item.trade.market.canonical for item in resolved}
        ),
        "direction_count": len(
            {item.trade.direction.value for item in resolved}
        ),
        "stop_triggered_losses": sum(
            item.trade.exit_reason == "MARK_STOP_TRIGGERED"
            for item in resolved
        ),
        "dominant_dimensions": dominant,
        "trades": rows,
    }


def _share(
    rows: tuple[dict[str, object], ...],
    *,
    field: str,
    value: str,
) -> tuple[int, Decimal | None]:
    if not rows:
        return 0, None
    count = sum(str(row[field]) == value for row in rows)
    return count, Decimal(count) / Decimal(len(rows))


def _baseline_rows(
    trades: tuple[TradeJournalEntry, ...],
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
) -> tuple[tuple[dict[str, object], ...], Counter[str]]:
    rows: list[dict[str, object]] = []
    unresolved: Counter[str] = Counter()
    for trade in trades:
        resolved, reason = _try_resolve(
            trade,
            facts,
            features,
            ranks,
        )
        if resolved is None:
            unresolved[reason or "unresolved"] += 1
            continue
        rows.append(_row(resolved))
    return tuple(rows), unresolved


def _recurring_patterns(
    streaks: tuple[dict[str, object], ...],
    *,
    qualifying_loss_rows: tuple[dict[str, object], ...],
    baseline_rows: tuple[dict[str, object], ...],
    non_loss_rows: tuple[dict[str, object], ...],
    baseline_complete: bool,
) -> tuple[dict[str, object], ...]:
    recurring: list[dict[str, object]] = []
    for field in DOMINANT_FIELDS:
        appearances: Counter[str] = Counter()
        for streak in streaks:
            raw = streak["dominant_dimensions"]
            if not isinstance(raw, tuple):
                raise LossStreakContextAuditError(
                    "streak dominant dimensions are invalid"
                )
            for item in raw:
                if (
                    isinstance(item, dict)
                    and item.get("field") == field
                    and item.get("dominant") is True
                    and isinstance(item.get("value"), str)
                ):
                    appearances[item["value"]] += 1
        for value, count in sorted(
            appearances.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            if count < RECURRING_STREAK_MIN:
                continue
            loss_count, loss_share = _share(
                qualifying_loss_rows,
                field=field,
                value=value,
            )
            baseline_count, baseline_share = _share(
                baseline_rows,
                field=field,
                value=value,
            )
            non_loss_count, non_loss_share = _share(
                non_loss_rows,
                field=field,
                value=value,
            )
            share_lift = (
                None
                if loss_share is None or baseline_share is None
                else loss_share - baseline_share
            )
            loss_vs_non_loss_delta = (
                None
                if loss_share is None or non_loss_share is None
                else loss_share - non_loss_share
            )
            recurring.append(
                {
                    "field": field,
                    "value": value,
                    "qualifying_streaks": count,
                    "streak_share": str(
                        Decimal(count) / Decimal(len(streaks))
                    ),
                    "entry_time_context": field != "exit_reason",
                    "qualifying_loss_trade_count": loss_count,
                    "qualifying_loss_trade_share": (
                        None if loss_share is None else str(loss_share)
                    ),
                    "baseline_trade_count": baseline_count,
                    "baseline_trade_share": (
                        None
                        if baseline_share is None
                        else str(baseline_share)
                    ),
                    "loss_share_lift_vs_baseline": (
                        None
                        if share_lift is None
                        else str(share_lift)
                    ),
                    "non_loss_trade_count": non_loss_count,
                    "non_loss_trade_share": (
                        None
                        if non_loss_share is None
                        else str(non_loss_share)
                    ),
                    "loss_share_delta_vs_non_loss": (
                        None
                        if loss_vs_non_loss_delta is None
                        else str(loss_vs_non_loss_delta)
                    ),
                    "baseline_complete": baseline_complete,
                    "strategy_authority": False,
                }
            )
    return tuple(recurring)

def loss_streak_context_audit(
    trades: tuple[TradeJournalEntry, ...],
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
    *,
    min_streak_length: int = DEFAULT_MIN_STREAK_LENGTH,
) -> dict[str, object]:
    if min_streak_length <= 1:
        raise ValueError("min_streak_length must be greater than one")

    all_streaks = _loss_streaks(trades)
    qualifying = tuple(
        streak
        for streak in all_streaks
        if len(streak) >= min_streak_length
    )
    payloads: list[dict[str, object]] = []
    qualifying_resolved: list[_ResolvedLoss] = []
    for index, streak in enumerate(qualifying, start=1):
        resolved = tuple(
            _resolve(trade, facts, features, ranks)
            for trade in streak
        )
        qualifying_resolved.extend(resolved)
        payloads.append(_streak_payload(index, resolved))

    ordered = tuple(payloads)
    qualifying_loss_rows = tuple(
        _row(item) for item in qualifying_resolved
    )
    baseline_rows, baseline_unresolved = _baseline_rows(
        trades,
        facts,
        features,
        ranks,
    )
    non_loss_rows = tuple(
        row
        for row in baseline_rows
        if Decimal(str(row["net_pnl"])) >= ZERO
    )
    baseline_complete = not baseline_unresolved
    current_length = (
        len(all_streaks[-1])
        if all_streaks
        and tuple(
            sorted(
                trades,
                key=lambda item: (item.closed_at_ms, item.trade_id),
            )
        )[-1].net_pnl < ZERO
        else 0
    )
    latest = None if not ordered else ordered[-1]
    recurring = (
        ()
        if len(ordered) < RECURRING_STREAK_MIN
        else _recurring_patterns(
            ordered,
            qualifying_loss_rows=qualifying_loss_rows,
            baseline_rows=baseline_rows,
            non_loss_rows=non_loss_rows,
            baseline_complete=baseline_complete,
        )
    )
    return {
        "research_only": True,
        "descriptive_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "schema_version": LOSS_STREAK_CONTEXT_SCHEMA_VERSION,
        "min_streak_length": min_streak_length,
        "dominant_share_min": str(DOMINANT_SHARE_MIN),
        "recurring_streak_min": RECURRING_STREAK_MIN,
        "trade_count": len(trades),
        "baseline_resolved_trade_count": len(baseline_rows),
        "baseline_unresolved_trade_count": sum(
            baseline_unresolved.values()
        ),
        "baseline_unresolved_reason_counts": dict(
            sorted(baseline_unresolved.items())
        ),
        "baseline_normalization_complete": baseline_complete,
        "non_loss_control_trade_count": len(non_loss_rows),
        "qualifying_loss_trade_count": len(qualifying_loss_rows),
        "recurring_patterns_baseline_normalized": True,
        "normalization_strategy_authority": False,
        "loss_streak_count": len(all_streaks),
        "qualifying_loss_streak_count": len(ordered),
        "current_consecutive_losses": current_length,
        "latest_qualifying_streak": latest,
        "recurring_dominant_patterns": recurring,
        "streaks": ordered,
    }
