from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.baseline import RecordedStateBook
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import (
    DECISION_INTERVAL_MS,
    DecisionEpoch,
    EpochMarketEvaluation,
)
from cocomelon.evidence.openings import BaselineOpeningEngine
from cocomelon.execution.paper import PaperExecutionAdapter

EVALUATED_AT_MS = 2_000_000
BTC = MarketId("", "BTC")
ETH = MarketId("", "ETH")


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _snapshot_record(
    market: MarketId,
    *,
    available_at_ms: int = EVALUATED_AT_MS - 1_000,
) -> ReplayRecord:
    payload = {
        "meta": {
            "wire_name": market.wire_name,
            "sz_decimals": 4,
            "max_leverage": 20,
            "margin_table_id": 1,
            "only_isolated": False,
            "is_delisted": False,
            "margin_mode": None,
        },
        "context": {
            "mark_px": "100",
            "mid_px": "100",
            "oracle_px": "100",
            "funding": "0",
            "open_interest": "1000000",
            "day_ntl_vlm": "500000000",
            "premium": "0",
            "prev_day_px": "99",
        },
    }
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=available_at_ms,
        source="hyperliquid-mainnet-info",
        schema_version=1,
        market=market.canonical,
        exchange_time_ms=None,
        event_key=f"snapshot:{market.canonical}:{available_at_ms}",
        payload_json=json.dumps(payload, sort_keys=True),
        event_kind="market_snapshot",
    )


def _stream_record(event: StreamEvent) -> ReplayRecord:
    receive_ms = int(event.receive_time.timestamp() * 1000)
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=receive_ms,
        source=event.source,
        schema_version=event.schema_version,
        market=event.market.canonical,
        exchange_time_ms=event.exchange_time_ms,
        event_key=event.event_key,
        payload_json=json.dumps(_canonical(event.payload), sort_keys=True),
        event_kind=event.kind.value,
    )


def _feature(market: MarketId, timestamp_ms: int) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=market,
        as_of_ms=timestamp_ms,
        source_received_at_ms=timestamp_ms - 1_000,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("500000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=Decimal("0.002"),
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=None,
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("0"),
        book_age_ms=10,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("continuous-entry-trigger-test",),
    )


def _evaluation(
    market: MarketId,
    *,
    timestamp_ms: int,
    direction: Direction,
) -> EpochMarketEvaluation:
    feature = _feature(market, timestamp_ms)
    decision = StrategyDecision(
        market=market,
        direction=direction,
        score=Decimal("80") if direction is not Direction.NO_TRADE else Decimal("0"),
        timestamp_ms=timestamp_ms,
        feature_snapshot_id=feature.snapshot_id,
        lead_strategy=None if direction is Direction.NO_TRADE else "trend",
        invalidation_price=(
            None if direction is Direction.NO_TRADE else Decimal("95")
        ),
        signal_ids=(f"signal:{market.canonical}:{timestamp_ms}",),
        reason_codes=(
            ("fixture_no_trade",)
            if direction is Direction.NO_TRADE
            else ("fixture_directional",)
        ),
    )
    return EpochMarketEvaluation(
        feature=feature,
        eligibility=EligibilityDecision(
            market=market,
            rankable=True,
            deep_ready=True,
            reasons=(),
        ),
        decision=decision,
    )


def _epoch(
    *markets: MarketId,
    timestamp_ms: int = EVALUATED_AT_MS,
    direction: Direction = Direction.LONG,
) -> DecisionEpoch:
    return DecisionEpoch(
        boundary_ms=timestamp_ms - 30_000,
        evaluated_at_ms=timestamp_ms,
        markets=tuple(
            _evaluation(
                market,
                timestamp_ms=timestamp_ms,
                direction=direction,
            )
            for market in markets
        ),
    )


def _book(
    market: MarketId,
    *,
    receive_ms: int,
    bid_size: str = "1000",
    ask_size: str = "1000",
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=market,
        exchange_time_ms=receive_ms,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"book:{market.canonical}:{receive_ms}:{bid_size}:{ask_size}",
        payload={
            "bids": (
                {"px": Decimal("99.9"), "sz": Decimal(bid_size), "n": 1},
            ),
            "asks": (
                {"px": Decimal("100.1"), "sz": Decimal(ask_size), "n": 1},
            ),
        },
    )


def _trade(
    market: MarketId,
    *,
    receive_ms: int,
    side: str,
    tid: int,
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.TRADE,
        market=market,
        exchange_time_ms=receive_ms,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"trade:{market.canonical}:{receive_ms}:{tid}",
        payload={
            "side": side,
            "price": Decimal("100"),
            "size": Decimal("10"),
            "hash": f"hash-{tid}",
            "tid": tid,
            "users": ("buyer", "seller"),
        },
    )


def _state(*markets: MarketId) -> RecordedStateBook:
    state = RecordedStateBook(microstructure_window_ms=60_000)
    for market in markets:
        record = _snapshot_record(market)
        state.apply(record, record.available_at_ms)
    return state


def _adapter(path: Path) -> PaperExecutionAdapter:
    return PaperExecutionAdapter(
        path,
        PaperExecutionConfig(),
        starting_cash=Decimal("10000"),
        startup_timestamp_ms=EVALUATED_AT_MS - 10_000,
    )


def _apply(state: RecordedStateBook, event: StreamEvent) -> None:
    record = _stream_record(event)
    state.apply(record, record.available_at_ms)


def _add_long_support(
    state: RecordedStateBook,
    market: MarketId,
    *,
    start_ms: int,
) -> StreamEvent:
    for offset in range(5):
        _apply(
            state,
            _trade(
                market,
                receive_ms=start_ms + offset,
                side="B",
                tid=offset + 1,
            ),
        )
    supportive = _book(
        market,
        receive_ms=start_ms + 10,
        bid_size="2000",
        ask_size="1000",
    )
    _apply(state, supportive)
    return supportive


def test_continuous_entry_waits_for_fresh_order_flow_support(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path / "entry-support.sqlite3")
    state = _state(BTC)
    engine = BaselineOpeningEngine(
        BaselineReplayConfig(),
        adapter,
        state,
        require_fresh_order_flow_entry=True,
    )
    engine.stage_epoch(_epoch(BTC))

    neutral = _book(
        BTC,
        receive_ms=EVALUATED_AT_MS + 250,
    )
    _apply(state, neutral)
    assert engine.on_book(neutral, EVALUATED_AT_MS + 250) == ()
    assert engine.pending_markets == (BTC,)
    assert adapter.account.positions == ()

    supportive = _add_long_support(
        state,
        BTC,
        start_ms=EVALUATED_AT_MS + 300,
    )
    outcomes = engine.on_book(
        supportive,
        int(supportive.receive_time.timestamp() * 1000),
    )

    assert len(outcomes) == 1
    assert outcomes[0].risk_decision.approved is True
    assert outcomes[0].simulation is not None
    assert outcomes[0].simulation.fills
    assert engine.pending_markets == ()
    assert len(adapter.account.positions) == 1
    activity = engine.entry_timing_activity
    assert activity.trigger_waits == 1
    assert activity.trigger_approvals == 1
    assert dict(activity.wait_reason_counts)["insufficient_trade_count"] == 1
    adapter.close()


def test_favorable_market_is_not_blocked_by_other_pending_market(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path / "independent-market-trigger.sqlite3")
    state = _state(BTC, ETH)
    engine = BaselineOpeningEngine(
        BaselineReplayConfig(),
        adapter,
        state,
        require_fresh_order_flow_entry=True,
    )
    engine.stage_epoch(_epoch(BTC, ETH))

    eth_supportive = _add_long_support(
        state,
        ETH,
        start_ms=EVALUATED_AT_MS + 300,
    )
    outcomes = engine.on_book(
        eth_supportive,
        int(eth_supportive.receive_time.timestamp() * 1000),
    )

    assert len(outcomes) == 1
    assert outcomes[0].risk_decision.market == ETH
    assert tuple(market.canonical for market in engine.pending_markets) == ("BTC",)
    assert tuple(position.market for position in adapter.account.positions) == (ETH,)
    adapter.close()


def test_new_no_trade_epoch_supersedes_older_pending_setup(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path / "supersede.sqlite3")
    state = _state(BTC)
    engine = BaselineOpeningEngine(
        BaselineReplayConfig(),
        adapter,
        state,
        require_fresh_order_flow_entry=True,
    )
    engine.stage_epoch(_epoch(BTC))
    assert engine.pending_markets == (BTC,)

    engine.stage_epoch(
        _epoch(
            BTC,
            timestamp_ms=EVALUATED_AT_MS + DECISION_INTERVAL_MS,
            direction=Direction.NO_TRADE,
        )
    )

    assert engine.pending_markets == ()
    assert engine.entry_timing_activity.superseded_candidates == 1
    adapter.close()


def test_pending_setup_expires_after_one_primary_setup_interval(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path / "expiry.sqlite3")
    state = _state(BTC)
    engine = BaselineOpeningEngine(
        BaselineReplayConfig(),
        adapter,
        state,
        require_fresh_order_flow_entry=True,
    )
    engine.stage_epoch(_epoch(BTC))

    expiry_ms = EVALUATED_AT_MS + DECISION_INTERVAL_MS
    book = _book(BTC, receive_ms=expiry_ms)
    _apply(state, book)
    assert engine.on_book(book, expiry_ms) == ()

    assert engine.pending_markets == ()
    assert engine.entry_timing_activity.expired_candidates == 1
    assert adapter.account.positions == ()
    adapter.close()
