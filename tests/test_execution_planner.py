from decimal import ROUND_UP, Decimal, getcontext

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    OrderSide,
    PaperExecutionConfig,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import RiskDecision
from cocomelon.domain.strategy import Direction
from cocomelon.execution.planner import PlanningRejection, plan_opening_order


def approved_risk(
    *,
    direction: Direction = Direction.LONG,
    approved_notional: Decimal = Decimal("1000"),
    entry_reference_price: Decimal = Decimal("100"),
) -> RiskDecision:
    return RiskDecision(
        strategy_decision_id="strategy-1",
        market=MarketId(dex="", coin="SOL"),
        direction=direction,
        approved=True,
        reason_codes=("risk_approved",),
        target_risk_amount=Decimal("25"),
        approved_risk_amount=Decimal("20"),
        approved_notional=approved_notional,
        entry_reference_price=entry_reference_price,
        stop_price=Decimal("95") if direction is Direction.LONG else Decimal("105"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.02"),
        correlation_bucket="sol-beta",
        binding_caps=("liquidity",),
        timestamp_ms=1_000,
    )


def rejected_risk() -> RiskDecision:
    return RiskDecision(
        strategy_decision_id="strategy-2",
        market=MarketId(dex="", coin="SOL"),
        direction=Direction.LONG,
        approved=False,
        reason_codes=("daily_lockout",),
        target_risk_amount=Decimal("25"),
        approved_risk_amount=Decimal("0"),
        approved_notional=Decimal("0"),
        entry_reference_price=Decimal("100"),
        stop_price=None,
        stop_distance_fraction=None,
        effective_loss_fraction=None,
        correlation_bucket="sol-beta",
        binding_caps=(),
        timestamp_ms=1_000,
    )


def native_spec(*, sz_decimals: int = 2) -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MarketId(dex="", coin="SOL"),
        sz_decimals=sz_decimals,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=1_900,
        metadata_source="hyperliquid-mainnet-info",
    )


def test_long_and_short_map_to_opening_sides() -> None:
    config = PaperExecutionConfig()
    long_plan = plan_opening_order(
        approved_risk(), native_spec(), config, Decimal("100"), 2_000
    )
    short_plan = plan_opening_order(
        approved_risk(direction=Direction.SHORT),
        native_spec(),
        config,
        Decimal("100"),
        2_000,
    )

    assert long_plan.side is OrderSide.BUY
    assert short_plan.side is OrderSide.SELL
    assert long_plan.reduce_only is False
    assert short_plan.reduce_only is False


def test_rejected_risk_decision_fails_closed() -> None:
    result = plan_opening_order(
        rejected_risk(), native_spec(), PaperExecutionConfig(), Decimal("100"), 2_000
    )

    assert isinstance(result, PlanningRejection)
    assert result.reason == "RISK_NOT_APPROVED"


def test_named_perp_dex_fails_closed() -> None:
    spec = InstrumentExecutionSpec(
        market=MarketId(dex="xyz", coin="SOL"),
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=1_900,
        metadata_source="hyperliquid-mainnet-info",
    )
    result = plan_opening_order(
        approved_risk(), spec, PaperExecutionConfig(), Decimal("100"), 2_000
    )

    assert isinstance(result, PlanningRejection)
    assert result.reason == "UNSUPPORTED_NON_NATIVE_PERP_DEX"


def test_quantity_rounds_down_and_never_breaches_approved_notional() -> None:
    risk = approved_risk(approved_notional=Decimal("1000"))
    plan = plan_opening_order(
        risk,
        native_spec(sz_decimals=3),
        PaperExecutionConfig(),
        Decimal("333"),
        2_000,
    )

    assert plan.requested_quantity == Decimal("3.003")
    assert plan.requested_quantity * plan.execution_reference_price <= risk.approved_notional


def test_below_minimum_notional_rejects_without_upsizing() -> None:
    risk = approved_risk(approved_notional=Decimal("9.99"))
    result = plan_opening_order(
        risk, native_spec(), PaperExecutionConfig(), Decimal("100"), 2_000
    )

    assert isinstance(result, PlanningRejection)
    assert result.reason == "BELOW_MINIMUM_NOTIONAL"


def test_hostile_decimal_context_cannot_increase_planned_quantity() -> None:
    risk = approved_risk(approved_notional=Decimal("1000"))
    original = getcontext().copy()
    try:
        getcontext().prec = 6
        getcontext().rounding = ROUND_UP
        plan = plan_opening_order(
            risk,
            native_spec(sz_decimals=4),
            PaperExecutionConfig(),
            Decimal("333"),
            2_000,
        )
    finally:
        getcontext().prec = original.prec
        getcontext().rounding = original.rounding

    assert plan.requested_quantity == Decimal("3.0030")
    assert plan.requested_quantity * plan.execution_reference_price <= risk.approved_notional


def test_plan_records_latency_and_risk_ceiling() -> None:
    risk = approved_risk()
    plan = plan_opening_order(
        risk, native_spec(), PaperExecutionConfig(), Decimal("100"), 2_000
    )

    assert plan.risk_decision_id == risk.risk_decision_id
    assert plan.approved_notional_ceiling == risk.approved_notional
    assert plan.created_at_ms == 2_000
    assert plan.earliest_execution_ms == 2_250
