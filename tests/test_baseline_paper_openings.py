from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import ExecutionResult, PaperExecutionConfig
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
from cocomelon.evidence.epochs import DecisionEpoch, EpochMarketEvaluation
from cocomelon.evidence.openings import (
    BaselineOpeningEngine,
    conservative_cost_estimate,
    paper_liquidation_surrogate,
)
from cocomelon.execution.paper import PaperExecutionAdapter

EVALUATED_AT_MS = 2_000_000
BTC = MarketId("", "BTC")
ETH = MarketId("", "ETH")
SOL = MarketId("", "SOL")


def _snapshot_record(
    market: MarketId,
    *,
    available_at_ms: int = EVALUATED_AT_MS - 1_000,
    mark: str = "100",
) -> ReplayRecord:
    price = Decimal(mark)
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
            "mark_px": str(price),
            "mid_px": str(price),
            "oracle_px": str(price),
            "funding": "0",
            "open_interest": "1000000",
            "day_ntl_vlm": "500000000",
            "premium": "0",
            "prev_day_px": str(price - Decimal("1")),
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


def _feature(market: MarketId) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=market,
        as_of_ms=EVALUATED_AT_MS,
        source_received_at_ms=EVALUATED_AT_MS - 1_000,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("500000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=None,
        return_15m=Decimal("0.01"),
        return_1h=None,
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("0"),
        book_age_ms=10,
        trend_regime=TrendRegime.UNKNOWN,
        volatility_regime=VolatilityRegime.UNKNOWN,
        provenance=("test",),
    )


def _evaluation(market: MarketId) -> EpochMarketEvaluation:
    feature = _feature(market)
    decision = StrategyDecision(
        market=market,
        direction=Direction.LONG,
        score=Decimal("80"),
        timestamp_ms=EVALUATED_AT_MS,
        feature_snapshot_id=feature.snapshot_id,
        lead_strategy="trend",
        invalidation_price=Decimal("95"),
        signal_ids=(f"signal:{market.canonical}",),
        reason_codes=("fixture_directional",),
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


def _epoch(*markets: MarketId) -> DecisionEpoch:
    return DecisionEpoch(
        boundary_ms=EVALUATED_AT_MS - 30_000,
        evaluated_at_ms=EVALUATED_AT_MS,
        markets=tuple(_evaluation(market) for market in reversed(markets)),
    )


def _book(
    market: MarketId,
    *,
    receive_ms: int,
    bid: str = "99.9",
    ask: str = "100.1",
    size: str = "1000",
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=market,
        exchange_time_ms=receive_ms,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"book:{market.canonical}:{receive_ms}:{bid}:{ask}:{size}",
        payload={
            "bids": ({"px": Decimal(bid), "sz": Decimal(size), "n": 1},),
            "asks": ({"px": Decimal(ask), "sz": Decimal(size), "n": 1},),
        },
    )


def _state(*markets: MarketId, snapshot_age_ms: int = 1_000) -> RecordedStateBook:
    state = RecordedStateBook(microstructure_window_ms=60_000)
    for market in markets:
        record = _snapshot_record(
            market,
            available_at_ms=EVALUATED_AT_MS - snapshot_age_ms,
        )
        state.apply(record, record.available_at_ms)
    return state


def _adapter(path: Path) -> PaperExecutionAdapter:
    return PaperExecutionAdapter(
        path,
        PaperExecutionConfig(),
        starting_cash=Decimal("10000"),
        startup_timestamp_ms=EVALUATED_AT_MS - 10_000,
    )


def test_cost_and_liquidation_surrogates_are_conservative_and_directional() -> None:
    config = PaperExecutionConfig()
    costs = conservative_cost_estimate(config)

    assert costs.entry_slippage_fraction == Decimal("0.0025")
    assert costs.stop_slippage_fraction == Decimal("0.0025")
    assert costs.round_trip_fee_fraction == Decimal("0.00090")
    assert paper_liquidation_surrogate(
        Decimal("100"),
        Direction.LONG,
        paper_max_leverage=Decimal("3"),
        venue_max_leverage=Decimal("20"),
    ) == Decimal("66.66666666666666666666666667")
    assert paper_liquidation_surrogate(
        Decimal("100"),
        Direction.SHORT,
        paper_max_leverage=Decimal("3"),
        venue_max_leverage=Decimal("20"),
    ) == Decimal("133.3333333333333333333333333")


def test_books_before_latency_never_fill_and_later_recorded_book_may_fill(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path / "latency.sqlite3")
    state = _state(BTC)
    engine = BaselineOpeningEngine(
        BaselineReplayConfig(),
        adapter,
        state,
    )
    engine.stage_epoch(_epoch(BTC))

    early = _book(BTC, receive_ms=EVALUATED_AT_MS + 249)
    assert engine.on_book(early, EVALUATED_AT_MS + 249) == ()
    assert adapter.account.positions == ()

    eligible = _book(BTC, receive_ms=EVALUATED_AT_MS + 250)
    outcomes = engine.on_book(eligible, EVALUATED_AT_MS + 250)

    assert len(outcomes) == 1
    submission = outcomes[0]
    assert submission.plan is not None
    assert submission.plan.earliest_execution_ms == EVALUATED_AT_MS + 250
    assert submission.simulation is not None
    assert submission.simulation.attempt.result in {
        ExecutionResult.FULL,
        ExecutionResult.PARTIAL,
    }
    assert submission.simulation.fills
    assert all(
        fill.source_event_key.startswith(eligible.event_key)
        for fill in submission.simulation.fills
    )
    assert len(adapter.account.positions) == 1
    adapter.close()


def test_epoch_candidates_execute_in_canonical_order_and_share_open_risk(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path / "shared-risk.sqlite3")
    state = _state(BTC, ETH, SOL)
    config = BaselineReplayConfig()
    engine = BaselineOpeningEngine(config, adapter, state)
    engine.stage_epoch(_epoch(SOL, BTC, ETH))
    eligible_ms = EVALUATED_AT_MS + config.execution.latency_ms

    assert engine.on_book(_book(SOL, receive_ms=eligible_ms), eligible_ms) == ()
    assert engine.on_book(_book(ETH, receive_ms=eligible_ms), eligible_ms) == ()
    outcomes = engine.on_book(_book(BTC, receive_ms=eligible_ms), eligible_ms)

    assert tuple(outcome.risk_decision.market.canonical for outcome in outcomes) == (
        "BTC",
        "ETH",
        "SOL",
    )
    assert outcomes[0].risk_decision.approved is True
    assert outcomes[1].risk_decision.approved is True
    assert outcomes[2].risk_decision.approved is False
    assert outcomes[2].risk_decision.reason_codes == ("correlation_bucket_exhausted",)
    assert outcomes[2].plan is None
    assert outcomes[2].simulation is None
    assert tuple(
        position.market.canonical for position in adapter.account.positions
    ) == ("BTC", "ETH")
    assert adapter.account.updated_at_ms == eligible_ms
    adapter.close()


def test_insufficient_visible_depth_and_stale_market_data_create_zero_exposure(
    tmp_path: Path,
) -> None:
    config = BaselineReplayConfig()

    thin_adapter = _adapter(tmp_path / "thin.sqlite3")
    thin_state = _state(BTC)
    thin = BaselineOpeningEngine(config, thin_adapter, thin_state)
    thin.stage_epoch(_epoch(BTC))
    eligible_ms = EVALUATED_AT_MS + config.execution.latency_ms
    thin_outcomes = thin.on_book(
        _book(BTC, receive_ms=eligible_ms, size="0.0001"),
        eligible_ms,
    )
    assert len(thin_outcomes) == 1
    assert thin_outcomes[0].risk_decision.approved is False
    assert thin_outcomes[0].risk_decision.reason_codes == ("below_venue_min_notional",)
    assert thin_adapter.account.positions == ()
    thin_adapter.close()

    stale_adapter = _adapter(tmp_path / "stale.sqlite3")
    stale_state = _state(BTC, snapshot_age_ms=10_000)
    stale = BaselineOpeningEngine(config, stale_adapter, stale_state)
    stale.stage_epoch(_epoch(BTC))
    stale_book = _book(BTC, receive_ms=eligible_ms)
    stale_outcomes = stale.on_book(stale_book, eligible_ms + 2_000)
    assert len(stale_outcomes) == 1
    assert stale_outcomes[0].risk_decision.approved is False
    assert stale_outcomes[0].risk_decision.reason_codes == ("stale_market_data",)
    assert stale_adapter.account.positions == ()
    stale_adapter.close()


def test_account_mark_refresh_is_durable_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "mark-refresh.sqlite3"
    adapter = _adapter(path)
    adapter.mark_account_to_market({}, timestamp_ms=EVALUATED_AT_MS)
    state_id = adapter.account.state_id
    adapter.close()

    recovered = _adapter(path)
    assert recovered.health.healthy_for_new_exposure is True
    assert recovered.account.state_id == state_id
    assert recovered.account.updated_at_ms == EVALUATED_AT_MS
    recovered.close()
