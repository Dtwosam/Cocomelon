"""Cross-worker immutable ledger continuity never grants trade authority."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts import audit_both_side_trend_ledger_anchor as continuity
from scripts.audit_both_side_trend_paired_handoff import TrendPairHandoffAuditError


def _record(end_ms: int, count: int, row_digest: str, prior: str | None) -> bytes:
    return (
        json.dumps({
            "end_ms": end_ms,
            "record_count": count,
            "row_digest": row_digest,
            "previous_row_digest": prior,
        }, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _archive(path: Path, rows: tuple[bytes, ...]) -> Path:
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr(continuity.LEDGER_MEMBER, b"".join(rows))
    return path


def _rows() -> tuple[bytes, ...]:
    return (
        _record(100, 200, "a" * 64, None),
        _record(200, 400, "b" * 64, "a" * 64),
    )


def _receipt(path: Path, run_id: int) -> dict[str, object]:
    return {
        "source_run_id": run_id, "source_run_attempt": 1,
        "status": "archive_checkpoint_lineage_verified",
        "archived_execution_economics_reconciled": True,
        "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "promotion_authority": False,
        "execution_authority": False,
    }


def _check(
    anchor: Path, current: Path, *, run_id: int, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(
        continuity, "audit_trend_handoff",
        lambda **_kw: {
            "status": "archive_checkpoint_lineage_verified",
            "source_class": "completed_expected_upgrade_handoff_worker",
            "expected_upgrade_handoff_proven": True,
            "archived_execution_economics_reconciled": True,
            "promotion_authority": False,
            "execution_authority": False,
        },
    )
    return continuity.audit_original_trend_handoff_continuity(
        repository="Dtwosam/Cocomelon",
        current_run_id=run_id,
        current_attempt=1,
        current_receipt=_receipt(current, run_id),
        current_archive=current,
        anchor_run={}, anchor_jobs={}, anchor_artifacts={},
        anchor_archive=anchor,
    )


def test_exact_appended_ledger_prefix_preserved_across_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _archive(tmp_path / "original.zip", _rows())
    later = _archive(
        tmp_path / "later.zip",
        _rows() + (_record(300, 700, "c" * 64, "b" * 64),),
    )
    result = _check(original, later, run_id=38305180885, monkeypatch=monkeypatch)
    assert result["status"] == "original_anchor_forward_append_verified"
    assert result["original_archive_independently_authenticated"] is True
    assert result["original_anchor_prefix_preserved"] is True
    assert result["forward_worker_append_verified"] is True
    assert result["new_signed_checkpoint_count"] == 1
    assert result["anchored_record_count"] == 400
    assert result["successor_record_count"] == 700
    assert result["research_only"] is True
    assert result["promotion_authority"] is False
    assert result["execution_authority"] is False


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ((_record(300, 700, "c" * 64, "b" * 64),), "truncated"),
        ((
            _record(100, 200, "0" * 64, None),
            _rows()[1],
            _record(300, 700, "c" * 64, "b" * 64),
        ), "rewrote"),
        (_rows() + (_record(300, 700, "c" * 64, "0" * 64),), "not linked"),
        (_rows() + (_record(200, 700, "c" * 64, "b" * 64),), "end_ms"),
        (_rows() + (_record(300, 350, "c" * 64, "b" * 64),), "record_count"),
    ],
)
def test_successor_ledger_tamper_or_stale_checkpoint_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    rows: tuple[bytes, ...], reason: str,
) -> None:
    original = _archive(tmp_path / "original.zip", _rows())
    later = _archive(tmp_path / "later.zip", rows)
    outcome = _check(
        original, later, run_id=38305180885, monkeypatch=monkeypatch,
    )
    assert outcome["status"] == "unverified"
    assert reason in str(outcome["reasons"])
    assert outcome["forward_worker_append_verified"] is False
    assert outcome["promotion_authority"] is False
    assert outcome["execution_authority"] is False


def test_same_signed_prefix_without_new_checkpoint_is_not_forward_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _archive(tmp_path / "original.zip", _rows())
    later = _archive(tmp_path / "later.zip", _rows())
    outcome = _check(
        original, later, run_id=38305180885, monkeypatch=monkeypatch,
    )
    assert outcome["status"] == "no_new_signed_checkpoint"
    assert outcome["original_anchor_prefix_preserved"] is True
    assert outcome["forward_worker_append_verified"] is False


def test_original_source_cannot_self_certify_forward_append(
    tmp_path: Path,
) -> None:
    original = _archive(tmp_path / "original.zip", _rows())
    receipt = _receipt(original, continuity.ORIGINAL_ANCHOR_RUN_ID)
    outcome = continuity.audit_original_trend_handoff_continuity(
        repository="Dtwosam/Cocomelon",
        current_run_id=continuity.ORIGINAL_ANCHOR_RUN_ID,
        current_attempt=1,
        current_receipt=receipt,
        current_archive=original,
        anchor_run=None, anchor_jobs=None, anchor_artifacts=None,
        anchor_archive=None,
    )
    assert outcome["status"] == "original_anchor_only"
    assert outcome["forward_worker_append_verified"] is False
    assert outcome["original_anchor_prefix_preserved"] is False


def test_missing_or_untrusted_anchor_never_proves_source_continuity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _archive(
        tmp_path / "current.zip", _rows()
        + (_record(300, 700, "c" * 64, "b" * 64),),
    )
    outcome = continuity.audit_original_trend_handoff_continuity(
        repository="Dtwosam/Cocomelon",
        current_run_id=38305180885, current_attempt=1,
        current_receipt=_receipt(current, 38305180885),
        current_archive=current,
        anchor_run=None, anchor_jobs=None, anchor_artifacts=None,
        anchor_archive=None,
    )
    assert outcome["status"] == "unverified"
    assert "absent" in str(outcome["reasons"])
    anchor = _archive(tmp_path / "anchor.zip", _rows())
    monkeypatch.setattr(
        continuity, "audit_trend_handoff",
        lambda **_kw: {"status": "unverified"},
    )
    result = continuity.audit_original_trend_handoff_continuity(
        repository="Dtwosam/Cocomelon",
        current_run_id=38305180885, current_attempt=1,
        current_receipt=_receipt(current, 38305180885),
        current_archive=current,
        anchor_run={}, anchor_jobs={}, anchor_artifacts={},
        anchor_archive=anchor,
    )
    assert result["original_archive_independently_authenticated"] is False
    assert result["forward_worker_append_verified"] is False


def test_current_receipt_must_match_current_zip_bytes_and_identity(
    tmp_path: Path,
) -> None:
    current = _archive(tmp_path / "current.zip", _rows())
    receipt = _receipt(current, 38305180885)
    receipt["archive_sha256"] = "0" * 64
    outcome = continuity.audit_original_trend_handoff_continuity(
        repository="Dtwosam/Cocomelon",
        current_run_id=38305180885, current_attempt=1,
        current_receipt=receipt, current_archive=current,
        anchor_run=None, anchor_jobs=None, anchor_artifacts=None,
        anchor_archive=None,
    )
    assert outcome["status"] == "unverified"
    assert outcome["current_source_validated"] is False
    assert outcome["promotion_authority"] is False


def test_review_anchor_workflow_remains_read_only() -> None:
    workflow = Path(
        ".github/workflows/independent-both-side-trend-handoff-audit.yml"
    ).read_text(encoding="utf-8")
    assert "scripts/audit_both_side_trend_ledger_anchor.py" in workflow
    assert "SOURCE_RUN_ID" in workflow
    assert "38281228549" in workflow
    assert "forward_worker_append_verified" in workflow
    assert "original_anchor_prefix_preserved" in workflow
    assert "permissions:\n  actions: read\n  contents: read" in workflow
    assert "actions: write" not in workflow
    assert "issues: write" not in workflow
    assert "gh workflow run" not in workflow


def test_ledger_bytes_are_bounded_and_nonempty(tmp_path: Path) -> None:
    original = _archive(tmp_path / "original.zip", _rows())
    assert continuity._ledger_rows(original) == _rows()
    with pytest.raises(TrendPairHandoffAuditError, match="truncated"):
        continuity._compare_rows(_rows(), _rows()[:1])
