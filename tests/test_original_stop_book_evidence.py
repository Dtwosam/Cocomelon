from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    OrderSide,
    OrderType,
    PaperExecutionConfig,
    PaperOrderPlan,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import (
    PaperPosition,
    PositionSide,
)
from cocomelon.research.original_stop_book_evidence import (
    MAX_ORIGINAL_STOP_PLAN_CACHE,
    OriginalStopBookCapture,
    OriginalStopBookEvidenceStore,
)

MARKET = MarketId("", "SOL")
CONFIG = PaperExecutionConfig(latency_ms=250)


def _plan(
    *,
    side: OrderSide = OrderSide.BUY,
) -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id="risk-1",
        strategy_decision_id="strategy-1",
        market=MARKET,
        side=side,
        requested_quantity=Decimal("2"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=(
            Decimal("95")
            if side is OrderSide.BUY
            else Decimal("105")
        ),
        approved_notional_ceiling=Decimal("1000"),
        created_at_ms=900,
        earliest_execution_ms=1_000,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=800,
        approved_risk_amount_ceiling=Decimal("20"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.051"),
    )


def _position(
    plan: PaperOrderPlan,
    *,
    side: PositionSide = PositionSide.LONG,
) -> PaperPosition:
    return PaperPosition(
        market=MARKET,
        side=side,
        quantity=Decimal("2"),
        average_entry_price=Decimal("100"),
        stop_price=(
            Decimal("95")
            if side is PositionSide.LONG
            else Decimal("105")
        ),
        opening_plan_id=plan.plan_id,
        opened_at_ms=1_000,
        updated_at_ms=1_000,
        planned_risk=Decimal("20"),
    )


def _mark(
    price: str,
    receive_ms: int,
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=receive_ms - 1,
        receive_time=datetime.fromtimestamp(
            receive_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"mark:{receive_ms}",
        payload={"mark_px": Decimal(price)},
    )


def _book(
    receive_ms: int,
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=receive_ms - 1,
        receive_time=datetime.fromtimestamp(
            receive_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"book:{receive_ms}",
        payload={
            "bids": (
                {
                    "px": Decimal("94.9"),
                    "sz": Decimal("1"),
                    "n": 2,
                },
                {
                    "px": Decimal("94.8"),
                    "sz": Decimal("3"),
                    "n": 1,
                },
            ),
            "asks": (
                {
                    "px": Decimal("95.1"),
                    "sz": Decimal("4"),
                    "n": 1,
                },
            ),
        },
    )


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=800,
        metadata_source="hyperliquid-mainnet-meta",
    )


def _capture(
    root: Path,
    plan: PaperOrderPlan,
) -> OriginalStopBookCapture:
    return OriginalStopBookCapture(
        OriginalStopBookEvidenceStore(root),
        opening_plan_loader=lambda plan_id: (
            plan if plan_id == plan.plan_id else None
        ),
        config=CONFIG,
    )


def test_capture_protocol_start_is_durable_across_restarts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stop-books"
    first = OriginalStopBookEvidenceStore(
        root,
        started_at_ms=1_000,
    )
    assert first.capture_started_at_ms == 1_000

    restored = OriginalStopBookEvidenceStore(
        root,
        started_at_ms=2_000,
    )
    assert restored.capture_started_at_ms == 1_000
    assert restored.state_digest == first.state_digest


def test_capture_uses_plan_book_then_first_latency_eligible_book(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stop-books"
    plan = _plan()
    position = _position(plan)
    capture = _capture(root, plan)

    capture.observe_mark(
        (position,),
        _mark("96", 1_100),
        now_ms=1_100,
    )
    assert capture.store.pending_count == 0

    capture.observe_mark(
        (position,),
        _mark("94.95", 1_200),
        now_ms=1_200,
    )
    assert capture.store.pending_count == 1

    capture.observe_book(
        (position,),
        _instrument(),
        _book(1_210),
        reference_price=Decimal("95"),
        now_ms=1_210,
    )
    assert capture.store.pending_count == 1
    assert capture.store.record_count == 0

    capture.observe_book(
        (position,),
        _instrument(),
        _book(1_460),
        reference_price=Decimal("94.85"),
        now_ms=1_460,
    )

    assert capture.error is None
    assert capture.store.pending_count == 0
    assert capture.store.record_count == 1

    restored = OriginalStopBookEvidenceStore(root)
    evidence = restored.evidence_for(plan.plan_id)
    assert evidence is not None
    assert evidence.crossing.original_stop == Decimal("95")
    assert (
        evidence.crossing.crossing_mark_price
        == Decimal("94.95")
    )
    assert (
        evidence.pending.plan_book_event_key
        == "book:1210"
    )
    assert evidence.reference_price == Decimal("95")
    assert (
        evidence.execution_book_event_key
        == "book:1460"
    )
    assert (
        evidence.execution_book_received_ms
        == 1_460
    )
    assert (
        evidence.pending.plan_book_source
        == "hyperliquid-mainnet-ws"
    )
    assert evidence.pending.instrument_sz_decimals == 2
    assert (
        evidence.pending.instrument_venue_max_leverage
        == Decimal("20")
    )
    assert tuple(
        level.price for level in evidence.bids
    ) == (
        Decimal("94.9"),
        Decimal("94.8"),
    )
    rebuilt = evidence.book_event()
    assert rebuilt.kind is StreamKind.L2_BOOK
    assert (
        rebuilt.payload["bids"][0]["px"]
        == Decimal("94.9")
    )
    plan_spec = evidence.plan_instrument_spec()
    execution_spec = evidence.execution_instrument_spec()
    assert plan_spec.size_quantum == Decimal("0.01")
    assert plan_spec.metadata_received_at_ms == 800
    assert execution_spec.size_quantum == Decimal("0.01")
    assert execution_spec.metadata_received_at_ms == 800


def test_transient_crossing_recovers_before_book_and_does_not_plan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stop-books"
    plan = _plan()
    position = _position(plan)
    capture = _capture(root, plan)

    capture.observe_mark(
        (position,),
        _mark("94.9", 1_200),
        now_ms=1_200,
    )
    assert capture.store.pending_count == 1

    capture.observe_mark(
        (position,),
        _mark("95.2", 1_300),
        now_ms=1_300,
    )
    assert capture.store.pending_count == 0

    capture.observe_book(
        (position,),
        _instrument(),
        _book(1_500),
        reference_price=Decimal("95.1"),
        now_ms=1_500,
    )
    assert capture.error is None
    assert capture.store.record_count == 0


def test_latest_crossing_before_plan_sets_action_timestamp(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stop-books"
    plan = _plan()
    position = _position(plan)
    capture = _capture(root, plan)

    capture.observe_mark(
        (position,),
        _mark("94.95", 1_200),
        now_ms=1_200,
    )
    capture.observe_mark(
        (position,),
        _mark("94.8", 1_300),
        now_ms=1_300,
    )
    pending = capture.store.pending_for(plan.plan_id)
    assert pending is not None
    assert (
        pending.crossing.crossing_mark_event_key
        == "mark:1300"
    )

    capture.observe_book(
        (position,),
        _instrument(),
        _book(1_310),
        reference_price=Decimal("94.9"),
        now_ms=1_310,
    )
    capture.observe_book(
        (position,),
        _instrument(),
        _book(1_560),
        reference_price=Decimal("94.85"),
        now_ms=1_560,
    )

    evidence = capture.store.evidence_for(plan.plan_id)
    assert evidence is not None
    assert (
        evidence.crossing.crossing_mark_received_ms
        == 1_300
    )
    assert (
        evidence.pending.plan_book_event_key
        == "book:1310"
    )
    assert (
        evidence.execution_book_event_key
        == "book:1560"
    )


def test_staged_stop_plan_survives_mark_recovery(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stop-books"
    plan = _plan()
    position = _position(plan)
    capture = _capture(root, plan)

    capture.observe_mark(
        (position,),
        _mark("94.9", 1_200),
        now_ms=1_200,
    )
    capture.observe_book(
        (position,),
        _instrument(),
        _book(1_210),
        reference_price=Decimal("95"),
        now_ms=1_210,
    )
    pending = capture.store.pending_for(plan.plan_id)
    assert pending is not None
    assert pending.plan_staged is True

    capture.observe_mark(
        (position,),
        _mark("95.4", 1_300),
        now_ms=1_300,
    )
    pending = capture.store.pending_for(plan.plan_id)
    assert pending is not None
    assert pending.plan_staged is True
    assert (
        pending.crossing.crossing_mark_event_key
        == "mark:1200"
    )

    capture.observe_book(
        (position,),
        _instrument(),
        _book(1_460),
        reference_price=Decimal("95.2"),
        now_ms=1_460,
    )
    evidence = capture.store.evidence_for(plan.plan_id)
    assert evidence is not None
    assert (
        evidence.pending.plan_book_event_key
        == "book:1210"
    )
    assert (
        evidence.crossing.crossing_mark_event_key
        == "mark:1200"
    )


def test_same_book_can_create_and_execute_plan_after_latency(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stop-books"
    plan = _plan()
    position = _position(plan)
    capture = _capture(root, plan)

    capture.observe_mark(
        (position,),
        _mark("94.9", 1_200),
        now_ms=1_200,
    )
    capture.observe_book(
        (position,),
        _instrument(),
        _book(1_500),
        reference_price=Decimal("94.95"),
        now_ms=1_500,
    )

    evidence = capture.store.evidence_for(plan.plan_id)
    assert evidence is not None
    assert (
        evidence.pending.plan_book_event_key
        == evidence.execution_book_event_key
    )
    assert evidence.reference_price == Decimal("94.95")


def test_pending_plan_survives_restart_before_execution_book(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stop-books"
    plan = _plan()
    position = _position(plan)
    first = _capture(root, plan)

    first.observe_mark(
        (position,),
        _mark("94.9", 1_200),
        now_ms=1_200,
    )
    first.observe_book(
        (position,),
        _instrument(),
        _book(1_210),
        reference_price=Decimal("95"),
        now_ms=1_210,
    )
    pending = first.store.pending_for(plan.plan_id)
    assert pending is not None
    assert pending.plan_staged is True

    restored = _capture(root, plan)
    restored.observe_book(
        (position,),
        _instrument(),
        _book(1_460),
        reference_price=Decimal("94.8"),
        now_ms=1_460,
    )

    assert restored.error is None
    assert restored.store.pending_count == 0
    evidence = restored.store.evidence_for(plan.plan_id)
    assert evidence is not None
    assert (
        evidence.pending.plan_book_event_key
        == "book:1210"
    )
    assert evidence.reference_price == Decimal("95")
    assert (
        evidence.execution_book_event_key
        == "book:1460"
    )


def test_short_crossing_captures_execution_book(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stop-books"
    plan = _plan(side=OrderSide.SELL)
    position = _position(
        plan,
        side=PositionSide.SHORT,
    )
    capture = _capture(root, plan)

    capture.observe_mark(
        (position,),
        _mark("105.1", 1_200),
        now_ms=1_200,
    )
    capture.observe_book(
        (position,),
        _instrument(),
        _book(1_500),
        reference_price=Decimal("105.05"),
        now_ms=1_500,
    )

    evidence = capture.store.evidence_for(plan.plan_id)
    assert evidence is not None
    assert evidence.crossing.direction == "short"
    assert (
        evidence.crossing.crossing_mark_price
        == Decimal("105.1")
    )
    assert evidence.asks[0].price == Decimal("95.1")


def test_capture_is_fail_open_when_opening_plan_is_missing(
    tmp_path: Path,
) -> None:
    store = OriginalStopBookEvidenceStore(
        tmp_path / "stop-books"
    )
    plan = _plan()
    capture = OriginalStopBookCapture(
        store,
        opening_plan_loader=lambda _plan_id: None,
        config=CONFIG,
    )

    capture.observe_mark(
        (_position(plan),),
        _mark("94", 1_200),
        now_ms=1_200,
    )

    assert capture.error is not None
    assert store.pending_count == 0
    assert store.record_count == 0


def test_immutable_opening_stop_plan_loaded_once_for_all_mark_updates(
    tmp_path: Path,
) -> None:
    plan = _plan()
    position = _position(plan)
    loaded: list[str] = []

    def loader(plan_id: str) -> PaperOrderPlan | None:
        loaded.append(plan_id)
        return plan if plan_id == plan.plan_id else None

    root = tmp_path / "cache"
    capture = OriginalStopBookCapture(
        OriginalStopBookEvidenceStore(root),
        opening_plan_loader=loader,
        config=CONFIG,
    )
    for observed in range(1_100, 1_120):
        capture.observe_mark(
            (position,), _mark("96", observed), now_ms=observed,
        )
    assert loaded == [plan.plan_id]
    assert capture.opening_plan_cache_misses == 1
    assert capture.opening_plan_cache_hits == 19
    # Crossing still uses the actual immutable opening stop and exact
    # original mark, then transitions through the same durable evidence.
    capture.observe_mark(
        (position,), _mark("94", 1_200), now_ms=1_200,
    )
    pending = capture.store.pending_for(plan.plan_id)
    assert pending is not None
    assert pending.crossing.original_stop == plan.stop_price
    assert pending.crossing.crossing_mark_received_ms == 1_200
    assert capture.error is None
    # A new worker/restarted observer cannot borrow an old in-memory plan.
    restored_loads: list[str] = []
    restarted = OriginalStopBookCapture(
        OriginalStopBookEvidenceStore(root),
        opening_plan_loader=lambda key: (
            restored_loads.append(key) or plan
        ),
        config=CONFIG,
    )
    restarted.observe_mark(
        (position,), _mark("93", 1_250), now_ms=1_250,
    )
    assert restored_loads == [plan.plan_id]
    assert restarted.opening_plan_cache_misses == 1


def test_stop_plan_lru_bounds_work_and_never_reuses_another_plan(
    tmp_path: Path,
) -> None:
    plans = {
        plan.plan_id: plan
        for plan in (
            replace(_plan(), risk_decision_id=f"frozen-risk-{n}")
            for n in range(MAX_ORIGINAL_STOP_PLAN_CACHE + 2)
        )
    }
    loaded: list[str] = []

    def loader(key: str) -> PaperOrderPlan | None:
        loaded.append(key)
        return plans.get(key)

    capture = OriginalStopBookCapture(
        OriginalStopBookEvidenceStore(tmp_path / "bounded"),
        opening_plan_loader=loader,
        config=CONFIG,
    )
    for plan in plans.values():
        capture._plan_for(_position(plan))
    assert len(capture._opening_plan_cache) == MAX_ORIGINAL_STOP_PLAN_CACHE
    assert capture.opening_plan_cache_misses == MAX_ORIGINAL_STOP_PLAN_CACHE + 2
    first = next(iter(plans.values()))
    assert capture._plan_for(_position(first)) == first
    assert capture.opening_plan_cache_misses == MAX_ORIGINAL_STOP_PLAN_CACHE + 3
    assert loaded.count(first.plan_id) == 2
    newest = next(reversed(plans.values()))
    assert capture._plan_for(_position(newest)) == newest
    assert capture.opening_plan_cache_hits == 1


def test_wrong_opening_plan_id_fails_closed_and_is_never_cached(
    tmp_path: Path,
) -> None:
    correct_plan = _plan()
    wrong_plan = replace(_plan(), risk_decision_id="another-plan")
    capture = OriginalStopBookCapture(
        OriginalStopBookEvidenceStore(tmp_path / "wrong"),
        opening_plan_loader=lambda key: wrong_plan,
        config=CONFIG,
    )
    capture.observe_mark(
        (_position(correct_plan),),
        _mark("94", 1_200),
        now_ms=1_200,
    )
    assert capture.error is not None
    assert "lineage mismatch" in capture.error
    assert capture.opening_plan_cache_misses == 1
    assert capture.opening_plan_cache_hits == 0
    assert not capture._opening_plan_cache
    assert capture.store.pending_count == 0
    assert capture.store.record_count == 0
