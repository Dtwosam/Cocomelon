import importlib
from decimal import Decimal

from cocomelon.domain.features import (
    EligibilityDecision,
    OpportunityRank,
    ScoreComponent,
)
from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager

shortlist_module = importlib.import_module("cocomelon.scanner.shortlist")
DynamicShortlistManager = shortlist_module.DynamicShortlistManager
ShortlistConfig = shortlist_module.ShortlistConfig
build_subscription_plan = shortlist_module.build_subscription_plan


def _rank(coin: str, ordinal: int, score: str | None = None) -> OpportunityRank:
    resolved_score = Decimal(score) if score is not None else Decimal(100 - ordinal) / Decimal(100)
    component = ScoreComponent(
        name="attention",
        raw_value=resolved_score,
        percentile=resolved_score,
        weight=Decimal("1"),
        contribution=resolved_score,
    )
    return OpportunityRank(
        market=MarketId("", coin),
        ordinal=ordinal,
        score=resolved_score,
        components=(component,),
        reason_codes=("attention",),
    )


def _decision(coin: str, *, rankable: bool = True) -> EligibilityDecision:
    return EligibilityDecision(
        market=MarketId("", coin),
        rankable=rankable,
        deep_ready=False,
        reasons=() if rankable else ("delisted",),
    )


def test_initial_shortlist_is_bounded_and_ranked_watchlist_is_independent() -> None:
    ranks = tuple(_rank(f"M{index:02d}", index) for index in range(1, 7))
    decisions = tuple(_decision(rank.market.coin) for rank in ranks)
    manager = DynamicShortlistManager(
        ShortlistConfig(target_size=2, retention_rank=3, ranked_watchlist_size=4)
    )

    delta = manager.reconcile(ranks, decisions)

    assert tuple(item.coin for item in delta.current) == ("M01", "M02")
    assert tuple(item.coin for item in delta.added) == ("M01", "M02")
    assert delta.removed == ()
    assert tuple(item.coin for item in delta.ranked_watchlist) == (
        "M01",
        "M02",
        "M03",
        "M04",
    )


def test_incumbent_inside_retention_band_survives_higher_ranked_newcomer() -> None:
    manager = DynamicShortlistManager(
        ShortlistConfig(target_size=1, retention_rank=3, ranked_watchlist_size=4)
    )
    manager.reconcile((_rank("OLD", 1),), (_decision("OLD"),))

    delta = manager.reconcile(
        (_rank("NEW", 1), _rank("OLD", 2)),
        (_decision("NEW"), _decision("OLD")),
    )

    assert delta.current == (MarketId("", "OLD"),)
    assert delta.added == ()
    assert delta.removed == ()


def test_incumbent_outside_retention_band_is_replaced() -> None:
    manager = DynamicShortlistManager(
        ShortlistConfig(target_size=1, retention_rank=2, ranked_watchlist_size=4)
    )
    manager.reconcile((_rank("OLD", 1),), (_decision("OLD"),))

    delta = manager.reconcile(
        (_rank("NEW", 1), _rank("OTHER", 2), _rank("OLD", 3)),
        (_decision("NEW"), _decision("OTHER"), _decision("OLD")),
    )

    assert delta.current == (MarketId("", "NEW"),)
    assert delta.added == (MarketId("", "NEW"),)
    assert delta.removed == (MarketId("", "OLD"),)


def test_newly_ineligible_non_pinned_incumbent_is_removed_immediately() -> None:
    manager = DynamicShortlistManager(ShortlistConfig(target_size=1, retention_rank=3))
    manager.reconcile((_rank("OLD", 1),), (_decision("OLD"),))

    delta = manager.reconcile(
        (_rank("NEW", 1), _rank("OLD", 2)),
        (_decision("NEW"), _decision("OLD", rankable=False)),
    )

    assert delta.current == (MarketId("", "NEW"),)
    assert delta.added == (MarketId("", "NEW"),)
    assert delta.removed == (MarketId("", "OLD"),)


def test_pinned_markets_are_retained_outside_non_pinned_target() -> None:
    manager = DynamicShortlistManager(ShortlistConfig(target_size=1, retention_rank=2))
    ranks = (_rank("A", 1), _rank("B", 2))
    decisions = (_decision("A"), _decision("B"))
    pinned = (MarketId("", "PIN1"), MarketId("", "PIN2"))

    delta = manager.reconcile(ranks, decisions, pinned_markets=pinned)

    assert delta.current == (
        MarketId("", "A"),
        MarketId("", "PIN1"),
        MarketId("", "PIN2"),
    )


def test_ties_are_stable_by_canonical_market_name() -> None:
    manager = DynamicShortlistManager(ShortlistConfig(target_size=2, retention_rank=3))
    ranks = (_rank("Z", 1, "0.5"), _rank("A", 1, "0.5"), _rank("M", 3, "0.4"))
    decisions = tuple(_decision(rank.market.coin) for rank in ranks)

    delta = manager.reconcile(ranks, decisions)

    assert tuple(item.coin for item in delta.current) == ("A", "Z")


def test_subscription_plan_delegates_to_phase3_public_watchlist_boundary() -> None:
    manager = DynamicShortlistManager(ShortlistConfig(target_size=1, retention_rank=2))
    delta = manager.reconcile((_rank("BTC", 1),), (_decision("BTC"),))
    deep_watchlist = DeepWatchlistManager(broad_dexes=("xyz",), safety_ceiling=20)

    plan = build_subscription_plan(deep_watchlist, delta)

    assert plan.desired_count == 8
    assert {item["type"] for item in plan.subscribe} == {
        "activeAssetCtx",
        "allMids",
        "l2Book",
        "trades",
        "candle",
    }
    assert all("user" not in str(item).lower() for item in plan.subscribe)
