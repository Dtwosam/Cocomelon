from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Literal

from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    OpportunityRank,
    ScoreComponent,
)
from cocomelon.features.math import percentile_rank

ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")

COARSE_WEIGHTS: dict[str, Decimal] = {
    "abs_day_return": Decimal("0.30"),
    "day_notional_volume": Decimal("0.25"),
    "open_interest": Decimal("0.20"),
    "abs_oi_change": Decimal("0.15"),
    "abs_funding": Decimal("0.10"),
}

ENRICHED_WEIGHTS: dict[str, Decimal] = {
    "coarse_score": Decimal("0.25"),
    "abs_return_15m": Decimal("0.15"),
    "abs_return_1h": Decimal("0.10"),
    "relative_volume_15m": Decimal("0.15"),
    "realized_vol_15m": Decimal("0.10"),
    "range_deviation": Decimal("0.10"),
    "abs_oi_change": Decimal("0.10"),
    "book_quality": Decimal("0.05"),
}


def _unique_snapshots(snapshots: Sequence[FeatureSnapshot]) -> dict[str, FeatureSnapshot]:
    result: dict[str, FeatureSnapshot] = {}
    for snapshot in snapshots:
        key = snapshot.market.canonical
        if key in result:
            raise ValueError(f"duplicate feature snapshot for market {key}")
        result[key] = snapshot
    return result


def _unique_decisions(
    decisions: Sequence[EligibilityDecision],
) -> dict[str, EligibilityDecision]:
    result: dict[str, EligibilityDecision] = {}
    for decision in decisions:
        key = decision.market.canonical
        if key in result:
            raise ValueError(f"duplicate eligibility decision for market {key}")
        result[key] = decision
    return result


def _coarse_raw(snapshot: FeatureSnapshot) -> dict[str, Decimal | None]:
    return {
        "abs_day_return": None if snapshot.day_return is None else abs(snapshot.day_return),
        "day_notional_volume": snapshot.day_notional_volume,
        "open_interest": snapshot.open_interest,
        "abs_oi_change": (
            None if snapshot.oi_change_fraction is None else abs(snapshot.oi_change_fraction)
        ),
        "abs_funding": abs(snapshot.funding),
    }


def _normalized_weights(
    names: Sequence[str],
    base_weights: Mapping[str, Decimal],
) -> dict[str, Decimal]:
    if not names:
        raise ValueError("at least one score component is required")
    total = sum((base_weights[name] for name in names), ZERO)
    if total <= ZERO:
        raise ValueError("available component weight must be positive")

    normalized: dict[str, Decimal] = {}
    accumulated = ZERO
    for index, name in enumerate(names):
        if index == len(names) - 1:
            value = ONE - accumulated
        else:
            value = base_weights[name] / total
            accumulated += value
        normalized[name] = value
    return normalized


def _percentile_universes(
    raw_by_market: Mapping[str, Mapping[str, Decimal | None]],
    names: Sequence[str],
) -> dict[str, tuple[Decimal, ...]]:
    return {
        name: tuple(
            raw[name]
            for raw in raw_by_market.values()
            if raw.get(name) is not None and isinstance(raw[name], Decimal)
        )
        for name in names
    }


def _score_components(
    raw_by_market: Mapping[str, Mapping[str, Decimal | None]],
    base_weights: Mapping[str, Decimal],
) -> dict[str, tuple[tuple[ScoreComponent, ...], Decimal]]:
    names = tuple(base_weights)
    universes = _percentile_universes(raw_by_market, names)
    scored: dict[str, tuple[tuple[ScoreComponent, ...], Decimal]] = {}

    for market, raw in raw_by_market.items():
        available_names = tuple(name for name in names if raw.get(name) is not None)
        normalized_weights = _normalized_weights(available_names, base_weights)
        components: list[ScoreComponent] = []
        for name in available_names:
            raw_value = raw[name]
            assert isinstance(raw_value, Decimal)
            percentile = percentile_rank(universes[name], raw_value)
            weight = normalized_weights[name]
            components.append(
                ScoreComponent(
                    name=name,
                    raw_value=raw_value,
                    percentile=percentile,
                    weight=weight,
                    contribution=percentile * weight,
                )
            )
        component_tuple = tuple(components)
        score = sum((component.contribution for component in component_tuple), ZERO)
        scored[market] = (component_tuple, score)
    return scored


def _book_quality_raw(
    snapshots: Mapping[str, FeatureSnapshot],
) -> dict[str, Decimal]:
    usable = {
        key: snapshot
        for key, snapshot in snapshots.items()
        if snapshot.spread_bps is not None
        and snapshot.bid_depth_25bps is not None
        and snapshot.ask_depth_25bps is not None
    }
    if not usable:
        return {}

    inverse_spreads = tuple(
        -snapshot.spread_bps
        for snapshot in usable.values()
        if snapshot.spread_bps is not None
    )
    side_depths = tuple(
        min(snapshot.bid_depth_25bps, snapshot.ask_depth_25bps)
        for snapshot in usable.values()
        if snapshot.bid_depth_25bps is not None and snapshot.ask_depth_25bps is not None
    )
    result: dict[str, Decimal] = {}
    for key, snapshot in usable.items():
        assert snapshot.spread_bps is not None
        assert snapshot.bid_depth_25bps is not None
        assert snapshot.ask_depth_25bps is not None
        spread_quality = percentile_rank(inverse_spreads, -snapshot.spread_bps)
        depth_quality = percentile_rank(
            side_depths,
            min(snapshot.bid_depth_25bps, snapshot.ask_depth_25bps),
        )
        result[key] = (spread_quality + depth_quality) / TWO
    return result


def _enriched_raw(
    snapshot: FeatureSnapshot,
    *,
    coarse_score: Decimal,
    book_quality: Decimal | None,
) -> dict[str, Decimal | None]:
    return {
        "coarse_score": coarse_score,
        "abs_return_15m": (
            None if snapshot.return_15m is None else abs(snapshot.return_15m)
        ),
        "abs_return_1h": None if snapshot.return_1h is None else abs(snapshot.return_1h),
        "relative_volume_15m": snapshot.relative_volume_15m,
        "realized_vol_15m": snapshot.realized_vol_15m,
        "range_deviation": (
            None
            if snapshot.range_expansion_15m is None
            else abs(snapshot.range_expansion_15m - ONE)
        ),
        "abs_oi_change": (
            None if snapshot.oi_change_fraction is None else abs(snapshot.oi_change_fraction)
        ),
        "book_quality": book_quality,
    }


def rank_opportunities(
    snapshots: Sequence[FeatureSnapshot],
    decisions: Sequence[EligibilityDecision],
    *,
    mode: Literal["coarse", "enriched"],
) -> tuple[OpportunityRank, ...]:
    if mode not in ("coarse", "enriched"):
        raise ValueError(f"unsupported ranking mode: {mode}")

    snapshot_map = _unique_snapshots(snapshots)
    decision_map = _unique_decisions(decisions)
    if set(snapshot_map) != set(decision_map):
        raise ValueError("snapshots and decisions must cover the same markets")

    rankable = {
        key: snapshot
        for key, snapshot in snapshot_map.items()
        if decision_map[key].rankable
    }
    if not rankable:
        return ()

    coarse_raw = {key: _coarse_raw(snapshot) for key, snapshot in rankable.items()}
    coarse_scores = _score_components(coarse_raw, COARSE_WEIGHTS)

    if mode == "coarse":
        scored = coarse_scores
    else:
        book_quality = _book_quality_raw(rankable)
        enriched_raw = {
            key: _enriched_raw(
                snapshot,
                coarse_score=coarse_scores[key][1],
                book_quality=book_quality.get(key),
            )
            for key, snapshot in rankable.items()
        }
        scored = _score_components(enriched_raw, ENRICHED_WEIGHTS)

    ordered = sorted(
        scored,
        key=lambda key: (-scored[key][1], key),
    )
    ranks: list[OpportunityRank] = []
    for ordinal, key in enumerate(ordered, start=1):
        components, score = scored[key]
        reason_codes = tuple(
            component.name
            for component in sorted(
                components,
                key=lambda component: (-component.contribution, component.name),
            )
        )
        ranks.append(
            OpportunityRank(
                market=rankable[key].market,
                ordinal=ordinal,
                score=score,
                components=components,
                reason_codes=reason_codes,
            )
        )
    return tuple(ranks)
