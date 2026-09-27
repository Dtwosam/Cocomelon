from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
DAY_MS: Final = 86_400_000
SEVEN_DAYS_MS: Final = 7 * DAY_MS
MARKET_POSITIVE_PNL_SHARE_REFERENCE_MAX: Final = Decimal("0.35")
SEVEN_DAY_POSITIVE_PNL_SHARE_REFERENCE_MAX: Final = Decimal("0.50")
AUTHORITATIVE_CONTEXT: Final = Context(
    prec=28,
    rounding=ROUND_HALF_EVEN,
)


def _sum(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext(AUTHORITATIVE_CONTEXT):
        return sum(values, ZERO)


def _share(
    numerator: Decimal,
    denominator: Decimal,
) -> Decimal | None:
    if denominator <= ZERO:
        return None
    with localcontext(AUTHORITATIVE_CONTEXT):
        return numerator / denominator


def _hhi(shares: tuple[Decimal, ...]) -> Decimal | None:
    if not shares:
        return None
    with localcontext(AUTHORITATIVE_CONTEXT):
        return sum((share * share for share in shares), ZERO)


def _group_rows(
    trades: tuple[TradeJournalEntry, ...],
    key_fn: Callable[[TradeJournalEntry], str],
) -> tuple[dict[str, object], ...]:
    grouped: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    for trade in trades:
        grouped[key_fn(trade)].append(trade)

    trade_count = len(trades)
    grouped_net = {
        label: _sum(tuple(item.net_pnl for item in items))
        for label, items in grouped.items()
    }
    positive_total = _sum(
        tuple(value for value in grouped_net.values() if value > ZERO)
    )

    rows: list[dict[str, object]] = []
    for label, items in sorted(grouped.items()):
        count = len(items)
        net_pnl = grouped_net[label]
        total_r = _sum(tuple(item.net_r for item in items))
        positive_share = (
            ZERO
            if net_pnl <= ZERO or positive_total <= ZERO
            else _share(net_pnl, positive_total)
        )
        trade_share = (
            ZERO
            if trade_count == 0
            else _share(Decimal(count), Decimal(trade_count))
        )
        rows.append(
            {
                "label": label,
                "trades": count,
                "wins": sum(1 for item in items if item.net_pnl > ZERO),
                "losses": sum(1 for item in items if item.net_pnl < ZERO),
                "breakeven": sum(1 for item in items if item.net_pnl == ZERO),
                "net_pnl": str(net_pnl),
                "mean_net_r": str(total_r / Decimal(count)),
                "trade_count_share": (
                    None if trade_share is None else str(trade_share)
                ),
                "positive_net_pnl_share": (
                    None
                    if positive_share is None
                    else str(positive_share)
                ),
            }
        )
    return tuple(rows)


def _positive_group_shares(
    rows: tuple[dict[str, object], ...],
) -> tuple[Decimal, ...]:
    shares: list[Decimal] = []
    for row in rows:
        raw = row["positive_net_pnl_share"]
        if raw is None:
            continue
        value = Decimal(str(raw))
        if value > ZERO:
            shares.append(value)
    return tuple(shares)


def _trade_shares(
    rows: tuple[dict[str, object], ...],
) -> tuple[Decimal, ...]:
    shares: list[Decimal] = []
    for row in rows:
        raw = row["trade_count_share"]
        if raw is None:
            continue
        shares.append(Decimal(str(raw)))
    return tuple(shares)


def _max_positive_share(
    rows: tuple[dict[str, object], ...],
) -> tuple[str | None, Decimal | None]:
    best_label: str | None = None
    best_share: Decimal | None = None
    for row in rows:
        raw = row["positive_net_pnl_share"]
        if raw is None:
            continue
        value = Decimal(str(raw))
        if best_share is None or value > best_share:
            best_label = str(row["label"])
            best_share = value
    return best_label, best_share


def _section(
    rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    top_label, max_positive_share = _max_positive_share(rows)
    trade_hhi = _hhi(_trade_shares(rows))
    positive_hhi = _hhi(_positive_group_shares(rows))
    return {
        "group_count": len(rows),
        "largest_positive_contributor": top_label,
        "max_positive_net_pnl_share": (
            None
            if max_positive_share is None
            else str(max_positive_share)
        ),
        "trade_count_hhi": (
            None if trade_hhi is None else str(trade_hhi)
        ),
        "positive_net_pnl_hhi": (
            None if positive_hhi is None else str(positive_hhi)
        ),
        "rows": list(rows),
    }


def closed_trade_concentration_summary(
    trades: tuple[TradeJournalEntry, ...],
) -> dict[str, object]:
    ordered = tuple(
        sorted(
            trades,
            key=lambda item: (item.closed_at_ms, item.trade_id),
        )
    )
    market_rows = _group_rows(
        ordered,
        lambda trade: trade.market.canonical,
    )
    strategy_rows = _group_rows(
        ordered,
        lambda trade: (
            "unknown"
            if not trade.strategy_names
            else trade.strategy_names[0]
        ),
    )
    seven_day_rows = _group_rows(
        ordered,
        lambda trade: str(trade.closed_at_ms // SEVEN_DAYS_MS),
    )

    market = _section(market_rows)
    strategy = _section(strategy_rows)
    seven_day = _section(seven_day_rows)

    market_max_raw = market["max_positive_net_pnl_share"]
    seven_day_max_raw = seven_day["max_positive_net_pnl_share"]
    market_max = (
        None
        if market_max_raw is None
        else Decimal(str(market_max_raw))
    )
    seven_day_max = (
        None
        if seven_day_max_raw is None
        else Decimal(str(seven_day_max_raw))
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": "phase9_positive_group_net_pnl_share",
        "trade_count": len(ordered),
        "distinct_markets": len(market_rows),
        "distinct_lead_strategies": len(strategy_rows),
        "distinct_seven_day_buckets": len(seven_day_rows),
        "market_reference_max_share": str(
            MARKET_POSITIVE_PNL_SHARE_REFERENCE_MAX
        ),
        "seven_day_reference_max_share": str(
            SEVEN_DAY_POSITIVE_PNL_SHARE_REFERENCE_MAX
        ),
        "market_reference_met": (
            None
            if market_max is None
            else market_max
            <= MARKET_POSITIVE_PNL_SHARE_REFERENCE_MAX
        ),
        "seven_day_reference_met": (
            None
            if seven_day_max is None
            else seven_day_max
            <= SEVEN_DAY_POSITIVE_PNL_SHARE_REFERENCE_MAX
        ),
        "market": market,
        "lead_strategy": strategy,
        "seven_day": seven_day,
    }
