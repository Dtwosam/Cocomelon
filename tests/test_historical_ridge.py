from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("numpy")

import cocomelon.research.historical_ridge as ridge_module
from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_features import HistoricalFeatureRow, HistoricalTrainingRow
from cocomelon.research.historical_learning import DirectionalOutcome
from cocomelon.research.historical_ridge import (
    fit_ridge_directional_model,
    prepare_ridge_walk_forward,
    run_walk_forward_ridge,
)
from cocomelon.research.historical_ridge_horizon import (
    run_walk_forward_horizon_calibrated_ridge,
)
from cocomelon.research.historical_ridge_stability import (
    run_walk_forward_stable_horizon_ridge,
)

ETH = MarketId(dex="", coin="ETH")
BTC = MarketId(dex="", coin="BTC")
FIVE = 300_000


def _feature(
    *,
    market: MarketId = ETH,
    anchor_end_ms: int,
    return_5m: str | None,
    funding_rate: str | None = "0.0001",
) -> HistoricalFeatureRow:
    return HistoricalFeatureRow(
        market=market,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=None if return_5m is None else Decimal(return_5m),
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=Decimal("0.03"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.5"),
        funding_rate=None if funding_rate is None else Decimal(funding_rate),
        funding_change=Decimal("0.00001") if funding_rate is not None else None,
        funding_premium=Decimal("0.0002") if funding_rate is not None else None,
        funding_premium_change=Decimal("0.00001") if funding_rate is not None else None,
        funding_age_ms=0 if funding_rate is not None else None,
        candle_15m_age_ms=0,
        trend_regime=TrendRegime.UP,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=99_000_000,
        retrieved_after_anchor=True,
        available_features=(),
        unavailable_features=(),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-manifest",),
    )


def _row(
    *,
    anchor_end_ms: int,
    return_5m: str | None,
    long_return: str,
    market: MarketId = ETH,
    funding_rate: str | None = "0.0001",
) -> HistoricalTrainingRow:
    feature = _feature(
        market=market,
        anchor_end_ms=anchor_end_ms,
        return_5m=return_5m,
        funding_rate=funding_rate,
    )
    long_value = Decimal(long_return)
    outcome = DirectionalOutcome(
        market=market,
        interval="5m",
        anchor_end_ms=anchor_end_ms,
        target_end_ms=anchor_end_ms + FIVE,
        horizon_ms=FIVE,
        entry_px=Decimal("100"),
        exit_px=Decimal("100") * (Decimal("1") + long_value),
        long_gross_return=long_value,
        short_gross_return=-long_value,
        provenance=("hyperliquid-mainnet-info",),
    )
    return HistoricalTrainingRow(feature=feature, outcome=outcome)


def test_ridge_learns_continuous_momentum_relation() -> None:
    rows = tuple(
        _row(
            anchor_end_ms=index * FIVE,
            return_5m=str(momentum),
            long_return=str(momentum * Decimal("0.5")),
        )
        for index, momentum in enumerate(
            (
                Decimal("-0.04"),
                Decimal("-0.03"),
                Decimal("-0.02"),
                Decimal("-0.01"),
                Decimal("0.01"),
                Decimal("0.02"),
                Decimal("0.03"),
                Decimal("0.04"),
            ),
            start=1,
        )
    )

    model = fit_ridge_directional_model(rows, alpha=Decimal("0.01"), min_market_samples=99)
    positive = model.predict(
        _feature(anchor_end_ms=20 * FIVE, return_5m="0.03"),
        horizon_ms=FIVE,
        allow_coin_calibration=False,
    )
    negative = model.predict(
        _feature(anchor_end_ms=21 * FIVE, return_5m="-0.03"),
        horizon_ms=FIVE,
        allow_coin_calibration=False,
    )

    assert positive.expected_long_return > 0
    assert positive.expected_short_return < 0
    assert negative.expected_long_return < 0
    assert negative.expected_short_return > 0
    assert positive.estimate_source == "shared_ridge"


def test_market_aware_ridge_activates_only_after_market_sample_gate() -> None:
    rows = tuple(
        _row(
            market=market,
            anchor_end_ms=index * FIVE,
            return_5m="0",
            long_return=long_return,
        )
        for index, (market, long_return) in enumerate(
            (
                (ETH, "0.02"),
                (ETH, "0.02"),
                (ETH, "0.02"),
                (BTC, "-0.02"),
                (BTC, "-0.02"),
                (BTC, "-0.02"),
            ),
            start=1,
        )
    )
    model = fit_ridge_directional_model(
        rows,
        alpha=Decimal("0.1"),
        min_market_samples=3,
    )

    eth = model.predict(
        _feature(market=ETH, anchor_end_ms=10 * FIVE, return_5m="0"),
        horizon_ms=FIVE,
        allow_coin_calibration=True,
    )
    btc = model.predict(
        _feature(market=BTC, anchor_end_ms=11 * FIVE, return_5m="0"),
        horizon_ms=FIVE,
        allow_coin_calibration=True,
    )
    shared = model.predict(
        _feature(market=ETH, anchor_end_ms=12 * FIVE, return_5m="0"),
        horizon_ms=FIVE,
        allow_coin_calibration=False,
    )

    assert eth.expected_long_return > 0
    assert btc.expected_long_return < 0
    assert eth.estimate_source == "market_ridge"
    assert btc.estimate_source == "market_ridge"
    assert abs(shared.expected_long_return) < Decimal("0.001")


def test_ridge_missing_values_are_imputed_from_training_only() -> None:
    rows = (
        _row(anchor_end_ms=FIVE, return_5m="-0.01", long_return="-0.01"),
        _row(
            anchor_end_ms=2 * FIVE,
            return_5m=None,
            funding_rate=None,
            long_return="0",
        ),
        _row(anchor_end_ms=3 * FIVE, return_5m="0.01", long_return="0.01"),
    )
    model = fit_ridge_directional_model(rows, alpha=Decimal("0.1"), min_market_samples=99)

    estimate = model.predict(
        _feature(
            anchor_end_ms=10 * FIVE,
            return_5m=None,
            funding_rate=None,
        ),
        horizon_ms=FIVE,
        allow_coin_calibration=False,
    )

    assert estimate.expected_long_return.is_finite()
    assert estimate.expected_short_return == -estimate.expected_long_return


def test_walk_forward_ridge_keeps_test_outcomes_out_of_model_selection() -> None:
    prefix = tuple(
        _row(
            anchor_end_ms=index * FIVE,
            return_5m=str(Decimal(index) / Decimal("100")),
            long_return=str(Decimal(index) / Decimal("200")),
        )
        for index in range(1, 7)
    )
    positive = (
        *prefix,
        _row(anchor_end_ms=7 * FIVE, return_5m="0.07", long_return="0.04"),
        _row(anchor_end_ms=8 * FIVE, return_5m="0.08", long_return="0.04"),
    )
    negative = (
        *prefix,
        _row(anchor_end_ms=7 * FIVE, return_5m="0.07", long_return="-0.04"),
        _row(anchor_end_ms=8 * FIVE, return_5m="0.08", long_return="-0.04"),
    )
    kwargs = {
        "costs": ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0"),
            round_trip_slippage_fraction=Decimal("0"),
            funding_reserve_fraction_per_hour=Decimal("0"),
        ),
        "candidate_alphas": (Decimal("0.01"), Decimal("0.1")),
        "candidate_thresholds": (Decimal("0"), Decimal("0.001")),
        "min_train_anchors": 4,
        "validation_anchors": 2,
        "test_anchors": 2,
        "step_anchors": 2,
        "embargo_anchors": 0,
        "min_market_samples": 99,
        "min_sample_count": 2,
        "min_validation_trades": 1,
    }

    positive_report = run_walk_forward_ridge(positive, **kwargs)
    negative_report = run_walk_forward_ridge(negative, **kwargs)

    assert positive_report.folds[0].shared_alpha == negative_report.folds[0].shared_alpha
    assert (
        positive_report.folds[0].shared_threshold
        == negative_report.folds[0].shared_threshold
    )
    assert positive_report.folds[0].shared_test.mean_realized_net_return > 0
    assert negative_report.folds[0].shared_test.mean_realized_net_return < 0


def test_walk_forward_ridge_abstains_when_validation_edge_is_negative() -> None:
    rows = tuple(
        _row(
            anchor_end_ms=index * FIVE,
            return_5m=str(Decimal(index) / Decimal("100")),
            long_return=(
                str(Decimal(index) / Decimal("200"))
                if index <= 4
                else "-0.02"
            ),
        )
        for index in range(1, 9)
    )

    report = run_walk_forward_ridge(
        rows,
        costs=ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0"),
            round_trip_slippage_fraction=Decimal("0"),
            funding_reserve_fraction_per_hour=Decimal("0"),
        ),
        candidate_alphas=(Decimal("0.01"), Decimal("0.1")),
        candidate_thresholds=(Decimal("0"), Decimal("0.001")),
        min_train_anchors=4,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=2,
        embargo_anchors=0,
        min_market_samples=99,
        min_sample_count=2,
        min_validation_trades=1,
    )

    fold = report.folds[0]
    assert fold.shared_alpha is None
    assert fold.shared_threshold is None
    assert fold.shared_test.trade_count == 0
    assert fold.shared_test.no_trade_count == 2


def test_prepared_ridge_fits_are_reused_without_changing_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = tuple(
        _row(
            anchor_end_ms=index * FIVE,
            return_5m=str(Decimal(index - 7) / Decimal("100")),
            long_return=str(Decimal(index - 7) / Decimal("200")),
        )
        for index in range(1, 13)
    )
    shared = {
        "costs": ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0"),
            round_trip_slippage_fraction=Decimal("0"),
            funding_reserve_fraction_per_hour=Decimal("0"),
        ),
        "candidate_alphas": (Decimal("0.01"), Decimal("0.1")),
        "candidate_thresholds": (Decimal("0"), Decimal("0.001")),
        "min_train_anchors": 4,
        "validation_anchors": 2,
        "test_anchors": 2,
        "step_anchors": 2,
        "embargo_anchors": 0,
        "min_market_samples": 99,
        "min_sample_count": 1,
        "min_validation_trades": 1,
    }

    expected_pooled = run_walk_forward_ridge(rows, **shared)
    expected_horizon = run_walk_forward_horizon_calibrated_ridge(rows, **shared)
    expected_stable = run_walk_forward_stable_horizon_ridge(
        rows,
        **shared,
        stability_blocks=2,
        min_block_trades=1,
    )

    original_fit = ridge_module.fit_ridge_directional_model
    fit_calls = 0

    def counted_fit(*args: object, **kwargs: object) -> object:
        nonlocal fit_calls
        fit_calls += 1
        return original_fit(*args, **kwargs)

    monkeypatch.setattr(ridge_module, "fit_ridge_directional_model", counted_fit)
    prepared = prepare_ridge_walk_forward(
        rows,
        candidate_alphas=shared["candidate_alphas"],
        min_train_anchors=4,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=2,
        embargo_anchors=0,
        min_market_samples=99,
    )
    assert fit_calls == len(prepared.folds) * len(prepared.candidate_alphas)

    def forbidden_fit(*args: object, **kwargs: object) -> object:
        raise AssertionError("prepared ridge evaluation must not refit models")

    monkeypatch.setattr(ridge_module, "fit_ridge_directional_model", forbidden_fit)

    actual_pooled = run_walk_forward_ridge(rows, **shared, prepared=prepared)
    actual_horizon = run_walk_forward_horizon_calibrated_ridge(
        rows,
        **shared,
        prepared=prepared,
    )
    actual_stable = run_walk_forward_stable_horizon_ridge(
        rows,
        **shared,
        stability_blocks=2,
        min_block_trades=1,
        prepared=prepared,
    )

    assert actual_pooled == expected_pooled
    assert actual_horizon == expected_horizon
    assert actual_stable == expected_stable
