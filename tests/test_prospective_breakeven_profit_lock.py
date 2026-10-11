from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from cocomelon.domain.execution import (
    OrderSide,
    OrderType,
    PaperExecutionConfig,
    PaperOrderPlan,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.profit_lock_counterfactual import (
    DEFAULT_PROFIT_LOCK_COSTS,
    DEFAULT_PROFIT_LOCK_RULES,
)
from cocomelon.research.profit_lock_execution_ledger import (
    update_profit_lock_execution_ledger,
)
from cocomelon.research.profit_lock_execution_shadow import (
    EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
    ProfitLockExecutionOutcome,
)
from cocomelon.research.prospective_breakeven_profit_lock import (
    EMBARGO_MS,
    ProspectiveBreakevenProfitLockError,
    ProspectiveBreakevenProfitLockState,
    prospective_breakeven_from_execution_ledger,
    prospective_breakeven_profit_lock_summary,
)
from cocomelon.research.prospective_entry_cost_r import (
    ProspectiveEntryCostRError,
    ProspectiveEntryCostRState,
    prospective_entry_cost_r_comparison,
)
from cocomelon.research.prospective_net_reserved_trailing import (
    prospective_net_reserved_trailing_comparison,
)
from cocomelon.research.prospective_profit_target_one_r_comparison import (
    ProspectiveProfitTargetComparisonError,
    prospective_profit_target_one_half_r_comparison,
    prospective_profit_target_one_r_comparison,
    prospective_profit_target_threshold_comparison,
    prospective_profit_trailing_comparison,
)
from cocomelon.research.prospective_profit_trailing_grid import (
    prospective_profit_trailing_grid_comparison,
)


def _trade(
    suffix: str,
    *,
    opened_at_ms: int,
    pnl: str,
    market: str = "SOL",
    direction: Direction = Direction.LONG,
) -> TradeJournalEntry:
    net = Decimal(pnl)
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
        initial_risk_amount=Decimal("10"),
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
        net_r=net / Decimal("10"),
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
    candidate_pnl: str,
    activated: bool = True,
    triggered: bool = True,
    complete: bool = True,
) -> ProfitLockExecutionOutcome:
    candidate = Decimal(candidate_pnl)
    # Fixture IOC fills must reconcile to their reported PnL after reserve.
    completion_elapsed_ms = 21_000
    funding_reserve = (
        trade.entry_price
        * trade.filled_quantity
        * DEFAULT_PROFIT_LOCK_COSTS.funding_reserve_fraction_per_hour
        * Decimal(completion_elapsed_ms)
        / Decimal(3_600_000)
    )
    per_unit_profit = (
        (candidate + trade.entry_fees + funding_reserve)
        / trade.filled_quantity
    )
    simulated_exit_price = (
        trade.entry_price + per_unit_profit
        if trade.direction is Direction.LONG
        else trade.entry_price - per_unit_profit
    )
    return ProfitLockExecutionOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        rule_id="breakeven_after_0_5r",
        activated=activated,
        triggered=triggered,
        simulated_close_complete=complete,
        activation_timestamp_ms=(
            trade.opened_at_ms + 10_000 if activated else None
        ),
        trigger_timestamp_ms=(
            trade.opened_at_ms + 20_000 if triggered else None
        ),
        completion_timestamp_ms=(
            trade.opened_at_ms + 21_000 if complete else None
        ),
        simulated_filled_quantity=(
            trade.filled_quantity if complete else Decimal("0")
        ),
        simulated_average_exit_price=(
            simulated_exit_price if complete and triggered else None
        ),
        simulated_exit_fees=Decimal("0"),
        attempt_count=1 if triggered else 0,
        planning_rejection_count=0,
        no_fill_count=0,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        candidate_net_pnl_estimate=(
            candidate if complete or not triggered else None
        ),
        candidate_net_r_estimate=(
            candidate / Decimal("10")
            if complete or not triggered
            else None
        ),
        delta_net_pnl_estimate=(
            candidate - trade.net_pnl
            if complete or not triggered
            else None
        ),
        delta_net_r_estimate=(
            candidate / Decimal("10") - trade.net_r
            if complete or not triggered
            else None
        ),
        candidate_source=(
            "visible_book_ioc"
            if complete and triggered
            else (
                "triggered_incomplete"
                if triggered
                else "actual_close"
            )
        ),
    )


def _state(outcomes: tuple[ProfitLockExecutionOutcome, ...]) -> dict[str, object]:
    return {
        "schema_version": EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
        "started_at_ms": 1,
        "execution_config": {"config_version": "paper-v1"},
        "rules": [
            {
                "rule_id": rule.rule_id,
                "activate_at_r": str(rule.activate_at_r),
                "lock_at_r": str(rule.lock_at_r),
            }
            for rule in DEFAULT_PROFIT_LOCK_RULES
        ],
        "positions": [],
        "outcomes": [outcome.payload() for outcome in outcomes],
        "excluded_closed_trades": 0,
        "lineage_mismatch_closed_trades": 0,
        "orphaned_restored_positions": 0,
    }


def test_prospective_breakeven_state_round_trip() -> None:
    state = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=123
    )
    assert state.started_at_ms == 123 + EMBARGO_MS
    restored = ProspectiveBreakevenProfitLockState.from_payload(
        state.payload()
    )
    assert restored == state

    payload = state.payload()
    rule = payload["rule"]
    assert isinstance(rule, dict)
    rule["activate_at_r"] = "0.6"
    with pytest.raises(
        ProspectiveBreakevenProfitLockError,
        match="rule drift",
    ):
        ProspectiveBreakevenProfitLockState.from_payload(payload)


def test_prospective_breakeven_ignores_touched_pre_embargo_trades() -> None:
    frozen = 1_000_000
    candidate = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=frozen
    )
    start = candidate.started_at_ms
    touched = _trade(
        "touched",
        opened_at_ms=start - 1,
        pnl="-5",
    )
    clean = _trade(
        "clean",
        opened_at_ms=start,
        pnl="-5",
    )
    result = prospective_breakeven_profit_lock_summary(
        (touched, clean),
        _state(
            (
                _outcome(touched, candidate_pnl="1"),
                _outcome(clean, candidate_pnl="1"),
            )
        ),
        candidate,
    )

    assert result["prospective_closed_trades"] == 1
    assert result["matched_outcomes"] == 1
    assert result["actual_net_pnl"] == "-5"
    assert result["candidate_net_pnl"] == "1"
    assert result["delta_net_pnl"] == "6"


def test_prospective_breakeven_requires_complete_future_outcomes() -> None:
    candidate = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=2_000_000
    )
    trade = _trade(
        "missing",
        opened_at_ms=candidate.started_at_ms,
        pnl="-5",
    )
    result = prospective_breakeven_profit_lock_summary(
        (trade,),
        _state(()),
        candidate,
    )

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["integrity_clean"] is False
    assert readiness["ready_for_review"] is False
    assert result["missing_outcome_trade_ids"] == [trade.trade_id]


def test_prospective_breakeven_ready_requires_profitable_robust_both_sides() -> None:
    candidate = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=3_000_000
    )
    trades: list[TradeJournalEntry] = []
    outcomes: list[ProfitLockExecutionOutcome] = []
    for index in range(40):
        direction = (
            Direction.LONG if index % 2 == 0 else Direction.SHORT
        )
        market = "SOL" if index % 5 < 3 else "ETH"
        trade = _trade(
            f"ready-{index}",
            opened_at_ms=candidate.started_at_ms + index * 120_000,
            pnl="-1" if index % 3 == 0 else "1",
            market=market,
            direction=direction,
        )
        trades.append(trade)
        outcomes.append(
            _outcome(
                trade,
                candidate_pnl="1",
                activated=True,
                triggered=True,
                complete=True,
            )
            if index % 3 == 0
            else ProfitLockExecutionOutcome(
                trade_id=trade.trade_id,
                opening_plan_id=trade.opening_plan_id,
                market=trade.market.canonical,
                direction=trade.direction.value,
                rule_id="breakeven_after_0_5r",
                activated=index < 16,
                triggered=False,
                simulated_close_complete=False,
                activation_timestamp_ms=(
                    trade.opened_at_ms + 10_000
                    if index < 16
                    else None
                ),
                trigger_timestamp_ms=None,
                completion_timestamp_ms=None,
                simulated_filled_quantity=Decimal("0"),
                simulated_average_exit_price=None,
                simulated_exit_fees=Decimal("0"),
                attempt_count=0,
                planning_rejection_count=0,
                no_fill_count=0,
                actual_net_pnl=trade.net_pnl,
                actual_net_r=trade.net_r,
                candidate_net_pnl_estimate=trade.net_pnl,
                candidate_net_r_estimate=trade.net_r,
                delta_net_pnl_estimate=Decimal("0"),
                delta_net_r_estimate=Decimal("0"),
                candidate_source="actual_close",
            )
        )

    result = prospective_breakeven_profit_lock_summary(
        tuple(trades),
        _state(tuple(outcomes)),
        candidate,
    )

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["sample_complete"] is True
    assert readiness["candidate_profitable"] is True
    assert readiness["delta_positive"] is True
    assert readiness["single_trade_robust"] is True
    assert readiness["single_market_robust"] is True
    assert readiness["ready_for_review"] is True
    assert result["long_evaluated_trades"] == 20
    assert result["short_evaluated_trades"] == 20
    assert readiness["chronologically_stable_absolute_and_incremental"] is True
    temporal = result["chronological_stability"]
    assert temporal["both_halves_profitable_and_improved"] is True
    assert len(temporal["halves"]) == 2
    assert result["paired_exit_payoff"]["losers_recovered_as_winners"] == 14
    assert result["paired_exit_payoff"]["original_winners_preserved"] == 26
    assert result["by_direction"]["short"]["trades"] == 20


def test_prospective_breakeven_incomplete_trigger_blocks_integrity() -> None:
    candidate = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=4_000_000
    )
    trade = _trade(
        "incomplete",
        opened_at_ms=candidate.started_at_ms,
        pnl="-5",
    )
    result = prospective_breakeven_profit_lock_summary(
        (trade,),
        _state(
            (
                _outcome(
                    trade,
                    candidate_pnl="0",
                    triggered=True,
                    complete=False,
                ),
            )
        ),
        candidate,
    )

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert result["triggered_incomplete"] == 1
    assert readiness["integrity_clean"] is False
    assert readiness["ready_for_review"] is False


def test_prospective_breakeven_reuses_immutable_execution_ledger() -> None:
    candidate = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=5_000_000
    )
    trade = _trade(
        "ledger",
        opened_at_ms=candidate.started_at_ms,
        pnl="-5",
        market="ETH",
        direction=Direction.SHORT,
    )
    execution_ledger = update_profit_lock_execution_ledger(
        (trade,),
        _state((_outcome(trade, candidate_pnl="1"),)),
        previous=None,
        source_paper_run_id=77,
        source_paper_run_attempt=2,
        source_artifact_name="learning-77-2",
        source_artifact_digest="sha256:" + "a" * 64,
    )

    result = prospective_breakeven_from_execution_ledger(
        (trade,),
        execution_ledger,
        candidate,
    )

    assert result["prospective_closed_trades"] == 1
    assert result["matched_outcomes"] == 1
    assert result["delta_net_pnl"] == "6"
    assert (
        result["source_execution_ledger_sha256"]
        == execution_ledger["ledger_sha256"]
    )
    assert result["source_execution_ledger_row_count"] == 1
    assert result["source_paper_run_id"] == 77
    assert result["source_paper_run_attempt"] == 2
    assert result["source_artifact_name"] == "learning-77-2"


def test_prospective_exit_no_promotion_for_one_half_only_improvement() -> None:
    state = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=7_000_000
    )
    trades = tuple(
        _trade(
            f"one-half-{index}",
            opened_at_ms=state.started_at_ms + index * 120_000,
            pnl="-1" if index < 10 else "1",
            market="ETH" if index % 2 else "SOL",
            direction=Direction.LONG if index % 2 else Direction.SHORT,
        )
        for index in range(30)
    )
    outcomes = tuple(
        _outcome(
            trade,
            candidate_pnl="1",
            activated=True,
            triggered=index < 10,
            complete=index < 10,
        )
        for index, trade in enumerate(trades)
    )
    result = prospective_breakeven_profit_lock_summary(
        trades, _state(outcomes), state
    )
    readiness = result["readiness"]
    assert readiness["sample_complete"] is True
    assert readiness["candidate_profitable"] is True
    assert readiness["delta_positive"] is True
    assert readiness["single_trade_robust"] is True
    assert readiness["single_market_robust"] is True
    assert readiness[
        "chronologically_stable_absolute_and_incremental"
    ] is False
    assert readiness["ready_for_review"] is False
    assert result["chronological_stability"]["halves"][1][
        "delta_net_pnl"
    ] == "0"


def test_prospective_exit_audits_winners_lost_as_well_as_losses_saved() -> None:
    state = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=8_000_000
    )
    winner = _trade(
        "foregone-winner",
        opened_at_ms=state.started_at_ms,
        pnl="5",
        direction=Direction.LONG,
    )
    loser = _trade(
        "recovered-loser",
        opened_at_ms=state.started_at_ms + 120_000,
        pnl="-2",
        direction=Direction.SHORT,
    )
    result = prospective_breakeven_profit_lock_summary(
        (winner, loser),
        _state((
            _outcome(winner, candidate_pnl="-1"),
            _outcome(loser, candidate_pnl="2"),
        )),
        state,
    )
    economics = result["paired_exit_payoff"]
    assert economics["trades"] == 2
    assert economics["losers_recovered_as_winners"] == 1
    assert economics["original_winners_turned_nonprofitable"] == 1
    assert economics["original_winners_preserved"] == 0
    assert economics["gross_positive_contribution_pnl"] == "4"
    assert economics["gross_forgone_contribution_pnl"] == "6"
    assert economics["delta_net_pnl"] == "-2"
    assert result["by_direction"]["long"]["delta_net_pnl"] == "-6"
    assert result["by_direction"]["short"]["delta_net_pnl"] == "4"
    assert result["readiness"]["ready_for_review"] is False


def _profit_target_state(
    outcomes: tuple[ProfitLockExecutionOutcome, ...],
    *,
    started_at_ms: int = 1_000_000,
) -> dict[str, object]:
    state = _state(outcomes)
    state["started_at_ms"] = started_at_ms
    state["rules"] = [{
        "rule_id": "profit_target_at_1r",
        "activate_at_r": "1",
        "lock_at_r": "1",
        "exit_on_activation": "true",
    }]
    return state


def _profit_target_fixture(
    *,
    bad_late_block: bool = False,
    short_loses: bool = False,
    unfilled: bool = False,
) -> tuple[
    tuple[TradeJournalEntry, ...], dict[str, object], dict[str, object]
]:
    trades = []
    targets = []
    breakevens = []
    for index in range(40):
        trade = _trade(
            f"paired-target-{index}",
            opened_at_ms=1_100_000 + index * 100_000,
            market=("BTC", "ETH", "SOL", "AVAX")[index % 4],
            direction=Direction.LONG if index % 2 == 0 else Direction.SHORT,
            pnl="-2",
        )
        target_pnl = (
            "-1" if bad_late_block and index >= 30
            else "-1" if short_loses and index % 2
            else "1"
        )
        trades.append(trade)
        targets.append(replace(
            _outcome(
                trade,
                candidate_pnl=target_pnl,
                triggered=True,
                complete=not (unfilled and index == 39),
            ),
            rule_id="profit_target_at_1r",
        ))
        breakevens.append(_outcome(
            trade, candidate_pnl="0", triggered=True, complete=True
        ))
    return (
        tuple(trades),
        _profit_target_state(tuple(targets)),
        _state(tuple(breakevens)),
    )


def test_paired_one_r_profit_target_requires_absolute_profit_and_two_benchmarks() -> None:
    trades, target, breakeven = _profit_target_fixture()
    report = prospective_profit_target_one_r_comparison(
        trades, target, breakeven
    )
    assert report["frozen_start_ms"] == 1_000_000
    assert report["prospective_closed_trades"] == 40
    assert report["matched_trades"] == 40
    assert report["target_triggered_trades"] == 40
    assert report["target_full_ioc_closes"] == 40
    assert report["integrity_clean"] is True
    assert report["sample_complete"] is True
    assert report["economic_screen_passes"] is True
    assert report["overall"]["actual_net_pnl"] == "-80"
    assert report["overall"]["breakeven_net_pnl"] == "0"
    assert report["overall"]["target_net_pnl"] == "40"
    assert report["overall"]["target_vs_actual_pnl"] == "120"
    assert report["overall"]["target_vs_breakeven_pnl"] == "40"
    assert all(block["passes"] for block in report["chronological_blocks"])
    assert report["positive_robust_to_single_winner_and_market"] is True
    assert report["by_direction"]["short"]["target_net_pnl"] == "20"
    assert report["ready_for_review"] is False
    assert report["account_level_profitability_proven"] is False
    assert report["execution_authority"] is False


def test_paired_one_r_profit_target_rejects_late_loss_cluster() -> None:
    trades, target, breakeven = _profit_target_fixture(
        bad_late_block=True
    )
    report = prospective_profit_target_one_r_comparison(
        trades, target, breakeven
    )
    assert Decimal(report["overall"]["target_net_pnl"]) > 0
    assert Decimal(report["overall"]["target_vs_actual_pnl"]) > 0
    assert report["chronological_blocks"][-1]["target_net_pnl"] == "-10"
    assert report["chronological_blocks"][-1]["passes"] is False
    assert report["economic_screen_passes"] is False


def test_paired_one_r_profit_target_rejects_losing_short_exits() -> None:
    trades, target, breakeven = _profit_target_fixture(
        short_loses=True
    )
    report = prospective_profit_target_one_r_comparison(
        trades, target, breakeven
    )
    assert report["overall"]["target_net_pnl"] == "0"
    assert report["by_direction"]["short"]["target_net_pnl"] == "-20"
    assert report["economic_screen_passes"] is False


def test_paired_one_r_profit_target_never_counts_unfilled_exit() -> None:
    trades, target, breakeven = _profit_target_fixture(unfilled=True)
    report = prospective_profit_target_one_r_comparison(
        trades, target, breakeven
    )
    assert report["prospective_closed_trades"] == 40
    assert report["matched_trades"] == 39
    assert report["incomplete_trade_ids"] == [trades[-1].trade_id]
    assert report["integrity_clean"] is False
    assert report["economic_screen_passes"] is False


def test_paired_one_r_profit_target_rejects_missing_shadow_trade() -> None:
    trades, target, breakeven = _profit_target_fixture()
    target["outcomes"] = target["outcomes"][:-1]
    report = prospective_profit_target_one_r_comparison(
        trades, target, breakeven
    )
    assert report["missing_target_trade_ids"] == [trades[-1].trade_id]
    assert report["economic_screen_passes"] is False


def test_paired_one_r_profit_target_rejects_rule_or_config_drift() -> None:
    trades, target, breakeven = _profit_target_fixture()
    target["rules"] = [{
        "rule_id": "profit_target_at_1r",
        "activate_at_r": "0.8",
        "lock_at_r": "1",
        "exit_on_activation": "true",
    }]
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="rule identity drift",
    ):
        prospective_profit_target_one_r_comparison(
            trades, target, breakeven
        )
    target["rules"][0]["activate_at_r"] = "1"
    target["execution_config"] = {"config_version": "changed"}
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="execution cost/config drift",
    ):
        prospective_profit_target_one_r_comparison(
            trades, target, breakeven
        )


def test_paired_one_r_profit_target_counts_winners_sacrificed() -> None:
    winning = _trade(
        "target-existing-big-winner",
        opened_at_ms=1_100_000,
        pnl="5",
    )
    target = _profit_target_state((
        replace(
            _outcome(winning, candidate_pnl="1"),
            rule_id="profit_target_at_1r",
        ),
    ))
    baseline = _state((_outcome(winning, candidate_pnl="3"),))
    report = prospective_profit_target_one_r_comparison(
        (winning,), target, baseline
    )
    assert report["existing_winners_with_reduced_pnl"] == 1
    assert report["existing_winners_turned_into_losers"] == 0
    assert report["overall"]["target_vs_actual_pnl"] == "-4"
    assert report["overall"]["target_vs_breakeven_pnl"] == "-2"
    assert report["economic_screen_passes"] is False


def _one_half_target_state(
    outcomes: tuple[ProfitLockExecutionOutcome, ...],
    *,
    started_at_ms: int = 1_050_000,
) -> dict[str, object]:
    state = _profit_target_state(outcomes, started_at_ms=started_at_ms)
    state["rules"] = [{
        "rule_id": "profit_target_at_1_5r",
        "activate_at_r": "1.5",
        "lock_at_r": "1.5",
        "exit_on_activation": "true",
    }]
    return state


def test_precommitted_one_half_profit_target_is_positive_on_identical_trades() -> None:
    trades, target_one_r, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="2"),
            rule_id="profit_target_at_1_5r",
        )
        for trade in trades
    ))
    report = prospective_profit_target_threshold_comparison(
        trades, target_one_r, one_half, baseline
    )
    assert report["frozen_common_start_ms"] == 1_050_000
    assert report["same_complete_future_trade_cohort"] is True
    assert report["common_matched_trade_count"] == 40
    assert report["one_r_net_pnl_on_identical_trades"] == "40"
    assert report["one_half_r_net_pnl_on_identical_trades"] == "80"
    assert report["one_half_minus_one_r_net_pnl"] == "40"
    assert Decimal(report["one_half_minus_one_r_net_r"]) == Decimal("4")
    assert report["one_r"]["economic_screen_passes"] is True
    assert report["one_half_r"]["economic_screen_passes"] is True
    assert report["both_precommitted_economic_screens_pass"] is True
    assert report["selected_winning_threshold"] is None
    assert report["threshold_selected_by_hindsight"] is False
    assert report["ready_for_review"] is False
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False

    paired = report["same_trade_incremental_robustness"]
    assert paired is not None
    assert paired["overall"]["one_half_minus_one_r_pnl"] == "40"
    assert paired["by_direction"]["long"]["one_half_minus_one_r_pnl"] == "20"
    assert paired["by_direction"]["short"]["one_half_minus_one_r_pnl"] == "20"
    assert paired["incremental_economic_screen_passes"] is True
    assert report["higher_target_strict_incremental_screen_passes"] is True
    assert paired["threshold_selected"] is None


def test_one_half_exit_only_compares_same_complete_fill_cohort() -> None:
    trades, target_one_r, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(
                trade,
                candidate_pnl="2",
                complete=index != 39,
                triggered=True,
            ),
            rule_id="profit_target_at_1_5r",
        )
        for index, trade in enumerate(trades)
    ))
    report = prospective_profit_target_threshold_comparison(
        trades, target_one_r, one_half, baseline
    )
    assert report["one_r"]["matched_trades"] == 40
    assert report["one_half_r"]["matched_trades"] == 39
    assert report["common_matched_trade_count"] == 39
    assert report["same_complete_future_trade_cohort"] is False
    assert report["one_half_minus_one_r_net_pnl"] is None
    assert report["one_half_minus_one_r_net_r"] is None
    assert report["both_precommitted_economic_screens_pass"] is False

    assert report["same_trade_incremental_robustness"] is None
    assert report["higher_target_strict_incremental_screen_passes"] is False


def test_one_half_exit_rejects_winning_threshold_selected_by_rule_drift() -> None:
    trades, target_one_r, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="2"),
            rule_id="profit_target_at_1_5r",
        )
        for trade in trades
    ))
    one_half["rules"][0]["activate_at_r"] = "1.25"
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="rule identity drift",
    ):
        prospective_profit_target_threshold_comparison(
            trades, target_one_r, one_half, baseline
        )


def test_one_half_exit_requires_same_cost_model_on_both_shadow_targets() -> None:
    trades, target_one_r, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="2"),
            rule_id="profit_target_at_1_5r",
        )
        for trade in trades
    ))
    one_half["execution_config"] = {"config_version": "not-original"}
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="different execution cost models",
    ):
        prospective_profit_target_threshold_comparison(
            trades, target_one_r, one_half, baseline
        )


def test_one_half_exit_stays_absolute_unprofitable_when_large_winner_pnl_erased() -> None:
    trades, target_one_r, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(
                trade,
                candidate_pnl="-2" if index >= 30 else "2",
            ),
            rule_id="profit_target_at_1_5r",
        )
        for index, trade in enumerate(trades)
    ))
    review = prospective_profit_target_one_half_r_comparison(
        trades, one_half, baseline
    )
    assert review["candidate_id"] == "profit_target_at_1_5r"
    assert review["overall"]["target_net_pnl"] == "40"
    assert review["chronological_blocks"][-1]["passes"] is False
    assert review["economic_screen_passes"] is False
    comparison = prospective_profit_target_threshold_comparison(
        trades, target_one_r, one_half, baseline
    )
    assert comparison["same_complete_future_trade_cohort"] is True
    assert comparison["one_half_minus_one_r_net_pnl"] == "0"
    assert comparison["both_precommitted_economic_screens_pass"] is False


def test_profit_target_rejects_manipulated_pnl_even_with_consistent_r() -> None:
    trades, target, baseline = _profit_target_fixture()
    forged = target["outcomes"][0]
    original_trade = trades[0]
    forged["candidate_net_pnl_estimate"] = "500"
    forged["candidate_net_r_estimate"] = "50"
    forged["delta_net_pnl_estimate"] = str(
        Decimal("500") - original_trade.net_pnl
    )
    forged["delta_net_r_estimate"] = str(
        Decimal("50") - original_trade.net_r
    )
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="IOC cashflow does not reconcile",
    ):
        prospective_profit_target_one_r_comparison(trades, target, baseline)


def test_profit_target_rejects_forged_pnl_or_r_deltas() -> None:
    trades, target, baseline = _profit_target_fixture()
    target["outcomes"][0]["delta_net_pnl_estimate"] = "10000"
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="candidate delta",
    ):
        prospective_profit_target_one_r_comparison(trades, target, baseline)

    trades, target, baseline = _profit_target_fixture()
    target["outcomes"][0]["candidate_net_r_estimate"] = "500"
    target["outcomes"][0]["delta_net_r_estimate"] = str(
        Decimal("500") - trades[0].net_r
    )
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="net R does not reconcile",
    ):
        prospective_profit_target_one_r_comparison(trades, target, baseline)


def test_profit_target_rejects_impossible_ioc_event_timing() -> None:
    trades, target, baseline = _profit_target_fixture()
    target["outcomes"][0]["activation_timestamp_ms"] = (
        trades[0].opened_at_ms + 25_000
    )
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="trigger precedes activation",
    ):
        prospective_profit_target_one_r_comparison(trades, target, baseline)

    trades, target, baseline = _profit_target_fixture()
    target["outcomes"][0]["completion_timestamp_ms"] = (
        trades[0].closed_at_ms + 1
    )
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="completion precedes trigger or follows original close",
    ):
        prospective_profit_target_one_r_comparison(trades, target, baseline)


def test_profit_target_rejects_filled_quantity_exceeding_original_trade() -> None:
    trades, target, baseline = _profit_target_fixture()
    target["outcomes"][0]["simulated_filled_quantity"] = "2"
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="fills more than the original quantity",
    ):
        prospective_profit_target_one_r_comparison(trades, target, baseline)


def test_threshold_comparison_rejects_forged_one_half_r_payoff() -> None:
    trades, first, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="2"),
            rule_id="profit_target_at_1_5r",
        )
        for trade in trades
    ))
    one_half["outcomes"][0]["simulated_exit_fees"] = "99"
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="IOC cashflow does not reconcile",
    ):
        prospective_profit_target_threshold_comparison(
            trades, first, one_half, baseline
        )


def test_waiting_for_one_half_r_fails_late_negative_incremental_block() -> None:
    trades, first, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(
                trade, candidate_pnl="3" if index < 30 else "-1"
            ),
            rule_id="profit_target_at_1_5r",
        )
        for index, trade in enumerate(trades)
    ))
    result = prospective_profit_target_threshold_comparison(
        trades, first, one_half, baseline
    )
    review = result["same_trade_incremental_robustness"]
    assert review is not None
    assert Decimal(review["overall"]["one_half_minus_one_r_pnl"]) > 0
    assert review["chronological_blocks"][-1][
        "one_half_minus_one_r_pnl"
    ] == "-20"
    assert review["chronological_blocks"][-1]["passes"] is False
    assert review["chronological_consistency_passes"] is False
    assert review["incremental_economic_screen_passes"] is False
    assert result["higher_target_strict_incremental_screen_passes"] is False


def test_waiting_for_one_half_r_cannot_hide_losing_short_edge() -> None:
    trades, first, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(
                trade, candidate_pnl="4" if index % 2 == 0 else "0"
            ),
            rule_id="profit_target_at_1_5r",
        )
        for index, trade in enumerate(trades)
    ))
    result = prospective_profit_target_threshold_comparison(
        trades, first, one_half, baseline
    )
    review = result["same_trade_incremental_robustness"]
    assert review is not None
    assert Decimal(review["overall"]["one_half_minus_one_r_pnl"]) > 0
    assert review["by_direction"]["short"]["one_half_minus_one_r_pnl"] == "-20"
    assert review["direction_consistency_passes"] is False
    assert review["incremental_economic_screen_passes"] is False
    assert result["selected_winning_threshold"] is None


def test_one_big_late_winner_cannot_create_fake_durable_target_advantage() -> None:
    trades, first, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(
                trade, candidate_pnl="60" if index == 0 else "1"
            ),
            rule_id="profit_target_at_1_5r",
        )
        for index, trade in enumerate(trades)
    ))
    result = prospective_profit_target_threshold_comparison(
        trades, first, one_half, baseline
    )
    review = result["same_trade_incremental_robustness"]
    assert review is not None
    assert Decimal(review["overall"]["one_half_minus_one_r_pnl"]) > 0
    assert review["leave_largest_incremental_winner_out"][
        "one_half_minus_one_r_pnl"
    ] == "0"
    assert review["leave_one_out_consistency_passes"] is False
    assert review["incremental_economic_screen_passes"] is False


def test_single_market_target_outperformance_fails_market_holdout() -> None:
    trades, first, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(
                trade,
                candidate_pnl="3" if trade.market.canonical == "BTC" else "1",
            ),
            rule_id="profit_target_at_1_5r",
        )
        for trade in trades
    ))
    result = prospective_profit_target_threshold_comparison(
        trades, first, one_half, baseline
    )
    review = result["same_trade_incremental_robustness"]
    assert review is not None
    assert Decimal(review["overall"]["one_half_minus_one_r_pnl"]) > 0
    assert review["leave_one_market_out"]["BTC"][
        "one_half_minus_one_r_pnl"
    ] == "0"
    assert review["leave_one_out_consistency_passes"] is False
    assert result["higher_target_strict_incremental_screen_passes"] is False


def test_higher_target_cannot_trigger_before_lower_target() -> None:
    trades, first, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="2"),
            rule_id="profit_target_at_1_5r",
        )
        for trade in trades
    ))
    one_half["outcomes"][0]["trigger_timestamp_ms"] = (
        trades[0].opened_at_ms + 19_000
    )
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="1.5R target triggered before 1R",
    ):
        prospective_profit_target_threshold_comparison(
            trades, first, one_half, baseline
        )


def _trailing_profit_state(
    outcomes: tuple[ProfitLockExecutionOutcome, ...],
) -> dict[str, object]:
    state = _profit_target_state(outcomes, started_at_ms=1_050_000)
    state["rules"] = [{
        "rule_id": "trail_peak_after_1r_by_0_5r",
        "activate_at_r": "1",
        "lock_at_r": "0.5",
        "trail_by_r": "0.5",
    }]
    return state


def test_prospective_trailing_exit_requires_absolute_fee_adjusted_profit() -> None:
    trades, _one_r, baseline = _profit_target_fixture()
    trailing = _trailing_profit_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="2"),
            rule_id="trail_peak_after_1r_by_0_5r",
        )
        for trade in trades
    ))
    report = prospective_profit_trailing_comparison(
        trades, trailing, baseline
    )
    assert report["candidate_id"] == "trail_peak_after_1r_by_0_5r"
    assert report["frozen_start_ms"] == 1_050_000
    assert report["matched_trades"] == 40
    assert report["target_full_ioc_closes"] == 40
    assert report["overall"]["target_net_pnl"] == "80"
    assert report["by_direction"]["short"]["target_net_pnl"] == "40"
    assert report["economic_screen_passes"] is True
    assert report["execution_authority"] is False
    assert report["ready_for_review"] is False


def test_prospective_trailing_exit_rejects_losing_short_or_incomplete_book() -> None:
    trades, _one_r, baseline = _profit_target_fixture()
    trailing = _trailing_profit_state(tuple(
        replace(
            _outcome(
                trade,
                candidate_pnl="-1" if index % 2 else "2",
                complete=index != 39,
            ),
            rule_id="trail_peak_after_1r_by_0_5r",
        )
        for index, trade in enumerate(trades)
    ))
    report = prospective_profit_trailing_comparison(
        trades, trailing, baseline
    )
    assert report["matched_trades"] == 39
    assert report["integrity_clean"] is False
    assert report["economic_screen_passes"] is False


def test_prospective_trailing_exit_fails_frozen_gap_or_cost_drift() -> None:
    trades, _one_r, baseline = _profit_target_fixture()
    trailing = _trailing_profit_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="2"),
            rule_id="trail_peak_after_1r_by_0_5r",
        )
        for trade in trades
    ))
    trailing["rules"][0]["trail_by_r"] = "0.75"
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="frozen exit rule identity drift",
    ):
        prospective_profit_trailing_comparison(
            trades, trailing, baseline
        )
    trailing["rules"][0]["trail_by_r"] = "0.5"
    trailing["execution_config"] = {"config_version": "different"}
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="execution cost/config drift",
    ):
        prospective_profit_trailing_comparison(
            trades, trailing, baseline
        )


def _five_way_exit_fixture(
    *,
    trailing_pnl: tuple[str, ...] | None = None,
    trailing_unfilled: int | None = None,
) -> tuple[
    tuple[TradeJournalEntry, ...],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    trades, one_r, baseline = _profit_target_fixture()
    one_half = _one_half_target_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="2"),
            rule_id="profit_target_at_1_5r",
        )
        for trade in trades
    ))
    trailing = _trailing_profit_state(tuple(
        replace(
            _outcome(
                trade,
                candidate_pnl=(
                    "3" if trailing_pnl is None else trailing_pnl[index]
                ),
                complete=index != trailing_unfilled,
            ),
            rule_id="trail_peak_after_1r_by_0_5r",
        )
        for index, trade in enumerate(trades)
    ))
    return trades, one_r, one_half, trailing, baseline


def test_five_way_exit_grid_needs_identical_costed_trades_and_positive_controls() -> None:
    trades, one_r, one_half, trailing, baseline = (
        _five_way_exit_fixture()
    )
    report = prospective_profit_trailing_grid_comparison(
        trades, one_r, one_half, trailing, baseline
    )
    assert report["candidate_winner_selected"] is None
    assert report["threshold_selected_by_hindsight"] is False
    assert report["five_way_cohort_aligned"] is True
    assert report["common_matched_trade_count"] == 40
    assert report["prospective_closed_trades"] == 40
    assert report["frozen_common_start_ms"] == 1_050_000
    assert report["trailing_strict_cross_policy_screen_passes"] is True
    controls = report["trailing_vs_controls"]
    assert controls is not None
    assert controls["actual"]["overall"][
        "trailing_minus_benchmark_net_pnl"
    ] == "200"
    assert controls["breakeven"]["overall"][
        "trailing_minus_benchmark_net_pnl"
    ] == "120"
    assert controls["one_r"]["overall"][
        "trailing_minus_benchmark_net_pnl"
    ] == "80"
    assert controls["one_half_r"]["overall"][
        "trailing_minus_benchmark_net_pnl"
    ] == "40"
    assert controls["one_half_r"]["by_direction"]["long"][
        "trailing_minus_benchmark_net_pnl"
    ] == "20"
    assert controls["one_half_r"]["by_direction"]["short"][
        "trailing_minus_benchmark_net_pnl"
    ] == "20"
    assert len(controls["one_half_r"]["chronological_blocks"]) == 4
    assert controls["one_half_r"]["concentration_resilience_passes"] is True
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False
    assert report["ready_for_review"] is False
    assert report["account_level_profitability_proven"] is False


def test_five_way_exit_grid_must_beat_both_fixed_targets() -> None:
    trades, one_r, one_half, trailing, baseline = (
        _five_way_exit_fixture(trailing_pnl=("1.5",) * 40)
    )
    report = prospective_profit_trailing_grid_comparison(
        trades, one_r, one_half, trailing, baseline
    )
    assert report["five_way_cohort_aligned"] is True
    assert report["trailing_strict_cross_policy_screen_passes"] is False
    controls = report["trailing_vs_controls"]
    assert controls is not None
    assert controls["one_r"]["overall"]["trailing_beats_benchmark"] is True
    assert controls["one_half_r"]["overall"]["trailing_beats_benchmark"] is False
    assert report["candidate_winner_selected"] is None


def test_five_way_exit_grid_positive_total_cannot_hide_late_failed_period() -> None:
    trades, one_r, one_half, trailing, baseline = _five_way_exit_fixture(
        trailing_pnl=("3",) * 30 + ("1",) * 10
    )
    report = prospective_profit_trailing_grid_comparison(
        trades, one_r, one_half, trailing, baseline
    )
    controls = report["trailing_vs_controls"]
    assert controls is not None
    alternative = controls["one_half_r"]
    assert alternative["overall"]["trailing_minus_benchmark_net_pnl"] == "20"
    assert alternative["chronological_blocks"][-1]["passes"] is False
    assert alternative["chronological_blocks"][-1][
        "trailing_minus_benchmark_net_pnl"
    ] == "-10"
    assert alternative["time_consistency_passes"] is False
    assert report["trailing_strict_cross_policy_screen_passes"] is False


def test_five_way_exit_grid_positive_total_cannot_hide_losing_short_edge() -> None:
    trades, one_r, one_half, trailing, baseline = _five_way_exit_fixture(
        trailing_pnl=tuple(
            "4" if index % 2 == 0 else "1" for index in range(40)
        )
    )
    report = prospective_profit_trailing_grid_comparison(
        trades, one_r, one_half, trailing, baseline
    )
    controls = report["trailing_vs_controls"]
    assert controls is not None
    alternative = controls["one_half_r"]
    assert alternative["overall"]["trailing_minus_benchmark_net_pnl"] == "20"
    assert alternative["by_direction"]["short"][
        "trailing_minus_benchmark_net_pnl"
    ] == "-20"
    assert alternative["side_consistency_passes"] is False
    assert report["trailing_strict_cross_policy_screen_passes"] is False


def test_five_way_exit_grid_single_winner_cannot_mask_bad_broader_policy() -> None:
    trades, one_r, one_half, trailing, baseline = _five_way_exit_fixture(
        trailing_pnl=("50",) + ("2",) * 39
    )
    report = prospective_profit_trailing_grid_comparison(
        trades, one_r, one_half, trailing, baseline
    )
    controls = report["trailing_vs_controls"]
    assert controls is not None
    check = controls["one_half_r"]
    assert check["overall"]["trailing_minus_benchmark_net_pnl"] == "48"
    assert check["leave_largest_incremental_winner_out"][
        "trailing_minus_benchmark_net_pnl"
    ] == "0"
    assert check["concentration_resilience_passes"] is False
    assert report["trailing_strict_cross_policy_screen_passes"] is False


def test_five_way_exit_grid_missing_ioc_never_scores_smaller_lucky_cohort() -> None:
    trades, one_r, one_half, trailing, baseline = _five_way_exit_fixture(
        trailing_unfilled=39
    )
    report = prospective_profit_trailing_grid_comparison(
        trades, one_r, one_half, trailing, baseline
    )
    assert report["common_matched_trade_count"] == 39
    assert report["five_way_cohort_aligned"] is False
    assert report["trailing_vs_controls"] is None
    assert report["trailing_strict_cross_policy_screen_passes"] is False
    assert report["per_policy"]["trail_peak_after_1r_by_0_5r"][
        "integrity_clean"
    ] is False
    assert report["unmatched_trade_ids_by_policy"][
        "trail_peak_after_1r_by_0_5r"
    ] == [trades[39].trade_id]


def test_five_way_exit_grid_rejects_different_execution_cost_models() -> None:
    trades, one_r, one_half, trailing, baseline = (
        _five_way_exit_fixture()
    )
    trailing["execution_config"] = {"config_version": "different"}
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="five-way exit grid has different execution cost models",
    ):
        prospective_profit_trailing_grid_comparison(
            trades, one_r, one_half, trailing, baseline
        )


def test_five_way_exit_grid_rejects_forged_one_half_r_cashflow() -> None:
    trades, one_r, one_half, trailing, baseline = (
        _five_way_exit_fixture()
    )
    one_half["outcomes"][0]["candidate_net_pnl_estimate"] = "999"
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="candidate delta|IOC cashflow|net R",
    ):
        prospective_profit_trailing_grid_comparison(
            trades, one_r, one_half, trailing, baseline
        )


def _net_reserved_exit_state(
    trades: tuple[TradeJournalEntry, ...],
    *,
    candidates: tuple[str, ...] | None = None,
    incomplete: int | None = None,
) -> dict[str, object]:
    state = _trailing_profit_state(tuple(
        replace(
            _outcome(
                trade,
                candidate_pnl=(
                    "4" if candidates is None else candidates[index]
                ),
                complete=index != incomplete,
            ),
            rule_id="trail_peak_after_1r_by_0_5r_net_reserved_0_25r",
        )
        for index, trade in enumerate(trades)
    ))
    state["started_at_ms"] = 1_100_000
    state["rules"] = [{
        "rule_id": "trail_peak_after_1r_by_0_5r_net_reserved_0_25r",
        "activate_at_r": "1",
        "lock_at_r": "0.5",
        "trail_by_r": "0.5",
        "minimum_estimated_net_lock_r": "0.25",
    }]
    return state


def test_net_reserved_trailing_requires_true_positive_same_future_ioc_edge() -> None:
    trades, _one_r, baseline = _profit_target_fixture()
    older = _trailing_profit_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="3"),
            rule_id="trail_peak_after_1r_by_0_5r",
        )
        for trade in trades
    ))
    new = _net_reserved_exit_state(trades)
    report = prospective_net_reserved_trailing_comparison(
        trades, new, older, baseline
    )
    assert report["same_complete_cohort"] is True
    assert report["common_matched_trade_count"] == 40
    assert report["strict_incremental_screen_passes"] is True
    robust = report["incremental_robustness"]
    assert robust is not None
    assert robust["overall"]["trailing_minus_benchmark_net_pnl"] == "40"
    assert robust["by_direction"]["long"][
        "trailing_minus_benchmark_net_pnl"
    ] == "20"
    assert robust["by_direction"]["short"][
        "trailing_minus_benchmark_net_pnl"
    ] == "20"
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False
    assert report["ready_for_review"] is False
    assert report["selected_winner"] is None


def test_net_reserved_trailing_rejects_losing_short_increment() -> None:
    trades, _one_r, baseline = _profit_target_fixture()
    older = _trailing_profit_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="3"),
            rule_id="trail_peak_after_1r_by_0_5r",
        )
        for trade in trades
    ))
    new = _net_reserved_exit_state(
        trades,
        candidates=tuple(
            "6" if i % 2 == 0 else "2" for i in range(40)
        ),
    )
    report = prospective_net_reserved_trailing_comparison(
        trades, new, older, baseline
    )
    review = report["incremental_robustness"]
    assert review is not None
    assert review["by_direction"]["short"][
        "trailing_minus_benchmark_net_pnl"
    ] == "-20"
    assert report["strict_incremental_screen_passes"] is False


def test_net_reserved_trailing_incomplete_book_disables_pairing() -> None:
    trades, _one_r, baseline = _profit_target_fixture()
    older = _trailing_profit_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="3"),
            rule_id="trail_peak_after_1r_by_0_5r",
        )
        for trade in trades
    ))
    new = _net_reserved_exit_state(trades, incomplete=39)
    report = prospective_net_reserved_trailing_comparison(
        trades, new, older, baseline
    )
    assert report["same_complete_cohort"] is False
    assert report["common_matched_trade_count"] == 39
    assert report["incremental_robustness"] is None
    assert report["strict_incremental_screen_passes"] is False


def test_net_reserved_trailing_rejects_mutated_rule_and_costs() -> None:
    trades, _one_r, baseline = _profit_target_fixture()
    older = _trailing_profit_state(tuple(
        replace(
            _outcome(trade, candidate_pnl="3"),
            rule_id="trail_peak_after_1r_by_0_5r",
        )
        for trade in trades
    ))
    new = _net_reserved_exit_state(trades)
    new["rules"][0]["minimum_estimated_net_lock_r"] = "0.35"
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="frozen exit rule identity drift",
    ):
        prospective_net_reserved_trailing_comparison(
            trades, new, older, baseline
        )
    new["rules"][0]["minimum_estimated_net_lock_r"] = "0.25"
    new["execution_config"] = {"config_version": "drift"}
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="different execution cost models",
    ):
        prospective_net_reserved_trailing_comparison(
            trades, new, older, baseline
        )


def _entry_cost_r_cohort(
    state: ProspectiveEntryCostRState,
    *,
    blocked_pnl: str = "-2",
    retained_pnl: str = "5",
    blocked_quantity: str = "10",
) -> tuple[
    tuple[TradeJournalEntry, ...],
    dict[str, PaperOrderPlan],
]:
    config = PaperExecutionConfig()
    trades: list[TradeJournalEntry] = []
    plans: dict[str, PaperOrderPlan] = {}
    for i in range(40):
        blocked = i % 4 >= 2
        qty = Decimal(blocked_quantity if blocked else "2")
        direction = Direction.LONG if i % 2 == 0 else Direction.SHORT
        initial = _trade(
            f"cost-r-{i}",
            opened_at_ms=state.started_at_ms + 5_000 + i * 60_000,
            pnl=blocked_pnl if blocked else retained_pnl,
            market=("SOL", "BTC", "ADA", "ETH")[i % 4],
            direction=direction,
        )
        initial = replace(
            initial,
            filled_quantity=qty,
            initial_stop=(
                Decimal("90")
                if direction is Direction.LONG
                else Decimal("110")
            ),
            exit_price=(
                Decimal("100") + initial.net_pnl / qty
                if direction is Direction.LONG
                else Decimal("100") - initial.net_pnl / qty
            ),
        )
        plan = PaperOrderPlan(
            risk_decision_id=initial.risk_decision_id,
            strategy_decision_id=initial.strategy_decision_id,
            market=initial.market,
            side=(
                OrderSide.BUY
                if direction is Direction.LONG else OrderSide.SELL
            ),
            requested_quantity=qty,
            order_type=OrderType.MARKETABLE_IOC,
            reduce_only=False,
            execution_reference_price=Decimal("100"),
            max_slippage_bps=config.max_ioc_slippage_bps,
            stop_price=initial.initial_stop,
            approved_notional_ceiling=qty * Decimal("100"),
            created_at_ms=initial.opened_at_ms - 1_000,
            earliest_execution_ms=initial.opened_at_ms,
            execution_config_version=config.config_version,
            instrument_metadata_received_at_ms=initial.opened_at_ms - 2_000,
            approved_risk_amount_ceiling=Decimal("10"),
            stop_distance_fraction=Decimal("0.1"),
            effective_loss_fraction=Decimal("0.106"),
        )
        trade = replace(initial, opening_plan_id=plan.plan_id)
        trades.append(trade)
        plans[plan.plan_id] = plan
    return tuple(trades), plans


def test_frozen_entry_cost_r_gate_is_forward_only_both_sides_positive() -> None:
    config = PaperExecutionConfig()
    state = ProspectiveEntryCostRState.freeze(
        config, frozen_at_ms=1_000_000
    )
    assert state.started_at_ms == 2_800_000
    assert ProspectiveEntryCostRState.from_payload(state.payload()) == state
    trades, plans = _entry_cost_r_cohort(state)
    report = prospective_entry_cost_r_comparison(
        trades, plans.get, state, config
    )
    assert report["closed_prospective_trades"] == 40
    assert report["hypothetically_blocked_trades"] == 20
    assert report["retained_trades"] == 20
    assert report["blocked_actual_winners"] == 0
    assert report["blocked_actual_losers"] == 20
    assert report["overall"]["actual_net_pnl"] == "60"
    assert report["overall"]["candidate_net_pnl"] == "100"
    assert report["overall"]["delta_net_pnl"] == "40"
    assert report["overall"]["economics_ready"] is True
    assert report["by_direction"]["long"]["retained_trades"] == 10
    assert report["by_direction"]["short"]["retained_trades"] == 10
    assert all(
        period["passes"] is True
        for period in report["chronological_periods"]
    )
    assert report["strict_descriptive_screen_passes"] is True
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False
    assert report["selected_winner"] is None
    assert report["account_level_profitability_proven"] is False

    # Historical trades before the frozen scoring embargo cannot vote.
    old = replace(
        trades[0],
        opened_at_ms=state.frozen_at_ms - 100_000,
        closed_at_ms=state.frozen_at_ms - 40_000,
        holding_duration_ms=60_000,
    )
    report_with_old = prospective_entry_cost_r_comparison(
        (*trades, old), plans.get, state, config
    )
    assert report_with_old["closed_prospective_trades"] == 40


def test_entry_cost_r_gate_cannot_hide_valuable_blocked_winners() -> None:
    config = PaperExecutionConfig()
    state = ProspectiveEntryCostRState.freeze(
        config, frozen_at_ms=1_000_000
    )
    trades, plans = _entry_cost_r_cohort(
        state, blocked_pnl="7"
    )
    report = prospective_entry_cost_r_comparison(
        trades, plans.get, state, config
    )
    assert report["blocked_actual_winners"] == 20
    assert report["overall"]["delta_net_pnl"] == "-140"
    assert report["strict_descriptive_screen_passes"] is False


def test_entry_cost_r_gate_fails_closed_on_missing_or_forged_entry_plans() -> None:
    config = PaperExecutionConfig()
    state = ProspectiveEntryCostRState.freeze(
        config, frozen_at_ms=1_000_000
    )
    trades, plans = _entry_cost_r_cohort(state)
    with pytest.raises(
        ProspectiveEntryCostRError, match="missing original durable opening plan"
    ):
        prospective_entry_cost_r_comparison(
            trades, lambda _: None, state, config
        )
    original = plans[trades[0].opening_plan_id]
    altered = replace(original, requested_quantity=Decimal("20"))
    mutated = dict(plans)
    mutated[trades[0].opening_plan_id] = altered
    with pytest.raises(
        ProspectiveEntryCostRError, match="lineage or frozen cost drift"
    ):
        prospective_entry_cost_r_comparison(
            trades, mutated.get, state, config
        )
    altered_config = replace(
        config, max_ioc_slippage_bps=Decimal("20")
    )
    with pytest.raises(
        ProspectiveEntryCostRError, match="configuration drift"
    ):
        prospective_entry_cost_r_comparison(
            trades, plans.get, state, altered_config
        )


def test_entry_cost_r_gate_restore_rejects_hindsight_threshold_change() -> None:
    config = PaperExecutionConfig()
    state = ProspectiveEntryCostRState.freeze(
        config, frozen_at_ms=2_000_000
    )
    modified = state.payload()
    modified["max_predicted_round_trip_cost_r"] = "0.35"
    with pytest.raises(
        ProspectiveEntryCostRError, match="policy or cost reserve drift"
    ):
        ProspectiveEntryCostRState.from_payload(modified)
    modified = state.payload()
    modified["funding_reserve_per_hour"] = "0.00001"
    with pytest.raises(
        ProspectiveEntryCostRError, match="policy or cost reserve drift"
    ):
        ProspectiveEntryCostRState.from_payload(modified)


def test_frozen_profit_targets_preserve_tiny_positive_edge_under_cancellation() -> None:
    """Big offsetting booked trades must not erase real small after-cost gains."""
    from cocomelon.research.prospective_profit_target_one_r_comparison import (
        _economics as target_economics,
    )
    from cocomelon.research.prospective_profit_target_one_r_comparison import (
        _paired_threshold_economics as threshold_economics,
    )

    pairs = []
    for original, one_r, one_half_r, breakeven in (
        ("10000", "10000", "10000", "10000"),
        ("0.000000000000000000000001",
         "0.000000000000000000000001",
         "0.000000000000000000000002",
         "0.000000000000000000000001"),
        ("-10000", "-10000", "-10000", "-10000"),
    ):
        trade = SimpleNamespace(net_pnl=Decimal(original), net_r=Decimal(original))
        first = SimpleNamespace(
            candidate_net_pnl_estimate=Decimal(one_r),
            candidate_net_r_estimate=Decimal(one_r),
            triggered=True,
            simulated_close_complete=True,
        )
        second = SimpleNamespace(
            candidate_net_pnl_estimate=Decimal(one_half_r),
            candidate_net_r_estimate=Decimal(one_half_r),
            triggered=True,
            simulated_close_complete=True,
        )
        control = SimpleNamespace(
            candidate_net_pnl_estimate=Decimal(breakeven),
            candidate_net_r_estimate=Decimal(breakeven),
        )
        pairs.append((trade, first, second, control))

    one_r = target_economics(tuple(
        (trade, first, control) for trade, first, _, control in pairs
    ))
    assert one_r["actual_net_pnl"] == "1E-24"
    assert one_r["target_net_pnl"] == "1E-24"
    assert one_r["breakeven_net_pnl"] == "1E-24"

    one_half = target_economics(tuple(
        (trade, second, control) for trade, _, second, control in pairs
    ))
    assert one_half["target_net_pnl"] == "2E-24"
    assert one_half["target_vs_actual_pnl"] == "1E-24"
    assert one_half["target_beats_both_controls"] is True

    paired = threshold_economics(tuple(
        (trade, first, second) for trade, first, second, _ in pairs
    ))
    assert paired["one_r_net_pnl"] == "1E-24"
    assert paired["one_half_r_net_pnl"] == "2E-24"
    assert paired["one_half_minus_one_r_pnl"] == "1E-24"
    assert paired["one_half_minus_one_r_net_r"] == "1E-24"
    assert paired["waiting_beats_one_r_net"] is True



def test_breakeven_exit_shadow_rejects_candidate_net_r_inflation() -> None:
    # Deliberately preserve booked candidate dollars and its internally
    # consistent incremental R while forging +5R from a -5-dollar close.
    trade = _trade(
        "inflated-r", opened_at_ms=EMBARGO_MS + 10, pnl="-5"
    )
    good = _outcome(trade, candidate_pnl="-5")
    altered_r = Decimal("5")
    bad = replace(
        good,
        candidate_net_r_estimate=altered_r,
        delta_net_r_estimate=altered_r - trade.net_r,
    )
    with pytest.raises(
        ProspectiveBreakevenProfitLockError, match="candidate net-R differs"
    ):
        prospective_breakeven_profit_lock_summary(
            (trade,), _state((bad,)),
            ProspectiveBreakevenProfitLockState(frozen_at_ms=0),
        )


def test_breakeven_shadow_accepts_small_arithmetic_precision_residual() -> None:
    trade = _trade(
        "precision", opened_at_ms=EMBARGO_MS + 10,
        pnl="-5.0000000000000000000000000001"
    )
    good = _outcome(trade, candidate_pnl="0")
    # The underlying execution computes Decimal in ordinary context,
    # preserving a booked 1E-28 residue. Economically material changes
    # cannot pass the 1E-18 source precision bound.
    assert good.candidate_net_pnl_estimate == Decimal("0")
    assert good.delta_net_pnl_estimate is not None
    source = ProfitLockExecutionOutcome.from_payload(good.payload())
    assert source == good
    report = prospective_breakeven_profit_lock_summary(
        (trade,), _state((good,)),
        ProspectiveBreakevenProfitLockState(frozen_at_ms=0),
    )
    assert report["economically_evaluated_trades"] == 1
    assert report["readiness"]["ready_for_review"] is False
