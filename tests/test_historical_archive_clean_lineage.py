from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.historical_archive_clean_checkpoint import (
    build_archive_clean_initial_checkpoint,
)
from cocomelon.research.historical_archive_clean_cycle import (
    ArchiveCleanOperationalCycleReceipt,
    HistoricalArchiveCleanCycleError,
    load_archive_clean_operational_cycle_receipt,
    write_archive_clean_operational_cycle_receipt,
)
from cocomelon.research.historical_archive_clean_lineage import (
    HistoricalArchiveCleanLineageError,
    verify_archive_clean_cycle_lineage,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
)
from cocomelon.research.prospective_context_evidence import (
    PROSPECTIVE_EVIDENCE_CLASS,
)

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


def _coverage(expected: int, captured: int) -> str | None:
    if expected == 0:
        return None
    return str(Decimal(captured) / Decimal(expected))


def _receipt(
    spec: HistoricalArchiveCleanValidationSpec,
    *,
    restored: str,
    current: str,
    started: int,
    completed: int,
    status: str,
    expected: int,
    captured: int,
    cumulative_settled: int,
    settled_ids: tuple[str, ...] = (),
    observation_id: str | None = None,
) -> ArchiveCleanOperationalCycleReceipt:
    initial = build_archive_clean_initial_checkpoint(
        spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
    )
    return ArchiveCleanOperationalCycleReceipt(
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
        campaign_id=initial.campaign_id,
        validation_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        restored_checkpoint_id=restored,
        current_checkpoint_id=current,
        cycle_started_ms=started,
        completed_at_ms=completed,
        status=status,
        anchor_end_ms=(
            None
            if status in {"before_validation_window", "after_validation_window"}
            else spec.first_expected_anchor_ms
            + max(expected - 1, 0) * spec.anchor_interval_ms
        ),
        observation_id=observation_id,
        settled_outcome_ids=settled_ids,
        missing_settlement_signal_ids=(),
        capture_coverage=_coverage(expected, captured),
        expected_elapsed_anchor_count=expected,
        captured_elapsed_anchor_count=captured,
        cumulative_settled_outcome_count=cumulative_settled,
        pending_signal_count=0,
        cycle_evidence_digest="1" * 64,
        cycle_evidence_file_count=0,
        source_digest="2" * 64,
        source_file_count=0,
    )


def _valid_chain(
    spec: HistoricalArchiveCleanValidationSpec,
) -> tuple[ArchiveCleanOperationalCycleReceipt, ...]:
    initial = build_archive_clean_initial_checkpoint(
        spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
    )
    first = _receipt(
        spec,
        restored=initial.checkpoint_id,
        current="3" * 64,
        started=10,
        completed=20,
        status="before_validation_window",
        expected=0,
        captured=0,
        cumulative_settled=0,
    )
    second = _receipt(
        spec,
        restored=first.current_checkpoint_id,
        current="4" * 64,
        started=21,
        completed=30,
        status="recorded",
        expected=1,
        captured=1,
        cumulative_settled=0,
        observation_id="5" * 64,
    )
    third = _receipt(
        spec,
        restored=second.current_checkpoint_id,
        current="6" * 64,
        started=31,
        completed=40,
        status="already_recorded",
        expected=1,
        captured=1,
        cumulative_settled=1,
        settled_ids=("7" * 64,),
        observation_id="5" * 64,
    )
    fourth = _receipt(
        spec,
        restored=third.current_checkpoint_id,
        current="9" * 64,
        started=41,
        completed=50,
        status="recorded",
        expected=2,
        captured=2,
        cumulative_settled=2,
        settled_ids=("a" * 64,),
        observation_id="b" * 64,
    )
    return first, second, third, fourth


def test_cycle_lineage_verifies_root_chain_and_exact_count_deltas() -> None:
    spec = _spec()
    receipts = _valid_chain(spec)

    report = verify_archive_clean_cycle_lineage(
        spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
        receipts=reversed(receipts),
    )

    initial = build_archive_clean_initial_checkpoint(
        spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
    )
    assert report.status == "append_only_valid"
    assert report.initial_checkpoint_id == initial.checkpoint_id
    assert report.latest_checkpoint_id == receipts[-1].current_checkpoint_id
    assert report.receipt_count == 4
    assert report.latest_expected_elapsed_anchor_count == 2
    assert report.latest_captured_elapsed_anchor_count == 2
    assert report.cumulative_settled_outcome_count == 2
    assert report.unique_settled_outcome_count == 2
    assert len(report.receipt_sequence_sha256) == 64
    assert len(report.lineage_id) == 64
    assert report.promotion_eligible is False
    assert report.execution_ready is False


def test_cycle_lineage_rejects_checkpoint_fork() -> None:
    spec = _spec()
    receipts = list(_valid_chain(spec))
    receipts[2] = _receipt(
        spec,
        restored="f" * 64,
        current=receipts[2].current_checkpoint_id,
        started=31,
        completed=40,
        status="already_recorded",
        expected=1,
        captured=1,
        cumulative_settled=1,
        settled_ids=("7" * 64,),
        observation_id="5" * 64,
    )

    with pytest.raises(
        HistoricalArchiveCleanLineageError,
        match="ARCHIVE_CLEAN_LINEAGE_CHECKPOINT_FORK",
    ):
        verify_archive_clean_cycle_lineage(
            spec,
            runtime_id=RUNTIME_ID,
            pin_id=PIN_ID,
            receipts=receipts,
        )


def test_cycle_lineage_rejects_capture_delta_not_matching_status() -> None:
    spec = _spec()
    initial = build_archive_clean_initial_checkpoint(
        spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
    )
    receipt = _receipt(
        spec,
        restored=initial.checkpoint_id,
        current="3" * 64,
        started=10,
        completed=20,
        status="already_recorded",
        expected=1,
        captured=1,
        cumulative_settled=0,
        observation_id="5" * 64,
    )

    with pytest.raises(
        HistoricalArchiveCleanLineageError,
        match="ARCHIVE_CLEAN_LINEAGE_CAPTURE_DELTA_MISMATCH",
    ):
        verify_archive_clean_cycle_lineage(
            spec,
            runtime_id=RUNTIME_ID,
            pin_id=PIN_ID,
            receipts=(receipt,),
        )


def test_cycle_lineage_rejects_settlement_delta_mismatch() -> None:
    spec = _spec()
    receipts = list(_valid_chain(spec))
    receipts[2] = _receipt(
        spec,
        restored=receipts[1].current_checkpoint_id,
        current="6" * 64,
        started=31,
        completed=40,
        status="already_recorded",
        expected=1,
        captured=1,
        cumulative_settled=2,
        settled_ids=("7" * 64,),
        observation_id="5" * 64,
    )

    with pytest.raises(
        HistoricalArchiveCleanLineageError,
        match="ARCHIVE_CLEAN_LINEAGE_SETTLED_DELTA_MISMATCH",
    ):
        verify_archive_clean_cycle_lineage(
            spec,
            runtime_id=RUNTIME_ID,
            pin_id=PIN_ID,
            receipts=receipts,
        )


def test_cycle_lineage_rejects_duplicate_settled_outcome_identity() -> None:
    spec = _spec()
    receipts = list(_valid_chain(spec))
    duplicate = "7" * 64
    receipts[3] = _receipt(
        spec,
        restored=receipts[2].current_checkpoint_id,
        current="9" * 64,
        started=41,
        completed=50,
        status="recorded",
        expected=2,
        captured=2,
        cumulative_settled=2,
        settled_ids=(duplicate,),
        observation_id="b" * 64,
    )

    with pytest.raises(
        HistoricalArchiveCleanLineageError,
        match="ARCHIVE_CLEAN_LINEAGE_DUPLICATE_SETTLED_OUTCOME",
    ):
        verify_archive_clean_cycle_lineage(
            spec,
            runtime_id=RUNTIME_ID,
            pin_id=PIN_ID,
            receipts=receipts,
        )


def test_cycle_lineage_rejects_overlapping_cycles() -> None:
    spec = _spec()
    receipts = list(_valid_chain(spec))
    receipts[1] = _receipt(
        spec,
        restored=receipts[0].current_checkpoint_id,
        current="4" * 64,
        started=19,
        completed=30,
        status="recorded",
        expected=1,
        captured=1,
        cumulative_settled=0,
        observation_id="5" * 64,
    )

    with pytest.raises(
        HistoricalArchiveCleanLineageError,
        match="ARCHIVE_CLEAN_LINEAGE_CYCLE_OVERLAP",
    ):
        verify_archive_clean_cycle_lineage(
            spec,
            runtime_id=RUNTIME_ID,
            pin_id=PIN_ID,
            receipts=receipts,
        )


def test_cycle_receipt_round_trips_and_detects_tampering(
    tmp_path: Path,
) -> None:
    spec = _spec()
    receipt = _valid_chain(spec)[0]
    root = tmp_path / "cycle"
    path = write_archive_clean_operational_cycle_receipt(root, receipt)

    loaded = load_archive_clean_operational_cycle_receipt(path)

    assert loaded == receipt
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["captured_elapsed_anchor_count"] = 1
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCleanCycleError,
        match="ARCHIVE_CLEAN_CYCLE_RECEIPT_INVALID",
    ):
        load_archive_clean_operational_cycle_receipt(path)
