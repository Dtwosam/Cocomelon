from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import Candle, MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_archive_clean_checkpoint import (
    ArchiveCleanCheckpointEvidenceStore,
    build_archive_clean_initial_checkpoint,
    HistoricalArchiveCleanCheckpointError,
    load_archive_clean_operational_checkpoint,
)
from cocomelon.research.historical_archive_clean_evidence import (
    build_archive_clean_outcome,
)
from cocomelon.research.historical_archive_paper_scorer import (
    ArchivePaperAnchorResult,
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
RUNTIME_ID = "7" * 64
PIN_ID = "8" * 64


def _spec() -> HistoricalArchiveCleanValidationSpec:
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
        model_family="stable_horizon_ridge",
        calibration_variant="shared",
        model_format="ridge-directional-json-v1",
        markets=("BTC", "ETH"),
        anchor_interval="15m",
        anchor_interval_ms=FIFTEEN,
        anchor_end_offset_ms=FIFTEEN - 1,
        horizon_thresholds=((FIFTEEN, Decimal("0.001")),),
        allow_coin_calibration=False,
        min_sample_count=20,
        decision_policy="cost_adjusted_directional_threshold_v1",
        execution_policy="independent_horizon",
        max_concurrent_positions=None,
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
) -> ArchivePaperSignal:
    gross = Decimal("0.02") if direction is Direction.LONG else Decimal("-0.02")
    cost = Decimal("0.001225")
    return ArchivePaperSignal(
        candidate_id=spec.candidate_id,
        validation_spec_id=spec.spec_id,
        model_artifact_id=spec.model_artifact_id,
        market=market,
        anchor_end_ms=anchor_end_ms,
        horizon_ms=FIFTEEN,
        target_end_ms=anchor_end_ms + FIFTEEN,
        direction=direction,
        expected_long_gross_return=gross,
        expected_short_gross_return=-gross,
        expected_long_net_return=gross - cost,
        expected_short_net_return=-gross - cost,
        expected_net_edge=max(gross - cost, -gross - cost),
        cost_fraction=cost,
        threshold=Decimal("0.001"),
        sample_count=100,
        estimate_source="shared_ridge",
        reason_codes=(
            ("long_edge_selected",)
            if direction is Direction.LONG
            else ("short_edge_selected",)
        ),
    )


def _result(
    spec: HistoricalArchiveCleanValidationSpec,
    anchor_end_ms: int,
) -> ArchivePaperAnchorResult:
    btc = _signal(
        spec,
        market="BTC",
        anchor_end_ms=anchor_end_ms,
        direction=Direction.LONG,
    )
    eth = _signal(
        spec,
        market="ETH",
        anchor_end_ms=anchor_end_ms,
        direction=Direction.SHORT,
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


def _store(
    tmp_path: Path,
    *,
    spec: HistoricalArchiveCleanValidationSpec,
    cycle_name: str,
) -> ArchiveCleanCheckpointEvidenceStore:
    return ArchiveCleanCheckpointEvidenceStore(
        tmp_path / "checkpoint.json",
        cycle_evidence_root=tmp_path / cycle_name,
        spec=spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
    )



def test_initial_checkpoint_helper_matches_fresh_store_state(
    tmp_path: Path,
) -> None:
    spec = _spec()
    expected = build_archive_clean_initial_checkpoint(
        spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
    )
    store = _store(tmp_path, spec=spec, cycle_name="cycle")

    assert store.checkpoint == expected
    assert expected.captured_anchor_count == 0
    assert expected.settled_outcome_count == 0
    assert expected.pending_observations == ()
    assert expected.total_net_return_sum == Decimal("0")

def test_checkpoint_survives_restart_with_pending_signals(
    tmp_path: Path,
) -> None:
    spec = _spec()
    anchor = spec.first_expected_anchor_ms
    first = _store(tmp_path, spec=spec, cycle_name="cycle-1")
    observation = first.record_anchor_result(
        features=(_feature(BTC, anchor), _feature(ETH, anchor)),
        state_before=ArchivePaperState(),
        result=_result(spec, anchor),
    )
    saved = first.save(as_of_ms=anchor + 100)

    assert saved.captured_anchor_count == 1
    assert len(saved.pending_observations) == 1
    assert len(saved.pending_observations[0].pending_signal_ids) == 2
    assert first.observation_id_for_time(anchor) == observation.observation_id
    assert len(saved.captured_bitmap_hex) <= 2

    restarted = _store(tmp_path, spec=spec, cycle_name="cycle-2")
    assert restarted.checkpoint.checkpoint_id == saved.checkpoint_id
    due = restarted.due_unsettled_signals(as_of_ms=anchor + FIFTEEN)
    assert len(due) == 2
    assert {item[1].market for item in due} == {"BTC", "ETH"}


def test_checkpoint_settlement_removes_only_exact_pending_signals(
    tmp_path: Path,
) -> None:
    spec = _spec()
    anchor = spec.first_expected_anchor_ms
    store = _store(tmp_path, spec=spec, cycle_name="cycle-1")
    store.record_anchor_result(
        features=(_feature(BTC, anchor), _feature(ETH, anchor)),
        state_before=ArchivePaperState(),
        result=_result(spec, anchor),
    )
    store.save(as_of_ms=anchor + 100)

    restarted = _store(tmp_path, spec=spec, cycle_name="cycle-2")
    target = anchor + FIFTEEN
    due = restarted.due_unsettled_signals(as_of_ms=target)
    for observation, signal in due:
        market = BTC if signal.market == "BTC" else ETH
        candle = Candle(
            market=market,
            interval="15m",
            start_ms=target - FIFTEEN + 1,
            end_ms=target,
            open_px=Decimal("100"),
            high_px=Decimal("103"),
            low_px=Decimal("98"),
            close_px=Decimal("102"),
            volume=Decimal("1"),
            trade_count=1,
            source="hyperliquid-mainnet-info",
            received_at_ms=target + 100,
            schema_version=1,
        )
        outcome = build_archive_clean_outcome(
            spec,
            observation=observation,
            signal=signal,
            exit_candle=candle,
            as_of_ms=target + 100,
        )
        restarted.record_outcome(outcome)

    saved = restarted.save(as_of_ms=target + 100)
    assert saved.pending_observations == ()
    assert saved.settled_outcome_count == 2
    assert saved.total_gross_return_sum == Decimal("0.00")
    assert saved.total_modeled_cost_sum == Decimal("0.002450")
    assert saved.total_net_return_sum == Decimal("-0.002450")
    assert saved.mean_net_return == Decimal("-0.001225")
    assert saved.block_economics[0].settled_trade_count == 2
    assert saved.block_economics[0].long_trade_count == 1
    assert saved.block_economics[0].short_trade_count == 1
    assert saved.block_economics[0].net_return_sum == Decimal("-0.002450")
    assert all(
        item.settled_trade_count == 0
        for item in saved.block_economics[1:]
    )
    assert restarted.due_unsettled_signals(as_of_ms=target + 100) == ()
    assert len(tuple((tmp_path / "cycle-2" / "outcomes").glob("*/*.json"))) == 2

    reloaded = _store(tmp_path, spec=spec, cycle_name="cycle-3")
    assert reloaded.checkpoint.settled_outcome_count == 2
    assert reloaded.checkpoint.pending_observations == ()
    assert reloaded.checkpoint.block_economics == saved.block_economics
    assert reloaded.checkpoint.total_net_return_sum == saved.total_net_return_sum



def test_checkpoint_assigns_settlements_to_exact_stability_blocks(
    tmp_path: Path,
) -> None:
    spec = _spec()
    store = _store(tmp_path, spec=spec, cycle_name="cycle")
    anchors = (
        spec.first_expected_anchor_ms,
        spec.first_expected_anchor_ms
        + spec.anchors_per_stability_block * spec.anchor_interval_ms,
    )

    for anchor in anchors:
        store.record_anchor_result(
            features=(_feature(BTC, anchor), _feature(ETH, anchor)),
            state_before=ArchivePaperState(),
            result=_result(spec, anchor),
        )
        target = anchor + FIFTEEN
        for observation, signal in store.due_unsettled_signals(as_of_ms=target):
            if observation.anchor_end_ms != anchor:
                continue
            market = BTC if signal.market == "BTC" else ETH
            outcome = build_archive_clean_outcome(
                spec,
                observation=observation,
                signal=signal,
                exit_candle=Candle(
                    market=market,
                    interval="15m",
                    start_ms=target - FIFTEEN + 1,
                    end_ms=target,
                    open_px=Decimal("100"),
                    high_px=Decimal("103"),
                    low_px=Decimal("98"),
                    close_px=Decimal("102"),
                    volume=Decimal("1"),
                    trade_count=1,
                    source="hyperliquid-mainnet-info",
                    received_at_ms=target + 100,
                    schema_version=1,
                ),
                as_of_ms=target + 100,
            )
            store.record_outcome(outcome)

    checkpoint = store.save(as_of_ms=anchors[-1] + FIFTEEN + 100)

    assert checkpoint.settled_outcome_count == 4
    assert checkpoint.block_economics[0].settled_trade_count == 2
    assert checkpoint.block_economics[1].settled_trade_count == 2
    assert checkpoint.block_economics[2].settled_trade_count == 0
    assert checkpoint.block_economics[3].settled_trade_count == 0
    assert checkpoint.total_gross_return_sum == Decimal("0.00")
    assert checkpoint.total_modeled_cost_sum == Decimal("0.004900")
    assert checkpoint.total_net_return_sum == Decimal("-0.004900")
    assert checkpoint.mean_net_return == Decimal("-0.001225")


def test_checkpoint_detects_derived_economics_tampering(
    tmp_path: Path,
) -> None:
    spec = _spec()
    store = _store(tmp_path, spec=spec, cycle_name="cycle")
    saved = store.save(as_of_ms=0)
    path = tmp_path / "checkpoint.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["total_net_return_sum"] = "1"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCleanCheckpointError,
        match="ARCHIVE_CLEAN_CHECKPOINT_NET_SUM_MISMATCH",
    ):
        load_archive_clean_operational_checkpoint(path)

    assert saved.total_net_return_sum == Decimal("0")

def test_checkpoint_capture_summary_preserves_missed_anchor_accounting(
    tmp_path: Path,
) -> None:
    spec = _spec()
    first_anchor = spec.first_expected_anchor_ms
    store = _store(tmp_path, spec=spec, cycle_name="cycle")
    store.record_anchor_result(
        features=(_feature(BTC, first_anchor), _feature(ETH, first_anchor)),
        state_before=ArchivePaperState(),
        result=_result(spec, first_anchor),
    )

    summary = store.capture_summary(
        as_of_ms=first_anchor + spec.anchor_interval_ms,
    )

    assert summary.expected_elapsed_anchor_count == 2
    assert summary.captured_elapsed_anchor_count == 1
    assert summary.missing_anchor_end_ms == (
        first_anchor + spec.anchor_interval_ms,
    )
    assert summary.capture_coverage == Decimal("0.5")


def test_checkpoint_bitset_stays_compact_across_many_anchors(
    tmp_path: Path,
) -> None:
    spec = _spec()
    store = _store(tmp_path, spec=spec, cycle_name="cycle")
    state = ArchivePaperState()

    for index in range(100):
        anchor = spec.first_expected_anchor_ms + index * spec.anchor_interval_ms
        result = _result(spec, anchor)
        observation = store.record_anchor_result(
            features=(_feature(BTC, anchor), _feature(ETH, anchor)),
            state_before=state,
            result=result,
        )
        state = observation.state_after
        for pending_observation, signal in store.due_unsettled_signals(
            as_of_ms=anchor + FIFTEEN,
        ):
            market = BTC if signal.market == "BTC" else ETH
            target = signal.target_end_ms
            outcome = build_archive_clean_outcome(
                spec,
                observation=pending_observation,
                signal=signal,
                exit_candle=Candle(
                    market=market,
                    interval="15m",
                    start_ms=target - FIFTEEN + 1,
                    end_ms=target,
                    open_px=Decimal("100"),
                    high_px=Decimal("101"),
                    low_px=Decimal("99"),
                    close_px=Decimal("100"),
                    volume=Decimal("1"),
                    trade_count=1,
                    source="hyperliquid-mainnet-info",
                    received_at_ms=target + 100,
                    schema_version=1,
                ),
                as_of_ms=target + 100,
            )
            store.record_outcome(outcome)

    checkpoint = store.save(
        as_of_ms=spec.first_expected_anchor_ms + 100 * spec.anchor_interval_ms,
    )
    assert checkpoint.captured_anchor_count == 100
    assert len(checkpoint.captured_bitmap_hex) <= 25
    assert checkpoint.pending_observations == ()


def test_checkpoint_rejects_runtime_or_pin_lineage_drift(
    tmp_path: Path,
) -> None:
    spec = _spec()
    store = _store(tmp_path, spec=spec, cycle_name="cycle-1")
    store.save(as_of_ms=0)

    with pytest.raises(
        HistoricalArchiveCleanCheckpointError,
        match="ARCHIVE_CLEAN_CHECKPOINT_LINEAGE_MISMATCH",
    ):
        ArchiveCleanCheckpointEvidenceStore(
            tmp_path / "checkpoint.json",
            cycle_evidence_root=tmp_path / "cycle-2",
            spec=spec,
            runtime_id="9" * 64,
            pin_id=PIN_ID,
        )


def test_checkpoint_detects_file_tampering(tmp_path: Path) -> None:
    spec = _spec()
    store = _store(tmp_path, spec=spec, cycle_name="cycle")
    saved = store.save(as_of_ms=0)
    payload = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    payload["as_of_ms"] = 1
    (tmp_path / "checkpoint.json").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCleanCheckpointError,
        match="ARCHIVE_CLEAN_CHECKPOINT_ID_MISMATCH",
    ):
        load_archive_clean_operational_checkpoint(tmp_path / "checkpoint.json")

    assert payload["as_of_ms"] == 1
    assert saved.as_of_ms == 0


def test_checkpoint_rejects_as_of_regression(tmp_path: Path) -> None:
    spec = _spec()
    store = _store(tmp_path, spec=spec, cycle_name="cycle")
    store.save(as_of_ms=100)

    with pytest.raises(
        HistoricalArchiveCleanCheckpointError,
        match="ARCHIVE_CLEAN_CHECKPOINT_AS_OF_REGRESSION",
    ):
        store.save(as_of_ms=99)


def test_checkpoint_lineage_is_bound_to_campaign_geometry(
    tmp_path: Path,
) -> None:
    spec = _spec()
    store = _store(tmp_path, spec=spec, cycle_name="cycle-1")
    store.save(as_of_ms=0)
    changed = replace(
        spec,
        validation_start_ms=spec.validation_start_ms + FIFTEEN,
        validation_end_ms=spec.validation_end_ms + FIFTEEN,
    )

    with pytest.raises(
        HistoricalArchiveCleanCheckpointError,
        match="ARCHIVE_CLEAN_CHECKPOINT_LINEAGE_MISMATCH",
    ):
        ArchiveCleanCheckpointEvidenceStore(
            tmp_path / "checkpoint.json",
            cycle_evidence_root=tmp_path / "cycle-2",
            spec=changed,
            runtime_id=RUNTIME_ID,
            pin_id=PIN_ID,
        )
