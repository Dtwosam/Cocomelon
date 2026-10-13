"""Fail-closed tests for terminal trend source account parity."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import verify_trend_paired_terminal_snapshot as audit


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    *, mismatch: bool = False, stale_summary: bool = False,
) -> Path:
    root = tmp_path / "paper"
    folder = root / audit.ROOT
    folder.mkdir(parents=True)
    state: dict[str, object] = {
        "schema_version": 2,
        "portfolio_shadow_candidate_id": "frozen-candidate",
        "record_count": 10,
        "last_record_available_at_ms": 1000,
        "review_ledger_row_count": 1,
        "review_ledger_latest_row_digest": "signed-row",
        "research_only": True,
        "paper_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "handoff_safe": True,
        "baseline": {"account_state_id": "signed-baseline"},
        "candidate": {"account_state_id": "signed-candidate"},
    }
    state["state_digest"] = audit._state_digest(state)
    (folder / "paired-shadow-state.json").write_text(json.dumps(state))
    (folder / "review-ledger.jsonl").write_text("{}\n")
    (root / audit.SUMMARY).write_text(
        json.dumps({
            "checkpoint_published": True,
            "checkpoint_error": None,
            "checkpoint": state if not stale_summary else {"record_count": 9},
        })
    )
    monkeypatch.setattr(
        audit, "review_ledger_receipt",
        lambda *a, **kw: {
            "row_count": 1,
            "latest_row_digest": "signed-row",
        },
    )
    for lane in ("baseline", "candidate"):
        with sqlite3.connect(folder / f"{lane}-execution.sqlite3") as db:
            db.execute(
                "CREATE TABLE paper_account_state "
                "(singleton_id INTEGER PRIMARY KEY,"
                "state_id TEXT,payload_json TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO paper_account_state VALUES (1,?,?)",
                (
                    f"later-{lane}" if mismatch else f"signed-{lane}",
                    json.dumps({"updated_at_ms": 1200}),
                ),
            )
    return root


def test_terminal_accounts_match_without_certifying_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = audit.verify_terminal_snapshot(_fixture(tmp_path, monkeypatch))
    assert result["status"] == "terminal_source_account_snapshot_coherent"
    assert result["terminal_account_ids_match_signed_checkpoint"] is True
    assert result["signed_state_digest_verified"] is True
    assert result["signed_ledger_receipt_verified"] is True
    assert result["lanes"]["baseline"]["sqlite_minus_signed_record_ms"] == 200
    assert result["forward_after_cost_edge_verified"] is False
    assert result["original_mainnet_feed_authenticated"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_both_sqlite_accounts_advance_without_signed_append_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _fixture(tmp_path, monkeypatch, mismatch=True)
    result = audit.verify_terminal_snapshot(root)
    assert result["status"] == "terminal_account_checkpoint_diverged"
    assert result["terminal_account_ids_match_signed_checkpoint"] is False
    assert result["signed_ledger_receipt_verified"] is True
    assert result["lanes"]["baseline"]["matches"] is False
    assert result["lanes"]["candidate"]["matches"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_stale_summary_fails_even_when_sqlite_accounts_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = audit.verify_terminal_snapshot(
        _fixture(tmp_path, monkeypatch, stale_summary=True)
    )
    assert result["status"] == "unverified"
    assert "published trend summary" in str(result["reasons"])


def test_tampered_signed_state_digest_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _fixture(tmp_path, monkeypatch)
    path = root / audit.ROOT / "paired-shadow-state.json"
    value = json.loads(path.read_text())
    value["record_count"] = 999
    path.write_text(json.dumps(value))
    result = audit.verify_terminal_snapshot(root)
    assert result["status"] == "unverified"
    assert "state digest mismatch" in str(result["reasons"])
    assert result["signed_ledger_receipt_verified"] is False
    assert result["promotion_authority"] is False


def test_missing_sqlite_keeps_terminal_receipt_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _fixture(tmp_path, monkeypatch)
    (root / audit.ROOT / "candidate-execution.sqlite3").unlink()
    result = audit.verify_terminal_snapshot(root)
    assert result["status"] == "unverified"
    assert "candidate SQLite account absent" in str(result["reasons"])


def test_source_workflow_audits_before_archive_upload() -> None:
    source = Path(".github/workflows/continuous-paper.yml").read_text()
    step = "Verify terminal trend paired account consistency before source ZIP"
    archive = "Upload isolated both-side trend paired-paper evidence"
    assert source.index(step) < source.index(archive)
    assert "verify_trend_paired_terminal_snapshot.py" in source
    assert "continuous-paper-state/trend-paired-terminal-consistency.json" in source
    assert "COCOMELON_EXECUTION_MODE: paper" in source


def test_fresh_v2_terminal_parity_uses_only_v2_sqlite_and_signed_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _fixture(tmp_path, monkeypatch)
    old_folder = root / audit.ROOT
    v2_folder = root / "both-side-trend-paired-shadow-v2"
    old_folder.rename(v2_folder)
    (root / audit.SUMMARY).rename(
        root / "both-side-trend-paired-shadow-v2-summary.json"
    )
    result = audit.verify_terminal_snapshot(
        root,
        root_name="both-side-trend-paired-shadow-v2",
        summary_name="both-side-trend-paired-shadow-v2-summary.json",
    )
    assert result["status"] == "terminal_source_account_snapshot_coherent"
    assert result["campaign_state_root"] == "both-side-trend-paired-shadow-v2"
    assert result["terminal_account_ids_match_signed_checkpoint"] is True
    assert result["forward_after_cost_edge_verified"] is False
    assert result["promotion_authority"] is False

    with sqlite3.connect(v2_folder / "candidate-execution.sqlite3") as db:
        db.execute(
            "UPDATE paper_account_state SET state_id=? WHERE singleton_id=1",
            ("uncheckpointed-advance",),
        )
    divergence = audit.verify_terminal_snapshot(
        root,
        root_name="both-side-trend-paired-shadow-v2",
        summary_name="both-side-trend-paired-shadow-v2-summary.json",
    )
    assert divergence["status"] == "terminal_account_checkpoint_diverged"
    assert divergence["terminal_account_ids_match_signed_checkpoint"] is False
    assert divergence["execution_authority"] is False


def test_v2_verifier_rejects_mixed_v1_summary_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _fixture(tmp_path, monkeypatch)
    result = audit.verify_terminal_snapshot(
        root,
        root_name="both-side-trend-paired-shadow-v2",
        summary_name=audit.SUMMARY,
    )
    assert result["status"] == "unverified"
    assert "unknown paired campaign identity" in str(result["reasons"])
    assert result["promotion_authority"] is False
