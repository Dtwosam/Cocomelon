"""Full-frame source order for inherited/rotation allMids gaps.

These are synthetic original-source ordering fixtures, NOT provenance for
live 72-hour market integrity or after-cost PAPER profitability.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.evidence.redundant_stream import RedundantStreamMux
from cocomelon.evidence.restored_gap_recovery import RestoredNamedGapRecovery
from cocomelon.hyperliquid.ws_protocol import normalize_ws_message
from cocomelon.hyperliquid.ws_supervisor import event_stream_id

STREAM = "allMids"


def _mids(ms: int, *, btc: str = "100", eth: str = "50") -> tuple[StreamEvent, ...]:
    return tuple(normalize_ws_message(
        {"channel": "allMids", "data": {"mids": {"BTC": btc, "ETH": eth}}},
        receive_time=datetime.fromtimestamp(ms / 1_000, UTC),
    ))


async def _setup():
    timeline: list[StreamEvent | DataGap] = []
    accepted: dict[str, tuple[StreamEvent, int]] = {}

    async def event_sink(event: StreamEvent) -> None:
        timeline.append(event)
        accepted[event_stream_id(event)] = (
            event, int(event.receive_time.timestamp() * 1000) + 10,
        )

    async def gap_sink(gap: DataGap) -> None:
        timeline.append(gap)

    mux = RedundantStreamMux(
        event_sink=event_sink, gap_sink=gap_sink,
        defer_all_mids_aggregate_recovery=True,
    )
    initial = _mids(1_000, btc="90")
    await mux.on_event(0, initial[0])
    await mux.on_event(1, initial[0])
    await mux.on_gap(0, DataGap(STREAM, 1_100, None, "disconnect"))
    await mux.on_gap(1, DataGap(STREAM, 1_200, None, "disconnect"))
    await mux.on_gap(0, DataGap(STREAM, 1_100, 1_900, "recovered"))
    assert mux._aggregate_gap_starts[STREAM] == 1_200
    timeline.clear()
    accepted.clear()
    restored = RestoredNamedGapRecovery(
        market_gaps={},
        global_gaps={STREAM: ((1_050, None),)},
        checkpoint_ms=1_500,
        max_exchange_age_ms=5_000,
    )
    rotated = RestoredNamedGapRecovery(
        market_gaps={},
        global_gaps={STREAM: ((1_300, None),)},
        checkpoint_ms=1_600,
        max_exchange_age_ms=5_000,
        recovery_reason="recovered_after_rotation_witness",
    )
    return mux, timeline, accepted, restored, rotated, gap_sink


def test_original_allmids_children_precede_both_named_recovery_receipts() -> None:
    async def run() -> None:
        mux, timeline, accepted, restored, rotated, sink = await _setup()
        frame = _mids(2_000)
        await mux.on_event(0, frame[0])
        assert timeline == [frame[0]]
        await mux.on_event(0, frame[1])
        assert timeline == list(frame)

        async def after_frame() -> None:
            # No restored/rotation marker may have been published before
            # the original complete frame, or before mux aggregate close.
            assert timeline == [
                *frame, DataGap(STREAM, 1_200, 2_000, "recovered"),
            ]
            event, observed_ms = accepted.pop(STREAM)
            assert event in frame
            await restored.accept_recorded_event(
                event, observed_at_ms=observed_ms, gap_sink=sink,
            )
            await rotated.accept_recorded_event(
                event, observed_at_ms=observed_ms, gap_sink=sink,
            )

        await mux.complete_all_mids_frame(
            0, frame, after_frame_sink=after_frame,
        )
        assert timeline == [
            *frame,
            DataGap(STREAM, 1_200, 2_000, "recovered"),
            DataGap(STREAM, 1_050, 2_000, "recovered_after_handoff_witness"),
            DataGap(STREAM, 1_300, 2_000, "recovered_after_rotation_witness"),
        ]
        assert restored.pending_named_starts == {}
        assert rotated.pending_named_starts == {}

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["error", "cancel"])
def test_failed_allmids_child_never_enters_full_frame_recovery_callback(
    cancel: bool,
) -> None:
    async def run() -> None:
        mux, timeline, _, restored, rotated, _ = await _setup()
        frame = _mids(2_000)
        failed = [True]
        # Validate the production API contract without trusting any
        # inferred market coverage after a failed/cancelled child.
        original_sink = mux._event_sink

        async def sometimes_fail(event: StreamEvent) -> None:
            if event.market.coin == "ETH" and failed[0]:
                if cancel:
                    raise asyncio.CancelledError()
                raise OSError("ETH original market receipt rejected")
            await original_sink(event)

        mux._event_sink = sometimes_fail
        await mux.on_event(0, frame[0])
        with pytest.raises(asyncio.CancelledError if cancel else OSError):
            await mux.on_event(0, frame[1])
        assert timeline == [frame[0]]
        assert restored.pending_named_starts == {STREAM: (1_050,)}
        assert rotated.pending_named_starts == {STREAM: (1_300,)}

        failed[0] = False
        await mux.on_event(0, frame[0])  # exact replay duplicate
        await mux.on_event(0, frame[1])
        async def after_frame() -> None:
            assert timeline == [
                *frame, DataGap(STREAM, 1_200, 2_000, "recovered"),
            ]
        await mux.complete_all_mids_frame(
            0, frame, after_frame_sink=after_frame,
        )
        assert timeline == [
            *frame, DataGap(STREAM, 1_200, 2_000, "recovered"),
        ]
        # Without an accepted and witnessed post-frame observer callback,
        # no independent checkpoint or rotation gap can be closed.
        assert restored.pending_named_starts == {STREAM: (1_050,)}
        assert rotated.pending_named_starts == {STREAM: (1_300,)}

    asyncio.run(run())


def test_mux_keeps_frame_post_commit_receipts_ahead_of_newer_market_input() -> None:
    async def run() -> None:
        mux, timeline, _, _, _, _ = await _setup()
        frame = _mids(2_000)
        for event in frame:
            await mux.on_event(0, event)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def after_frame() -> None:
            entered.set()
            await release.wait()
            timeline.append(DataGap(
                STREAM, 1_050, 2_000, "recovered_after_handoff_witness",
            ))

        finishing = asyncio.create_task(mux.complete_all_mids_frame(
            0, frame, after_frame_sink=after_frame,
        ))
        await entered.wait()
        next_frame = _mids(3_000, btc="110", eth="55")
        next_event = asyncio.create_task(mux.on_event(0, next_frame[0]))
        await asyncio.sleep(0)
        assert timeline == [
            *frame, DataGap(STREAM, 1_200, 2_000, "recovered"),
        ]
        release.set()
        await finishing
        await next_event
        assert timeline == [
            *frame,
            DataGap(STREAM, 1_200, 2_000, "recovered"),
            DataGap(STREAM, 1_050, 2_000, "recovered_after_handoff_witness"),
            next_frame[0],
        ]

    asyncio.run(run())


def test_paper_defers_original_named_recovery_to_mux_locked_frame_callback() -> None:
    from pathlib import Path

    runtime = (
        Path(__file__).resolve().parents[1]
        / "src/cocomelon/continuous_paper.py"
    ).read_text(encoding="utf-8")
    assert "accepted_named_all_mids[event_stream_id(event)]" in runtime
    assert "if event.kind is StreamKind.ALL_MIDS:" in runtime
    assert "after_frame_sink=finish_named_recovery" in runtime
    assert "await mux.complete_all_mids_frame(" in runtime
    assert "await restored_named_gap_recovery.accept_recorded_event(" in runtime
    assert "await recovery.accept_recorded_event(" in runtime
