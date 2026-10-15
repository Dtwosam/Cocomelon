"""Fail-closed tests for terminal trend source account parity."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
    V2SourceGapWitness,
    read_source_gap_witness,
)
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



def test_relative_runtime_state_root_opens_two_sqlite_accounts_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    receipt = audit.verify_terminal_snapshot(Path("paper"))
    assert receipt["status"] == "terminal_source_account_snapshot_coherent"
    assert receipt["terminal_account_ids_match_signed_checkpoint"] is True
    assert receipt["lanes"]["baseline"]["matches"] is True
    assert receipt["lanes"]["candidate"]["matches"] is True
    assert receipt["original_mainnet_feed_authenticated"] is False
    assert receipt["forward_after_cost_edge_verified"] is False


def test_terminal_cli_failure_returns_nonzero_but_keeps_failure_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _fixture(tmp_path, monkeypatch, mismatch=True)
    result_path = tmp_path / "terminal-result.json"
    rc = audit.main(["--state-root", str(root), "--output", str(result_path)])
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert rc == 1
    assert result["status"] == "terminal_account_checkpoint_diverged"
    assert result["terminal_account_ids_match_signed_checkpoint"] is False
    assert result["promotion_authority"] is False
    assert result["execution_authority"] is False


def test_terminal_cli_relative_source_succeeds_only_for_matching_accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    rc = audit.main([
        "--state-root", "paper",
        "--output", "paper/source-audit-receipt.json",
    ])
    result = json.loads(
        Path("paper/source-audit-receipt.json").read_text(encoding="utf-8")
    )
    assert rc == 0
    assert result["status"] == "terminal_source_account_snapshot_coherent"
    assert result["terminal_account_ids_match_signed_checkpoint"] is True


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


def _v2_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    root = _fixture(tmp_path, monkeypatch)
    old_folder = root / audit.ROOT
    v2_folder = root / "both-side-trend-paired-shadow-v2"
    old_folder.rename(v2_folder)
    (root / audit.SUMMARY).rename(
        root / "both-side-trend-paired-shadow-v2-summary.json"
    )
    from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
        both_side_trend_matched_shadow_v2_freeze,
    )

    frozen = both_side_trend_matched_shadow_v2_freeze()
    (root / "both-side-trend-paired-shadow-v2-freeze.json").write_text(
        json.dumps(frozen.to_dict())
    )
    signed_path = v2_folder / "paired-shadow-state.json"
    state = json.loads(signed_path.read_text())
    state["portfolio_shadow_candidate_id"] = frozen.candidate_id
    V2SourceGapWitness(v2_folder, restoring=False)
    state["v2_source_gap_event_witness"] = read_source_gap_witness(
        v2_folder / "source-gap-record-witness.jsonl",
        total_processed_records=10,
    )
    state.pop("state_digest")
    state["state_digest"] = audit._state_digest(state)
    signed_path.write_text(json.dumps(state))
    summary_path = root / "both-side-trend-paired-shadow-v2-summary.json"
    summary = json.loads(summary_path.read_text())
    summary["checkpoint"] = state
    summary_path.write_text(json.dumps(summary))

    return root, v2_folder


def test_fresh_v2_terminal_parity_uses_only_v2_sqlite_and_signed_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, v2_folder = _v2_fixture(tmp_path, monkeypatch)
    result = audit.verify_terminal_snapshot(
        root,
        root_name="both-side-trend-paired-shadow-v2",
        summary_name="both-side-trend-paired-shadow-v2-summary.json",
    )
    assert result["status"] == "terminal_source_account_snapshot_coherent"
    assert result["campaign_state_root"] == "both-side-trend-paired-shadow-v2"
    assert result["frozen_v2_candidate_identity_verified"] is True
    assert result["terminal_account_ids_match_signed_checkpoint"] is True
    assert result["v2_original_received_gap_witness_matches_signed_checkpoint"] is True
    assert result["v2_received_gap_event_count"] == 0
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


@pytest.mark.parametrize("damage", [
    "uncheckpointed_tail", "missing_witness", "modified_witness",
    "forged_signed_receipt",
])
def test_v2_original_gap_receipt_cannot_be_stale_even_with_matching_accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str,
) -> None:
    root, folder = _v2_fixture(tmp_path, monkeypatch)
    witness_path = folder / "source-gap-record-witness.jsonl"
    signed_path = folder / "paired-shadow-state.json"
    summary_path = root / "both-side-trend-paired-shadow-v2-summary.json"

    if damage == "uncheckpointed_tail":
        # This is a perfectly valid new original SHA-chained row, but it is
        # NOT included in the old processed-record count or signed receipt.
        witness = V2SourceGapWitness(folder, restoring=True)
        witness.append(
            ReplayRecord(
                record_kind=SourceRecordKind.DATA_GAP,
                available_at_ms=1000,
                source="paired-terminal-test",
                schema_version=1,
                market="BTC",
                exchange_time_ms=1000,
                event_key="late-received-gap",
                payload_json=json.dumps({"reason": "disconnect"}),
                event_kind="data_gap",
            ),
            ordinal=11,
        )
    elif damage == "missing_witness":
        witness_path.unlink()
    elif damage == "modified_witness":
        witness_path.write_bytes(b"{}\\n")
    elif damage == "forged_signed_receipt":
        signed = json.loads(signed_path.read_text())
        signed["v2_source_gap_event_witness"]["witness_byte_count"] = 9
        signed.pop("state_digest")
        signed["state_digest"] = audit._state_digest(signed)
        signed_path.write_text(json.dumps(signed))
        summary = json.loads(summary_path.read_text())
        summary["checkpoint"] = signed
        summary_path.write_text(json.dumps(summary))

    result = audit.verify_terminal_snapshot(
        root,
        root_name="both-side-trend-paired-shadow-v2",
        summary_name="both-side-trend-paired-shadow-v2-summary.json",
    )
    assert result["status"] == "terminal_received_gap_witness_diverged"
    assert result["v2_original_received_gap_witness_matches_signed_checkpoint"] is False
    assert result["summary_checkpoint_matches_signed_state"] is True
    assert result["signed_ledger_receipt_verified"] is True
    assert result["terminal_account_ids_match_signed_checkpoint"] is False
    assert result["original_mainnet_feed_authenticated"] is False
    assert result["forward_after_cost_edge_verified"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


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


def test_v2_rejects_copied_v1_checkpoint_even_when_account_ids_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _fixture(tmp_path, monkeypatch)
    (root / audit.ROOT).rename(root / "both-side-trend-paired-shadow-v2")
    (root / audit.SUMMARY).rename(
        root / "both-side-trend-paired-shadow-v2-summary.json"
    )
    from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
        both_side_trend_matched_shadow_v2_freeze,
    )

    frozen = both_side_trend_matched_shadow_v2_freeze()
    (root / "both-side-trend-paired-shadow-v2-freeze.json").write_text(
        json.dumps(frozen.to_dict())
    )
    result = audit.verify_terminal_snapshot(
        root,
        root_name="both-side-trend-paired-shadow-v2",
        summary_name="both-side-trend-paired-shadow-v2-summary.json",
    )
    assert result["status"] == "unverified"
    assert "v2 state candidate identity" in str(result["reasons"])
    assert result["terminal_account_ids_match_signed_checkpoint"] is False
    assert result["frozen_v2_candidate_identity_verified"] is False
    assert result["promotion_authority"] is False
