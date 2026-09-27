from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.closed_trade_concentration import (
    SEVEN_DAYS_MS,
    closed_trade_concentration,
)


def _trade(
    *,
    trade_id: str,
    market: str,
    pnl: str,
    closed_at_ms: int,
    strategy: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        trade_id=trade_id,
        market=MarketId("", market),
        direction=Direction.LONG,
        feature_snapshot_id=f"feature-{trade_id}",
        strategy_decision_id=f"decision-{trade_id}",
        replay_run_id="continuous-paper-mainnet-v1",
        closed_at_ms=closed_at_ms,
        net_pnl=Decimal(pnl),
        strategy=strategy,
    )


class _Facts:
    def __init__(self, trades: tuple[SimpleNamespace, ...]) -> None:
        self._by_decision = {
            trade.strategy_decision_id: trade
            for trade in trades
        }

    def load_decision_by_strategy_id(
        self,
        strategy_decision_id: str,
        replay_run_id: str,
    ) -> SimpleNamespace | None:
        trade = self._by_decision.get(strategy_decision_id)
        if trade is None:
            return None
        return SimpleNamespace(
            market=trade.market,
            direction=trade.direction,
            feature_snapshot_id=trade.feature_snapshot_id,
            lead_strategy=trade.strategy,
            replay_run_id=replay_run_id,
        )


def test_concentration_nets_each_group_before_positive_share() -> None:
    trades = (
        _trade(
            trade_id="a-win",
            market="A",
            pnl="10",
            closed_at_ms=1_000,
            strategy="trend",
        ),
        _trade(
            trade_id="a-loss",
            market="A",
            pnl="-2",
            closed_at_ms=2_000,
            strategy="trend",
        ),
        _trade(
            trade_id="b-win",
            market="B",
            pnl="4",
            closed_at_ms=SEVEN_DAYS_MS + 1_000,
            strategy="breakout",
        ),
        _trade(
            trade_id="c-loss",
            market="C",
            pnl="-1",
            closed_at_ms=SEVEN_DAYS_MS + 2_000,
            strategy="trend",
        ),
    )
    facts = _Facts(trades)

    result = closed_trade_concentration(
        trades,  # type: ignore[arg-type]
        facts,  # type: ignore[arg-type]
    )

    market = result["market"]
    assert isinstance(market, dict)
    assert market["group_count"] == 3
    assert market["positive_group_count"] == 2
    assert market["total_positive_group_pnl"] == "12"
    assert market["max_positive_group"] == "A"
    assert market["max_positive_pnl_share"] == str(
        Decimal("8") / Decimal("12")
    )
    assert market["formal_limit"] == "0.35"
    assert market["within_formal_limit_current_sample"] is False

    rows = market["groups"]
    assert isinstance(rows, list)
    by_market = {
        row["group"]: row
        for row in rows
        if isinstance(row, dict)
    }
    assert by_market["A"]["net_pnl"] == "8"
    assert by_market["A"]["trades"] == 2
    assert by_market["C"]["positive_group_pnl_share"] is None

    strategy = result["lead_strategy"]
    assert isinstance(strategy, dict)
    assert strategy["max_positive_group"] == "trend"
    assert strategy["total_positive_group_pnl"] == "11"

    seven_day = result["seven_day"]
    assert isinstance(seven_day, dict)
    assert seven_day["group_count"] == 2
    assert seven_day["max_positive_group"] == "0"
    assert seven_day["max_positive_pnl_share"] == str(
        Decimal("8") / Decimal("11")
    )
    assert seven_day["formal_limit"] == "0.50"
    assert seven_day["within_formal_limit_current_sample"] is False

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False
    assert readiness["missing_closed_trades"] == 26


def test_concentration_handles_no_positive_groups() -> None:
    trades = (
        _trade(
            trade_id="a",
            market="A",
            pnl="-2",
            closed_at_ms=1_000,
            strategy="trend",
        ),
        _trade(
            trade_id="b",
            market="B",
            pnl="-3",
            closed_at_ms=2_000,
            strategy="breakout",
        ),
    )
    result = closed_trade_concentration(
        trades,  # type: ignore[arg-type]
        _Facts(trades),  # type: ignore[arg-type]
    )

    market = result["market"]
    assert isinstance(market, dict)
    assert market["positive_group_count"] == 0
    assert market["max_positive_group"] is None
    assert market["max_positive_pnl_share"] is None
    assert market["within_formal_limit_current_sample"] is None


def test_concentration_reports_missing_strategy_attribution() -> None:
    trade = _trade(
        trade_id="missing",
        market="A",
        pnl="5",
        closed_at_ms=1_000,
        strategy="trend",
    )

    result = closed_trade_concentration(
        (trade,),  # type: ignore[arg-type]
        _Facts(()),  # type: ignore[arg-type]
    )

    assert result["strategy_attribution_misses"] == 1
    strategy = result["lead_strategy"]
    assert isinstance(strategy, dict)
    assert strategy["max_positive_group"] == "unknown"
