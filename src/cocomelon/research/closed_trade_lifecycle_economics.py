from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal, localcontext
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore

ZERO: Final = Decimal("0")
QUARTER_R: Final = Decimal("0.25")
HALF_R: Final = Decimal("0.5")
ONE_R: Final = Decimal("1")
MIN_SETUP_TRADES: Final = 20
MIN_BLOCK_TRADES: Final = 10


class ClosedTradeLifecycleEconomicsError(RuntimeError):
    pass


def _verified_setup(
    trade: TradeJournalEntry,
    fact_store: EvaluationFactStore,
) -> tuple[str, str, str, bool]:
    if trade.replay_run_id is None:
        return "unknown", "unknown", "unknown", False
    fact = fact_store.load_decision_by_strategy_id(
        trade.strategy_decision_id, trade.replay_run_id
    )
    if fact is None:
        return "unknown", "unknown", "unknown", False
    if (
        fact.market != trade.market
        or fact.direction is not trade.direction
        or fact.feature_snapshot_id != trade.feature_snapshot_id
        or fact.timestamp_ms > trade.opened_at_ms
    ):
        raise ClosedTradeLifecycleEconomicsError(
            "closed trade setup has inconsistent or future decision lineage"
        )
    return (
        fact.lead_strategy or "unknown",
        fact.trend_regime.value,
        fact.volatility_regime.value,
        True,
    )


def _complete_mfe(trade: TradeJournalEntry) -> Decimal | None:
    # Excursion is known only AFTER entry/exit. Never use it as an entry feature.
    if (
        trade.mfe is None
        or trade.mae is None
        or not trade.mfe.complete
        or not trade.mae.complete
        or trade.mfe.r_multiple is None
        or trade.mae.r_multiple is None
    ):
        return None
    return trade.mfe.r_multiple


def _sum(values: Sequence[Decimal]) -> Decimal:
    return sum(values, ZERO)


def _cohort(
    items: Sequence[TradeJournalEntry],
) -> dict[str, object]:
    trades = tuple(sorted(
        items, key=lambda t: (t.closed_at_ms, t.opened_at_ms, t.trade_id)
    ))
    count = len(trades)
    gross = _sum(tuple(t.gross_realized_pnl for t in trades))
    fees = _sum(tuple(t.entry_fees + t.exit_fees for t in trades))
    funding = _sum(tuple(t.funding_cash_pnl for t in trades))
    net = _sum(tuple(t.net_pnl for t in trades))
    net_r = _sum(tuple(t.net_r for t in trades))
    entry_slippage = _sum(tuple(t.entry_slippage_amount for t in trades))
    exit_slippage = _sum(tuple(t.exit_slippage_amount for t in trades))
    slippage = entry_slippage + exit_slippage
    losses = tuple(t for t in trades if t.net_pnl < ZERO)
    complete = tuple(t for t in trades if _complete_mfe(t) is not None)
    no_initial_move = tuple(
        t for t in losses
        if (mfe := _complete_mfe(t)) is not None and mfe < QUARTER_R
    )
    gave_back = tuple(
        t for t in losses
        if (mfe := _complete_mfe(t)) is not None and mfe >= HALF_R
    )
    gave_back_one_r = tuple(
        t for t in gave_back
        if (mfe := _complete_mfe(t)) is not None and mfe >= ONE_R
    )
    fee_flips = tuple(
        t for t in trades
        if t.gross_realized_pnl > ZERO and t.net_pnl <= ZERO
    )
    first = trades[: count // 2]
    second = trades[count // 2 :]
    first_pnl = _sum(tuple(t.net_pnl for t in first))
    second_pnl = _sum(tuple(t.net_pnl for t in second))
    best_win = max(
        (t.net_pnl for t in trades if t.net_pnl > ZERO),
        default=ZERO,
    )
    markets = len({t.market.canonical for t in trades})
    # A retrospective profile is never an executable, frozen challenger.
    # This flag merely identifies profiles worth independently forward-testing.
    sufficient = (
        count >= MIN_SETUP_TRADES
        and len(first) >= MIN_BLOCK_TRADES
        and len(second) >= MIN_BLOCK_TRADES
        and markets >= 2
        and len(complete) * 5 >= count * 4
    )
    worth_forward_testing = (
        sufficient
        and net > ZERO
        and net_r > ZERO
        and first_pnl > ZERO
        and second_pnl > ZERO
        and net - best_win > ZERO
    )
    return {
        "trades": count,
        "wins": sum(t.net_pnl > ZERO for t in trades),
        "losses": len(losses),
        "unique_markets": markets,
        "net_pnl": str(net),
        "gross_realized_pnl": str(gross),
        "signed_slippage": str(slippage),
        "entry_signed_slippage": str(entry_slippage),
        "exit_signed_slippage": str(exit_slippage),
        "reference_gross_pnl": str(gross + slippage),
        "fees": str(fees),
        "funding_cash_pnl": str(funding),
        "net_reconciliation_residual": str(net - (gross - fees + funding)),
        "mean_net_r": None if not count else str(net_r / Decimal(count)),
        "complete_excursion_trades": len(complete),
        "incomplete_excursion_trades": count - len(complete),
        "loss_without_0_25r_favorable_mark": len(no_initial_move),
        "loss_without_0_25r_net_pnl": str(_sum(tuple(
            t.net_pnl for t in no_initial_move
        ))),
        "loss_after_0_5r_favorable_mark": len(gave_back),
        "loss_after_0_5r_net_pnl": str(_sum(tuple(
            t.net_pnl for t in gave_back
        ))),
        "loss_after_1r_favorable_mark": len(gave_back_one_r),
        "gross_winners_flipped_by_fees_and_funding": len(fee_flips),
        "peak_to_close_mean_r": (
            None if not complete else str(
                _sum(tuple(
                    max(ZERO, _complete_mfe(t) - t.net_r)  # type: ignore[operator]
                    for t in complete
                )) / Decimal(len(complete))
            )
        ),
        "chronological_first_half_net_pnl": str(first_pnl),
        "chronological_second_half_net_pnl": str(second_pnl),
        "net_pnl_without_largest_winner": str(net - best_win),
        "minimum_profile_trades": MIN_SETUP_TRADES,
        "sufficient_for_retrospective_profile": sufficient,
        "worth_independent_forward_test": worth_forward_testing,
    }


def _holding_bucket(trade: TradeJournalEntry) -> str:
    # Observed close time only; never an ex-ante entry feature.
    if trade.holding_duration_ms < 300_000:
        return "under_5m"
    if trade.holding_duration_ms < 900_000:
        return "5_to_15m"
    if trade.holding_duration_ms < 3_600_000:
        return "15_to_60m"
    return "60m_plus"


def _closed_trade_lifecycle_economics_precise(
    trades: Sequence[TradeJournalEntry],
    fact_store: EvaluationFactStore,
) -> dict[str, object]:
    items = tuple(trades)
    if len({t.trade_id for t in items}) != len(items):
        raise ClosedTradeLifecycleEconomicsError(
            "duplicate closed trade IDs in lifecycle economics"
        )

    by_setup: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    by_regime: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    by_exit: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    by_side: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    by_holding: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    unattributed = 0
    for trade in items:
        strategy, trend, volatility, matched = _verified_setup(
            trade, fact_store
        )
        if not matched:
            unattributed += 1
        side = trade.direction.value
        by_setup[f"{side} | {strategy}"].append(trade)
        by_regime[f"{side} | {trend} | {volatility}"].append(trade)
        by_exit[f"{side} | {trade.exit_reason}"].append(trade)
        by_side[side].append(trade)
        by_holding[f"{side} | {_holding_bucket(trade)}"].append(trade)

    def groups(
        cohorts: dict[str, list[TradeJournalEntry]],
    ) -> dict[str, dict[str, object]]:
        return {
            name: _cohort(cohorts[name])
            for name in sorted(cohorts)
        }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": "closed_trade_entry_exit_and_cost_attribution_v1",
        "caution": (
            "MFE/MAE and actual exit/holding time are post-entry observations. "
            "Mark excursions are not executable limit or stop fills; do not "
            "backfit entry filters or exit triggers using future outcomes. "
            "Any change requires separately frozen, prospective, paired "
            "fill-aware net-PnL validation and robustness."
        ),
        "decision_fact_attribution_misses": unattributed,
        "overall": _cohort(items),
        "by_side": groups(by_side),
        "by_side_and_holding_duration": groups(by_holding),
        "by_side_and_lead_strategy": groups(by_setup),
        "by_side_and_regime": groups(by_regime),
        "by_side_and_exit_reason": groups(by_exit),
    }


def closed_trade_lifecycle_economics(
    trades: Sequence[TradeJournalEntry],
        fact_store: EvaluationFactStore,
) -> dict[str, object]:
    """Aggregate unrounded journal decimals before checking cohort parity."""
    with localcontext(prec=96):
        return _closed_trade_lifecycle_economics_precise(trades, fact_store)
