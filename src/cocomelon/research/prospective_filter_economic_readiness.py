from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry

ZERO: Final = Decimal("0")


class ProspectiveFilterEconomicReadinessError(RuntimeError):
    pass


def _minimum(values: tuple[Decimal, ...]) -> str | None:
    return None if not values else str(min(values))


def prospective_filter_economic_readiness(
    items: Sequence[tuple[TradeJournalEntry, bool]],
) -> dict[str, object]:
    values = tuple(items)
    trade_ids = tuple(trade.trade_id for trade, _blocked in values)
    if len(set(trade_ids)) != len(trade_ids):
        raise ProspectiveFilterEconomicReadinessError(
            "filter economics contain duplicate trade ids"
        )

    actual_pnl = tuple(trade.net_pnl for trade, _blocked in values)
    actual_r = tuple(trade.net_r for trade, _blocked in values)
    candidate_pnl = tuple(
        ZERO if blocked else trade.net_pnl
        for trade, blocked in values
    )
    candidate_r = tuple(
        ZERO if blocked else trade.net_r
        for trade, blocked in values
    )
    delta_pnl = tuple(
        candidate - actual
        for candidate, actual in zip(
            candidate_pnl,
            actual_pnl,
            strict=True,
        )
    )
    delta_r = tuple(
        candidate - actual
        for candidate, actual in zip(
            candidate_r,
            actual_r,
            strict=True,
        )
    )

    total_actual_pnl = sum(actual_pnl, ZERO)
    total_actual_r = sum(actual_r, ZERO)
    total_candidate_pnl = sum(candidate_pnl, ZERO)
    total_candidate_r = sum(candidate_r, ZERO)
    total_delta_pnl = sum(delta_pnl, ZERO)
    total_delta_r = sum(delta_r, ZERO)

    leave_trade_candidate_pnl = tuple(
        total_candidate_pnl - value for value in candidate_pnl
    )
    leave_trade_candidate_r = tuple(
        total_candidate_r - value for value in candidate_r
    )
    leave_trade_delta_pnl = tuple(
        total_delta_pnl - value for value in delta_pnl
    )
    leave_trade_delta_r = tuple(
        total_delta_r - value for value in delta_r
    )

    by_market_candidate_pnl: dict[str, Decimal] = defaultdict(
        lambda: ZERO
    )
    by_market_candidate_r: dict[str, Decimal] = defaultdict(
        lambda: ZERO
    )
    by_market_delta_pnl: dict[str, Decimal] = defaultdict(
        lambda: ZERO
    )
    by_market_delta_r: dict[str, Decimal] = defaultdict(
        lambda: ZERO
    )
    for index, (trade, _blocked) in enumerate(values):
        market = trade.market.canonical
        by_market_candidate_pnl[market] += candidate_pnl[index]
        by_market_candidate_r[market] += candidate_r[index]
        by_market_delta_pnl[market] += delta_pnl[index]
        by_market_delta_r[market] += delta_r[index]

    leave_market_candidate_pnl = tuple(
        total_candidate_pnl - value
        for value in by_market_candidate_pnl.values()
    )
    leave_market_candidate_r = tuple(
        total_candidate_r - value
        for value in by_market_candidate_r.values()
    )
    leave_market_delta_pnl = tuple(
        total_delta_pnl - value
        for value in by_market_delta_pnl.values()
    )
    leave_market_delta_r = tuple(
        total_delta_r - value
        for value in by_market_delta_r.values()
    )

    candidate_profitable = (
        total_candidate_pnl > ZERO
        and total_candidate_r > ZERO
    )
    improvement_positive = (
        total_delta_pnl > ZERO
        and total_delta_r > ZERO
    )
    candidate_single_trade_robust = (
        len(values) >= 2
        and min(leave_trade_candidate_pnl, default=ZERO) > ZERO
        and min(leave_trade_candidate_r, default=ZERO) > ZERO
    )
    candidate_single_market_robust = (
        len(by_market_candidate_pnl) >= 2
        and min(leave_market_candidate_pnl, default=ZERO) > ZERO
        and min(leave_market_candidate_r, default=ZERO) > ZERO
    )
    delta_single_trade_robust = (
        len(values) >= 2
        and min(leave_trade_delta_pnl, default=ZERO) > ZERO
        and min(leave_trade_delta_r, default=ZERO) > ZERO
    )
    delta_single_market_robust = (
        len(by_market_delta_pnl) >= 2
        and min(leave_market_delta_pnl, default=ZERO) > ZERO
        and min(leave_market_delta_r, default=ZERO) > ZERO
    )

    return {
        "actual_net_pnl": str(total_actual_pnl),
        "actual_net_r": str(total_actual_r),
        "candidate_net_pnl": str(total_candidate_pnl),
        "candidate_net_r": str(total_candidate_r),
        "delta_net_pnl": str(total_delta_pnl),
        "delta_net_r": str(total_delta_r),
        "candidate_profitable": candidate_profitable,
        "improvement_positive": improvement_positive,
        "candidate_leave_one_trade_out_min_pnl": _minimum(
            leave_trade_candidate_pnl
        ),
        "candidate_leave_one_trade_out_min_r": _minimum(
            leave_trade_candidate_r
        ),
        "candidate_single_trade_robust": (
            candidate_single_trade_robust
        ),
        "candidate_leave_one_market_out_min_pnl": _minimum(
            leave_market_candidate_pnl
        ),
        "candidate_leave_one_market_out_min_r": _minimum(
            leave_market_candidate_r
        ),
        "candidate_single_market_robust": (
            candidate_single_market_robust
        ),
        "delta_leave_one_trade_out_min_pnl": _minimum(
            leave_trade_delta_pnl
        ),
        "delta_leave_one_trade_out_min_r": _minimum(
            leave_trade_delta_r
        ),
        "delta_single_trade_robust": delta_single_trade_robust,
        "delta_leave_one_market_out_min_pnl": _minimum(
            leave_market_delta_pnl
        ),
        "delta_leave_one_market_out_min_r": _minimum(
            leave_market_delta_r
        ),
        "delta_single_market_robust": delta_single_market_robust,
        "market_count": len(by_market_candidate_pnl),
        "economics_ready": (
            candidate_profitable
            and improvement_positive
            and candidate_single_trade_robust
            and candidate_single_market_robust
            and delta_single_trade_robust
            and delta_single_market_robust
        ),
    }
