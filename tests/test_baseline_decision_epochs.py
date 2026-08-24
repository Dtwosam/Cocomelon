from __future__ import annotations

import json
from decimal import Decimal

from cocomelon.domain.market import MarketId, PerpMarketContext, PerpMarketMeta, PerpMarketSnapshot
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction, StrategyContext
from cocomelon.evidence.baseline import BaselineDecisionEngine
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.features.assemble import assemble_feature_snapshot
from cocomelon.features.broad import calculate_broad_features
from cocomelon.features.candles import calculate_candle_features
from cocomelon.features.microstructure import calculate_microstructure_features
from cocomelon.features.regime import assign_volatility_regimes
from cocomelon.scanner.eligibility import derive_eligibility_thresholds, evaluate_eligibility
from cocomelon.strategies.engine import evaluate_strategies
from cocomelon.strategies.microstructure import build_microstructure_window

INTERVAL_MS = 900_000
BOUNDARY_MS = 1_800_000
EVALUATED_AT_MS = BOUNDARY_MS + 30_000
BTC = MarketId("", "BTC")
ETH = MarketId("", "ETH")


def _record(
    market: MarketId,
    *,
    kind: str,
    available_at_ms: int,
    payload: dict[str, object],
    exchange_time_ms: int | None = None,
    key: str | None = None,
    source: str | None = None,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=available_at_ms,
        source=source or ("hyperliquid-mainnet-info" if kind == "market_snapshot" else "hyperliquid-mainnet-ws"),
        schema_version=1,
        market=market.canonical,
        exchange_time_ms=exchange_time_ms,
        event_key=key or f"{kind}:{market.canonical}:{available_at_ms}",
        payload_json=json.dumps(payload, sort_keys=True),
        event_kind=kind,
    )


def _snapshot_payload(market: MarketId, *, mark: str) -> dict[str, object]:
    price = Decimal(mark)
    return {
        "meta": {
            "wire_name": market.wire_name,
            "sz_decimals": 5,
            "max_leverage": 40,
            "margin_table_id": 1,
            "only_isolated": False,
            "is_delisted": False,
            "margin_mode": None,
        },
        "context": {
            "mark_px": str(price),
            "mid_px": str(price + Decimal("0.1")),
            "oracle_px": str(price - Decimal("0.1")),
            "funding": "0.00001",
            "open_interest": "1000000",
            "day_ntl_vlm": "500000000",
            "premium": "0.0001",
            "prev_day_px": str(price - Decimal("1")),
        },
    }


def _candle_payload(market: MarketId, *, close: str) -> dict[str, object]:
    price = Decimal(close)
    return {
        "start_ms": BOUNDARY_MS - INTERVAL_MS,
        "end_ms": BOUNDARY_MS,
        "interval": "15m",
        "open_px": str(price - Decimal("1")),
        "high_px": str(price + Decimal("2")),
        "low_px": str(price - Decimal("2")),
        "close_px": str(price),
        "volume": "12345",
        "trade_count": 500,
    }


def _book_payload(*, bid: str, ask: str) -> dict[str, object]:
    return {
        "bids": [{"px": bid, "sz": "100", "n": 3}],
        "asks": [{"px": ask, "sz": "100", "n": 4}],
    }


def _market_rows(market: MarketId, *, mark: str) -> tuple[ReplayRecord, ...]:
    price = Decimal(mark)
    return (
        _record(
            market,
            kind="market_snapshot",
            available_at_ms=BOUNDARY_MS - 20_000,
            payload=_snapshot_payload(market, mark=mark),
            source="hyperliquid-mainnet-info",
        ),
        _record(
            market,
            kind="candle",
            available_at_ms=BOUNDARY_MS - 10_000,
            exchange_time_ms=BOUNDARY_MS - INTERVAL_MS,
            payload=_candle_payload(market, close=mark),
        ),
        _record(
            market,
            kind="l2_book",
            available_at_ms=BOUNDARY_MS + 29_000,
            exchange_time_ms=BOUNDARY_MS + 29_000,
            payload=_book_payload(
                bid=str(price - Decimal("0.1")),
                ask=str(price + Decimal("0.1")),
            ),
        ),
    )


def _ordered_rows(reverse_same_time: bool) -> tuple[ReplayRecord, ...]:
    btc = _market_rows(BTC, mark="100")
    eth = _market_rows(ETH, mark="200")
    rows: list[ReplayRecord] = []
    for index in range(3):
        pair = (btc[index], eth[index])
        rows.extend(reversed(pair) if reverse_same_time else pair)
    return tuple(rows)


def _run_epoch(rows: tuple[ReplayRecord, ...], markets: tuple[MarketId, ...]) -> object:
    engine = BaselineDecisionEngine(markets, replay_config=BaselineReplayConfig())
    emitted = []
    for row in rows:
        emitted.extend(engine.observe(row, row.available_at_ms))
    trigger = _record(
        markets[0],
        kind="trade",
        available_at_ms=EVALUATED_AT_MS + 1,
        exchange_time_ms=EVALUATED_AT_MS + 1,
        payload={
            "side": "B",
            "price": "100",
            "size": "1",
            "hash": "0xtrigger",
            "tid": 999,
            "users": ["0xa", "0xb"],
        },
    )
    emitted.extend(engine.observe(trigger, trigger.available_at_ms))
    assert len(emitted) == 1
    return emitted[0]


def test_epoch_identity_is_invariant_to_same_time_market_arrival_order() -> None:
    first = _run_epoch(_ordered_rows(False), (BTC, ETH))
    second = _run_epoch(_ordered_rows(True), (ETH, BTC))

    assert first == second
    assert first.boundary_ms == BOUNDARY_MS
    assert first.evaluated_at_ms == EVALUATED_AT_MS
    assert tuple(item.feature.market.canonical for item in first.markets) == ("BTC", "ETH")
    assert tuple(item.feature.snapshot_id for item in first.markets) == tuple(
        item.feature.snapshot_id for item in second.markets
    )
    assert tuple(item.decision.decision_id for item in first.markets) == tuple(
        item.decision.decision_id for item in second.markets
    )


def test_epoch_never_borrows_evidence_arriving_after_evaluated_at() -> None:
    engine = BaselineDecisionEngine((BTC,), replay_config=BaselineReplayConfig())
    emitted = []
    for row in _market_rows(BTC, mark="100"):
        emitted.extend(engine.observe(row, row.available_at_ms))

    future_book = _record(
        BTC,
        kind="l2_book",
        available_at_ms=EVALUATED_AT_MS + 10_000,
        exchange_time_ms=EVALUATED_AT_MS + 10_000,
        payload=_book_payload(bid="109.9", ask="110.1"),
        key="future-book",
    )
    emitted.extend(engine.observe(future_book, future_book.available_at_ms))
    assert len(emitted) == 1
    frozen = emitted[0]

    future_candle = _record(
        BTC,
        kind="candle",
        available_at_ms=EVALUATED_AT_MS + 20_000,
        exchange_time_ms=BOUNDARY_MS,
        payload={
            **_candle_payload(BTC, close="120"),
            "start_ms": BOUNDARY_MS,
            "end_ms": BOUNDARY_MS + INTERVAL_MS,
        },
        key="future-candle",
    )
    assert engine.observe(future_candle, future_candle.available_at_ms) == ()
    assert frozen.markets[0].feature.as_of_ms == EVALUATED_AT_MS
    assert frozen.markets[0].feature.spread_bps < Decimal("100")


def test_epoch_reuses_existing_feature_eligibility_and_strategy_formulas() -> None:
    rows = _market_rows(BTC, mark="100")
    epoch = _run_epoch(rows, (BTC,))
    evaluation = epoch.markets[0]

    snapshot_row, candle_row, book_row = rows
    snapshot = PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=BTC,
            wire_name="BTC",
            sz_decimals=5,
            max_leverage=40,
            margin_table_id=1,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=BTC,
            mark_px=Decimal("100"),
            mid_px=Decimal("100.1"),
            oracle_px=Decimal("99.9"),
            funding=Decimal("0.00001"),
            open_interest=Decimal("1000000"),
            day_ntl_vlm=Decimal("500000000"),
            premium=Decimal("0.0001"),
            prev_day_px=Decimal("99"),
        ),
        source=snapshot_row.source,
        received_at_ms=snapshot_row.available_at_ms,
        schema_version=1,
    )
    from cocomelon.evidence.baseline import replay_record_candle, replay_record_stream_event

    candle = replay_record_candle(candle_row)
    book = replay_record_stream_event(book_row)
    broad = calculate_broad_features(snapshot, None, as_of_ms=EVALUATED_AT_MS)
    candle_values = calculate_candle_features(
        BTC,
        candles_15m=(candle,),
        as_of_ms=EVALUATED_AT_MS,
    )
    micro = calculate_microstructure_features(book, as_of_ms=EVALUATED_AT_MS)
    feature = assemble_feature_snapshot(
        BTC,
        broad,
        candle=candle_values,
        microstructure=micro,
        as_of_ms=EVALUATED_AT_MS,
        provenance=(snapshot.source, candle.source, book.source),
    )
    expected_feature = assign_volatility_regimes((feature,))[0]
    thresholds = derive_eligibility_thresholds((expected_feature,), BaselineReplayConfig().eligibility)
    eligibility = evaluate_eligibility(
        snapshot,
        expected_feature,
        thresholds,
        BaselineReplayConfig().eligibility,
    )
    micro_window = build_microstructure_window(
        (book,),
        market=BTC,
        as_of_ms=EVALUATED_AT_MS,
        window_ms=BaselineReplayConfig().microstructure_window_ms,
    )
    expected_decision = evaluate_strategies(
        StrategyContext(
            market_snapshot=snapshot,
            feature_snapshot=expected_feature,
            eligibility=eligibility,
            candles_5m=(),
            candles_15m=(candle,),
            microstructure=micro_window,
            as_of_ms=EVALUATED_AT_MS,
        )
    ).decision

    assert evaluation.feature == expected_feature
    assert evaluation.eligibility == eligibility
    assert evaluation.decision == expected_decision


def test_missing_or_stale_deep_context_is_a_hard_no_trade() -> None:
    config = BaselineReplayConfig()
    engine = BaselineDecisionEngine((BTC,), replay_config=config)
    snapshot = _record(
        BTC,
        kind="market_snapshot",
        available_at_ms=BOUNDARY_MS + 10_000,
        payload=_snapshot_payload(BTC, mark="100"),
        source="hyperliquid-mainnet-info",
    )
    engine.observe(snapshot, snapshot.available_at_ms)
    epochs = engine.flush(EVALUATED_AT_MS)

    assert len(epochs) == 1
    item = epochs[0].markets[0]
    assert item.eligibility.rankable is True
    assert item.eligibility.deep_ready is False
    assert item.decision.direction is Direction.NO_TRADE
    assert item.decision.reason_codes == ("not_deep_ready",)
