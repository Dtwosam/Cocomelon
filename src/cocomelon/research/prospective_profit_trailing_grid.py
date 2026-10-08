from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.profit_lock_execution_shadow import ProfitLockExecutionOutcome
from cocomelon.research.prospective_profit_target_one_r_comparison import (
    BREAKEVEN_RULE_ID,
    CHRONOLOGICAL_BLOCKS,
    MIN_BLOCK_TRADES,
    MIN_DIRECTION_TRADES,
    MIN_MARKETS,
    MIN_PAIRED_TRADES,
    MIN_PROFIT_TARGET_FULL_CLOSES,
    MIN_PROFIT_TARGET_TRIGGERS,
    TAKE_PROFIT_ONE_HALF_RULE_ID,
    TAKE_PROFIT_RULE_ID,
    TRAILING_PROFIT_RULE_ID,
    ProspectiveProfitTargetComparisonError,
    _prospective_profit_target_comparison,
    _verified_outcomes,
)

ZERO: Final = Decimal("0")
POLICY_IDS: Final = (
    TAKE_PROFIT_RULE_ID,
    TAKE_PROFIT_ONE_HALF_RULE_ID,
    TRAILING_PROFIT_RULE_ID,
    BREAKEVEN_RULE_ID,
)


def _economics(
    rows: Sequence[
        tuple[TradeJournalEntry, ProfitLockExecutionOutcome, Decimal, Decimal]
    ],
) -> dict[str, object]:
    """Trailing versus one precommitted control on exactly identical trades."""
    candidate_pnl = ZERO
    candidate_r = ZERO
    control_pnl = ZERO
    control_r = ZERO
    winner_reduced = 0
    loser_rescued = 0
    for _trade, candidate, benchmark_pnl, benchmark_r in rows:
        pnl = candidate.candidate_net_pnl_estimate
        net_r = candidate.candidate_net_r_estimate
        if pnl is None or net_r is None:
            raise ProspectiveProfitTargetComparisonError(
                "paired trailing outcome has missing net executable economics"
            )
        candidate_pnl += pnl
        candidate_r += net_r
        control_pnl += benchmark_pnl
        control_r += benchmark_r
        winner_reduced += int(
            benchmark_pnl > ZERO and pnl < benchmark_pnl
        )
        loser_rescued += int(
            benchmark_pnl <= ZERO and pnl > ZERO
        )
    return {
        "trades": len(rows),
        "trailing_net_pnl": str(candidate_pnl),
        "trailing_net_r": str(candidate_r),
        "benchmark_net_pnl": str(control_pnl),
        "benchmark_net_r": str(control_r),
        "trailing_minus_benchmark_net_pnl": str(
            candidate_pnl - control_pnl
        ),
        "trailing_minus_benchmark_net_r": str(
            candidate_r - control_r
        ),
        "benchmark_winners_reduced_by_trailing": winner_reduced,
        "benchmark_losers_recovered_by_trailing": loser_rescued,
        "trailing_absolutely_profitable": (
            bool(rows) and candidate_pnl > ZERO and candidate_r > ZERO
        ),
        "trailing_beats_benchmark": (
            bool(rows)
            and candidate_pnl > control_pnl
            and candidate_r > control_r
        ),
    }


def _verified_net_cashflow(
    outcome: ProfitLockExecutionOutcome,
) -> tuple[Decimal, Decimal]:
    pnl = outcome.candidate_net_pnl_estimate
    net_r = outcome.candidate_net_r_estimate
    if pnl is None or net_r is None:
        raise ProspectiveProfitTargetComparisonError(
            "complete five-way exit grid has missing cashflow"
        )
    return pnl, net_r


def _robust_pair(
    cohort: Sequence[
        tuple[TradeJournalEntry, ProfitLockExecutionOutcome, Decimal, Decimal]
    ],
) -> dict[str, object]:
    rows = tuple(cohort)
    overall = _economics(rows)
    markets = sorted({row[0].market.canonical for row in rows})
    by_side = {
        side: _economics(tuple(
            row for row in rows if row[0].direction.value == side
        ))
        for side in ("long", "short")
    }
    blocks: list[dict[str, object]] = []
    for i in range(CHRONOLOGICAL_BLOCKS):
        subset = rows[
            len(rows) * i // CHRONOLOGICAL_BLOCKS:
            len(rows) * (i + 1) // CHRONOLOGICAL_BLOCKS
        ]
        economics = _economics(subset)
        blocks.append({
            "block": i + 1,
            "first_opened_at_ms": (
                subset[0][0].opened_at_ms if subset else None
            ),
            "last_opened_at_ms": (
                subset[-1][0].opened_at_ms if subset else None
            ),
            **economics,
            "passes": (
                len(subset) >= MIN_BLOCK_TRADES
                and economics["trailing_absolutely_profitable"] is True
                and economics["trailing_beats_benchmark"] is True
            ),
        })
    largest_delta = (
        None if not rows else max(
            rows,
            key=lambda row: (
                row[1].candidate_net_pnl_estimate - row[2]
                if row[1].candidate_net_pnl_estimate is not None
                else ZERO,
                row[0].trade_id,
            ),
        )[0].trade_id
    )
    without_largest = _economics(tuple(
        row for row in rows if row[0].trade_id != largest_delta
    ))
    without_market = {
        market: _economics(tuple(
            row for row in rows if row[0].market.canonical != market
        ))
        for market in markets
    }
    def positive(value: dict[str, object]) -> bool:
        return (
            value["trailing_absolutely_profitable"] is True
            and value["trailing_beats_benchmark"] is True
        )
    side_ok = all(
        sum(row[0].direction.value == side for row in rows)
        >= MIN_DIRECTION_TRADES
        and positive(economics)
        for side, economics in by_side.items()
    )
    time_ok = all(item["passes"] is True for item in blocks)
    robust = (
        len(markets) >= MIN_MARKETS
        and positive(without_largest)
        and all(positive(economics) for economics in without_market.values())
    )
    return {
        "overall": overall,
        "by_direction": by_side,
        "chronological_blocks": blocks,
        "leave_largest_incremental_winner_out": without_largest,
        "leave_one_market_out": without_market,
        "side_consistency_passes": side_ok,
        "time_consistency_passes": time_ok,
        "concentration_resilience_passes": robust,
        "strict_paired_economic_screen_passes": (
            positive(overall) and side_ok and time_ok and robust
        ),
    }


def prospective_profit_trailing_grid_comparison(
    trades: Sequence[TradeJournalEntry],
    one_r_state: object,
    one_half_r_state: object,
    trailing_state: object,
    breakeven_state: object,
) -> dict[str, object]:
    """Do not compare policies on unequal cohorts or retrospectively select a winner."""
    states = {
        TAKE_PROFIT_RULE_ID: one_r_state,
        TAKE_PROFIT_ONE_HALF_RULE_ID: one_half_r_state,
        TRAILING_PROFIT_RULE_ID: trailing_state,
        BREAKEVEN_RULE_ID: breakeven_state,
    }
    verified = {
        name: _verified_outcomes(state, rule_id=name)
        for name, state in states.items()
    }
    costs = [verified[name][2]["execution_config"] for name in POLICY_IDS]
    if any(cost != costs[0] for cost in costs[1:]):
        raise ProspectiveProfitTargetComparisonError(
            "five-way exit grid has different execution cost models"
        )
    common_start = max(verified[name][0] for name in POLICY_IDS)
    comparison = {
        name: _prospective_profit_target_comparison(
            trades,
            states[name],
            breakeven_state,
            target_rule_id=name,
            scoring_started_at_ms=common_start,
        )
        for name in (
            TAKE_PROFIT_RULE_ID,
            TAKE_PROFIT_ONE_HALF_RULE_ID,
            TRAILING_PROFIT_RULE_ID,
        )
    }
    ids: dict[str, list[str]] = {}
    for name, item in comparison.items():
        raw_ids = item["paired_trade_ids"]
        if not isinstance(raw_ids, list) or not all(
            isinstance(trade_id, str) for trade_id in raw_ids
        ):
            raise ProspectiveProfitTargetComparisonError(
                "five-way grid missing paired trade identities"
            )
        ids[name] = raw_ids
    cohorts = [set(value) for value in ids.values()]
    intersection = set.intersection(*cohorts)
    original_ids = ids[TAKE_PROFIT_RULE_ID]
    aligned = (
        all(value == original_ids for value in ids.values())
        and all(
            item["integrity_clean"] is True
            and len(original_ids) == item["prospective_closed_trades"]
            for item in comparison.values()
        )
    )
    benchmarks: dict[str, object] | None = None
    strict = False
    if aligned:
        trade_by_id = {trade.trade_id: trade for trade in trades}
        if len(trade_by_id) != len(trades):
            raise ProspectiveProfitTargetComparisonError(
                "five-way exit grid journal contains duplicate trade ids"
            )
        paired = tuple(
            (
                trade_by_id[trade_id],
                verified[TAKE_PROFIT_RULE_ID][1][trade_id],
                verified[TAKE_PROFIT_ONE_HALF_RULE_ID][1][trade_id],
                verified[TRAILING_PROFIT_RULE_ID][1][trade_id],
                verified[BREAKEVEN_RULE_ID][1][trade_id],
            )
            for trade_id in original_ids
        )
        for _trade, one_r, one_half, _trailing, _breakeven in paired:
            if one_half.triggered and (
                not one_r.triggered
                or (
                    one_r.trigger_timestamp_ms is not None
                    and one_half.trigger_timestamp_ms is not None
                    and one_half.trigger_timestamp_ms
                    < one_r.trigger_timestamp_ms
                )
            ):
                raise ProspectiveProfitTargetComparisonError(
                    "1.5R target triggered before 1R on same trade"
                )
        raw_controls: Mapping[
            str, tuple[tuple[Decimal, Decimal], ...]
        ] = {
            "actual": tuple(
                (trade.net_pnl, trade.net_r)
                for trade, _, _, _, _ in paired
            ),
            "breakeven": tuple(
                _verified_net_cashflow(base)
                for _, _, _, _, base in paired
            ),
            "one_r": tuple(
                _verified_net_cashflow(fixed)
                for _, fixed, _, _, _ in paired
            ),
            "one_half_r": tuple(
                _verified_net_cashflow(fixed)
                for _, _, fixed, _, _ in paired
            ),
        }
        benchmarks = {}
        for name, values in raw_controls.items():
            rows = tuple(
                (trade, trailing, pnl, net_r)
                for (trade, _, _, trailing, _), (pnl, net_r)
                in zip(paired, values, strict=True)
            )
            benchmarks[name] = _robust_pair(rows)

        markets = {trade.market.canonical for trade, *_ in paired}
        sample_complete = (
            len(paired) >= MIN_PAIRED_TRADES
            and len(markets) >= MIN_MARKETS
            and all(
                sum(trade.direction.value == side for trade, *_ in paired)
                >= MIN_DIRECTION_TRADES
                for side in ("long", "short")
            )
            and sum(trailing.triggered for _, _, _, trailing, _ in paired)
            >= MIN_PROFIT_TARGET_TRIGGERS
            and sum(
                trailing.triggered and trailing.simulated_close_complete
                for _, _, _, trailing, _ in paired
            ) >= MIN_PROFIT_TARGET_FULL_CLOSES
        )
        strict = (
            sample_complete
            and all(
                review["strict_paired_economic_screen_passes"] is True
                for review in benchmarks.values()
            )
            and comparison[TRAILING_PROFIT_RULE_ID][
                "economic_screen_passes"
            ] is True
        )
    return {
        "schema_version": 1,
        "candidate_id": TRAILING_PROFIT_RULE_ID,
        "comparison_scope": "exact_same_future_closed_trades",
        "frozen_common_start_ms": common_start,
        "candidate_winner_selected": None,
        "threshold_selected_by_hindsight": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready_for_review": False,
        "account_level_profitability_proven": False,
        "prospective_closed_trades": comparison[TRAILING_PROFIT_RULE_ID][
            "prospective_closed_trades"
        ],
        "common_matched_trade_count": len(intersection),
        "five_way_cohort_aligned": aligned,
        "unmatched_trade_ids_by_policy": {
            name: sorted(set.union(*cohorts) - set(value))
            for name, value in ids.items()
        },
        "per_policy": comparison,
        "trailing_vs_controls": benchmarks,
        "trailing_strict_cross_policy_screen_passes": strict,
        "warning": (
            "The precommitted trailing rule is never selected or promoted "
            "from this matched-trade comparison. Even positive evidence is "
            "not an executable capacity-reflow portfolio nor a prospective "
            "policy-switching trial. Original LONG/SHORT entries and exits "
            "remain unchanged."
        ),
    }
