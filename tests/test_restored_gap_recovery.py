from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.restored_gap_recovery import (
    RestoredNamedGapRecovery,
    append_restored_named_gap_witness,
    rotation_named_gap_recovery,
)

BASE = datetime(2026, 10, 9, 17, 0, tzinfo=UTC)
BASE_MS = int(BASE.timestamp() * 1_000)


def _event(
    *,
    market: str = "BTC",
    kind: StreamKind = StreamKind.L2_BOOK,
    received_ms: int = BASE_MS + 2_000,
    exchange_ms: int | None = BASE_MS + 1_900,
    source: str = "hyperliquid-mainnet-ws",
) -> StreamEvent:
    coin = MarketId("", market)
    if kind is StreamKind.ALL_MIDS:
        exchange_ms = None
    return StreamEvent(
        kind=kind,
        market=coin,
        exchange_time_ms=exchange_ms,
        receive_time=BASE + timedelta(milliseconds=received_ms - BASE_MS),
        schema_version=1,
        source=source,
        event_key=f"{kind}:{market}:{received_ms}",
        payload={"bids": (), "asks": ()} if kind is StreamKind.L2_BOOK else {},
    )


def _recovery(
    *,
    market: dict[str, tuple[tuple[int, int | None], ...]] | None = None,
    shared: dict[str, tuple[tuple[int, int | None], ...]] | None = None,
) -> RestoredNamedGapRecovery:
    return RestoredNamedGapRecovery(
        market_gaps=market if market is not None else {
            "l2Book:BTC": (
                (BASE_MS - 10_000, None),
                (BASE_MS - 8_000, BASE_MS - 4_000),
                (BASE_MS - 5_000, None),
            ),
            "l2Book:ETH": ((BASE_MS - 6_000, None),),
        },
        global_gaps=shared if shared is not None else {
            "allMids": ((BASE_MS - 7_000, None),),
            "unknown-legacy-topic": ((BASE_MS - 9_000, None),),
        },
        checkpoint_ms=BASE_MS,
        max_exchange_age_ms=5_000,
    )


def test_valid_fresh_recovery_persists_exact_starts_once() -> None:
    async def run() -> None:
        recovery = _recovery()
        persisted: list[DataGap] = []

        async def gap_sink(gap: DataGap) -> None:
            persisted.append(gap)

        event = _event()
        count = await recovery.accept_recorded_event(
            event, observed_at_ms=BASE_MS + 2_300, gap_sink=gap_sink,
        )
        assert count == 2
        assert [
            (gap.stream_id, gap.started_ms, gap.ended_ms, gap.reason)
            for gap in persisted
        ] == [
            (
                "l2Book:BTC", BASE_MS - 10_000, BASE_MS + 2_000,
                "recovered_after_handoff_witness",
            ),
            (
                "l2Book:BTC", BASE_MS - 5_000, BASE_MS + 2_000,
                "recovered_after_handoff_witness",
            ),
        ]
        assert "l2Book:BTC" not in recovery.pending_named_starts
        assert recovery.pending_named_starts["l2Book:ETH"] == (
            BASE_MS - 6_000,
        )
        assert await recovery.accept_recorded_event(
            event, observed_at_ms=BASE_MS + 2_300, gap_sink=gap_sink,
        ) == 0
        assert len(persisted) == 2

    asyncio.run(run())


def test_shared_recovery_cannot_erase_other_named_or_anonymous_histories() -> None:
    async def run() -> None:
        recovery = _recovery()
        persisted: list[DataGap] = []

        async def gap_sink(gap: DataGap) -> None:
            persisted.append(gap)

        assert await recovery.accept_recorded_event(
            _event(kind=StreamKind.ALL_MIDS),
            observed_at_ms=BASE_MS + 2_100,
            gap_sink=gap_sink,
        ) == 1
        assert persisted[0].stream_id == "allMids"
        assert "unknown-legacy-topic" in recovery.pending_named_starts
        assert "l2Book:BTC" in recovery.pending_named_starts
        assert "l2Book:ETH" in recovery.pending_named_starts

        assert await recovery.accept_recorded_event(
            _event(market="SOL"), observed_at_ms=BASE_MS + 2_200,
            gap_sink=gap_sink,
        ) == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    ("received_ms", "exchange_ms", "source", "observed_at_ms"),
    [
        (BASE_MS, BASE_MS - 100, "hyperliquid-mainnet-ws", BASE_MS + 1_000),
        (BASE_MS - 100, BASE_MS - 200, "hyperliquid-mainnet-ws", BASE_MS + 1_000),
        (BASE_MS + 2_000, BASE_MS - 20_000, "hyperliquid-mainnet-ws", BASE_MS + 2_100),
        (BASE_MS + 2_000, BASE_MS + 2_001, "hyperliquid-mainnet-ws", BASE_MS + 2_100),
        (BASE_MS + 2_000, None, "hyperliquid-mainnet-ws", BASE_MS + 2_100),
        (BASE_MS + 2_000, BASE_MS + 1_900, "hyperliquid-mainnet-rest", BASE_MS + 2_100),
        (BASE_MS + 2_000, BASE_MS + 1_900, "hyperliquid-mainnet-ws", BASE_MS + 32_500),
        (BASE_MS + 2_000, BASE_MS + 1_900, "hyperliquid-mainnet-ws", BASE_MS + 1_900),
    ],
)
def test_old_stale_rest_future_and_uncommitted_receipts_never_heal(
    received_ms: int,
    exchange_ms: int | None,
    source: str,
    observed_at_ms: int,
) -> None:
    async def run() -> None:
        recovery = _recovery()
        gaps: list[DataGap] = []

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        assert await recovery.accept_recorded_event(
            _event(
                received_ms=received_ms,
                exchange_ms=exchange_ms,
                source=source,
            ),
            observed_at_ms=observed_at_ms,
            gap_sink=gap_sink,
        ) == 0
        assert gaps == []
        assert recovery.pending_named_starts["l2Book:BTC"] == (
            BASE_MS - 10_000, BASE_MS - 5_000,
        )

    asyncio.run(run())


def test_failed_gap_sink_keeps_uncommitted_start_for_retry() -> None:
    async def run() -> None:
        recovery = _recovery(
            market={"l2Book:BTC": ((BASE_MS - 10_000, None),)},
            shared={},
        )

        async def failed_sink(_gap: DataGap) -> None:
            raise RuntimeError("gap persistence failed")

        with pytest.raises(RuntimeError, match="gap persistence failed"):
            await recovery.accept_recorded_event(
                _event(), observed_at_ms=BASE_MS + 2_100,
                gap_sink=failed_sink,
            )
        assert recovery.pending_named_starts == {
            "l2Book:BTC": (BASE_MS - 10_000,)
        }

        gaps: list[DataGap] = []

        async def successful_sink(gap: DataGap) -> None:
            gaps.append(gap)

        assert await recovery.accept_recorded_event(
            _event(), observed_at_ms=BASE_MS + 2_100,
            gap_sink=successful_sink,
        ) == 1
        assert len(gaps) == 1
        assert not recovery.pending_named_starts

    asyncio.run(run())


def test_concurrent_acceptance_cannot_double_close_same_source() -> None:
    async def run() -> None:
        recovery = _recovery(
            market={"l2Book:BTC": ((BASE_MS - 10_000, None),)},
            shared={},
        )
        gaps: list[DataGap] = []

        async def sink(gap: DataGap) -> None:
            await asyncio.sleep(0)
            gaps.append(gap)

        counts = await asyncio.gather(
            recovery.accept_recorded_event(
                _event(), observed_at_ms=BASE_MS + 2_100,
                gap_sink=sink,
            ),
            recovery.accept_recorded_event(
                _event(), observed_at_ms=BASE_MS + 2_100,
                gap_sink=sink,
            ),
        )
        assert sorted(counts) == [0, 1]
        assert len(gaps) == 1
        assert recovery.pending_named_starts == {}

    asyncio.run(run())


def test_receive_only_mainnet_topic_requires_forward_checkpoint_receipt() -> None:
    async def run() -> None:
        recovery = _recovery(
            market={}, shared={"allMids": ((BASE_MS - 20_000, None),)}
        )
        observed: list[DataGap] = []

        async def sink(gap: DataGap) -> None:
            observed.append(gap)

        assert await recovery.accept_recorded_event(
            _event(kind=StreamKind.ALL_MIDS, received_ms=BASE_MS - 1_000),
            observed_at_ms=BASE_MS + 2_000, gap_sink=sink,
        ) == 0
        assert await recovery.accept_recorded_event(
            _event(kind=StreamKind.ALL_MIDS, received_ms=BASE_MS + 2_000),
            observed_at_ms=BASE_MS + 2_010, gap_sink=sink,
        ) == 1
        assert len(observed) == 1

    asyncio.run(run())


def test_recovery_rejects_ambiguous_scope_and_invalid_limits() -> None:
    with pytest.raises(ValueError, match="both checkpoint scopes"):
        _recovery(
            market={"allMids": ((BASE_MS - 10_000, None),)},
            shared={"allMids": ((BASE_MS - 7_000, None),)},
        )
    with pytest.raises(ValueError, match="invalid restored named source"):
        RestoredNamedGapRecovery(
            market_gaps={}, global_gaps={}, checkpoint_ms=BASE_MS,
            max_exchange_age_ms=0,
        )



def test_fsynced_witness_precedes_gap_commit_and_preserves_event_identity(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        recovery = _recovery(
            market={"l2Book:BTC": ((BASE_MS - 10_000, None),)},
            shared={},
        )
        path = tmp_path / "named-gap-recovery-witnesses.jsonl"
        events: list[str] = []

        async def persist_witness(
            event: StreamEvent, gap: DataGap, checkpoint_ms: int,
        ) -> None:
            append_restored_named_gap_witness(
                path, event=event, gap=gap, checkpoint_ms=checkpoint_ms,
            )
            events.append("witness")

        async def persist_gap(_gap: DataGap) -> None:
            assert path.exists()
            events.append("gap")

        event = _event()
        assert await recovery.accept_recorded_event(
            event, observed_at_ms=BASE_MS + 2_300,
            gap_sink=persist_gap, witness_sink=persist_witness,
        ) == 1
        assert events == ["witness", "gap"]
        rows = [json.loads(s) for s in path.read_text().splitlines()]
        assert len(rows) == 1
        assert rows[0]["stream_id"] == "l2Book:BTC"
        assert rows[0]["witness_event_key"] == event.event_key
        assert rows[0]["checkpoint_last_available_at_ms"] == BASE_MS
        assert rows[0]["independently_verified_checkpoint_closure"] is False

    asyncio.run(run())


def test_failed_witness_fsync_never_closes_named_gap() -> None:
    async def run() -> None:
        recovery = _recovery(
            market={"l2Book:BTC": ((BASE_MS - 10_000, None),)},
            shared={},
        )
        gap_calls = 0

        async def rejected_witness(
            _event: StreamEvent, _gap: DataGap, _checkpoint_ms: int,
        ) -> None:
            raise OSError("fsync not durable")

        async def gap_sink(_gap: DataGap) -> None:
            nonlocal gap_calls
            gap_calls += 1

        with pytest.raises(OSError, match="fsync not durable"):
            await recovery.accept_recorded_event(
                _event(), observed_at_ms=BASE_MS + 2_100,
                gap_sink=gap_sink, witness_sink=rejected_witness,
            )
        assert gap_calls == 0
        assert recovery.pending_named_starts == {
            "l2Book:BTC": (BASE_MS - 10_000,)
        }

    asyncio.run(run())


def test_rotation_recovery_keeps_only_unclaimed_actual_open_starts() -> None:
    old = _recovery(
        market={"l2Book:BTC": ((BASE_MS - 10_000, None),)},
        shared={},
    )
    rotating = rotation_named_gap_recovery(
        market_gaps={
            "l2Book:BTC": (
                (BASE_MS - 10_000, None),  # owned by original checkpoint
                (BASE_MS - 2_000, BASE_MS - 1_000),  # already closed
                (BASE_MS + 100, None),  # SAME-worker rotation gap
                (BASE_MS + 5_000, None),  # created after rotation snapshot
            ),
            "l2Book:ETH": ((BASE_MS + 200, None),),
        },
        global_gaps={"allMids": ((BASE_MS + 300, None),)},
        checkpoint_ms=BASE_MS + 1_000,
        max_exchange_age_ms=5_000,
        earlier_observers=(old,),
    )
    assert rotating is not None
    assert rotating.pending_named_starts == {
        "allMids": (BASE_MS + 300,),
        "l2Book:BTC": (BASE_MS + 100,),
        "l2Book:ETH": (BASE_MS + 200,),
    }
    assert old.pending_named_starts == {
        "l2Book:BTC": (BASE_MS - 10_000,)
    }


def test_rotation_witness_after_accepted_live_market_event_only() -> None:
    async def run() -> None:
        old = _recovery(
            market={"l2Book:BTC": ((BASE_MS - 10_000, None),)},
            shared={},
        )
        rotation = rotation_named_gap_recovery(
            market_gaps={
                "l2Book:BTC": (
                    (BASE_MS - 10_000, None),
                    (BASE_MS + 100, None),
                ),
                "l2Book:ETH": ((BASE_MS + 300, None),),
            },
            global_gaps={},
            checkpoint_ms=BASE_MS + 1_000,
            max_exchange_age_ms=5_000,
            earlier_observers=(old,),
        )
        assert rotation is not None
        gaps: list[DataGap] = []

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        # Before the replacement group's checkpoint there is no new witness.
        assert await rotation.accept_recorded_event(
            _event(received_ms=BASE_MS + 1_000,
                   exchange_ms=BASE_MS + 900),
            observed_at_ms=BASE_MS + 1_000,
            gap_sink=gap_sink,
        ) == 0
        # An independent market cannot heal this source.
        assert await rotation.accept_recorded_event(
            _event(market="SOL"),
            observed_at_ms=BASE_MS + 2_010,
            gap_sink=gap_sink,
        ) == 0
        # The actual accepted, exchange-fresh same-source book closes only
        # the new in-session start. Old checkpoint lineage is still waiting
        # for its distinct signed witness observer.
        assert await rotation.accept_recorded_event(
            _event(),
            observed_at_ms=BASE_MS + 2_010,
            gap_sink=gap_sink,
        ) == 1
        assert [(g.stream_id, g.started_ms, g.ended_ms) for g in gaps] == [
            ("l2Book:BTC", BASE_MS + 100, BASE_MS + 2_000),
        ]
        assert old.pending_named_starts["l2Book:BTC"] == (
            BASE_MS - 10_000,
        )
        assert rotation.pending_named_starts == {
            "l2Book:ETH": (BASE_MS + 300,),
        }
    asyncio.run(run())


def test_sequential_rotations_never_discard_unrecovered_starts() -> None:
    async def run() -> None:
        old = _recovery(market={}, shared={})
        first = rotation_named_gap_recovery(
            market_gaps={"l2Book:BTC": ((BASE_MS + 100, None),)},
            global_gaps={},
            checkpoint_ms=BASE_MS + 1_000,
            max_exchange_age_ms=5_000,
            earlier_observers=(old,),
        )
        assert first is not None
        second = rotation_named_gap_recovery(
            market_gaps={"l2Book:BTC": (
                (BASE_MS + 100, None), (BASE_MS + 1_300, None),
            )},
            global_gaps={},
            checkpoint_ms=BASE_MS + 1_500,
            max_exchange_age_ms=5_000,
            earlier_observers=(old, first),
        )
        assert second is not None
        assert first.pending_named_starts == {"l2Book:BTC": (BASE_MS + 100,)}
        assert second.pending_named_starts == {"l2Book:BTC": (BASE_MS + 1_300,)}
        gaps: list[DataGap] = []

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        event = _event()
        assert await first.accept_recorded_event(
            event, observed_at_ms=BASE_MS + 2_100, gap_sink=gap_sink,
        ) == 1
        assert await second.accept_recorded_event(
            event, observed_at_ms=BASE_MS + 2_100, gap_sink=gap_sink,
        ) == 1
        assert {g.started_ms for g in gaps} == {
            BASE_MS + 100, BASE_MS + 1_300,
        }
    asyncio.run(run())


@pytest.mark.parametrize(
    ("event_receive", "exchange_ms", "source", "observed_at_ms"),
    [
        (BASE_MS + 900, BASE_MS + 890, "hyperliquid-mainnet-ws", BASE_MS + 1_100),
        (BASE_MS + 2_000, BASE_MS - 20_000, "hyperliquid-mainnet-ws", BASE_MS + 2_100),
        (BASE_MS + 2_000, None, "hyperliquid-mainnet-ws", BASE_MS + 2_100),
        (BASE_MS + 2_000, BASE_MS + 1_900, "hyperliquid-mainnet-rest", BASE_MS + 2_100),
        (BASE_MS + 2_000, BASE_MS + 1_900, "hyperliquid-mainnet-ws", BASE_MS + 80_000),
    ],
)
def test_rotation_never_heals_stale_unaccepted_or_wrong_source(
    event_receive: int, exchange_ms: int | None,
    source: str, observed_at_ms: int,
) -> None:
    async def run() -> None:
        recovery = rotation_named_gap_recovery(
            market_gaps={"l2Book:BTC": ((BASE_MS + 100, None),)},
            global_gaps={},
            checkpoint_ms=BASE_MS + 1_000,
            max_exchange_age_ms=5_000,
            earlier_observers=(),
        )
        assert recovery is not None
        gaps: list[DataGap] = []

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        assert await recovery.accept_recorded_event(
            _event(
                received_ms=event_receive, exchange_ms=exchange_ms,
                source=source,
            ),
            observed_at_ms=observed_at_ms,
            gap_sink=gap_sink,
        ) == 0
        assert gaps == []
        assert recovery.pending_named_starts == {
            "l2Book:BTC": (BASE_MS + 100,),
        }
    asyncio.run(run())


def test_rotated_gap_sink_failure_keeps_named_start_pending() -> None:
    async def run() -> None:
        recovery = rotation_named_gap_recovery(
            market_gaps={"l2Book:BTC": ((BASE_MS + 100, None),)},
            global_gaps={},
            checkpoint_ms=BASE_MS + 1_000,
            max_exchange_age_ms=5_000,
            earlier_observers=(),
        )
        assert recovery is not None

        async def failing_sink(_gap: DataGap) -> None:
            raise OSError("durable replay rejection")

        with pytest.raises(OSError, match="durable replay rejection"):
            await recovery.accept_recorded_event(
                _event(),
                observed_at_ms=BASE_MS + 2_100,
                gap_sink=failing_sink,
            )
        assert recovery.pending_named_starts == {
            "l2Book:BTC": (BASE_MS + 100,),
        }
    asyncio.run(run())


def test_paper_runtime_witnesses_both_supervisor_rotation_paths() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    assert "in_session_rotation_gap_recoveries" in source
    assert source.count("register_rotated_group_gap_recovery()") == 3
    assert source.count("await _cancel_supervisor_group(previous_group)") == 1
    assert (
        "await _cancel_supervisor_group(\n                                previous_group"
        in source
    )
    callback = source.index("async def event_sink(event: StreamEvent)")
    recorded = source.index("await pump.process(_record_from_stream(event))", callback)
    rotated = source.index(
        "await rotation_observer.accept_recorded_event(", recorded
    )
    assert recorded < rotated
    assert "gap_sink=lambda gap: pump.process(_record_from_gap(gap))" in (
        source[rotated:rotated + 300]
    )
