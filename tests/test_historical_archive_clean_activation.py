from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.research.historical_archive_clean_activation import (
    HistoricalArchiveCleanActivationError,
    build_archive_clean_activation_authorization,
    load_archive_clean_activation_authorization,
    verify_archive_clean_activation_authorization,
    write_archive_clean_activation_authorization,
)
from cocomelon.research.historical_archive_clean_bootstrap import (
    bootstrap_archive_clean_state,
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


def _bootstrap(tmp_path: Path) -> tuple[SimpleNamespace, Path]:
    pinned = _pinned()
    state_root = tmp_path / "state"
    bootstrap_archive_clean_state(
        pinned,  # type: ignore[arg-type]
        state_root=state_root,
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
        as_of_ms=1_000,
    )
    return pinned, state_root


def test_activation_authorization_binds_green_bootstrap_readiness(
    tmp_path: Path,
) -> None:
    pinned, state_root = _bootstrap(tmp_path)

    authorization = build_archive_clean_activation_authorization(
        pinned,  # type: ignore[arg-type]
        state_root=state_root,
        frozen_revision="f" * 40,
        authorization_source_revision="a" * 40,
        runtime_artifact_id="123",
        as_of_ms=2_000,
    )

    assert authorization.runtime_id == pinned.bundle.runtime_id
    assert authorization.pin_id == pinned.pin.pin_id
    assert authorization.candidate_id == pinned.bundle.candidate_id
    assert authorization.validation_spec_id == pinned.bundle.validation_spec_id
    assert authorization.model_artifact_id == pinned.bundle.model_artifact_id
    assert authorization.frozen_revision == "f" * 40
    assert authorization.authorization_source_revision == "a" * 40
    assert authorization.candidate_package_id == pinned.bundle.candidate_package_id
    assert authorization.bootstrap_checkpoint_id
    assert authorization.control_plane_id
    assert authorization.readiness_status == "ready_for_cutover"
    assert authorization.campaign_enabled_at_authorization is False
    assert authorization.activation_authorized is True
    assert authorization.paper_only is True
    assert authorization.prospective_only is True
    assert authorization.promotion_eligible is False
    assert authorization.execution_ready is False
    assert authorization.activation_artifact_name == (
        "historical-archive-clean-activation-" + pinned.pin.pin_id
    )
    assert len(authorization.authorization_id) == 64


def test_activation_authorization_is_pre_cutover_only(tmp_path: Path) -> None:
    pinned, state_root = _bootstrap(tmp_path)

    with pytest.raises(
        HistoricalArchiveCleanActivationError,
        match="POST_CUTOVER_ARCHIVE_CLEAN_ACTIVATION_AUTHORIZATION_FORBIDDEN",
    ):
        build_archive_clean_activation_authorization(
            pinned,  # type: ignore[arg-type]
            state_root=state_root,
            frozen_revision="f" * 40,
            authorization_source_revision="a" * 40,
            runtime_artifact_id="123",
            as_of_ms=pinned.runtime.spec.validation_start_ms,
        )


def test_activation_authorization_requires_valid_bootstrap(tmp_path: Path) -> None:
    pinned = _pinned()

    with pytest.raises(RuntimeError):
        build_archive_clean_activation_authorization(
            pinned,  # type: ignore[arg-type]
            state_root=tmp_path / "missing-state",
            frozen_revision="f" * 40,
            authorization_source_revision="a" * 40,
            runtime_artifact_id="123",
            as_of_ms=2_000,
        )


def test_activation_authorization_write_is_idempotent_and_conflict_safe(
    tmp_path: Path,
) -> None:
    pinned, state_root = _bootstrap(tmp_path)
    authorization = build_archive_clean_activation_authorization(
        pinned,  # type: ignore[arg-type]
        state_root=state_root,
        frozen_revision="f" * 40,
        authorization_source_revision="a" * 40,
        runtime_artifact_id="123",
        as_of_ms=2_000,
    )
    root = tmp_path / "activation"

    path = write_archive_clean_activation_authorization(root, authorization)
    repeated = write_archive_clean_activation_authorization(root, authorization)

    assert repeated == path
    assert load_archive_clean_activation_authorization(path) == authorization
    path.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(
        HistoricalArchiveCleanActivationError,
        match="ARCHIVE_CLEAN_ACTIVATION_AUTHORIZATION_CONFLICT",
    ):
        write_archive_clean_activation_authorization(root, authorization)


def test_activation_authorization_verifies_after_cutover_without_bootstrap_replay(
    tmp_path: Path,
) -> None:
    pinned, state_root = _bootstrap(tmp_path)
    authorization = build_archive_clean_activation_authorization(
        pinned,  # type: ignore[arg-type]
        state_root=state_root,
        frozen_revision="f" * 40,
        authorization_source_revision="a" * 40,
        runtime_artifact_id="123",
        as_of_ms=2_000,
    )
    path = write_archive_clean_activation_authorization(
        tmp_path / "activation",
        authorization,
    )

    verified = verify_archive_clean_activation_authorization(
        path,
        pinned=pinned,  # type: ignore[arg-type]
        state_root=state_root,
        frozen_revision="f" * 40,
        runtime_artifact_id="123",
    )

    assert verified == authorization


def test_activation_authorization_rejects_runtime_artifact_drift(
    tmp_path: Path,
) -> None:
    pinned, state_root = _bootstrap(tmp_path)
    authorization = build_archive_clean_activation_authorization(
        pinned,  # type: ignore[arg-type]
        state_root=state_root,
        frozen_revision="f" * 40,
        authorization_source_revision="a" * 40,
        runtime_artifact_id="123",
        as_of_ms=2_000,
    )
    path = write_archive_clean_activation_authorization(
        tmp_path / "activation",
        authorization,
    )

    with pytest.raises(
        HistoricalArchiveCleanActivationError,
        match="ARCHIVE_CLEAN_ACTIVATION_CONTROL_PLANE_MISMATCH",
    ):
        verify_archive_clean_activation_authorization(
            path,
            pinned=pinned,  # type: ignore[arg-type]
            state_root=state_root,
            frozen_revision="f" * 40,
            runtime_artifact_id="999",
        )


def test_activation_authorization_loader_detects_tampering(
    tmp_path: Path,
) -> None:
    pinned, state_root = _bootstrap(tmp_path)
    authorization = build_archive_clean_activation_authorization(
        pinned,  # type: ignore[arg-type]
        state_root=state_root,
        frozen_revision="f" * 40,
        authorization_source_revision="a" * 40,
        runtime_artifact_id="123",
        as_of_ms=2_000,
    )
    path = write_archive_clean_activation_authorization(
        tmp_path / "activation",
        authorization,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["runtime_artifact_id"] = "999"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCleanActivationError,
        match="ARCHIVE_CLEAN_ACTIVATION_AUTHORIZATION_ID_MISMATCH",
    ):
        load_archive_clean_activation_authorization(path)
