"""Restore the ORIGINAL consumed-paper receipt ordering from pinned v3 segments.

Segment paths are partitioned by market and event kind. A canonical replay
sort by timestamp/event kind is not the same as original first-received order,
especially for two observations in the same millisecond. Never manufacture an
ordering from a timestamp tie or silently assign missing receive ordinals.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from cocomelon.domain.replay import ReplayManifest, ReplayRecord
from cocomelon.replay.source import _decode_segment


class OriginalV3ReceiptOrderError(ValueError):
    """Pinned source cannot prove exact original record arrival order."""


def restore_original_v3_received_order(
    root: Path,
    manifest: ReplayManifest,
    validated_records: Sequence[ReplayRecord],
) -> tuple[ReplayRecord, ...]:
    """Reorder the *already fully validated* source by sealed arrival ordinal.

    The caller MUST first validate every segment's SHA-256, row count, safe
    path, manifest identity and full recorder. This method checks all
    manifest rows are uniquely assigned a single 1-based ordinal in the
    original worker stream, and that their source population exactly equals
    the independently validated population. It cannot establish source
    continuity across worker ZIPs or prove venue-event completeness.
    """
    expected_rows = sum(part.row_count for part in manifest.segments)
    if not validated_records or len(validated_records) != expected_rows:
        raise OriginalV3ReceiptOrderError(
            "original receipt order population differs from pinned manifest"
        )
    ordered: list[ReplayRecord | None] = [None] * expected_rows
    for segment in manifest.segments:
        path = root / segment.relative_path
        # The outer pinned-source validator independently rejects symlinks
        # in every directory, and checks the exact original segment SHA.
        try:
            decoded = _decode_segment(path)
        except (OSError, ValueError) as exc:
            raise OriginalV3ReceiptOrderError(
                "cannot decode exact original ordinal segment"
            ) from exc
        if len(decoded) != segment.row_count:
            raise OriginalV3ReceiptOrderError("original ordinal segment row count drift")
        for raw, record in decoded:
            ordinal = raw.get("original_receipt_ordinal")
            if (
                type(ordinal) is not int
                or ordinal < 1
                or ordinal > expected_rows
            ):
                raise OriginalV3ReceiptOrderError(
                    "original received ordinal missing or outside signed population"
                )
            index = ordinal - 1
            if ordered[index] is not None:
                raise OriginalV3ReceiptOrderError(
                    "original received ordinals duplicated"
                )
            ordered[index] = record
    if any(record is None for record in ordered):
        raise OriginalV3ReceiptOrderError("original received ordinals have gaps")
    actual = tuple(record for record in ordered if record is not None)
    # SourceSegment and original JSONL are exact SHA-pinned already. Check
    # that no row was changed or substituted when reconstructing the global
    # arrival stream from disjoint partition segments. Include canonical
    # payload for same-key ordering ties.
    def identity(
        row: ReplayRecord,
    ) -> tuple[int, str, str, int, str, int, str, str, str]:
        return (
            row.available_at_ms, row.record_kind.value, row.source,
            row.schema_version, row.market or "",
            row.exchange_time_ms if row.exchange_time_ms is not None else -1,
            row.event_key or "", row.event_kind or "", row.payload_json,
        )

    if sorted(actual, key=identity) != sorted(validated_records, key=identity):
        raise OriginalV3ReceiptOrderError(
            "original ordinal stream and independent pinned replay differ"
        )
    last_at = -1
    for row in actual:
        if row.available_at_ms < last_at:
            raise OriginalV3ReceiptOrderError(
                "original PAPER stream has regressing first-received timestamp"
            )
        last_at = row.available_at_ms
    return actual
