"""Real paper-adapter integration using explicitly synthetic policy windows."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from test_flow_exhaustion import BTC, T, _window

from cocomelon.domain.execution import InstrumentExecutionSpec
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.funding import FundingAccrual, funding_cash_delta

D = Decimal


def spec(market=BTC):
    return InstrumentExecutionSpec(market, 4, D(20), D(10), 0, "synthetic-mainnet-meta")


def quote(ms, *, bid="99.49", ask="99.51", size="100", market=BTC):
    return StreamEvent(
        StreamKind.L2_BOOK,
        market,
        ms,
        datetime.fromtimestamp(ms / 1000, UTC),
        1,
        "hyperliquid-mainnet-ws",
        f"{market}:{ms}",
        {"bids": ({"px": D(bid), "sz": D(size)},), "asks": ({"px": D(ask), "sz": D(size)},)},
    )


def mark(ms, price="99.5", market=BTC):
    return StreamEvent(
        StreamKind.ACTIVE_ASSET_CTX,
        market,
        None,
        datetime.fromtimestamp(ms / 1000, UTC),
        1,
        "hyperliquid-mainnet-ws",
        f"mark:{ms}",
        {"mark_px": D(price), "oracle_px": D(price)},
    )


def trial(root, *, t=T, authorized=True):
    from cocomelon.research.flow_exhaustion_paper import FlowPaperTrial

    obj = FlowPaperTrial(
        root, candidate_id="candidate", control_id="control", first_entry_ms=t, startup_ms=t - 1000
    )
    obj.entries_authorized = authorized  # Explicit synthetic authorization, never launch evidence.
    return obj


def window_at(t=T, short=False, market=BTC):
    window = _window(short)
    delta = t - T
    events = tuple(
        replace(
            e,
            market=market,
            exchange_time_ms=e.exchange_time_ms + delta,
            receive_time=datetime.fromtimestamp(
                (int(e.receive_time.timestamp() * 1000) + delta) / 1000, UTC
            ),
        )
        for e in window.events
    )
    return replace(
        window,
        market=market,
        decision_time_ms=t,
        events=events,
        eligibility=replace(window.eligibility, market=market),
        funding=replace(
            window.funding, market=market, time_ms=t // 3600000 * 3600000, received_at_ms=t
        ),
    )


def stage(obj, t=T, short=False):
    book = quote(t, bid="100.48" if short else "99.49", ask="100.50" if short else "99.51")
    obj.evaluate((window_at(t, short),), {BTC: spec()}, {BTC: book}, now_ms=t)


def opened(obj, t=T, short=False):
    stage(obj, t, short)
    obj.on_book(
        quote(t + 300, bid="100.48" if short else "99.49", ask="100.50" if short else "99.51"),
        spec(),
        mark(t + 300, "100.49" if short else "99.5"),
        now_ms=t + 300,
    )
    assert len(obj.candidate.account.positions) == 1
    return obj.candidate.account.positions[0]


def test_stays_inactive_without_operational_authorization(tmp_path):
    obj = trial(tmp_path, authorized=False)
    stage(obj)
    obj.on_book(quote(T + 300), spec(), mark(T + 300), now_ms=T + 300)
    assert not obj.candidate.account.positions
    assert not obj.control.account.positions
    assert obj.snapshot()["entries_authorized"] is False
    obj.close()


def test_real_delayed_fill_preserves_fees_risk_and_control(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    obj.on_book(quote(T + 100), spec(), mark(T + 100), now_ms=T + 100)
    assert not obj.candidate.account.positions
    pos = opened_after_stage(obj)
    assert pos.planned_risk <= D(10)
    assert pos.quantity * pos.average_entry_price <= D(2500)
    assert obj.candidate.account.cumulative_fees > 0
    assert obj.control.account.cash == D(10000)
    assert obj.control.store.table_counts()["paper_execution_attempts"] == 0
    obj.close()


def opened_after_stage(obj):
    obj.on_book(quote(T + 300), spec(), mark(T + 300), now_ms=T + 300)
    return obj.candidate.account.positions[0]


def test_entry_expiry_and_one_attempt_per_epoch_survive_restart(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    obj.on_book(quote(T + 2000), spec(), mark(T + 2000), now_ms=T + 2000)
    assert not obj.candidate.account.positions
    obj.close()
    obj = trial(tmp_path)
    stage(obj)
    assert obj.snapshot()["pending"] is None
    obj.close()


@pytest.mark.parametrize(
    "short,bid,ask,expected",
    [
        (False, "100.01", "100.03", "target"),
        (False, "99.20", "99.22", "stop"),
        (True, "99.97", "99.99", "target"),
        (True, "100.78", "100.80", "stop"),
    ],
)
def test_frozen_exit_intent_retries_after_restart(tmp_path, short, bid, ask, expected):
    obj = trial(tmp_path)
    opened(obj, short=short)
    obj.on_book(
        quote(T + 1000, bid=bid, ask=ask),
        spec(),
        mark(T + 1000, str((D(bid) + D(ask)) / 2)),
        now_ms=T + 1000,
    )
    assert obj.snapshot()["exit_reason"] == expected
    assert obj.candidate.account.positions  # 250ms simulated latency is real.
    obj.close()
    obj = trial(tmp_path)
    obj.entries_authorized = False
    obj.on_book(
        quote(T + 1300, bid=bid, ask=ask),
        spec(),
        mark(T + 1300, str((D(bid) + D(ask)) / 2)),
        now_ms=T + 1300,
    )
    obj.on_book(
        quote(T + 1600, bid=bid, ask=ask),
        spec(),
        mark(T + 1600, str((D(bid) + D(ask)) / 2)),
        now_ms=T + 1600,
    )
    assert not obj.candidate.account.positions
    assert len(obj.snapshot()["components"]) == 1
    obj.close()


def test_partial_exit_remains_latched_when_price_returns_inside_target(tmp_path):
    obj = trial(tmp_path)
    pos = opened(obj)
    obj.on_book(
        quote(T + 1000, bid="100.01", ask="100.03", size=".1"),
        spec(),
        mark(T + 1000, "100.02"),
        now_ms=T + 1000,
    )
    obj.on_book(
        quote(T + 1300, bid="100.01", ask="100.03", size=".1"),
        spec(),
        mark(T + 1300, "100.02"),
        now_ms=T + 1300,
    )
    assert obj.candidate.account.positions[0].quantity == pos.quantity - D(".1")
    obj.on_book(quote(T + 1600), spec(), mark(T + 1600), now_ms=T + 1600)
    obj.on_book(quote(T + 1900), spec(), mark(T + 1900), now_ms=T + 1900)
    assert not obj.candidate.account.positions
    obj.close()


def test_max_hold_uses_actual_fill_and_new_entries_can_be_disabled(tmp_path):
    obj = trial(tmp_path)
    pos = opened(obj)
    obj.entries_authorized = False
    now = pos.opened_at_ms + 1800000
    obj.on_book(quote(now), spec(), mark(now), now_ms=now)
    assert obj.snapshot()["exit_reason"] == "max_hold"
    obj.on_book(quote(now + 300), spec(), mark(now + 300), now_ms=now + 300)
    assert not obj.candidate.account.positions
    obj.close()


def test_late_funding_after_full_exit_uses_boundary_quantity_idempotently(tmp_path):
    t = 3570000
    obj = trial(tmp_path, t=t)
    pos = opened(obj, t=t)
    oracle = mark(3599999)
    obj.on_mark(oracle, now_ms=3599999)
    pos = obj.candidate.account.positions[0]  # Exact boundary state, not changing live state hash.
    obj.on_book(
        quote(3600100, bid="100.01", ask="100.03"), spec(), mark(3600100, "100.02"), now_ms=3600100
    )
    obj.on_book(
        quote(3600400, bid="100.01", ask="100.03"), spec(), mark(3600400, "100.02"), now_ms=3600400
    )
    assert not obj.candidate.account.positions
    assert obj.snapshot()["funding_unknown"] is True
    before = obj.candidate.account.cash
    obj.close()
    obj = trial(tmp_path, t=t)
    cash = funding_cash_delta(pos.quantity, D("99.5"), D(".001"))
    accrual = FundingAccrual(
        BTC,
        3600000,
        pos.position_id,
        pos.quantity,
        D("99.5"),
        D(".001"),
        cash,
        oracle.event_key,
        "hyperliquid-mainnet-info",
        3600500,
    )
    obj.apply_funding(accrual, now_ms=3600600)
    obj.apply_funding(accrual, now_ms=3600700)
    assert obj.candidate.account.cash == before + cash
    assert obj.candidate.account.cumulative_funding == cash
    assert obj.snapshot()["funding_unknown"] is False
    assert obj.snapshot()["components"][0]["funding"] == str(cash)
    obj.close()


def test_missing_or_forged_boundary_funding_fails_closed(tmp_path):
    obj = trial(tmp_path)
    pos = opened(obj)
    accrual = FundingAccrual(
        BTC,
        3600000,
        pos.position_id,
        pos.quantity,
        D(100),
        D(".001"),
        -pos.quantity * D(".1"),
        "fake",
        "hyperliquid-mainnet-info",
        3600500,
    )
    with pytest.raises(ValueError, match="boundary"):
        obj.apply_funding(accrual, now_ms=3600600)
    obj.close()


def test_fifty_dollar_marked_loss_permanently_disables_entry(tmp_path):
    obj = trial(tmp_path)
    opened(obj)
    obj.on_mark(mark(T + 500, "1"), now_ms=T + 500)
    assert obj.snapshot()["permanently_disabled"] is True
    obj.on_mark(mark(T + 600, "99.5"), now_ms=T + 600)
    assert obj.snapshot()["permanently_disabled"] is True
    obj.close()
    obj = trial(tmp_path)
    assert obj.snapshot()["permanently_disabled"] is True
    obj.close()


def test_conflicting_account_identity_is_rejected(tmp_path):
    obj = trial(tmp_path)
    obj.close()
    from cocomelon.research.flow_exhaustion_paper import FlowPaperTrial

    with pytest.raises(ValueError, match="identity"):
        FlowPaperTrial(
            tmp_path,
            candidate_id="different",
            control_id="control",
            first_entry_ms=T,
            startup_ms=T - 1000,
        )
    resumed = trial(tmp_path)
    resumed.close()


def test_committed_opening_is_reconciled_after_checkpoint_interruption(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    checkpoint = obj._db.execute("SELECT data FROM checkpoint WHERE id=1").fetchone()[0]
    opened_after_stage(obj)
    # Simulate the crash window after the account transaction, before runner checkpoint.
    import json

    stale = json.loads(checkpoint)
    key = stale["pending"]
    current = obj._state["intents"][key]
    stale["intents"][key].update(
        status="attempting", plan_id=current["plan_id"], equity_before=current["equity_before"]
    )
    with obj._db:
        obj._db.execute("UPDATE checkpoint SET data=? WHERE id=1", (json.dumps(stale),))
    obj._dispose()  # Crash releases OS lease without saving runner checkpoint.
    obj = trial(tmp_path)
    assert len(obj.candidate.account.positions) == 1
    count = obj.candidate.store.table_counts()["paper_execution_attempts"]
    obj.on_book(quote(T + 600), spec(), mark(T + 600), now_ms=T + 600)
    assert obj.candidate.store.table_counts()["paper_execution_attempts"] == count
    obj.close()


def test_stale_exchange_book_cannot_open_despite_recent_receipt(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    bad = replace(quote(T + 300), exchange_time_ms=T - 5000)
    obj.on_book(bad, spec(), mark(T + 300), now_ms=T + 300)
    assert not obj.candidate.account.positions
    obj.close()


def test_changed_price_that_invalidates_frozen_room_rejects_without_crash(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    obj.on_book(
        quote(T + 300, bid="100.01", ask="100.03"), spec(), mark(T + 300, "100.02"), now_ms=T + 300
    )
    assert not obj.candidate.account.positions
    obj.close()


def test_only_one_candidate_stages_in_lexical_queue(tmp_path):
    obj = trial(tmp_path)
    eth = MarketId("", "ETH")
    obj.evaluate(
        (window_at(market=eth), window_at()),
        {BTC: spec(), eth: spec(eth)},
        {BTC: quote(T), eth: quote(T, market=eth)},
        now_ms=T,
    )
    obj.on_book(quote(T + 300, market=eth), spec(eth), mark(T + 300, market=eth), now_ms=T + 300)
    assert not obj.candidate.account.positions
    obj.on_book(quote(T + 600), spec(), mark(T + 600), now_ms=T + 600)
    assert obj.candidate.account.positions[0].market == BTC
    obj.close()


def test_unassigned_entry_boundary_keeps_preparation_inactive(tmp_path):
    from cocomelon.research.flow_exhaustion_paper import FlowPaperTrial

    obj = FlowPaperTrial(
        tmp_path,
        candidate_id="candidate",
        control_id="control",
        first_entry_ms=None,
        startup_ms=T - 1000,
    )
    obj.entries_authorized = True  # Still insufficient without an immutable boundary.
    stage(obj)
    assert obj.snapshot()["pending"] is None
    assert obj.snapshot()["first_entry_ms"] is None
    obj.close()


def test_conflicting_second_funding_rate_cannot_double_book_boundary(tmp_path):
    t = 3570000
    obj = trial(tmp_path, t=t)
    opened(obj, t=t)
    oracle = mark(3599999)
    obj.on_mark(oracle, now_ms=3599999)
    pos = obj.candidate.account.positions[0]
    obj.on_book(quote(3600100), spec(), mark(3600100), now_ms=3600100)
    cash = funding_cash_delta(pos.quantity, D("99.5"), D(".001"))
    accrual = FundingAccrual(
        BTC,
        3600000,
        pos.position_id,
        pos.quantity,
        D("99.5"),
        D(".001"),
        cash,
        oracle.event_key,
        "hyperliquid-mainnet-info",
        3600500,
    )
    obj.apply_funding(accrual, now_ms=3600600)
    with pytest.raises(ValueError, match="boundary"):
        obj.apply_funding(
            replace(accrual, funding_rate=D(".002"), cash_delta=2 * cash), now_ms=3600700
        )
    assert obj.candidate.account.cumulative_funding == cash
    obj.close()


def test_partial_opening_is_a_single_opening_and_never_averaged(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    book = quote(T + 300)
    book = replace(
        book,
        payload={
            **book.payload,
            "asks": ({"px": D("99.51"), "sz": D(".0001")}, {"px": D("99.74"), "sz": D(100)}),
        },
    )
    obj.on_book(book, spec(), mark(T + 300), now_ms=T + 300)
    assert len(obj.candidate.account.positions) == 1
    count = obj.candidate.store.table_counts()["paper_execution_attempts"]
    plan = obj.candidate.store.load_plan(obj.candidate.account.positions[0].opening_plan_id)
    assert obj.candidate.account.positions[0].quantity < plan.requested_quantity
    obj.on_book(quote(T + 600), spec(), mark(T + 600), now_ms=T + 600)
    assert obj.candidate.store.table_counts()["paper_execution_attempts"] == count
    obj.close()


def cycle(obj, market, t, *, losing=False):
    obj.evaluate(
        (window_at(t, market=market),),
        {market: spec(market)},
        {market: quote(t, market=market)},
        now_ms=t,
    )
    obj.on_book(
        quote(t + 300, market=market), spec(market), mark(t + 300, market=market), now_ms=t + 300
    )
    assert len(obj.candidate.account.positions) == 1
    bid, ask = ("99.20", "99.22") if losing else ("100.01", "100.03")
    for offset in (1000, 1300):
        obj.on_book(
            quote(t + offset, bid=bid, ask=ask, market=market),
            spec(market),
            mark(t + offset, str((D(bid) + D(ask)) / 2), market),
            now_ms=t + offset,
        )
    assert not obj.candidate.account.positions


def test_six_actual_openings_per_day_and_market_cooldown(tmp_path):
    obj = trial(tmp_path)
    cycle(obj, BTC, T)
    obj.evaluate((window_at(T + 30000),), {BTC: spec()}, {BTC: quote(T + 30000)}, now_ms=T + 30000)
    assert obj.snapshot()["pending"] is None
    for i in range(1, 6):
        cycle(obj, MarketId("", f"M{i}"), T + i * 60000)
    other = MarketId("", "OTHER")
    obj.evaluate(
        (window_at(T + 360000, market=other),),
        {other: spec(other)},
        {other: quote(T + 360000, market=other)},
        now_ms=T + 360000,
    )
    assert obj.snapshot()["pending"] is None
    assert len(obj.snapshot()["components"]) == 6
    obj.close()


def test_three_actual_losses_use_existing_one_hour_risk_cooldown(tmp_path):
    obj = trial(tmp_path)
    for i in range(3):
        cycle(obj, MarketId("", f"M{i}"), T + i * 60000, losing=True)
    assert obj.candidate.account.consecutive_losses == 3
    other = MarketId("", "OTHER")
    obj.evaluate(
        (window_at(T + 180000, market=other),),
        {other: spec(other)},
        {other: quote(T + 180000, market=other)},
        now_ms=T + 180000,
    )
    assert obj.snapshot()["pending"] is None
    obj.close()


def test_no_fill_expiry_never_moves_to_second_market_in_epoch(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    # Adverse drift makes this one candidate unexecutable; no chase into another market.
    obj.on_book(
        quote(T + 300, bid="99.01", ask="99.03"), spec(), mark(T + 300, "99.02"), now_ms=T + 300
    )
    assert not obj.candidate.account.positions
    assert obj.snapshot()["pending"] is None
    stage(obj)
    assert obj.snapshot()["pending"] is None
    obj.close()


def test_failed_exit_ioc_retries_latched_intent_until_actual_fill(tmp_path):
    obj = trial(tmp_path)
    opened(obj)
    obj.on_book(
        quote(T + 1000, bid="100.01", ask="100.03"),
        spec(),
        mark(T + 1000, "100.02"),
        now_ms=T + 1000,
    )
    # Latency completes after price moves outside the pending IOC's 25bp boundary.
    obj.on_book(quote(T + 1300), spec(), mark(T + 1300), now_ms=T + 1300)
    assert obj.candidate.account.positions
    assert obj.snapshot()["exit_reason"] == "target"
    connection = obj.candidate.store.raw_connection()
    import json

    attempts = [
        json.loads(row[0])
        for row in connection.execute("SELECT payload_json FROM paper_execution_attempts")
    ]
    assert any(row["result"] == "no_fill" for row in attempts)
    for offset in (1600, 1900):
        obj.on_book(quote(T + offset), spec(), mark(T + offset), now_ms=T + offset)
    assert not obj.candidate.account.positions
    obj.close()


def test_missing_component_funding_is_unknown_not_zero(tmp_path):
    t = 3570000
    obj = trial(tmp_path, t=t)
    opened(obj, t=t)
    obj.on_mark(mark(3599999), now_ms=3599999)
    for now in (3600100, 3600400):
        obj.on_book(quote(now, bid="100.01", ask="100.03"), spec(), mark(now, "100.02"), now_ms=now)
    component = obj.snapshot()["components"][0]
    assert component["funding"] is None
    assert component["net"] is None
    assert component["funding_complete"] is False
    obj.close()


def test_root_has_exclusive_account_lease(tmp_path):
    obj = trial(tmp_path)
    with pytest.raises((ValueError, RuntimeError), match="lease"):
        trial(tmp_path)
    obj.close()
    obj.close()
    resumed = trial(tmp_path)
    resumed.close()


def test_old_account_store_cannot_be_adopted_without_trial_checkpoint(tmp_path):
    from cocomelon.domain.execution import PaperExecutionConfig
    from cocomelon.execution.paper import PaperExecutionAdapter

    old = PaperExecutionAdapter(
        tmp_path / "candidate.sqlite",
        PaperExecutionConfig(),
        starting_cash=D(10000),
        startup_timestamp_ms=T - 1000,
    )
    old.mark_account_to_market({}, timestamp_ms=T - 1000)
    old.close()
    with pytest.raises(ValueError, match="existing|checkpoint"):
        trial(tmp_path)


def test_missing_candidate_history_cannot_reset_recorded_losses(tmp_path):
    obj = trial(tmp_path)
    cycle(obj, BTC, T, losing=True)
    obj.close()
    (tmp_path / "candidate.sqlite").unlink()
    with pytest.raises(ValueError, match="missing|history|restore"):
        trial(tmp_path)


def test_rolled_back_account_history_cannot_reset_recorded_losses(tmp_path):
    import shutil

    obj = trial(tmp_path)
    obj.close()
    saved = tmp_path / "earlier.sqlite"
    shutil.copyfile(tmp_path / "candidate.sqlite", saved)
    obj = trial(tmp_path)
    cycle(obj, BTC, T, losing=True)
    obj.close()
    shutil.copyfile(saved, tmp_path / "candidate.sqlite")
    with pytest.raises(ValueError, match="history|restore|intent"):
        trial(tmp_path)


def test_account_store_symlink_cannot_alias_another_ledger(tmp_path):
    import shutil

    obj = trial(tmp_path)
    obj.close()
    outside = tmp_path / "other.sqlite"
    shutil.move(tmp_path / "candidate.sqlite", outside)
    (tmp_path / "candidate.sqlite").symlink_to(outside)
    with pytest.raises(ValueError, match="alias|symlink"):
        trial(tmp_path)


def test_real_nullable_asset_context_does_not_break_protective_exit(tmp_path):
    obj = trial(tmp_path)
    opened(obj)
    real = replace(
        mark(T + 1000, "99.21"),
        payload={
            "mark_px": D("99.21"),
            "oracle_px": D("99.21"),
            "mid_px": None,
            "funding": D(0),
            "open_interest": D(100),
        },
    )
    obj.on_book(quote(T + 1000, bid="99.20", ask="99.22"), spec(), real, now_ms=T + 1000)
    obj.close()
    obj = trial(tmp_path)
    for offset in (1300, 1600):
        obj.on_book(quote(T + offset, bid="99.20", ask="99.22"), spec(), now_ms=T + offset)
    assert not obj.candidate.account.positions
    obj.close()


def test_fresh_mark_stop_triggers_even_before_executable_quote_crosses(tmp_path):
    obj = trial(tmp_path)
    opened(obj)
    obj.on_book(quote(T + 1000), spec(), mark(T + 1000, "99.20"), now_ms=T + 1000)
    assert obj.snapshot()["exit_reason"] == "stop"
    obj.on_book(quote(T + 1300), spec(), mark(T + 1300, "99.20"), now_ms=T + 1300)
    assert not obj.candidate.account.positions
    obj.close()


def test_exit_cannot_fill_replayed_book_received_before_latency_boundary(tmp_path):
    obj = trial(tmp_path)
    opened(obj)
    same = quote(T + 1000, bid="100.01", ask="100.03")
    obj.on_book(same, spec(), mark(T + 1000, "100.02"), now_ms=T + 1000)
    obj.on_book(same, spec(), now_ms=T + 1300)
    assert obj.candidate.account.positions
    obj.on_book(
        quote(T + 1600, bid="100.01", ask="100.03"),
        spec(),
        mark(T + 1600, "100.02"),
        now_ms=T + 1600,
    )
    assert not obj.candidate.account.positions
    obj.close()


def test_decision_clock_regression_fault_blocks_pending_entry(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    obj.evaluate((), {}, {}, now_ms=T - 1)
    assert "RUNNER_CLOCK_REGRESSION" in obj.snapshot()["faults"]
    obj.on_book(quote(T + 300), spec(), mark(T + 300), now_ms=T + 300)
    assert not obj.candidate.account.positions
    obj.close()


def test_stop_preemption_preserves_pending_reduce_receipt_boundary(tmp_path):
    obj = trial(tmp_path)
    opened(obj)
    obj.on_book(
        quote(T + 1000, bid="100.01", ask="100.03"),
        spec(),
        mark(T + 1000, "100.02"),
        now_ms=T + 1000,
    )
    old = quote(T + 1050, bid="100.01", ask="100.03")
    obj.on_book(old, spec(), mark(T + 1300, "99.20"), now_ms=T + 1300)
    assert obj.snapshot()["exit_reason"] == "stop"
    assert obj.candidate.account.positions
    obj.close()
