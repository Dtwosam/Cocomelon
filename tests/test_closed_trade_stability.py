from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from cocomelon.research.closed_trade_stability import (
    closed_trade_stability,
)


def _trade(
    index: int,
    pnl: str,
    net_r: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        trade_id=f"trade-{index:03d}",
        net_pnl=Decimal(pnl),
        net_r=Decimal(net_r),
        opened_at_ms=index * 1_000,
        closed_at_ms=index * 1_000 + 500,
    )


def test_stability_exposes_rolling_deterioration_before_review_gate() -> None:
    trades = tuple(
        _trade(
            index,
            "5" if index <= 10 else "-2",
            "0.5" if index <= 10 else "-0.2",
        )
        for index in range(1, 21)
    )

    result = closed_trade_stability(trades)  # type: ignore[arg-type]

    assert result["closed_trades"] == 20
    rolling = result["rolling"]
    assert isinstance(rolling, dict)

    five = rolling["5"]
    assert isinstance(five, dict)
    assert five["window_count"] == 16
    latest_five = five["latest"]
    assert isinstance(latest_five, dict)
    assert latest_five["net_pnl"] == "-10"
    assert latest_five["mean_net_r"] == "-0.2"
    assert five["worst_net_pnl"] == "-10"
    assert five["best_net_pnl"] == "25"

    ten = rolling["10"]
    assert isinstance(ten, dict)
    latest_ten = ten["latest"]
    assert isinstance(latest_ten, dict)
    assert latest_ten["net_pnl"] == "-20"
    assert latest_ten["mean_net_r"] == "-0.2"

    blocks = result["chronological_blocks"]
    assert isinstance(blocks, list)
    assert [block["trades"] for block in blocks] == [5, 5, 5, 5]
    stability = result["stability"]
    assert isinstance(stability, dict)
    assert stability["full_blocks"] == 0
    assert stability["all_full_blocks_positive_net_pnl"] is False

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False
    assert readiness["missing_closed_trades"] == 20


def test_stability_requires_four_full_chronological_blocks() -> None:
    trades = tuple(
        _trade(
            index,
            "1" if index <= 30 else "-0.25",
            "0.1" if index <= 30 else "-0.025",
        )
        for index in range(1, 41)
    )

    result = closed_trade_stability(trades)  # type: ignore[arg-type]

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is True
    assert readiness["missing_closed_trades"] == 0

    blocks = result["chronological_blocks"]
    assert isinstance(blocks, list)
    assert [block["trades"] for block in blocks] == [10, 10, 10, 10]
    assert [block["net_pnl"] for block in blocks] == [
        "10",
        "10",
        "10",
        "-2.50",
    ]

    stability = result["stability"]
    assert isinstance(stability, dict)
    assert stability["full_blocks"] == 4
    assert stability["all_full_blocks_positive_net_pnl"] is False
    assert stability["all_full_blocks_positive_mean_net_r"] is False

    rolling = result["rolling"]
    assert isinstance(rolling, dict)
    ten = rolling["10"]
    assert isinstance(ten, dict)
    assert ten["window_count"] == 31
    assert ten["positive_pnl_windows"] < ten["window_count"]


def test_stability_orders_trades_by_close_time() -> None:
    trades = (
        _trade(3, "-3", "-0.3"),
        _trade(1, "1", "0.1"),
        _trade(2, "2", "0.2"),
    )

    result = closed_trade_stability(trades)  # type: ignore[arg-type]

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["net_pnl"] == "0"
    assert overall["first_closed_at_ms"] == 1_500
    assert overall["last_closed_at_ms"] == 3_500
