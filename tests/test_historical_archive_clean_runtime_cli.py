from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.historical_archive_clean_runtime_cli as cli


def test_publish_cli_is_offline_and_emits_pin_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle = SimpleNamespace(
        candidate_id="a" * 64,
        model_artifact_id="b" * 64,
        validation_spec_id="c" * 64,
        runtime_id="d" * 64,
        validation_start_ms=1_000,
        validation_end_ms=2_000,
        observer_source_attestation_id="e" * 64,
        observer_source_tree_sha256="f" * 64,
    )
    pin = SimpleNamespace(
        pin_id="1" * 64,
        pinned_at_ms=999,
    )
    captured: dict[str, object] = {}

    def fake_publish(**kwargs: object) -> tuple[object, object]:
        captured.update(kwargs)
        return bundle, pin

    monkeypatch.setattr(cli, "publish_archive_clean_runtime", fake_publish)

    payload = cli.runtime_payload(
        (
            "publish",
            "--output-root",
            str(tmp_path / "output"),
            "--runtime-root",
            str(tmp_path / "runtime"),
        ),
        clock_ms=lambda: 999,
    )

    assert captured["output_root"] == tmp_path / "output"
    assert captured["publish_root"] == tmp_path / "runtime"
    assert captured["pinned_at_ms"] == 999
    assert payload["command"] == "publish"
    assert payload["paid_request_performed"] is False
    assert payload["paper_only"] is True
    assert payload["prospective_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert payload["runtime_id"] == "d" * 64
    assert payload["pin_id"] == "1" * 64
    assert payload["observer_source_tree_sha256"] == "f" * 64


def test_verify_cli_requires_exact_pin_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    pinned = SimpleNamespace(
        bundle=SimpleNamespace(
            paper_only=True,
            prospective_only=True,
            promotion_eligible=False,
            execution_ready=False,
            candidate_id="a" * 64,
            model_artifact_id="b" * 64,
            validation_spec_id="c" * 64,
            runtime_id="d" * 64,
            observer_source_tree_sha256="f" * 64,
        ),
        pin=SimpleNamespace(
            pin_id="1" * 64,
            pinned_at_ms=999,
        ),
    )

    def fake_load(
        root: Path,
        *,
        expected_pin_id: str,
    ) -> object:
        captured["root"] = root
        captured["pin_id"] = expected_pin_id
        return pinned

    monkeypatch.setattr(cli, "load_pinned_archive_clean_runtime", fake_load)

    payload = cli.runtime_payload(
        (
            "verify",
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--pin-id",
            "1" * 64,
        )
    )

    assert captured == {
        "root": tmp_path / "runtime",
        "pin_id": "1" * 64,
    }
    assert payload["command"] == "verify"
    assert payload["paid_request_performed"] is False
    assert payload["valid"] is True
    assert payload["runtime_id"] == "d" * 64
    assert payload["pin_id"] == "1" * 64
    assert payload["execution_ready"] is False


def test_main_emits_json_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("invalid runtime pin")
        ),
    )

    status = cli.main(
        [
            "verify",
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--pin-id",
            "1" * 64,
        ]
    )

    assert status == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload == {
        "error": "invalid runtime pin",
        "error_type": "RuntimeError",
    }
