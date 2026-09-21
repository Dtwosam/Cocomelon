from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_cross_sectional_spread import (
    build_cross_sectional_spread_entries,
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
    relative_score: str,
    long_return: str,
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
        trend_regime=TrendRegime.UNKNOWN,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=99_000_000,
        retrieved_after_anchor=True,
        available_features=(),
        unavailable_features=(),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-a",),
        relative_return_zscore_1h_vs_basket=Decimal(relative_score),
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


def _pair_rows(
    leader_returns: tuple[str, ...],
    *,
    leader_scores: tuple[str, ...] | None = None,
) -> tuple[HistoricalTrainingRow, ...]:
    scores = leader_scores or tuple("1" for _ in leader_returns)
    rows: list[HistoricalTrainingRow] = []
    for anchor, (leader_return, leader_score) in enumerate(
        zip(leader_returns, scores, strict=True),
        start=1,
    ):
        rows.extend(
            (
                _row(
                    market=BTC,
                    anchor_index=anchor,
                    relative_score=leader_score,
                    long_return=leader_return,
                ),
                _row(
                    market=ETH,
                    anchor_index=anchor,
                    relative_score="-1",
                    long_return=str(-Decimal(leader_return)),
                ),
            )
        )
    return tuple(rows)


def _zero_costs() -> ExecutionCostAssumptions:
    return ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )


def test_cross_sectional_spread_finds_stable_momentum_pair() -> None:
    rows = _pair_rows(tuple("0.02" for _ in range(8)))

    entry = build_cross_sectional_spread_entries(
        rows,
        costs=_zero_costs(),
        stability_blocks=4,
        min_markets_per_anchor=2,
        min_block_observations=2,
    )[0]

    assert entry.observation_count == 8
    assert entry.mean_momentum_net_return == Decimal("0.04")
    assert entry.mean_reversal_net_return == Decimal("-0.04")
    assert entry.stable_momentum is True
    assert entry.stable_reversal is False
    assert [block.observation_count for block in entry.blocks] == [2, 2, 2, 2]


def test_cross_sectional_spread_rejects_positive_aggregate_with_losing_block() -> None:
    rows = _pair_rows(
        (
            "0.02",
            "0.02",
            "0.02",
            "0.02",
            "-0.05",
            "-0.05",
            "0.02",
            "0.02",
        )
    )

    entry = build_cross_sectional_spread_entries(
        rows,
        costs=_zero_costs(),
        stability_blocks=4,
        min_markets_per_anchor=2,
        min_block_observations=2,
    )[0]

    assert entry.mean_momentum_net_return == Decimal("0.005")
    assert entry.blocks[2].mean_momentum_net_return == Decimal("-0.10")
    assert entry.stable_momentum is False


def test_cross_sectional_spread_subtracts_costs_for_both_legs() -> None:
    rows = _pair_rows(tuple("0.002" for _ in range(8)))

    entry = build_cross_sectional_spread_entries(
        rows,
        costs=ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0.003"),
            round_trip_slippage_fraction=Decimal("0"),
            funding_reserve_fraction_per_hour=Decimal("0"),
        ),
        stability_blocks=4,
        min_markets_per_anchor=2,
        min_block_observations=2,
    )[0]

    assert entry.mean_momentum_net_return == Decimal("-0.002")
    assert entry.stable_momentum is False


def test_cross_sectional_spread_skips_tied_extremes_without_hiding_block() -> None:
    rows = _pair_rows(
        tuple("0.02" for _ in range(8)),
        leader_scores=("1", "1", "1", "1", "-1", "1", "1", "1"),
    )

    entry = build_cross_sectional_spread_entries(
        rows,
        costs=_zero_costs(),
        stability_blocks=4,
        min_markets_per_anchor=2,
        min_block_observations=2,
    )[0]

    assert entry.observation_count == 7
    assert entry.skipped_tied_anchors == 1
    assert entry.blocks[2].anchor_count == 2
    assert entry.blocks[2].observation_count == 1
    assert entry.stable_momentum is False


def test_cross_sectional_spread_rejects_duplicate_market_rows() -> None:
    rows = list(_pair_rows(tuple("0.02" for _ in range(4))))
    rows.append(rows[0])

    with pytest.raises(ValueError, match="duplicate market row"):
        build_cross_sectional_spread_entries(
            rows,
            costs=_zero_costs(),
            stability_blocks=2,
            min_markets_per_anchor=2,
            min_block_observations=1,
        )
