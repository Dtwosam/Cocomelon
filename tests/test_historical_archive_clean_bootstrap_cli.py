from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.historical_archive_clean_bootstrap_cli as cli


def test_bootstrap_cli_is_offline_and_emits_receipt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    pinned = object()
    receipt = SimpleNamespace(
        to_dict=lambda: {
            "kind": "historical-archive-clean-bootstrap",
            "runtime_id": "1" * 64,
            "pin_id": "2" * 64,
            "candidate_id": "a" * 64,
            "validation_spec_id": "b" * 64,
            "model_artifact_id": "c" * 64,
            "candidate_package_id": "d" * 64,
            "candidate_package_sha256": "e" * 64,
            "checkpoint_id": "f" * 64,
            "control_plane_id": "3" * 64,
            "frozen_revision": "4" * 40,
            "runtime_artifact_id": "123",
            "bootstrap_as_of_ms": 999,
            "validation_start_ms": 1_000,
            "state_artifact_name": "historical-archive-clean-bootstrap-state-" + "2" * 64,
            "paper_only": True,
            "prospective_only": True,
            "campaign_enabled": False,
            "promotion_eligible": False,
            "execution_ready": False,
            "schema_version": 1,
            "bootstrap_id": "5" * 64,
        }
    )
    captured: dict[str, object] = {}

    def fake_load(root: Path, *, expected_pin_id: str) -> object:
        captured["runtime_root"] = root
        captured["pin_id"] = expected_pin_id
        return pinned

    def fake_bootstrap(runtime: object, **kwargs: object) -> object:
        captured["runtime"] = runtime
        captured.update(kwargs)
        return receipt

    monkeypatch.setattr(cli, "load_pinned_archive_clean_runtime", fake_load)
    monkeypatch.setattr(cli, "bootstrap_archive_clean_state", fake_bootstrap)

    payload = cli.archive_clean_bootstrap_payload(
        runtime_root=tmp_path / "runtime",
        pin_id="2" * 64,
        state_root=tmp_path / "state",
        frozen_revision="4" * 40,
        runtime_artifact_id="123",
        clock_ms=lambda: 999,
    )

    assert captured["runtime_root"] == tmp_path / "runtime"
    assert captured["pin_id"] == "2" * 64
    assert captured["runtime"] is pinned
    assert captured["state_root"] == tmp_path / "state"
    assert captured["frozen_revision"] == "4" * 40
    assert captured["runtime_artifact_id"] == "123"
    assert captured["as_of_ms"] == 999
    assert payload["command"] == "historical-archive-clean-bootstrap"
    assert payload["campaign_enabled"] is False
    assert payload["execution_ready"] is False
    assert payload["bootstrap_id"] == "5" * 64
    assert capsys.readouterr().out == ""



def test_bootstrap_cli_verify_only_uses_post_cutover_safe_verifier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pinned = object()
    receipt = SimpleNamespace(
        to_dict=lambda: {
            "bootstrap_id": "5" * 64,
            "campaign_enabled": False,
            "execution_ready": False,
        }
    )
    calls: list[str] = []

    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: pinned,
    )
    monkeypatch.setattr(
        cli,
        "verify_archive_clean_bootstrap_state",
        lambda *args, **kwargs: calls.append("verify") or receipt,
    )
    monkeypatch.setattr(
        cli,
        "bootstrap_archive_clean_state",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("verify-only must not bootstrap state")
        ),
    )

    payload = cli.archive_clean_bootstrap_payload(
        runtime_root=tmp_path / "runtime",
        pin_id="2" * 64,
        state_root=tmp_path / "state",
        frozen_revision="4" * 40,
        runtime_artifact_id="123",
        verify_only=True,
        clock_ms=lambda: 99_999_999,
    )

    assert calls == ["verify"]
    assert payload["command"] == "historical-archive-clean-bootstrap-verify"
    assert payload["bootstrap_id"] == "5" * 64

def test_bootstrap_cli_main_emits_structured_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("invalid pinned runtime")
        ),
    )

    status = cli.main(
        [
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--pin-id",
            "2" * 64,
            "--state-root",
            str(tmp_path / "state"),
            "--frozen-revision",
            "4" * 40,
            "--runtime-artifact-id",
            "123",
        ]
    )

    assert status == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": "invalid pinned runtime",
        "error_type": "RuntimeError",
    }
