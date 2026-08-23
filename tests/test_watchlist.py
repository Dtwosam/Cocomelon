import pytest
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager

from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.ws_protocol import subscription_id


def market(symbol: str) -> MarketId:
    if ":" in symbol:
        dex = symbol.split(":", 1)[0]
        return MarketId.from_wire_name(dex, symbol)
    return MarketId.from_wire_name("", symbol)


def test_twenty_market_deep_watchlist_stays_below_safety_ceiling() -> None:
    manager = DeepWatchlistManager(broad_dexes=("xyz",))
    markets = [market(f"COIN{i}") for i in range(20)]

    plan = manager.reconcile(markets)

    assert plan.desired_count == 102
    assert len(plan.subscribe) == 102
    assert plan.unsubscribe == ()
    ids = {subscription_id(item) for item in plan.subscribe}
    assert "allMids" in ids
    assert "allMids:xyz" in ids
    assert "l2Book:COIN0" in ids
    assert "trades:COIN0" in ids
    assert "candle:COIN0:1m" in ids
    assert "candle:COIN0:5m" in ids
    assert "candle:COIN0:15m" in ids


def test_reconcile_unsubscribes_removed_before_subscribing_added() -> None:
    manager = DeepWatchlistManager()
    manager.reconcile([market("BTC"), market("ETH")])

    plan = manager.reconcile([market("BTC"), market("SOL")])

    unsubscribe_ids = tuple(subscription_id(item) for item in plan.unsubscribe)
    subscribe_ids = tuple(subscription_id(item) for item in plan.subscribe)
    assert unsubscribe_ids == tuple(sorted(unsubscribe_ids))
    assert subscribe_ids == tuple(sorted(subscribe_ids))
    assert all(":ETH" in item for item in unsubscribe_ids)
    assert all(":SOL" in item for item in subscribe_ids)


def test_safety_ceiling_rejects_oversized_state_without_mutating_active() -> None:
    manager = DeepWatchlistManager(safety_ceiling=12)
    initial = manager.reconcile([market("BTC")])
    assert initial.desired_count == 6

    with pytest.raises(ValueError, match="safety ceiling"):
        manager.reconcile([market("BTC"), market("ETH"), market("SOL")])

    recovery = manager.reconcile([market("BTC")])
    assert recovery.subscribe == ()
    assert recovery.unsubscribe == ()
    assert recovery.desired_count == 6


def test_hip3_market_subscriptions_preserve_wire_prefix() -> None:
    manager = DeepWatchlistManager(broad_dexes=("xyz",))

    plan = manager.reconcile([market("xyz:NVDA")])
    ids = {subscription_id(item) for item in plan.subscribe}

    assert "l2Book:xyz:NVDA" in ids
    assert "trades:xyz:NVDA" in ids
    assert "candle:xyz:NVDA:15m" in ids
