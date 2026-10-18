"""Lossless gzipped v3 source writer cannot manufacture original market evidence."""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    ReplayRecord,
    SourceRecordKind,
    SourceSegment,
)
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.fresh_long_trend_forward_pair import FORWARD_NOT_BEFORE_MS
from cocomelon.research.fresh_long_trend_receipt_order import (
    restore_original_v3_received_order,
)
from cocomelon.research.original_paper_v3_capture import (
    COMPRESSED_JOURNAL_FORMAT,
    COMPRESSED_RECORD_FILE,
    RECORD_FILE,
    OriginalPaperMicrostructureCapture,
)
from cocomelon.research.prospective_short_breakout_pinned_source import (
    PinnedShortRankReplaySource,
)
from scripts.seal_original_paper_v3_source import (
    OriginalV3CaptureSealError,
    seal_original_paper_v3_source,
)

RUN = "39122220001"
ATTEMPT = "1"
HEAD = "a" * 40


def _book(time_ms: int, key: str) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=time_ms,
        source="hyperliquid-original-source",
        schema_version=1,
        market="TEST",
        exchange_time_ms=time_ms - 1,
        event_key=key,
        event_kind="l2_book",
        payload_json=json.dumps({
            "bids": [{"px": "1.001", "sz": "100", "n": 1}],
            "asks": [{"px": "1.002", "sz": "100", "n": 1}],
        }),
    )


def _rows() -> tuple[ReplayRecord, ...]:
    t = FORWARD_NOT_BEFORE_MS + 1
    # Multiple 256-row fsync batches, and deliberate same-ms received
    # order opposite to lexicographic keys.
    return (
        _book(FORWARD_NOT_BEFORE_MS - 1, "warmup"),
        _book(t, "z-received-before-a"),
        _book(t, "a-received-second"),
        *tuple(_book(t + k, f"book-{k:05d}") for k in range(3, 620)),
    )


async def _capture(root: Path, rows: tuple[ReplayRecord, ...]) -> dict[str, object]:
    recorder = OriginalPaperMicrostructureCapture(
        root,
        run_id=RUN,
        run_attempt=ATTEMPT,
        head_sha=HEAD,
        selected_markets=("TEST",),
        first_observed_ms=FORWARD_NOT_BEFORE_MS - 50_000,
        replay_config=BaselineReplayConfig(),
        compressed_journal=True,
    )
    for row in rows:
        recorder.offer(row)
    return await recorder.close()


def _seal(root: Path) -> dict[str, object]:
    return seal_original_paper_v3_source(
        capture_root=root / "original",
        upload_root=root / "upload",
        run_id=RUN, run_attempt=ATTEMPT, head_sha=HEAD,
    )


def _manifest(upload: Path) -> ReplayManifest:
    payload = json.loads((upload / "replay-manifest.json").read_text())["manifest"]
    return ReplayManifest(
        **{
            **payload,
            "evidence_class": EvidenceClass(payload["evidence_class"]),
            "segments": tuple(SourceSegment(**r) for r in payload["segments"]),
            "gap_refs": tuple(payload["gap_refs"]),
        }
    )


def test_lossless_gzip_member_stream_roundtrips_every_original_row(
    tmp_path: Path,
) -> None:
    rows = _rows()
    status = asyncio.run(_capture(tmp_path / "original", rows))
    path = tmp_path / "original" / COMPRESSED_RECORD_FILE
    assert status["complete"] is True
    assert status["written_count"] == status["offered_count"] == len(rows)
    assert status["dropped_count"] == 0
    assert status["original_received_journal_format"] == COMPRESSED_JOURNAL_FORMAT
    assert path.is_file()
    assert not (tmp_path / "original" / RECORD_FILE).exists()
    physical = path.read_bytes()
    with gzip.open(path, "rb") as stream:
        decoded = stream.read()
    assert status["written_source_journal_bytes"] == len(physical)
    assert status["uncompressed_original_journal_bytes"] == len(decoded)
    assert len(decoded.splitlines()) == len(rows)
    assert len(physical) < len(decoded)
    assert status["original_received_journal_sha256"] == (
        hashlib.sha256(decoded).hexdigest()
    )
    assert [
        json.loads(line)["event_key"] for line in decoded.splitlines()
    ] == [row.event_key for row in rows]
    receipt = _seal(tmp_path)
    assert receipt["original_received_record_count"] == len(rows)
    source = tmp_path / "upload" / "microstructure"
    manifest = _manifest(tmp_path / "upload")
    canonical = PinnedShortRankReplaySource(
        root=source, manifest=manifest,
        expected_manifest_id=manifest.manifest_id,
    ).verified_records(forward_not_before_ms=FORWARD_NOT_BEFORE_MS)
    original = restore_original_v3_received_order(source, manifest, canonical)
    assert [(row.event_key, row.available_at_ms) for row in original] == [
        (row.event_key, row.available_at_ms) for row in rows
    ]
    assert receipt["execution_authority"] is False
    assert receipt["72h_forward_profitability_certified"] is False
    assert receipt["promotion_authority"] is False


@pytest.mark.parametrize("damage", [
    "truncated_member", "crc_flip", "rogue_plain_copy",
    "changed_terminal_stored_count", "changed_terminal_raw_count",
    "changed_terminal_format", "changed_terminal_digest",
])
def test_tampered_compressed_original_never_seals(
    tmp_path: Path, damage: str,
) -> None:
    asyncio.run(_capture(tmp_path / "original", _rows()))
    root = tmp_path / "original"
    journal = root / COMPRESSED_RECORD_FILE
    terminal = root / "original-capture-terminal.json"
    if damage == "truncated_member":
        journal.write_bytes(journal.read_bytes()[:-7])
    elif damage == "crc_flip":
        raw = bytearray(journal.read_bytes())
        raw[-5] ^= 0xFF
        journal.write_bytes(raw)
    elif damage == "rogue_plain_copy":
        (root / RECORD_FILE).write_text("unsigned second encoding", encoding="utf-8")
    else:
        status = json.loads(terminal.read_text())
        if damage == "changed_terminal_stored_count":
            status["written_source_journal_bytes"] += 1
        elif damage == "changed_terminal_raw_count":
            status["uncompressed_original_journal_bytes"] += 1
        elif damage == "changed_terminal_format":
            status["original_received_journal_format"] = "plain-jsonl-v1"
        elif damage == "changed_terminal_digest":
            status["original_received_journal_sha256"] = "f" * 64
        terminal.write_text(json.dumps(status, sort_keys=True))
    with pytest.raises((OriginalV3CaptureSealError, EOFError, OSError)):
        _seal(tmp_path)
    assert not (tmp_path / "upload").exists()


def test_genuine_backward_received_clock_still_invalid_under_gzip(
    tmp_path: Path,
) -> None:
    t = FORWARD_NOT_BEFORE_MS
    status = asyncio.run(_capture(
        tmp_path / "original", (
            _book(t, "first"),
            _book(t + 10, "next"),
            _book(t + 9, "regressed-original"),
        )
    ))
    assert status["failure"] == "original_received_clock_regression"
    assert status["complete"] is False
    assert status["dropped_count"] >= 1
    assert status["original_received_clock_regressions"] >= 1
    assert status["promotion_authority"] is False
    with pytest.raises(OriginalV3CaptureSealError, match="lost rows"):
        _seal(tmp_path)


def test_gzip_stored_budget_failure_cannot_launder_lost_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cocomelon.research.original_paper_v3_capture as capture_module

    monkeypatch.setattr(capture_module, "MAX_SOURCE_BYTES", 1)
    status = asyncio.run(_capture(
        tmp_path / "original", (_book(FORWARD_NOT_BEFORE_MS, "one"),)
    ))
    assert status["complete"] is False
    assert status["failure"] == "original_capture_source_byte_budget_exceeded"
    assert status["dropped_count"] == 1
    assert status["written_count"] == 0
    assert status["offered_count"] == 1
    with pytest.raises(OriginalV3CaptureSealError):
        _seal(tmp_path)
