from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.historical_archive_clean_observer_cli as cli
from cocomelon.config import ExecutionMode


class LiveSettings:
    execution_mode = ExecutionMode.LIVE
    api_url = "https://api.hyperliquid.xyz"


class PaperSettings:
    execution_mode = ExecutionMode.PAPER
    api_url = "https://api.hyperliquid.xyz"


def _runtime() -> SimpleNamespace:
    spec = SimpleNamespace(
        candidate_id="a" * 64,
        model_artifact_id="b" * 64,
        model_payload_sha256="c" * 64,
        spec_id="d" * 64,
        validation_evidence_class="prospective_clean",
        validation_start_ms=100,
        validation_end_ms=200,
        finalization_not_before_ms=300,
    )
    return SimpleNamespace(
        artifact=SimpleNamespace(),
        spec=spec,
    )


def _pinned_runtime() -> SimpleNamespace:
    runtime = _runtime()
    return SimpleNamespace(
        runtime=runtime,
        bundle=SimpleNamespace(
            runtime_id="9" * 64,
            observer_source_tree_sha256="8" * 64,
        ),
        pin=SimpleNamespace(pin_id="7" * 64),
    )


def test_payload_rejects_live_mode_before_runtime_or_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("live mode must fail before pinned runtime loading")
        ),
    )
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("live mode must fail before client construction")
        ),
    )

    with pytest.raises(
        ValueError,
        match="archive clean observer requires paper execution mode",
    ):
        cli.archive_clean_observer_payload(
            LiveSettings(),  # type: ignore[arg-type]
            runtime_root=tmp_path / "runtime",
            pin_id="7" * 64,
            root=tmp_path / "evidence",
        )


def test_payload_validates_frozen_runtime_before_client_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("invalid pinned runtime")
        ),
    )
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("client must not be built before runtime validation")
        ),
    )

    with pytest.raises(RuntimeError, match="invalid pinned runtime"):
        cli.archive_clean_observer_payload(
            PaperSettings(),  # type: ignore[arg-type]
            runtime_root=tmp_path / "runtime",
            pin_id="7" * 64,
            root=tmp_path / "evidence",
        )


def test_payload_runs_paper_cycle_and_emits_non_executable_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pinned = _pinned_runtime()
    runtime = pinned.runtime
    reader = object()
    manifest = SimpleNamespace(campaign_id="e" * 64)

    class FakeEvidenceStore:
        def __init__(self, root: Path, *, spec: object) -> None:
            assert root == tmp_path / "evidence"
            assert spec is runtime.spec
            self.manifest = manifest

        def iter_anchors(self) -> tuple[object, ...]:
            return (object(), object())

        def iter_outcomes(self) -> tuple[object, ...]:
            return (object(),)

    class FakeSourceStore:
        def __init__(self, root: Path) -> None:
            assert root == tmp_path / "evidence" / "sources"

    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: pinned,
    )
    monkeypatch.setattr(cli, "ArchiveCleanEvidenceStore", FakeEvidenceStore)
    monkeypatch.setattr(cli, "ArchiveCleanSourceCaptureStore", FakeSourceStore)
    monkeypatch.setattr(
        cli,
        "run_archive_clean_observer_cycle",
        lambda source, **kwargs: SimpleNamespace(
            status="recorded",
            cycle_started_ms=123,
            anchor_end_ms=119,
            observation_id="f" * 64,
            settled_outcome_ids=("1" * 64,),
            missing_settlement_signal_ids=(),
            capture_coverage="1",
            expected_elapsed_anchor_count=1,
            captured_elapsed_anchor_count=1,
        ),
    )

    payload = cli.archive_clean_observer_payload(
        PaperSettings(),  # type: ignore[arg-type]
        runtime_root=tmp_path / "runtime",
        pin_id="7" * 64,
        root=tmp_path / "evidence",
        reader=reader,  # type: ignore[arg-type]
        clock_ms=lambda: 123,
    )

    assert payload["command"] == "historical-archive-clean-observer"
    assert payload["execution_mode"] == "paper"
    assert payload["paper_only"] is True
    assert payload["prospective_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert payload["candidate_id"] == "a" * 64
    assert payload["validation_spec_id"] == "d" * 64
    assert payload["campaign_id"] == "e" * 64
    assert payload["runtime_id"] == "9" * 64
    assert payload["pin_id"] == "7" * 64
    assert payload["observer_source_tree_sha256"] == "8" * 64
    assert payload["runtime_root"] == str(tmp_path / "runtime")
    assert payload["anchor_observation_count"] == 2
    assert payload["settled_outcome_count"] == 1
    cycle = payload["cycle"]
    assert isinstance(cycle, dict)
    assert cycle["status"] == "recorded"
    assert cycle["observation_id"] == "f" * 64


def test_main_emits_json_error_for_live_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    class FakeSettings:
        @classmethod
        def from_env(cls) -> LiveSettings:
            return LiveSettings()

    monkeypatch.setattr(cli, "Settings", FakeSettings)

    status = cli.main(
        [
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--pin-id",
            "7" * 64,
            "--root",
            str(tmp_path / "evidence"),
        ]
    )

    assert status == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["error"] == "archive clean observer requires paper execution mode"
