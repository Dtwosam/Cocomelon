from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.research.historical_archive_clean_runtime as runtime_module
from cocomelon.research.historical_archive_clean_observer import (
    ArchiveCleanFrozenRuntime,
)
from cocomelon.research.historical_archive_clean_runtime import (
    RUNTIME_SOURCE_SUBJECT_TYPE,
    HistoricalArchiveCleanRuntimeError,
    load_archive_clean_runtime_pin,
    load_pinned_archive_clean_runtime,
    publish_archive_clean_runtime,
)
from cocomelon.research.python_source_attestation import (
    PythonSourceFileAttestation,
    PythonSourceTreeAttestation,
)


def _runtime() -> ArchiveCleanFrozenRuntime:
    costs = {
        "round_trip_fee_fraction": "0.0007",
        "round_trip_slippage_fraction": "0.0005",
        "funding_reserve_fraction_per_hour": "0.0001",
    }
    spec = SimpleNamespace(
        spec_id="f" * 64,
        candidate_id="a" * 64,
        training_plan_id="1" * 64,
        calibration_id="2" * 64,
        model_artifact_id="b" * 64,
        model_payload_sha256="c" * 64,
        model_family="stable_horizon_ridge",
        calibration_variant="shared",
        model_format="ridge-directional-json-v1",
        horizon_thresholds=((900_000, Decimal("0.001")),),
        allow_coin_calibration=False,
        min_sample_count=20,
        execution_policy="independent_horizon",
        max_concurrent_positions=None,
        costs=costs,
        validation_start_ms=1_000,
        validation_end_ms=2_000,
        finalization_not_before_ms=3_000,
        paper_only=True,
        prospective_only=True,
        execution_ready=False,
        promotion_eligible=False,
    )
    artifact = SimpleNamespace(
        artifact_id=spec.model_artifact_id,
        model_payload_sha256=spec.model_payload_sha256,
        candidate_id=spec.candidate_id,
        training_plan_id=spec.training_plan_id,
        calibration_id=spec.calibration_id,
        model_family=spec.model_family,
        calibration_variant=spec.calibration_variant,
        model_format=spec.model_format,
        selected_horizon_thresholds=spec.horizon_thresholds,
        allow_coin_calibration=spec.allow_coin_calibration,
        min_sample_count=spec.min_sample_count,
        execution_policy=spec.execution_policy,
        max_concurrent_positions=spec.max_concurrent_positions,
        costs=spec.costs,
        validation_not_before_ms=spec.validation_start_ms,
        execution_ready=False,
        promotion_eligible=False,
    )
    return ArchiveCleanFrozenRuntime(
        artifact=artifact,  # type: ignore[arg-type]
        spec=spec,  # type: ignore[arg-type]
    )


def _attestation(
    subject_id: str,
    *,
    sha256: str = "3" * 64,
) -> PythonSourceTreeAttestation:
    return PythonSourceTreeAttestation(
        subject_type=RUNTIME_SOURCE_SUBJECT_TYPE,
        subject_id=subject_id,
        source_root_name="cocomelon",
        files=(
            PythonSourceFileAttestation(
                relative_path="observer.py",
                sha256=sha256,
                byte_count=10,
            ),
        ),
    )


def _install_publication_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    runtime: ArchiveCleanFrozenRuntime,
    attestation: PythonSourceTreeAttestation,
) -> None:
    monkeypatch.setattr(
        runtime_module,
        "load_archive_clean_frozen_runtime",
        lambda _root: runtime,
    )
    monkeypatch.setattr(
        runtime_module,
        "_build_source_attestation",
        lambda **kwargs: attestation,
    )


def _install_runtime_load_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    runtime: ArchiveCleanFrozenRuntime,
    attestation: PythonSourceTreeAttestation,
) -> None:
    monkeypatch.setattr(
        runtime_module,
        "load_archive_candidate_model_artifact",
        lambda _path: runtime.artifact,
    )
    monkeypatch.setattr(
        runtime_module,
        "load_archive_clean_validation_spec",
        lambda _path: runtime.spec,
    )
    monkeypatch.setattr(
        runtime_module,
        "_build_source_attestation",
        lambda **kwargs: attestation,
    )


def _write_mutable_runtime(output_root: Path) -> None:
    output_root.mkdir(parents=True)
    (output_root / "candidate-model.json").write_text(
        '{"kind":"candidate-model"}\n',
        encoding="utf-8",
    )
    (output_root / "candidate-validation-spec.json").write_text(
        '{"kind":"validation-spec"}\n',
        encoding="utf-8",
    )


def test_runtime_publication_is_content_addressed_and_pinned_before_cutover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    attestation = _attestation(runtime.spec.spec_id)
    _install_publication_fakes(
        monkeypatch,
        runtime=runtime,
        attestation=attestation,
    )
    output_root = tmp_path / "output"
    publish_root = tmp_path / "published"
    _write_mutable_runtime(output_root)

    bundle, pin = publish_archive_clean_runtime(
        output_root=output_root,
        publish_root=publish_root,
        pinned_at_ms=999,
    )

    bundle_root = publish_root / "bundles" / bundle.runtime_id
    assert (bundle_root / "candidate-model.json").is_file()
    assert (bundle_root / "candidate-validation-spec.json").is_file()
    assert (bundle_root / "observer-source.json").is_file()
    assert (bundle_root / "runtime.json").is_file()
    assert load_archive_clean_runtime_pin(publish_root / "pin.json") == pin
    assert pin.runtime_id == bundle.runtime_id
    assert pin.pinned_at_ms == 999
    assert pin.validation_start_ms == 1_000
    assert len(pin.pin_id) == 64


def test_existing_pre_cutover_pin_is_idempotent_after_cutover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    attestation = _attestation(runtime.spec.spec_id)
    _install_publication_fakes(
        monkeypatch,
        runtime=runtime,
        attestation=attestation,
    )
    output_root = tmp_path / "output"
    publish_root = tmp_path / "published"
    _write_mutable_runtime(output_root)
    first_bundle, first_pin = publish_archive_clean_runtime(
        output_root=output_root,
        publish_root=publish_root,
        pinned_at_ms=999,
    )

    second_bundle, second_pin = publish_archive_clean_runtime(
        output_root=output_root,
        publish_root=publish_root,
        pinned_at_ms=2_500,
    )

    assert second_bundle == first_bundle
    assert second_pin == first_pin
    assert second_pin.pinned_at_ms == 999


def test_new_runtime_pin_is_forbidden_at_or_after_cutover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    attestation = _attestation(runtime.spec.spec_id)
    _install_publication_fakes(
        monkeypatch,
        runtime=runtime,
        attestation=attestation,
    )
    output_root = tmp_path / "output"
    publish_root = tmp_path / "published"
    _write_mutable_runtime(output_root)

    with pytest.raises(
        HistoricalArchiveCleanRuntimeError,
        match="POST_CUTOVER_ARCHIVE_CLEAN_RUNTIME_PIN_FORBIDDEN",
    ):
        publish_archive_clean_runtime(
            output_root=output_root,
            publish_root=publish_root,
            pinned_at_ms=1_000,
        )

    assert not (publish_root / "pin.json").exists()
    assert not (publish_root / "bundles").exists()


def test_pinned_runtime_verifies_exact_files_and_current_source_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    attestation = _attestation(runtime.spec.spec_id)
    _install_publication_fakes(
        monkeypatch,
        runtime=runtime,
        attestation=attestation,
    )
    output_root = tmp_path / "output"
    publish_root = tmp_path / "published"
    _write_mutable_runtime(output_root)
    bundle, pin = publish_archive_clean_runtime(
        output_root=output_root,
        publish_root=publish_root,
        pinned_at_ms=999,
    )
    _install_runtime_load_fakes(
        monkeypatch,
        runtime=runtime,
        attestation=attestation,
    )

    loaded = load_pinned_archive_clean_runtime(
        publish_root,
        expected_pin_id=pin.pin_id,
    )

    assert loaded.runtime.artifact is runtime.artifact
    assert loaded.runtime.spec is runtime.spec
    assert loaded.bundle == bundle
    assert loaded.pin == pin
    assert loaded.source_attestation == attestation


def test_pinned_runtime_rejects_unexpected_pin_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    attestation = _attestation(runtime.spec.spec_id)
    _install_publication_fakes(
        monkeypatch,
        runtime=runtime,
        attestation=attestation,
    )
    output_root = tmp_path / "output"
    publish_root = tmp_path / "published"
    _write_mutable_runtime(output_root)
    publish_archive_clean_runtime(
        output_root=output_root,
        publish_root=publish_root,
        pinned_at_ms=999,
    )

    with pytest.raises(
        HistoricalArchiveCleanRuntimeError,
        match="ARCHIVE_CLEAN_RUNTIME_PIN_NOT_EXPECTED",
    ):
        load_pinned_archive_clean_runtime(
            publish_root,
            expected_pin_id="9" * 64,
        )


def test_pinned_runtime_rejects_model_byte_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    attestation = _attestation(runtime.spec.spec_id)
    _install_publication_fakes(
        monkeypatch,
        runtime=runtime,
        attestation=attestation,
    )
    output_root = tmp_path / "output"
    publish_root = tmp_path / "published"
    _write_mutable_runtime(output_root)
    bundle, pin = publish_archive_clean_runtime(
        output_root=output_root,
        publish_root=publish_root,
        pinned_at_ms=999,
    )
    (publish_root / "bundles" / bundle.runtime_id / "candidate-model.json").write_text(
        '{"tampered":true}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCleanRuntimeError,
        match="ARCHIVE_CLEAN_RUNTIME_MODEL_DIGEST_MISMATCH",
    ):
        load_pinned_archive_clean_runtime(
            publish_root,
            expected_pin_id=pin.pin_id,
        )


def test_pinned_runtime_rejects_observer_source_tree_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    attestation = _attestation(runtime.spec.spec_id)
    _install_publication_fakes(
        monkeypatch,
        runtime=runtime,
        attestation=attestation,
    )
    output_root = tmp_path / "output"
    publish_root = tmp_path / "published"
    _write_mutable_runtime(output_root)
    _bundle, pin = publish_archive_clean_runtime(
        output_root=output_root,
        publish_root=publish_root,
        pinned_at_ms=999,
    )
    _install_runtime_load_fakes(
        monkeypatch,
        runtime=runtime,
        attestation=_attestation(runtime.spec.spec_id, sha256="4" * 64),
    )

    with pytest.raises(
        HistoricalArchiveCleanRuntimeError,
        match="ARCHIVE_CLEAN_RUNTIME_SOURCE_TREE_DRIFT",
    ):
        load_pinned_archive_clean_runtime(
            publish_root,
            expected_pin_id=pin.pin_id,
        )
