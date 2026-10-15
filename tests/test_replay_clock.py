import pytest
from dataclasses import replace

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


def test_original_first_received_ordinals_override_legacy_same_ms_kind_order() -> None:
    # Actual original PAPER receipt: trade before book before snapshot,
    # all within one millisecond. A legacy replay would sort snapshot first.
    rows = (
        replace(record(
            available_at_ms=1_000, event_kind="trade", event_key="z",
        ), source_receive_ordinal=1),
        replace(record(
            available_at_ms=1_000, event_kind="l2_book", event_key="m",
        ), source_receive_ordinal=2),
        replace(record(
            available_at_ms=1_000, event_kind="market_snapshot", event_key="a",
        ), source_receive_ordinal=3),
    )
    assert canonical_record_order(tuple(reversed(rows))) == rows
    assert canonical_record_order(tuple(
        replace(row, source_receive_ordinal=None) for row in rows
    )) != rows


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5])
def test_source_receive_ordinal_must_be_original_positive_int(invalid: object) -> None:
    with pytest.raises(ValueError, match="source_receive_ordinal"):
        replace(
            record(available_at_ms=1000, event_kind="l2_book"),
            source_receive_ordinal=invalid,
        )


def test_canonical_order_supports_public_rest_evidence_kinds() -> None:
    rows = (
        record(available_at_ms=1_000, event_kind="funding_rate", event_key="funding"),
        record(available_at_ms=1_000, event_kind="market_snapshot", event_key="snapshot"),
        record(available_at_ms=1_000, event_kind="active_asset_ctx", event_key="ctx"),
    )

    ordered = canonical_record_order(rows)

    assert [item.event_key for item in ordered] == ["snapshot", "funding", "ctx"]
    assert (
        KIND_PRIORITY["market_snapshot"]
        < KIND_PRIORITY["funding_rate"]
        < KIND_PRIORITY["active_asset_ctx"]
    )


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
