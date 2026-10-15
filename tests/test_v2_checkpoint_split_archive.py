"""Original ZIP split-audit tests never grant restore, execution or profit."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
    FILE_NAME,
    V2SourceGapWitness,
)
from scripts.audit_v2_checkpoint_split_archive import (
    CheckpointArchiveAuditError,
    audit_original_v2_checkpoint_split,
    main,
)


def gap(at_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=at_ms,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="BLUR",
        exchange_time_ms=at_ms,
        event_key=f"gap-{at_ms}",
        payload_json=json.dumps({"reason": "disconnect", "at": at_ms}),
        event_kind="data_gap",
    )


def raw_sqlite(path: Path, state_id: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE paper_account_state ("
            "singleton_id INTEGER PRIMARY KEY, state_id TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO paper_account_state VALUES (1, ?)", (state_id,),
        )
        conn.commit()
    finally:
        conn.close()


def make_zip(
    root: Path, *, uncheckpointed_tail: bool, sqlite_mismatch: bool,
) -> tuple[Path, str]:
    source_root = root / "src"
    source = V2SourceGapWitness(source_root, restoring=False)
    source.append(gap(100), ordinal=2)
    signed = source.signed_receipt(total_processed_records=2)
    state = {
        "record_count": 2,
        "v2_source_gap_event_witness": signed,
        "baseline": {"account_state_id": "signed-baseline"},
        "candidate": {"account_state_id": "signed-candidate"},
    }
    state["state_digest"] = hashlib.sha256(json.dumps(
        state, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()
    if uncheckpointed_tail:
        source.append(gap(200), ordinal=4)
    raw_sqlite(
        root / "baseline.sqlite3",
        "advanced-baseline" if sqlite_mismatch else "signed-baseline",
    )
    raw_sqlite(
        root / "candidate.sqlite3",
        "advanced-candidate" if sqlite_mismatch else "signed-candidate",
    )
    archive = root / "v2.zip"
    base = "both-side-trend-paired-shadow-v2/"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(base + "paired-shadow-state.json", json.dumps(state))
        z.write(source_root / FILE_NAME, base + FILE_NAME)
        z.write(root / "baseline.sqlite3", base + "baseline-execution.sqlite3")
        z.write(root / "candidate.sqlite3", base + "candidate-execution.sqlite3")
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_real_shape_of_three_way_split_is_detected_without_changes(
    tmp_path: Path,
) -> None:
    archive, digest = make_zip(
        tmp_path, uncheckpointed_tail=True, sqlite_mismatch=True,
    )
    original = archive.read_bytes()
    result = audit_original_v2_checkpoint_split(
        archive, expected_zip_sha256=digest,
    )
    assert result["classification"] == "three_way_checkpoint_split"
    assert result["signed_witness_prefix_bytes_sha256_valid"] is True
    assert result["signed_witness_prefix_row_count_and_last_digest_valid"] is True
    assert result["baseline_sqlite_account_id_matches_signed_state"] is False
    assert result["candidate_sqlite_account_id_matches_signed_state"] is False
    witness = result["witness_diagnostic"]
    assert isinstance(witness, dict)
    assert witness["status"] == "uncheckpointed_witness_tail"
    assert witness["first_failed_row_number"] == 2
    assert witness["observed_record_ordinal"] == 4
    assert archive.read_bytes() == original
    for guard in (
        "original_exchange_feed_authenticated",
        "research_restore_authorized",
        "execution_authority",
        "promotion_authority",
        "after_cost_profitability_verified",
        "source_files_modified",
    ):
        assert result[guard] is False


def test_all_local_components_matching_is_still_not_venue_certification(
    tmp_path: Path,
) -> None:
    archive, digest = make_zip(
        tmp_path, uncheckpointed_tail=False, sqlite_mismatch=False,
    )
    report = audit_original_v2_checkpoint_split(
        archive, expected_zip_sha256=digest,
    )
    assert report["classification"] == "locally_consistent_unverified"
    assert report["research_restore_authorized"] is False
    assert report["independent_terminal_account_parity_certified"] is False
    assert report["baseline_sqlite_account_id_matches_signed_state"] is True
    assert report["candidate_sqlite_account_id_matches_signed_state"] is True


def test_wrong_zip_sha_is_rejected_before_extraction(tmp_path: Path) -> None:
    archive, _ = make_zip(
        tmp_path, uncheckpointed_tail=True, sqlite_mismatch=True,
    )
    with pytest.raises(CheckpointArchiveAuditError, match="artifact digest"):
        audit_original_v2_checkpoint_split(
            archive, expected_zip_sha256="f" * 64,
        )


def test_tampered_witness_prefix_is_never_trimmed_or_qualified(
    tmp_path: Path,
) -> None:
    archive, _ = make_zip(
        tmp_path, uncheckpointed_tail=True, sqlite_mismatch=True,
    )
    with zipfile.ZipFile(archive) as existing:
        data = {name: existing.read(name) for name in existing.namelist()}
    source_name = "both-side-trend-paired-shadow-v2/" + FILE_NAME
    data[source_name] = data[source_name].replace(b"disconnect", b"untrusted")
    with zipfile.ZipFile(archive, "w") as z:
        for name, content in data.items():
            z.writestr(name, content)
    fresh_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(CheckpointArchiveAuditError, match="signed witness prefix"):
        audit_original_v2_checkpoint_split(
            archive, expected_zip_sha256=fresh_digest,
        )


def test_cli_can_only_exit_unverified_and_creates_no_sibling_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    archive, digest = make_zip(
        tmp_path, uncheckpointed_tail=True, sqlite_mismatch=True,
    )
    before = sorted(x.name for x in tmp_path.iterdir())
    assert main(["--zip", str(archive), "--expected-zip-sha256", digest]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["classification"] == "three_way_checkpoint_split"
    assert sorted(x.name for x in tmp_path.iterdir()) == before
