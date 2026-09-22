from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from cocomelon.features.math import quantile
from cocomelon.research.historical_features import (
    BASKET_CONTEXT_FEATURE_NAMES,
    HistoricalFeatureRow,
    HistoricalTrainingRow,
)

ZERO = Decimal("0")
MEDIAN = Decimal("0.5")
WINDOWS = ("5m", "15m", "1h", "4h")


class HistoricalCrossMarketError(RuntimeError):
    pass


def _feature_key(feature: HistoricalFeatureRow) -> tuple[str, int]:
    return feature.market.canonical, feature.anchor_end_ms


def _context_for_window(
    features: Sequence[HistoricalFeatureRow],
    *,
    target: HistoricalFeatureRow,
    window: str,
) -> dict[str, Decimal | None]:
    return_field = f"return_{window}"
    by_market = {feature.market.canonical: feature for feature in features}
    btc = by_market.get("BTC")
    eth = by_market.get("ETH")
    btc_return = None if btc is None else getattr(btc, return_field)
    eth_return = None if eth is None else getattr(eth, return_field)

    observed = tuple(
        value
        for feature in features
        if (value := getattr(feature, return_field)) is not None
    )
    count = Decimal(len(observed))
    basket_median: Decimal | None = None
    basket_breadth: Decimal | None = None
    dispersion: Decimal | None = None
    relative: Decimal | None = None
    relative_zscore: Decimal | None = None
    if len(observed) >= 2:
        basket_median = quantile(observed, MEDIAN)
        basket_breadth = Decimal(
            sum(1 for value in observed if value > ZERO)
        ) / count
        mean = sum(observed, ZERO) / count
        variance = sum(
            ((value - mean) * (value - mean) for value in observed),
            ZERO,
        ) / count
        dispersion = variance.sqrt()
        target_return = getattr(target, return_field)
        if target_return is not None:
            relative = target_return - basket_median
            if dispersion > ZERO:
                relative_zscore = relative / dispersion

    return {
        f"btc_return_{window}": btc_return,
        f"eth_return_{window}": eth_return,
        f"basket_median_return_{window}": basket_median,
        f"basket_breadth_positive_{window}": basket_breadth,
        f"relative_return_{window}_vs_basket": relative,
        f"basket_return_count_{window}": count,
        f"basket_return_dispersion_{window}": dispersion,
        f"relative_return_zscore_{window}_vs_basket": relative_zscore,
    }


def _validate_unique_feature_states(
    rows: Sequence[HistoricalTrainingRow],
) -> dict[tuple[str, int], HistoricalFeatureRow]:
    by_key: dict[tuple[str, int], HistoricalFeatureRow] = {}
    for row in rows:
        key = _feature_key(row.feature)
        existing = by_key.get(key)
        if existing is not None and existing != row.feature:
            raise HistoricalCrossMarketError("CONFLICTING_FEATURE_STATE")
        by_key[key] = row.feature
    return by_key


def enrich_feature_rows_with_basket_context(
    features: Sequence[HistoricalFeatureRow],
) -> tuple[HistoricalFeatureRow, ...]:
    if not features:
        return ()

    by_key: dict[tuple[str, int], HistoricalFeatureRow] = {}
    for feature in features:
        key = _feature_key(feature)
        existing = by_key.get(key)
        if existing is not None and existing != feature:
            raise HistoricalCrossMarketError("CONFLICTING_FEATURE_STATE")
        by_key[key] = feature

    by_anchor: dict[int, list[HistoricalFeatureRow]] = defaultdict(list)
    for feature in by_key.values():
        by_anchor[feature.anchor_end_ms].append(feature)

    enriched_features: list[HistoricalFeatureRow] = []
    for anchor_end_ms, anchor_features in by_anchor.items():
        group = tuple(
            sorted(anchor_features, key=lambda item: item.market.canonical)
        )
        provenance = tuple(
            sorted(
                {
                    item
                    for feature in group
                    for item in feature.provenance
                }
            )
        )
        manifest_ids = tuple(
            sorted(
                {
                    item
                    for feature in group
                    for item in feature.source_manifest_ids
                }
            )
        )
        retrieved_at_ms = max(
            feature.source_retrieved_at_ms for feature in group
        )

        for target in group:
            context: dict[str, Decimal | None] = {}
            for window in WINDOWS:
                context.update(
                    _context_for_window(
                        group,
                        target=target,
                        window=window,
                    )
                )
            if set(context) != set(BASKET_CONTEXT_FEATURE_NAMES):
                raise HistoricalCrossMarketError("BASKET_CONTEXT_SCHEMA_MISMATCH")

            available = set(target.available_features)
            unavailable = set(target.unavailable_features)
            for name in BASKET_CONTEXT_FEATURE_NAMES:
                if context[name] is None:
                    available.discard(name)
                    unavailable.add(name)
                else:
                    unavailable.discard(name)
                    available.add(name)

            enriched_features.append(
                replace(
                    target,
                    btc_return_5m=context["btc_return_5m"],
                    btc_return_15m=context["btc_return_15m"],
                    btc_return_1h=context["btc_return_1h"],
                    btc_return_4h=context["btc_return_4h"],
                    eth_return_5m=context["eth_return_5m"],
                    eth_return_15m=context["eth_return_15m"],
                    eth_return_1h=context["eth_return_1h"],
                    eth_return_4h=context["eth_return_4h"],
                    basket_median_return_5m=context["basket_median_return_5m"],
                    basket_median_return_15m=context["basket_median_return_15m"],
                    basket_median_return_1h=context["basket_median_return_1h"],
                    basket_median_return_4h=context["basket_median_return_4h"],
                    basket_breadth_positive_5m=context[
                        "basket_breadth_positive_5m"
                    ],
                    basket_breadth_positive_15m=context[
                        "basket_breadth_positive_15m"
                    ],
                    basket_breadth_positive_1h=context[
                        "basket_breadth_positive_1h"
                    ],
                    basket_breadth_positive_4h=context[
                        "basket_breadth_positive_4h"
                    ],
                    relative_return_5m_vs_basket=context[
                        "relative_return_5m_vs_basket"
                    ],
                    relative_return_15m_vs_basket=context[
                        "relative_return_15m_vs_basket"
                    ],
                    relative_return_1h_vs_basket=context[
                        "relative_return_1h_vs_basket"
                    ],
                    relative_return_4h_vs_basket=context[
                        "relative_return_4h_vs_basket"
                    ],
                    basket_return_count_5m=context["basket_return_count_5m"],
                    basket_return_count_15m=context["basket_return_count_15m"],
                    basket_return_count_1h=context["basket_return_count_1h"],
                    basket_return_count_4h=context["basket_return_count_4h"],
                    basket_return_dispersion_5m=context[
                        "basket_return_dispersion_5m"
                    ],
                    basket_return_dispersion_15m=context[
                        "basket_return_dispersion_15m"
                    ],
                    basket_return_dispersion_1h=context[
                        "basket_return_dispersion_1h"
                    ],
                    basket_return_dispersion_4h=context[
                        "basket_return_dispersion_4h"
                    ],
                    relative_return_zscore_5m_vs_basket=context[
                        "relative_return_zscore_5m_vs_basket"
                    ],
                    relative_return_zscore_15m_vs_basket=context[
                        "relative_return_zscore_15m_vs_basket"
                    ],
                    relative_return_zscore_1h_vs_basket=context[
                        "relative_return_zscore_1h_vs_basket"
                    ],
                    relative_return_zscore_4h_vs_basket=context[
                        "relative_return_zscore_4h_vs_basket"
                    ],
                    source_retrieved_at_ms=retrieved_at_ms,
                    retrieved_after_anchor=retrieved_at_ms > anchor_end_ms,
                    available_features=tuple(sorted(available)),
                    unavailable_features=tuple(sorted(unavailable)),
                    provenance=provenance,
                    source_manifest_ids=manifest_ids,
                    schema_version=max(3, target.schema_version),
                )
            )

    ordered = tuple(
        sorted(
            enriched_features,
            key=lambda item: (
                item.market.canonical,
                item.anchor_end_ms,
                item.row_id,
            ),
        )
    )
    identities = tuple(item.row_id for item in ordered)
    if len(set(identities)) != len(identities):
        raise HistoricalCrossMarketError("DUPLICATE_ENRICHED_FEATURE_ID")
    return ordered


def enrich_training_rows_with_basket_context(
    rows: Sequence[HistoricalTrainingRow],
) -> tuple[HistoricalTrainingRow, ...]:
    if not rows:
        return ()

    unique_features = _validate_unique_feature_states(rows)
    enriched = enrich_feature_rows_with_basket_context(
        tuple(unique_features.values())
    )
    enriched_features = {
        _feature_key(feature): feature
        for feature in enriched
    }

    enriched_rows = tuple(
        replace(
            row,
            feature=enriched_features[_feature_key(row.feature)],
            schema_version=max(3, row.schema_version),
        )
        for row in rows
    )
    identities = tuple(row.training_row_id for row in enriched_rows)
    if len(set(identities)) != len(identities):
        raise HistoricalCrossMarketError("DUPLICATE_ENRICHED_TRAINING_ID")

    return tuple(
        sorted(
            enriched_rows,
            key=lambda item: (
                item.market.canonical,
                item.anchor_end_ms,
                item.horizon_ms,
                item.training_row_id,
            ),
        )
    )
