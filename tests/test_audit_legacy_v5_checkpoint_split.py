"""Reproducible non-execution legacy v5 account drift diagnoses."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from scripts import audit_legacy_v5_checkpoint_split as diagnostic

REPO = "Dtwosam/Cocomelon"


def _sqlite(path: Path, *, identifier: str, last_ms: int) -> bytes:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE paper_account_state ("
            "singleton_id INTEGER PRIMARY KEY, state_id TEXT,"
            "payload_json TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO paper_account_state VALUES (1,?,?)",
            (
                identifier,
                json.dumps({
                    "starting_cash": "10000",
                    "equity": "10011",
                    "updated_at_ms": last_ms,
                }),
            ),
        )
    return path.read_bytes()


def _input(
    tmp_path: Path,
    *,
    sqlite_id: str = "newer",
    tamper_digest: bool = False,
) -> tuple[Path, dict[str, object], dict[str, object], dict[str, object]]:
    row = {
        "portfolio_shadow_candidate_id": "candidate",
        "record_count": 900,
        "end_ms": 1000,
        "baseline": {
            "total_account_pnl": "1", "realized_net_pnl": "1",
            "closed_trade_count": 46,
        },
        "candidate": {
            "total_account_pnl": "10", "realized_net_pnl": "10",
            "closed_trade_count": 26,
        },
    }
    state = {
        "schema_version": 2,
        "portfolio_shadow_candidate_id": "candidate",
        "record_count": 900, "last_record_available_at_ms": 900,
        "review_ledger_row_count": 1,
        "review_ledger_latest_row_digest": "digest",
        "research_only": True, "paper_only": True,
        "promotion_authority": False, "execution_authority": False,
        "baseline": {"account_state_id": "signed-baseline"},
        "candidate": {"account_state_id": "signed-candidate"},
    }
    state["state_digest"] = diagnostic._signed_digest(state)
    if tamper_digest:
        state["record_count"] = 901
    archive = tmp_path / "legacy.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(
            f"{diagnostic.ROOT}/paired-shadow-state.json",
            json.dumps(state),
        )
        zipped.writestr(
            f"{diagnostic.ROOT}/review-ledger.jsonl", json.dumps(row) + "\n",
        )
        zipped.writestr(
            "loss-context-paired-portfolio-shadow-summary.json",
            json.dumps({
                "checkpoint_published": False,
                "checkpoint_error": "paired shadow durable account state mismatch",
            }),
        )
        for lane in ("baseline", "candidate"):
            zipped.writestr(
                f"{diagnostic.ROOT}/{lane}-execution.sqlite3",
                _sqlite(
                    tmp_path / f"{lane}.sqlite3",
                    identifier=(
                        sqlite_id if sqlite_id == "newer"
                        else f"signed-{lane}"
                    ),
                    last_ms=5000,
                ),
            )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    artifacts = {
        "artifacts": [{
            "name": (
                "continuous-paper-loss-context-paired-shadow-"
                f"{diagnostic.ANCHOR_RUN_ID}-1"
            ),
            "digest": f"sha256:{digest}",
            "expired": False,
        }],
    }
    return archive, {}, {}, artifacts


def _check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    *, sqlite_id: str = "newer", tamper_digest: bool = False,
) -> dict[str, object]:
    monkeypatch.setattr(
        diagnostic, "_source_class",
        lambda **_kw: "completed_expected_upgrade_handoff_worker",
    )
    monkeypatch.setattr(
        diagnostic, "review_ledger_receipt",
        lambda *args, **kwargs: {
            "row_count": 1, "latest_row_digest": "digest",
        },
    )
    archive, run, jobs, artifacts = _input(
        tmp_path, sqlite_id=sqlite_id, tamper_digest=tamper_digest,
    )
    return diagnostic.audit_legacy_v5_split(
        run=run, jobs=jobs, artifacts=artifacts,
        archive_path=archive, repository=REPO,
        run_id=diagnostic.ANCHOR_RUN_ID, attempt=1,
    )


def test_postcheckpoint_sqlite_id_drift_must_never_qualify_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _check(tmp_path, monkeypatch)
    assert result["status"] == "authenticated_legacy_v5_checkpoint_db_split"
    assert result["signed_checkpoint_count"] == 1
    assert result["lanes"]["baseline"]["durable_state_id_matches"] is False
    assert result["lanes"]["candidate"]["durable_state_id_matches"] is False
    assert result["lanes"]["baseline"]["sqlite_is_after_signed_record"] is True
    assert result["lanes"]["candidate"]["sqlite_account_pnl_not_signed"] == "11"
    assert result["lanes"]["candidate"]["signed_total_account_pnl"] == "10"
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
    assert result["forward_profitability_verified"] is False


def test_ids_matching_does_not_imply_positive_net_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _check(tmp_path, monkeypatch, sqlite_id="matched")
    assert result["status"] == "legacy_v5_terminal_ids_match_not_profit_certified"
    assert all(
        value["durable_state_id_matches"]
        for value in result["lanes"].values()
    )
    assert result["forward_profitability_verified"] is False


def test_tampered_signed_checkpoint_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _check(tmp_path, monkeypatch, tamper_digest=True)
    assert result["status"] == "unverified"
    assert "checkpoint digest" in str(result["reasons"])
    assert result["lanes"] is None
    assert result["promotion_authority"] is False


def test_wrong_exact_artifact_identity_or_digest_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostic, "_source_class",
        lambda **_kw: "completed_expected_upgrade_handoff_worker",
    )
    archive, run, jobs, artifacts = _input(tmp_path)
    artifacts["artifacts"][0]["digest"] = "sha256:" + "a" * 64
    result = diagnostic.audit_legacy_v5_split(
        run=run, jobs=jobs, artifacts=artifacts,
        archive_path=archive, repository=REPO,
        run_id=diagnostic.ANCHOR_RUN_ID, attempt=1,
    )
    assert result["status"] == "unverified"
    assert "SHA256 mismatch" in str(result["reasons"])
    artifacts["artifacts"][0]["name"] = "unrelated"
    result = diagnostic.audit_legacy_v5_split(
        run=run, jobs=jobs, artifacts=artifacts,
        archive_path=archive, repository=REPO,
        run_id=diagnostic.ANCHOR_RUN_ID, attempt=1,
    )
    assert "exact unexpired legacy v5 artifact" in str(result["reasons"])


def test_untrusted_run_or_attempt_cannot_qualify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, run, jobs, artifacts = _input(tmp_path)
    monkeypatch.setattr(
        diagnostic, "_source_class",
        lambda **_kw: "completed_non_success_worker",
    )
    result = diagnostic.audit_legacy_v5_split(
        run=run, jobs=jobs, artifacts=artifacts,
        archive_path=archive, repository=REPO,
        run_id=diagnostic.ANCHOR_RUN_ID, attempt=1,
    )
    assert result["status"] == "unverified"
    assert "not independently authenticated" in str(result["reasons"])
    result = diagnostic.audit_legacy_v5_split(
        run=run, jobs=jobs, artifacts=artifacts,
        archive_path=archive, repository=REPO,
        run_id=diagnostic.ANCHOR_RUN_ID, attempt=2,
    )
    assert result["status"] == "unverified"


def test_v5_forensic_workflow_never_has_order_permissions() -> None:
    source = Path(
        ".github/workflows/independent-legacy-v5-checkpoint-split.yml"
    ).read_text()
    assert "permissions:\n  actions: read\n  contents: read" in source
    assert "38281228549" in source
    assert "audit_legacy_v5_checkpoint_split.py" in source
    assert "actions: write" not in source
    assert "issues: write" not in source
    assert "gh workflow run" not in source
    assert "original mainnet feed authentication: FALSE" in source
    assert "promotion / live execution: FALSE / FALSE" in source
