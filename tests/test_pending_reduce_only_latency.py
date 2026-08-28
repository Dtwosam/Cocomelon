from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    ExecutionResult,
    InstrumentExecutionSpec,
    PaperExecutionConfig,
    PositionActionType,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import RiskDecision
from cocomelon.domain.strategy import Direction
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.paper import PaperExecutionAdapter

MARKET = MarketId("", "SOL")
FOUR_HOURS_MS = 14_400_000


def _approved_risk() -> RiskDecision:
    return RiskDecision(
        strategy_decision_id="strategy-long",
        market=MARKET,
        direction=Direction.LONG,
        approved=True,
        reason_codes=("risk_approved",),
        target_risk_amount=Decimal("25"),
        approved_risk_amount=Decimal("20"),
        approved_notional=Decimal("200"),
        entry_reference_price=Decimal("100"),
        stop_price=Decimal("95"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
        correlation_bucket="crypto_beta",
        binding_caps=(),
        timestamp_ms=1_000,
    )


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="hyperliquid-mainnet-meta",
    )


def _book(*, exchange_ms: int, receive_ms: int, bid: str, ask: str) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=exchange_ms,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"l2:{MARKET.canonical}:{exchange_ms}:{bid}:{ask}",
        payload={
            "bids": ({"px": Decimal(bid), "sz": Decimal("10"), "n": 1},),
            "asks": ({"px": Decimal(ask), "sz": Decimal("10"), "n": 1},),
        },
    )


def _mark(mark_px: str, *, receive_ms: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=None,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"ctx:{MARKET.canonical}:{receive_ms}:{mark_px}",
        payload={
            "mark_px": Decimal(mark_px),
            "mid_px": Decimal(mark_px),
            "oracle_px": Decimal(mark_px),
            "funding": Decimal("0"),
            "open_interest": Decimal("1000"),
        },
    )


def _adapter(
    path: Path,
    config: PaperExecutionConfig | None = None,
) -> PaperExecutionAdapter:
    return PaperExecutionAdapter(
        path,
        config or PaperExecutionConfig(),
        starting_cash=Decimal("10000"),
        startup_timestamp_ms=500,
    )


def test_stop_exit_reuses_pending_reduce_only_plan_after_latency(tmp_path: Path) -> None:
    engine = _adapter(tmp_path / "paper.sqlite3")
    opened = engine.submit_opening(
        _approved_risk(),
        _instrument(),
        _book(exchange_ms=1_250, receive_ms=1_260, bid="99.9", ask="100"),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    assert len(opened.account.positions) == 1

    first = engine.manage_position(
        MARKET,
        _instrument(),
        _mark("94", receive_ms=2_000),
        _book(exchange_ms=2_100, receive_ms=2_110, bid="94", ask="94.1"),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        reference_price=Decimal("94"),
        timestamp_ms=2_100,
        attempt_timestamp_ms=2_100,
    )

    assert first.plan is not None
    assert first.plan.reduce_only is True
    assert first.simulation is not None
    assert first.simulation.attempt.result is ExecutionResult.REJECTED
    assert first.simulation.attempt.reason_codes == ("LATENCY_NOT_ELAPSED",)
    assert first.account.positions

    second = engine.manage_position(
        MARKET,
        _instrument(),
        _mark("94", receive_ms=2_300),
        _book(exchange_ms=2_400, receive_ms=2_410, bid="94", ask="94.1"),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        reference_price=Decimal("94"),
        timestamp_ms=2_400,
        attempt_timestamp_ms=2_410,
    )

    assert second.plan is not None
    assert second.plan.plan_id == first.plan.plan_id
    assert second.simulation is not None
    assert second.simulation.attempt.result is ExecutionResult.FULL
    assert second.account.positions == ()
    engine.close()


def test_thesis_expiry_reuses_normal_reduce_only_latency_and_flattens(
    tmp_path: Path,
) -> None:
    config = PaperExecutionConfig(
        config_version="phase7-v2-4h-thesis-expiry",
        max_position_age_ms=FOUR_HOURS_MS,
    )
    engine = _adapter(tmp_path / "thesis-expiry.sqlite3", config)
    risk = _approved_risk()
    opened = engine.submit_opening(
        risk,
        _instrument(),
        _book(exchange_ms=1_250, receive_ms=1_260, bid="99.9", ask="100"),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    assert opened.simulation is not None
    assert opened.simulation.attempt.result is ExecutionResult.FULL
    assert len(opened.account.positions) == 1
    position = opened.account.positions[0]
    expiry_ms = position.opened_at_ms + FOUR_HOURS_MS

    before = engine.manage_position(
        MARKET,
        _instrument(),
        _mark("101", receive_ms=expiry_ms - 1),
        _book(
            exchange_ms=expiry_ms - 1,
            receive_ms=expiry_ms - 1,
            bid="100.9",
            ask="101",
        ),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        reference_price=Decimal("101"),
        timestamp_ms=expiry_ms - 1,
        attempt_timestamp_ms=expiry_ms - 1,
    )
    assert before.action.action_type is PositionActionType.HOLD
    assert before.plan is None
    assert before.account.positions == (position,)

    expired = engine.manage_position(
        MARKET,
        _instrument(),
        _mark("101", receive_ms=expiry_ms),
        _book(
            exchange_ms=expiry_ms,
            receive_ms=expiry_ms,
            bid="100.9",
            ask="101",
        ),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        reference_price=Decimal("101"),
        timestamp_ms=expiry_ms,
        attempt_timestamp_ms=expiry_ms,
    )
    assert expired.action.action_type is PositionActionType.EXIT_THESIS
    assert expired.action.reason_codes == ("MAX_HOLD_EXPIRED",)
    assert expired.plan is not None
    assert expired.plan.reduce_only is True
    assert expired.plan.risk_decision_id == risk.risk_decision_id
    assert expired.plan.strategy_decision_id == risk.strategy_decision_id
    assert expired.plan.requested_quantity == position.quantity
    assert expired.simulation is not None
    assert expired.simulation.attempt.result is ExecutionResult.REJECTED
    assert expired.simulation.attempt.reason_codes == ("LATENCY_NOT_ELAPSED",)
    assert expired.account.positions == (position,)

    retry_ms = expiry_ms + config.latency_ms + 1
    closed = engine.manage_position(
        MARKET,
        _instrument(),
        _mark("101", receive_ms=retry_ms),
        _book(
            exchange_ms=retry_ms,
            receive_ms=retry_ms,
            bid="100.9",
            ask="101",
        ),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        reference_price=Decimal("101"),
        timestamp_ms=retry_ms,
        attempt_timestamp_ms=retry_ms,
    )
    assert closed.plan is not None
    assert closed.plan.plan_id == expired.plan.plan_id
    assert closed.simulation is not None
    assert closed.simulation.attempt.result is ExecutionResult.FULL
    assert closed.simulation.attempt.fee > Decimal("0")
    assert closed.simulation.attempt.filled_quantity == position.quantity
    assert closed.account.positions == ()
    engine.close()
