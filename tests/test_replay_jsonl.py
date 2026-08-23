import json
from pathlib import Path

import pytest

from cocomelon.domain.replay import EvidenceClass
from cocomelon.replay.jsonl import ReplayValidationError, validate_jsonl_segment


def write_lines(path: Path, rows: list[dict[str, object]], *, final_newline: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows)
    if final_newline:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def normalized_event(
    *,
    kind: str = "trade",
    market: str = "SOL",
    exchange_time_ms: int | None = 1_000,
    receive_time: str = "2026-08-23T00:00:05Z",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "record_type": "normalized_event",
        "schema_version": 1,
        "source": "hyperliquid-mainnet-ws",
        "kind": kind,
        "market": market,
        "exchange_time_ms": exchange_time_ms,
        "receive_time": receive_time,
        "event_key": f"{kind}:{market}:1",
        "payload": payload or {"price": "100", "size": "1"},
    }


def test_validated_event_preserves_provenance_and_receive_time_controls_availability(
    tmp_path: Path,
) -> None:
    root = tmp_path / "recordings"
    path = root / "events/2026-08-23/trade/SOL/segment-000002.jsonl"
    write_lines(path, [normalized_event(exchange_time_ms=1_000)])

    segment = validate_jsonl_segment(
        path,
        root=root,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    )

    assert segment.input_file.relative_path == (
        "events/2026-08-23/trade/SOL/segment-000002.jsonl"
    )
    assert segment.input_file.size_bytes == path.stat().st_size
    assert len(segment.input_file.sha256) == 64
    assert len(segment.rows) == 1
    row = segment.rows[0]
    assert row.receive_time_ms == 1_777_075_205_000
    assert row.exchange_time_ms == 1_000
    assert row.coordinate.segment == 2
    assert row.coordinate.line_number == 1
    assert row.market is not None and row.market.canonical == "SOL"
    assert row.event_kind == "trade"
    assert row.event_key == "trade:SOL:1"
    assert row.payload_json == '{"price":"100","size":"1"}'


def test_hip3_market_is_reconstructed_without_losing_namespace(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    path = root / "events/2026-08-23/l2_book/xyz%3ANVDA/segment-000001.jsonl"
    write_lines(path, [normalized_event(kind="l2_book", market="xyz:NVDA")])

    row = validate_jsonl_segment(
        path,
        root=root,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    ).rows[0]

    assert row.market is not None and row.market.canonical == "xyz:NVDA"


def test_gap_record_uses_started_time_as_operational_availability(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    path = root / "gaps/2026-08-23/segment-000001.jsonl"
    write_lines(
        path,
        [
            {
                "record_type": "data_gap",
                "schema_version": 1,
                "source": "hyperliquid-mainnet-ws",
                "stream_id": "trades:SOL",
                "started_ms": 5_000,
                "ended_ms": 7_000,
                "reason": "disconnect",
            }
        ],
    )

    row = validate_jsonl_segment(
        path,
        root=root,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    ).rows[0]

    assert row.record_type == "data_gap"
    assert row.receive_time_ms == 5_000
    assert row.exchange_time_ms is None
    assert row.event_kind is None


def test_truncated_final_line_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    path = root / "events/2026-08-23/trade/SOL/segment-000001.jsonl"
    write_lines(path, [normalized_event()], final_newline=False)

    with pytest.raises(ReplayValidationError, match="final newline"):
        validate_jsonl_segment(path, root=root, evidence_class=EvidenceClass.MICROSTRUCTURE)


def test_invalid_json_and_nonstandard_nan_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    bad_json = root / "events/a/segment-000001.jsonl"
    bad_json.parent.mkdir(parents=True, exist_ok=True)
    bad_json.write_bytes(b'{"record_type":\n')

    with pytest.raises(ReplayValidationError, match="invalid JSON"):
        validate_jsonl_segment(bad_json, root=root, evidence_class=EvidenceClass.CANDLE_CONTEXT)

    nan_path = root / "events/b/segment-000001.jsonl"
    row = normalized_event(payload={"price": float("nan")})
    nan_path.parent.mkdir(parents=True, exist_ok=True)
    nan_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ReplayValidationError, match="non-standard JSON constant"):
        validate_jsonl_segment(nan_path, root=root, evidence_class=EvidenceClass.MICROSTRUCTURE)


def test_unsupported_schema_and_missing_provenance_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    schema_path = root / "events/a/segment-000001.jsonl"
    row = normalized_event()
    row["schema_version"] = 2
    write_lines(schema_path, [row])

    with pytest.raises(ReplayValidationError, match="schema_version"):
        validate_jsonl_segment(
            schema_path,
            root=root,
            evidence_class=EvidenceClass.MICROSTRUCTURE,
        )

    missing_path = root / "events/b/segment-000001.jsonl"
    missing = normalized_event()
    del missing["source"]
    write_lines(missing_path, [missing])

    with pytest.raises(ReplayValidationError, match="source"):
        validate_jsonl_segment(
            missing_path,
            root=root,
            evidence_class=EvidenceClass.MICROSTRUCTURE,
        )


def test_non_jsonl_and_root_escape_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    wrong_suffix = root / "events/a/segment-000001.parquet"
    write_lines(wrong_suffix, [normalized_event()])

    with pytest.raises(ReplayValidationError, match=".jsonl"):
        validate_jsonl_segment(
            wrong_suffix,
            root=root,
            evidence_class=EvidenceClass.MICROSTRUCTURE,
        )

    outside = tmp_path / "segment-000001.jsonl"
    write_lines(outside, [normalized_event()])

    with pytest.raises(ReplayValidationError, match="inside root"):
        validate_jsonl_segment(outside, root=root, evidence_class=EvidenceClass.MICROSTRUCTURE)


def test_segment_filename_must_carry_deterministic_sequence_number(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    path = root / "events/a/not-a-segment.jsonl"
    write_lines(path, [normalized_event()])

    with pytest.raises(ReplayValidationError, match="segment"):
        validate_jsonl_segment(path, root=root, evidence_class=EvidenceClass.MICROSTRUCTURE)
