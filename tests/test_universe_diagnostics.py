from decimal import Decimal

from cocomelon.domain.features import OpportunityRank
from cocomelon.domain.market import MarketId
from cocomelon.universe_diagnostics import (
    build_universe_opportunity_diagnostics,
)


def _rank(market: MarketId, ordinal: int, score: str) -> OpportunityRank:
    return OpportunityRank(
        market=market,
        ordinal=ordinal,
        score=Decimal(score),
        components=(),
        reason_codes=("ELIGIBLE",),
    )


def test_universe_diagnostics_quantifies_hip3_displacement() -> None:
    ranks = (
        _rank(MarketId("", "BTC"), 1, "0.90"),
        _rank(MarketId("xyz", "ABC"), 2, "0.85"),
        _rank(MarketId("", "ETH"), 3, "0.80"),
        _rank(MarketId("xyz", "DEF"), 4, "0.70"),
    )

    report = build_universe_opportunity_diagnostics(
        ranks,
        observed_at_ms=1_700_000_000_000,
        dex_count=1,
        market_count=4,
        deep_limit=2,
        top_hip3_limit=2,
    )

    assert report.rankable_count == 4
    assert report.native_rankable_count == 2
    assert report.hip3_rankable_count == 2
    assert report.hip3_in_combined_top_n == 1
    assert tuple(row.market for row in report.combined_top_n) == ("BTC", "xyz:ABC")
    assert tuple(row.market for row in report.current_native_top_n) == ("BTC", "ETH")
    assert report.displaced_native_markets == ("ETH",)
    assert report.paper_trading_policy == "native_only"
    assert report.economic_authority is False
    assert report.live_orders is False


def test_universe_diagnostics_rejects_invalid_limits() -> None:
    try:
        build_universe_opportunity_diagnostics(
            (),
            observed_at_ms=0,
            dex_count=0,
            market_count=0,
            deep_limit=0,
        )
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected invalid diagnostic limit to fail")
