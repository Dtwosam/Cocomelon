from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.research.historical_archive_clean_checkpoint import (
    ArchiveCleanCheckpointEvidenceStore,
)
from cocomelon.research.historical_archive_clean_control_plane import (
    HistoricalArchiveCleanControlPlaneError,
    ensure_archive_clean_control_plane,
    load_archive_clean_control_plane,
)
from cocomelon.research.historical_archive_clean_readiness import (
    STATUS_BLOCKED,
    STATUS_BOOTSTRAP_REQUIRED,
    STATUS_READY_FOR_CUTOVER,
    build_archive_clean_activation_readiness,
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
        validation_start_ms=900_000,
        validation_end_ms=900_000 + 45 * DAY_MS,
        min_capture_coverage=Decimal("0.90"),
        min_settled_trades=80,
        stability_blocks=4,
        min_block_trades=15,
        min_mean_net_return=Decimal("0"),
        min_block_mean_net_return=Decimal("0"),
    )


def _pinned() -> SimpleNamespace:
    spec = _spec()
    return SimpleNamespace(
        runtime=SimpleNamespace(spec=spec),
        bundle=SimpleNamespace(
            runtime_id="1" * 64,
            candidate_id=spec.candidate_id,
            validation_spec_id=spec.spec_id,
            model_artifact_id=spec.model_artifact_id,
            candidate_package_id="3" * 64,
            candidate_package_sha256="4" * 64,
            portable_package_bound=True,
        ),
        pin=SimpleNamespace(
            pin_id="2" * 64,
            candidate_package_id="3" * 64,
            portable_package_bound=True,
        ),
    )


def test_readiness_requires_pre_cutover_bootstrap_state(tmp_path: Path) -> None:
    result = build_archive_clean_activation_readiness(
        _pinned(),  # type: ignore[arg-type]
        state_root=tmp_path,
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
        enabled=False,
        as_of_ms=1_000,
    )

    assert result.status == STATUS_BOOTSTRAP_REQUIRED
    assert result.activation_ready is False
    assert result.operationally_valid is False
    assert result.reasons == (
        "bootstrap_checkpoint_missing",
        "campaign_not_enabled",
        "control_plane_attestation_missing",
    )



def test_readiness_blocks_legacy_unbound_runtime(tmp_path: Path) -> None:
    pinned = _pinned()
    pinned.bundle.portable_package_bound = False
    pinned.bundle.candidate_package_id = None
    pinned.bundle.candidate_package_sha256 = None
    pinned.pin.portable_package_bound = False
    pinned.pin.candidate_package_id = None

    result = build_archive_clean_activation_readiness(
        pinned,  # type: ignore[arg-type]
        state_root=tmp_path,
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
        enabled=False,
        as_of_ms=1_000,
    )

    assert result.status == STATUS_BLOCKED
    assert result.activation_ready is False
    assert "runtime_not_portable_package_bound" in result.reasons

def test_readiness_is_ready_after_valid_pre_cutover_bootstrap(
    tmp_path: Path,
) -> None:
    pinned = _pinned()
    checkpoint_path = tmp_path / "checkpoint.json"
    store = ArchiveCleanCheckpointEvidenceStore(
        checkpoint_path,
        cycle_evidence_root=tmp_path / "cycle",
        spec=pinned.runtime.spec,
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
    )
    store.save(as_of_ms=1_000)
    control = ensure_archive_clean_control_plane(
        tmp_path,
        pinned=pinned,  # type: ignore[arg-type]
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
        as_of_ms=1_000,
    )

    result = build_archive_clean_activation_readiness(
        pinned,  # type: ignore[arg-type]
        state_root=tmp_path,
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
        enabled=True,
        as_of_ms=2_000,
    )

    assert result.status == STATUS_READY_FOR_CUTOVER
    assert result.activation_ready is True
    assert result.operationally_valid is True
    assert result.control_plane_id == control.control_plane_id
    assert result.checkpoint_id is not None
    assert result.reasons == ()


def test_control_plane_loader_detects_tampering(tmp_path: Path) -> None:
    pinned = _pinned()
    control = ensure_archive_clean_control_plane(
        tmp_path,
        pinned=pinned,  # type: ignore[arg-type]
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
        as_of_ms=1_000,
    )
    path = tmp_path / "control-plane.json"
    assert load_archive_clean_control_plane(path) == control

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["runtime_artifact_id"] = "999"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCleanControlPlaneError,
        match="ARCHIVE_CLEAN_CONTROL_PLANE_ID_MISMATCH",
    ):
        load_archive_clean_control_plane(path)
