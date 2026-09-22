from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import Candle, MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_archive_clean_evidence import (
    ArchiveCleanEvidenceStore,
    HistoricalArchiveCleanEvidenceConsistencyError,
    HistoricalArchiveCleanEvidenceError,
    build_archive_clean_anchor_observation,
    build_archive_clean_outcome,
)
from cocomelon.research.historical_archive_paper_scorer import (
    ArchivePaperAnchorResult,
    ArchivePaperPosition,
    ArchivePaperSignal,
    ArchivePaperState,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
)
from cocomelon.research.historical_features import HistoricalFeatureRow
from cocomelon.research.prospective_context_evidence import (
    PROSPECTIVE_EVIDENCE_CLASS,
)

BTC = MarketId("", "BTC")
ETH = MarketId("", "ETH")
FIFTEEN = 900_000
DAY_MS = 86_400_000


def _spec(
    *,
    execution_policy: str = "independent_horizon",
    horizon_ms: int = FIFTEEN,
) -> HistoricalArchiveCleanValidationSpec:
    return HistoricalArchiveCleanValidationSpec(
        preset_name="test-preset",
        preset_id="preset-id",
        source_evidence_class="touched_development",
        validation_evidence_class=PROSPECTIVE_EVIDENCE_CLASS,
        candidate_id="a" * 64,
        training_plan_id="b" * 64,
        calibration_id="c" * 64,
        model_artifact_id="d" * 64,
        model_payload_sha256="e" * 64,
        model_family=(
            "portfolio_capacity_stable_ridge"
            if execution_policy == "portfolio_capacity"
            else "occupancy_stable_ridge"
            if execution_policy == "single_position_occupancy"
            else "stable_horizon_ridge"
        ),
        calibration_variant="shared",
        model_format="ridge-directional-json-v1",
        markets=("BTC", "ETH"),
        anchor_interval="15m",
        anchor_interval_ms=FIFTEEN,
        anchor_end_offset_ms=FIFTEEN - 1,
        horizon_thresholds=((horizon_ms, Decimal("0.001")),),
        allow_coin_calibration=False,
        min_sample_count=20,
        decision_policy="cost_adjusted_directional_threshold_v1",
        execution_policy=execution_policy,
        max_concurrent_positions=(1 if execution_policy == "portfolio_capacity" else None),
        costs={
            "round_trip_fee_fraction": "0.0007",
            "round_trip_slippage_fraction": "0.0005",
            "funding_reserve_fraction_per_hour": "0.0001",
        },
        validation_start_ms=0,
        validation_end_ms=45 * DAY_MS,
        min_capture_coverage=Decimal("0.90"),
        min_settled_trades=80,
        stability_blocks=4,
        min_block_trades=15,
        min_mean_net_return=Decimal("0"),
        min_block_mean_net_return=Decimal("0"),
    )


def _feature(market: MarketId, anchor_end_ms: int) -> HistoricalFeatureRow:
    return HistoricalFeatureRow(
        market=market,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=Decimal("0.01"),
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=Decimal("0.03"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        funding_rate=Decimal("0.0001"),
        funding_change=Decimal("0"),
        funding_premium=Decimal("0.0002"),
        funding_premium_change=Decimal("0"),
        funding_age_ms=0,
        candle_15m_age_ms=0,
        trend_regime=TrendRegime.UP,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=anchor_end_ms + 100,
        retrieved_after_anchor=True,
        available_features=(),
        unavailable_features=(),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=(f"manifest-{market.canonical}",),
    )


def _signal(
    spec: HistoricalArchiveCleanValidationSpec,
    *,
    market: str,
    anchor_end_ms: int,
    direction: Direction,
    edge: str,
) -> ArchivePaperSignal:
    value = Decimal(edge)
    cost = Decimal("0.001225")
    gross = (
        value + cost
        if direction is Direction.LONG
        else -(value + cost)
        if direction is Direction.SHORT
        else Decimal("0")
    )
    long_net = gross - cost
    short_net = -gross - cost
    return ArchivePaperSignal(
        candidate_id=spec.candidate_id,
        validation_spec_id=spec.spec_id,
        model_artifact_id=spec.model_artifact_id,
        market=market,
        anchor_end_ms=anchor_end_ms,
        horizon_ms=spec.active_horizons[0],
        target_end_ms=anchor_end_ms + spec.active_horizons[0],
        direction=direction,
        expected_long_gross_return=gross,
        expected_short_gross_return=-gross,
        expected_long_net_return=long_net,
        expected_short_net_return=short_net,
        expected_net_edge=max(long_net, short_net),
        cost_fraction=cost,
        threshold=Decimal("0.001"),
        sample_count=100,
        estimate_source="shared_ridge",
        reason_codes=(
            ("edge_not_above_threshold",)
            if direction is Direction.NO_TRADE
            else ("long_edge_selected",)
            if direction is Direction.LONG
            else ("short_edge_selected",)
        ),
    )


def _independent_result(
    spec: HistoricalArchiveCleanValidationSpec,
    anchor_end_ms: int,
) -> ArchivePaperAnchorResult:
    btc = _signal(
        spec,
        market="BTC",
        anchor_end_ms=anchor_end_ms,
        direction=Direction.LONG,
        edge="0.01",
    )
    eth = _signal(
        spec,
        market="ETH",
        anchor_end_ms=anchor_end_ms,
        direction=Direction.SHORT,
        edge="0.008",
    )
    return ArchivePaperAnchorResult(
        anchor_end_ms=anchor_end_ms,
        raw_signals=(btc, eth),
        accepted_signals=(btc, eth),
        no_trade_markets=(),
        occupied_skip_markets=(),
        capacity_skip_markets=(),
        next_state=ArchivePaperState(),
    )


def test_anchor_observation_requires_complete_market_capture() -> None:
    spec = _spec()
    anchor = spec.first_expected_anchor_ms
    result = _independent_result(spec, anchor)

    with pytest.raises(
        HistoricalArchiveCleanEvidenceError,
        match="CLEAN_EVIDENCE_MARKET_COVERAGE_MISMATCH",
    ):
        build_archive_clean_anchor_observation(
            spec,
            features=(_feature(BTC, anchor),),
            state_before=ArchivePaperState(),
            result=result,
        )



def test_anchor_observation_rejects_corrupt_state_transition() -> None:
    spec = _spec()
    anchor = spec.first_expected_anchor_ms
    result = _independent_result(spec, anchor)
    corrupt = replace(
        result,
        next_state=ArchivePaperState(
            positions=(
                ArchivePaperPosition(
                    market="BTC",
                    opened_at_ms=anchor,
                    hold_until_ms=anchor + FIFTEEN,
                    horizon_ms=FIFTEEN,
                    direction=Direction.LONG,
                    expected_net_edge=Decimal("0.01"),
                ),
            )
        ),
    )

    with pytest.raises(
        HistoricalArchiveCleanEvidenceError,
        match="CLEAN_EVIDENCE_STATE_TRANSITION_MISMATCH",
    ):
        build_archive_clean_anchor_observation(
            spec,
            features=(_feature(BTC, anchor), _feature(ETH, anchor)),
            state_before=ArchivePaperState(),
            result=corrupt,
        )

def test_store_records_anchor_idempotently_and_tracks_missing_coverage(
    tmp_path: Path,
) -> None:
    spec = _spec()
    store = ArchiveCleanEvidenceStore(tmp_path, spec=spec)
    anchor = spec.first_expected_anchor_ms
    features = (_feature(BTC, anchor), _feature(ETH, anchor))
    result = _independent_result(spec, anchor)

    observation = store.record_anchor_result(
        features=features,
        state_before=ArchivePaperState(),
        result=result,
    )
    repeated = store.record_anchor_result(
        features=features,
        state_before=ArchivePaperState(),
        result=result,
    )

    assert repeated == observation
    reloaded = ArchiveCleanEvidenceStore(tmp_path, spec=spec)
    assert reloaded.iter_anchors() == (observation,)
    summary = reloaded.capture_summary(
        as_of_ms=anchor + spec.anchor_interval_ms,
    )
    assert summary.expected_elapsed_anchor_count == 2
    assert summary.captured_elapsed_anchor_count == 1
    assert summary.missing_anchor_end_ms == (
        anchor + spec.anchor_interval_ms,
    )
    assert summary.capture_coverage == Decimal("0.5")
    assert summary.validation_window_complete is False


def test_store_settles_each_accepted_signal_against_exact_target_candle(
    tmp_path: Path,
) -> None:
    spec = _spec()
    store = ArchiveCleanEvidenceStore(tmp_path, spec=spec)
    anchor = spec.first_expected_anchor_ms
    observation = store.record_anchor_result(
        features=(_feature(BTC, anchor), _feature(ETH, anchor)),
        state_before=ArchivePaperState(),
        result=_independent_result(spec, anchor),
    )
    target = anchor + spec.active_horizons[0]

    due = store.due_unsettled_signals(as_of_ms=target)
    assert len(due) == 2

    for item_observation, signal in due:
        candle = Candle(
            market=_market(signal.market),
            interval=spec.anchor_interval,
            start_ms=target - spec.anchor_interval_ms + 1,
            end_ms=target,
            open_px=Decimal("100"),
            high_px=Decimal("103"),
            low_px=Decimal("99"),
            close_px=Decimal("102"),
            volume=Decimal("1"),
            trade_count=1,
            source="hyperliquid-mainnet-info",
            received_at_ms=target + 100,
            schema_version=1,
        )
        outcome = build_archive_clean_outcome(
            spec,
            observation=item_observation,
            signal=signal,
            exit_candle=candle,
            as_of_ms=target + 100,
        )
        store.record_outcome(outcome)

    outcomes = store.iter_outcomes()
    assert len(outcomes) == 2
    by_market = {item.market: item for item in outcomes}
    assert by_market["BTC"].gross_return == Decimal("0.02")
    assert by_market["ETH"].gross_return == Decimal("-0.02")
    assert all(
        item.net_return == item.gross_return - item.modeled_cost_fraction
        for item in outcomes
    )
    assert store.due_unsettled_signals(as_of_ms=target + 100) == ()
    assert {item.anchor_observation_id for item in outcomes} == {
        observation.observation_id
    }


def _market(canonical: str) -> MarketId:
    return MarketId("", canonical)


def test_store_rejects_state_discontinuity(
    tmp_path: Path,
) -> None:
    spec = _spec(
        execution_policy="single_position_occupancy",
        horizon_ms=3_600_000,
    )
    store = ArchiveCleanEvidenceStore(tmp_path, spec=spec)
    first = spec.first_expected_anchor_ms
    first_features = (_feature(BTC, first), _feature(ETH, first))
    btc = _signal(
        spec,
        market="BTC",
        anchor_end_ms=first,
        direction=Direction.LONG,
        edge="0.01",
    )
    eth = _signal(
        spec,
        market="ETH",
        anchor_end_ms=first,
        direction=Direction.NO_TRADE,
        edge="0",
    )
    position = ArchivePaperPosition(
        market="BTC",
        opened_at_ms=first,
        hold_until_ms=first + 3_600_000,
        horizon_ms=3_600_000,
        direction=Direction.LONG,
        expected_net_edge=btc.expected_net_edge,
    )
    first_result = ArchivePaperAnchorResult(
        anchor_end_ms=first,
        raw_signals=(btc, eth),
        accepted_signals=(btc,),
        no_trade_markets=("ETH",),
        occupied_skip_markets=(),
        capacity_skip_markets=(),
        next_state=ArchivePaperState(positions=(position,)),
    )
    first_observation = build_archive_clean_anchor_observation(
        spec,
        features=first_features,
        state_before=ArchivePaperState(),
        result=first_result,
    )
    store.record_anchor(first_observation)

    second = first + spec.anchor_interval_ms
    second_result = ArchivePaperAnchorResult(
        anchor_end_ms=second,
        raw_signals=(
            _signal(
                spec,
                market="BTC",
                anchor_end_ms=second,
                direction=Direction.NO_TRADE,
                edge="0",
            ),
            _signal(
                spec,
                market="ETH",
                anchor_end_ms=second,
                direction=Direction.NO_TRADE,
                edge="0",
            ),
        ),
        accepted_signals=(),
        no_trade_markets=("BTC", "ETH"),
        occupied_skip_markets=(),
        capacity_skip_markets=(),
        next_state=ArchivePaperState(),
    )
    second_observation = build_archive_clean_anchor_observation(
        spec,
        features=(_feature(BTC, second), _feature(ETH, second)),
        state_before=ArchivePaperState(),
        result=second_result,
    )

    with pytest.raises(
        HistoricalArchiveCleanEvidenceConsistencyError,
        match="CLEAN_EVIDENCE_STATE_CONTINUITY_MISMATCH",
    ):
        store.record_anchor(second_observation)


def test_store_detects_tampered_anchor_record(
    tmp_path: Path,
) -> None:
    spec = _spec()
    store = ArchiveCleanEvidenceStore(tmp_path, spec=spec)
    anchor = spec.first_expected_anchor_ms
    store.record_anchor_result(
        features=(_feature(BTC, anchor), _feature(ETH, anchor)),
        state_before=ArchivePaperState(),
        result=_independent_result(spec, anchor),
    )
    path = next((tmp_path / "anchors").glob("*/*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["decision_as_of_ms"] += 1
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCleanEvidenceConsistencyError,
        match="CLEAN_EVIDENCE_OBSERVATION_ID_MISMATCH",
    ):
        store.iter_anchors()


def test_store_manifest_is_bound_to_validation_spec(tmp_path: Path) -> None:
    first = _spec()
    ArchiveCleanEvidenceStore(tmp_path, spec=first)
    other = replace(first, model_artifact_id="9" * 64)

    with pytest.raises(
        HistoricalArchiveCleanEvidenceConsistencyError,
        match="CLEAN_EVIDENCE_MANIFEST_CONFLICT",
    ):
        ArchiveCleanEvidenceStore(tmp_path, spec=other)
