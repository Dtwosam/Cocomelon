from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_net_edge_admission import (
    FROZEN_EMBARGO_MS,
    ProspectiveNetEdgeError,
    ProspectiveNetEdgeState,
    preentry_net_floor,
    replay_net_floor_on_original_closes,
)

STATE = ProspectiveNetEdgeState(frozen_at_ms=1_800_000_000_000)
BASE = STATE.started_at_ms
RISK = Decimal("10")
MARKETS = ("BTC", "ETH", "SOL", "XRP")


def _trade(
    index: int, *,
    r: str = "0.20",
    side: Direction = Direction.LONG,
    market: str | None = None,
    opened_ms: int | None = None,
    closed_ms: int | None = None,
) -> TradeJournalEntry:
    pnl = Decimal(r) * RISK
    opened = opened_ms if opened_ms is not None else BASE + index * 10_000
    closed = closed_ms if closed_ms is not None else opened + 1_000
    return TradeJournalEntry(
        market=MarketId("", market or MARKETS[index % len(MARKETS)]),
        direction=side,
        opened_at_ms=opened,
        closed_at_ms=closed,
        feature_snapshot_id=f"f-{index}",
        strategy_decision_id=f"s-{index}",
        risk_decision_id=f"r-{index}",
        opening_plan_id=f"o-{index}",
        opening_attempt_id=f"a-{index}",
        exit_plan_ids=(f"e-{index}",),
        exit_attempt_ids=(f"ea-{index}",),
        fill_ids=(f"open-{index}", f"close-{index}"),
        position_action_ids=(f"action-{index}",),
        funding_event_ids=(),
        initial_stop=Decimal("90"),
        initial_risk_amount=RISK,
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + pnl,
        filled_quantity=Decimal("1"),
        gross_realized_pnl=pnl,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed - opened,
        mfe=None,
        mae=None,
        net_r=Decimal(r),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + pnl,
        exit_reason="fixture",
        health_refs=("original-paper",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="baseline-paper-custody",
    )


def test_freeze_embargo_and_only_new_closed_reference() -> None:
    rows = tuple(_trade(i) for i in range(40))
    early = preentry_net_floor(
        rows,
        proposed_open_ms=BASE - 1,
        direction=Direction.LONG,
        state=STATE,
    )
    assert early["reason"] == "precommitted_embargo"
    assert early["candidate_decision"] == "BLOCK"
    assert STATE.started_at_ms == STATE.frozen_at_ms + FROZEN_EMBARGO_MS
    assert STATE.contract()["execution_authority"] is False

    old_rows = tuple(_trade(i, opened_ms=BASE - 50_000 + i * 1_000,
                           closed_ms=BASE - 40_000 + i * 1_000)
                     for i in range(40))
    after = preentry_net_floor(
        old_rows, proposed_open_ms=BASE + 100_000,
        direction=Direction.LONG, state=STATE,
    )
    assert after["reference_closed_trades"] == 0
    assert after["candidate_decision"] == "BLOCK"


def test_future_closes_and_same_ms_closes_can_never_vote_on_earlier_entry() -> None:
    prior = tuple(_trade(i) for i in range(40))
    at = BASE + 405_000
    decision = preentry_net_floor(
        prior, proposed_open_ms=at,
        direction=Direction.LONG, state=STATE,
    )
    assert decision["candidate_decision"] == "ADMIT"
    assert Decimal(decision["empirical_stress_floor_net_r"]) > Decimal("0.05")
    assert decision["strictly_past_reference_last_close_ms"] < at
    # A gigantic winner that closes AFTER target opening cannot lift
    # the target floor, even if the trade opened much earlier.
    eventual = _trade(
        100, r="100", opened_ms=BASE + 50, closed_ms=at + 1,
    )
    tied = _trade(
        101, r="-9", opened_ms=BASE + 60, closed_ms=at,
    )
    outcome = preentry_net_floor(
        prior + (eventual, tied),
        proposed_open_ms=at, direction=Direction.LONG, state=STATE,
    )
    assert outcome == decision


def test_negative_earliest_block_fails_even_when_pooled_net_positive() -> None:
    rows = tuple(
        _trade(i, r="-0.8" if i < 10 else "0.7")
        for i in range(40)
    )
    result = preentry_net_floor(
        rows, proposed_open_ms=BASE + 450_000,
        direction=Direction.LONG, state=STATE,
    )
    assert result["candidate_decision"] == "BLOCK"
    assert Decimal(result["empirical_stress_floor_net_r"]) == Decimal("-0.8")


def test_leave_one_market_out_fails_a_single_market_winner_spike() -> None:
    rows = tuple(
        _trade(i, market=MARKETS[i % 4], r="2" if i % 4 == 0 else "-0.2")
        for i in range(40)
    )
    result = preentry_net_floor(
        rows, proposed_open_ms=BASE + 450_000,
        direction=Direction.LONG, state=STATE,
    )
    assert result["candidate_decision"] == "BLOCK"
    assert Decimal(result["empirical_stress_floor_net_r"]) < 0


def test_rolling_direction_uses_only_the_latest_80_completed_trades() -> None:
    rows = tuple(_trade(i, r="-0.5" if i < 50 else "0.3")
                 for i in range(130))
    result = preentry_net_floor(
        rows, proposed_open_ms=BASE + 1_310_000,
        direction=Direction.LONG, state=STATE,
    )
    assert result["reference_closed_trades"] == 80
    assert result["candidate_decision"] == "ADMIT"

    shorts = preentry_net_floor(
        rows, proposed_open_ms=BASE + 1_310_000,
        direction=Direction.SHORT, state=STATE,
    )
    assert shorts["reference_closed_trades"] == 0
    assert shorts["candidate_decision"] == "BLOCK"


def test_unfiltered_baseline_remains_training_source_even_when_shadow_skips() -> None:
    rows = tuple(_trade(i) for i in range(45))
    report = replay_net_floor_on_original_closes(rows, state=STATE)
    assert report["forward_original_rows"] == 45
    assert report["forward_original_admitted"] == 5
    assert report["forward_original_skipped"] == 40
    assert Decimal(
        report["hypothetical_forward_retained_same_fills_net"]
    ) == Decimal("10")
    assert Decimal(
        report["whole_original_baseline_net_pnl_including_discovery"]
    ) == Decimal("90")
    assert report["counterfactual_is_independent_account"] is False
    assert report["all_original_source_continuity_verified"] is False
    assert report["positive_whole_account_equity_verified"] is False
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False


def test_no_trades_yields_no_fake_profit_or_promotion() -> None:
    report = replay_net_floor_on_original_closes((), state=STATE)
    assert report["forward_original_rows"] == 0
    assert report["hypothetical_forward_retained_same_fills_net"] == "0"
    assert report["positive_whole_account_equity_verified"] is False


def test_duplicate_original_custody_and_bad_clock_fail_closed() -> None:
    item = _trade(0)
    with pytest.raises(ProspectiveNetEdgeError, match="duplicate"):
        preentry_net_floor(
            (item, item), proposed_open_ms=BASE + 3_000,
            direction=Direction.LONG, state=STATE,
        )
    with pytest.raises(ProspectiveNetEdgeError, match="clock"):
        preentry_net_floor(
            (), proposed_open_ms=-1,
            direction=Direction.LONG, state=STATE,
        )
    with pytest.raises(ProspectiveNetEdgeError, match="direction"):
        preentry_net_floor(
            (), proposed_open_ms=BASE + 3_000,
            direction=Direction.NO_TRADE, state=STATE,
        )
    with pytest.raises(ValueError, match="nonnegative"):
        ProspectiveNetEdgeState(frozen_at_ms=-1)
    assert replace(STATE, frozen_at_ms=STATE.frozen_at_ms).contract() == STATE.contract()
