from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research import closed_trade_entry_exit_context as audit


def _trade(
    n: int, *, side: Direction, gross: str,
    mfe: str | None, complete: bool = True,
) -> SimpleNamespace:
    fee = Decimal("0.5")
    gross_amount = Decimal(gross)
    excursion = (
        None if mfe is None
        else SimpleNamespace(r_multiple=Decimal(mfe), complete=complete)
    )
    return SimpleNamespace(
        trade_id=f"t{n}",
        market=MarketId("", "SOL" if n % 2 else "BTC"),
        direction=side,
        opened_at_ms=n * 1000,
        closed_at_ms=n * 1000 + 300,
        gross_realized_pnl=gross_amount,
        entry_fees=fee / 2,
        exit_fees=fee / 2,
        funding_cash_pnl=Decimal("0"),
        net_pnl=gross_amount - fee,
        exit_reason="MARK_STOP_TRIGGERED" if gross_amount < 0 else "EXIT_RULE",
        mfe=excursion,
        mae=excursion,
    )


def test_full_journal_long_short_rank_and_exit_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = (
        _trade(1, side=Direction.LONG, gross="-2", mfe="0.7"),
        _trade(2, side=Direction.LONG, gross="-2", mfe="0.1"),
        _trade(3, side=Direction.SHORT, gross="3", mfe="1.2"),
        _trade(4, side=Direction.SHORT, gross="-2", mfe=None),
    )
    def entry(trade: SimpleNamespace, *_: object) -> tuple[dict[str, object] | None, str | None]:
        if trade.trade_id == "t4":
            return None, "missing feature snapshot"
        return {
            "lead_strategy": "trend",
            "rank_band": "outside10" if trade.direction is Direction.LONG else "top10",
            "return_15m_sign": "negative",
            "return_1h_sign": "negative",
            "trend_regime": "down",
            "volatility_regime": "normal",
            "trade_id": trade.trade_id,
        }, None

    monkeypatch.setattr(audit, "try_resolve_entry_context_row", entry)
    result = audit.closed_trade_entry_exit_context(values, None, None, None)
    overall = result["overall"]
    assert result["trade_count"] == 4
    assert result["entry_context_verified_trades"] == 3
    assert result["entry_context_unresolved_reasons"] == {
        "missing feature snapshot": 1
    }
    assert Decimal(str(overall["net_pnl"])) == Decimal("-5")
    assert Decimal(str(overall["net_reconciliation_residual"])) == 0
    assert overall["mark_stop_losing_exits"] == 3
    assert overall["losses_no_0_25r_favorable_move"] == 1
    assert overall["losses_after_0_5r_favorable_move"] == 1
    assert overall["losing_trades_missing_excursion"] == 1
    grouped = result["dimensions"]["by_side_strategy_and_rank"]
    assert grouped["long | trend | outside10"]["trades"] == 2
    assert grouped["short | trend | top10"]["trades"] == 1
    missing = ("short | historical_context_unavailable | "
               "historical_context_unavailable")
    assert grouped[missing]["trades"] == 1
    assert result["entry_context_by_trade_id"]["t4"] is None
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_incomplete_excursion_never_invents_giveback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = _trade(1, side=Direction.SHORT, gross="-3", mfe="1.1", complete=False)
    monkeypatch.setattr(
        audit,
        "try_resolve_entry_context_row",
        lambda *_: (None, "missing decision fact"),
    )
    result = audit.closed_trade_entry_exit_context((t,), None, None, None)
    overall = result["overall"]
    assert overall["losses_after_0_5r_favorable_move"] == 0
    assert overall["losses_no_0_25r_favorable_move"] == 0
    assert overall["losing_trades_missing_excursion"] == 1


def test_duplicate_journal_trade_id_fails() -> None:
    t = _trade(1, side=Direction.LONG, gross="-3", mfe=None)
    with pytest.raises(audit.ClosedTradeEntryExitContextError, match="duplicate"):
        audit.closed_trade_entry_exit_context((t, t), None, None, None)



def test_exact_cash_parity_across_reordered_entry_context_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default 28-digit Decimal summation used to invent a cohort mismatch."""
    amounts = (
        Decimal("100000000000000000000"),
        Decimal("0.000000000000000000000000001"),
        Decimal("-100000000000000000000"),
        Decimal("0.000000000000000000000000001"),
    )
    rows = [
        _trade(i, side=Direction.LONG, gross=str(amount), mfe=None)
        for i, amount in enumerate(amounts, 1)
    ]
    for row, amount in zip(rows, amounts, strict=True):
        row.gross_realized_pnl = amount
        row.net_pnl = amount
        row.entry_fees = Decimal("0")
        row.exit_fees = Decimal("0")

    def entry(trade: SimpleNamespace, *_: object) -> tuple[dict[str, object], None]:
        return {
            "lead_strategy": "trend",
            "rank_band": "top10" if trade.trade_id in ("t1", "t3") else "outside10",
            "return_15m_sign": "positive",
            "return_1h_sign": "positive",
            "trend_regime": "up",
            "volatility_regime": "normal",
        }, None

    monkeypatch.setattr(audit, "try_resolve_entry_context_row", entry)
    result = audit.closed_trade_entry_exit_context(tuple(rows), None, None, None)
    expected = Decimal("0.000000000000000000000000002")
    assert Decimal(result["overall"]["net_pnl"]) == expected
    for groups in result["dimensions"].values():
        assert sum(
            (Decimal(cohort["net_pnl"]) for cohort in groups.values()),
            Decimal("0"),
        ) == expected
    assert result["overall"]["net_reconciliation_residual"] == "0"
    assert result["entry_context_verified_trades"] == 4
