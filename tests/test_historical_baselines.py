from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import (
    DecisionAction,
    DecisionPolicy,
    ExecutionCostAssumptions,
    HistoricalBaselineError,
    calibrate_no_trade_threshold,
    chronological_split,
    compare_shared_and_coin_calibration,
    fit_conditional_baseline,
    run_walk_forward_baseline,
    walk_forward_splits,
)
from cocomelon.research.historical_features import (
    HistoricalFeatureRow,
    HistoricalTrainingRow,
)
from cocomelon.research.historical_learning import DirectionalOutcome

ETH = MarketId(dex="", coin="ETH")
BTC = MarketId(dex="", coin="BTC")
FIVE = 300_000


def _feature(
    *,
    market: MarketId = ETH,
    anchor_end_ms: int,
    trend: TrendRegime = TrendRegime.UP,
    return_5m: str | None = "0.01",
    funding_rate: str | None = "0.0001",
) -> HistoricalFeatureRow:
    available = []
    unavailable = [
        "ask_depth_25bps",
        "bid_depth_25bps",
        "book_imbalance",
        "day_notional_volume",
        "mark_oracle_dislocation_bps",
        "open_interest",
        "order_flow",
        "oi_change_fraction",
        "spread_bps",
    ]
    if return_5m is None:
        unavailable.append("return_5m")
    else:
        available.append("return_5m")
    if funding_rate is None:
        unavailable.append("funding_rate")
    else:
        available.append("funding_rate")

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
        funding_change=None,
        funding_premium=None,
        funding_premium_change=None,
        funding_age_ms=0 if funding_rate is not None else None,
        candle_15m_age_ms=0,
        trend_regime=trend,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=99_000_000,
        retrieved_after_anchor=True,
        available_features=tuple(available),
        unavailable_features=tuple(unavailable),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-manifest",),
    )


def _row(
    *,
    market: MarketId = ETH,
    anchor_end_ms: int,
    horizon_ms: int = FIVE,
    trend: TrendRegime = TrendRegime.UP,
    return_5m: str | None = "0.01",
    funding_rate: str | None = "0.0001",
    long_return: str,
    short_return: str,
) -> HistoricalTrainingRow:
    feature = _feature(
        market=market,
        anchor_end_ms=anchor_end_ms,
        trend=trend,
        return_5m=return_5m,
        funding_rate=funding_rate,
    )
    outcome = DirectionalOutcome(
        market=market,
        interval="5m",
        anchor_end_ms=anchor_end_ms,
        target_end_ms=anchor_end_ms + horizon_ms,
        horizon_ms=horizon_ms,
        entry_px=Decimal("100"),
        exit_px=Decimal("100") * (Decimal("1") + Decimal(long_return)),
        long_gross_return=Decimal(long_return),
        short_gross_return=Decimal(short_return),
        provenance=("hyperliquid-mainnet-info",),
    )
    return HistoricalTrainingRow(feature=feature, outcome=outcome)


def test_chronological_split_keeps_same_anchor_together_and_enforces_embargo() -> None:
    rows = (
        _row(anchor_end_ms=1 * FIVE, horizon_ms=FIVE, long_return="0.01", short_return="-0.01"),
        _row(anchor_end_ms=1 * FIVE, horizon_ms=2 * FIVE, long_return="0.02", short_return="-0.02"),
        _row(anchor_end_ms=2 * FIVE, long_return="0.01", short_return="-0.01"),
        _row(anchor_end_ms=3 * FIVE, long_return="-0.01", short_return="0.01"),
        _row(anchor_end_ms=4 * FIVE, long_return="-0.02", short_return="0.02"),
        _row(anchor_end_ms=5 * FIVE, long_return="0.03", short_return="-0.03"),
        _row(anchor_end_ms=6 * FIVE, long_return="0.01", short_return="-0.01"),
    )

    split = chronological_split(
        rows,
        train_end_ms=2 * FIVE,
        validation_end_ms=4 * FIVE,
        embargo_ms=FIVE,
    )

    assert {row.anchor_end_ms for row in split.train} == {FIVE, 2 * FIVE}
    assert {row.anchor_end_ms for row in split.validation} == {4 * FIVE}
    assert {row.anchor_end_ms for row in split.test} == {6 * FIVE}
    assert all(row.anchor_end_ms > 3 * FIVE for row in split.validation)
    assert all(row.anchor_end_ms > 5 * FIVE for row in split.test)


def test_chronological_split_rejects_invalid_cutoffs() -> None:
    rows = (_row(anchor_end_ms=FIVE, long_return="0.01", short_return="-0.01"),)
    with pytest.raises(ValueError, match="validation_end_ms"):
        chronological_split(
            rows,
            train_end_ms=2 * FIVE,
            validation_end_ms=FIVE,
        )


def test_walk_forward_splits_expand_train_and_keep_future_blocks_separate() -> None:
    rows = tuple(
        _row(
            anchor_end_ms=index * FIVE,
            long_return="0.01",
            short_return="-0.01",
        )
        for index in range(1, 11)
    )

    folds = walk_forward_splits(
        rows,
        min_train_anchors=4,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=2,
        embargo_anchors=1,
    )

    assert len(folds) == 1
    fold = folds[0]
    assert {row.anchor_end_ms for row in fold.train} == {1 * FIVE, 2 * FIVE, 3 * FIVE, 4 * FIVE}
    assert {row.anchor_end_ms for row in fold.validation} == {6 * FIVE, 7 * FIVE}
    assert {row.anchor_end_ms for row in fold.test} == {9 * FIVE, 10 * FIVE}


def test_shared_baseline_estimates_long_and_short_independently() -> None:
    rows = (
        _row(anchor_end_ms=1 * FIVE, long_return="0.02", short_return="-0.02"),
        _row(anchor_end_ms=2 * FIVE, long_return="0.04", short_return="-0.04"),
        _row(anchor_end_ms=3 * FIVE, long_return="-0.01", short_return="0.01"),
    )

    model = fit_conditional_baseline(rows, min_state_samples=2, min_coin_samples=4)
    estimate = model.predict(rows[0].feature, horizon_ms=FIVE)

    assert estimate.sample_count == 3
    assert estimate.expected_long_return == Decimal("0.05") / Decimal("3")
    assert estimate.expected_short_return == Decimal("-0.05") / Decimal("3")
    assert estimate.source == "shared_state"


def test_coin_calibration_overrides_shared_only_after_minimum_sample() -> None:
    shared_rows = (
        _row(market=ETH, anchor_end_ms=1 * FIVE, long_return="0.01", short_return="-0.01"),
        _row(market=ETH, anchor_end_ms=2 * FIVE, long_return="0.01", short_return="-0.01"),
        _row(market=BTC, anchor_end_ms=3 * FIVE, long_return="-0.03", short_return="0.03"),
        _row(market=BTC, anchor_end_ms=4 * FIVE, long_return="-0.03", short_return="0.03"),
    )

    sparse = fit_conditional_baseline(shared_rows, min_state_samples=2, min_coin_samples=3)
    sparse_estimate = sparse.predict(shared_rows[0].feature, horizon_ms=FIVE)
    assert sparse_estimate.source == "shared_state"

    enough = fit_conditional_baseline(
        (
            *shared_rows,
            _row(market=ETH, anchor_end_ms=5 * FIVE, long_return="0.02", short_return="-0.02"),
        ),
        min_state_samples=2,
        min_coin_samples=3,
    )
    eth_feature = replace(shared_rows[0].feature, anchor_end_ms=6 * FIVE)
    estimate = enough.predict(eth_feature, horizon_ms=FIVE)

    assert estimate.source == "coin_state"
    assert estimate.sample_count == 3
    assert estimate.expected_long_return == Decimal("0.04") / Decimal("3")
    assert estimate.expected_short_return == Decimal("-0.04") / Decimal("3")


def test_baseline_falls_back_to_horizon_when_state_is_sparse() -> None:
    rows = (
        _row(
            anchor_end_ms=1 * FIVE,
            trend=TrendRegime.UP,
            return_5m="0.01",
            long_return="0.02",
            short_return="-0.02",
        ),
        _row(
            anchor_end_ms=2 * FIVE,
            trend=TrendRegime.DOWN,
            return_5m="-0.01",
            long_return="-0.01",
            short_return="0.01",
        ),
    )
    model = fit_conditional_baseline(rows, min_state_samples=2, min_coin_samples=10)

    unseen = _feature(
        anchor_end_ms=3 * FIVE,
        trend=TrendRegime.MIXED,
        return_5m=None,
        funding_rate=None,
    )
    estimate = model.predict(unseen, horizon_ms=FIVE)

    assert estimate.source == "shared_horizon"
    assert estimate.sample_count == 2
    assert estimate.expected_long_return == Decimal("0.005")
    assert estimate.expected_short_return == Decimal("-0.005")


def test_baseline_rejects_mixed_horizon_outcome_identity_errors() -> None:
    row = _row(anchor_end_ms=FIVE, long_return="0.01", short_return="-0.01")
    bad_outcome = replace(row.outcome, market=BTC)

    with pytest.raises(ValueError):
        HistoricalTrainingRow(feature=row.feature, outcome=bad_outcome)

    with pytest.raises(HistoricalBaselineError, match="rows must not be empty"):
        fit_conditional_baseline((), min_state_samples=1, min_coin_samples=1)



def test_cost_assumptions_include_fee_slippage_and_conservative_funding_reserve() -> None:
    costs = ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0.0007"),
        round_trip_slippage_fraction=Decimal("0.0005"),
        funding_reserve_fraction_per_hour=Decimal("0.0001"),
    )

    assert costs.total_cost_fraction(5 * FIVE) == (
        Decimal("0.0012")
        + Decimal("0.0001") * Decimal(25 * 60) / Decimal(3600)
    )


def test_decision_policy_is_symmetric_and_keeps_no_trade_first_class() -> None:
    rows = (
        _row(anchor_end_ms=1 * FIVE, long_return="0.03", short_return="-0.03"),
        _row(anchor_end_ms=2 * FIVE, long_return="0.03", short_return="-0.03"),
        _row(
            anchor_end_ms=3 * FIVE,
            trend=TrendRegime.DOWN,
            return_5m="-0.01",
            long_return="-0.04",
            short_return="0.04",
        ),
        _row(
            anchor_end_ms=4 * FIVE,
            trend=TrendRegime.DOWN,
            return_5m="-0.01",
            long_return="-0.04",
            short_return="0.04",
        ),
    )
    model = fit_conditional_baseline(rows, min_state_samples=2, min_coin_samples=10)
    costs = ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0.002"),
        round_trip_slippage_fraction=Decimal("0.001"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )
    policy = DecisionPolicy(
        min_expected_net_edge=Decimal("0.01"),
        min_sample_count=2,
    )

    long_decision = policy.decide(
        model.predict(rows[0].feature, horizon_ms=FIVE),
        costs=costs,
    )
    short_decision = policy.decide(
        model.predict(rows[2].feature, horizon_ms=FIVE),
        costs=costs,
    )
    no_trade = DecisionPolicy(
        min_expected_net_edge=Decimal("0.05"),
        min_sample_count=2,
    ).decide(
        model.predict(rows[0].feature, horizon_ms=FIVE),
        costs=costs,
    )

    assert long_decision.action is DecisionAction.LONG
    assert short_decision.action is DecisionAction.SHORT
    assert no_trade.action is DecisionAction.NO_TRADE


def test_validation_only_threshold_calibration_filters_low_quality_state() -> None:
    train = (
        _row(anchor_end_ms=1 * FIVE, long_return="0.03", short_return="-0.03"),
        _row(anchor_end_ms=2 * FIVE, long_return="0.03", short_return="-0.03"),
        _row(
            anchor_end_ms=3 * FIVE,
            trend=TrendRegime.DOWN,
            return_5m="-0.01",
            long_return="-0.01",
            short_return="0.01",
        ),
        _row(
            anchor_end_ms=4 * FIVE,
            trend=TrendRegime.DOWN,
            return_5m="-0.01",
            long_return="-0.01",
            short_return="0.01",
        ),
    )
    validation = (
        _row(anchor_end_ms=5 * FIVE, long_return="0.02", short_return="-0.02"),
        _row(
            anchor_end_ms=6 * FIVE,
            trend=TrendRegime.DOWN,
            return_5m="-0.01",
            long_return="0.02",
            short_return="-0.02",
        ),
    )
    model = fit_conditional_baseline(train, min_state_samples=2, min_coin_samples=10)
    costs = ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0.003"),
        round_trip_slippage_fraction=Decimal("0.002"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )

    calibration = calibrate_no_trade_threshold(
        model,
        validation,
        costs=costs,
        candidate_thresholds=(
            Decimal("0"),
            Decimal("0.01"),
            Decimal("0.02"),
        ),
        min_sample_count=2,
        min_validation_trades=1,
    )

    assert calibration.selected_threshold == Decimal("0.01")
    selected = next(
        item
        for item in calibration.candidates
        if item.threshold == calibration.selected_threshold
    )
    assert selected.trade_count == 1
    assert selected.mean_realized_net_return == Decimal("0.015")



def test_shared_vs_coin_comparison_reports_both_variants_without_retraining() -> None:
    train = (
        _row(market=ETH, anchor_end_ms=1 * FIVE, long_return="0.03", short_return="-0.03"),
        _row(market=ETH, anchor_end_ms=2 * FIVE, long_return="0.03", short_return="-0.03"),
        _row(
            market=BTC,
            anchor_end_ms=3 * FIVE,
            long_return="-0.03",
            short_return="0.03",
        ),
        _row(
            market=BTC,
            anchor_end_ms=4 * FIVE,
            long_return="-0.03",
            short_return="0.03",
        ),
    )
    evaluation_rows = (
        _row(market=ETH, anchor_end_ms=5 * FIVE, long_return="0.02", short_return="-0.02"),
        _row(
            market=BTC,
            anchor_end_ms=6 * FIVE,
            long_return="-0.02",
            short_return="0.02",
        ),
    )
    model = fit_conditional_baseline(
        train,
        min_state_samples=2,
        min_coin_samples=2,
    )
    policy = DecisionPolicy(
        min_expected_net_edge=Decimal("0.005"),
        min_sample_count=2,
    )
    costs = ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )

    comparison = compare_shared_and_coin_calibration(
        model,
        evaluation_rows,
        policy=policy,
        costs=costs,
    )

    assert comparison.shared_only.trade_count == 0
    assert comparison.shared_only.no_trade_count == 2
    assert comparison.coin_calibrated.trade_count == 2
    assert comparison.coin_calibrated.long_count == 1
    assert comparison.coin_calibrated.short_count == 1
    assert comparison.coin_calibrated.mean_realized_net_return == Decimal("0.02")



def test_walk_forward_baseline_fits_calibrates_then_scores_future_test_blocks() -> None:
    rows = tuple(
        _row(
            anchor_end_ms=index * FIVE,
            long_return="0.03" if index <= 8 else "-0.02",
            short_return="-0.03" if index <= 8 else "0.02",
        )
        for index in range(1, 13)
    )
    costs = ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )

    report = run_walk_forward_baseline(
        rows,
        costs=costs,
        candidate_thresholds=(Decimal("0"),),
        min_train_anchors=4,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=2,
        embargo_anchors=0,
        min_state_samples=2,
        min_coin_samples=99,
        min_sample_count=2,
        min_validation_trades=1,
    )

    assert len(report.folds) == 3
    assert [fold.train_anchor_count for fold in report.folds] == [4, 6, 8]
    assert all(fold.shared_threshold == Decimal("0") for fold in report.folds)
    assert all(fold.coin_threshold == Decimal("0") for fold in report.folds)
    assert report.folds[-1].shared_test.trade_count == 2
    assert report.folds[-1].shared_test.mean_realized_net_return == Decimal("-0.02")



def test_walk_forward_threshold_is_independent_of_future_test_outcomes() -> None:
    prefix = tuple(
        _row(
            anchor_end_ms=index * FIVE,
            long_return="0.03",
            short_return="-0.03",
        )
        for index in range(1, 7)
    )
    positive_test = (
        *prefix,
        _row(anchor_end_ms=7 * FIVE, long_return="0.05", short_return="-0.05"),
        _row(anchor_end_ms=8 * FIVE, long_return="0.05", short_return="-0.05"),
    )
    negative_test = (
        *prefix,
        _row(anchor_end_ms=7 * FIVE, long_return="-0.05", short_return="0.05"),
        _row(anchor_end_ms=8 * FIVE, long_return="-0.05", short_return="0.05"),
    )
    costs = ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )
    kwargs = {
        "costs": costs,
        "candidate_thresholds": (
            Decimal("0"),
            Decimal("0.01"),
            Decimal("0.02"),
        ),
        "min_train_anchors": 4,
        "validation_anchors": 2,
        "test_anchors": 2,
        "step_anchors": 2,
        "embargo_anchors": 0,
        "min_state_samples": 2,
        "min_coin_samples": 99,
        "min_sample_count": 2,
        "min_validation_trades": 1,
    }

    positive_report = run_walk_forward_baseline(positive_test, **kwargs)
    negative_report = run_walk_forward_baseline(negative_test, **kwargs)

    assert positive_report.folds[0].shared_threshold == negative_report.folds[0].shared_threshold
    assert positive_report.folds[0].coin_threshold == negative_report.folds[0].coin_threshold
    assert positive_report.folds[0].shared_test.mean_realized_net_return == Decimal("0.05")
    assert negative_report.folds[0].shared_test.mean_realized_net_return == Decimal("-0.05")



def test_threshold_calibration_can_abstain_when_validation_has_no_qualifying_trades() -> None:
    train = (
        _row(anchor_end_ms=1 * FIVE, long_return="0.001", short_return="-0.001"),
        _row(anchor_end_ms=2 * FIVE, long_return="0.001", short_return="-0.001"),
    )
    validation = (
        _row(anchor_end_ms=3 * FIVE, long_return="0.001", short_return="-0.001"),
        _row(anchor_end_ms=4 * FIVE, long_return="0.001", short_return="-0.001"),
    )
    model = fit_conditional_baseline(train, min_state_samples=2, min_coin_samples=99)
    costs = ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0.002"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )

    calibration = calibrate_no_trade_threshold(
        model,
        validation,
        costs=costs,
        candidate_thresholds=(Decimal("0"), Decimal("0.001")),
        min_sample_count=2,
        min_validation_trades=1,
    )

    assert calibration.selected_threshold is None
    assert calibration.abstained is True
    assert all(item.trade_count == 0 for item in calibration.candidates)



def test_walk_forward_report_preserves_validation_candidates_and_test_breakdowns() -> None:
    rows = tuple(
        _row(
            market=ETH if index % 2 else BTC,
            anchor_end_ms=index * FIVE,
            trend=TrendRegime.UP if index <= 6 else TrendRegime.DOWN,
            return_5m="0.01" if index <= 6 else "-0.01",
            long_return="0.03" if index <= 6 else "-0.02",
            short_return="-0.03" if index <= 6 else "0.02",
        )
        for index in range(1, 9)
    )
    costs = ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )

    report = run_walk_forward_baseline(
        rows,
        costs=costs,
        candidate_thresholds=(Decimal("0"), Decimal("0.01")),
        min_train_anchors=4,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=2,
        embargo_anchors=0,
        min_state_samples=1,
        min_coin_samples=99,
        min_sample_count=1,
        min_validation_trades=1,
    )

    fold = report.folds[0]
    assert [item.threshold for item in fold.shared_validation_candidates] == [
        Decimal("0"),
        Decimal("0.01"),
    ]
    assert [item.threshold for item in fold.coin_validation_candidates] == [
        Decimal("0"),
        Decimal("0.01"),
    ]

    shared_breakdowns = {
        (item.dimension, item.value): item.evaluation
        for item in fold.shared_test_breakdowns
    }
    assert ("market", "BTC") in shared_breakdowns
    assert ("market", "ETH") in shared_breakdowns
    assert ("horizon_ms", str(FIVE)) in shared_breakdowns
    assert ("trend_regime", TrendRegime.DOWN.value) in shared_breakdowns
    assert ("action", "short") in shared_breakdowns
    assert shared_breakdowns[("action", "short")].trade_count == 2
