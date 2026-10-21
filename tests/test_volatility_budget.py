"""Synthetic policy fixtures prove arithmetic and fail-closed gates, not real source custody."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, localcontext

import pytest

from cocomelon.domain.features import EligibilityDecision
from cocomelon.domain.market import (
    FundingRate,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.strategy import Direction
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.research.volatility_budget import (
    Native8hBar,
    VolatilityBudgetWindow,
    crossing_direction_from_variances,
    evaluate_volatility_budget,
    exit_reason,
    quantity_for_plan,
)

D = Decimal
BTC = MarketId("", "BTC")
DAY = 86_400_000
EIGHT = DAY // 3
T = 100 * DAY + 30_000


def _window(long: bool = False) -> VolatilityBudgetWindow:
    # Last new return spikes for SHORT; a shock leaves the seven-return window for LONG.
    returns = [D(".001") * (1 if i % 2 else -1) for i in range(29)]
    returns[21 if long else 28] = D(".04") if long else D(".08")
    with localcontext() as ctx:
        ctx.prec = 60
        closes = [D("100")]
        for value in returns:
            closes.append(closes[-1] * value.exp())
    bars = []
    midnight = T - 30_000
    for day, close in enumerate(closes):
        for part in range(3):
            start = midnight - 30 * DAY + day * DAY + part * EIGHT
            bars.append(
                Native8hBar(
                    BTC, start, start + EIGHT - 1, close, close, close, close, D("10"), 10, T - 1
                )
            )
    book = StreamEvent(
        StreamKind.L2_BOOK,
        BTC,
        T - 100,
        datetime.fromtimestamp((T - 100) / 1000, UTC),
        1,
        "hyperliquid-mainnet-ws",
        "predecision",
        {
            "bids": ({"px": D("99.99"), "sz": D("1000")},),
            "asks": ({"px": D("100.01"), "sz": D("1000")},),
        },
    )
    meta = PerpMarketMeta(BTC, "BTC", 3, 20, 1, False, False, "cross")
    context = PerpMarketContext(
        BTC, D("100"), D("100"), D("100"), D(".00001"), D("50000"), D("10000000"), D("0"), D("100")
    )
    snapshot = PerpMarketSnapshot(meta, context, "hyperliquid-mainnet-info", T - 100, 1)
    return VolatilityBudgetWindow(
        BTC,
        T,
        tuple(bars),
        book,
        EligibilityDecision(BTC, True, True, ()),
        FundingRate(BTC, T - 100, D(".00001"), D("0"), "hyperliquid-mainnet-info", T - 100, 1),
        snapshot,
    )


def window_at(t: int, short: bool = False, market: MarketId = BTC) -> VolatilityBudgetWindow:
    """Reusable synthetic source fixture; no historical/venue availability claim."""
    window = _window(long=not short)
    delta = t - T
    assert window.book is not None and window.funding is not None and window.snapshot is not None
    snapshot = replace(
        window.snapshot,
        received_at_ms=t - 100,
        meta=replace(window.snapshot.meta, market=market, wire_name=market.wire_name),
        context=replace(window.snapshot.context, market=market),
    )
    return replace(
        window,
        market=market,
        decision_time_ms=t,
        bars=tuple(
            replace(
                bar,
                market=market,
                open_time_ms=bar.open_time_ms + delta,
                native_close_time_ms=bar.native_close_time_ms + delta,
                received_at_ms=t - 1,
            )
            for bar in window.bars
        ),
        book=replace(
            window.book,
            market=market,
            exchange_time_ms=t - 100,
            receive_time=datetime.fromtimestamp((t - 100) / 1000, UTC),
        ),
        eligibility=replace(window.eligibility, market=market),
        funding=replace(window.funding, market=market, time_ms=t - 100, received_at_ms=t - 100),
        snapshot=snapshot,
    )


def _reject(window: VolatilityBudgetWindow, reason: str, *, unknown: bool = False) -> None:
    plan = evaluate_volatility_budget(window)
    assert plan.decision.direction is Direction.NO_TRADE
    assert plan.entry is None and plan.target is None and plan.stop is None
    assert reason in plan.decision.reason_codes
    if unknown:
        assert plan.signal_direction is None


@pytest.mark.parametrize(
    "long,direction,entry", [(False, Direction.SHORT, "99.99"), (True, Direction.LONG, "100.01")]
)
def test_latest_and_prior_sample_windows_generate_crossing_and_frozen_geometry(
    long: bool, direction: Direction, entry: str
) -> None:
    plan = evaluate_volatility_budget(_window(long))
    assert plan.signal_direction is direction and plan.decision.direction is direction
    assert plan.entry == D(entry)
    assert plan.cost_bps == D("23.5")
    assert plan.sigma28 is not None and plan.stop_distance_bps is not None
    assert plan.expires_at_ms == T + 2000
    assert plan.decision.invalidation_price == plan.stop
    assert plan.target is not None and plan.stop is not None
    with localcontext() as ctx:
        ctx.prec = 60
        assert abs(abs(plan.target - plan.entry) - 2 * abs(plan.stop - plan.entry)) < D("1e-45")
    if long:
        assert plan.stop == D("99.0099") and plan.target == D("102.0102")
        assert plan.stop_distance_bps == 100
    else:
        assert plan.stop > plan.entry > plan.target
        assert plan.stop_distance_bps > 100


@pytest.mark.parametrize(
    "pv7,pv28,v7,v28,want",
    [
        ("8", "4", "9", "4", Direction.SHORT),
        ("9", "4", "10", "4", Direction.NO_TRADE),
        ("5", "9", "4", "9", Direction.LONG),
        ("4", "9", "3", "9", Direction.NO_TRADE),
        ("0", "1", "0", "1", Direction.NO_TRADE),
        ("0", "0", "1", "1", None),
        ("1", "1", "1", "0", None),
        ("NaN", "1", "1", "1", None),
    ],
)
def test_squared_rational_crossing_is_inclusive_only_on_current_day(
    pv7: str, pv28: str, v7: str, v28: str, want: Direction | None
) -> None:
    assert (
        crossing_direction_from_variances(
            prior_variance7=D(pv7), prior_variance28=D(pv28), variance7=D(v7), variance28=D(v28)
        )
        is want
    )


def test_missing_zero_denominator_is_unknown_not_false() -> None:
    window = _window()
    flat = tuple(
        replace(bar, open=D("100"), high=D("100"), low=D("100"), close=D("100"))
        for bar in window.bars
    )
    _reject(replace(window, bars=flat), "volatility_unknown", unknown=True)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("missing", "invalid_bar_count"),
        ("duplicate", "invalid_bar_grid"),
        ("reverse", "invalid_bar_grid"),
        ("close", "invalid_bar_grid"),
        ("late", "invalid_bar_receipt"),
        ("early", "invalid_bar_receipt"),
        ("symbol", "invalid_bar_provenance"),
        ("interval", "invalid_bar_provenance"),
        ("source", "invalid_bar_provenance"),
        ("schema", "invalid_bar_provenance"),
        ("zero_volume", "invalid_bar_values"),
        ("zero_count", "invalid_bar_values"),
        ("boolean_count", "invalid_bar_values"),
        ("nan", "invalid_bar_values"),
        ("ohlc", "invalid_bar_values"),
    ],
)
def test_invalid_native_source_never_becomes_known_noncrossing(mutation: str, reason: str) -> None:
    window = _window()
    bars = list(window.bars)
    if mutation == "missing":
        bars.pop()
    elif mutation == "duplicate":
        bars[10] = bars[9]
    elif mutation == "reverse":
        bars.reverse()
    else:
        changes = {
            "close": {"native_close_time_ms": bars[10].native_close_time_ms + 1},
            "late": {"received_at_ms": T + 1},
            "early": {"received_at_ms": bars[10].native_close_time_ms},
            "symbol": {"market": MarketId("", "ETH")},
            "interval": {"interval": "1d"},
            "source": {"source": "unknown"},
            "schema": {"schema_version": 2},
            "zero_volume": {"volume": D("0")},
            "zero_count": {"trade_count": 0},
            "boolean_count": {"trade_count": True},
            "nan": {"close": D("NaN")},
            "ohlc": {"low": bars[10].high + 1},
        }[mutation]
        bars[10] = replace(bars[10], **changes)
    _reject(replace(window, bars=tuple(bars)), reason, unknown=True)


@pytest.mark.parametrize("offset", [-1, 1, 86_400_000])
def test_daily_clock_cannot_be_retimed(offset: int) -> None:
    window = _window()
    reason = "invalid_bar_grid" if offset == DAY else "off_decision_grid"
    _reject(replace(window, decision_time_ms=T + offset), reason, unknown=True)


def test_canonical_close_preserves_native_inclusive_timestamp() -> None:
    window = _window()
    assert window.bars[-1].native_close_time_ms == T - 30_001
    assert window.bars[-1].canonical_close_time_ms == T - 30_000


@pytest.mark.parametrize("coin,dex", [("HYPE", ""), ("BTC", "xyz")])
def test_frozen_scope_rejects_other_native_and_namespaced_markets(coin: str, dex: str) -> None:
    _reject(replace(_window(), market=MarketId(dex, coin)), "outside_frozen_scope", unknown=True)


def test_eligibility_veto_preserves_valid_crossing_for_cooldown() -> None:
    window = _window()
    result = evaluate_volatility_budget(
        replace(window, eligibility=EligibilityDecision(BTC, False, False, ("health",)))
    )
    assert result.decision.direction is Direction.NO_TRADE
    assert result.signal_direction is Direction.SHORT


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("book", None, "book_unavailable"),
        ("snapshot", None, "current_context_unavailable"),
        ("funding", None, "funding_unavailable"),
    ],
)
def test_missing_execution_input_preserves_known_crossing(
    field: str, value: object, reason: str
) -> None:
    window = replace(_window(), **{field: value})
    _reject(window, reason)
    assert evaluate_volatility_budget(window).signal_direction is Direction.SHORT


@pytest.mark.parametrize(
    "exchange_offset,receive_offset,allowed",
    [
        (-1000, -1000, True),
        (-1001, -1000, False),
        (-1001, -1001, False),
        (0, 1, False),
        (1, 0, False),
        (-99, -100, False),
    ],
)
def test_predecision_book_requires_both_clocks_within_one_second(
    exchange_offset: int, receive_offset: int, allowed: bool
) -> None:
    window = _window()
    assert window.book is not None
    book = replace(
        window.book,
        exchange_time_ms=T + exchange_offset,
        receive_time=datetime.fromtimestamp((T + receive_offset) / 1000, UTC),
    )
    result = evaluate_volatility_budget(replace(window, book=book))
    assert (result.decision.direction is Direction.SHORT) is allowed


@pytest.mark.parametrize(
    "mutation", ["volume", "oi", "mark", "oracle", "late", "stale", "delisted"]
)
def test_current_native_eligibility_enforces_frozen_floors(mutation: str) -> None:
    window = _window()
    assert window.snapshot is not None
    snap = window.snapshot
    if mutation == "late":
        snap = replace(snap, received_at_ms=T + 1)
    elif mutation == "stale":
        snap = replace(snap, received_at_ms=T - 5001)
    elif mutation == "delisted":
        snap = replace(snap, meta=replace(snap.meta, is_delisted=True))
    else:
        changes = {
            "volume": {"day_ntl_vlm": D("9999999.99")},
            "oi": {"open_interest": D("49999.99")},
            "mark": {"mark_px": None},
            "oracle": {"oracle_px": D("0")},
        }[mutation]
        snap = replace(snap, context=replace(snap.context, **changes))
    _reject(replace(window, snapshot=snap), "current_context_unavailable")


def test_cost_reserve_rejects_excess_and_uses_absolute_hourly_funding() -> None:
    window = _window()
    assert window.funding is not None
    positive = evaluate_volatility_budget(window)
    negative = evaluate_volatility_budget(
        replace(window, funding=replace(window.funding, funding_rate=D("-.00001")))
    )
    assert positive.cost_bps == negative.cost_bps == D("23.5")
    _reject(
        replace(window, funding=replace(window.funding, funding_rate=D(".0002"))),
        "cost_reserve_exceeded",
    )


def test_policy_arithmetic_is_independent_of_callers_decimal_precision() -> None:
    window = _window()
    expected = evaluate_volatility_budget(window)
    with localcontext() as ctx:
        ctx.prec = 5
        assert evaluate_volatility_budget(window) == expected
        assert (
            crossing_direction_from_variances(
                prior_variance7=D("8.999999"),
                prior_variance28=D("4"),
                variance7=D("9"),
                variance28=D("4"),
            )
            is Direction.SHORT
        )


def test_evidence_digest_binds_receipts_and_actual_source_values() -> None:
    window = _window()
    original = evaluate_volatility_budget(window)
    changed = replace(
        window, bars=(replace(window.bars[0], received_at_ms=T - 2), *window.bars[1:])
    )
    assert evaluate_volatility_budget(changed).evidence_digest != original.evidence_digest
    assert len(original.evidence_digest) == 64


def test_sizing_reserves_stricter_independent_cost_and_rounds_down() -> None:
    plan = evaluate_volatility_budget(_window(True))
    args = dict(
        equity=D("10000"),
        executable_entry=D("100.01"),
        contra_depth_25bp=D("100000"),
        sz_decimals=3,
        now_ms=T + 250,
    )
    assert quantity_for_plan(plan, **args) == D("8.096")
    assert quantity_for_plan(plan, **args, independent_reserve_bps=D("100")) == D("4.999")
    assert quantity_for_plan(plan, **{**args, "contra_depth_25bp": D("10000")}) == D("4.999")
    assert quantity_for_plan(plan, **{**args, "equity": D("9950")}) == 0
    assert quantity_for_plan(plan, **{**args, "now_ms": T + 2000}) == 0
    assert quantity_for_plan(plan, **{**args, "executable_entry": D("103")}) == 0


def test_exit_priority_and_24h_use_first_actual_fill() -> None:
    plan = evaluate_volatility_budget(_window(True))
    args = dict(first_fill_ms=T + 251, now_ms=T + 251 + DAY)
    assert exit_reason(plan, executable_price=plan.stop, **args) == "stop"
    assert exit_reason(plan, executable_price=plan.target, **args) == "target"
    assert exit_reason(plan, executable_price=None, **args) == "max_hold"
    assert exit_reason(plan, executable_price=None, **{**args, "now_ms": T + DAY}) is None


def test_policy_digest_is_bound_to_frozen_bytes() -> None:
    import hashlib
    import json
    from pathlib import Path

    from cocomelon.research.volatility_budget import POLICY, PROTOCOL_SHA256

    path = (
        Path(__file__).resolve().parents[1]
        / "research/experiments/volatility-budget-v1/policy.json"
    )
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PROTOCOL_SHA256
    assert json.loads(raw)["policy_id"] == POLICY


@pytest.mark.parametrize(
    "change",
    [
        dict(only_isolated=True),
        dict(margin_mode="unknown"),
        dict(max_leverage=0),
        dict(margin_table_id=-1),
    ],
)
def test_unsupported_native_margin_fails_even_if_external_eligibility_is_true(
    change: dict[str, object],
) -> None:
    window = _window()
    assert window.snapshot is not None
    snapshot = replace(window.snapshot, meta=replace(window.snapshot.meta, **change))
    _reject(replace(window, snapshot=snapshot), "current_context_unavailable")


def test_canonical_selection_eligibility_survives_later_cost_or_funding_veto() -> None:
    window = _window()
    assert window.funding is not None
    plan = evaluate_volatility_budget(replace(window, funding=None))
    assert plan.current_eligible is True
    assert plan.signal_direction is Direction.SHORT
    expensive = evaluate_volatility_budget(
        replace(window, funding=replace(window.funding, funding_rate=D(".0002")))
    )
    assert expensive.current_eligible is True
    assert expensive.decision.direction is Direction.NO_TRADE
    assert evaluate_volatility_budget(replace(window, book=None)).current_eligible is False


def test_sample_standard_deviation_uses_28_returns_with_ddof_one() -> None:
    plan = evaluate_volatility_budget(_window())
    # Latest28 returns:14*(+.001),13*(-.001),1*(+.08).
    # Their sum=.081 and sum of squares=.006427; variance=(.006427-.081^2/28)/27.
    assert plan.sigma28 is not None
    assert abs(plan.sigma28 - D("0.01514458535610881650610166182275982529914")) < D("1e-40")


def test_known_noncrossing_is_distinct_from_unknown() -> None:
    window = _window()
    # Geometric, gently alternating daily returns keep q close to1 on both dates.
    with localcontext() as ctx:
        ctx.prec = 60
        a, b = D("100"), D("100") * D(".001").exp()
    bars = tuple(
        replace(
            bar,
            open=(a if i // 3 % 2 else b),
            high=(a if i // 3 % 2 else b),
            low=(a if i // 3 % 2 else b),
            close=(a if i // 3 % 2 else b),
        )
        for i, bar in enumerate(window.bars)
    )
    plan = evaluate_volatility_budget(replace(window, bars=bars))
    assert plan.signal_direction is Direction.NO_TRADE
    assert plan.decision.reason_codes == ("no_crossing",)


@pytest.mark.parametrize(
    "spread,size,reason",
    [(D(".06"), D("1000"), "spread_too_wide"), (D(".01"), D("1"), "visible_depth_insufficient")],
)
def test_book_eligibility_enforces_spread_and_both_visible_sides(
    spread: Decimal, size: Decimal, reason: str
) -> None:
    window = _window()
    assert window.book is not None
    book = replace(
        window.book,
        payload={
            "bids": ({"px": D("100") - spread, "sz": size},),
            "asks": ({"px": D("100") + spread, "sz": D("1000")},),
        },
    )
    _reject(replace(window, book=book), reason)


def test_cost_ceiling_is_inclusive_and_reserve_not_an_expected_return() -> None:
    window = _window(True)
    assert window.funding is not None
    plan = evaluate_volatility_budget(
        replace(window, funding=replace(window.funding, funding_rate=D(".000116")))
    )
    assert plan.cost_bps == 50
    assert plan.decision.direction is Direction.LONG
    assert plan.stop_distance_bps == 100


@pytest.mark.parametrize("coin", ["BTC", "ETH", "SOL", "BNB"])
def test_all_four_predeclared_native_markets_share_identical_policy(coin: str) -> None:
    plan = evaluate_volatility_budget(window_at(T, market=MarketId("", coin)))
    assert plan.decision.direction is Direction.LONG
    assert plan.stop == D("99.0099")


@pytest.mark.parametrize("component", ["bar", "book", "snapshot", "funding"])
def test_boolean_schema_is_not_a_genuine_version_one_receipt(component: str) -> None:
    window = _window()
    if component == "bar":
        window = replace(
            window, bars=(replace(window.bars[0], schema_version=True), *window.bars[1:])
        )
    else:
        value = getattr(window, component)
        assert value is not None
        window = replace(window, **{component: replace(value, schema_version=True)})
    assert evaluate_volatility_budget(window).decision.direction is Direction.NO_TRADE


def test_unknown_prior_variance_stays_unknown_despite_current_spike() -> None:
    window = _window()
    bars = tuple(
        replace(bar, open=D("100"), high=D("100"), low=D("100"), close=D("100"))
        if index < 87
        else replace(bar, open=D("110"), high=D("110"), low=D("110"), close=D("110"))
        for index, bar in enumerate(window.bars)
    )
    _reject(replace(window, bars=bars), "volatility_unknown", unknown=True)


def test_nonpositive_short_target_fails_closed_without_erasing_crossing() -> None:
    window = _window()
    last = window.bars[-4].close * D("20")
    bars = (
        *window.bars[:-3],
        *(replace(bar, open=last, high=last, low=last, close=last) for bar in window.bars[-3:]),
    )
    plan = evaluate_volatility_budget(replace(window, bars=bars))
    assert plan.signal_direction is Direction.SHORT
    assert plan.current_eligible is True
    assert plan.decision.reason_codes == ("nonpositive_geometry",)
    assert plan.entry is None and plan.stop is None and plan.target is None


def test_candle_receipt_at_cutoff_is_late_and_remains_unknown() -> None:
    window = _window()
    bars = (*window.bars[:-1], replace(window.bars[-1], received_at_ms=T))
    _reject(replace(window, bars=bars), "invalid_bar_receipt", unknown=True)
