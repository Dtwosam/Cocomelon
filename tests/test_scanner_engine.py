import importlib
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal

from cocomelon.domain.market import (
    Candle,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager
from cocomelon.scanner.eligibility import EligibilityConfig
from cocomelon.scanner.shortlist import ShortlistConfig

engine_module = importlib.import_module("cocomelon.scanner.engine")
FeatureScanner = engine_module.FeatureScanner
ScanResult = engine_module.ScanResult

AS_OF_MS = 20_000_000


def _market(
    index: int,
    *,
    received_at_ms: int = AS_OF_MS - 100,
    is_delisted: bool = False,
    mid_px: Decimal | None = None,
) -> PerpMarketSnapshot:
    market = MarketId("", f"M{index:02d}")
    price = Decimal(100 + index)
    resolved_mid = price if mid_px is None else mid_px
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market,
            wire_name=market.wire_name,
            sz_decimals=4,
            max_leverage=20,
            margin_table_id=None,
            only_isolated=False,
            is_delisted=is_delisted,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=market,
            mark_px=price,
            mid_px=resolved_mid,
            oracle_px=price,
            funding=Decimal(index + 1) / Decimal("1000000"),
            open_interest=Decimal(10_000 + index * 100),
            day_ntl_vlm=Decimal(1_000_000 + index * 10_000),
            premium=None,
            prev_day_px=price - Decimal("1"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _candles(market: MarketId) -> tuple[Candle, ...]:
    interval_ms = 900_000
    start = AS_OF_MS - 21 * interval_ms
    candles = []
    for index in range(21):
        open_px = Decimal("100") + Decimal(index)
        close_px = open_px + Decimal("1")
        candles.append(
            Candle(
                market=market,
                interval="15m",
                start_ms=start + index * interval_ms,
                end_ms=start + (index + 1) * interval_ms - 1,
                open_px=open_px,
                high_px=close_px + Decimal("1"),
                low_px=open_px - Decimal("1"),
                close_px=close_px,
                volume=Decimal(100 + index),
                trade_count=10 + index,
                source="hyperliquid-mainnet-info",
                received_at_ms=AS_OF_MS - 50,
                schema_version=1,
            )
        )
    return tuple(candles)


def _book(market: MarketId) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=market,
        exchange_time_ms=AS_OF_MS - 100,
        receive_time=datetime.fromtimestamp((AS_OF_MS - 50) / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"l2Book:{market.canonical}:{AS_OF_MS - 100}:fixture",
        payload={
            "bids": ({"px": Decimal("100"), "sz": Decimal("100"), "n": 1},),
            "asks": ({"px": Decimal("100.05"), "sz": Decimal("100"), "n": 1},),
        },
    )


def _universe() -> dict[str, PerpMarketSnapshot]:
    markets = {_market(index).meta.market.canonical: _market(index) for index in range(30)}
    markets["M00"] = _market(0, is_delisted=True)
    markets["M01"] = _market(1, received_at_ms=AS_OF_MS - 10_000)
    invalid = _market(2)
    markets["M02"] = PerpMarketSnapshot(
        meta=invalid.meta,
        context=PerpMarketContext(
            market=invalid.context.market,
            mark_px=invalid.context.mark_px,
            mid_px=Decimal("0"),
            oracle_px=invalid.context.oracle_px,
            funding=invalid.context.funding,
            open_interest=invalid.context.open_interest,
            day_ntl_vlm=invalid.context.day_ntl_vlm,
            premium=invalid.context.premium,
            prev_day_px=invalid.context.prev_day_px,
        ),
        source=invalid.source,
        received_at_ms=invalid.received_at_ms,
        schema_version=invalid.schema_version,
    )
    return markets


def _scanner() -> FeatureScanner:
    return FeatureScanner(
        eligibility_config=EligibilityConfig(max_context_age_ms=1_000),
        shortlist_config=ShortlistConfig(
            target_size=3,
            retention_rank=5,
            ranked_watchlist_size=6,
        ),
        deep_watchlist=DeepWatchlistManager(safety_ceiling=40),
    )


def test_scan_covers_dynamic_universe_and_separates_tiers() -> None:
    current = _universe()
    scanner = _scanner()
    top_market = MarketId("", "M29")

    result = scanner.scan(
        current,
        candles_15m={top_market.canonical: _candles(top_market)},
        l2_books={top_market.canonical: _book(top_market)},
        as_of_ms=AS_OF_MS,
    )

    assert len(result.feature_snapshots) == 30
    decision_map = {item.market.canonical: item for item in result.eligibility}
    assert decision_map["M00"].rankable is False
    assert decision_map["M01"].rankable is False
    assert decision_map["M02"].rankable is False
    assert {rank.market.canonical for rank in result.ranks}.isdisjoint({"M00", "M01", "M02"})

    assert len(result.shortlist.ranked_watchlist) <= 6
    feature_map = {item.market.canonical: item for item in result.feature_snapshots}
    assert feature_map["M29"].return_15m is not None
    assert feature_map["M28"].return_15m is None
    assert decision_map["M29"].deep_ready is True
    assert decision_map["M28"].rankable is True
    assert decision_map["M28"].deep_ready is False
    assert decision_map["M28"].reasons == ("missing_deep_data",)

    assert result.subscription_plan.desired_count <= 40
    assert all("user" not in str(item).lower() for item in result.subscription_plan.subscribe)
    assert all("order" not in str(item).lower() for item in result.subscription_plan.subscribe)


def test_scan_is_deterministic_and_second_identical_scan_has_no_shortlist_churn() -> None:
    current = _universe()
    scanner = _scanner()

    first = scanner.scan(current, as_of_ms=AS_OF_MS)
    second = scanner.scan(
        dict(reversed(tuple(current.items()))),
        as_of_ms=AS_OF_MS,
    )

    assert tuple((rank.market.canonical, rank.score) for rank in first.ranks) == tuple(
        (rank.market.canonical, rank.score) for rank in second.ranks
    )
    assert first.shortlist.current == second.shortlist.current
    assert second.shortlist.added == ()
    assert second.shortlist.removed == ()


def test_future_received_market_is_skipped_instead_of_leaking_lookahead() -> None:
    current = _universe()
    future = _market(99, received_at_ms=AS_OF_MS + 1)
    current[future.meta.market.canonical] = future

    result = _scanner().scan(current, as_of_ms=AS_OF_MS)

    assert all(item.market != future.meta.market for item in result.feature_snapshots)
    assert all(item.market != future.meta.market for item in result.ranks)


def test_scan_result_contract_has_no_strategy_risk_or_order_output() -> None:
    result = _scanner().scan(_universe(), as_of_ms=AS_OF_MS)
    names = {field.name for field in fields(ScanResult)}
    rendered = str(result).lower()

    assert "direction" not in names
    assert "risk" not in names
    assert "order" not in names
    assert "long" not in rendered
    assert "short" not in rendered
