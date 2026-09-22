from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.historical_archive_clean_lineage_cli as cli
from cocomelon.research.historical_archive_clean_lineage import (
    HistoricalArchiveCleanLineageError,
)


def _pinned() -> SimpleNamespace:
    return SimpleNamespace(
        runtime=SimpleNamespace(spec=SimpleNamespace()),
        bundle=SimpleNamespace(runtime_id="7" * 64),
        pin=SimpleNamespace(pin_id="8" * 64),
    )


def _report(*, latest_checkpoint_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        status="append_only_valid",
        paper_only=True,
        prospective_only=True,
        promotion_eligible=False,
        execution_ready=False,
        runtime_id="7" * 64,
        pin_id="8" * 64,
        campaign_id="9" * 64,
        validation_spec_id="a" * 64,
        candidate_id="b" * 64,
        initial_checkpoint_id="c" * 64,
        latest_checkpoint_id=latest_checkpoint_id,
        receipt_count=4,
        receipt_sequence_sha256="d" * 64,
        cumulative_settled_outcome_count=12,
        latest_expected_elapsed_anchor_count=20,
        latest_captured_elapsed_anchor_count=19,
        lineage_id="e" * 64,
    )


def test_lineage_cli_is_offline_and_binds_chain_tip_to_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    checkpoint_id = "f" * 64
    pinned = _pinned()
    checkpoint = SimpleNamespace(checkpoint_id=checkpoint_id)
    receipts_root = tmp_path / "receipts"
    receipts_root.mkdir()
    (receipts_root / "cycle-1").mkdir()
    (receipts_root / "cycle-1" / "cycle.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: pinned,
    )
    monkeypatch.setattr(
        cli,
        "load_archive_clean_operational_checkpoint",
        lambda *args, **kwargs: checkpoint,
    )

    captured_paths: dict[str, object] = {}

    def fake_verify(*args: object, **kwargs: object) -> SimpleNamespace:
        captured_paths["receipt_paths"] = kwargs["receipt_paths"]
        return _report(latest_checkpoint_id=checkpoint_id)

    monkeypatch.setattr(
        cli,
        "verify_archive_clean_cycle_lineage_paths",
        fake_verify,
    )

    payload = cli.archive_clean_lineage_payload(
        runtime_root=tmp_path / "runtime",
        pin_id="8" * 64,
        checkpoint_path=tmp_path / "checkpoint.json",
        receipts_root=receipts_root,
    )

    assert payload["command"] == "historical-archive-clean-lineage"
    assert payload["status"] == "append_only_valid"
    assert payload["paper_only"] is True
    assert payload["prospective_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert payload["latest_checkpoint_id"] == checkpoint_id
    assert payload["receipt_count"] == 4
    assert payload["cumulative_settled_outcome_count"] == 12
    assert captured_paths["receipt_paths"] == (
        receipts_root / "cycle-1" / "cycle.json",
    )

    status = cli.main(
        [
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--pin-id",
            "8" * 64,
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--receipts-root",
            str(receipts_root),
        ]
    )
    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    emitted = json.loads(captured.out)
    assert emitted["status"] == "append_only_valid"
    assert emitted["lineage_id"] == "e" * 64


def test_lineage_cli_rejects_chain_tip_checkpoint_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipts_root = tmp_path / "receipts"
    receipts_root.mkdir()
    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: _pinned(),
    )
    monkeypatch.setattr(
        cli,
        "load_archive_clean_operational_checkpoint",
        lambda *args, **kwargs: SimpleNamespace(checkpoint_id="f" * 64),
    )
    monkeypatch.setattr(
        cli,
        "verify_archive_clean_cycle_lineage_paths",
        lambda *args, **kwargs: _report(latest_checkpoint_id="1" * 64),
    )

    with pytest.raises(
        HistoricalArchiveCleanLineageError,
        match="ARCHIVE_CLEAN_LINEAGE_TIP_CHECKPOINT_MISMATCH",
    ):
        cli.archive_clean_lineage_payload(
            runtime_root=tmp_path / "runtime",
            pin_id="8" * 64,
            checkpoint_path=tmp_path / "checkpoint.json",
            receipts_root=receipts_root,
        )


def test_lineage_cli_rejects_missing_receipts_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "load_pinned_archive_clean_runtime",
        lambda *args, **kwargs: _pinned(),
    )
    monkeypatch.setattr(
        cli,
        "load_archive_clean_operational_checkpoint",
        lambda *args, **kwargs: SimpleNamespace(checkpoint_id="f" * 64),
    )

    with pytest.raises(
        HistoricalArchiveCleanLineageError,
        match="ARCHIVE_CLEAN_LINEAGE_RECEIPTS_ROOT_NOT_DIRECTORY",
    ):
        cli.archive_clean_lineage_payload(
            runtime_root=tmp_path / "runtime",
            pin_id="8" * 64,
            checkpoint_path=tmp_path / "checkpoint.json",
            receipts_root=tmp_path / "missing",
        )
