from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.research.historical_archive_candidate_package as package_mod
from cocomelon.research.historical_archive_candidate_package import (
    HistoricalArchiveCandidatePackageError,
    build_archive_clean_candidate_package,
    load_archive_clean_candidate_package,
    materialize_archive_clean_candidate_package,
    verify_archive_clean_candidate_package,
)


def _artifact() -> SimpleNamespace:
    return SimpleNamespace(
        preset_name="archive-jul-sep-2026-v2",
        preset_id="preset-id",
        evidence_class="touched_development",
        candidate_id="a" * 64,
        training_plan_id="b" * 64,
        calibration_id="c" * 64,
        bundle_id="d" * 64,
        dataset_id="e" * 64,
        artifact_id="f" * 64,
        model_payload_sha256="1" * 64,
        model_family="stable_horizon_ridge",
        calibration_variant="shared",
    )


def _spec() -> SimpleNamespace:
    return SimpleNamespace(
        validation_evidence_class="prospective_clean",
        spec_id="2" * 64,
        validation_start_ms=1_000_000,
        validation_end_ms=2_000_000,
        finalization_not_before_ms=2_900_000,
    )


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    artifact: SimpleNamespace,
    spec: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        package_mod,
        "ArchiveCleanFrozenRuntime",
        lambda *, artifact, spec: SimpleNamespace(
            artifact=artifact,
            spec=spec,
        ),
    )


def _write_source_files(root: Path) -> tuple[bytes, bytes]:
    root.mkdir(parents=True, exist_ok=True)
    model = b'{"model":"frozen"}\n'
    spec = b'{"validation":"clean"}\n'
    (root / "candidate-model.json").write_bytes(model)
    (root / "candidate-validation-spec.json").write_bytes(spec)
    return model, spec


def test_build_candidate_package_reverifies_local_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    model_bytes, spec_bytes = _write_source_files(output_root)
    artifact = _artifact()
    spec = _spec()
    captured: dict[str, object] = {}

    def verify_model(path: Path, **kwargs: object) -> SimpleNamespace:
        captured["model_path"] = path
        captured["model_kwargs"] = kwargs
        return artifact

    def verify_spec(path: Path, **kwargs: object) -> SimpleNamespace:
        captured["spec_path"] = path
        captured["spec_kwargs"] = kwargs
        return spec

    monkeypatch.setattr(
        package_mod,
        "verify_archive_candidate_model_artifact",
        verify_model,
    )
    monkeypatch.setattr(
        package_mod,
        "verify_archive_clean_validation_spec",
        verify_spec,
    )
    _patch_runtime(monkeypatch, artifact=artifact, spec=spec)

    preset = object()
    result = build_archive_clean_candidate_package(
        preset,  # type: ignore[arg-type]
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    assert captured["model_path"] == output_root / "candidate-model.json"
    assert captured["spec_path"] == output_root / "candidate-validation-spec.json"
    assert captured["model_kwargs"] == {
        "preset": preset,
        "archive_root": tmp_path / "archive",
        "source_root": tmp_path / "sources",
        "output_root": output_root,
    }
    assert captured["spec_kwargs"] == captured["model_kwargs"]
    assert result.candidate_id == artifact.candidate_id
    assert result.model_artifact_id == artifact.artifact_id
    assert result.validation_spec_id == spec.spec_id
    assert result.candidate_model_sha256 == package_mod._sha256_bytes(model_bytes)
    assert result.validation_spec_sha256 == package_mod._sha256_bytes(spec_bytes)
    assert result.local_lineage_reverified is True
    assert result.paper_only is True
    assert result.prospective_only is True
    assert result.promotion_eligible is False
    assert result.execution_ready is False
    assert len(result.package_id) == 64


def test_portable_package_round_trips_and_detects_model_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    _write_source_files(output_root)
    artifact = _artifact()
    spec = _spec()
    _patch_runtime(monkeypatch, artifact=artifact, spec=spec)
    monkeypatch.setattr(
        package_mod,
        "verify_archive_candidate_model_artifact",
        lambda *args, **kwargs: artifact,
    )
    monkeypatch.setattr(
        package_mod,
        "verify_archive_clean_validation_spec",
        lambda *args, **kwargs: spec,
    )
    package = build_archive_clean_candidate_package(
        object(),  # type: ignore[arg-type]
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )
    package_root = tmp_path / "package"
    receipt = materialize_archive_clean_candidate_package(
        output_root=output_root,
        package_root=package_root,
        package=package,
    )
    monkeypatch.setattr(
        package_mod,
        "load_archive_candidate_model_artifact",
        lambda _path: artifact,
    )
    monkeypatch.setattr(
        package_mod,
        "load_archive_clean_validation_spec",
        lambda _path: spec,
    )

    loaded = load_archive_clean_candidate_package(package_root)

    assert loaded.package == package
    assert receipt == package_root / "candidate-package.json"
    assert tuple(sorted(path.name for path in package_root.iterdir())) == (
        "candidate-model.json",
        "candidate-package.json",
        "candidate-validation-spec.json",
    )

    (package_root / "candidate-model.json").write_text(
        '{"model":"tampered"}\n',
        encoding="utf-8",
    )
    with pytest.raises(
        HistoricalArchiveCandidatePackageError,
        match="ARCHIVE_CANDIDATE_PACKAGE_LINEAGE_MISMATCH",
    ):
        load_archive_clean_candidate_package(package_root)


def test_portable_package_detects_receipt_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    _write_source_files(output_root)
    artifact = _artifact()
    spec = _spec()
    _patch_runtime(monkeypatch, artifact=artifact, spec=spec)
    monkeypatch.setattr(
        package_mod,
        "verify_archive_candidate_model_artifact",
        lambda *args, **kwargs: artifact,
    )
    monkeypatch.setattr(
        package_mod,
        "verify_archive_clean_validation_spec",
        lambda *args, **kwargs: spec,
    )
    package = build_archive_clean_candidate_package(
        object(),  # type: ignore[arg-type]
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )
    package_root = tmp_path / "package"
    materialize_archive_clean_candidate_package(
        output_root=output_root,
        package_root=package_root,
        package=package,
    )
    payload = json.loads(
        (package_root / "candidate-package.json").read_text(encoding="utf-8")
    )
    payload["model_family"] = "tampered"
    (package_root / "candidate-package.json").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCandidatePackageError,
        match="ARCHIVE_CANDIDATE_PACKAGE_ID_MISMATCH",
    ):
        load_archive_clean_candidate_package(package_root)


def test_materialize_refuses_conflicting_existing_package_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    _write_source_files(output_root)
    artifact = _artifact()
    spec = _spec()
    _patch_runtime(monkeypatch, artifact=artifact, spec=spec)
    monkeypatch.setattr(
        package_mod,
        "verify_archive_candidate_model_artifact",
        lambda *args, **kwargs: artifact,
    )
    monkeypatch.setattr(
        package_mod,
        "verify_archive_clean_validation_spec",
        lambda *args, **kwargs: spec,
    )
    package = build_archive_clean_candidate_package(
        object(),  # type: ignore[arg-type]
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "candidate-model.json").write_text(
        "conflict\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCandidatePackageError,
        match="conflicting candidate package file",
    ):
        materialize_archive_clean_candidate_package(
            output_root=output_root,
            package_root=package_root,
            package=package,
        )


def test_source_verification_compares_portable_receipt_to_rebuilt_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = SimpleNamespace(package_id="p" * 64)
    loaded = SimpleNamespace(package=expected)
    monkeypatch.setattr(
        package_mod,
        "build_archive_clean_candidate_package",
        lambda *args, **kwargs: expected,
    )
    monkeypatch.setattr(
        package_mod,
        "load_archive_clean_candidate_package",
        lambda _root: loaded,
    )

    assert verify_archive_clean_candidate_package(
        object(),  # type: ignore[arg-type]
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=tmp_path / "output",
        package_root=tmp_path / "package",
    ) is loaded
