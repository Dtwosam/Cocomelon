from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.profit_lock_counterfactual import (
    DEFAULT_PROFIT_LOCK_COSTS,
    DEFAULT_PROFIT_LOCK_RULES,
)
from cocomelon.research.profit_lock_execution_shadow import (
    EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
    ProfitLockExecutionOutcome,
)

ZERO: Final = Decimal("0")
TAKE_PROFIT_RULE_ID: Final = "profit_target_at_1r"
TAKE_PROFIT_ONE_HALF_RULE_ID: Final = "profit_target_at_1_5r"
BREAKEVEN_RULE_ID: Final = "breakeven_after_0_5r"
MIN_PAIRED_TRADES: Final = 40
MIN_DIRECTION_TRADES: Final = 10
MIN_MARKETS: Final = 4
MIN_PROFIT_TARGET_TRIGGERS: Final = 10
MIN_PROFIT_TARGET_FULL_CLOSES: Final = 5
CHRONOLOGICAL_BLOCKS: Final = 4
MIN_BLOCK_TRADES: Final = 10


class ProspectiveProfitTargetComparisonError(RuntimeError):
    pass


def _verified_outcomes(
    state: object,
    *,
    rule_id: str,
) -> tuple[int, dict[str, ProfitLockExecutionOutcome], dict[str, object]]:
    if not isinstance(state, Mapping):
        raise ProspectiveProfitTargetComparisonError(
            "shadow state must be an object"
        )
    if state.get("schema_version") != EXECUTION_SHADOW_STATE_SCHEMA_VERSION:
        raise ProspectiveProfitTargetComparisonError(
            "shadow state schema mismatch"
        )
    if rule_id == TAKE_PROFIT_RULE_ID:
        expected_rules = [{
            "rule_id": TAKE_PROFIT_RULE_ID,
            "activate_at_r": "1",
            "lock_at_r": "1",
            "exit_on_activation": "true",
        }]
    elif rule_id == TAKE_PROFIT_ONE_HALF_RULE_ID:
        expected_rules = [{
            "rule_id": TAKE_PROFIT_ONE_HALF_RULE_ID,
            "activate_at_r": "1.5",
            "lock_at_r": "1.5",
            "exit_on_activation": "true",
        }]
    elif rule_id == BREAKEVEN_RULE_ID:
        expected_rules = [{
            "rule_id": rule.rule_id,
            "activate_at_r": str(rule.activate_at_r),
            "lock_at_r": str(rule.lock_at_r),
        } for rule in DEFAULT_PROFIT_LOCK_RULES]
    else:
        raise ProspectiveProfitTargetComparisonError(
            "unsupported frozen exit candidate"
        )
    if state.get("rules") != expected_rules:
        raise ProspectiveProfitTargetComparisonError(
            "frozen exit rule identity drift"
        )
    started_at_ms = state.get("started_at_ms")
    if type(started_at_ms) is not int or started_at_ms < 0:
        raise ProspectiveProfitTargetComparisonError(
            "shadow started_at_ms is invalid"
        )
    raw_outcomes = state.get("outcomes")
    if not isinstance(raw_outcomes, list):
        raise ProspectiveProfitTargetComparisonError(
            "shadow outcomes must be an array"
        )
    selected: dict[str, ProfitLockExecutionOutcome] = {}
    for raw in raw_outcomes:
        outcome = ProfitLockExecutionOutcome.from_payload(raw)
        if (
            rule_id in {TAKE_PROFIT_RULE_ID, TAKE_PROFIT_ONE_HALF_RULE_ID}
            and outcome.rule_id != rule_id
        ):
            raise ProspectiveProfitTargetComparisonError(
                "profit target state contains other rules"
            )
        if outcome.rule_id != rule_id:
            continue
        if outcome.trade_id in selected:
            raise ProspectiveProfitTargetComparisonError(
                "shadow contains duplicate closed trade"
            )
        selected[outcome.trade_id] = outcome

    integrity: dict[str, object] = {}
    for name in (
        "lineage_mismatch_closed_trades",
        "orphaned_restored_positions",
    ):
        count = state.get(name)
        if type(count) is not int or count < 0:
            raise ProspectiveProfitTargetComparisonError(
                "shadow integrity counter is invalid"
            )
        integrity[name] = count
    config = state.get("execution_config")
    if not isinstance(config, dict):
        raise ProspectiveProfitTargetComparisonError(
            "shadow execution config is missing"
        )
    integrity["execution_config"] = config
    return started_at_ms, selected, integrity


def _verify_trade_exit_cashflow(
    trade: TradeJournalEntry,
    outcome: ProfitLockExecutionOutcome,
) -> None:
    """Reject corrupted or economically impossible restored exit evidence.

    The frozen IOC shadow calculates every complete close from filled price,
    entry/exit fees and a duration-sensitive funding reserve. Recompute the
    cashflow here rather than trusting a persisted candidate PnL number.
    """
    if trade.initial_risk_amount <= ZERO:
        raise ProspectiveProfitTargetComparisonError(
            "paired exit has non-positive initial risk"
        )
    activated = outcome.activation_timestamp_ms
    triggered = outcome.trigger_timestamp_ms
    completed = outcome.completion_timestamp_ms
    if activated is not None and not (
        trade.opened_at_ms <= activated <= trade.closed_at_ms
    ):
        raise ProspectiveProfitTargetComparisonError(
            "paired exit activation outside original position lifetime"
        )
    if triggered is not None and (
        activated is None or not activated <= triggered <= trade.closed_at_ms
    ):
        raise ProspectiveProfitTargetComparisonError(
            "paired exit trigger precedes activation or original close"
        )
    if completed is not None and (
        triggered is None or not triggered <= completed <= trade.closed_at_ms
    ):
        raise ProspectiveProfitTargetComparisonError(
            "paired exit completion precedes trigger or follows original close"
        )
    if outcome.simulated_filled_quantity > trade.filled_quantity:
        raise ProspectiveProfitTargetComparisonError(
            "paired exit fills more than the original quantity"
        )
    if outcome.no_fill_count > outcome.attempt_count:
        raise ProspectiveProfitTargetComparisonError(
            "paired exit no-fill count exceeds attempts"
        )

    candidate_pnl = outcome.candidate_net_pnl_estimate
    candidate_r = outcome.candidate_net_r_estimate
    if candidate_pnl is None or candidate_r is None:
        return
    if (
        outcome.delta_net_pnl_estimate != candidate_pnl - trade.net_pnl
        or outcome.delta_net_r_estimate != candidate_r - trade.net_r
    ):
        raise ProspectiveProfitTargetComparisonError(
            "paired exit candidate delta does not reconcile to journal"
        )
    if not outcome.triggered:
        return
    if candidate_r != candidate_pnl / trade.initial_risk_amount:
        raise ProspectiveProfitTargetComparisonError(
            "paired exit net R does not reconcile to planned risk"
        )
    exit_price = outcome.simulated_average_exit_price
    if not outcome.simulated_close_complete or exit_price is None or completed is None:
        raise ProspectiveProfitTargetComparisonError(
            "paired exit claims candidate PnL without a complete IOC fill"
        )
    elapsed_ms = max(1, completed - trade.opened_at_ms)
    funding_reserve = (
        trade.entry_price
        * trade.filled_quantity
        * DEFAULT_PROFIT_LOCK_COSTS.funding_reserve_fraction_per_hour
        * Decimal(elapsed_ms)
        / Decimal(3_600_000)
    )
    gross = (
        (exit_price - trade.entry_price) * trade.filled_quantity
        if trade.direction.value == "long"
        else (trade.entry_price - exit_price) * trade.filled_quantity
    )
    expected_net = (
        gross - trade.entry_fees - outcome.simulated_exit_fees
        - funding_reserve
    )
    # Weighted average fill price can be rounded at Decimal precision.
    tolerance = max(
        Decimal("1e-12"),
        abs(trade.entry_price * trade.filled_quantity) * Decimal("1e-24"),
    )
    if abs(candidate_pnl - expected_net) > tolerance:
        raise ProspectiveProfitTargetComparisonError(
            "paired exit IOC cashflow does not reconcile to filled price, "
            "fees and funding reserve"
        )


def _economics(
    pairs: Sequence[
        tuple[TradeJournalEntry, ProfitLockExecutionOutcome, ProfitLockExecutionOutcome]
    ],
) -> dict[str, object]:
    actual_pnl = sum((trade.net_pnl for trade, _, _ in pairs), ZERO)
    actual_r = sum((trade.net_r for trade, _, _ in pairs), ZERO)
    target_pnl = sum(
        (target.candidate_net_pnl_estimate for _, target, _ in pairs
         if target.candidate_net_pnl_estimate is not None),
        ZERO,
    )
    target_r = sum(
        (target.candidate_net_r_estimate for _, target, _ in pairs
         if target.candidate_net_r_estimate is not None),
        ZERO,
    )
    breakeven_pnl = sum(
        (breakeven.candidate_net_pnl_estimate for _, _, breakeven in pairs
         if breakeven.candidate_net_pnl_estimate is not None),
        ZERO,
    )
    breakeven_r = sum(
        (breakeven.candidate_net_r_estimate for _, _, breakeven in pairs
         if breakeven.candidate_net_r_estimate is not None),
        ZERO,
    )
    return {
        "trades": len(pairs),
        "actual_net_pnl": str(actual_pnl),
        "target_net_pnl": str(target_pnl),
        "breakeven_net_pnl": str(breakeven_pnl),
        "target_vs_actual_pnl": str(target_pnl - actual_pnl),
        "target_vs_breakeven_pnl": str(target_pnl - breakeven_pnl),
        "actual_net_r": str(actual_r),
        "target_net_r": str(target_r),
        "breakeven_net_r": str(breakeven_r),
        "target_vs_actual_r": str(target_r - actual_r),
        "target_vs_breakeven_r": str(target_r - breakeven_r),
        "target_absolutely_profitable": (
            bool(pairs) and target_pnl > ZERO and target_r > ZERO
        ),
        "target_beats_both_controls": (
            bool(pairs)
            and target_pnl > actual_pnl
            and target_r > actual_r
            and target_pnl > breakeven_pnl
            and target_r > breakeven_r
        ),
    }


def prospective_profit_target_one_r_comparison(
    trades: Sequence[TradeJournalEntry],
    target_shadow_state: object,
    breakeven_shadow_state: object,
) -> dict[str, object]:
    return _prospective_profit_target_comparison(
        trades,
        target_shadow_state,
        breakeven_shadow_state,
        target_rule_id=TAKE_PROFIT_RULE_ID,
    )


def prospective_profit_target_one_half_r_comparison(
    trades: Sequence[TradeJournalEntry],
    target_shadow_state: object,
    breakeven_shadow_state: object,
) -> dict[str, object]:
    return _prospective_profit_target_comparison(
        trades,
        target_shadow_state,
        breakeven_shadow_state,
        target_rule_id=TAKE_PROFIT_ONE_HALF_RULE_ID,
    )


def _prospective_profit_target_comparison(
    trades: Sequence[TradeJournalEntry],
    target_shadow_state: object,
    breakeven_shadow_state: object,
    *,
    target_rule_id: str,
    scoring_started_at_ms: int | None = None,
) -> dict[str, object]:
    target_start, target_outcomes, target_integrity = _verified_outcomes(
        target_shadow_state, rule_id=target_rule_id
    )
    breakeven_start, breakeven_outcomes, breakeven_integrity = _verified_outcomes(
        breakeven_shadow_state, rule_id=BREAKEVEN_RULE_ID
    )
    if (
        target_integrity["execution_config"]
        != breakeven_integrity["execution_config"]
    ):
        raise ProspectiveProfitTargetComparisonError(
            "paired shadow execution cost/config drift"
        )
    overlap_start = max(
        target_start,
        breakeven_start,
        0 if scoring_started_at_ms is None else scoring_started_at_ms,
    )
    journal = tuple(trades)
    trade_by_id = {trade.trade_id: trade for trade in journal}
    if len(trade_by_id) != len(journal):
        raise ProspectiveProfitTargetComparisonError(
            "journal contains duplicate trade identity"
        )
    prospective = tuple(
        sorted(
            (trade for trade in journal if trade.opened_at_ms >= overlap_start),
            key=lambda trade: (
                trade.opened_at_ms, trade.closed_at_ms, trade.trade_id
            ),
        )
    )
    prospective_ids = {trade.trade_id for trade in prospective}
    missing_target = sorted(prospective_ids - target_outcomes.keys())
    missing_breakeven = sorted(prospective_ids - breakeven_outcomes.keys())
    orphan_target = sorted(target_outcomes.keys() - trade_by_id.keys())
    orphan_breakeven = sorted(
        breakeven_outcomes.keys() - trade_by_id.keys()
    )
    matched: list[
        tuple[TradeJournalEntry, ProfitLockExecutionOutcome, ProfitLockExecutionOutcome]
    ] = []
    incomplete: list[str] = []
    for trade in prospective:
        target = target_outcomes.get(trade.trade_id)
        baseline = breakeven_outcomes.get(trade.trade_id)
        if target is None or baseline is None:
            continue
        for outcome in (target, baseline):
            if (
                outcome.opening_plan_id != trade.opening_plan_id
                or outcome.market != trade.market.canonical
                or outcome.direction != trade.direction.value
                or outcome.actual_net_pnl != trade.net_pnl
                or outcome.actual_net_r != trade.net_r
            ):
                raise ProspectiveProfitTargetComparisonError(
                    "paired exit journal provenance drift"
                )
            _verify_trade_exit_cashflow(trade, outcome)
            if outcome.triggered:
                if (
                    not outcome.simulated_close_complete
                    or outcome.candidate_source != "visible_book_ioc"
                    or outcome.completion_timestamp_ms is None
                    or outcome.trigger_timestamp_ms is None
                    or outcome.simulated_filled_quantity
                    != trade.filled_quantity
                    or outcome.simulated_average_exit_price is None
                    or outcome.attempt_count <= 0
                    or not (
                        trade.opened_at_ms
                        <= outcome.trigger_timestamp_ms
                        <= outcome.completion_timestamp_ms
                        <= trade.closed_at_ms
                    )
                ):
                    incomplete.append(trade.trade_id)
                    continue
            elif outcome.candidate_source != "actual_close":
                raise ProspectiveProfitTargetComparisonError(
                    "untriggered exit cannot claim a simulated fill"
                )
        if (
            target.candidate_net_pnl_estimate is None
            or target.candidate_net_r_estimate is None
            or baseline.candidate_net_pnl_estimate is None
            or baseline.candidate_net_r_estimate is None
        ):
            incomplete.append(trade.trade_id)
            continue
        if trade.trade_id not in incomplete:
            matched.append((trade, target, baseline))

    pairs = tuple(matched)
    totals = _economics(pairs)
    direction = {
        side: _economics(tuple(
            pair for pair in pairs if pair[0].direction.value == side
        ))
        for side in ("long", "short")
    }
    markets = sorted({trade.market.canonical for trade, _, _ in pairs})
    blocks: list[dict[str, object]] = []
    for index in range(CHRONOLOGICAL_BLOCKS):
        low = len(pairs) * index // CHRONOLOGICAL_BLOCKS
        high = len(pairs) * (index + 1) // CHRONOLOGICAL_BLOCKS
        portion = pairs[low:high]
        detail = _economics(portion)
        blocks.append({
            "block": index + 1,
            "first_opened_at_ms": (
                None if not portion else portion[0][0].opened_at_ms
            ),
            "last_opened_at_ms": (
                None if not portion else portion[-1][0].opened_at_ms
            ),
            **detail,
            "passes": (
                len(portion) >= MIN_BLOCK_TRADES
                and detail["target_absolutely_profitable"] is True
                and detail["target_beats_both_controls"] is True
            ),
        })
    target_triggered = sum(target.triggered for _, target, _ in pairs)
    target_complete = sum(
        target.triggered and target.simulated_close_complete
        for _, target, _ in pairs
    )
    winners_sacrificed = sum(
        trade.net_pnl > ZERO
        and target.candidate_net_pnl_estimate is not None
        and target.candidate_net_pnl_estimate < trade.net_pnl
        for trade, target, _ in pairs
    )
    winner_to_loser = sum(
        trade.net_pnl > ZERO
        and target.candidate_net_pnl_estimate is not None
        and target.candidate_net_pnl_estimate <= ZERO
        for trade, target, _ in pairs
    )
    saved_losers = sum(
        trade.net_pnl <= ZERO
        and target.candidate_net_pnl_estimate is not None
        and target.candidate_net_pnl_estimate > ZERO
        for trade, target, _ in pairs
    )
    best_winner_removed = tuple(
        pair for pair in pairs
        if pair[0].trade_id != (
            max(
                pairs,
                key=lambda p: (
                    p[1].candidate_net_pnl_estimate or ZERO,
                    p[0].trade_id,
                ),
            )[0].trade_id
            if pairs else None
        )
    )
    market_without = tuple(
        _economics(tuple(
            pair for pair in pairs
            if pair[0].market.canonical != market
        ))
        for market in markets
    )
    trade_without = _economics(best_winner_removed)
    robust = (
        len(markets) >= 2
        and trade_without["target_absolutely_profitable"] is True
        and trade_without["target_beats_both_controls"] is True
        and all(
            item["target_absolutely_profitable"] is True
            and item["target_beats_both_controls"] is True
            for item in market_without
        )
    )
    complete_integrity = (
        not missing_target
        and not missing_breakeven
        and not orphan_target
        and not orphan_breakeven
        and not incomplete
        and all(
            integrity["lineage_mismatch_closed_trades"] == 0
            and integrity["orphaned_restored_positions"] == 0
            for integrity in (target_integrity, breakeven_integrity)
        )
    )
    sample_complete = (
        len(pairs) >= MIN_PAIRED_TRADES
        and len(markets) >= MIN_MARKETS
        and all(
            sum(trade.direction.value == side for trade, _, _ in pairs)
            >= MIN_DIRECTION_TRADES
            for side in ("long", "short")
        )
        and target_triggered >= MIN_PROFIT_TARGET_TRIGGERS
        and target_complete >= MIN_PROFIT_TARGET_FULL_CLOSES
    )
    economic_screen = (
        complete_integrity
        and sample_complete
        and totals["target_absolutely_profitable"] is True
        and totals["target_beats_both_controls"] is True
        and all(
            item["target_absolutely_profitable"] is True
            for item in direction.values()
        )
        and all(block["passes"] is True for block in blocks)
        and robust
    )
    return {
        "schema_version": 1,
        "candidate_id": target_rule_id,
        "benchmark_id": BREAKEVEN_RULE_ID,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready_for_review": False,
        "account_level_profitability_proven": False,
        "comparison_scope": "identical_future_closed_trade_cohort",
        "frozen_start_ms": overlap_start,
        "profit_target_shadow_started_at_ms": target_start,
        "breakeven_shadow_started_at_ms": breakeven_start,
        "prospective_closed_trades": len(prospective),
        "matched_trades": len(pairs),
        "paired_trade_ids": [trade.trade_id for trade, _, _ in pairs],
        "observed_markets": len(markets),
        "target_triggered_trades": target_triggered,
        "target_full_ioc_closes": target_complete,
        "missing_target_trade_ids": missing_target,
        "missing_breakeven_trade_ids": missing_breakeven,
        "orphan_target_trade_ids": orphan_target,
        "orphan_breakeven_trade_ids": orphan_breakeven,
        "incomplete_trade_ids": sorted(set(incomplete)),
        "integrity_clean": complete_integrity,
        "sample_complete": sample_complete,
        "economic_screen_passes": economic_screen,
        "existing_winners_with_reduced_pnl": winners_sacrificed,
        "existing_winners_turned_into_losers": winner_to_loser,
        "existing_losers_recovered_as_winners": saved_losers,
        "overall": totals,
        "by_direction": direction,
        "chronological_blocks": blocks,
        "leave_biggest_winner_out": trade_without,
        "leave_one_market_out": list(market_without),
        "positive_robust_to_single_winner_and_market": robust,
        "required_paired_trades": MIN_PAIRED_TRADES,
        "required_direction_trades": MIN_DIRECTION_TRADES,
        "required_markets": MIN_MARKETS,
        "required_target_triggers": MIN_PROFIT_TARGET_TRIGGERS,
        "required_target_full_closes": MIN_PROFIT_TARGET_FULL_CLOSES,
        "warning": (
            "Matched original entries and shadow exits are not a "
            "replay of portfolio capital reflow, displaced opportunity "
            "fills, overlapping positions or account-level drawdown. "
            "Partial fills and missing exits are never counted as winners; "
            "all execution authority and policy promotion remain disabled."
        ),
    }


def prospective_profit_target_threshold_comparison(
    trades: Sequence[TradeJournalEntry],
    one_r_shadow_state: object,
    one_half_r_shadow_state: object,
    breakeven_shadow_state: object,
) -> dict[str, object]:
    """Freeze both profit targets on exactly the same future trade IDs.

    The two thresholds are precommitted independent hypotheses, not
    alternative fills to cherry-pick on each position.
    """
    first_start, _first_outcomes, first_integrity = _verified_outcomes(
        one_r_shadow_state, rule_id=TAKE_PROFIT_RULE_ID
    )
    later_start, _later_outcomes, later_integrity = _verified_outcomes(
        one_half_r_shadow_state, rule_id=TAKE_PROFIT_ONE_HALF_RULE_ID
    )
    breakeven_start, _baseline_outcomes, baseline_integrity = (
        _verified_outcomes(
            breakeven_shadow_state, rule_id=BREAKEVEN_RULE_ID
        )
    )
    if not (
        first_integrity["execution_config"]
        == later_integrity["execution_config"]
        == baseline_integrity["execution_config"]
    ):
        raise ProspectiveProfitTargetComparisonError(
            "profit target grid uses different execution cost models"
        )
    frozen_start = max(
        first_start, later_start, breakeven_start
    )
    one_r = _prospective_profit_target_comparison(
        trades,
        one_r_shadow_state,
        breakeven_shadow_state,
        target_rule_id=TAKE_PROFIT_RULE_ID,
        scoring_started_at_ms=frozen_start,
    )
    one_half = _prospective_profit_target_comparison(
        trades,
        one_half_r_shadow_state,
        breakeven_shadow_state,
        target_rule_id=TAKE_PROFIT_ONE_HALF_RULE_ID,
        scoring_started_at_ms=frozen_start,
    )
    one_r_ids = one_r["paired_trade_ids"]
    later_ids = one_half["paired_trade_ids"]
    if not isinstance(one_r_ids, list) or not isinstance(later_ids, list):
        raise ProspectiveProfitTargetComparisonError(
            "paired exit source trade identities unavailable"
        )
    common_pair_ids = set(one_r_ids).intersection(later_ids)
    pair_alignment_clean = (
        one_r_ids == later_ids
        and one_r["integrity_clean"] is True
        and one_half["integrity_clean"] is True
        and len(one_r_ids) == one_r["prospective_closed_trades"]
        and len(later_ids) == one_half["prospective_closed_trades"]
    )
    # Do not subtract results from mismatched fill-complete subsets.
    one_r_pnl: Decimal | None = None
    one_half_pnl: Decimal | None = None
    net_increment: Decimal | None = None
    one_r_net_r: Decimal | None = None
    one_half_net_r: Decimal | None = None
    r_increment: Decimal | None = None
    if pair_alignment_clean:
        original = one_r["overall"]
        alternative = one_half["overall"]
        if not isinstance(original, dict) or not isinstance(alternative, dict):
            raise ProspectiveProfitTargetComparisonError(
                "paired exit economics must be objects"
            )
        if (
            original["actual_net_pnl"] != alternative["actual_net_pnl"]
            or original["actual_net_r"] != alternative["actual_net_r"]
            or original["breakeven_net_pnl"] != alternative["breakeven_net_pnl"]
            or original["breakeven_net_r"] != alternative["breakeven_net_r"]
        ):
            raise ProspectiveProfitTargetComparisonError(
                "frozen baseline differs across the two target horizons"
            )
        one_r_pnl = Decimal(str(original["target_net_pnl"]))
        one_half_pnl = Decimal(str(alternative["target_net_pnl"]))
        one_r_net_r = Decimal(str(original["target_net_r"]))
        one_half_net_r = Decimal(str(alternative["target_net_r"]))
        net_increment = one_half_pnl - one_r_pnl
        r_increment = one_half_net_r - one_r_net_r

    return {
        "schema_version": 1,
        "candidate_grid": [TAKE_PROFIT_RULE_ID, TAKE_PROFIT_ONE_HALF_RULE_ID],
        "selected_winning_threshold": None,
        "threshold_selected_by_hindsight": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready_for_review": False,
        "account_level_profitability_proven": False,
        "frozen_common_start_ms": frozen_start,
        "common_matched_trade_count": len(common_pair_ids),
        "same_complete_future_trade_cohort": pair_alignment_clean,
        "one_r": one_r,
        "one_half_r": one_half,
        "one_r_net_pnl_on_identical_trades": (
            None if one_r_pnl is None else str(one_r_pnl)
        ),
        "one_half_r_net_pnl_on_identical_trades": (
            None if one_half_pnl is None else str(one_half_pnl)
        ),
        "one_half_minus_one_r_net_pnl": (
            None if net_increment is None else str(net_increment)
        ),
        "one_r_net_r_on_identical_trades": (
            None if one_r_net_r is None else str(one_r_net_r)
        ),
        "one_half_r_net_r_on_identical_trades": (
            None if one_half_net_r is None else str(one_half_net_r)
        ),
        "one_half_minus_one_r_net_r": (
            None if r_increment is None else str(r_increment)
        ),
        "both_precommitted_economic_screens_pass": (
            pair_alignment_clean
            and one_r["economic_screen_passes"] is True
            and one_half["economic_screen_passes"] is True
        ),
        "warning": (
            "Do not choose whichever take-profit threshold wins this "
            "historical or prospective sample for active trading. Each "
            "exit remains an unpromoted hypothesis until a separately "
            "frozen post-selection account-level paper portfolio trial "
            "proves positive profit after realistic fees, funding, "
            "slippage, and risk-capital capacity effects."
        ),
    }
