from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.continuous_paper_capacity_release_books import (
    CapacityReleaseBookCapture,
    CapacityReleaseBookEvidenceError,
    CapacityReleaseBookRegistration,
    CapacityReleaseBookStore,
)

BTC = MarketId("", "BTC")
SOL = MarketId("", "SOL")


def _position() -> PaperPosition:
    return PaperPosition(
        market=BTC,
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        opening_plan_id="holder-plan-btc",
        opened_at_ms=500,
        updated_at_ms=900,
        correlation_bucket="majors",
        planned_risk=Decimal("20"),
        venue_max_leverage=Decimal("20"),
        latest_mark=Decimal("101"),
    )


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=BTC,
        sz_decimals=3,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="hyperliquid-mainnet-meta",
    )


def _book(
    *,
    received_ms: int,
    exchange_ms: int | None = None,
) -> StreamEvent:
    resolved_exchange = (
        received_ms - 10 if exchange_ms is None else exchange_ms
    )
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=BTC,
        exchange_time_ms=resolved_exchange,
        receive_time=datetime.fromtimestamp(
            received_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"book:BTC:{resolved_exchange}:{received_ms}",
        payload={
            "bids": (
                {
                    "px": Decimal("100.9"),
                    "sz": Decimal("2"),
                    "n": 1,
                },
            ),
            "asks": (
                {
                    "px": Decimal("101.1"),
                    "sz": Decimal("3"),
                    "n": 2,
                },
            ),
        },
    )


def _registration() -> CapacityReleaseBookRegistration:
    return CapacityReleaseBookRegistration(
        opportunity_id="opportunity-sol-short-1",
        opportunity_timestamp_ms=1_000,
        opportunity_market="SOL",
        opportunity_direction="short",
        release_market="BTC",
        release_direction="long",
        release_correlation_bucket="majors",
        strategy_decision_id="strategy-sol",
        risk_decision_id="risk-sol",
    )


def _store(root: Path) -> CapacityReleaseBookStore:
    return CapacityReleaseBookStore(
        root,
        capture_started_at_ms=900,
        latency_ms=250,
        max_book_age_ms=1_000,
        execution_config=PaperExecutionConfig(),
    )


def test_release_books_stage_plan_then_capture_latency_eligible_execution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "capacity-release-books"
    store = _store(root)
    registration = _registration()

    assert store.register(registration) is True
    assert store.register(registration) is False
    assert (
        store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=1_100),
            reference_price=Decimal("101"),
            now_ms=1_100,
        )
        == 0
    )
    pending = store.iter_pending()
    assert len(pending) == 1
    assert pending[0].registration == registration
    assert pending[0].release_opening_plan_id == "holder-plan-btc"
    assert pending[0].plan_observed_at_ms == 1_100
    assert pending[0].plan_reference_price == Decimal("101")
    assert pending[0].execution_config == {
        "config_version": "phase7-v1",
        "latency_ms": 250,
        "max_book_age_ms": 1000,
        "max_asset_ctx_age_ms": 5000,
        "max_position_age_ms": None,
        "funding_reconciliation_grace_ms": 300000,
        "max_ioc_slippage_bps": "25",
        "taker_fee_rate": "0.00045",
        "fee_schedule_id": "hyperliquid-native-base-2026-08-23",
        "native_perp_min_notional": "10",
        "paper_max_gross_leverage": "3",
    }
    assert store.iter_records() == ()

    assert (
        store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=1_300),
            reference_price=Decimal("101"),
            now_ms=1_300,
        )
        == 0
    )
    assert len(store.iter_pending()) == 1

    assert (
        store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=1_360),
            reference_price=Decimal("101"),
            now_ms=1_360,
        )
        == 1
    )
    records = store.iter_records()
    assert len(records) == 1
    evidence = records[0]
    assert evidence.registration == registration
    assert evidence.release_opening_plan_id == "holder-plan-btc"
    assert evidence.release_position == _position()
    assert evidence.pending.plan_book_event == _book(received_ms=1_100)
    assert evidence.pending.plan_instrument == _instrument()
    assert evidence.execution_book_event == _book(received_ms=1_360)
    assert evidence.execution_instrument == _instrument()
    assert store.iter_pending() == ()


def test_release_plan_survives_restart_before_execution_book(
    tmp_path: Path,
) -> None:
    root = tmp_path / "capacity-release-books"
    first = _store(root)
    first.register(_registration())
    first.capture(
        positions=(_position(),),
        instrument=_instrument(),
        book=_book(received_ms=1_100),
        reference_price=Decimal("101"),
        now_ms=1_100,
    )

    restored = CapacityReleaseBookStore(
        root,
        capture_started_at_ms=50_000,
        latency_ms=250,
        max_book_age_ms=1_000,
        execution_config=PaperExecutionConfig(),
    )
    assert restored.capture_started_at_ms == 900
    assert len(restored.iter_pending()) == 1
    assert (
        restored.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=1_360),
            reference_price=Decimal("101"),
            now_ms=1_360,
        )
        == 1
    )
    assert len(restored.iter_records()) == 1
    assert restored.iter_pending() == ()


def test_release_books_never_accept_stale_plan_or_execution_book(
    tmp_path: Path,
) -> None:
    plan_store = _store(tmp_path / "late-plan")
    plan_store.register(_registration())
    assert (
        plan_store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=2_001, exchange_ms=2_000),
            reference_price=Decimal("101"),
            now_ms=2_001,
        )
        == 0
    )
    assert plan_store.iter_pending() == ()
    plan_summary = plan_store.summary(now_ms=2_001)
    assert plan_summary["missed_plan"] == 1
    assert plan_summary["captured"] == 0

    execution_store = _store(tmp_path / "late-execution")
    execution_store.register(_registration())
    execution_store.capture(
        positions=(_position(),),
        instrument=_instrument(),
        book=_book(received_ms=1_100),
        reference_price=Decimal("101"),
        now_ms=1_100,
    )
    assert (
        execution_store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=2_351, exchange_ms=2_350),
            reference_price=Decimal("101"),
            now_ms=2_351,
        )
        == 0
    )
    execution_summary = execution_store.summary(now_ms=2_351)
    assert execution_summary["missed_execution"] == 1
    assert execution_summary["captured"] == 0


def test_release_plan_rejects_pre_opportunity_exchange_timestamp(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "capacity-release-books")
    store.register(_registration())

    assert (
        store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=1_100, exchange_ms=990),
            reference_price=Decimal("101"),
            now_ms=1_100,
        )
        == 0
    )
    assert store.iter_pending() == ()
    assert store.iter_records() == ()


def test_release_book_capture_registers_exact_causal_release_positions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _store(tmp_path / "capacity-release-books")
    capture = CapacityReleaseBookCapture(store)
    monkeypatch.setattr(
        "cocomelon.research.continuous_paper_capacity_release_books."
        "single_position_capacity_release_risk_positions",
        lambda request, _reasons: (request.open_positions[0],),
    )
    risk_decision = SimpleNamespace(
        approved=False,
        reason_codes=("correlation_bucket_exhausted",),
        risk_decision_id="risk-sol",
    )
    request = SimpleNamespace(
        timestamp_ms=1_000,
        market=SOL,
        direction=Direction.SHORT,
        correlation_bucket="majors",
        strategy_decision_id="strategy-sol",
        open_positions=(
            SimpleNamespace(
                market=BTC,
                direction=Direction.LONG,
                correlation_bucket="majors",
            ),
            SimpleNamespace(
                market=MarketId("", "ETH"),
                direction=Direction.SHORT,
                correlation_bucket="alts",
            ),
            SimpleNamespace(
                market=SOL,
                direction=Direction.LONG,
                correlation_bucket="majors",
            ),
        ),
    )
    trace = SimpleNamespace(
        submission=SimpleNamespace(risk_decision=risk_decision),
        risk_request=request,
    )

    capture.register_from_trace(  # type: ignore[arg-type]
        trace,
        opportunity_id="canonical-opportunity-id",
    )

    assert capture.error is None
    registrations = store.iter_registrations()
    assert len(registrations) == 1
    registration = registrations[0]
    assert registration.opportunity_id == "canonical-opportunity-id"
    assert registration.release_market == "BTC"
    assert registration.release_direction == "long"


def test_release_book_capture_accepts_exact_aggregate_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _store(tmp_path / "capacity-release-books")
    capture = CapacityReleaseBookCapture(store)
    monkeypatch.setattr(
        "cocomelon.research.continuous_paper_capacity_release_books."
        "single_position_capacity_release_risk_positions",
        lambda request, _reasons: (request.open_positions[0],),
    )
    trace = SimpleNamespace(
        submission=SimpleNamespace(
            risk_decision=SimpleNamespace(
                approved=False,
                reason_codes=("aggregate_risk_exhausted",),
                risk_decision_id="risk-sol",
            )
        ),
        risk_request=SimpleNamespace(
            timestamp_ms=1_000,
            market=SOL,
            direction=Direction.SHORT,
            correlation_bucket="majors",
            strategy_decision_id="strategy-sol",
            open_positions=(
                SimpleNamespace(
                    market=BTC,
                    direction=Direction.LONG,
                    correlation_bucket="btc_beta",
                ),
            ),
        ),
    )

    capture.register_from_trace(  # type: ignore[arg-type]
        trace,
        opportunity_id="aggregate-opportunity-id",
    )

    assert capture.error is None
    registrations = store.iter_registrations()
    assert len(registrations) == 1
    assert registrations[0].opportunity_id == "aggregate-opportunity-id"
    assert registrations[0].release_market == "BTC"
    assert registrations[0].release_correlation_bucket == "btc_beta"


def test_release_book_capture_ignores_non_capacity_rejections(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "capacity-release-books")
    capture = CapacityReleaseBookCapture(store)
    trace = SimpleNamespace(
        submission=SimpleNamespace(
            risk_decision=SimpleNamespace(
                approved=False,
                reason_codes=("below_venue_min_notional",),
                risk_decision_id="risk-sol",
            )
        ),
        risk_request=SimpleNamespace(
            timestamp_ms=1_000,
            market=SOL,
            direction=Direction.SHORT,
            correlation_bucket="majors",
            strategy_decision_id="strategy-sol",
            open_positions=(),
        ),
    )

    capture.register_from_trace(  # type: ignore[arg-type]
        trace,
        opportunity_id="canonical-opportunity-id",
    )

    assert store.iter_registrations() == ()
    assert capture.error is None


def test_hot_l2_registration_cache_is_market_scoped_and_invalidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "capacity-cache"
    store = _store(root)
    primary = _registration()
    other_market = replace(
        primary, opportunity_id="other-release", release_market="SOL",
    )
    assert store.register(primary)
    assert store.register(other_market)

    original = store.iter_registrations
    loaded = [0]

    def audited():
        loaded[0] += 1
        return original()

    monkeypatch.setattr(store, "iter_registrations", audited)
    assert store._registrations_for_capture_market("BTC") == (primary,)
    assert store._registrations_for_capture_market("SOL") == (other_market,)
    assert store._registrations_for_capture_market("ETH") == ()
    assert loaded == [1]

    # Repeated genuine book callbacks must not rescan every unrelated
    # registration file. Candidate matching, staging and evidence remain
    # identical to the existing exact latency causal protocol.
    assert store.capture(
        positions=(_position(),), instrument=_instrument(),
        book=_book(received_ms=1_100),
        reference_price=Decimal("101"), now_ms=1_100,
    ) == 0
    assert store.capture(
        positions=(_position(),), instrument=_instrument(),
        book=_book(received_ms=1_110),
        reference_price=Decimal("101"), now_ms=1_110,
    ) == 0
    assert loaded == [1]
    assert len(store.iter_pending()) == 1
    assert store.capture(
        positions=(_position(),), instrument=_instrument(),
        book=_book(received_ms=1_360),
        reference_price=Decimal("101"), now_ms=1_360,
    ) == 1
    assert loaded == [1]
    assert len(store.iter_records()) == 1

    # An in-process new registration MUST invalidate even on a coarse
    # filesystem clock.
    added = replace(primary, opportunity_id="later-release")
    assert store.register(added)
    assert store._registrations_for_capture_market("BTC") == (
        *tuple(item for item in original() if item.release_market == "BTC"),
    )
    assert loaded == [2]

    # Another exact-store writer publishing a separate atomic file is
    # detected from the directory change, not an inferred market tick.
    outside = _store(root)
    outside.register(replace(primary, opportunity_id="external-release"))
    assert len(store._registrations_for_capture_market("BTC")) == 3
    assert loaded == [3]

    # Sealing/summary always executes an independent full canonical
    # on-disk read rather than trusting the live observer cache.
    store.iter_registrations()
    assert loaded == [4]
    new_worker = _store(root)
    assert len(new_worker.iter_registrations()) == 4
    assert len(new_worker._registrations_for_capture_market("BTC")) == 3


def test_hot_book_cache_cannot_hide_corrupt_registered_evidence_from_audit(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "bad-registration")
    registration = _registration()
    store.register(registration)
    assert store._registrations_for_capture_market("BTC") == (registration,)
    path = store._registration_path(registration.registration_id)
    path.write_text("{not-canonical-JSON", encoding="utf-8")
    # Full independent state review never trusts in-memory book lookup.
    with pytest.raises(CapacityReleaseBookEvidenceError):
        store.iter_registrations()
    with pytest.raises(CapacityReleaseBookEvidenceError):
        store.summary(now_ms=1_400)
    # A worker handoff cannot inherit the volatile cache or claim this as
    # a valid registration source.
    replacement_store = _store(store.root)
    with pytest.raises(CapacityReleaseBookEvidenceError):
        replacement_store._registrations_for_capture_market("BTC")
