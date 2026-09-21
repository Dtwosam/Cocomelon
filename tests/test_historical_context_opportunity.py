from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_context_opportunity import (
    build_context_opportunity_map,
)
from cocomelon.research.historical_features import (
    HistoricalFeatureRow,
    HistoricalTrainingRow,
)
from cocomelon.research.historical_learning import DirectionalOutcome

BTC = MarketId(dex="", coin="BTC")
ETH = MarketId(dex="", coin="ETH")
HOUR = 3_600_000


def _row(
    *,
    market: MarketId,
    anchor_index: int,
    long_return: str,
    basket_median: str,
    basket_breadth: str,
    relative_zscore: str,
) -> HistoricalTrainingRow:
    anchor_end_ms = anchor_index * HOUR
    feature = HistoricalFeatureRow(
        market=market,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=None,
        return_15m=None,
        return_1h=Decimal("0.01"),
        return_4h=Decimal("0.02"),
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        funding_rate=Decimal("0.0001"),
        funding_change=Decimal("0"),
        funding_premium=Decimal("0.0002"),
        funding_premium_change=Decimal("0"),
        funding_age_ms=0,
        candle_15m_age_ms=None,
        trend_regime=TrendRegime.UP,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=99_000_000,
        retrieved_after_anchor=True,
        available_features=(),
        unavailable_features=(),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-a",),
        basket_median_return_1h=Decimal(basket_median),
        basket_breadth_positive_1h=Decimal(basket_breadth),
        relative_return_zscore_1h_vs_basket=Decimal(relative_zscore),
        schema_version=3,
    )
    realized = Decimal(long_return)
    return HistoricalTrainingRow(
        feature=feature,
        outcome=DirectionalOutcome(
            market=market,
            interval="1h",
            anchor_end_ms=anchor_end_ms,
            target_end_ms=anchor_end_ms + HOUR,
            horizon_ms=HOUR,
            entry_px=Decimal("100"),
            exit_px=Decimal("100") * (Decimal("1") + realized),
            long_gross_return=realized,
            short_gross_return=-realized,
            provenance=("hyperliquid-mainnet-info",),
        ),
    )


def _rows() -> tuple[HistoricalTrainingRow, ...]:
    eth_returns = {
        1: "0.05",
        2: "0.05",
        3: "0.05",
        4: "0.05",
        5: "-0.10",
        6: "-0.10",
        7: "0.05",
        8: "0.05",
    }
    rows: list[HistoricalTrainingRow] = []
    for anchor in range(1, 9):
        rows.append(
            _row(
                market=BTC,
                anchor_index=anchor,
                long_return="0.02",
                basket_median="0.01",
                basket_breadth="0.75",
                relative_zscore="1.2",
            )
        )
        rows.append(
            _row(
                market=ETH,
                anchor_index=anchor,
                long_return=eth_returns[anchor],
                basket_median="-0.01",
                basket_breadth="0.25",
                relative_zscore="-1.2",
            )
        )
    return tuple(rows)


def _zero_costs() -> ExecutionCostAssumptions:
    return ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )


def test_context_opportunity_map_requires_positive_edge_in_every_time_block() -> None:
    report = build_context_opportunity_map(
        _rows(),
        costs=_zero_costs(),
        stability_blocks=4,
        min_block_rows=2,
    )
    entries = {
        (entry.dimension, entry.value, entry.horizon_ms): entry
        for entry in report.entries
    }

    leader = entries[
        (
            "context_state_1h",
            "up/bullish/leading_1sd",
            HOUR,
        )
    ]
    lagger = entries[
        (
            "context_state_1h",
            "down/bearish/lagging_1sd",
            HOUR,
        )
    ]
    btc_context = entries[
        (
            "market_context_state_1h",
            "BTC/up/bullish/leading_1sd",
            HOUR,
        )
    ]
    eth_context = entries[
        (
            "market_context_state_1h",
            "ETH/down/bearish/lagging_1sd",
            HOUR,
        )
    ]

    assert leader.mean_long_net_return == Decimal("0.02")
    assert leader.stable_long is True
    assert leader.stable_short is False
    assert [block.row_count for block in leader.blocks] == [2, 2, 2, 2]

    assert lagger.mean_long_net_return == Decimal("0.0125")
    assert lagger.mean_long_net_return > 0
    assert lagger.blocks[2].mean_long_net_return == Decimal("-0.10")
    assert lagger.stable_long is False

    assert btc_context.mean_long_net_return == Decimal("0.02")
    assert btc_context.stable_long is True
    assert eth_context.mean_long_net_return == Decimal("0.0125")
    assert eth_context.stable_long is False


def test_context_opportunity_map_is_cost_aware() -> None:
    rows = tuple(
        _row(
            market=BTC,
            anchor_index=anchor,
            long_return="0.001",
            basket_median="0.01",
            basket_breadth="0.75",
            relative_zscore="1.2",
        )
        for anchor in range(1, 9)
    )
    report = build_context_opportunity_map(
        rows,
        costs=ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0.002"),
            round_trip_slippage_fraction=Decimal("0"),
            funding_reserve_fraction_per_hour=Decimal("0"),
        ),
        stability_blocks=4,
        min_block_rows=2,
    )
    context = next(
        entry
        for entry in report.entries
        if entry.dimension == "context_state_1h"
        and entry.value == "up/bullish/leading_1sd"
    )

    assert context.mean_long_net_return == Decimal("-0.001")
    assert context.stable_long is False


def test_context_opportunity_map_uses_global_chronological_blocks() -> None:
    report = build_context_opportunity_map(
        _rows(),
        costs=_zero_costs(),
        stability_blocks=4,
        min_block_rows=2,
    )

    market_entries = {
        entry.value: entry
        for entry in report.entries
        if entry.dimension == "market"
    }
    assert [block.anchor_count for block in market_entries["BTC"].blocks] == [
        2,
        2,
        2,
        2,
    ]
    assert [block.anchor_count for block in market_entries["ETH"].blocks] == [
        2,
        2,
        2,
        2,
    ]
