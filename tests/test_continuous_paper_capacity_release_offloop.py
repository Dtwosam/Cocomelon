"""Off-loop optional L2 evidence keeps exact FIFO and PAPER running."""
from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest

from cocomelon.domain.execution import InstrumentExecutionSpec, PaperExecutionConfig
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.continuous_paper_capacity_release_books import (
    AsyncCapacityReleaseBookCapture,
    CapacityReleaseBookCapture,
    CapacityReleaseBookRegistration,
    CapacityReleaseBookStore,
)

BTC = MarketId("", "BTC")


def _store(root: Path) -> CapacityReleaseBookStore:
    return CapacityReleaseBookStore(
        root, capture_started_at_ms=900, latency_ms=250,
        max_book_age_ms=1000, execution_config=PaperExecutionConfig(),
    )


def _registration() -> CapacityReleaseBookRegistration:
    return CapacityReleaseBookRegistration(
        opportunity_id="opp-1", opportunity_timestamp_ms=1000,
        opportunity_market="SOL", opportunity_direction="short",
        release_market="BTC", release_direction="long",
        release_correlation_bucket="majors",
        strategy_decision_id="strategy-1", risk_decision_id="risk-1",
    )


def _position() -> PaperPosition:
    return PaperPosition(
        market=BTC, side=PositionSide.LONG, quantity=Decimal("1"),
        average_entry_price=Decimal("100"), stop_price=Decimal("95"),
        opening_plan_id="original-holder", opened_at_ms=500,
        updated_at_ms=900, correlation_bucket="majors",
        planned_risk=Decimal("20"), venue_max_leverage=Decimal("20"),
        latest_mark=Decimal("101"),
    )


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=BTC, sz_decimals=3, venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900, metadata_source="genuine-meta",
    )


def _book(ms: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK, market=BTC, exchange_time_ms=ms - 10,
        receive_time=datetime.fromtimestamp(ms / 1000, tz=UTC),
        schema_version=1, source="genuine-l2",
        event_key=f"btc-original-book-{ms}",
        payload={
            "bids": ({"px": Decimal("100.9"), "sz": Decimal("2"), "n": 1},),
            "asks": ({"px": Decimal("101.1"), "sz": Decimal("3"), "n": 1},),
        },
    )


def _offer_book(capture: AsyncCapacityReleaseBookCapture, ms: int) -> None:
    capture.observe_book(
        (_position(),), _instrument(), _book(ms),
        reference_price=Decimal("101"), now_ms=ms,
    )


def test_async_offloop_order_matches_exact_original_capture_and_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "async"
    worker_store = _store(root)
    capture = CapacityReleaseBookCapture(worker_store)
    # The real validation path for trace-derived registration is covered
    # by the existing direct capture tests. Here isolate queue causality.
    def fake_register(_trace: object, *, opportunity_id: str) -> None:
        assert opportunity_id == "opp-1"
        worker_store.register(_registration())

    monkeypatch.setattr(capture, "register_from_trace", fake_register)
    async_capture = AsyncCapacityReleaseBookCapture(capture, capacity=8)
    async_capture.register_from_trace(
        SimpleNamespace(), opportunity_id="opp-1",  # type: ignore[arg-type]
    )
    _offer_book(async_capture, 1100)
    _offer_book(async_capture, 1400)
    asyncio.run(async_capture.close())
    assert async_capture.error is None
    assert async_capture.pending == 0
    expected = _store(tmp_path / "direct")
    assert expected.register(_registration())
    for ms in (1100, 1400):
        expected.capture(
            positions=(_position(),), instrument=_instrument(),
            book=_book(ms), reference_price=Decimal("101"), now_ms=ms,
        )
    assert worker_store.iter_registrations() == expected.iter_registrations()
    assert worker_store.iter_pending() == expected.iter_pending()
    assert worker_store.iter_records() == expected.iter_records()
    assert _store(root).iter_records() == expected.iter_records()


def test_heavy_fsync_work_never_blocks_main_paper_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path / "blocked")
    capture = CapacityReleaseBookCapture(store)
    started = threading.Event()
    released = threading.Event()
    original = capture.observe_book

    def slow_original(*args: object, **kwargs: object) -> None:
        started.set()
        assert released.wait(timeout=3)
        original(*args, **kwargs)

    monkeypatch.setattr(capture, "observe_book", slow_original)
    wrapper = AsyncCapacityReleaseBookCapture(capture, capacity=2)

    async def run() -> float:
        begin = monotonic()
        _offer_book(wrapper, 1100)
        await asyncio.sleep(0)
        elapsed = monotonic() - begin
        assert await asyncio.to_thread(started.wait, 1)
        released.set()
        await wrapper.close()
        return elapsed

    assert asyncio.run(run()) < 0.1
    assert wrapper.error is None


def test_full_queue_is_permanently_noncertifying_not_silently_lossy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path / "overflow")
    capture = CapacityReleaseBookCapture(store)
    started = threading.Event()
    released = threading.Event()

    def blocked(*_args: object, **_kwargs: object) -> None:
        started.set()
        assert released.wait(timeout=3)

    monkeypatch.setattr(capture, "observe_book", blocked)
    wrapper = AsyncCapacityReleaseBookCapture(capture, capacity=1)
    _offer_book(wrapper, 1100)
    assert started.wait(timeout=1)
    _offer_book(wrapper, 1400)
    _offer_book(wrapper, 1700)
    assert wrapper.error == "optional_capacity_book_research_queue_overflow"
    released.set()
    asyncio.run(wrapper.close())
    assert wrapper.error == "optional_capacity_book_research_queue_overflow"
    assert worker_error_only(wrapper)


def worker_error_only(wrapper: AsyncCapacityReleaseBookCapture) -> bool:
    return wrapper.error is not None and wrapper.pending == 0


def test_background_write_failure_preserves_negative_failure_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path / "failed")
    capture = CapacityReleaseBookCapture(store)
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("disk did not accept original optional mark")
    monkeypatch.setattr(capture, "observe_book", fail)
    wrapper = AsyncCapacityReleaseBookCapture(capture)
    _offer_book(wrapper, 1100)
    asyncio.run(wrapper.close())
    assert wrapper.error is not None
    assert "OSError" in wrapper.error
    assert store.iter_records() == ()


def test_drain_timeout_never_claims_clean_research_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path / "timeout")
    capture = CapacityReleaseBookCapture(store)
    started = threading.Event()
    release = threading.Event()

    def blocked(*args: object, **kwargs: object) -> None:
        started.set()
        assert release.wait(timeout=3)
    monkeypatch.setattr(capture, "observe_book", blocked)
    wrapper = AsyncCapacityReleaseBookCapture(capture)
    _offer_book(wrapper, 1100)
    assert started.wait(timeout=1)
    asyncio.run(wrapper.close(timeout_seconds=0.01))
    assert wrapper.error == "optional_capacity_book_research_drain_timeout"
    release.set()
    wrapper._worker.join(timeout=2)
    assert not wrapper._worker.is_alive()
