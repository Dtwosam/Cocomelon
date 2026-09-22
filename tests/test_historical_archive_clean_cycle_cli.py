from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.historical_archive_clean_cycle_cli as cli
from cocomelon.config import ExecutionMode


class LiveSettings:
    execution_mode = ExecutionMode.LIVE
    api_url = "https://api.hyperliquid.xyz"


class PaperSettings:
    execution_mode = ExecutionMode.PAPER
    api_url = "https://api.hyperliquid.xyz"


def _pinned() -> SimpleNamespace:
    spec = SimpleNamespace(
        spec_id="a" * 64,
        candidate_id="b" * 64,
    )
    return SimpleNamespace(
        runtime=SimpleNamespace(
            spec=spec,
            artifact=SimpleNamespace(),
        ),
        bundle=SimpleNamespace(runtime_id="c" * 64),
        pin=SimpleNamespace(pin_id="d" * 64),
    )


def test_cycle_rejects_live_mode_before_pin_or_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("live mode must fail before runtime loading")
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
        match="archive clean cycle requires paper execution mode",
    ):
        cli.archive_clean_cycle_payload(
            LiveSettings(),  # type: ignore[arg-type]
            runtime_root=tmp_path / "runtime",
            pin_id="d" * 64,
            checkpoint_path=tmp_path / "checkpoint.json",
            cycle_evidence_root=tmp_path / "evidence",
            source_root=tmp_path / "sources",
        )


def test_cycle_validates_checkpoint_before_client_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pinned = _pinned()
    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: pinned,
    )
    monkeypatch.setattr(
        cli,
        "ArchiveCleanCheckpointEvidenceStore",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("invalid checkpoint")
        ),
    )
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("client must not be built before checkpoint validation")
        ),
    )

    with pytest.raises(RuntimeError, match="invalid checkpoint"):
        cli.archive_clean_cycle_payload(
            PaperSettings(),  # type: ignore[arg-type]
            runtime_root=tmp_path / "runtime",
            pin_id="d" * 64,
            checkpoint_path=tmp_path / "checkpoint.json",
            cycle_evidence_root=tmp_path / "evidence",
            source_root=tmp_path / "sources",
        )


def test_cycle_payload_saves_checkpoint_and_emits_lineage_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pinned = _pinned()
    reader = object()
    checkpoint_before = SimpleNamespace(checkpoint_id="1" * 64)
    checkpoint_after = SimpleNamespace(
        checkpoint_id="2" * 64,
        settled_outcome_count=7,
    )

    class FakeCheckpointStore:
        campaign_id = "3" * 64

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.checkpoint = checkpoint_before

        def save(self, *, as_of_ms: int) -> object:
            assert as_of_ms == 120
            self.checkpoint = checkpoint_after
            return checkpoint_after

    class FakeSourceStore:
        def __init__(self, root: Path) -> None:
            assert root == tmp_path / "sources"

    result = SimpleNamespace(
        status="recorded",
        cycle_started_ms=100,
        anchor_end_ms=99,
        observation_id="4" * 64,
        settled_outcome_ids=("5" * 64,),
        missing_settlement_signal_ids=(),
        capture_coverage="1",
        expected_elapsed_anchor_count=1,
        captured_elapsed_anchor_count=1,
    )
    receipt = SimpleNamespace(
        receipt_id="6" * 64,
        pending_signal_count=2,
        cycle_evidence_file_count=1,
        source_file_count=4,
    )
    receipt_path = tmp_path / "evidence" / "cycle.json"

    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: pinned,
    )
    monkeypatch.setattr(
        cli,
        "ArchiveCleanCheckpointEvidenceStore",
        FakeCheckpointStore,
    )
    monkeypatch.setattr(cli, "ArchiveCleanSourceCaptureStore", FakeSourceStore)
    monkeypatch.setattr(
        cli,
        "run_archive_clean_observer_cycle",
        lambda *args, **kwargs: result,
    )
    monkeypatch.setattr(
        cli,
        "build_archive_clean_operational_cycle_receipt",
        lambda **kwargs: receipt,
    )
    monkeypatch.setattr(
        cli,
        "write_archive_clean_operational_cycle_receipt",
        lambda *args, **kwargs: receipt_path,
    )
    clock_values = iter((120,))

    payload = cli.archive_clean_cycle_payload(
        PaperSettings(),  # type: ignore[arg-type]
        runtime_root=tmp_path / "runtime",
        pin_id="d" * 64,
        checkpoint_path=tmp_path / "checkpoint.json",
        cycle_evidence_root=tmp_path / "evidence",
        source_root=tmp_path / "sources",
        reader=reader,  # type: ignore[arg-type]
        clock_ms=lambda: next(clock_values),
    )

    assert payload["command"] == "historical-archive-clean-cycle"
    assert payload["paper_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert payload["runtime_id"] == "c" * 64
    assert payload["pin_id"] == "d" * 64
    assert payload["campaign_id"] == "3" * 64
    assert payload["restored_checkpoint_id"] == "1" * 64
    assert payload["checkpoint_id"] == "2" * 64
    assert payload["receipt_id"] == "6" * 64
    assert payload["pending_signal_count"] == 2
    assert payload["cycle_evidence_file_count"] == 1
    assert payload["source_file_count"] == 4


def test_cycle_rejects_reused_cycle_roots_before_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pinned = _pinned()
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    (evidence_root / "old.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: pinned,
    )
    monkeypatch.setattr(
        cli,
        "InfoClient",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("client must not be built for reused cycle root")
        ),
    )

    with pytest.raises(
        ValueError,
        match="cycle_evidence_root must be missing or empty",
    ):
        cli.archive_clean_cycle_payload(
            PaperSettings(),  # type: ignore[arg-type]
            runtime_root=tmp_path / "runtime",
            pin_id="d" * 64,
            checkpoint_path=tmp_path / "checkpoint.json",
            cycle_evidence_root=evidence_root,
            source_root=tmp_path / "sources",
        )


def test_main_emits_json_error(
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
            "d" * 64,
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--cycle-evidence-root",
            str(tmp_path / "evidence"),
            "--source-root",
            str(tmp_path / "sources"),
        ]
    )

    assert status == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["error"] == "archive clean cycle requires paper execution mode"
