from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from cocomelon.domain.market import MarketId
from cocomelon.research.closed_trade_robustness import (
    closed_trade_robustness,
)


def _trade(
    trade_id: str,
    pnl: str,
    net_r: str,
    closed_at_ms: int,
    market: str = "SOL",
) -> SimpleNamespace:
    return SimpleNamespace(
        trade_id=trade_id,
        net_pnl=Decimal(pnl),
        net_r=Decimal(net_r),
        closed_at_ms=closed_at_ms,
        market=MarketId("", market),
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
    assert result["top_positive_market"] is None
    assert result["top_positive_market_net_pnl"] is None
    assert result["top_positive_market_trade_count"] == 0
    assert (
        result["top_positive_market_share_of_positive_market_pnl"]
        is None
    )
    remove_one = result["remove_best_one"]
    assert isinstance(remove_one, dict)
    assert remove_one["removed_trade_count"] == 0
    assert remove_one["net_pnl"] == "-5"
    assert remove_one["profit_factor"] == "0"
    remove_market = result["remove_top_positive_market"]
    assert isinstance(remove_market, dict)
    assert remove_market["removed_trade_count"] == 0
    assert remove_market["net_pnl"] == "-5"
    assert (
        result["positive_pnl_survives_remove_top_positive_market"]
        is False
    )


def test_robustness_exposes_whole_market_dependence() -> None:
    trades = (
        _trade("nil-a", "50", "2.0", 1, "NIL"),
        _trade("nil-b", "25", "1.0", 2, "NIL"),
        _trade("nil-loss", "-5", "-0.2", 3, "NIL"),
        _trade("jup-win", "15", "0.6", 4, "JUP"),
        _trade("loss-a", "-20", "-0.8", 5, "ENA"),
        _trade("loss-b", "-10", "-0.4", 6, "CC"),
    )

    result = closed_trade_robustness(trades)  # type: ignore[arg-type]

    assert result["net_pnl"] == "55"
    assert result["top_positive_market"] == "NIL"
    assert result["top_positive_market_net_pnl"] == "70"
    assert result["top_positive_market_trade_count"] == 3
    assert result["top_positive_market_share_of_positive_market_pnl"] == str(
        Decimal("70") / Decimal("85")
    )

    scenario = result["remove_top_positive_market"]
    assert isinstance(scenario, dict)
    assert scenario["removed_trade_count"] == 3
    assert scenario["removed_net_pnl"] == "70"
    assert scenario["remaining_trades"] == 3
    assert scenario["net_pnl"] == "-15"
    assert scenario["mean_net_r"] == "-0.2"
    assert scenario["profit_factor"] == "0.5"
    assert scenario["positive_net_pnl"] is False
    assert (
        result["positive_pnl_survives_remove_top_positive_market"]
        is False
    )
