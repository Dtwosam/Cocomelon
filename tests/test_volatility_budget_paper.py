"""Synthetic PAPER lifecycle tests; these do not authenticate source/activation."""

from dataclasses import replace
from decimal import Decimal

import pytest
from test_flow_exhaustion_paper import mark as flow_mark
from test_flow_exhaustion_paper import quote as flow_quote
from test_flow_exhaustion_paper import spec

from cocomelon.domain.market import MarketId

D = Decimal
DAY = 86_400_000
T = 100 * DAY + 30_000
BTC = MarketId("", "BTC")


def quote(ms, **kwargs):
    return flow_quote(ms, **{"bid": "99.99", "ask": "100.01", "size": "1000", **kwargs})


def mark(ms, price="100", market=BTC):
    return flow_mark(ms, price, market)


ETH = MarketId("", "ETH")


def trial(root, *, t=T, authorized=True):
    from cocomelon.research.volatility_budget_paper import VolatilityPaperTrial

    obj = VolatilityPaperTrial(
        root,
        candidate_id="volatility-candidate",
        control_id="volatility-control",
        first_entry_ms=t,
        startup_ms=t - 1000,
        prepare_new=not (root / "trial.sqlite").exists(),
    )
    obj.entries_authorized = authorized
    obj.set_source_valid(True, now_ms=max(t - 1000, obj.snapshot()["now_ms"]))
    return obj


def test_trial_stays_inactive_and_owns_distinct_durable_accounts(tmp_path):
    obj = trial(tmp_path, authorized=False)
    assert obj.snapshot()["entries_authorized"] is False
    assert obj.candidate.account.cash == obj.control.account.cash == D(10000)
    assert (tmp_path / "candidate.sqlite").stat().st_ino != (
        tmp_path / "control.sqlite"
    ).stat().st_ino
    obj.close()
    obj = trial(tmp_path, authorized=False)
    assert not obj.entries_authorized
    assert obj.candidate.account.starting_cash == D(10000)
    obj.close()


def test_duplicate_lease_and_identity_changes_rejected(tmp_path):
    obj = trial(tmp_path)
    with pytest.raises(RuntimeError, match="lease"):
        trial(tmp_path)
    obj.close()
    from cocomelon.research.volatility_budget_paper import VolatilityPaperTrial

    with pytest.raises(ValueError, match="identity"):
        VolatilityPaperTrial(
            tmp_path,
            candidate_id="replacement",
            control_id="control",
            first_entry_ms=T,
            startup_ms=T,
        )


def test_source_clock_regression_is_durable_and_permanent(tmp_path):
    obj = trial(tmp_path)
    obj.set_source_valid(True, now_ms=T)
    with pytest.raises(ValueError, match="clock regression"):
        obj.set_source_valid(True, now_ms=T - 1)
    assert obj.snapshot()["permanently_disabled"]
    obj.close()
    obj = trial(tmp_path)
    assert obj.snapshot()["permanently_disabled"]
    obj.close()


def test_store_alias_is_rejected(tmp_path):
    import os

    obj = trial(tmp_path)
    obj.close()
    os.unlink(tmp_path / "control.sqlite")
    os.link(tmp_path / "candidate.sqlite", tmp_path / "control.sqlite")
    with pytest.raises(ValueError, match="alias"):
        trial(tmp_path)


def test_deleted_account_does_not_reset_history(tmp_path):
    obj = trial(tmp_path)
    obj.close()
    (tmp_path / "candidate.sqlite").unlink()
    with pytest.raises(ValueError, match="history"):
        trial(tmp_path)


def stage(obj, *, t=T, short=False, market=BTC, windows=None):
    from test_volatility_budget import window_at

    rows = windows or (window_at(t, short=short, market=market),)
    obj.evaluate(
        rows,
        {w.market: spec(w.market) for w in rows},
        {w.market: w.book for w in rows if w.book is not None},
        now_ms=max(t, obj.snapshot()["now_ms"]),
    )


def opened(obj, *, t=T, short=False):
    stage(obj, t=t, short=short)
    obj.on_book(quote(t + 300), spec(), mark(t + 300), now_ms=t + 300)
    assert len(obj.candidate.account.positions) == 1
    return obj.candidate.account.positions[0]


def test_daily_batch_first_eligible_canonical_only_and_all_crossings_cooldown(tmp_path):
    from test_volatility_budget import window_at

    obj = trial(tmp_path)
    rows = (window_at(T, market=ETH), window_at(T, market=BTC))
    stage(obj, windows=rows)
    snap = obj.snapshot()
    assert snap["cooldowns"] == {BTC.canonical: T, ETH.canonical: T}
    assert snap["selected_market"] == BTC.canonical
    obj.on_book(quote(T + 300), spec(), mark(T + 300), now_ms=T + 300)
    assert obj.candidate.account.positions[0].market == BTC
    assert obj.candidate.account.positions[0].planned_risk <= D(10)
    assert obj.control.account.cash == D(10000)
    assert obj.control.store.table_counts()["paper_execution_attempts"] == 0
    obj.close()


def test_ineligible_first_does_not_hide_eligible_next_but_consumes_cooldown(tmp_path):
    from test_volatility_budget import window_at

    obj = trial(tmp_path)
    btc = window_at(T)
    btc = replace(
        btc,
        eligibility=replace(
            btc.eligibility, rankable=False, deep_ready=False, reasons=("SYNTHETIC_VETO",)
        ),
    )
    stage(obj, windows=(btc, window_at(T, market=ETH)))
    assert obj.snapshot()["selected_market"] == ETH.canonical
    assert obj.snapshot()["cooldowns"][BTC.canonical] == T
    obj.close()


def test_late_daily_batch_is_recorded_never_retimed(tmp_path):
    from test_volatility_budget import window_at

    obj = trial(tmp_path)
    w = window_at(T)
    obj.evaluate((w,), {BTC: spec()}, {BTC: w.book}, now_ms=T + 1)
    assert obj.snapshot()["pending"] is None
    assert obj.snapshot()["last_decision_ms"] == T
    assert obj.snapshot()["cooldowns"] == {}
    obj.close()


def test_predecision_book_cannot_fill_and_expiry_no_chase_after_restart(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    obj.on_book(quote(T), spec(), mark(T + 300), now_ms=T + 300)
    assert not obj.candidate.account.positions
    obj.on_book(quote(T + 2000), spec(), mark(T + 2000), now_ms=T + 2000)
    assert obj.snapshot()["pending"] is None
    obj.close()
    obj = trial(tmp_path, authorized=False)
    assert not obj.entries_authorized
    stage(obj)
    assert obj.snapshot()["pending"] is None
    obj.close()


def test_immutable_geometry_real_ioc_partial_and_one_trial_attempt(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    book = quote(T + 300, bid="100.10", ask="100.12")
    book = replace(
        book,
        payload={
            **book.payload,
            "asks": (
                {"px": D("100.12"), "sz": D(".1")},
                {"px": D("100.20"), "sz": D("1000")},
            ),
        },
    )
    obj.on_book(book, spec(), mark(T + 300), now_ms=T + 300)
    opening = next(
        obj.candidate.store.load_plan(str(row[0]))
        for row in obj.candidate.store.raw_connection().execute(
            "SELECT plan_id FROM paper_order_plans"
        )
    )
    assert obj.candidate.account.positions[0].quantity < opening.requested_quantity
    assert opening.execution_reference_price == D("100.12")
    assert obj.candidate.account.positions[0].stop_price == D("99.0099")
    pos = obj.candidate.account.positions[0]
    attempts = obj.candidate.store.table_counts()["paper_execution_attempts"]
    obj.on_book(quote(T + 600), spec(), mark(T + 600), now_ms=T + 600)
    assert obj.candidate.account.positions[0].quantity == pos.quantity
    assert obj.candidate.store.table_counts()["paper_execution_attempts"] == attempts
    assert obj.candidate.account.cumulative_fees > 0
    obj.close()


def test_durable_exit_waits_for_postintent_latency_and_new_book_after_restart(tmp_path):
    obj = trial(tmp_path)
    pos = opened(obj)
    bid = str(pos.average_entry_price * D("1.5"))
    ask = str(D(bid) + D(".02"))
    obj.on_book(quote(T + 1000, bid=bid, ask=ask), spec(), mark(T + 1000, bid), now_ms=T + 1000)
    assert obj.snapshot()["exit_reason"] == "target"
    assert obj.candidate.account.positions
    obj.close()
    obj = trial(tmp_path, authorized=False)
    obj.set_source_valid(False, now_ms=T + 1100)
    obj.on_book(quote(T + 1000, bid=bid, ask=ask), spec(), now_ms=T + 1300)
    assert obj.candidate.account.positions  # old trigger book cannot be recycled
    obj.on_book(quote(T + 1400, bid=bid, ask=ask), spec(), now_ms=T + 1400)
    assert not obj.candidate.account.positions
    assert len(obj.snapshot()["components"]) == 1
    obj.close()


def test_partial_exit_remains_latched_and_retries_use_new_latency(tmp_path):
    obj = trial(tmp_path)
    pos = opened(obj)
    price = str(pos.average_entry_price * D("1.5"))
    obj.on_book(
        quote(T + 1000, bid=price, ask=str(D(price) + D(".02"))),
        spec(),
        mark(T + 1000, price),
        now_ms=T + 1000,
    )
    obj.on_book(
        quote(T + 1300, bid=price, ask=str(D(price) + D(".02")), size=".01"),
        spec(),
        now_ms=T + 1300,
    )
    assert obj.candidate.account.positions[0].quantity == pos.quantity - D(".01")
    obj.on_book(quote(T + 1600), spec(), now_ms=T + 1600)
    assert obj.candidate.account.positions
    obj.on_book(quote(T + 1900), spec(), now_ms=T + 1900)
    assert not obj.candidate.account.positions
    obj.close()


def test_source_failure_blocks_entries_but_keeps_time_exit_after_actual_fill(tmp_path):
    obj = trial(tmp_path)
    pos = opened(obj)
    obj.record_source_fault("MATERIAL_HELD_GAP", permanent=True, now_ms=T + 500)
    now = pos.opened_at_ms + DAY
    obj.on_book(quote(now), spec(), mark(now), now_ms=now)
    assert obj.snapshot()["exit_reason"] == "max_hold"
    obj.on_book(quote(now + 300), spec(), mark(now + 300), now_ms=now + 300)
    assert not obj.candidate.account.positions
    assert obj.snapshot()["permanently_disabled"]
    assert obj.snapshot()["funding_unknown"]
    obj.close()


def test_execution_cost_veto_of_first_eligible_market_never_substitutes(tmp_path):
    from test_volatility_budget import window_at

    obj = trial(tmp_path)
    btc = window_at(T)
    btc = replace(btc, funding=replace(btc.funding, funding_rate=D(".001")))
    stage(obj, windows=(window_at(T, market=ETH), btc))
    assert obj.snapshot()["selected_market"] == BTC.canonical
    assert obj.snapshot()["pending"] is None
    assert obj.snapshot()["cooldowns"] == {BTC.canonical: T, ETH.canonical: T}
    obj.close()


def test_cooldown_anyside_and_suppressed_crossing_does_not_extend_expiry(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    obj.tick(now_ms=T + 2000)
    assert obj.snapshot()["pending"] is None
    stage(obj, t=T + DAY, short=True)
    assert obj.snapshot()["cooldowns"][BTC.canonical] == T
    assert obj.snapshot()["pending"] is None
    stage(obj, t=T + 3 * DAY)
    assert obj.snapshot()["cooldowns"][BTC.canonical] == T + 3 * DAY
    assert obj.snapshot()["pending"] is not None
    obj.close()


def test_mark_stop_is_durable_even_if_mark_recovers_before_book(tmp_path):
    obj = trial(tmp_path)
    opened(obj)
    obj.on_mark(mark(T + 1000, "98"), now_ms=T + 1000)
    assert obj.snapshot()["exit_reason"] == "stop"
    obj.on_mark(mark(T + 1100), now_ms=T + 1100)
    obj.close()
    obj = trial(tmp_path, authorized=False)
    assert obj.snapshot()["exit_reason"] == "stop"
    obj.on_book(quote(T + 1400), spec(), now_ms=T + 1400)
    obj.on_book(quote(T + 1700), spec(), now_ms=T + 1700)
    assert not obj.candidate.account.positions
    assert obj.snapshot()["components"][0]["exit_reason"] == "stop"
    obj.close()


def test_time_exit_latches_on_tick_without_a_book_and_survives_restart(tmp_path):
    obj = trial(tmp_path)
    pos = opened(obj)
    obj.tick(now_ms=pos.opened_at_ms + DAY)
    assert obj.snapshot()["exit_reason"] == "max_hold"
    obj.close()
    obj = trial(tmp_path, authorized=False)
    assert obj.snapshot()["exit_reason"] == "max_hold"
    obj.close()


def test_cross_kind_original_receive_regression_disables_entries_durably(tmp_path):
    obj = trial(tmp_path)
    obj.on_mark(mark(T + 100), now_ms=T + 100)
    obj.on_book(quote(T + 50), spec(), now_ms=T + 200)
    assert obj.snapshot()["permanently_disabled"]
    assert "SOURCE_RECEIVE_CLOCK_REGRESSION" in obj.snapshot()["faults"]
    obj.close()
    obj = trial(tmp_path, authorized=False)
    assert obj.snapshot()["permanently_disabled"]
    obj.close()


def test_missing_or_invalid_actual_mark_oracle_cannot_open(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    invalid = replace(mark(T + 300), payload={"mark_px": D("100"), "oracle_px": None})
    obj.on_book(quote(T + 300), spec(), invalid, now_ms=T + 300)
    assert not obj.candidate.account.positions
    assert obj.snapshot()["pending"] is None
    obj.close()


def test_one_rejected_opening_never_chases_a_later_good_quote(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    obj.on_book(quote(T + 300, bid="100.50", ask="100.52"), spec(), mark(T + 300), now_ms=T + 300)
    assert not obj.candidate.account.positions
    assert obj.snapshot()["pending"] is None
    obj.on_book(quote(T + 600), spec(), mark(T + 600), now_ms=T + 600)
    assert not obj.candidate.account.positions
    obj.close()


def test_equity_loss_floor_cannot_be_reset_by_price_recovery_or_restart(tmp_path):
    obj = trial(tmp_path)
    opened(obj)
    obj.on_mark(mark(T + 1000, "80"), now_ms=T + 1000)
    assert obj.candidate.account.equity <= D(9950)
    assert obj.snapshot()["permanently_disabled"]
    obj.on_mark(mark(T + 1100), now_ms=T + 1100)
    assert obj.candidate.account.equity > D(9950)
    assert obj.snapshot()["permanently_disabled"]
    obj.close()
    obj = trial(tmp_path, authorized=False)
    assert obj.snapshot()["permanently_disabled"]
    obj.close()


def test_trial_checkpoint_rollback_cannot_reset_consumed_day(tmp_path):
    import shutil

    obj = trial(tmp_path)
    obj.close()
    backup = tmp_path / "old-checkpoint.sqlite"
    shutil.copy2(tmp_path / "trial.sqlite", backup)
    obj = trial(tmp_path)
    stage(obj)
    obj.close()
    shutil.copy2(backup, tmp_path / "trial.sqlite")
    with pytest.raises(ValueError, match="rollback"):
        trial(tmp_path)


def test_account_only_rollback_cannot_erase_immutable_opening(tmp_path):
    import shutil

    obj = trial(tmp_path)
    obj.close()
    backup = tmp_path / "old-candidate.sqlite"
    shutil.copy2(tmp_path / "candidate.sqlite", backup)
    obj = trial(tmp_path)
    opened(obj)
    obj.close()
    shutil.copy2(backup, tmp_path / "candidate.sqlite")
    with pytest.raises(ValueError, match="rollback"):
        trial(tmp_path)


def test_exact_boundary_residual_quantity_is_settled_after_close_once(tmp_path):
    from cocomelon.execution.funding import FundingAccrual, funding_cash_delta
    from cocomelon.execution.store import _position_from_payload

    obj = trial(tmp_path)
    initial = opened(obj)
    boundary = (T // 3_600_000 + 1) * 3_600_000
    obj.on_book(
        quote(boundary - 400, bid="103", ask="103.02"),
        spec(),
        mark(boundary - 400, "103"),
        now_ms=boundary - 400,
    )
    obj.on_book(
        quote(boundary - 100, bid="103", ask="103.02", size=".01"), spec(), now_ms=boundary - 100
    )
    residual = obj.candidate.account.positions[0]
    assert residual.quantity == initial.quantity - D(".01")
    obj.on_mark(mark(boundary - 1, "103"), now_ms=boundary - 1)
    obj.on_book(quote(boundary + 100, bid="103", ask="103.02"), spec(), now_ms=boundary + 100)
    obj.on_book(quote(boundary + 400, bid="103", ask="103.02"), spec(), now_ms=boundary + 400)
    assert not obj.candidate.account.positions
    obligation = obj.snapshot()["funding_obligations"][0]
    position = _position_from_payload(obligation["position"])
    assert position.quantity == residual.quantity
    assert obj.snapshot()["funding_unknown"]
    before = obj.candidate.account.cash
    obj.close()
    obj = trial(tmp_path, authorized=False)
    cash = funding_cash_delta(position.quantity, D("103"), D(".001"))
    accrual = FundingAccrual(
        market=BTC,
        boundary_ms=boundary,
        position_id=position.position_id,
        signed_quantity=position.quantity,
        oracle_price=D("103"),
        funding_rate=D(".001"),
        cash_delta=cash,
        oracle_event_key=f"mark:{boundary - 1}",
        funding_source="hyperliquid-mainnet-info",
        funding_received_at_ms=boundary + 1000,
    )
    obj.apply_funding(accrual, now_ms=boundary + 1000)
    assert obj.candidate.account.cash == before + cash
    assert not obj.snapshot()["funding_unknown"]
    assert obj.snapshot()["components"][0]["funding_complete"]
    obj.apply_funding(accrual, now_ms=boundary + 1100)
    assert obj.candidate.account.cash == before + cash
    obj.close()


@pytest.mark.parametrize("mutation", ["schema", "duplicate"])
def test_actual_book_schema_or_duplicate_depth_cannot_open(tmp_path, mutation):
    obj = trial(tmp_path)
    stage(obj)
    book = quote(T + 300)
    if mutation == "schema":
        book = replace(book, schema_version=2)
    else:
        book = replace(book, payload={**book.payload, "asks": book.payload["asks"] * 2})
    obj.on_book(book, spec(), mark(T + 300), now_ms=T + 300)
    assert not obj.candidate.account.positions
    assert obj.snapshot()["pending"] is None
    obj.close()


def test_opening_without_a_genuine_recorded_mark_is_rejected(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    obj.on_book(quote(T + 300), spec(), now_ms=T + 300)
    assert not obj.candidate.account.positions
    assert obj.snapshot()["pending"] is None
    obj.close()


def test_stale_oracle_blocks_new_entry_at_actual_attempt(tmp_path):
    obj = trial(tmp_path)
    obj.on_mark(mark(T - 4800), now_ms=T - 1000)
    stage(obj)
    obj.on_book(quote(T + 300), spec(), now_ms=T + 300)
    assert not obj.candidate.account.positions
    assert obj.snapshot()["pending"] is None
    obj.close()


def test_restore_never_implicitly_creates_replacement_cash(tmp_path):
    from cocomelon.research.volatility_budget_paper import VolatilityPaperTrial

    with pytest.raises(ValueError, match="history"):
        VolatilityPaperTrial(
            tmp_path / "lost-root", candidate_id="c", control_id="b", first_entry_ms=T, startup_ms=T
        )


def test_original_receive_milliseconds_are_exact_and_fractional_clock_rejected():
    from datetime import timedelta

    from cocomelon.research.volatility_budget_paper import _received

    event = quote(T + 999)
    assert _received(event) == T + 999
    with pytest.raises(ValueError, match="exact milliseconds"):
        _received(replace(event, receive_time=event.receive_time + timedelta(microseconds=1)))


def test_short_uses_native_paper_stack_and_records_signed_complete_component(tmp_path):
    from cocomelon.execution.accounting import PositionSide

    obj = trial(tmp_path)
    pos = opened(obj, short=True)
    assert pos.side is PositionSide.SHORT
    assert pos.stop_price > pos.average_entry_price
    assert pos.planned_risk <= D(10)
    obj.on_book(
        quote(T + 1000, bid="96", ask="96.02"), spec(), mark(T + 1000, "96"), now_ms=T + 1000
    )
    assert obj.snapshot()["exit_reason"] == "target"
    obj.on_book(
        quote(T + 1300, bid="96", ask="96.02"), spec(), mark(T + 1300, "96"), now_ms=T + 1300
    )
    assert not obj.candidate.account.positions
    component = obj.snapshot()["components"][0]
    assert component["direction"] == "SHORT"
    assert component["decision_batch_ms"] == T
    assert component["evidence_digest"]
    assert component["opened_at_ms"] == T + 300
    assert component["funding_complete"]
    assert D(component["net"]) > 0  # Synthetic outcome only.
    assert obj.control.account.equity == D(10000)
    obj.close()


def test_known_opening_mark_immediately_latches_stop_and_permanent_loss_floor(tmp_path):
    obj = trial(tmp_path)
    stage(obj)
    obj.on_book(quote(T + 300), spec(), mark(T + 300, "80"), now_ms=T + 300)
    position = obj.candidate.account.positions[0]
    assert position.latest_mark == D("80")
    assert obj.candidate.account.unrealized_pnl < D(0)
    assert obj.candidate.account.equity <= D(9950)
    assert obj.snapshot()["permanently_disabled"]
    assert obj.snapshot()["exit_reason"] == "stop"
    obj.on_mark(mark(T + 400), now_ms=T + 400)
    assert obj.candidate.account.equity > D(9950)
    assert obj.snapshot()["permanently_disabled"]
    assert obj.snapshot()["exit_reason"] == "stop"
    obj.close()


@pytest.mark.parametrize("later_mark", [None, "100"])
def test_commit_before_opening_mark_reconciles_historical_stop_and_floor(
    tmp_path, monkeypatch, later_mark
):
    from cocomelon.research.volatility_budget_paper import VolatilityPaperTrial

    obj = trial(tmp_path)
    stage(obj)
    submit = obj.candidate.submit_opening

    def committed_then_interrupted(*args, **kwargs):
        submit(*args, **kwargs)
        if later_mark is not None:
            # Account can be ahead of the trial checkpoint after an interrupted
            # independent account write; this valuation must survive recovery.
            obj.candidate.mark_account_to_market({BTC: D(later_mark)}, timestamp_ms=T + 400)
        raise RuntimeError("synthetic interruption after actual adapter commit")

    monkeypatch.setattr(obj.candidate, "submit_opening", committed_then_interrupted)
    with pytest.raises(RuntimeError, match="after actual adapter commit"):
        obj.on_book(quote(T + 300), spec(), mark(T + 300, "80"), now_ms=T + 300)
    obj._dispose()  # Abrupt loss: do not checkpoint post-commit transient state.
    restored = VolatilityPaperTrial(
        tmp_path,
        candidate_id="volatility-candidate",
        control_id="volatility-control",
        first_entry_ms=T,
        startup_ms=T + 10_000,
    )
    assert not restored.entries_authorized
    assert not restored.source_valid  # The old receipt does not certify current freshness.
    assert restored.snapshot()["permanently_disabled"]
    assert restored.snapshot()["exit_reason"] == "stop"
    if later_mark is None:
        assert restored.candidate.account.equity <= D(9950)
        assert restored.candidate.account.positions[0].latest_mark == D("80")
    else:
        assert restored.candidate.account.equity > D(9950)
        assert restored.candidate.account.positions[0].latest_mark == D("100")
    fills_before = restored.candidate.store.table_counts()["paper_fills"]
    restored.close()
    restored = VolatilityPaperTrial(
        tmp_path,
        candidate_id="volatility-candidate",
        control_id="volatility-control",
        first_entry_ms=T,
        startup_ms=T + 11_000,
    )
    assert restored.snapshot()["permanently_disabled"]
    assert restored.snapshot()["exit_reason"] == "stop"
    assert restored.candidate.store.table_counts()["paper_fills"] == fills_before
    # A historical breach never backdates a new actual reduction plan or latency.
    restored.on_book(quote(T + 12_000), spec(), now_ms=T + 12_000)
    assert restored.candidate.account.positions
    restored.on_book(quote(T + 12_200), spec(), now_ms=T + 12_200)
    assert restored.candidate.account.positions
    assert restored.candidate.store.table_counts()["paper_fills"] == fills_before
    restored.on_book(quote(T + 12_300), spec(), now_ms=T + 12_300)
    assert not restored.candidate.account.positions
    assert restored.snapshot()["components"][0]["exit_reason"] == "stop"
    restored.close()


def test_committed_final_reduction_recovers_without_repeating_exit(tmp_path, monkeypatch):
    from cocomelon.research.volatility_budget_paper import VolatilityPaperTrial

    obj = trial(tmp_path)
    opened(obj)
    obj.on_book(
        quote(T + 1000, bid="103", ask="103.02"), spec(), mark(T + 1000, "103"), now_ms=T + 1000
    )
    assert obj.snapshot()["exit_reason"] == "target"
    execute = obj.candidate._execute_reduce_only_plan

    def committed_close_then_interrupted(*args, **kwargs):
        execute(*args, **kwargs)
        raise RuntimeError("synthetic interruption after committed final reduction")

    monkeypatch.setattr(
        obj.candidate, "_execute_reduce_only_plan", committed_close_then_interrupted
    )
    with pytest.raises(RuntimeError, match="committed final reduction"):
        obj.on_book(quote(T + 1300, bid="103", ask="103.02"), spec(), now_ms=T + 1300)
    assert not obj.candidate.account.positions
    cash = obj.candidate.account.cash
    fills = obj.candidate.store.table_counts()["paper_fills"]
    obj._dispose()
    restored = VolatilityPaperTrial(
        tmp_path,
        candidate_id="volatility-candidate",
        control_id="volatility-control",
        first_entry_ms=T,
        startup_ms=T + 2000,
    )
    assert not restored.candidate.account.positions
    assert restored.candidate.account.cash == cash
    assert restored.snapshot()["pending"] is None
    assert restored.snapshot()["exit_reason"] is None
    assert len(restored.snapshot()["components"]) == 1
    assert restored.snapshot()["components"][0]["exit_reason"] == "target"
    restored.on_book(quote(T + 2300), spec(), now_ms=T + 2300)
    assert restored.candidate.store.table_counts()["paper_fills"] == fills
    restored.close()


def test_same_timestamp_mark_commit_with_audit_event_recovers_pruned_peaks(tmp_path, monkeypatch):
    from cocomelon.research.volatility_budget_paper import VolatilityPaperTrial

    obj = trial(tmp_path)
    opened(obj)
    counts = obj.candidate.store.table_counts()
    mark_account = obj.candidate.mark_account_to_market

    def committed_mark_then_interrupted(*args, **kwargs):
        mark_account(*args, **kwargs)
        raise RuntimeError("synthetic interruption after committed same-clock mark")

    monkeypatch.setattr(obj.candidate, "mark_account_to_market", committed_mark_then_interrupted)
    with pytest.raises(RuntimeError, match="committed same-clock mark"):
        obj.on_mark(mark(T + 300, "101"), now_ms=T + 300)
    after = obj.candidate.store.table_counts()
    assert after["paper_position_events"] > counts["paper_position_events"]
    assert after["paper_rolling_peak_candidates"] < counts["paper_rolling_peak_candidates"]
    equity = obj.candidate.account.equity
    obj._dispose()
    restored = VolatilityPaperTrial(
        tmp_path,
        candidate_id="volatility-candidate",
        control_id="volatility-control",
        first_entry_ms=T,
        startup_ms=T + 2000,
    )
    assert restored.candidate.account.positions[0].latest_mark == D("101")
    assert restored.candidate.account.equity == equity
    assert not restored.snapshot()["faults"]
    restored.close()


def test_same_clock_mark_without_expected_transition_cannot_bypass_custody(tmp_path):
    from cocomelon.research.volatility_budget_paper import VolatilityPaperTrial

    obj = trial(tmp_path)
    opened(obj)
    obj.candidate.mark_account_to_market({BTC: D("101")}, timestamp_ms=T + 300)
    obj._dispose()
    with pytest.raises(ValueError, match="custody state mismatch"):
        VolatilityPaperTrial(
            tmp_path,
            candidate_id="volatility-candidate",
            control_id="volatility-control",
            first_entry_ms=T,
            startup_ms=T + 2000,
        )


def test_conflicting_same_clock_mark_after_expected_commit_is_rejected(tmp_path, monkeypatch):
    from cocomelon.research.volatility_budget_paper import VolatilityPaperTrial

    obj = trial(tmp_path)
    opened(obj)
    mark_account = obj.candidate.mark_account_to_market

    def conflicting_commits_then_interrupted(*args, **kwargs):
        mark_account(*args, **kwargs)
        mark_account({BTC: D("102")}, timestamp_ms=T + 300)
        raise RuntimeError("synthetic conflicting commit")

    monkeypatch.setattr(
        obj.candidate, "mark_account_to_market", conflicting_commits_then_interrupted
    )
    with pytest.raises(RuntimeError, match="conflicting commit"):
        obj.on_mark(mark(T + 300, "101"), now_ms=T + 300)
    obj._dispose()
    with pytest.raises(ValueError, match="custody state mismatch"):
        VolatilityPaperTrial(
            tmp_path,
            candidate_id="volatility-candidate",
            control_id="volatility-control",
            first_entry_ms=T,
            startup_ms=T + 2000,
        )


def test_interruption_before_witnessed_mark_commit_recovers_observed_loss(tmp_path, monkeypatch):
    from cocomelon.research.volatility_budget_paper import VolatilityPaperTrial

    obj = trial(tmp_path)
    opened(obj)

    def interrupted_before_mark(*args, **kwargs):
        raise RuntimeError("synthetic interruption before witnessed mark commit")

    monkeypatch.setattr(obj.candidate, "mark_account_to_market", interrupted_before_mark)
    with pytest.raises(RuntimeError, match="before witnessed mark commit"):
        obj.on_mark(mark(T + 1000, "80"), now_ms=T + 1000)
    assert obj.candidate.account.equity > D(9950)
    obj._dispose()
    restored = VolatilityPaperTrial(
        tmp_path,
        candidate_id="volatility-candidate",
        control_id="volatility-control",
        first_entry_ms=T,
        startup_ms=T + 10_000,
    )
    assert restored.candidate.account.positions[0].latest_mark == D("80")
    assert restored.candidate.account.equity <= D(9950)
    assert restored.snapshot()["permanently_disabled"]
    assert restored.snapshot()["exit_reason"] == "stop"
    assert not restored.source_valid
    restored.close()


def test_partial_reduction_preserves_genuine_known_marked_equity_and_margin(tmp_path):
    obj = trial(tmp_path)
    initial = opened(obj)
    obj.on_book(
        quote(T + 1000, bid="150", ask="150.02"), spec(), mark(T + 1000, "150"), now_ms=T + 1000
    )
    obj.on_book(quote(T + 1300, bid="150", ask="150.02", size=".01"), spec(), now_ms=T + 1300)
    remaining = obj.candidate.account.positions[0]
    assert remaining.quantity == initial.quantity - D(".01")
    expected = (D("150") - initial.average_entry_price) * remaining.quantity
    assert obj.candidate.account.unrealized_pnl == expected
    assert obj.candidate.account.equity == obj.candidate.account.cash + expected
    assert obj.candidate.account.gross_open_notional == D("150") * remaining.quantity
    assert obj.candidate.account.reserved_margin > 0
    obj.close()


def test_partial_reduction_known_mark_latches_loss_floor_before_recovery(tmp_path):
    obj = trial(tmp_path)
    opened(obj)
    obj.on_book(
        quote(T + 1000, bid="50", ask="50.02"), spec(), mark(T + 1000, "96"), now_ms=T + 1000
    )
    assert not obj.snapshot()["permanently_disabled"]
    obj.on_book(quote(T + 1300, bid="50", ask="50.02", size=".6"), spec(), now_ms=T + 1300)
    assert obj.candidate.account.equity <= D(9950)
    assert obj.snapshot()["permanently_disabled"]
    assert obj.snapshot()["exit_reason"] == "stop"
    obj.on_mark(mark(T + 1400), now_ms=T + 1400)
    assert obj.candidate.account.equity > D(9950)
    assert obj.snapshot()["permanently_disabled"]
    obj.close()


@pytest.mark.parametrize("later_mark", [None, "100"])
def test_committed_partial_recovers_historical_marked_loss_without_overwriting_newer_mark(
    tmp_path, monkeypatch, later_mark
):
    from cocomelon.research.volatility_budget_paper import VolatilityPaperTrial

    obj = trial(tmp_path)
    initial = opened(obj)
    obj.on_book(
        quote(T + 1000, bid="50", ask="50.02"), spec(), mark(T + 1000, "96"), now_ms=T + 1000
    )
    execute = obj.candidate._execute_reduce_only_plan

    def committed_partial_then_interrupted(*args, **kwargs):
        execute(*args, **kwargs)
        if later_mark is not None:
            obj.candidate.mark_account_to_market({BTC: D(later_mark)}, timestamp_ms=T + 1400)
        raise RuntimeError("synthetic interruption after committed partial reduction")

    monkeypatch.setattr(
        obj.candidate, "_execute_reduce_only_plan", committed_partial_then_interrupted
    )
    with pytest.raises(RuntimeError, match="committed partial reduction"):
        obj.on_book(quote(T + 1300, bid="50", ask="50.02", size=".6"), spec(), now_ms=T + 1300)
    obj._dispose()
    restored = VolatilityPaperTrial(
        tmp_path,
        candidate_id="volatility-candidate",
        control_id="volatility-control",
        first_entry_ms=T,
        startup_ms=T + 10_000,
    )
    assert restored.candidate.account.positions[0].quantity == initial.quantity - D(".6")
    assert restored.snapshot()["permanently_disabled"]
    assert restored.snapshot()["exit_reason"] == "stop"
    assert not restored.source_valid
    assert not restored.entries_authorized
    if later_mark is None:
        assert restored.candidate.account.positions[0].latest_mark == D("96")
        assert restored.candidate.account.equity <= D(9950)
    else:
        assert restored.candidate.account.positions[0].latest_mark == D("100")
        assert restored.candidate.account.equity > D(9950)
    fills = restored.candidate.store.table_counts()["paper_fills"]
    restored.on_book(quote(T + 12_000, bid="50", ask="50.02"), spec(), now_ms=T + 12_000)
    restored.on_book(quote(T + 12_200, bid="50", ask="50.02"), spec(), now_ms=T + 12_200)
    assert restored.candidate.store.table_counts()["paper_fills"] == fills
    restored.on_book(quote(T + 12_300, bid="50", ask="50.02"), spec(), now_ms=T + 12_300)
    assert not restored.candidate.account.positions
    assert restored.snapshot()["permanently_disabled"]
    restored.close()


def test_stale_context_keeps_partial_protection_enabled_and_qualification_closed(tmp_path):
    obj = trial(tmp_path)
    initial = opened(obj)
    obj.on_book(quote(T + 7000, bid="50", ask="50.02"), spec(), now_ms=T + 7000)
    obj.on_book(quote(T + 7300, bid="50", ask="50.02", size=".6"), spec(), now_ms=T + 7300)
    assert obj.candidate.account.positions[0].quantity == initial.quantity - D(".6")
    assert obj.snapshot()["permanently_disabled"]
    assert not obj.source_valid
    assert "REDUCTION_MARK_PROVENANCE_UNRECOVERABLE" in obj.snapshot()["faults"]
    obj.on_book(quote(T + 7600, bid="50", ask="50.02"), spec(), now_ms=T + 7600)
    obj.on_book(quote(T + 7900, bid="50", ask="50.02"), spec(), now_ms=T + 7900)
    assert not obj.candidate.account.positions
    assert obj.snapshot()["permanently_disabled"]
    obj.close()
