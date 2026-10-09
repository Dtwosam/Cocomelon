from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, cast

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
# Match prospective top-10 evidence admissibility; stale ordinals cannot
# establish a trade's entry rank in retrospective loss discovery.
MAX_VERIFIED_ENTRY_RANK_AGE_MS: Final = 300_000
LOSS_STREAK_CONTEXT_SCHEMA_VERSION = 4
DEFAULT_MIN_STREAK_LENGTH = 3
DOMINANT_SHARE_MIN = Decimal("0.75")
RECURRING_STREAK_MIN = 2
CONTEXT_FILTER_SPLIT_FRACTION = Decimal("0.60")
CONTEXT_FILTER_MIN_DISCOVERY_ROWS = 8
CONTEXT_FILTER_MIN_VALIDATION_ROWS = 6
CONTEXT_FILTER_MIN_VALIDATION_MARKETS = 3
CONTEXT_FILTER_MIN_DISCOVERY_LOSS_SHARE = Decimal("0.65")
CONTEXT_FILTER_MIN_VALIDATION_LOSS_SHARE = Decimal("0.60")
CONTEXT_FILTER_BLOCK_COUNT = 2
CONTEXT_FILTER_MIN_BLOCK_ROWS = 2
CONTEXT_FILTER_MIN_BLOCK_LOSS_SHARE = Decimal("0.50")
CONTEXT_FILTER_DIMENSION_SETS: Final = (
    ("lead_strategy", "trend_regime"),
    ("lead_strategy", "volatility_regime"),
    ("lead_strategy", "return_15m_sign"),
    ("lead_strategy", "return_1h_sign"),
    ("lead_strategy", "rank_band"),
    ("lead_strategy", "trend_regime", "volatility_regime"),
    ("lead_strategy", "trend_regime", "direction"),
    ("lead_strategy", "volatility_regime", "direction"),
)


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
    if rank.rank_age_ms > MAX_VERIFIED_ENTRY_RANK_AGE_MS:
        return "stale"
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
        or fact.replay_run_id != run_id
        or fact.strategy_decision_id != trade.strategy_decision_id
        or fact.timestamp_ms > trade.opened_at_ms
    ):
        raise LossStreakContextAuditError(
            "loss-streak decision lineage mismatch or future decision"
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
    if (
        feature.as_of_ms > fact.timestamp_ms
        or feature.source_received_at_ms > fact.timestamp_ms
    ):
        raise LossStreakContextAuditError(
            "loss-streak decision used an unavailable future feature"
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
        "rank_ordinal": (
            None if rank is None
            or rank.rank_age_ms > MAX_VERIFIED_ENTRY_RANK_AGE_MS
            else rank.ordinal
        ),
        "rank_score": (
            None if rank is None
            or rank.rank_age_ms > MAX_VERIFIED_ENTRY_RANK_AGE_MS
            else str(rank.score)
        ),
        "rank_band": _rank_band(rank),
        "rank_age_ms": None if rank is None else rank.rank_age_ms,
        "rank_evidence_status": (
            "missing" if rank is None else
            "stale" if rank.rank_age_ms > MAX_VERIFIED_ENTRY_RANK_AGE_MS
            else "fresh"
        ),
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
        "context_complete": True,
        "context_resolved_trade_count": len(resolved),
        "context_unresolved_trade_count": 0,
        "context_unresolved_reason_counts": {},
    }


def _incomplete_streak_payload(
    streak_index: int,
    trades: tuple[TradeJournalEntry, ...],
    resolved: tuple[_ResolvedLoss, ...],
    unresolved: Counter[str],
) -> dict[str, object]:
    """Retain true journal economics without claiming partial entry-context patterns."""
    if not trades or not unresolved:
        raise ValueError("incomplete streak requires trades and unresolved context")
    return {
        "streak_index": streak_index,
        "length": len(trades),
        "started_at_ms": trades[0].closed_at_ms,
        "ended_at_ms": trades[-1].closed_at_ms,
        "net_pnl": str(sum((trade.net_pnl for trade in trades), ZERO)),
        "net_r": str(sum((trade.net_r for trade in trades), ZERO)),
        "market_count": len({trade.market.canonical for trade in trades}),
        "direction_count": len({trade.direction.value for trade in trades}),
        "stop_triggered_losses": sum(
            trade.exit_reason == "MARK_STOP_TRIGGERED" for trade in trades
        ),
        "dominant_dimensions": (),
        "trades": tuple(_row(item) for item in resolved),
        "context_complete": False,
        "context_resolved_trade_count": len(resolved),
        "context_unresolved_trade_count": sum(unresolved.values()),
        "context_unresolved_reason_counts": dict(sorted(unresolved.items())),
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



def _baseline_attribution_gap_diagnostics(
    trades: tuple[TradeJournalEntry, ...],
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
) -> dict[str, object]:
    # Do not impute missing historical features or silently change the
    # denominator used by discovery and validation.
    ordered = tuple(sorted(
        trades,
        key=lambda item: (
            item.opened_at_ms,
            item.closed_at_ms,
            item.trade_id,
        ),
    ))
    gaps: list[dict[str, object]] = []
    resolved_count = 0
    first_resolved_index: int | None = None
    last_unresolved_index: int | None = None
    for index, trade in enumerate(ordered):
        resolved, reason = _try_resolve(trade, facts, features, ranks)
        if resolved is not None:
            resolved_count += 1
            if first_resolved_index is None:
                first_resolved_index = index
            continue
        last_unresolved_index = index
        gaps.append({
            "trade_id": trade.trade_id,
            "opening_plan_id": trade.opening_plan_id,
            "feature_snapshot_id": trade.feature_snapshot_id,
            "strategy_decision_id": trade.strategy_decision_id,
            "market": trade.market.canonical,
            "direction": trade.direction.value,
            "opened_at_ms": trade.opened_at_ms,
            "closed_at_ms": trade.closed_at_ms,
            "reason": reason or "unresolved",
        })
    prefix_only = (
        bool(gaps)
        and first_resolved_index is not None
        and last_unresolved_index is not None
        and last_unresolved_index < first_resolved_index
    )
    suffix_start_index = (
        0 if last_unresolved_index is None
        else last_unresolved_index + 1
    )
    suffix = ordered[suffix_start_index:]
    return {
        "research_only": True,
        "changes_strategy": False,
        "execution_authority": False,
        "promotion_authority": False,
        "historical_exclusion_authority": False,
        "source_trade_count": len(ordered),
        "resolved_trade_count": resolved_count,
        "unresolved_trade_count": len(gaps),
        "unresolved_trades": gaps,
        "unresolved_strictly_before_first_resolved": prefix_only,
        "first_resolved_opened_at_ms": (
            None if first_resolved_index is None
            else ordered[first_resolved_index].opened_at_ms
        ),
        "fully_attributed_trailing_suffix_trades": len(suffix),
        "trailing_suffix_first_opened_at_ms": (
            None if not suffix else suffix[0].opened_at_ms
        ),
        "trailing_suffix_net_pnl": str(
            sum((trade.net_pnl for trade in suffix), ZERO)
        ),
        "requires_exact_source_recovery_for_full_baseline": bool(gaps),
        "warning": (
            "The trailing suffix is a descriptive availability diagnostic, "
            "not a validated training cohort or license to omit losses. "
            "The full-baseline candidate-freeze gate remains fail closed."
        ),
    }


def try_resolve_entry_context_row(
    trade: TradeJournalEntry,
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
) -> tuple[dict[str, object] | None, str | None]:
    resolved, reason = _try_resolve(
        trade,
        facts,
        features,
        ranks,
    )
    if resolved is None:
        return None, reason
    return _row(resolved), None


def resolved_entry_context_rows(
    trades: tuple[TradeJournalEntry, ...],
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
) -> tuple[tuple[dict[str, object], ...], dict[str, int]]:
    rows, unresolved = _baseline_rows(
        trades,
        facts,
        features,
        ranks,
    )
    return rows, dict(sorted(unresolved.items()))


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


def _context_values(
    row: dict[str, object],
    dimensions: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(str(row[dimension]) for dimension in dimensions)


def _chronological_context_split(
    rows: tuple[dict[str, object], ...],
) -> tuple[
    int | None,
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    if not rows:
        return None, (), ()
    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                cast(int, row["closed_at_ms"]),
                str(row["trade_id"]),
            ),
        )
    )
    timestamps = tuple(
        sorted({cast(int, row["closed_at_ms"]) for row in ordered})
    )
    if len(timestamps) < 2:
        return timestamps[0], ordered, ()
    split_index = int(
        Decimal(len(timestamps)) * CONTEXT_FILTER_SPLIT_FRACTION
    )
    split_index = max(1, min(split_index, len(timestamps) - 1))
    split_timestamp_ms = timestamps[split_index]
    discovery = tuple(
        row
        for row in ordered
        if cast(int, row["closed_at_ms"]) < split_timestamp_ms
    )
    validation = tuple(
        row
        for row in ordered
        if cast(int, row["closed_at_ms"]) >= split_timestamp_ms
    )
    return split_timestamp_ms, discovery, validation


def _context_loss_share(
    rows: tuple[dict[str, object], ...],
) -> Decimal | None:
    if not rows:
        return None
    losses = sum(Decimal(str(row["net_pnl"])) < ZERO for row in rows)
    return Decimal(losses) / Decimal(len(rows))


def _context_filter_delta(
    rows: tuple[dict[str, object], ...],
) -> Decimal:
    return sum(
        (-Decimal(str(row["net_pnl"])) for row in rows),
        ZERO,
    )


def _context_leave_one_trade_min_delta(
    rows: tuple[dict[str, object], ...],
) -> Decimal | None:
    if len(rows) < 2:
        return None
    total = _context_filter_delta(rows)
    return min(
        total + Decimal(str(row["net_pnl"]))
        for row in rows
    )


def _context_leave_one_market_min_delta(
    rows: tuple[dict[str, object], ...],
) -> Decimal | None:
    by_market: dict[str, Decimal] = {}
    for row in rows:
        market = str(row["market"])
        by_market[market] = (
            by_market.get(market, ZERO)
            - Decimal(str(row["net_pnl"]))
        )
    if len(by_market) < 2:
        return None
    total = sum(by_market.values(), ZERO)
    return min(total - value for value in by_market.values())


def _context_blocks(
    rows: tuple[dict[str, object], ...],
) -> tuple[tuple[dict[str, object], ...], ...]:
    if not rows:
        return ()
    timestamps = tuple(
        sorted({cast(int, row["closed_at_ms"]) for row in rows})
    )
    resolved = min(CONTEXT_FILTER_BLOCK_COUNT, len(timestamps))
    blocks: list[tuple[dict[str, object], ...]] = []
    for index in range(resolved):
        start = (len(timestamps) * index) // resolved
        end = (len(timestamps) * (index + 1)) // resolved
        selected = set(timestamps[start:end])
        if selected:
            blocks.append(
                tuple(
                    row
                    for row in rows
                    if cast(int, row["closed_at_ms"]) in selected
                )
            )
    return tuple(blocks)


def _context_recurring_streaks(
    streaks: tuple[dict[str, object], ...],
    *,
    dimensions: tuple[str, ...],
    values: tuple[str, ...],
) -> int:
    count = 0
    for streak in streaks:
        if streak.get("context_complete") is not True:
            continue
        raw = streak.get("trades")
        if not isinstance(raw, tuple):
            raise LossStreakContextAuditError(
                "streak trades are invalid"
            )
        if any(
            isinstance(row, dict)
            and _context_values(row, dimensions) == values
            for row in raw
        ):
            count += 1
    return count


def _context_filter_stability(
    streaks: tuple[dict[str, object], ...],
    baseline_rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    split_timestamp_ms, discovery, validation = (
        _chronological_context_split(baseline_rows)
    )
    candidates: list[dict[str, object]] = []

    for dimensions in CONTEXT_FILTER_DIMENSION_SETS:
        discovery_groups: dict[
            tuple[str, ...],
            list[dict[str, object]],
        ] = {}
        validation_groups: dict[
            tuple[str, ...],
            list[dict[str, object]],
        ] = {}
        for row in discovery:
            discovery_groups.setdefault(
                _context_values(row, dimensions),
                [],
            ).append(row)
        for row in validation:
            validation_groups.setdefault(
                _context_values(row, dimensions),
                [],
            ).append(row)

        for values in sorted(discovery_groups):
            recurring_streaks = _context_recurring_streaks(
                streaks,
                dimensions=dimensions,
                values=values,
            )
            if recurring_streaks < RECURRING_STREAK_MIN:
                continue

            discovery_group = tuple(discovery_groups[values])
            discovery_loss_share = _context_loss_share(discovery_group)
            discovery_delta = _context_filter_delta(discovery_group)
            if (
                len(discovery_group) < CONTEXT_FILTER_MIN_DISCOVERY_ROWS
                or discovery_loss_share is None
                or discovery_loss_share
                < CONTEXT_FILTER_MIN_DISCOVERY_LOSS_SHARE
                or discovery_delta <= ZERO
            ):
                continue

            validation_group = tuple(
                validation_groups.get(values, ())
            )
            validation_loss_share = _context_loss_share(validation_group)
            validation_delta = _context_filter_delta(validation_group)
            validation_markets = len(
                {str(row["market"]) for row in validation_group}
            )
            loo_trade = _context_leave_one_trade_min_delta(
                validation_group
            )
            loo_market = _context_leave_one_market_min_delta(
                validation_group
            )
            blocks = _context_blocks(validation_group)
            block_rows = tuple(len(block) for block in blocks)
            block_loss_shares = tuple(
                _context_loss_share(block) for block in blocks
            )
            block_deltas = tuple(
                _context_filter_delta(block) for block in blocks
            )
            consistent_blocks = sum(
                len(block) >= CONTEXT_FILTER_MIN_BLOCK_ROWS
                and loss_share is not None
                and loss_share >= CONTEXT_FILTER_MIN_BLOCK_LOSS_SHARE
                and delta > ZERO
                for block, loss_share, delta in zip(
                    blocks,
                    block_loss_shares,
                    block_deltas,
                    strict=True,
                )
            )
            stable = (
                len(validation_group) >= CONTEXT_FILTER_MIN_VALIDATION_ROWS
                and validation_markets
                >= CONTEXT_FILTER_MIN_VALIDATION_MARKETS
                and validation_loss_share is not None
                and validation_loss_share
                >= CONTEXT_FILTER_MIN_VALIDATION_LOSS_SHARE
                and validation_delta > ZERO
                and loo_trade is not None
                and loo_trade > ZERO
                and loo_market is not None
                and loo_market > ZERO
                and len(blocks) == CONTEXT_FILTER_BLOCK_COUNT
                and consistent_blocks == CONTEXT_FILTER_BLOCK_COUNT
            )
            candidates.append(
                {
                    "dimensions": dimensions,
                    "values": values,
                    "recurring_loss_streaks": recurring_streaks,
                    "discovery_rows": len(discovery_group),
                    "discovery_markets": len(
                        {str(row["market"]) for row in discovery_group}
                    ),
                    "discovery_loss_share": str(discovery_loss_share),
                    "discovery_filter_delta_pnl": str(discovery_delta),
                    "validation_rows": len(validation_group),
                    "validation_markets": validation_markets,
                    "validation_loss_share": (
                        None
                        if validation_loss_share is None
                        else str(validation_loss_share)
                    ),
                    "validation_filter_delta_pnl": str(validation_delta),
                    "validation_leave_one_trade_min_delta_pnl": (
                        None if loo_trade is None else str(loo_trade)
                    ),
                    "validation_leave_one_market_min_delta_pnl": (
                        None if loo_market is None else str(loo_market)
                    ),
                    "validation_block_rows": block_rows,
                    "validation_block_loss_shares": tuple(
                        None if value is None else str(value)
                        for value in block_loss_shares
                    ),
                    "validation_block_filter_delta_pnl": tuple(
                        str(value) for value in block_deltas
                    ),
                    "validation_blocks_consistent": consistent_blocks,
                    "stable_on_validation": stable,
                    "strategy_authority": False,
                    "risk_authority": False,
                    "execution_authority": False,
                }
            )

    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (
                len(cast(tuple[str, ...], item["dimensions"])),
                cast(tuple[str, ...], item["dimensions"]),
                cast(tuple[str, ...], item["values"]),
            ),
        )
    )
    return {
        "schema_version": 1,
        "split_timestamp_ms": split_timestamp_ms,
        "discovery_rows": len(discovery),
        "validation_rows": len(validation),
        "candidate_count": len(ordered),
        "stable_candidate_count": sum(
            item["stable_on_validation"] is True for item in ordered
        ),
        "candidates": ordered,
        "candidate_dimension_sets": CONTEXT_FILTER_DIMENSION_SETS,
        "direction_only_candidates_allowed": False,
        "lead_strategy_context_required": True,
        "entry_time_context_only": True,
        "realized_net_pnl_economics_required": True,
        "counterfactual_filter_delta_definition": (
            "negative_of_realized_net_pnl_for_matching_trade"
        ),
        "chronological_holdout_required": True,
        "leave_one_trade_robustness_required": True,
        "leave_one_market_robustness_required": True,
        "validation_block_consistency_required": True,
        "prospective_freeze_required_before_strategy_use": True,
        "research_only": True,
        "descriptive_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "promotion_authority": False,
        "execution_authority": False,
    }


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
    qualifying_unresolved: Counter[str] = Counter()
    for index, streak in enumerate(qualifying, start=1):
        resolved: list[_ResolvedLoss] = []
        unresolved: Counter[str] = Counter()
        for trade in streak:
            item, reason = _try_resolve(trade, facts, features, ranks)
            if item is None:
                unresolved[reason or "unresolved"] += 1
            else:
                resolved.append(item)
        if unresolved:
            qualifying_unresolved.update(unresolved)
            payloads.append(
                _incomplete_streak_payload(
                    index, streak, tuple(resolved), unresolved
                )
            )
            continue
        qualifying_resolved.extend(resolved)
        payloads.append(_streak_payload(index, tuple(resolved)))

    ordered = tuple(payloads)
    complete_streaks = tuple(
        streak for streak in ordered if streak["context_complete"] is True
    )
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
    attribution_gaps = _baseline_attribution_gap_diagnostics(
        trades, facts, features, ranks,
    )
    if (
        attribution_gaps["resolved_trade_count"] != len(baseline_rows)
        or attribution_gaps["unresolved_trade_count"]
        != sum(baseline_unresolved.values())
    ):
        raise LossStreakContextAuditError(
            "attribution gap diagnostics diverge from baseline"
        )
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
        if len(complete_streaks) < RECURRING_STREAK_MIN
        else _recurring_patterns(
            complete_streaks,
            qualifying_loss_rows=qualifying_loss_rows,
            baseline_rows=baseline_rows,
            non_loss_rows=non_loss_rows,
            baseline_complete=baseline_complete,
        )
    )
    context_filter_stability = _context_filter_stability(
        complete_streaks,
        baseline_rows,
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
        "max_trade_closed_at_ms": (
            None
            if not trades
            else max(trade.closed_at_ms for trade in trades)
        ),
        "baseline_resolved_trade_count": len(baseline_rows),
        "baseline_unresolved_trade_count": sum(
            baseline_unresolved.values()
        ),
        "baseline_unresolved_reason_counts": dict(
            sorted(baseline_unresolved.items())
        ),
        "baseline_normalization_complete": baseline_complete,
        "baseline_attribution_gaps": attribution_gaps,
        "non_loss_control_trade_count": len(non_loss_rows),
        "qualifying_loss_trade_count": len(qualifying_loss_rows),
        "all_qualifying_loss_trade_count": sum(
            len(streak) for streak in qualifying
        ),
        "qualifying_loss_excluded_partial_resolved_trade_count": sum(
            cast(int, streak["context_resolved_trade_count"])
            for streak in ordered
            if streak["context_complete"] is False
        ),
        "qualifying_loss_unresolved_trade_count": sum(
            qualifying_unresolved.values()
        ),
        "qualifying_loss_unresolved_reason_counts": dict(
            sorted(qualifying_unresolved.items())
        ),
        "complete_qualifying_loss_streak_count": len(complete_streaks),
        "incomplete_qualifying_loss_streak_count": (
            len(ordered) - len(complete_streaks)
        ),
        "recurring_patterns_baseline_normalized": True,
        "normalization_strategy_authority": False,
        "loss_streak_count": len(all_streaks),
        "qualifying_loss_streak_count": len(ordered),
        "current_consecutive_losses": current_length,
        "latest_qualifying_streak": latest,
        "recurring_dominant_patterns": recurring,
        "context_filter_stability": context_filter_stability,
        "streaks": ordered,
    }
