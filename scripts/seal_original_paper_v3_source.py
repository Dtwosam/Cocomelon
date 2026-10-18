"""Seal actual PAPER-consumed received records as an original v3 research ZIP source.

Run only AFTER the paper worker exits and its successor has been queued.
The GitHub upload action supplies the outer original ZIP/archive digest.
Never manufacture fills, rank observations or missing market data.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    ReplayRecord,
    SourceRecordKind,
)
from cocomelon.recorder import _encode_json_line
from cocomelon.replay.source import validate_recording
from cocomelon.research.fresh_long_trend_forward_pair import (
    FORWARD_NOT_BEFORE_MS,
)
from cocomelon.research.original_paper_v3_capture import (
    COMPRESSED_JOURNAL_FORMAT,
    COMPRESSED_RECORD_FILE,
    MAX_DECODED_SOURCE_BYTES,
    MAX_SOURCE_BYTES,
    MAX_SOURCE_ROWS,
    PLAIN_JOURNAL_FORMAT,
    RECORD_FILE,
    TERMINAL_FILE,
)

MAX_SEGMENT_ROWS = 30_000
MAX_SEGMENT_BYTES = 16 * 1024 * 1024


class OriginalV3CaptureSealError(RuntimeError):
    """Recorder did not preserve an eligible original entire-worker stream."""


def _source_row(raw: object) -> ReplayRecord:
    if not isinstance(raw, dict) or set(raw) != {
        "record_kind", "available_at_ms", "source", "schema_version",
        "market", "exchange_time_ms", "event_key", "payload_json",
        "event_kind",
    }:
        raise OriginalV3CaptureSealError("original received row schema invalid")
    if (
        type(raw["available_at_ms"]) is not int
        or type(raw["schema_version"]) is not int
        or type(raw["exchange_time_ms"]) not in (int, type(None))
    ):
        raise OriginalV3CaptureSealError("original received row numeric type invalid")
    try:
        return ReplayRecord(
            record_kind=SourceRecordKind(raw["record_kind"]),
            available_at_ms=raw["available_at_ms"],
            source=raw["source"],
            schema_version=raw["schema_version"],
            market=raw["market"],
            exchange_time_ms=raw["exchange_time_ms"],
            event_key=raw["event_key"],
            event_kind=raw["event_kind"],
            payload_json=raw["payload_json"],
        )
    except (TypeError, ValueError) as exc:
        raise OriginalV3CaptureSealError("original received row malformed") from exc


def _format_receive(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _recorder_row(record: ReplayRecord) -> tuple[str, dict[str, object]]:
    if record.record_kind is SourceRecordKind.NORMALIZED_EVENT:
        if record.market is None or record.event_kind is None or record.event_key is None:
            raise OriginalV3CaptureSealError("original normalized market identity missing")
        observed_date = _format_receive(record.available_at_ms)[:10]
        path = (
            "events/" + observed_date + "/" + record.event_kind + "/"
            + quote(record.market, safe="-_.")
        )
        payload = json.loads(record.payload_json)
        if not isinstance(payload, dict):
            raise OriginalV3CaptureSealError("original normalized payload not object")
        return path, {
            "record_type": "normalized_event",
            "schema_version": record.schema_version,
            "source": record.source,
            "kind": record.event_kind,
            "market": record.market,
            "exchange_time_ms": record.exchange_time_ms,
            "receive_time": _format_receive(record.available_at_ms),
            "event_key": record.event_key,
            "payload": payload,
        }
    if record.record_kind is SourceRecordKind.DATA_GAP:
        gap = json.loads(record.payload_json)
        if not isinstance(gap, dict):
            raise OriginalV3CaptureSealError("original data gap not object")
        started = gap.get("started_ms")
        ended = gap.get("ended_ms")
        if type(started) is not int or (
            ended is not None and type(ended) is not int
        ):
            raise OriginalV3CaptureSealError("original gap timeline malformed")
        date = _format_receive(started)[:10]
        return "gaps/" + date, {
            "record_type": "data_gap",
            "schema_version": record.schema_version,
            "source": record.source,
            "started_ms": started,
            "ended_ms": ended,
            "stream_id": gap.get("stream_id"),
            "reason": gap.get("reason"),
        }
    raise OriginalV3CaptureSealError("unsupported original source type")


def seal_original_paper_v3_source(
    *,
    capture_root: Path,
    upload_root: Path,
    run_id: str,
    run_attempt: str,
    head_sha: str,
) -> dict[str, object]:
    if upload_root.exists() or upload_root.is_symlink():
        raise OriginalV3CaptureSealError("new source upload root already exists")
    terminal_path = capture_root / TERMINAL_FILE
    if (
        capture_root.is_symlink() or not terminal_path.is_file()
    ):
        raise OriginalV3CaptureSealError("no CLOSED original worker capture")
    try:
        terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OriginalV3CaptureSealError("original terminal receipt unreadable") from exc
    if (
        not isinstance(terminal, dict)
        or terminal.get("run_id") != run_id
        or terminal.get("run_attempt") != run_attempt
        or terminal.get("head_sha") != head_sha
        or terminal.get("complete") is not True
        or terminal.get("failure") is not None
        or terminal.get("dropped_count") != 0
        or type(terminal.get("written_count")) is not int
        or terminal["written_count"] < 1
        or terminal.get("offered_count") != terminal["written_count"]
        or terminal["written_count"] > MAX_SOURCE_ROWS
        or not isinstance(terminal.get("selected_markets_at_worker_start"), list)
        or not isinstance(terminal.get("original_received_journal_sha256"), str)
        or len(terminal["original_received_journal_sha256"]) != 64
        or any(
            char not in "0123456789abcdef"
            for char in terminal["original_received_journal_sha256"]
        )
    ):
        raise OriginalV3CaptureSealError("original capture lost rows or changed identity")
    format_name = terminal.get(
        "original_received_journal_format", PLAIN_JOURNAL_FORMAT
    )
    if format_name not in (PLAIN_JOURNAL_FORMAT, COMPRESSED_JOURNAL_FORMAT):
        raise OriginalV3CaptureSealError("unknown original journal representation")
    compressed = format_name == COMPRESSED_JOURNAL_FORMAT
    stream_path = capture_root / (
        COMPRESSED_RECORD_FILE if compressed else RECORD_FILE
    )
    unexpected = capture_root / (
        RECORD_FILE if compressed else COMPRESSED_RECORD_FILE
    )
    if (
        not stream_path.is_file() or stream_path.is_symlink()
        or unexpected.exists() or unexpected.is_symlink()
    ):
        raise OriginalV3CaptureSealError(
            "original captured source journal missing or ambiguous"
        )
    physical_bytes = stream_path.stat().st_size
    if (
        physical_bytes > MAX_SOURCE_BYTES
        or (
            compressed
            and physical_bytes != terminal.get("written_source_journal_bytes")
        )
    ):
        raise OriginalV3CaptureSealError(
            "physical original journal length differs from signed receipt"
        )
    predecessor_id = terminal.get("declared_predecessor_run_id")
    predecessor_attempt = terminal.get("declared_predecessor_run_attempt")
    if (
        (predecessor_id is None) != (predecessor_attempt is None)
        or (
            predecessor_id is not None
            and (
                type(predecessor_id) is not str
                or not predecessor_id.isdecimal()
                or int(predecessor_id) <= 0
                or predecessor_id == run_id
                or type(predecessor_attempt) is not str
                or not predecessor_attempt.isdecimal()
                or int(predecessor_attempt) <= 0
            )
        )
        or terminal.get(
            "predecessor_state_restore_independently_authenticated"
        ) is not False
    ):
        raise OriginalV3CaptureSealError(
            "original declared paper predecessor identity malformed"
        )
    selected = terminal["selected_markets_at_worker_start"]
    if (
        not selected or not all(isinstance(m, str) and m for m in selected)
        or selected != sorted(set(selected))
    ):
        raise OriginalV3CaptureSealError("original selected market cohort invalid")
    identity_names = (
        "original_effective_replay_config_digest",
        "original_effective_execution_config_version",
        "original_effective_fee_schedule_id",
        "original_effective_feature_version",
        "original_effective_strategy_version",
        "original_effective_risk_version",
        "original_effective_replay_engine_version",
    )
    if (
        not all(
            isinstance(terminal.get(field), str) and terminal[field]
            for field in identity_names
        )
        or len(terminal["original_effective_replay_config_digest"]) != 64
        or any(
            c not in "0123456789abcdef"
            for c in terminal["original_effective_replay_config_digest"]
        )
    ):
        raise OriginalV3CaptureSealError(
            "original effective PAPER replay/fee identity unavailable"
        )
    original_rows = 0
    first: int | None = None
    last: int | None = None
    forward_l2: set[str] = set()
    actual_markets: set[str] = set()
    gap_refs: list[str] = []
    source_bytes = 0
    original_journal_sha256 = hashlib.sha256()
    # Avoid partial runnable artifacts: staging occurs in a transient
    # directory and is exposed only after validation has completed.
    staging = upload_root.with_name(upload_root.name + ".unverified")
    if staging.exists() or staging.is_symlink():
        raise OriginalV3CaptureSealError("prior unverified source root exists")
    src = staging / "microstructure"
    src.mkdir(parents=True, exist_ok=False)
    per_partition: dict[str, tuple[int, int, int]] = {}
    try:
        # gzip.open handles concatenated independently fsynced gzip members.
        # Decode to the original exact newline-delimited canonical row bytes,
        # then verify the writer's UNCOMPRESSED ordered SHA256.
        with (
            gzip.open(stream_path, "rb")
            if compressed else stream_path.open("rb")
        ) as original:
            for original_line in original:
                if not original_line.endswith(b"\n"):
                    raise OriginalV3CaptureSealError("torn original received row")
                source_bytes += len(original_line)
                original_journal_sha256.update(original_line)
                source_limit = (
                    MAX_DECODED_SOURCE_BYTES if compressed else MAX_SOURCE_BYTES
                )
                if source_bytes > source_limit:
                    raise OriginalV3CaptureSealError(
                        "original decoded source exceeded recorded safety bound"
                    )
                try:
                    row = _source_row(json.loads(original_line))
                except (UnicodeError, ValueError, TypeError) as exc:
                    raise OriginalV3CaptureSealError(
                        "cannot decode original captured record"
                    ) from exc
                original_rows += 1
                if original_rows > MAX_SOURCE_ROWS:
                    raise OriginalV3CaptureSealError("record count exceeds cap")
                if last is not None and row.available_at_ms < last:
                    raise OriginalV3CaptureSealError(
                        "original consumed source receipts out of order"
                    )
                if first is None:
                    first = row.available_at_ms
                last = row.available_at_ms
                if (
                    row.record_kind is SourceRecordKind.NORMALIZED_EVENT
                    and row.market is not None
                ):
                    actual_markets.add(row.market)
                    if (
                        row.event_kind == "l2_book"
                        and row.available_at_ms >= FORWARD_NOT_BEFORE_MS
                    ):
                        forward_l2.add(row.market)
                if row.record_kind is SourceRecordKind.DATA_GAP:
                    gap_refs.append(row.event_key or row.payload_json)
                partition, encoded = _recorder_row(row)
                # These globally consecutive ordinals are assigned while
                # reading the CLOSED original worker journal in receipt order.
                # Partitioning by market/event type otherwise loses ordering
                # when two actual observations share a receive millisecond.
                encoded["original_receipt_ordinal"] = original_rows
                payload = _encode_json_line(encoded)
                n, count, length = per_partition.get(partition, (1, 0, 0))
                if (
                    count >= MAX_SEGMENT_ROWS
                    or (count > 0 and length + len(payload) > MAX_SEGMENT_BYTES)
                ):
                    n, count, length = n + 1, 0, 0
                target = src / partition / f"segment-{n:06d}.jsonl"
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("ab") as output:
                    output.write(payload)
                per_partition[partition] = (n, count + 1, length + len(payload))
        if (
            first is None or last is None
            or original_rows != terminal["written_count"]
            or (
                source_bytes
                != terminal.get(
                    "uncompressed_original_journal_bytes",
                    physical_bytes if not compressed else None,
                )
            )
            or last != terminal.get("last_written_available_at_ms")
        ):
            raise OriginalV3CaptureSealError(
                "original capture terminal count/end timestamp mismatch"
            )
        if (
            original_journal_sha256.hexdigest()
            != terminal["original_received_journal_sha256"]
        ):
            raise OriginalV3CaptureSealError(
                "original PAPER received journal differs from writer SHA256"
            )
        if last < FORWARD_NOT_BEFORE_MS or not forward_l2:
            raise OriginalV3CaptureSealError(
                "post-embargo genuine original L2 has not arrived"
            )
        if not forward_l2.issubset(set(selected)):
            raise OriginalV3CaptureSealError("original L2 escaped startup cohort")
        segments = validate_recording(src)
        # The manifest MUST name the effective PAPER engine/risk/fee contract
        # used by the actual source worker, never reconstructed defaults.
        # Its config_digest is the original BaselineReplayConfig digest,
        # independently checked again against the replay caller's config.
        manifest = ReplayManifest(
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            start_ms=first,
            end_ms=last,
            segments=segments,
            gap_refs=tuple(gap_refs),
            code_revision=head_sha,
            config_digest=terminal["original_effective_replay_config_digest"],
            feature_version=terminal["original_effective_feature_version"],
            strategy_version=terminal["original_effective_strategy_version"],
            risk_version=terminal["original_effective_risk_version"],
            execution_config_version=terminal[
                "original_effective_execution_config_version"
            ],
            fee_schedule_id=terminal["original_effective_fee_schedule_id"],
            replay_engine_version=terminal[
                "original_effective_replay_engine_version"
            ],
            dataset_manifest_id=None,
        )
        (staging / "replay-manifest.json").write_text(
            json.dumps({
                "manifest_id": manifest.manifest_id,
                "manifest": asdict(manifest),
            }, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
            encoding="utf-8",
        )
        # Declared predecessor is an unverified origin hint, not an
        # independent proof that GitHub restored the preceding account.
        handoff = {
            "schema": "v3-original-paper-source-worker-link-v1",
            "worker_run_id": run_id,
            "worker_run_attempt": run_attempt,
            "worker_head_sha": head_sha,
            "declared_predecessor_run_id": predecessor_id,
            "declared_predecessor_run_attempt": predecessor_attempt,
            "original_journal_sha256": terminal[
                "original_received_journal_sha256"
            ],
            "original_record_count": original_rows,
            "original_first_available_at_ms": first,
            "original_last_available_at_ms": last,
            "original_selected_markets_at_worker_start": selected,
            "original_resume_chain_independently_verified": False,
            "original_exchange_feed_continuity_verified": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }
        (staging / "source-handoff-receipt.json").write_text(
            json.dumps(
                handoff, sort_keys=True, separators=(",", ":"),
                allow_nan=False,
            ) + "\n",
            encoding="utf-8",
        )
        # Reconciled original rows and manifest segments, still NOT venue
        # authenticity. The original archive SHA is assigned by GitHub on
        # upload and must be fetched separately before any replay.
        receipt = {
            "schema": "original-v3-worker-source-seal-v1",
            "source_run_id": run_id,
            "source_run_attempt": run_attempt,
            "source_head_sha": head_sha,
            "manifest_id": manifest.manifest_id,
            "original_received_record_count": original_rows,
            "original_original_writer_journal_sha256": (
                original_journal_sha256.hexdigest()
            ),
            "declared_predecessor_run_id": predecessor_id,
            "declared_predecessor_run_attempt": predecessor_attempt,
            "original_resume_chain_independently_verified": False,
            "original_receipt_ordinals_contiguous_in_original_journal": True,
            "original_receipt_ordinal_first": 1,
            "original_receipt_ordinal_last": original_rows,
            "original_received_gap_count": len(gap_refs),
            "original_source_segments": len(segments),
            "original_capture_market_count": len(actual_markets),
            "original_post_embargo_l2_market_count": len(forward_l2),
            "original_cohort_at_worker_start": selected,
            "original_effective_replay_config_digest": manifest.config_digest,
            "original_effective_execution_config_version": (
                manifest.execution_config_version
            ),
            "original_effective_fee_schedule_id": manifest.fee_schedule_id,
            "original_continuity_across_workers_certified": False,
            "venue_original_event_completeness_certified": False,
            "72h_forward_profitability_certified": False,
            "execution_authority": False,
            "promotion_authority": False,
        }
        # Publish a separate diagnostic to the runner, outside the original
        # GH artifact ZIP so it can't alter the pinned member set.
        staging.replace(upload_root)
        return receipt
    except Exception:
        # A failed source can NEVER leak as the expected original ZIP.
        # Retain the unpublished .unverified evidence for forensic debugging.
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", required=True, type=Path)
    parser.add_argument("--upload-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = seal_original_paper_v3_source(
            capture_root=args.capture_root,
            upload_root=args.upload_root,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            head_sha=args.head_sha,
        )
    except (OSError, ValueError, OriginalV3CaptureSealError) as exc:
        print(json.dumps({
            "ready": False, "reason": f"{type(exc).__name__}: {exc}",
            "promotion_authority": False, "execution_authority": False,
        }, sort_keys=True))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
