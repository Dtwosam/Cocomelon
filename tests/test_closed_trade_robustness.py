from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from cocomelon.research.closed_trade_robustness import (
    closed_trade_robustness,
)


def _trade(
    trade_id: str,
    pnl: str,
    net_r: str,
    closed_at_ms: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        trade_id=trade_id,
        net_pnl=Decimal(pnl),
        net_r=Decimal(net_r),
        closed_at_ms=closed_at_ms,
    )


def test_robustness_exposes_single_winner_dependence() -> None:
    trades = (
        _trade("best", "10", "1.0", 4),
        _trade("second", "5", "0.5", 3),
        _trade("loss-a", "-8", "-0.8", 2),
        _trade("loss-b", "-3", "-0.3", 1),
    )

    result = closed_trade_robustness(trades)  # type: ignore[arg-type]

    assert result["closed_trades"] == 4
    assert result["net_pnl"] == "4"
    assert result["gross_profit"] == "15"
    assert result["largest_winner_net_pnl"] == "10"
    assert result["largest_winner_net_r"] == "1.0"
    assert result["largest_winner_trade_id"] == "best"
    assert result["top_one_winner_share_of_gross_profit"] == str(
        Decimal("10") / Decimal("15")
    )
    assert result["top_two_winner_share_of_gross_profit"] == "1"

    remove_one = result["remove_best_one"]
    assert isinstance(remove_one, dict)
    assert remove_one["remaining_trades"] == 3
    assert remove_one["removed_trade_ids"] == ["best"]
    assert remove_one["net_pnl"] == "-6"
    assert remove_one["positive_net_pnl"] is False
    assert Decimal(str(remove_one["profit_factor"])) == (
        Decimal("5") / Decimal("11")
    )

    remove_two = result["remove_best_two"]
    assert isinstance(remove_two, dict)
    assert remove_two["remaining_trades"] == 2
    assert remove_two["removed_trade_ids"] == ["best", "second"]
    assert remove_two["net_pnl"] == "-11"
    assert remove_two["profit_factor"] == "0"
    assert remove_two["positive_net_pnl"] is False

    assert result["positive_pnl_survives_remove_best_one"] is False
    assert result["positive_pnl_survives_remove_best_two"] is False
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False
    assert readiness["missing_closed_trades"] == 26


def test_robustness_handles_no_winners_without_infinite_pf() -> None:
    trades = (
        _trade("loss-a", "-2", "-0.2", 1),
        _trade("loss-b", "-3", "-0.3", 2),
    )

    result = closed_trade_robustness(trades)  # type: ignore[arg-type]

    assert result["largest_winner_net_pnl"] is None
    assert result["top_one_winner_share_of_gross_profit"] is None
    remove_one = result["remove_best_one"]
    assert isinstance(remove_one, dict)
    assert remove_one["removed_trade_count"] == 0
    assert remove_one["net_pnl"] == "-5"
    assert remove_one["profit_factor"] == "0"
