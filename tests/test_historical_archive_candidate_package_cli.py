from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.historical_archive_candidate_package_cli as cli


def _loaded() -> SimpleNamespace:
    return SimpleNamespace(
        package=SimpleNamespace(
            package_id="a" * 64,
            candidate_id="b" * 64,
            model_artifact_id="c" * 64,
            validation_spec_id="d" * 64,
            model_payload_sha256="e" * 64,
            candidate_model_sha256="f" * 64,
            validation_spec_sha256="1" * 64,
            model_family="stable_horizon_ridge",
            calibration_variant="shared",
            validation_start_ms=1_000,
            validation_end_ms=2_000,
            finalization_not_before_ms=2_900,
            local_lineage_reverified=True,
            paper_only=True,
            prospective_only=True,
            promotion_eligible=False,
            execution_ready=False,
        )
    )


def test_build_cli_verifies_and_materializes_portable_package(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    preset = object()
    package = object()
    loaded = _loaded()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        cli,
        "get_archive_experiment_preset",
        lambda name: preset,
    )

    def build(*args: object, **kwargs: object) -> object:
        captured["build_args"] = args
        captured["build_kwargs"] = kwargs
        return package

    def materialize(**kwargs: object) -> Path:
        captured["materialize"] = kwargs
        root = kwargs["package_root"]
        assert isinstance(root, Path)
        return root / "candidate-package.json"

    monkeypatch.setattr(cli, "build_archive_clean_candidate_package", build)
    monkeypatch.setattr(
        cli,
        "materialize_archive_clean_candidate_package",
        materialize,
    )
    monkeypatch.setattr(
        cli,
        "load_archive_clean_candidate_package",
        lambda root: loaded,
    )

    status = cli.main(
        [
            "build",
            "--archive-root",
            str(tmp_path / "archive"),
            "--source-root",
            str(tmp_path / "sources"),
            "--output-root",
            str(tmp_path / "output"),
            "--package-root",
            str(tmp_path / "package"),
        ]
    )

    assert status == 0
    captured_io = capsys.readouterr()
    assert captured_io.err == ""
    payload = json.loads(captured_io.out)
    assert payload["command"] == "build"
    assert payload["valid"] is True
    assert payload["paid_request_performed"] is False
    assert payload["package_id"] == "a" * 64
    assert payload["candidate_id"] == "b" * 64
    assert payload["local_lineage_reverified"] is True
    assert payload["execution_ready"] is False
    assert captured["build_args"] == (preset,)
    assert captured["build_kwargs"] == {
        "archive_root": tmp_path / "archive",
        "source_root": tmp_path / "sources",
        "output_root": tmp_path / "output",
    }


def test_verify_portable_requires_only_package_root(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    loaded = _loaded()
    monkeypatch.setattr(
        cli,
        "load_archive_clean_candidate_package",
        lambda root: loaded,
    )
    monkeypatch.setattr(
        cli,
        "get_archive_experiment_preset",
        lambda _name: (_ for _ in ()).throw(
            AssertionError("portable verification must not load preset evidence")
        ),
    )

    status = cli.main(
        [
            "verify-portable",
            "--package-root",
            str(tmp_path / "package"),
        ]
    )

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "verify-portable"
    assert payload["valid"] is True
    assert payload["paid_request_performed"] is False
    assert payload["package_root"] == str(tmp_path / "package")


def test_cli_emits_structured_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "load_archive_clean_candidate_package",
        lambda _root: (_ for _ in ()).throw(RuntimeError("invalid package")),
    )

    status = cli.main(
        [
            "verify-portable",
            "--package-root",
            str(tmp_path / "package"),
        ]
    )

    assert status == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "error": "invalid package",
        "error_type": "RuntimeError",
    }
