from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("sklearn")

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_features import HistoricalFeatureRow, HistoricalTrainingRow
from cocomelon.research.historical_learning import DirectionalOutcome
from cocomelon.research.historical_tree import (
    TreeModelConfig,
    fit_tree_directional_model,
    run_walk_forward_stable_tree,
)

BTC = MarketId(dex="", coin="BTC")
ETH = MarketId(dex="", coin="ETH")
FIVE = 300_000


def _feature(
    *,
    market: MarketId,
    anchor_index: int,
    momentum: Decimal,
) -> HistoricalFeatureRow:
    anchor_end_ms = anchor_index * FIVE
    return HistoricalFeatureRow(
        market=market,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=momentum,
        return_15m=momentum / Decimal("2"),
        return_1h=momentum,
        return_4h=momentum * Decimal("2"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        funding_rate=Decimal("0.0001"),
        funding_change=Decimal("0.00001"),
        funding_premium=Decimal("0.0002"),
        funding_premium_change=Decimal("0.00001"),
        funding_age_ms=0,
        candle_15m_age_ms=0,
        trend_regime=TrendRegime.UP if momentum >= 0 else TrendRegime.DOWN,
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
    momentum: Decimal,
    long_return: Decimal,
) -> HistoricalTrainingRow:
    anchor_end_ms = anchor_index * FIVE
    return HistoricalTrainingRow(
        feature=_feature(
            market=market,
            anchor_index=anchor_index,
            momentum=momentum,
        ),
        outcome=DirectionalOutcome(
            market=market,
            interval="5m",
            anchor_end_ms=anchor_end_ms,
            target_end_ms=anchor_end_ms + FIVE,
            horizon_ms=FIVE,
            entry_px=Decimal("100"),
            exit_px=Decimal("100") * (Decimal("1") + long_return),
            long_gross_return=long_return,
            short_gross_return=-long_return,
            provenance=("hyperliquid-mainnet-info",),
        ),
    )


def _config() -> TreeModelConfig:
    return TreeModelConfig(
        max_leaf_nodes=7,
        min_samples_leaf=2,
        learning_rate=Decimal("0.1"),
        max_iter=80,
        l2_regularization=Decimal("0.1"),
    )


def test_tree_learns_simple_nonlinear_directional_pattern() -> None:
    rows = tuple(
        _row(
            market=BTC,
            anchor_index=index,
            momentum=Decimal(index - 11) / Decimal("100"),
            long_return=(
                Decimal("0.03")
                if abs(Decimal(index - 11) / Decimal("100")) >= Decimal("0.05")
                else Decimal("-0.03")
            ),
        )
        for index in range(1, 22)
    )

    model = fit_tree_directional_model(
        rows,
        config=_config(),
        min_market_samples=100,
    )

    outer = model.predict(
        _feature(market=BTC, anchor_index=30, momentum=Decimal("0.08")),
        horizon_ms=FIVE,
        allow_coin_calibration=False,
    )
    inner = model.predict(
        _feature(market=BTC, anchor_index=31, momentum=Decimal("0.00")),
        horizon_ms=FIVE,
        allow_coin_calibration=False,
    )

    assert outer.expected_long_return > 0
    assert inner.expected_long_return < 0
    assert outer.expected_short_return == -outer.expected_long_return
    assert inner.expected_short_return == -inner.expected_long_return


def test_tree_sparse_market_falls_back_to_shared_estimator() -> None:
    rows = tuple(
        [
            _row(
                market=BTC,
                anchor_index=index,
                momentum=Decimal(index) / Decimal("100"),
                long_return=Decimal("0.02"),
            )
            for index in range(1, 11)
        ]
        + [
            _row(
                market=ETH,
                anchor_index=20 + index,
                momentum=Decimal(index) / Decimal("100"),
                long_return=Decimal("-0.02"),
            )
            for index in range(1, 3)
        ]
    )
    model = fit_tree_directional_model(
        rows,
        config=_config(),
        min_market_samples=5,
    )

    btc = model.predict(
        _feature(market=BTC, anchor_index=40, momentum=Decimal("0.04")),
        horizon_ms=FIVE,
        allow_coin_calibration=True,
    )
    eth = model.predict(
        _feature(market=ETH, anchor_index=41, momentum=Decimal("0.04")),
        horizon_ms=FIVE,
        allow_coin_calibration=True,
    )

    assert btc.estimate_source == "market_tree"
    assert eth.estimate_source == "shared_tree"


def _walk_forward_rows(test_return: Decimal) -> tuple[HistoricalTrainingRow, ...]:
    rows: list[HistoricalTrainingRow] = []
    for index in range(1, 21):
        momentum = Decimal(index - 10) / Decimal("100")
        if index <= 8:
            realized = Decimal("0.025") if momentum >= 0 else Decimal("-0.025")
        elif index <= 16:
            realized = Decimal("0.03") if momentum >= 0 else Decimal("-0.03")
        else:
            realized = test_return if momentum >= 0 else -test_return
        rows.append(
            _row(
                market=BTC,
                anchor_index=index,
                momentum=momentum,
                long_return=realized,
            )
        )
    return tuple(rows)


def _walk_forward_kwargs() -> dict[str, object]:
    return {
        "config": _config(),
        "costs": ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0"),
            round_trip_slippage_fraction=Decimal("0"),
            funding_reserve_fraction_per_hour=Decimal("0"),
        ),
        "candidate_thresholds": (Decimal("0"), Decimal("0.001")),
        "min_train_anchors": 8,
        "validation_anchors": 8,
        "test_anchors": 4,
        "step_anchors": 4,
        "embargo_anchors": 0,
        "min_market_samples": 100,
        "min_sample_count": 1,
        "min_validation_trades": 2,
        "stability_blocks": 2,
        "min_block_trades": 1,
    }


def test_tree_walk_forward_selection_ignores_future_test_outcomes() -> None:
    positive = run_walk_forward_stable_tree(
        _walk_forward_rows(Decimal("0.03")),
        **_walk_forward_kwargs(),
    ).folds[0]
    negative = run_walk_forward_stable_tree(
        _walk_forward_rows(Decimal("-0.03")),
        **_walk_forward_kwargs(),
    ).folds[0]

    assert positive.shared_horizon_thresholds == negative.shared_horizon_thresholds
    assert positive.market_horizon_thresholds == negative.market_horizon_thresholds
    assert positive.shared_validation == negative.shared_validation
    assert positive.market_validation == negative.market_validation
    assert (
        positive.shared_test.trade_count,
        positive.shared_test.long_count,
        positive.shared_test.short_count,
        positive.shared_test.no_trade_count,
    ) == (
        negative.shared_test.trade_count,
        negative.shared_test.long_count,
        negative.shared_test.short_count,
        negative.shared_test.no_trade_count,
    )


def test_tree_config_disables_hidden_early_stopping() -> None:
    assert _config().to_dict()["early_stopping"] is False
