"""Synthetic logic fixtures: none of these events authenticate venue completeness."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.features import EligibilityDecision
from cocomelon.domain.market import FundingRate, MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.research.flow_exhaustion import (
    FlowExhaustionWindow,
    evaluate_flow_exhaustion,
    exit_reason,
    quantity_for_plan,
)

D = Decimal
BTC = MarketId("", "BTC")
T = 720_000


def _event(ms: int, kind: StreamKind, payload: dict[str, object], key: str) -> StreamEvent:
    return StreamEvent(
        kind,
        BTC,
        ms,
        datetime.fromtimestamp(ms / 1000, UTC),
        1,
        "hyperliquid-mainnet-ws",
        key,
        payload,
    )


def _window(short: bool = False) -> FlowExhaustionWindow:
    events: list[StreamEvent] = []
    for i in range(10):
        ms = 30_000 + i * 60_000
        events.append(
            _event(
                ms,
                StreamKind.TRADE,
                {"price": D("100"), "size": D("1"), "side": "B", "tid": i},
                f"trade-{i}",
            )
        )
    for ms in range(630_000, T + 1, 1000):
        mid = D("100") - D(ms - 630_000) / D("59000") * D("0.6")
        if ms >= 690_000:
            mid = D("99.5")
        if short:
            mid = D("200") - mid
            if ms >= 690_000:
                mid = D("100.49")
        bids = ({"px": mid - D(".01"), "sz": D("100") if short else D("1")},)
        asks = ({"px": mid + D(".01"), "sz": D("1") if short else D("100")},)
        if ms >= 690_000:
            if short:
                asks += ({"px": D("100.65"), "sz": D("2")},)
            else:
                bids += ({"px": D("99.35"), "sz": D("2")},)
        events.append(_event(ms, StreamKind.L2_BOOK, {"bids": bids, "asks": asks}, f"book-{ms}"))
    for i in range(20):
        ms = 632_000 + i * 3000
        events.append(
            _event(
                ms,
                StreamKind.TRADE,
                {
                    "price": D("100"),
                    "size": D("10"),
                    "side": "B" if short else "A",
                    "tid": 100 + i,
                },
                f"pressure-{i}",
            )
        )
    for i in range(4):
        events.append(
            _event(
                691_000 + i * 1000,
                StreamKind.TRADE,
                {
                    "price": D("100.65") if short else D("99.35"),
                    "size": D("1"),
                    "side": "B" if short else "A",
                    "tid": 200 + i,
                },
                f"absorption-{i}",
            )
        )
    for i in range(6):
        events.append(
            _event(
                712_000 + i * 1000,
                StreamKind.TRADE,
                {
                    "price": D("100.5") if short else D("99.5"),
                    "size": D("1"),
                    "side": "A" if short else "B",
                    "tid": 300 + i,
                },
                f"response-{i}",
            )
        )
    # Fixture assembly only; the policy must NEVER sort its supplied source events.
    events.sort(key=lambda event: event.receive_time)
    funding = FundingRate(BTC, 0, D(".0001"), D("0"), "hyperliquid-mainnet-info", T, 1)
    return FlowExhaustionWindow(
        BTC, T, tuple(events), True, EligibilityDecision(BTC, True, True, ()), funding
    )


def _change(window: FlowExhaustionWindow, key: str, **fields: object) -> FlowExhaustionWindow:
    return replace(
        window,
        events=tuple(replace(e, **fields) if e.event_key == key else e for e in window.events),
    )


def _payload(window: FlowExhaustionWindow, key: str, **fields: object) -> FlowExhaustionWindow:
    event = next(e for e in window.events if e.event_key == key)
    return _change(window, key, payload={**event.payload, **fields})


def _reject(window: FlowExhaustionWindow, reason: str | None = None) -> None:
    result = evaluate_flow_exhaustion(window)
    assert result.decision.direction is Direction.NO_TRADE
    assert result.stop is None and result.target is None and result.entry is None
    assert result.decision.reason_codes
    if reason:
        assert reason in result.decision.reason_codes


@pytest.mark.parametrize(
    "short,direction,entry,stop",
    [
        (False, Direction.LONG, "99.51", "99.3006"),
        (True, Direction.SHORT, "100.48", "100.7006"),
    ],
)
def test_full_mechanism_mirrors_and_uses_executable_quote_and_mid_stop(
    short: bool,
    direction: Direction,
    entry: str,
    stop: str,
) -> None:
    plan = evaluate_flow_exhaustion(_window(short))
    assert plan.decision.direction is direction
    assert plan.entry == D(entry) and plan.target == D("100") and plan.stop == D(stop)
    assert plan.expires_at_ms == T + 2000
    assert plan.cost_bps == D("21") + D(".02") / D("100.49" if short else "99.5") * 10000
    assert plan.decision.invalidation_price == plan.stop
    assert len(plan.evidence_digest) == 64


def test_receipt_and_exchange_provenance_change_evidence_digest() -> None:
    window = _window()
    before = evaluate_flow_exhaustion(window)
    changed = evaluate_flow_exhaustion(_change(window, "trade-0", exchange_time_ms=29_999))
    assert before.evidence_digest != changed.evidence_digest
    assert before.decision.feature_snapshot_id != changed.decision.feature_snapshot_id


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("coverage_complete", False, "incomplete_external_coverage"),
        ("funding", None, "funding_unavailable"),
        ("decision_time_ms", T + 1, "off_decision_grid"),
        ("market", MarketId("xyz", "BTC"), "native_market_required"),
    ],
)
def test_missing_required_obligations_reject(field: str, value: object, reason: str) -> None:
    _reject(replace(_window(), **{field: value}), reason)


def test_ordinary_eligibility_veto_is_independent() -> None:
    _reject(
        replace(_window(), eligibility=EligibilityDecision(BTC, True, False, ("depth",))),
        "ordinary_eligibility_failed",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"funding_rate": D("NaN")},
        {"time_ms": 3_600_000},
        {"received_at_ms": T + 1},
        {"source": "hyperliquid-testnet-info"},
        {"market": MarketId("", "ETH")},
    ],
)
def test_invalid_funding_cannot_be_zeroed(change: dict[str, object]) -> None:
    window = _window()
    assert window.funding is not None
    _reject(replace(window, funding=replace(window.funding, **change)))


def test_missing_baseline_minute_and_pressure_count_reject() -> None:
    window = _window()
    _reject(
        replace(window, events=tuple(e for e in window.events if e.event_key != "trade-3")),
        "baseline_minute_missing",
    )
    _reject(
        replace(
            window,
            events=tuple(e for e in window.events if e.event_key != "pressure-3"),
        ),
        "pressure_insufficient",
    )


def test_pressure_notional_and_dominance_are_separate_requirements() -> None:
    window = _window()
    small = replace(
        window,
        events=tuple(
            replace(e, payload={**e.payload, "size": D(".001")})
            if e.event_key.startswith("pressure-")
            else e
            for e in window.events
        ),
    )
    _reject(small, "pressure_insufficient")
    mixed = replace(
        window,
        events=tuple(
            replace(e, payload={**e.payload, "side": "B"})
            if e.event_key in {f"pressure-{i}" for i in range(10)}
            else e
            for e in window.events
        ),
    )
    _reject(mixed, "pressure_not_dominant")


def test_wrong_signed_displacement_rejects_even_high_notional() -> None:
    window = _window()
    wrong = replace(
        window,
        events=tuple(
            replace(e, payload={**e.payload, "side": "B"})
            if e.event_key.startswith("pressure-")
            else e
            for e in window.events
        ),
    )
    _reject(wrong, "displacement_insufficient")


def test_insufficient_reversal_and_confirmation_new_extreme_reject() -> None:
    window = _window()
    book = {
        "bids": ({"px": D("99.39"), "sz": D("2")},),
        "asks": ({"px": D("99.41"), "sz": D("100")},),
    }
    _reject(_change(window, "book-720000", payload=book), "reversal_insufficient")
    breach = {
        "bids": ({"px": D("99.2"), "sz": D("2")},),
        "asks": ({"px": D("99.22"), "sz": D("100")},),
    }
    _reject(_change(window, "book-700000", payload=breach), "confirmation_new_extreme")


def test_static_imbalance_without_same_price_band_recovery_rejects() -> None:
    window = _window()
    _reject(
        _payload(window, "book-720000", bids=({"px": D("99.49"), "sz": D("1000")},)),
        "fixed_band_not_recovered",
    )


def test_original_side_execution_must_be_inside_fixed_band() -> None:
    window = _window()
    outside = replace(
        window,
        events=tuple(
            replace(e, payload={**e.payload, "price": D("99.5")})
            if e.event_key.startswith("absorption-")
            else e
            for e in window.events
        ),
    )
    _reject(outside, "fixed_band_execution_insufficient")
    wrong_side = replace(
        window,
        events=tuple(
            replace(e, payload={**e.payload, "side": "B"})
            if e.event_key.startswith("absorption-")
            else e
            for e in window.events
        ),
    )
    _reject(wrong_side, "fixed_band_execution_insufficient")


def test_last_ten_seconds_need_count_and_opposing_share() -> None:
    window = _window()
    _reject(
        replace(
            window,
            events=tuple(
                e for e in window.events if e.event_key not in ("response-0", "response-1")
            ),
        ),
        "opposing_response_insufficient",
    )
    mixed = replace(
        window,
        events=tuple(
            replace(e, payload={**e.payload, "side": "A"})
            if e.event_key in ("response-0", "response-1", "response-2")
            else e
            for e in window.events
        ),
    )
    _reject(mixed, "opposing_response_insufficient")


def test_spread_and_after_cost_hurdle_reject() -> None:
    window = _window()
    _reject(
        _payload(window, "book-720000", asks=({"px": D("99.6"), "sz": D("100")},)),
        "spread_too_wide",
    )
    assert window.funding is not None
    _reject(
        replace(window, funding=replace(window.funding, funding_rate=D(".001"))),
        "target_room_insufficient",
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"exchange_time_ms": None},
        {"exchange_time_ms": 30_001},
        {"exchange_time_ms": 27_999},
        {"source": "hyperliquid-testnet-ws"},
        {"schema_version": 2},
        {"market": MarketId("", "ETH")},
    ],
)
def test_invalid_original_event_provenance_rejects(fields: dict[str, object]) -> None:
    _reject(_change(_window(), "trade-0", **fields))


@pytest.mark.parametrize(
    "fields",
    [
        {"price": D("NaN")},
        {"price": D("0")},
        {"size": D("-1")},
        {"side": "unknown"},
        {"tid": True},
        {"tid": -1},
    ],
)
def test_invalid_trade_payload_rejects(fields: dict[str, object]) -> None:
    _reject(_payload(_window(), "trade-0", **fields))


def test_duplicate_trade_identity_rejects_even_with_new_key() -> None:
    window = _window()
    events = list(window.events)
    events.insert(1, replace(events[0], event_key="different-key"))
    _reject(replace(window, events=tuple(events)), "duplicate_trade")
    events[1] = events[0]
    _reject(replace(window, events=tuple(events)), "duplicate_event")


def test_receipt_regression_and_per_stream_exchange_regression_are_not_sorted_away() -> None:
    window = _window()
    events = list(window.events)
    events[0], events[1] = events[1], events[0]
    _reject(replace(window, events=tuple(events)), "receipt_clock_regression")
    _reject(
        _change(window, "response-1", exchange_time_ms=711_999),
        "exchange_clock_regression",
    )


def test_exchange_interleaving_across_trade_and_book_streams_is_valid() -> None:
    window = _change(_window(), "response-0", exchange_time_ms=711_500)
    assert evaluate_flow_exhaustion(window).decision.direction is Direction.LONG


def test_future_receipt_is_rejected_without_truncation() -> None:
    window = _window()
    event = replace(window.events[-1], receive_time=datetime.fromtimestamp((T + 1) / 1000, UTC))
    _reject(replace(window, events=window.events[:-1] + (event,)), "future_receipt")


@pytest.mark.parametrize(
    "drop",
    [
        {"book-630000", "book-631000"},
        {"book-650000", "book-651000"},
        {"book-719000", "book-720000"},
    ],
)
def test_book_coverage_requires_start_interior_and_end(drop: set[str]) -> None:
    window = _window()
    _reject(
        replace(window, events=tuple(e for e in window.events if e.event_key not in drop)),
        "incomplete_book_coverage",
    )


def test_last_exchange_book_age_is_checked_as_well_as_receipt() -> None:
    window = _window()
    # Equal exchange clocks remain monotonic; final latest snapshot is 2s exchange-old.
    window = _payload(window, "book-719000", asks=({"px": D("99.51"), "sz": D("101")},))
    window = _change(window, "book-719000", exchange_time_ms=718_000)
    window = _payload(window, "book-720000", asks=({"px": D("99.51"), "sz": D("102")},))
    window = _change(window, "book-720000", exchange_time_ms=718_000)
    _reject(window, "incomplete_book_coverage")


@pytest.mark.parametrize(
    "payload",
    [
        {"bids": (), "asks": ({"px": D("100"), "sz": D("1")},)},
        {
            "bids": ({"px": D("101"), "sz": D("1")},),
            "asks": ({"px": D("100"), "sz": D("1")},),
        },
        {
            "bids": ({"px": D("99"), "sz": D("NaN")},),
            "asks": ({"px": D("100"), "sz": D("1")},),
        },
    ],
)
def test_invalid_books_reject(payload: dict[str, object]) -> None:
    _reject(_change(_window(), "book-650000", payload=payload))


def test_sizing_reserves_cost_and_floors_quantity() -> None:
    plan = evaluate_flow_exhaustion(_window())
    qty = quantity_for_plan(
        plan,
        equity=D("10000"),
        executable_entry=D("99.51"),
        contra_depth_25bp=D("100000"),
        sz_decimals=3,
        now_ms=T,
    )
    # $10 / ($.2094 stop + $.228973 reserve) = 22.811..., floor to .001.
    assert qty == D("22.811")
    assert qty * (D("99.51") - D("99.3006") + D("99.51") * plan.cost_bps / 10000) <= 10
    assert quantity_for_plan(
        plan,
        equity=D("10000"),
        executable_entry=D("99.51"),
        contra_depth_25bp=D("100"),
        sz_decimals=3,
        now_ms=T,
    ) == D(".050")
    assert quantity_for_plan(
        plan,
        equity=D("10000"),
        executable_entry=D("99.4"),
        contra_depth_25bp=D("1000000"),
        sz_decimals=3,
        now_ms=T,
    ) == D("25.150")


@pytest.mark.parametrize(
    "changes",
    [
        {"now_ms": T + 2000},
        {"now_ms": T - 1},
        {"equity": D("NaN")},
        {"equity": D("0")},
        {"contra_depth_25bp": D("-1")},
        {"sz_decimals": -1},
        {"executable_entry": D("99.3")},
        {"executable_entry": D("99.6")},
    ],
)
def test_sizing_rejects_invalid_expired_or_worsened_unqualified_entry(
    changes: dict[str, object],
) -> None:
    plan = evaluate_flow_exhaustion(_window())
    args: dict[str, object] = {
        "equity": D("10000"),
        "executable_entry": D("99.51"),
        "contra_depth_25bp": D("100000"),
        "sz_decimals": 3,
        "now_ms": T,
    }
    assert quantity_for_plan(plan, **{**args, **changes}) == 0


@pytest.mark.parametrize("short,stop,target", [(False, "99.2", "100"), (True, "100.8", "100")])
def test_exit_priority_is_stop_then_target_then_timeout(
    short: bool, stop: str, target: str
) -> None:
    plan = evaluate_flow_exhaustion(_window(short))
    assert (
        exit_reason(plan, executable_price=D(stop), first_fill_ms=T, now_ms=T + 1_800_000) == "stop"
    )
    assert (
        exit_reason(plan, executable_price=D(target), first_fill_ms=T, now_ms=T + 1_800_000)
        == "target"
    )
    assert (
        exit_reason(plan, executable_price=plan.entry, first_fill_ms=T, now_ms=T + 1_800_000)
        == "max_hold"
    )
    assert (
        exit_reason(plan, executable_price=plan.entry, first_fill_ms=T, now_ms=T + 1_799_999)
        is None
    )


def test_missing_executable_quote_cannot_pretend_to_fill_exit() -> None:
    plan = evaluate_flow_exhaustion(_window())
    assert (
        exit_reason(plan, executable_price=None, first_fill_ms=T, now_ms=T + 1_800_000)
        == "max_hold"
    )
    with pytest.raises(ValueError):
        exit_reason(plan, executable_price=D("NaN"), first_fill_ms=T, now_ms=T + 1)


def test_depth_recovery_must_precede_opposing_response() -> None:
    window = _window()
    window = replace(
        window,
        events=tuple(
            replace(e, payload={**e.payload, "bids": ({"px": D("99.49"), "sz": D("1000")},)})
            if e.kind is StreamKind.L2_BOOK
            and 690_000 <= int(e.receive_time.timestamp() * 1000) <= 710_000
            else e
            for e in window.events
        ),
    )
    _reject(window, "fixed_band_not_recovered")


def test_original_side_band_execution_must_precede_response() -> None:
    window = _window()
    events = [
        replace(e, receive_time=datetime.fromtimestamp(711, UTC), exchange_time_ms=711_000)
        if e.event_key.startswith("absorption-")
        else e
        for e in window.events
    ]
    events.sort(key=lambda event: event.receive_time)  # constructing chronological fixture
    _reject(replace(window, events=tuple(events)), "fixed_band_execution_insufficient")


def test_truthy_nonboolean_eligibility_cannot_approve_exposure() -> None:
    window = _window()
    _reject(
        replace(window, eligibility=EligibilityDecision(BTC, 1, "yes", ())),
        "ordinary_eligibility_failed",
    )


def test_trade_identifier_can_recur_in_different_exchange_block() -> None:
    window = _payload(_window(), "response-1", tid=300)
    assert evaluate_flow_exhaustion(window).decision.direction is Direction.LONG


def test_policy_digest_binds_exact_frozen_protocol_bytes() -> None:
    import hashlib
    from pathlib import Path

    from cocomelon.research.flow_exhaustion import PROTOCOL_SHA256

    protocol = (
        Path(__file__).resolve().parents[1]
        / "research/experiments/flow-exhaustion-v1/protocol.json"
    )
    assert hashlib.sha256(protocol.read_bytes()).hexdigest() == PROTOCOL_SHA256


def test_caller_decimal_precision_and_rounding_cannot_change_decision_or_cap() -> None:
    from decimal import ROUND_UP, localcontext

    window = _window()
    expected = evaluate_flow_exhaustion(window)
    args = {
        "equity": D("10000"),
        "executable_entry": D("99.51"),
        "contra_depth_25bp": D("100000"),
        "sz_decimals": 3,
        "now_ms": T,
    }
    expected_qty = quantity_for_plan(expected, **args)
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_UP
        actual = evaluate_flow_exhaustion(window)
        assert actual == expected
        assert quantity_for_plan(expected, **args) == expected_qty
