"""Offline v2 witness forensics must never repair or qualify signed history."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
    FILE_NAME,
    V2SourceGapWitness,
    V2SourceGapWitnessError,
    read_source_gap_witness,
)
from scripts.diagnose_v2_source_gap_order import diagnose_source_gap_order, main


def _gap(at_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=at_ms,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="BLUR",
        exchange_time_ms=at_ms,
        event_key=f"received-{at_ms}",
        payload_json=json.dumps({"reason": "disconnect", "at": at_ms}),
        event_kind="data_gap",
    )


def _setup(tmp_path: Path, *, first: int = 100, second: int = 200) -> Path:
    witness = V2SourceGapWitness(tmp_path, restoring=False)
    witness.append(_gap(first), ordinal=2)
    witness.append(_gap(second), ordinal=4)
    return tmp_path / FILE_NAME


def _rehash(row: dict[str, object]) -> None:
    unsigned = {key: val for key, val in row.items() if key != "row_digest"}
    row["row_digest"] = hashlib.sha256(json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()


def test_clean_chain_never_claims_signed_or_exchange_certification(
    tmp_path: Path,
) -> None:
    path = _setup(tmp_path)
    original = path.read_bytes()
    finding = diagnose_source_gap_order(path, signed_processed_records=4)
    assert finding["status"] == "self_consistent_unverified"
    assert finding["verified_chain_rows_before_failure"] == 2
    assert finding["original_file_sha256"] == hashlib.sha256(original).hexdigest()
    for denied in (
        "signed_count_independently_authenticated",
        "original_exchange_feed_complete",
        "signed_checkpoint_accepted",
        "profitability_verified",
        "promotion_authority",
        "execution_authority",
        "source_file_modified",
    ):
        assert finding[denied] is False
    assert path.read_bytes() == original


def test_first_checkpoint_overrun_is_localized_with_intact_signed_bytes(
    tmp_path: Path,
) -> None:
    path = _setup(tmp_path)
    original = path.read_bytes()
    with pytest.raises(V2SourceGapWitnessError, match="order"):
        read_source_gap_witness(path, total_processed_records=3)
    finding = diagnose_source_gap_order(path, signed_processed_records=3)
    assert finding["status"] == "uncheckpointed_witness_tail"
    assert finding["reason"] == "ordinal_exceeds_signed_processed_count"
    assert finding["first_failed_row_number"] == 2
    assert finding["observed_record_ordinal"] == 4
    assert finding["verified_chain_rows_before_failure"] == 2
    assert path.read_bytes() == original


def test_original_signed_timestamp_regression_is_not_silently_reordered(
    tmp_path: Path,
) -> None:
    path = _setup(tmp_path, first=200, second=100)
    original = path.read_bytes()
    with pytest.raises(V2SourceGapWitnessError, match="order"):
        read_source_gap_witness(path, total_processed_records=4)
    finding = diagnose_source_gap_order(path, signed_processed_records=4)
    assert finding["status"] == "invalid"
    assert finding["reason"] == "received_timestamp_regression"
    assert finding["first_failed_row_number"] == 2
    assert finding["previous_available_at_ms"] == 200
    assert finding["observed_available_at_ms"] == 100
    assert finding["previous_record_ordinal"] == 2
    assert finding["observed_record_ordinal"] == 4
    assert path.read_bytes() == original


def test_tampered_row_digest_takes_priority_over_spoofed_order_failure(
    tmp_path: Path,
) -> None:
    path = _setup(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["record_ordinal"] = 1
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    original = path.read_bytes()
    finding = diagnose_source_gap_order(path, signed_processed_records=4)
    assert finding["status"] == "invalid"
    assert finding["reason"] == "row_digest_mismatch"
    assert finding["first_failed_row_number"] == 2
    assert finding["verified_chain_rows_before_failure"] == 1
    assert finding["original_file_sha256"] == hashlib.sha256(original).hexdigest()
    assert path.read_bytes() == original


def test_validly_hashed_duplicate_ordinal_is_still_invalid(tmp_path: Path) -> None:
    path = _setup(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["record_ordinal"] = 2
    _rehash(rows[1])
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = diagnose_source_gap_order(path, signed_processed_records=4)
    assert result["reason"] == "ordinal_not_strictly_increasing"
    assert result["status"] == "invalid"
    assert result["first_failed_row_number"] == 2


def test_validly_hashed_broken_previous_link_is_still_invalid(
    tmp_path: Path,
) -> None:
    path = _setup(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["previous_digest"] = "0" * 64
    _rehash(rows[1])
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = diagnose_source_gap_order(path, signed_processed_records=4)
    assert result["reason"] == "previous_digest_mismatch"
    assert result["status"] == "invalid"
    assert result["verified_chain_rows_before_failure"] == 1


def test_truncated_file_does_not_become_a_valid_prefix(tmp_path: Path) -> None:
    path = _setup(tmp_path)
    path.write_bytes(path.read_bytes()[:-1])
    result = diagnose_source_gap_order(path, signed_processed_records=4)
    assert result["reason"] == "truncated_row"
    assert result["status"] == "invalid"
    assert result["original_file_bytes"] == path.stat().st_size


def test_missing_file_and_bad_checkpoint_input_fail_closed(tmp_path: Path) -> None:
    result = diagnose_source_gap_order(
        tmp_path / "missing.jsonl", signed_processed_records=10,
    )
    assert result["status"] == "invalid"
    assert result["reason"] == "witness_file_missing"
    for invalid in (-1, True):
        with pytest.raises(ValueError, match="signed_processed_records"):
            diagnose_source_gap_order(tmp_path / "missing", signed_processed_records=invalid)


def test_cli_emits_no_artifacts_and_never_returns_green_on_unverified_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    path = _setup(tmp_path)
    initial = {p: p.read_bytes() for p in tmp_path.iterdir()}
    assert main([
        "--witness", str(path), "--signed-processed-records", "4",
    ]) == 2
    body = json.loads(capsys.readouterr().out)
    assert body["status"] == "self_consistent_unverified"
    assert body["execution_authority"] is False
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == initial
