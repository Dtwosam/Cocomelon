from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    ExecutionResult,
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import (
    ExecutionCostEstimate,
    LiquidityRiskState,
    RiskAccountState,
    RiskHealthState,
    RiskLimits,
    RiskRequest,
)
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.paper import PaperExecutionAdapter

MARKET = MarketId("", "SOL")
NOW_MS = 1_000


def strategy(direction: Direction) -> StrategyDecision:
    return StrategyDecision(
        market=MARKET,
        direction=direction,
        score=Decimal("80") if direction is not Direction.NO_TRADE else Decimal("0"),
        timestamp_ms=NOW_MS - 100,
        feature_snapshot_id="phase5-features",
        lead_strategy="trend" if direction is not Direction.NO_TRADE else None,
        invalidation_price=(
            Decimal("95")
            if direction is Direction.LONG
            else Decimal("105")
            if direction is Direction.SHORT
            else None
        ),
        signal_ids=("phase5-signal",),
        reason_codes=("phase5_fixture",),
    )


def risk_request(direction: Direction) -> RiskRequest:
    return RiskRequest(
        strategy_decision=strategy(direction),
        entry_reference_price=Decimal("100"),
        correlation_bucket="crypto_beta",
        account_state=RiskAccountState(
            equity=Decimal("10000"),
            day_start_equity=Decimal("10000"),
            daily_realized_pnl=Decimal("0"),
            rolling_7d_peak_equity=Decimal("10000"),
            available_margin=Decimal("10000"),
            gross_open_notional=Decimal("0"),
            consecutive_losses=0,
            last_closed_trade_ms=None,
            as_of_ms=NOW_MS - 100,
        ),
        open_positions=(),
        health_state=RiskHealthState(
            market_data_fresh=True,
            account_state_fresh=True,
            execution_health_ok=True,
            state_consistent=True,
            as_of_ms=NOW_MS - 100,
        ),
        cost_estimate=ExecutionCostEstimate(
            entry_slippage_fraction=Decimal("0.0005"),
            stop_slippage_fraction=Decimal("0.0010"),
            round_trip_fee_fraction=Decimal("0.0009"),
        ),
        liquidity_state=LiquidityRiskState(
            entry_side_visible_notional_25bps=Decimal("100000"),
            exit_side_visible_notional_25bps=Decimal("100000"),
            venue_max_leverage=Decimal("20"),
            liquidation_price=(
                Decimal("90") if direction is not Direction.SHORT else Decimal("110")
            ),
            venue_min_notional=Decimal("10"),
            as_of_ms=NOW_MS - 100,
        ),
        limits=RiskLimits(),
        timestamp_ms=NOW_MS,
    )


def instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="hyperliquid-mainnet-meta",
    )


def book(*, bid: str, ask: str, exchange_ms: int, receive_ms: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=exchange_ms,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"l2:{MARKET.canonical}:{exchange_ms}:{bid}:{ask}",
        payload={
            "bids": ({"px": Decimal(bid), "sz": Decimal("100"), "n": 1},),
            "asks": ({"px": Decimal(ask), "sz": Decimal("100"), "n": 1},),
        },
    )


def mark(value: str, receive_ms: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=None,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"ctx:{MARKET.canonical}:{receive_ms}:{value}",
        payload={
            "mark_px": Decimal(value),
            "mid_px": Decimal(value),
            "oracle_px": Decimal(value),
            "funding": Decimal("0"),
            "open_interest": Decimal("1000"),
        },
    )


def adapter(path: Path) -> PaperExecutionAdapter:
    return PaperExecutionAdapter(
        path,
        PaperExecutionConfig(),
        starting_cash=Decimal("10000"),
        startup_timestamp_ms=500,
    )


def test_phase5_long_flows_through_phase6_and_opens_paper_position(
    tmp_path: Path,
) -> None:
    engine = adapter(tmp_path / "long.sqlite3")
    result = engine.submit_risk_request(
        risk_request(Direction.LONG),
        instrument(),
        book(bid="99.9", ask="100", exchange_ms=1_250, receive_ms=1_260),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )

    assert result.risk_decision.approved is True
    assert result.risk_decision.strategy_decision_id == strategy(Direction.LONG).decision_id
    assert result.simulation is not None
    assert result.simulation.attempt.result in {ExecutionResult.FULL, ExecutionResult.PARTIAL}
    assert result.account.positions[0].side.value == "long"
    assert result.account.positions[0].initial_risk_decision_id == result.risk_decision.risk_decision_id
    engine.close()


def test_phase5_no_trade_flows_through_phase6_and_creates_zero_exposure(
    tmp_path: Path,
) -> None:
    engine = adapter(tmp_path / "no-trade.sqlite3")
    result = engine.submit_risk_request(
        risk_request(Direction.NO_TRADE),
        instrument(),
        book(bid="99.9", ask="100", exchange_ms=1_250, receive_ms=1_260),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )

    assert result.risk_decision.approved is False
    assert result.risk_decision.reason_codes == ("strategy_no_trade",)
    assert result.plan is None
    assert result.simulation is None
    assert result.account.positions == ()
    engine.close()


def test_short_lifecycle_opens_sell_then_stop_closes_with_reduce_only_buy(
    tmp_path: Path,
) -> None:
    engine = adapter(tmp_path / "short.sqlite3")
    opened = engine.submit_risk_request(
        risk_request(Direction.SHORT),
        instrument(),
        book(bid="100", ask="100.1", exchange_ms=1_250, receive_ms=1_260),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    assert opened.risk_decision.approved is True
    assert opened.account.positions[0].side.value == "short"

    closed = engine.manage_position(
        MARKET,
        instrument(),
        mark("106", 2_000),
        book(bid="105.9", ask="106", exchange_ms=2_100, receive_ms=2_110),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        reference_price=Decimal("106"),
        timestamp_ms=2_100,
        attempt_timestamp_ms=2_400,
    )

    assert closed.plan is not None
    assert closed.plan.reduce_only is True
    assert closed.plan.side.value == "buy"
    assert closed.simulation is not None
    assert closed.simulation.attempt.result is ExecutionResult.FULL
    assert closed.account.positions == ()
    engine.close()
