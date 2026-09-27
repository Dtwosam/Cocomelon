from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.execution.accounting import PaperPosition

ZERO: Final = Decimal("0")
MIN_CLOSED_TRADES_FOR_REVIEW: Final = 30
MIN_SOLO_TRADES_FOR_REVIEW: Final = 10
MIN_OVERLAP_TRADES_FOR_REVIEW: Final = 10


class ClosedTradeEntryConcurrencyError(RuntimeError):
    pass


def _profit_factor(
    trades: Sequence[TradeJournalEntry],
) -> Decimal | None:
    gross_profit = sum(
        (trade.net_pnl for trade in trades if trade.net_pnl > ZERO),
        ZERO,
    )
    gross_loss = -sum(
        (trade.net_pnl for trade in trades if trade.net_pnl < ZERO),
        ZERO,
    )
    if gross_loss == ZERO:
        return None
    if gross_profit == ZERO:
        return ZERO
    return gross_profit / gross_loss


def _summary(
    trades: Sequence[TradeJournalEntry],
) -> dict[str, object]:
    items = tuple(trades)
    count = len(items)
    net_pnl = sum((trade.net_pnl for trade in items), ZERO)
    total_r = sum((trade.net_r for trade in items), ZERO)
    pf = _profit_factor(items)
    return {
        "trades": count,
        "wins": sum(1 for trade in items if trade.net_pnl > ZERO),
        "losses": sum(1 for trade in items if trade.net_pnl < ZERO),
        "breakeven": sum(1 for trade in items if trade.net_pnl == ZERO),
        "net_pnl": str(net_pnl),
        "mean_net_r": (
            None if count == 0 else str(total_r / Decimal(count))
        ),
        "profit_factor": None if pf is None else str(pf),
    }


def _bucket(count: int) -> str:
    if count < 0:
        raise ValueError("concurrency count must be non-negative")
    if count >= 3:
        return "3+"
    return str(count)


def _closed_identity(
    trade: TradeJournalEntry,
) -> tuple[str, int, int]:
    return trade.trade_id, trade.opened_at_ms, trade.closed_at_ms


def closed_trade_entry_concurrency(
    trades: Sequence[TradeJournalEntry],
    open_positions: Sequence[PaperPosition] = (),
) -> dict[str, object]:
    items = tuple(trades)
    trade_ids = [trade.trade_id for trade in items]
    if len(trade_ids) != len(set(trade_ids)):
        raise ClosedTradeEntryConcurrencyError(
            "duplicate closed trade id"
        )

    open_plan_ids = [
        position.opening_plan_id for position in open_positions
    ]
    if len(open_plan_ids) != len(set(open_plan_ids)):
        raise ClosedTradeEntryConcurrencyError(
            "duplicate open position opening plan id"
        )

    closed_intervals = tuple(
        (_closed_identity(trade), trade)
        for trade in items
    )

    buckets: dict[str, list[TradeJournalEntry]] = {
        "0": [],
        "1": [],
        "2": [],
        "3+": [],
    }
    same_side_buckets: dict[str, list[TradeJournalEntry]] = {
        "0": [],
        "1+": [],
    }
    observations: list[dict[str, object]] = []

    for trade in items:
        already_open: list[tuple[str, str]] = []

        for (other_id, opened_ms, closed_ms), other in closed_intervals:
            if other_id == trade.trade_id:
                continue
            if (
                opened_ms < trade.opened_at_ms
                and trade.opened_at_ms < closed_ms
            ):
                already_open.append(
                    (other_id, other.direction.value)
                )

        for position in open_positions:
            if position.opened_at_ms < trade.opened_at_ms:
                already_open.append(
                    (
                        position.opening_plan_id,
                        position.side.value,
                    )
                )

        identities = [identity for identity, _ in already_open]
        if len(identities) != len(set(identities)):
            raise ClosedTradeEntryConcurrencyError(
                "duplicate overlapping lifecycle identity"
            )

        concurrency = len(already_open)
        same_side = sum(
            1
            for _, side in already_open
            if side == trade.direction.value
        )
        bucket = _bucket(concurrency)
        same_side_bucket = "0" if same_side == 0 else "1+"
        buckets[bucket].append(trade)
        same_side_buckets[same_side_bucket].append(trade)
        observations.append(
            {
                "trade_id": trade.trade_id,
                "market": trade.market.canonical,
                "direction": trade.direction.value,
                "opened_at_ms": trade.opened_at_ms,
                "already_open_positions": concurrency,
                "same_side_already_open_positions": same_side,
                "concurrency_bucket": bucket,
                "same_side_bucket": same_side_bucket,
            }
        )

    solo = tuple(buckets["0"])
    overlapping = tuple(
        trade
        for key in ("1", "2", "3+")
        for trade in buckets[key]
    )
    missing_total = max(
        0,
        MIN_CLOSED_TRADES_FOR_REVIEW - len(items),
    )
    missing_solo = max(
        0,
        MIN_SOLO_TRADES_FOR_REVIEW - len(solo),
    )
    missing_overlap = max(
        0,
        MIN_OVERLAP_TRADES_FOR_REVIEW - len(overlapping),
    )
    ready = (
        missing_total == 0
        and missing_solo == 0
        and missing_overlap == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": "positions_already_open_before_fill",
        "same_timestamp_openings_count_as_prior": False,
        "closed_trades": len(items),
        "currently_open_positions_used_for_history": len(
            tuple(open_positions)
        ),
        "solo": _summary(solo),
        "overlapping": _summary(overlapping),
        "by_concurrency_bucket": {
            key: _summary(tuple(buckets[key]))
            for key in ("0", "1", "2", "3+")
        },
        "by_same_side_overlap": {
            key: _summary(tuple(same_side_buckets[key]))
            for key in ("0", "1+")
        },
        "observations": sorted(
            observations,
            key=lambda item: (
                int(item["opened_at_ms"]),
                str(item["trade_id"]),
            ),
        ),
        "readiness": {
            "ready_for_review": ready,
            "min_closed_trades": MIN_CLOSED_TRADES_FOR_REVIEW,
            "min_solo_trades": MIN_SOLO_TRADES_FOR_REVIEW,
            "min_overlap_trades": MIN_OVERLAP_TRADES_FOR_REVIEW,
            "missing_closed_trades": missing_total,
            "missing_solo_trades": missing_solo,
            "missing_overlap_trades": missing_overlap,
        },
    }
