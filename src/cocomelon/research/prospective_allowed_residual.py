from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry

ZERO: Final = Decimal("0")


class ProspectiveAllowedResidualError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AllowedResidualItem:
    trade: TradeJournalEntry
    lead_strategy: str | None = None
    ordinal: int | None = None

    def __post_init__(self) -> None:
        if self.lead_strategy is not None and not self.lead_strategy.strip():
            raise ValueError("lead_strategy must be non-empty when present")
        if self.ordinal is not None and self.ordinal <= 0:
            raise ValueError("ordinal must be positive when present")


def _summary(
    items: Sequence[AllowedResidualItem],
) -> dict[str, object]:
    values = tuple(items)
    net = sum((item.trade.net_pnl for item in values), ZERO)
    winner_pnl = sum(
        (
            item.trade.net_pnl
            for item in values
            if item.trade.net_pnl > ZERO
        ),
        ZERO,
    )
    loser_pnl = sum(
        (
            item.trade.net_pnl
            for item in values
            if item.trade.net_pnl < ZERO
        ),
        ZERO,
    )
    net_r = sum((item.trade.net_r for item in values), ZERO)
    return {
        "trades": len(values),
        "wins": sum(
            1 for item in values if item.trade.net_pnl > ZERO
        ),
        "losses": sum(
            1 for item in values if item.trade.net_pnl < ZERO
        ),
        "breakeven": sum(
            1 for item in values if item.trade.net_pnl == ZERO
        ),
        "net_pnl": str(net),
        "winner_pnl": str(winner_pnl),
        "loser_pnl": str(loser_pnl),
        "mean_net_r": (
            None
            if not values
            else str(net_r / Decimal(len(values)))
        ),
    }


def _rank_band(ordinal: int) -> str:
    if ordinal <= 5:
        return "1-5"
    if ordinal <= 10:
        return "6-10"
    if ordinal <= 20:
        return "11-20"
    return "21+"


def _group(
    items: Sequence[AllowedResidualItem],
    *,
    key: str,
) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[AllowedResidualItem]] = defaultdict(list)
    for item in items:
        if key == "side":
            label = item.trade.direction.value
        elif key == "lead_strategy":
            if item.lead_strategy is None:
                continue
            label = item.lead_strategy
        elif key == "rank_band":
            if item.ordinal is None:
                continue
            label = _rank_band(item.ordinal)
        elif key == "side_lead_strategy":
            if item.lead_strategy is None:
                continue
            label = (
                f"{item.trade.direction.value}:"
                f"{item.lead_strategy}"
            )
        elif key == "market":
            label = item.trade.market.canonical
        else:
            raise ProspectiveAllowedResidualError(
                f"unsupported residual grouping: {key}"
            )
        grouped[label].append(item)
    return {
        label: _summary(tuple(grouped[label]))
        for label in sorted(grouped)
    }


def _worst_group(
    grouped: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    if not grouped:
        return None
    parsed: list[tuple[str, Decimal, int]] = []
    for label, summary in grouped.items():
        raw = summary.get("net_pnl")
        count = summary.get("trades")
        if not isinstance(raw, str):
            raise ProspectiveAllowedResidualError(
                "residual group net_pnl must be a string"
            )
        if isinstance(count, bool) or not isinstance(count, int):
            raise ProspectiveAllowedResidualError(
                "residual group trades must be an integer"
            )
        parsed.append((label, Decimal(raw), count))
    label, net_pnl, count = min(
        parsed,
        key=lambda item: (item[1], -item[2], item[0]),
    )
    return {
        "label": label,
        "net_pnl": str(net_pnl),
        "trades": count,
    }


def prospective_allowed_residual_attribution(
    items: Sequence[AllowedResidualItem],
) -> dict[str, object]:
    values = tuple(items)
    trade_ids = tuple(item.trade.trade_id for item in values)
    if len(set(trade_ids)) != len(trade_ids):
        raise ProspectiveAllowedResidualError(
            "allowed residual attribution contains duplicate trade ids"
        )

    by_side = _group(values, key="side")
    by_lead_strategy = _group(values, key="lead_strategy")
    by_rank_band = _group(values, key="rank_band")
    by_side_lead_strategy = _group(
        values,
        key="side_lead_strategy",
    )
    by_market = _group(values, key="market")

    return {
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "overall": _summary(values),
        "by_side": by_side,
        "by_lead_strategy": by_lead_strategy,
        "by_rank_band": by_rank_band,
        "by_side_lead_strategy": by_side_lead_strategy,
        "by_market": by_market,
        "worst_side": _worst_group(by_side),
        "worst_lead_strategy": _worst_group(by_lead_strategy),
        "worst_rank_band": _worst_group(by_rank_band),
        "worst_side_lead_strategy": _worst_group(
            by_side_lead_strategy
        ),
        "worst_market": _worst_group(by_market),
    }
