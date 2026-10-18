"""Named source gap CLOSE retries retain first originally observed evidence.

Synthetic test fixtures do NOT qualify market completeness or PAPER returns.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.restored_gap_recovery import RestoredNamedGapRecovery

BASE = datetime(2026, 10, 18, tzinfo=UTC)
BASE_MS = int(BASE.timestamp() * 1000)
STREAM = "l2Book:BTC"
FIRST_START = BASE_MS + 100
CHECKPOINT = BASE_MS + 1_000


def _book(number: int, *, market: str = "BTC") -> StreamEvent:
    received_ms = BASE_MS + number
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MarketId("", market),
        exchange_time_ms=received_ms - 100,
        receive_time=BASE + timedelta(milliseconds=number),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"l2Book:{market}:{received_ms}",
        payload={"bids": (), "asks": ()},
    )


def _observer(*, rotation: bool = False) -> RestoredNamedGapRecovery:
    return RestoredNamedGapRecovery(
        market_gaps={STREAM: ((FIRST_START, None),)},
        global_gaps={},
        checkpoint_ms=CHECKPOINT,
        max_exchange_age_ms=5_000,
        recovery_reason=(
            "recovered_after_rotation_witness"
            if rotation else "recovered_after_handoff_witness"
        ),
    )


@pytest.mark.parametrize("cancel", [False, True], ids=["io_failure", "cancelled"])
@pytest.mark.parametrize("rotation", [False, True], ids=["restored", "rotation"])
def test_first_named_recovery_gap_and_witness_never_retimed(
    cancel: bool, rotation: bool,
) -> None:
    async def run() -> None:
        observer = _observer(rotation=rotation)
        initial, newer = _book(2_000), _book(3_000)
        expected = DataGap(
            STREAM, FIRST_START, BASE_MS + 2_000,
            "recovered_after_rotation_witness"
            if rotation else "recovered_after_handoff_witness",
        )
        written_witnesses: list[tuple[StreamEvent, DataGap, int]] = []
        attempted_gaps: list[DataGap] = []
        fail = [True]

        async def witness_sink(
            event: StreamEvent, gap: DataGap, checkpoint_ms: int,
        ) -> None:
            written_witnesses.append((event, gap, checkpoint_ms))

        async def gap_sink(gap: DataGap) -> None:
            attempted_gaps.append(gap)
            if fail[0]:
                if cancel:
                    raise asyncio.CancelledError()
                raise OSError("original recovery gap fsync uncertain")

        error = asyncio.CancelledError if cancel else OSError
        with pytest.raises(error):
            await observer.accept_recorded_event(
                initial, observed_at_ms=BASE_MS + 2_100,
                gap_sink=gap_sink, witness_sink=witness_sink,
            )
        assert observer.pending_named_starts == {STREAM: (FIRST_START,)}
        assert attempted_gaps == [expected]
        assert written_witnesses == [(initial, expected, CHECKPOINT)]

        # PAPER must run this BEFORE the new normalized market record:
        # ongoing failures cannot allow a later timestamp to overtake.
        with pytest.raises(error):
            await observer.retry_pending_before_record(
                STREAM, gap_sink=gap_sink, witness_sink=witness_sink,
            )
        assert attempted_gaps == [expected, expected]
        assert written_witnesses == [(initial, expected, CHECKPOINT)]
        assert observer.pending_named_starts == {STREAM: (FIRST_START,)}

        fail[0] = False
        assert await observer.retry_pending_before_record(
            STREAM, gap_sink=gap_sink, witness_sink=witness_sink,
        ) == 1
        assert attempted_gaps == [expected, expected, expected]
        assert written_witnesses == [(initial, expected, CHECKPOINT)]
        assert observer.pending_named_starts == {}
        assert await observer.accept_recorded_event(
            newer, observed_at_ms=BASE_MS + 3_100,
            gap_sink=gap_sink, witness_sink=witness_sink,
        ) == 0
        assert attempted_gaps[-1] == expected

    asyncio.run(run())


def test_unacknowledged_named_witness_retry_does_not_substitute_later_event() -> None:
    async def run() -> None:
        observer = _observer()
        first, later = _book(2_000), _book(3_000)
        witnessed: list[StreamEvent] = []
        gaps: list[DataGap] = []
        reject = [True]

        async def witness(
            event: StreamEvent, _gap: DataGap, _checkpoint_ms: int,
        ) -> None:
            witnessed.append(event)
            if reject[0]:
                raise OSError("witness fsync rejected")

        async def sink(gap: DataGap) -> None:
            gaps.append(gap)

        with pytest.raises(OSError, match="witness fsync"):
            await observer.accept_recorded_event(
                first, observed_at_ms=BASE_MS + 2_050,
                gap_sink=sink, witness_sink=witness,
            )
        assert gaps == []
        assert witnessed == [first]

        reject[0] = False
        assert await observer.accept_recorded_event(
            later, observed_at_ms=BASE_MS + 3_050,
            gap_sink=sink, witness_sink=witness,
        ) == 1
        assert witnessed == [first, first]
        assert gaps == [DataGap(
            STREAM, FIRST_START, BASE_MS + 2_000,
            "recovered_after_handoff_witness",
        )]
        assert observer.pending_named_starts == {}

    asyncio.run(run())


def test_pending_named_recovery_remains_fail_closed_for_missing_witness_sink() -> None:
    async def run() -> None:
        observer = _observer()

        async def fail_witness(
            _event: StreamEvent, _gap: DataGap, _checkpoint_ms: int,
        ) -> None:
            raise OSError("witness down")

        async def sink(_gap: DataGap) -> None:
            raise AssertionError("gap sink must not be reached")

        with pytest.raises(OSError):
            await observer.accept_recorded_event(
                _book(2_000), observed_at_ms=BASE_MS + 2_001,
                gap_sink=sink, witness_sink=fail_witness,
            )
        with pytest.raises(RuntimeError, match="requires original witness"):
            await observer.retry_pending_before_record(
                STREAM, gap_sink=sink,
            )
        assert observer.pending_named_starts == {STREAM: (FIRST_START,)}

    asyncio.run(run())


def test_original_paper_blocks_market_record_on_previous_named_close_debt() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/cocomelon/continuous_paper.py"
    ).read_text(encoding="utf-8")
    start = source.index("            async def event_sink(event: StreamEvent) -> None:")
    next_market = source.index(
        "await pump.process(_record_from_stream(event))", start,
    )
    first_retry = source.index(
        "await restored_named_gap_recovery.retry_pending_before_record(", start,
    )
    rotation_retry = source.index(
        "await recovery.retry_pending_before_record(", start,
    )
    assert first_retry < rotation_retry < next_market
    assert "await restored_named_gap_recovery.accept_recorded_event(" in source[
        next_market:next_market + 1000
    ]
    assert "await rotation_observer.accept_recorded_event(" in source[
        next_market:next_market + 1800
    ]
    next_gap = source.index(
        "async def gap_sink(gap: DataGap)", next_market,
    )
    forwarded = source.index("await pump.process(gap)", next_gap)
    gap_retry = source.index(
        "await restored_named_gap_recovery.retry_pending_before_record(",
        next_gap,
    )
    rotation_gap_retry = source.index(
        "await recovery.retry_pending_before_record(",
        next_gap,
    )
    assert next_gap < gap_retry < rotation_gap_retry < forwarded
