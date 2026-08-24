from __future__ import annotations

from collections.abc import Iterable

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind

KIND_PRIORITY: dict[str, int] = {
    "data_gap": 0,
    "market_snapshot": 5,
    "funding_rate": 6,
    "all_mids": 10,
    "active_asset_ctx": 20,
    "candle": 30,
    "l2_book": 40,
    "trade": 50,
}


def _kind_key(record: ReplayRecord) -> str:
    if record.record_kind is SourceRecordKind.DATA_GAP:
        return "data_gap"
    if record.event_kind is None:
        raise ValueError("normalized replay record is missing event_kind")
    return record.event_kind


def canonical_order_key(record: ReplayRecord) -> tuple[int, int, str, str]:
    kind = _kind_key(record)
    try:
        priority = KIND_PRIORITY[kind]
    except KeyError as exc:
        raise ValueError(f"unsupported replay record kind: {kind}") from exc
    return (
        record.available_at_ms,
        priority,
        record.market or "",
        record.event_key or record.payload_json,
    )


def canonical_record_order(records: Iterable[ReplayRecord]) -> tuple[ReplayRecord, ...]:
    return tuple(sorted(records, key=canonical_order_key))


class ReplayClock:
    def __init__(self) -> None:
        self._now_ms: int | None = None

    @property
    def now_ms(self) -> int | None:
        return self._now_ms

    def advance(self, record: ReplayRecord) -> int:
        next_ms = record.available_at_ms
        if self._now_ms is not None and next_ms < self._now_ms:
            raise ValueError("replay clock cannot regress")
        self._now_ms = next_ms
        return next_ms
