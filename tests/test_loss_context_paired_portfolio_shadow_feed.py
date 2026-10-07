from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.research.loss_context_paired_portfolio_shadow_feed import (
    LossContextPairedShadowBackgroundFeed,
)


def _record(sequence: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=sequence,
        source="paired-shadow-feed-test",
        schema_version=1,
        market="TEST",
        exchange_time_ms=sequence,
        event_key=f"record-{sequence}",
        payload_json=json.dumps(
            {"sequence": sequence},
            sort_keys=True,
        ),
        event_kind="active_asset_ctx",
    )


@dataclass
class _FakeShadow:
    events: list[str]
    thread_ids: list[int]
    block_first: bool = False
    raise_on_record: bool = False
    first_entered: threading.Event = field(
        default_factory=threading.Event
    )
    release_first: threading.Event = field(
        default_factory=threading.Event
    )

    def _thread(self) -> None:
        self.thread_ids.append(threading.get_ident())

    def on_record(
        self,
        record: ReplayRecord,
        now_ms: int,
        *,
        evaluate_decisions: bool = True,
    ) -> None:
        self._thread()
        assert now_ms == record.available_at_ms
        self.events.append(
            f"record:{record.event_key}:{evaluate_decisions}"
        )
        if self.raise_on_record:
            raise RuntimeError("synthetic worker failure")
        if self.block_first and record.event_key == "record-1":
            self.first_entered.set()
            assert self.release_first.wait(5)

    def reconcile_markets(
        self,
        selected_markets: tuple[MarketId, ...],
    ) -> None:
        self._thread()
        self.events.append(
            "reconcile:"
            + ",".join(
                market.canonical for market in selected_markets
            )
        )

    def mark_restore_warmup_complete(self) -> None:
        self._thread()
        self.events.append("warmup-complete")

    def checkpoint(self, *, end_ms: int) -> dict[str, object]:
        self._thread()
        self.events.append(f"checkpoint:{end_ms}")
        return {"end_ms": end_ms}

    def summary_payload(self, *, end_ms: int) -> dict[str, object]:
        self._thread()
        self.events.append(f"summary:{end_ms}")
        return {"end_ms": end_ms, "events": tuple(self.events)}

    def close(self) -> None:
        self._thread()
        self.events.append("close")


def test_background_feed_keeps_shadow_work_off_caller_thread() -> None:
    main_thread_id = threading.get_ident()
    events: list[str] = []
    thread_ids: list[int] = []
    holder: list[_FakeShadow] = []

    def factory() -> _FakeShadow:
        shadow = _FakeShadow(events, thread_ids)
        shadow._thread()
        holder.append(shadow)
        return shadow

    feed = LossContextPairedShadowBackgroundFeed(
        factory,
        max_queue_records=16,
    )
    feed.start()
    assert feed.wait_until_ready()

    assert feed.offer_record(
        _record(1),
        evaluate_decisions=False,
    )
    assert feed.request_warmup_complete()
    assert feed.request_reconcile(
        (MarketId("", "BBB"), MarketId("", "AAA"))
    )
    assert feed.offer_record(_record(2))
    assert feed.request_summary(end_ms=2)
    assert feed.request_checkpoint(end_ms=2)
    assert feed.wait_until_idle()

    assert events[:6] == [
        "record:record-1:False",
        "warmup-complete",
        "reconcile:AAA,BBB",
        "record:record-2:True",
        "summary:2",
        "checkpoint:2",
    ]
    assert holder
    assert thread_ids
    assert all(item == thread_ids[0] for item in thread_ids)
    assert thread_ids[0] != main_thread_id
    assert feed.last_summary is not None
    assert feed.last_summary["end_ms"] == 2

    status = feed.status_payload()
    assert status["failed"] is False
    assert status["offered_records"] == 2
    assert status["accepted_records"] == 2
    assert status["processed_records"] == 2
    assert status["offered_controls"] == 4
    assert status["processed_controls"] == 4
    assert status["checkpoint_count"] == 1
    assert status["summary_count"] == 1
    assert status["hot_path_blocking_puts"] == 0
    assert status["active_trader_backpressure"] is False

    assert feed.request_stop()
    assert feed.join()
    assert events[-1] == "close"


def test_background_feed_overflow_fails_research_closed() -> None:
    events: list[str] = []
    thread_ids: list[int] = []
    holder: list[_FakeShadow] = []

    def factory() -> _FakeShadow:
        shadow = _FakeShadow(
            events,
            thread_ids,
            block_first=True,
        )
        holder.append(shadow)
        return shadow

    feed = LossContextPairedShadowBackgroundFeed(
        factory,
        max_queue_records=1,
    )
    feed.start()
    assert feed.wait_until_ready()
    assert feed.offer_record(_record(1))
    assert holder[0].first_entered.wait(5)

    assert feed.offer_record(_record(2))
    assert feed.offer_record(_record(3)) is False
    status = feed.status_payload()
    assert status["failed"] is True
    assert status["failed_reason"] == "queue_overflow"
    assert status["queue_overflow_count"] == 1

    assert feed.offer_record(_record(4)) is False
    holder[0].release_first.set()
    assert feed.wait_until_idle()
    assert feed.request_stop()
    assert feed.join()

    status = feed.status_payload()
    assert status["processed_records"] == 1
    assert status["accepted_records"] == 2
    assert status["rejected_after_failure"] >= 1
    assert status["overflow_fails_research_closed"] is True


def test_background_feed_worker_exception_never_escapes_hot_path() -> None:
    events: list[str] = []
    thread_ids: list[int] = []

    feed = LossContextPairedShadowBackgroundFeed(
        lambda: _FakeShadow(
            events,
            thread_ids,
            raise_on_record=True,
        ),
        max_queue_records=4,
    )
    feed.start()
    assert feed.wait_until_ready()

    assert feed.offer_record(_record(1)) is True
    assert feed.wait_until_idle()
    status = feed.status_payload()
    assert status["failed"] is True
    assert status["failed_reason"] == "worker_exception"
    assert "synthetic worker failure" in str(status["failed_detail"])
    assert feed.request_checkpoint(end_ms=1) is False

    assert feed.request_stop()
    assert feed.join()
    assert status["active_trader_backpressure"] is False
