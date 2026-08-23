import pytest

from cocomelon.domain.execution import OrderIntent, OrderSide, OrderType
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction, StrategySignal


def test_market_id_canonicalizes_default_and_named_dex() -> None:
    assert MarketId(dex="", coin="BTC").canonical == "BTC"
    assert MarketId(dex="xyz", coin="XYZ100").canonical == "xyz:XYZ100"


def test_strategy_score_is_bounded() -> None:
    market = MarketId(dex="", coin="SOL")
    with pytest.raises(ValueError, match="score"):
        StrategySignal(
            strategy="trend",
            market=market,
            direction=Direction.LONG,
            score=101.0,
            timestamp_ms=1,
            reasons=("example",),
            invalidation_price=100.0,
        )


def test_no_trade_does_not_require_invalidation() -> None:
    signal = StrategySignal(
        strategy="trend",
        market=MarketId(dex="", coin="ETH"),
        direction=Direction.NO_TRADE,
        score=40.0,
        timestamp_ms=1,
        reasons=("insufficient edge",),
        invalidation_price=None,
    )
    assert signal.direction is Direction.NO_TRADE


def test_opening_order_requires_positive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity"):
        OrderIntent(
            intent_id="intent-1",
            market=MarketId(dex="", coin="BTC"),
            side=OrderSide.BUY,
            quantity=0.0,
            order_type=OrderType.MARKETABLE_IOC,
            reduce_only=False,
            limit_price=None,
            created_at_ms=1,
        )
