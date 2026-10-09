from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.restored_gap_recovery import RestoredNamedGapRecovery

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
        receive_time=datetime.fromtimestamp(received_ms / 1_000, tz=UTC),
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
