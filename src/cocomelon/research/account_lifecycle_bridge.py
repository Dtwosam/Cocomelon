from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.execution.accounting import PaperAccountState, PaperPosition, PositionSide

ZERO: Final = Decimal("0")
RECONCILIATION_ABS_TOLERANCE: Final = Decimal("1e-18")


class AccountLifecycleBridgeError(RuntimeError):
    pass


def _matches_zero(value: Decimal) -> bool:
    if not value.is_finite():
        raise AccountLifecycleBridgeError(
            "reconciliation delta must be finite"
        )
    return abs(value) <= RECONCILIATION_ABS_TOLERANCE


def _position_unrealized(position: PaperPosition) -> Decimal:
    mark = position.latest_mark
    if mark is None:
        raise AccountLifecycleBridgeError(
            f"open position {position.market.canonical} is missing latest mark"
        )
    if position.side is PositionSide.LONG:
        return (mark - position.average_entry_price) * position.quantity
    return (position.average_entry_price - mark) * position.quantity


def _position_payload(position: PaperPosition) -> dict[str, object]:
    realized_net = (
        position.cumulative_realized_gross_pnl
        - position.cumulative_fees
        + position.cumulative_funding
    )
    unrealized = _position_unrealized(position)
    return {
        "market": position.market.canonical,
        "side": position.side.value,
        "remaining_quantity": str(position.quantity),
        "average_entry_price": str(position.average_entry_price),
        "latest_mark": (
            None if position.latest_mark is None else str(position.latest_mark)
        ),
        "cumulative_realized_gross_pnl": str(
            position.cumulative_realized_gross_pnl
        ),
        "cumulative_fees": str(position.cumulative_fees),
        "cumulative_funding": str(position.cumulative_funding),
        "realized_net_cash": str(realized_net),
        "unrealized_gross_pnl": str(unrealized),
        "lifecycle_mark_to_market_pnl": str(realized_net + unrealized),
        "planned_risk_remaining": str(position.planned_risk),
        "opening_plan_id": position.opening_plan_id,
        "opened_at_ms": position.opened_at_ms,
    }


def account_lifecycle_bridge(
    account: PaperAccountState,
    closed_trades: Sequence[TradeJournalEntry],
) -> dict[str, object]:
    positions = tuple(account.positions)
    trades = tuple(closed_trades)

    open_realized_gross = sum(
        (position.cumulative_realized_gross_pnl for position in positions),
        ZERO,
    )
    open_fees = sum(
        (position.cumulative_fees for position in positions),
        ZERO,
    )
    open_funding = sum(
        (position.cumulative_funding for position in positions),
        ZERO,
    )
    open_realized_net = open_realized_gross - open_fees + open_funding

    journal_gross = sum(
        (trade.gross_realized_pnl for trade in trades),
        ZERO,
    )
    journal_fees = sum(
        (trade.entry_fees + trade.exit_fees for trade in trades),
        ZERO,
    )
    journal_funding = sum(
        (trade.funding_cash_pnl for trade in trades),
        ZERO,
    )
    journal_net = sum((trade.net_pnl for trade in trades), ZERO)

    account_realized_net = (
        account.realized_gross_pnl
        - account.cumulative_fees
        + account.cumulative_funding
    )
    cash_delta = account.cash - account.starting_cash
    cash_bridge_delta = cash_delta - account_realized_net

    implied_closed_gross = (
        account.realized_gross_pnl - open_realized_gross
    )
    implied_closed_fees = account.cumulative_fees - open_fees
    implied_closed_funding = account.cumulative_funding - open_funding
    implied_closed_net = (
        implied_closed_gross
        - implied_closed_fees
        + implied_closed_funding
    )

    gross_delta = implied_closed_gross - journal_gross
    fees_delta = implied_closed_fees - journal_fees
    funding_delta = implied_closed_funding - journal_funding
    net_delta = implied_closed_net - journal_net

    bridge_realized = journal_net + open_realized_net
    realized_bridge_delta = account_realized_net - bridge_realized

    account_total_pnl = account.equity - account.starting_cash
    bridged_total_pnl = (
        journal_net
        + open_realized_net
        + account.unrealized_pnl
    )
    equity_bridge_delta = account_total_pnl - bridged_total_pnl

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "closed_trade_count": len(trades),
        "open_position_count": len(positions),
        "account": {
            "realized_gross_pnl": str(account.realized_gross_pnl),
            "cumulative_fees": str(account.cumulative_fees),
            "cumulative_funding": str(account.cumulative_funding),
            "realized_net_cash": str(account_realized_net),
            "unrealized_pnl": str(account.unrealized_pnl),
            "total_account_pnl": str(account_total_pnl),
        },
        "open_lifecycles": {
            "realized_gross_pnl": str(open_realized_gross),
            "fees": str(open_fees),
            "funding": str(open_funding),
            "realized_net_cash": str(open_realized_net),
            "unrealized_pnl": str(account.unrealized_pnl),
            "mark_to_market_pnl": str(
                open_realized_net + account.unrealized_pnl
            ),
            "positions": [
                _position_payload(position)
                for position in positions
            ],
        },
        "implied_fully_closed_lifecycles": {
            "realized_gross_pnl": str(implied_closed_gross),
            "fees": str(implied_closed_fees),
            "funding": str(implied_closed_funding),
            "net_pnl": str(implied_closed_net),
        },
        "journal_closed_trades": {
            "realized_gross_pnl": str(journal_gross),
            "fees": str(journal_fees),
            "funding": str(journal_funding),
            "net_pnl": str(journal_net),
        },
        "reconciliation": {
            "cash_bridge_delta": str(cash_bridge_delta),
            "closed_gross_delta": str(gross_delta),
            "closed_fees_delta": str(fees_delta),
            "closed_funding_delta": str(funding_delta),
            "closed_net_delta": str(net_delta),
            "realized_bridge_delta": str(realized_bridge_delta),
            "equity_bridge_delta": str(equity_bridge_delta),
            "absolute_tolerance": str(
                RECONCILIATION_ABS_TOLERANCE
            ),
            "cash_bridge_matches_account": _matches_zero(
                cash_bridge_delta
            ),
            "closed_journal_matches_account": (
                _matches_zero(gross_delta)
                and _matches_zero(fees_delta)
                and _matches_zero(funding_delta)
                and _matches_zero(net_delta)
            ),
            "realized_bridge_matches_account": _matches_zero(
                realized_bridge_delta
            ),
            "equity_bridge_matches_account": _matches_zero(
                equity_bridge_delta
            ),
        },
    }
