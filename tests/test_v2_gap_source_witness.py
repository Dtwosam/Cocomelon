"""Original received v2 DATA_GAP records are append-only, not feed authentication."""

from __future__ import annotations

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


def _gap(at: int = 100, *, source: str = "hyperliquid-ws") -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=at,
        source=source,
        schema_version=1,
        market="BTC",
        exchange_time_ms=at,
        event_key=f"gap-{at}",
        payload_json=json.dumps({
            "reason": "disconnect", "stream": "BTC:book",
            "available_at_ms": at,
        }),
        event_kind="data_gap",
    )


def _normal(at: int = 50) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at,
        source="hyperliquid-ws",
        schema_version=1,
        market="BTC",
        exchange_time_ms=at,
        event_key=f"book-{at}",
        payload_json='{"bids":[],"asks":[]}',
        event_kind="l2_book",
    )


def test_write_once_source_gap_receipt_and_exact_cross_worker_restore(
    tmp_path: Path,
) -> None:
    source = V2SourceGapWitness(tmp_path, restoring=False)
    source.append(_normal(), ordinal=1)
    source.append(_gap(100), ordinal=2)
    source.append(_gap(200), ordinal=4)
    receipt = source.signed_receipt(total_processed_records=5)
    assert receipt["received_gap_record_count"] == 2
    assert receipt["processed_market_record_count"] == 5
    assert receipt["last_gap_record_ordinal"] == 4
    assert receipt["not_a_complete_original_venue_feed"] is True
    assert receipt["original_exchange_gap_provenance_authenticated"] is False
    original = (tmp_path / FILE_NAME).read_bytes()
    restored = V2SourceGapWitness(tmp_path, restoring=True)
    restored.restore(receipt=receipt, total_processed_records=5)
    assert (tmp_path / FILE_NAME).read_bytes() == original
    restored.append(_gap(300), ordinal=7)
    after = restored.signed_receipt(total_processed_records=7)
    assert after["received_gap_record_count"] == 3
    assert after["witness_byte_count"] > receipt["witness_byte_count"]
    assert after["latest_gap_record_digest"] != receipt["latest_gap_record_digest"]


def test_unsealed_existing_or_missing_restored_record_never_repaired(
    tmp_path: Path,
) -> None:
    V2SourceGapWitness(tmp_path, restoring=False)
    with pytest.raises(FileExistsError):
        V2SourceGapWitness(tmp_path, restoring=False)
    (tmp_path / FILE_NAME).unlink()
    with pytest.raises(V2SourceGapWitnessError, match="lack original"):
        V2SourceGapWitness(tmp_path, restoring=True)


@pytest.mark.parametrize("mutation", [
    "change_record", "rewrite_digest", "rewrite_previous", "truncate",
    "append_unsigned", "replace_no_gaps", "duplicate_ordinal",
])
def test_tampered_or_unsigned_gap_history_fails_closed(
    tmp_path: Path, mutation: str,
) -> None:
    source = V2SourceGapWitness(tmp_path, restoring=False)
    source.append(_gap(100), ordinal=2)
    source.append(_gap(200), ordinal=4)
    receipt = source.signed_receipt(total_processed_records=5)
    path = tmp_path / FILE_NAME
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if mutation == "change_record":
        rows[0]["record"]["source"] = "forged"
    elif mutation == "rewrite_digest":
        rows[1]["row_digest"] = "f" * 64
    elif mutation == "rewrite_previous":
        rows[1]["previous_digest"] = None
    elif mutation == "duplicate_ordinal":
        rows[1]["record_ordinal"] = 2
    elif mutation == "truncate":
        path.write_bytes(path.read_bytes()[:-3])
    elif mutation == "append_unsigned":
        path.write_bytes(path.read_bytes() + b"{}\n")
    elif mutation == "replace_no_gaps":
        path.write_bytes(b"")
    if mutation in ("change_record", "rewrite_digest", "rewrite_previous", "duplicate_ordinal"):
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        )
    restored = V2SourceGapWitness(tmp_path, restoring=True)
    with pytest.raises(V2SourceGapWitnessError):
        restored.restore(receipt=receipt, total_processed_records=5)


def test_ledger_cannot_reclassify_normal_market_events_as_gap(
    tmp_path: Path,
) -> None:
    witness = V2SourceGapWitness(tmp_path, restoring=False)
    witness.append(_normal(), ordinal=1)
    receipt = witness.signed_receipt(total_processed_records=1)
    assert receipt["received_gap_record_count"] == 0
    assert (tmp_path / FILE_NAME).read_bytes() == b""


def test_checkpoint_record_count_cannot_fall_behind_original_gap_index(
    tmp_path: Path,
) -> None:
    witness = V2SourceGapWitness(tmp_path, restoring=False)
    witness.append(_gap(), ordinal=4)
    with pytest.raises(V2SourceGapWitnessError, match="order"):
        read_source_gap_witness(
            tmp_path / FILE_NAME, total_processed_records=3,
        )


def test_actor_and_independent_reviewer_both_bind_gap_sequence() -> None:
    base = Path(
        "src/cocomelon/research/loss_context_paired_portfolio_shadow.py"
    ).read_text()
    verifier = Path("scripts/audit_both_side_trend_paired_handoff.py").read_text()
    economic = Path("scripts/audit_fresh_trend_v2_forward_outcome.py").read_text()
    assert "self._v2_gap_witness.append(" in base
    assert "self._v2_gap_witness.restore(" in base
    assert 'payload["v2_source_gap_event_witness"]' in base
    assert "read_source_gap_witness(" in verifier
    assert "state.get(\"v2_source_gap_event_witness\") != source_witness" in verifier
    assert "signed_forward_gaps += 1" in economic
    assert "original_actor_received_forward_market_gap_event" in economic
    assert "original_exchange_gap_provenance_authenticated" not in economic
