from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.research.historical_archive_clean_bootstrap import (
    HistoricalArchiveCleanBootstrapError,
    bootstrap_archive_clean_state,
    load_archive_clean_bootstrap_receipt,
    verify_archive_clean_bootstrap_state,
)
from cocomelon.research.historical_archive_clean_checkpoint import (
    load_archive_clean_operational_checkpoint,
)
from cocomelon.research.historical_archive_clean_control_plane import (
    load_archive_clean_control_plane,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
)
from cocomelon.research.prospective_context_evidence import (
    PROSPECTIVE_EVIDENCE_CLASS,
)

DAY_MS = 86_400_000


def _spec() -> HistoricalArchiveCleanValidationSpec:
    return HistoricalArchiveCleanValidationSpec(
        preset_name="test",
        preset_id="preset",
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
        markets=("BTC",),
        anchor_interval="15m",
        anchor_interval_ms=900_000,
        anchor_end_offset_ms=899_999,
        horizon_thresholds=((900_000, Decimal("0.001")),),
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
        validation_start_ms=10_000_000,
        validation_end_ms=10_000_000 + 45 * DAY_MS,
        min_capture_coverage=Decimal("0.90"),
        min_settled_trades=80,
        stability_blocks=4,
        min_block_trades=15,
        min_mean_net_return=Decimal("0"),
        min_block_mean_net_return=Decimal("0"),
    )


def _pinned(*, package_bound: bool = True) -> SimpleNamespace:
    spec = _spec()
    package_id = "3" * 64 if package_bound else None
    package_sha = "4" * 64 if package_bound else None
    return SimpleNamespace(
        runtime=SimpleNamespace(spec=spec),
        bundle=SimpleNamespace(
            runtime_id="1" * 64,
            candidate_id=spec.candidate_id,
            validation_spec_id=spec.spec_id,
            model_artifact_id=spec.model_artifact_id,
            candidate_package_id=package_id,
            candidate_package_sha256=package_sha,
            portable_package_bound=package_bound,
        ),
        pin=SimpleNamespace(
            pin_id="2" * 64,
            candidate_package_id=package_id,
            portable_package_bound=package_bound,
        ),
    )


def test_bootstrap_creates_only_empty_pre_cutover_state(tmp_path: Path) -> None:
    pinned = _pinned()

    receipt = bootstrap_archive_clean_state(
        pinned,  # type: ignore[arg-type]
        state_root=tmp_path,
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
        as_of_ms=1_000,
    )

    checkpoint = load_archive_clean_operational_checkpoint(
        tmp_path / "checkpoint.json"
    )
    control = load_archive_clean_control_plane(tmp_path / "control-plane.json")
    loaded_receipt = load_archive_clean_bootstrap_receipt(
        tmp_path / "bootstrap.json"
    )

    assert loaded_receipt == receipt
    assert receipt.checkpoint_id == checkpoint.checkpoint_id
    assert receipt.control_plane_id == control.control_plane_id
    assert receipt.candidate_package_id == pinned.bundle.candidate_package_id
    assert (
        receipt.candidate_package_sha256
        == pinned.bundle.candidate_package_sha256
    )
    assert receipt.campaign_enabled is False
    assert receipt.execution_ready is False
    assert receipt.promotion_eligible is False
    assert checkpoint.captured_anchor_count == 0
    assert checkpoint.settled_outcome_count == 0
    assert checkpoint.pending_observations == ()
    assert checkpoint.latest_anchor_end_ms is None
    assert checkpoint.as_of_ms == 1_000
    assert receipt.state_artifact_name == (
        "historical-archive-clean-bootstrap-state-" + pinned.pin.pin_id
    )
    assert len(receipt.bootstrap_id) == 64


def test_bootstrap_rerun_is_idempotent_before_cutover(tmp_path: Path) -> None:
    pinned = _pinned()
    first = bootstrap_archive_clean_state(
        pinned,  # type: ignore[arg-type]
        state_root=tmp_path,
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
        as_of_ms=1_000,
    )
    first_bytes = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    }

    second = bootstrap_archive_clean_state(
        pinned,  # type: ignore[arg-type]
        state_root=tmp_path,
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
        as_of_ms=2_000,
    )

    assert second == first
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    } == first_bytes



def test_bootstrap_state_verifies_after_cutover_without_mutation(
    tmp_path: Path,
) -> None:
    pinned = _pinned()
    created = bootstrap_archive_clean_state(
        pinned,  # type: ignore[arg-type]
        state_root=tmp_path,
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
        as_of_ms=1_000,
    )
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    }

    verified = verify_archive_clean_bootstrap_state(
        pinned,  # type: ignore[arg-type]
        state_root=tmp_path,
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
    )

    assert verified == created
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    } == before

def test_bootstrap_rejects_post_cutover_creation(tmp_path: Path) -> None:
    pinned = _pinned()

    with pytest.raises(
        HistoricalArchiveCleanBootstrapError,
        match="POST_CUTOVER_ARCHIVE_CLEAN_BOOTSTRAP_FORBIDDEN",
    ):
        bootstrap_archive_clean_state(
            pinned,  # type: ignore[arg-type]
            state_root=tmp_path,
            frozen_revision="f" * 40,
            runtime_artifact_id="123",
            as_of_ms=pinned.runtime.spec.validation_start_ms,
        )

    assert not tmp_path.exists()


def test_bootstrap_rejects_legacy_runtime_without_writing_state(
    tmp_path: Path,
) -> None:
    pinned = _pinned(package_bound=False)

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_CLEAN_CONTROL_PLANE_PORTABLE_PACKAGE_REQUIRED",
    ):
        bootstrap_archive_clean_state(
            pinned,  # type: ignore[arg-type]
            state_root=tmp_path,
            frozen_revision="f" * 40,
            runtime_artifact_id="123",
            as_of_ms=1_000,
        )

    assert not tmp_path.exists()


def test_bootstrap_rejects_unattested_existing_state(tmp_path: Path) -> None:
    pinned = _pinned()
    tmp_path.mkdir()
    (tmp_path / "checkpoint.json").write_text(
        '{"unattested":true}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCleanBootstrapError,
        match="ARCHIVE_CLEAN_BOOTSTRAP_UNATTESTED_STATE_PRESENT",
    ):
        bootstrap_archive_clean_state(
            pinned,  # type: ignore[arg-type]
            state_root=tmp_path,
            frozen_revision="f" * 40,
            runtime_artifact_id="123",
            as_of_ms=1_000,
        )


def test_bootstrap_receipt_detects_tampering(tmp_path: Path) -> None:
    pinned = _pinned()
    bootstrap_archive_clean_state(
        pinned,  # type: ignore[arg-type]
        state_root=tmp_path,
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
        as_of_ms=1_000,
    )
    path = tmp_path / "bootstrap.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["runtime_artifact_id"] = "999"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCleanBootstrapError,
        match="ARCHIVE_CLEAN_BOOTSTRAP_ID_MISMATCH",
    ):
        load_archive_clean_bootstrap_receipt(path)
