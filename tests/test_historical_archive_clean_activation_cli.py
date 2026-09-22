from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.historical_archive_clean_activation_cli as cli


def _receipt() -> SimpleNamespace:
    return SimpleNamespace(
        authorization_source_revision="8" * 40,
        to_dict=lambda: {
            "runtime_id": "1" * 64,
            "pin_id": "2" * 64,
            "campaign_id": "3" * 64,
            "candidate_id": "a" * 64,
            "validation_spec_id": "b" * 64,
            "model_artifact_id": "c" * 64,
            "candidate_package_id": "d" * 64,
            "candidate_package_sha256": "e" * 64,
            "bootstrap_id": "f" * 64,
            "bootstrap_checkpoint_id": "4" * 64,
            "control_plane_id": "5" * 64,
            "frozen_revision": "6" * 40,
            "authorization_source_revision": "8" * 40,
            "runtime_artifact_id": "123",
            "authorized_at_ms": 999,
            "validation_start_ms": 1000,
            "validation_end_ms": 2000,
            "finalization_not_before_ms": 3000,
            "activation_artifact_name": "historical-archive-clean-activation-" + "2" * 64,
            "readiness_status": "ready_for_cutover",
            "kind": "historical-archive-clean-activation-authorization",
            "paper_only": True,
            "prospective_only": True,
            "campaign_enabled_at_authorization": False,
            "activation_authorized": True,
            "promotion_eligible": False,
            "execution_ready": False,
            "schema_version": 1,
            "authorization_id": "7" * 64,
        }
    )


def test_activation_cli_authorizes_offline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pinned = object()
    receipt = _receipt()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda root, *, expected_pin_id, require_current_source_match: (
            captured.update(
                runtime_root=root,
                pin_id=expected_pin_id,
                require_current_source_match=require_current_source_match,
            )
            or pinned
        ),
    )

    def fake_build(runtime: object, **kwargs: object) -> object:
        captured["runtime"] = runtime
        captured.update(kwargs)
        return receipt

    monkeypatch.setattr(cli, "build_archive_clean_activation_authorization", fake_build)
    output = tmp_path / "authorization" / "activation.json"
    monkeypatch.setattr(
        cli,
        "write_archive_clean_activation_authorization",
        lambda root, value: (
            captured.update(authorization_root=root, authorization=value)
            or output
        ),
    )

    payload = cli.archive_clean_activation_payload(
        runtime_root=tmp_path / "runtime",
        pin_id="2" * 64,
        state_root=tmp_path / "state",
        authorization_root=tmp_path / "authorization",
        frozen_revision="6" * 40,
        authorization_source_revision="8" * 40,
        runtime_artifact_id="123",
        clock_ms=lambda: 999,
    )

    assert captured["runtime"] is pinned
    assert captured["state_root"] == tmp_path / "state"
    assert captured["frozen_revision"] == "6" * 40
    assert captured["authorization_source_revision"] == "8" * 40
    assert captured["require_current_source_match"] is False
    assert captured["runtime_artifact_id"] == "123"
    assert captured["as_of_ms"] == 999
    assert captured["authorization"] is receipt
    assert payload["command"] == "historical-archive-clean-activation-authorize"
    assert payload["authorization_id"] == "7" * 64
    assert payload["campaign_enabled_at_authorization"] is False
    assert payload["execution_ready"] is False
    assert payload["authorization_path"] == str(output)


def test_activation_cli_verify_only_does_not_reauthorize(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pinned = object()
    receipt = _receipt()
    calls: list[str] = []
    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: pinned,
    )
    monkeypatch.setattr(
        cli,
        "build_archive_clean_activation_authorization",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("verify-only must not create authorization")
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_archive_clean_activation_authorization",
        lambda *args, **kwargs: calls.append("verify") or receipt,
    )

    payload = cli.archive_clean_activation_payload(
        runtime_root=tmp_path / "runtime",
        pin_id="2" * 64,
        state_root=tmp_path / "state",
        authorization_root=tmp_path / "authorization",
        frozen_revision="6" * 40,
        authorization_source_revision="8" * 40,
        runtime_artifact_id="123",
        verify_only=True,
        clock_ms=lambda: 9_999_999,
    )

    assert calls == ["verify"]
    assert payload["command"] == "historical-archive-clean-activation-verify"
    assert payload["authorization_id"] == "7" * 64


def test_activation_cli_main_emits_structured_error(
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
            "--authorization-root",
            str(tmp_path / "authorization"),
            "--frozen-revision",
            "6" * 40,
            "--authorization-source-revision",
            "8" * 40,
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
