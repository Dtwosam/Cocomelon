from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

import cocomelon.research.historical_archive_paper_scorer as scorer
from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_archive_paper_scorer import (
    ArchivePaperState,
    HistoricalArchivePaperScorerError,
    score_archive_candidate_anchor,
    score_archive_candidate_feature,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
)
from cocomelon.research.historical_features import HistoricalFeatureRow

BTC = MarketId("", "BTC")
ETH = MarketId("", "ETH")
HYPE = MarketId("", "HYPE")
FIVE = 300_000
FIFTEEN = 900_000
HOUR = 3_600_000
START = 0
END = 45 * 86_400_000


def _artifact(
    *,
    execution_policy: str = "independent_horizon",
    capacity: int | None = None,
    thresholds: tuple[tuple[int, Decimal | None], ...] = (
        (FIFTEEN, Decimal("0.002")),
        (HOUR, Decimal("0.002")),
    ),
) -> SimpleNamespace:
    return SimpleNamespace(
        artifact_id="d" * 64,
        model_payload_sha256="e" * 64,
        candidate_id="a" * 64,
        training_plan_id="b" * 64,
        calibration_id="c" * 64,
        model_family="stable_horizon_ridge",
        calibration_variant="market",
        model_format="ridge-directional-json-v1",
        selected_horizon_thresholds=thresholds,
        allow_coin_calibration=True,
        min_sample_count=20,
        execution_policy=execution_policy,
        max_concurrent_positions=capacity,
        costs={
            "round_trip_fee_fraction": "0.0007",
            "round_trip_slippage_fraction": "0.0005",
            "funding_reserve_fraction_per_hour": "0.0001",
        },
        model_payload={
            "horizons": tuple(
                {
                    "horizon_ms": horizon_ms,
                    "sample_count": 100,
                    "market_names": ("BTC", "ETH", "HYPE"),
                }
                for horizon_ms, _threshold in thresholds
            ),
        },
    )


def _spec(artifact: SimpleNamespace) -> HistoricalArchiveCleanValidationSpec:
    return HistoricalArchiveCleanValidationSpec(
        preset_name="archive-jul-sep-2026-v2",
        preset_id="preset-id",
        source_evidence_class="touched_development",
        validation_evidence_class="prospective_clean",
        candidate_id=artifact.candidate_id,
        training_plan_id=artifact.training_plan_id,
        calibration_id=artifact.calibration_id,
        model_artifact_id=artifact.artifact_id,
        model_payload_sha256=artifact.model_payload_sha256,
        model_family=artifact.model_family,
        calibration_variant=artifact.calibration_variant,
        model_format=artifact.model_format,
        markets=("BTC", "ETH", "HYPE", "SOL"),
        anchor_interval="5m",
        anchor_interval_ms=FIVE,
        anchor_end_offset_ms=FIVE - 1,
        horizon_thresholds=artifact.selected_horizon_thresholds,
        allow_coin_calibration=artifact.allow_coin_calibration,
        min_sample_count=artifact.min_sample_count,
        decision_policy="cost_adjusted_directional_threshold_v1",
        execution_policy=artifact.execution_policy,
        max_concurrent_positions=artifact.max_concurrent_positions,
        costs=dict(artifact.costs),
        validation_start_ms=START,
        validation_end_ms=END,
        min_capture_coverage=Decimal("0.90"),
        min_settled_trades=80,
        stability_blocks=4,
        min_block_trades=15,
        min_mean_net_return=Decimal("0"),
        min_block_mean_net_return=Decimal("0"),
    )


def _feature(
    market: MarketId,
    *,
    anchor_end_ms: int = FIVE - 1,
) -> HistoricalFeatureRow:
    return HistoricalFeatureRow(
        market=market,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=Decimal("0.01"),
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=Decimal("0.03"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.5"),
        funding_rate=Decimal("0.0001"),
        funding_change=Decimal("0.00001"),
        funding_premium=Decimal("0.0002"),
        funding_premium_change=Decimal("0.00001"),
        funding_age_ms=0,
        candle_15m_age_ms=0,
        trend_regime=TrendRegime.UP,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=anchor_end_ms + 1,
        retrieved_after_anchor=True,
        available_features=(),
        unavailable_features=(),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-a",),
    )


def _install_predictions(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[tuple[str, int], Decimal],
) -> None:
    monkeypatch.setattr(
        scorer,
        "predict_archive_candidate_model",
        lambda _artifact, feature, *, horizon_ms: values[
            (feature.market.canonical, horizon_ms)
        ],
    )


def test_feature_scorer_applies_costs_thresholds_and_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact()
    spec = _spec(artifact)
    _install_predictions(
        monkeypatch,
        {
            ("BTC", FIFTEEN): Decimal("0.010"),
            ("BTC", HOUR): Decimal("-0.012"),
        },
    )

    long_signal = score_archive_candidate_feature(
        artifact,
        spec,
        _feature(BTC),
        horizon_ms=FIFTEEN,
    )
    short_signal = score_archive_candidate_feature(
        artifact,
        spec,
        _feature(BTC),
        horizon_ms=HOUR,
    )

    assert long_signal.direction is Direction.LONG
    assert long_signal.expected_long_gross_return == Decimal("0.010")
    assert long_signal.expected_short_gross_return == Decimal("-0.010")
    assert long_signal.expected_long_net_return == Decimal("0.008775")
    assert long_signal.expected_net_edge == Decimal("0.008775")
    assert long_signal.reason_codes == ("long_edge_selected",)
    assert long_signal.paper_only is True

    assert short_signal.direction is Direction.SHORT
    assert short_signal.expected_short_gross_return == Decimal("0.012")
    assert short_signal.expected_short_net_return == Decimal("0.0107")
    assert short_signal.expected_net_edge == Decimal("0.0107")
    assert short_signal.reason_codes == ("short_edge_selected",)


def test_feature_scorer_no_trades_below_strict_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact(
        thresholds=((FIFTEEN, Decimal("0.002")),),
    )
    spec = _spec(artifact)
    cost = Decimal("0.001225")
    _install_predictions(
        monkeypatch,
        {("BTC", FIFTEEN): Decimal("0.002") + cost},
    )

    signal = score_archive_candidate_feature(
        artifact,
        spec,
        _feature(BTC),
        horizon_ms=FIFTEEN,
    )

    assert signal.expected_net_edge == Decimal("0.002")
    assert signal.direction is Direction.NO_TRADE
    assert signal.reason_codes == ("edge_not_above_threshold",)


def test_feature_scorer_rejects_misaligned_or_drifted_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact(thresholds=((FIFTEEN, Decimal("0.002")),))
    spec = _spec(artifact)
    _install_predictions(
        monkeypatch,
        {("BTC", FIFTEEN): Decimal("0.01")},
    )

    with pytest.raises(
        HistoricalArchivePaperScorerError,
        match="PAPER_SCORER_ANCHOR_NOT_ALIGNED",
    ):
        score_archive_candidate_feature(
            artifact,
            spec,
            _feature(BTC, anchor_end_ms=FIVE),
            horizon_ms=FIFTEEN,
        )

    spec_drift = _spec(artifact)
    spec_drift.costs["round_trip_fee_fraction"] = "0"
    with pytest.raises(
        HistoricalArchivePaperScorerError,
        match="PAPER_SCORER_ARTIFACT_SPEC_MISMATCH",
    ):
        score_archive_candidate_feature(
            artifact,
            spec_drift,
            _feature(BTC),
            horizon_ms=FIFTEEN,
        )


def test_occupancy_policy_selects_best_horizon_and_blocks_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact(execution_policy="single_position_occupancy")
    spec = _spec(artifact)
    _install_predictions(
        monkeypatch,
        {
            ("BTC", FIFTEEN): Decimal("0.008"),
            ("BTC", HOUR): Decimal("0.012"),
        },
    )

    first = score_archive_candidate_anchor(
        artifact,
        spec,
        (_feature(BTC),),
    )

    assert len(first.accepted_signals) == 1
    assert first.accepted_signals[0].horizon_ms == HOUR
    assert tuple(item.market for item in first.next_state.positions) == ("BTC",)

    next_anchor = 2 * FIVE - 1
    _install_predictions(
        monkeypatch,
        {
            ("BTC", FIFTEEN): Decimal("0.02"),
            ("BTC", HOUR): Decimal("0.02"),
        },
    )
    second = score_archive_candidate_anchor(
        artifact,
        spec,
        (_feature(BTC, anchor_end_ms=next_anchor),),
        state=first.next_state,
    )

    assert second.accepted_signals == ()
    assert second.occupied_skip_markets == ("BTC",)
    assert second.next_state == first.next_state


def test_portfolio_capacity_ranks_markets_by_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact(
        execution_policy="portfolio_capacity",
        capacity=2,
        thresholds=((FIFTEEN, Decimal("0.002")),),
    )
    spec = _spec(artifact)
    _install_predictions(
        monkeypatch,
        {
            ("BTC", FIFTEEN): Decimal("0.010"),
            ("ETH", FIFTEEN): Decimal("0.020"),
            ("HYPE", FIFTEEN): Decimal("0.015"),
        },
    )

    result = score_archive_candidate_anchor(
        artifact,
        spec,
        (_feature(BTC), _feature(ETH), _feature(HYPE)),
    )

    assert tuple(item.market for item in result.accepted_signals) == (
        "ETH",
        "HYPE",
    )
    assert result.capacity_skip_markets == ("BTC",)
    assert tuple(item.market for item in result.next_state.positions) == (
        "ETH",
        "HYPE",
    )


def test_independent_policy_keeps_all_executable_horizons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact()
    spec = _spec(artifact)
    _install_predictions(
        monkeypatch,
        {
            ("BTC", FIFTEEN): Decimal("0.010"),
            ("BTC", HOUR): Decimal("0.012"),
        },
    )

    result = score_archive_candidate_anchor(
        artifact,
        spec,
        (_feature(BTC),),
        state=ArchivePaperState(),
    )

    assert tuple(item.horizon_ms for item in result.accepted_signals) == (
        FIFTEEN,
        HOUR,
    )
    assert result.next_state.positions == ()
    assert result.no_trade_markets == ()
