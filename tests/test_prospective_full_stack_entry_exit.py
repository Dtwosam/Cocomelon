from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.profit_lock_execution_shadow import (
    ProfitLockExecutionOutcome,
)
from cocomelon.research.prospective_breakeven_profit_lock import (
    ProspectiveBreakevenProfitLockState,
)
from cocomelon.research.prospective_full_stack_entry_exit import (
    prospective_full_stack_entry_exit_summary,
)


def _trade(
    suffix: str,
    *,
    direction: Direction,
    pnl: str,
    opened_at_ms: int,
    market: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    risk = Decimal("10")
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 60_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"open-{suffix}", f"close-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=Decimal("90"),
        initial_risk_amount=risk,
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + net,
        filled_quantity=Decimal("1"),
        gross_realized_pnl=net,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=net / risk,
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    candidate_pnl: str | None,
) -> dict[str, object]:
    candidate = (
        None
        if candidate_pnl is None
        else Decimal(candidate_pnl)
    )
    outcome = ProfitLockExecutionOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        rule_id="breakeven_after_0_5r",
        activated=True,
        triggered=True,
        simulated_close_complete=candidate is not None,
        activation_timestamp_ms=trade.opened_at_ms + 1_000,
        trigger_timestamp_ms=trade.opened_at_ms + 2_000,
        completion_timestamp_ms=(
            trade.opened_at_ms + 3_000
            if candidate is not None
            else None
        ),
        simulated_filled_quantity=(
            Decimal("1")
            if candidate is not None
            else Decimal("0")
        ),
        simulated_average_exit_price=(
            Decimal("100")
            if candidate is not None
            else None
        ),
        simulated_exit_fees=Decimal("0"),
        attempt_count=1,
        planning_rejection_count=0,
        no_fill_count=0,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        candidate_net_pnl_estimate=candidate,
        candidate_net_r_estimate=(
            None
            if candidate is None
            else candidate / trade.initial_risk_amount
        ),
        delta_net_pnl_estimate=(
            None
            if candidate is None
            else candidate - trade.net_pnl
        ),
        delta_net_r_estimate=(
            None
            if candidate is None
            else candidate / trade.initial_risk_amount - trade.net_r
        ),
        candidate_source=(
            "visible_book_ioc"
            if candidate is not None
            else "triggered_incomplete"
        ),
    )
    return outcome.payload()


def test_full_stack_applies_exit_only_to_entry_admitted_trades() -> None:
    start = 30_000_000
    breakeven = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=start - 6 * 60 * 60 * 1_000
    )
    blocked = _trade(
        "blocked",
        direction=Direction.LONG,
        pnl="-8",
        opened_at_ms=start + 1_000,
        market="SOL",
    )
    admitted = _trade(
        "admitted",
        direction=Direction.SHORT,
        pnl="-6",
        opened_at_ms=start + 2_000,
        market="ETH",
    )
    combined = {
        "started_at_ms": start,
        "decision_block_reason_by_trade_id": {
            blocked.trade_id: "long_trend_block",
            admitted.trade_id: None,
        },
    }
    two = {
        "started_at_ms": start,
        "decision_prior_strikes": {
            blocked.trade_id: 0,
            admitted.trade_id: 0,
        },
    }
    momentum = {
        "started_at_ms": start,
        "decision_details": {
            blocked.trade_id: {"decision": "ADMIT"},
            admitted.trade_id: {"decision": "ADMIT"},
        },
    }
    execution_state = {
        "outcomes": [
            _outcome(blocked, candidate_pnl="5"),
            _outcome(admitted, candidate_pnl="1"),
        ]
    }

    result = prospective_full_stack_entry_exit_summary(
        (blocked, admitted),
        combined,
        two,
        momentum,
        execution_state,
        breakeven,
    )

    assert result["closed_trades_since_overlap_start"] == 2
    assert result["economically_evaluated_trades"] == 2
    assert result["entry_blocked_trades"] == 1
    assert result["entry_admitted_trades"] == 1
    assert result["actual_net_pnl"] == "-14"
    assert result["entry_stack_candidate_net_pnl"] == "-6"
    assert result["full_stack_candidate_net_pnl"] == "1"
    assert result["full_stack_delta_net_pnl"] == "15"
    assert result["breakeven_incremental_net_pnl"] == "7"
    assert result["integrity_clean"] is True
    decisions = result["decision_by_trade_id"]
    assert isinstance(decisions, dict)
    assert decisions[blocked.trade_id]["exit_evaluation"] == "NOT_APPLICABLE"
    assert decisions[admitted.trade_id]["exit_evaluation"] == "EVALUATED"


def test_full_stack_reports_missing_exit_only_for_admitted_trade() -> None:
    start = 30_000_000
    breakeven = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=start - 6 * 60 * 60 * 1_000
    )
    blocked = _trade(
        "blocked-missing",
        direction=Direction.LONG,
        pnl="-8",
        opened_at_ms=start + 1_000,
        market="SOL",
    )
    admitted = _trade(
        "admitted-missing",
        direction=Direction.SHORT,
        pnl="-6",
        opened_at_ms=start + 2_000,
        market="ETH",
    )
    combined = {
        "started_at_ms": start,
        "decision_block_reason_by_trade_id": {
            blocked.trade_id: None,
            admitted.trade_id: None,
        },
    }
    two = {
        "started_at_ms": start,
        "decision_prior_strikes": {
            blocked.trade_id: 2,
            admitted.trade_id: 0,
        },
    }
    momentum = {
        "started_at_ms": start,
        "decision_details": {
            blocked.trade_id: {"decision": "ADMIT"},
            admitted.trade_id: {"decision": "ADMIT"},
        },
    }

    result = prospective_full_stack_entry_exit_summary(
        (blocked, admitted),
        combined,
        two,
        momentum,
        {"outcomes": []},
        breakeven,
    )

    assert result["entry_blocked_trades"] == 1
    assert result["entry_admitted_trades"] == 1
    assert result["missing_breakeven_outcomes"] == 1
    assert result["economically_evaluated_trades"] == 1
    assert result["integrity_clean"] is False
    assert result["actual_net_pnl"] == "-8"
    assert result["full_stack_candidate_net_pnl"] == "0"


def test_full_stack_reports_unevaluable_exact_outcome() -> None:
    start = 30_000_000
    breakeven = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=start - 6 * 60 * 60 * 1_000
    )
    trade = _trade(
        "unevaluable",
        direction=Direction.LONG,
        pnl="-5",
        opened_at_ms=start + 1_000,
        market="SOL",
    )
    combined = {
        "started_at_ms": start,
        "decision_block_reason_by_trade_id": {trade.trade_id: None},
    }
    two = {
        "started_at_ms": start,
        "decision_prior_strikes": {trade.trade_id: 0},
    }
    momentum = {
        "started_at_ms": start,
        "decision_details": {
            trade.trade_id: {"decision": "ADMIT"}
        },
    }

    result = prospective_full_stack_entry_exit_summary(
        (trade,),
        combined,
        two,
        momentum,
        {"outcomes": [_outcome(trade, candidate_pnl=None)]},
        breakeven,
    )

    assert result["missing_breakeven_outcomes"] == 0
    assert result["unevaluable_breakeven_outcomes"] == 1
    assert result["economically_evaluated_trades"] == 0
    assert result["integrity_clean"] is False


def _economic_fixture(
    *,
    last_block_negative: bool = False,
    all_blocked: bool = False,
    short_net_negative: bool = False,
) -> dict[str, object]:
    start = 40_000_000
    trades: list[TradeJournalEntry] = []
    combined: dict[str, object] = {}
    strikes: dict[str, object] = {}
    momentum: dict[str, object] = {}
    outcomes: list[dict[str, object]] = []
    for index in range(40):
        blocked = all_blocked or index % 5 == 0
        loss_block = last_block_negative and index >= 30
        weak_short = short_net_negative and index % 2 == 1 and not blocked
        actual = (
            "-3" if loss_block or weak_short
            else ("-2" if blocked else "1")
        )
        candidate = "-2" if loss_block else ("-1" if weak_short else "3")
        trade = _trade(
            f"economic-{index}",
            direction=(
                Direction.LONG if index % 2 == 0 else Direction.SHORT
            ),
            pnl=actual,
            opened_at_ms=start + index * 120_000,
            market=("BTC", "ETH", "SOL", "AVAX")[index % 4],
        )
        trades.append(trade)
        combined[trade.trade_id] = "rank_and_trend" if blocked else None
        strikes[trade.trade_id] = 0
        momentum[trade.trade_id] = {"decision": "ADMIT"}
        if not blocked:
            outcomes.append(_outcome(trade, candidate_pnl=candidate))
    return {
        "trades": tuple(trades),
        "combined": {
            "started_at_ms": start,
            "decision_block_reason_by_trade_id": combined,
        },
        "two": {
            "started_at_ms": start,
            "decision_prior_strikes": strikes,
        },
        "momentum": {
            "started_at_ms": start,
            "decision_details": momentum,
        },
        "shadow": {"outcomes": outcomes},
        "breakeven": ProspectiveBreakevenProfitLockState(
            frozen_at_ms=start - 6 * 60 * 60 * 1_000
        ),
    }


def _evaluate_fixture(raw: dict[str, object]) -> dict[str, object]:
    return prospective_full_stack_entry_exit_summary(
        raw["trades"],
        raw["combined"],
        raw["two"],
        raw["momentum"],
        raw["shadow"],
        raw["breakeven"],
    )


def test_full_stack_economic_screen_needs_real_winners_in_each_block() -> None:
    result = _evaluate_fixture(_economic_fixture())
    screen = result["economic_viability_screen"]
    assert result["integrity_clean"] is True
    assert screen["economic_screen_passes"] is True
    assert screen["absolute_candidate_profitable"] is True
    assert screen["both_directions_absolutely_profitable"] is True
    assert screen["incremental_vs_actual_positive"] is True
    assert screen["chronological_blocks_all_pass"] is True
    assert screen["candidate_leave_one_out_robust"] is True
    assert screen["incremental_leave_one_out_robust"] is True
    assert screen["evaluated_trades"] == 40
    assert screen["observed_markets"] == 4
    assert screen["entry_admitted"] == 32
    assert screen["entry_blocked"] == 8
    assert screen["blocked_losers"] == 8
    assert screen["blocked_winners_forgone"] == 0
    assert screen["admitted_winners_preserved"] == 32
    assert screen["admitted_winners_lost_after_exit"] == 0
    assert screen["by_direction"]["short"]["evaluated_trades"] == 20
    assert all(
        block["passes_absolute_and_incremental"]
        for block in screen["temporal_blocks"]
    )
    # Matched trade economics must never count as full account profits.
    assert screen["ready_for_review"] is False
    assert screen["portfolio_profitability_proven"] is False
    assert screen["execution_authority"] is False
    assert screen["promotion_authority"] is False


def test_full_stack_economic_screen_rejects_profitable_total_with_bad_late_block() -> None:
    result = _evaluate_fixture(_economic_fixture(last_block_negative=True))
    screen = result["economic_viability_screen"]
    assert Decimal(screen["full_stack_net_pnl"]) > 0
    assert Decimal(screen["full_stack_delta_net_pnl"]) > 0
    assert screen["sample_sufficient"] is True
    assert screen["chronological_blocks_all_pass"] is False
    assert screen["temporal_blocks"][-1]["full_stack_net_pnl"] == "-16"
    assert screen["economic_screen_passes"] is False


def test_full_stack_economic_screen_rejects_flat_no_trade_strategy() -> None:
    result = _evaluate_fixture(_economic_fixture(all_blocked=True))
    screen = result["economic_viability_screen"]
    assert screen["evaluated_trades"] == 40
    assert screen["entry_admitted"] == 0
    assert screen["full_stack_net_pnl"] == "0"
    assert screen["absolute_candidate_profitable"] is False
    assert screen["sample_sufficient"] is False
    assert screen["economic_screen_passes"] is False


def test_full_stack_exit_counts_existing_winner_lost() -> None:
    start = 45_000_000
    winner = _trade(
        "profit-forgone",
        direction=Direction.SHORT,
        pnl="4",
        opened_at_ms=start,
        market="ETH",
    )
    report = prospective_full_stack_entry_exit_summary(
        (winner,),
        {
            "started_at_ms": start,
            "decision_block_reason_by_trade_id": {winner.trade_id: None},
        },
        {
            "started_at_ms": start,
            "decision_prior_strikes": {winner.trade_id: 0},
        },
        {
            "started_at_ms": start,
            "decision_details": {winner.trade_id: {"decision": "ADMIT"}},
        },
        {"outcomes": [_outcome(winner, candidate_pnl="-1")]},
        ProspectiveBreakevenProfitLockState(
            frozen_at_ms=start - 6 * 60 * 60 * 1_000
        ),
    )
    screen = report["economic_viability_screen"]
    assert screen["admitted_winners_preserved"] == 0
    assert screen["admitted_winners_lost_after_exit"] == 1
    assert screen["blocked_winners_forgone"] == 0
    assert screen["exit_incremental_net_pnl"] == "-5"
    assert screen["economic_screen_passes"] is False


def test_full_stack_cannot_hide_negative_short_trade_economics() -> None:
    result = _evaluate_fixture(_economic_fixture(short_net_negative=True))
    screen = result["economic_viability_screen"]
    assert screen["sample_sufficient"] is True
    assert Decimal(screen["full_stack_net_pnl"]) > 0
    assert Decimal(screen["full_stack_delta_net_pnl"]) > 0
    assert screen["chronological_blocks_all_pass"] is True
    assert Decimal(screen["by_direction"]["long"]["net_pnl"]) > 0
    assert Decimal(screen["by_direction"]["short"]["net_pnl"]) < 0
    assert screen["both_directions_absolutely_profitable"] is False
    assert screen["direction_absolute_profitability"] == {
        "long": True,
        "short": False,
    }
    assert screen["economic_screen_passes"] is False
    # No blanket ban is authorized by this finding.
    assert screen["execution_authority"] is False
    assert screen["promotion_authority"] is False
