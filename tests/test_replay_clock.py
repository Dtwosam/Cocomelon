import pytest

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.replay.clock import KIND_PRIORITY, ReplayClock, canonical_record_order


def record(
    *,
    available_at_ms: int,
    event_kind: str | None,
    market: str = "SOL",
    event_key: str = "event-1",
    exchange_time_ms: int | None = None,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=(
            SourceRecordKind.DATA_GAP
            if event_kind is None
            else SourceRecordKind.NORMALIZED_EVENT
        ),
        available_at_ms=available_at_ms,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market=None if event_kind is None else market,
        exchange_time_ms=exchange_time_ms,
        event_key=event_key,
        payload_json="{}",
        event_kind=event_kind,
    )


def test_receive_time_not_exchange_time_controls_ws_availability() -> None:
    item = record(
        available_at_ms=2_000,
        event_kind="l2_book",
        exchange_time_ms=1_000,
    )

    ordered = canonical_record_order((item,))

    assert ordered[0].available_at_ms == 2_000


def test_canonical_order_uses_explicit_kind_priority_and_stable_ties() -> None:
    rows = (
        record(available_at_ms=1_000, event_kind="trade", event_key="z"),
        record(available_at_ms=1_000, event_kind="l2_book", event_key="b"),
        record(available_at_ms=1_000, event_kind=None, event_key="gap"),
        record(available_at_ms=1_000, event_kind="l2_book", event_key="a"),
    )

    ordered = canonical_record_order(rows)

    assert [item.event_key for item in ordered] == ["gap", "a", "b", "z"]
    assert KIND_PRIORITY["data_gap"] < KIND_PRIORITY["l2_book"] < KIND_PRIORITY["trade"]


def test_canonical_order_does_not_depend_on_input_enumeration() -> None:
    first = record(available_at_ms=1_000, event_kind="candle", market="BTC", event_key="a")
    second = record(available_at_ms=1_000, event_kind="candle", market="SOL", event_key="b")

    assert canonical_record_order((second, first)) == canonical_record_order((first, second))


def test_clock_rejects_time_regression() -> None:
    clock = ReplayClock()
    clock.advance(record(available_at_ms=2_000, event_kind="candle"))

    with pytest.raises(ValueError, match="regress"):
        clock.advance(record(available_at_ms=1_999, event_kind="candle"))


def test_clock_starts_without_time_and_advances_to_availability() -> None:
    clock = ReplayClock()
    assert clock.now_ms is None

    assert clock.advance(record(available_at_ms=1_500, event_kind="active_asset_ctx")) == 1_500
    assert clock.now_ms == 1_500
