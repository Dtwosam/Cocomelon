from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("numpy")

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_features import HistoricalFeatureRow, HistoricalTrainingRow
from cocomelon.research.historical_learning import DirectionalOutcome
from cocomelon.research.historical_ridge_portfolio_capacity import (
    run_walk_forward_portfolio_capacity_stable_ridge,
)

BTC = MarketId(dex="", coin="BTC")
ETH = MarketId(dex="", coin="ETH")
SOL = MarketId(dex="", coin="SOL")
MARKETS = (BTC, ETH, SOL)
FIFTEEN = 900_000


def _feature(*, market: MarketId, anchor_end_ms: int) -> HistoricalFeatureRow:
    return HistoricalFeatureRow(
        market=market,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=None,
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=Decimal("0.03"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        funding_rate=Decimal("0.0001"),
        funding_change=Decimal("0.00001"),
        funding_premium=Decimal("0.0002"),
        funding_premium_change=Decimal("0.00001"),
        funding_age_ms=0,
        candle_15m_age_ms=0,
        trend_regime=TrendRegime.UP,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=99_000_000,
        retrieved_after_anchor=True,
        available_features=(),
        unavailable_features=(),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-a",),
    )


def _row(
    *,
    market: MarketId,
    anchor_index: int,
    long_return: Decimal,
) -> HistoricalTrainingRow:
    anchor_end_ms = anchor_index * FIFTEEN
    return HistoricalTrainingRow(
        feature=_feature(market=market, anchor_end_ms=anchor_end_ms),
        outcome=DirectionalOutcome(
            market=market,
            interval="15m",
            anchor_end_ms=anchor_end_ms,
            target_end_ms=anchor_end_ms + FIFTEEN,
            horizon_ms=FIFTEEN,
            entry_px=Decimal("100"),
            exit_px=Decimal("100") * (Decimal("1") + long_return),
            long_gross_return=long_return,
            short_gross_return=-long_return,
            provenance=("hyperliquid-mainnet-info",),
        ),
    )


def _rows(*, test_return: Decimal) -> tuple[HistoricalTrainingRow, ...]:
    rows: list[HistoricalTrainingRow] = []
    for anchor_index in range(1, 13):
        realized = Decimal("0.02") if anchor_index <= 8 else test_return
        for market in MARKETS:
            rows.append(
                _row(
                    market=market,
                    anchor_index=anchor_index,
                    long_return=realized,
                )
            )
    return tuple(rows)


def _kwargs() -> dict[str, object]:
    return {
        "costs": ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0"),
            round_trip_slippage_fraction=Decimal("0"),
            funding_reserve_fraction_per_hour=Decimal("0"),
        ),
        "candidate_alphas": (Decimal("0.1"),),
        "candidate_thresholds": (Decimal("0"),),
        "min_train_anchors": 4,
        "validation_anchors": 4,
        "test_anchors": 4,
        "step_anchors": 4,
        "embargo_anchors": 0,
        "min_market_samples": 99,
        "min_sample_count": 1,
        "min_validation_trades": 4,
        "stability_blocks": 2,
        "min_block_trades": 2,
        "max_concurrent_positions": 2,
    }


def test_portfolio_capacity_walk_forward_executes_two_of_three_markets_per_anchor() -> None:
    fold = run_walk_forward_portfolio_capacity_stable_ridge(
        _rows(test_return=Decimal("0.02")),
        **_kwargs(),
    ).folds[0]

    assert fold.max_concurrent_positions == 2
    assert fold.shared_horizon_thresholds == ((FIFTEEN, Decimal("0")),)
    assert fold.shared_test.opportunity_count == 12
    assert fold.shared_test.trade_count == 8
    assert fold.shared_test.capacity_skip_count == 4
    assert fold.shared_test.occupied_skip_count == 0
    assert fold.shared_test.no_trade_count == 0
    assert fold.shared_test.total_realized_net_return == Decimal("0.16")


def test_portfolio_capacity_selection_ignores_future_test_outcomes() -> None:
    positive = run_walk_forward_portfolio_capacity_stable_ridge(
        _rows(test_return=Decimal("0.02")),
        **_kwargs(),
    ).folds[0]
    negative = run_walk_forward_portfolio_capacity_stable_ridge(
        _rows(test_return=Decimal("-0.02")),
        **_kwargs(),
    ).folds[0]

    assert positive.shared_alpha == negative.shared_alpha
    assert positive.market_alpha == negative.market_alpha
    assert positive.shared_horizon_thresholds == negative.shared_horizon_thresholds
    assert positive.market_horizon_thresholds == negative.market_horizon_thresholds
    assert positive.shared_validation == negative.shared_validation
    assert positive.market_validation == negative.market_validation
    assert positive.shared_test.total_realized_net_return == Decimal("0.16")
    assert negative.shared_test.total_realized_net_return == Decimal("-0.16")
