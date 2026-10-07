from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_paired_shadow_runtime import (
    LossContextPairedShadowRuntime,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)

MARKET = MarketId("", "TEST")


def _freeze() -> LossContextPortfolioShadowFreeze:
    frozen_at_ms = 1_000
    return LossContextPortfolioShadowFreeze(
        loss_context_candidate_id="a" * 64,
        source_composition_digest="b" * 64,
        source_max_timestamp_ms=900,
        source_paper_run_id=123,
        source_paper_run_attempt=1,
        source_paper_head_sha="c" * 40,
        dimensions=("lead_strategy", "trend_regime"),
        values=("mean_reversion", "down"),
        horizons_ms=(300_000, 900_000),
        frozen_at_ms=frozen_at_ms,
        prospective_not_before_ms=(
            frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ),
    )


def _record(at_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at_ms,
        source="paired-runtime-test",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=at_ms,
        event_key=f"record:{at_ms}",
        payload_json=json.dumps({"mark_px": "100"}),
        event_kind="active_asset_ctx",
    )


class _FakeShadow:
    events: list[tuple[object, ...]] = []
    thread_ids: list[int] = []

    def __init__(self, **_kwargs: Any) -> None:
        type(self).events = []
        type(self).thread_ids = []

    @classmethod
    def _observe_thread(cls) -> None:
        cls.thread_ids.append(threading.get_ident())

    def on_record(
        self,
        record: ReplayRecord,
        now_ms: int,
        *,
        evaluate_decisions: bool = True,
    ) -> None:
        self._observe_thread()
        self.events.append(
            ("record", record.available_at_ms, now_ms, evaluate_decisions)
        )

    def reconcile_markets(
        self,
        selected_markets: tuple[MarketId, ...],
    ) -> None:
        self._observe_thread()
        self.events.append(
            (
                "reconcile",
                tuple(market.canonical for market in selected_markets),
            )
        )

    def mark_restore_warmup_complete(self) -> None:
        self._observe_thread()
        self.events.append(("warmup_complete",))

    def checkpoint(self, *, end_ms: int) -> dict[str, object]:
        self._observe_thread()
        self.events.append(("checkpoint", end_ms))
        return {"checkpoint_end_ms": end_ms}

    def summary_payload(self, *, end_ms: int) -> dict[str, object]:
        self._observe_thread()
        self.events.append(("summary", end_ms))
        return {"summary_end_ms": end_ms}

    def close(self) -> None:
        self._observe_thread()
        self.events.append(("close",))


class _SlowShadow(_FakeShadow):
    entered = threading.Event()
    release = threading.Event()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        type(self).entered = threading.Event()
        type(self).release = threading.Event()

    def on_record(
        self,
        record: ReplayRecord,
        now_ms: int,
        *,
        evaluate_decisions: bool = True,
    ) -> None:
        self._observe_thread()
        self.entered.set()
        self.release.wait(timeout=5)
        self.events.append(
            ("record", record.available_at_ms, now_ms, evaluate_decisions)
        )


def _runtime(
    tmp_path: Path,
    *,
    shadow_factory: type[_FakeShadow],
    max_queue_size: int = 16,
) -> LossContextPairedShadowRuntime:
    return LossContextPairedShadowRuntime(
        freeze=_freeze(),
        replay_config=BaselineReplayConfig(
            execution=PaperExecutionConfig()
        ),
        selected_markets=(MARKET,),
        state_root=tmp_path,
        startup_timestamp_ms=2_000,
        max_queue_size=max_queue_size,
        shadow_factory=shadow_factory,  # type: ignore[arg-type]
    )


def test_paired_shadow_runtime_processes_off_main_thread_in_order(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, shadow_factory=_FakeShadow)
    main_thread = threading.get_ident()
    try:
        assert runtime.submit_record(
            _record(3_000),
            now_ms=3_000,
            evaluate_decisions=False,
        )
        assert runtime.submit_restore_warmup_complete()
        assert runtime.submit_reconcile((MARKET,))
        assert runtime.submit_record(
            _record(4_000),
            now_ms=4_000,
            evaluate_decisions=True,
        )
        checkpoint = asyncio.run(
            runtime.checkpoint(end_ms=5_000)
        )
        summary = asyncio.run(runtime.summary(end_ms=5_000))

        assert checkpoint == {"checkpoint_end_ms": 5_000}
        assert summary == {"summary_end_ms": 5_000}
        assert _FakeShadow.events[:6] == [
            ("record", 3_000, 3_000, False),
            ("warmup_complete",),
            ("reconcile", ("TEST",)),
            ("record", 4_000, 4_000, True),
            ("checkpoint", 5_000),
            ("summary", 5_000),
        ]
        assert _FakeShadow.thread_ids
        assert set(_FakeShadow.thread_ids) == {
            _FakeShadow.thread_ids[0]
        }
        assert _FakeShadow.thread_ids[0] != main_thread

        status = runtime.status_payload()
        assert status["submitted_records"] == 2
        assert status["processed_records"] == 2
        assert status["checkpoint_count"] == 1
        assert status["queue_overflows"] == 0
        assert status["non_blocking_active_paper_feed"] is True
        assert status["execution_authority"] is False
    finally:
        asyncio.run(runtime.close())

    assert _FakeShadow.events[-1] == ("close",)


def test_paired_shadow_runtime_overflow_fails_only_shadow_closed(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        shadow_factory=_SlowShadow,
        max_queue_size=1,
    )
    try:
        assert runtime.submit_record(
            _record(3_000),
            now_ms=3_000,
            evaluate_decisions=False,
        )
        assert _SlowShadow.entered.wait(timeout=2)
        assert runtime.submit_record(
            _record(4_000),
            now_ms=4_000,
            evaluate_decisions=False,
        )
        assert (
            runtime.submit_record(
                _record(5_000),
                now_ms=5_000,
                evaluate_decisions=False,
            )
            is False
        )
        status = runtime.status_payload()
        assert status["failed"] is True
        assert status["queue_overflows"] == 1
        assert status["execution_authority"] is False
        assert "queue overflow" in str(status["error"])
    finally:
        _SlowShadow.release.set()
        asyncio.run(runtime.close())
