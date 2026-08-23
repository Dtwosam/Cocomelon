from decimal import ROUND_UP, Decimal, getcontext, localcontext

import pytest

from cocomelon.domain.execution import (
    ExecutionResult,
    InstrumentExecutionSpec,
    OrderSide,
    OrderType,
    PaperExecutionConfig,
    PaperFill,
    PaperOrderPlan,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.market import MarketId


def opening_plan_kwargs() -> dict[str, object]:
    return {
        "risk_decision_id": "risk-1",
        "strategy_decision_id": "strategy-1",
        "market": MarketId(dex="", coin="ETH"),
        "side": OrderSide.BUY,
        "requested_quantity": Decimal("1.23456"),
        "order_type": OrderType.MARKETABLE_IOC,
        "reduce_only": False,
        "execution_reference_price": Decimal("3500.125"),
        "max_slippage_bps": Decimal("25"),
        "stop_price": Decimal("3400"),
        "approved_notional_ceiling": Decimal("4321.987654"),
        "approved_risk_amount_ceiling": Decimal("100"),
        "stop_distance_fraction": Decimal("0.02"),
        "effective_loss_fraction": Decimal("0.024"),
        "created_at_ms": 2_000,
        "earliest_execution_ms": 2_250,
        "execution_config_version": "phase7-v1",
        "instrument_metadata_received_at_ms": 1_900,
    }


def test_paper_execution_config_defaults_are_decimal_and_versioned() -> None:
    config = PaperExecutionConfig()

    assert config.config_version == "phase7-v1"
    assert config.latency_ms == 250
    assert config.max_book_age_ms == 1_000
    assert config.max_asset_ctx_age_ms == 5_000
    assert config.funding_reconciliation_grace_ms == 300_000
    assert config.max_ioc_slippage_bps == Decimal("25")
    assert config.taker_fee_rate == Decimal("0.00045")
    assert config.fee_schedule_id == "hyperliquid-native-base-2026-08-23"
    assert config.native_perp_min_notional == Decimal("10")
    assert config.paper_max_gross_leverage == Decimal("3")


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("latency_ms", -1, "latency_ms"),
        ("max_book_age_ms", 0, "max_book_age_ms"),
        ("max_asset_ctx_age_ms", 0, "max_asset_ctx_age_ms"),
        ("funding_reconciliation_grace_ms", -1, "funding_reconciliation_grace_ms"),
        ("max_ioc_slippage_bps", Decimal("NaN"), "max_ioc_slippage_bps"),
        ("taker_fee_rate", Decimal("-0.1"), "taker_fee_rate"),
        ("native_perp_min_notional", Decimal("0"), "native_perp_min_notional"),
        ("paper_max_gross_leverage", Decimal("0"), "paper_max_gross_leverage"),
    ],
)
def test_paper_execution_config_rejects_invalid_values(
    field: str,
    value: object,
    match: str,
) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError, match=match):
        PaperExecutionConfig(**kwargs)


def test_instrument_execution_spec_derives_size_quantum_and_native_support() -> None:
    spec = InstrumentExecutionSpec(
        market=MarketId(dex="", coin="BTC"),
        sz_decimals=5,
        venue_max_leverage=Decimal("40"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=1_000,
        metadata_source="hyperliquid-mainnet-info",
    )

    assert spec.size_quantum == Decimal("0.00001")
    assert spec.execution_supported is True
    assert spec.unsupported_reason is None


def test_instrument_execution_spec_fails_closed_for_named_dex() -> None:
    spec = InstrumentExecutionSpec(
        market=MarketId(dex="xyz", coin="XYZ100"),
        sz_decimals=2,
        venue_max_leverage=Decimal("5"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=1_000,
        metadata_source="hyperliquid-mainnet-info",
    )

    assert spec.execution_supported is False
    assert spec.unsupported_reason == "UNSUPPORTED_NON_NATIVE_PERP_DEX"


def test_order_plan_id_and_cost_buffer_ignore_ambient_decimal_context() -> None:
    kwargs = opening_plan_kwargs()
    baseline_plan = PaperOrderPlan(**kwargs)
    baseline_id = baseline_plan.plan_id
    baseline_cost_buffer = baseline_plan.cost_buffer_fraction

    original = getcontext().copy()
    try:
        getcontext().prec = 8
        getcontext().rounding = ROUND_UP
        hostile_plan = PaperOrderPlan(**kwargs)
        hostile_id = hostile_plan.plan_id
        hostile_cost_buffer = hostile_plan.cost_buffer_fraction
    finally:
        getcontext().prec = original.prec
        getcontext().rounding = original.rounding

    assert baseline_cost_buffer == Decimal("0.004")
    assert hostile_cost_buffer == baseline_cost_buffer
    assert hostile_id == baseline_id


def test_opening_order_plan_requires_nonnegative_phase6_cost_buffer() -> None:
    kwargs = opening_plan_kwargs()
    kwargs["stop_distance_fraction"] = Decimal("0.05")
    kwargs["effective_loss_fraction"] = Decimal("0.02")

    with pytest.raises(ValueError, match="effective_loss_fraction"):
        PaperOrderPlan(**kwargs)


def test_order_plan_rejects_non_ioc_opening_orders() -> None:
    kwargs = opening_plan_kwargs()
    kwargs["order_type"] = OrderType.LIMIT_GTC
    with pytest.raises(ValueError, match="MARKETABLE_IOC"):
        PaperOrderPlan(**kwargs)


def test_fill_id_is_deterministic_and_fee_is_explicit_decimal() -> None:
    fill = PaperFill(
        plan_id="plan-1",
        attempt_id="attempt-1",
        market=MarketId(dex="", coin="BTC"),
        side=OrderSide.SELL,
        price=Decimal("65000.5"),
        quantity=Decimal("0.01"),
        notional=Decimal("650.005"),
        taker_fee=Decimal("0.29250225"),
        source_event_key="segment-1:42",
        timestamp_ms=3_000,
    )
    same = PaperFill(
        plan_id="plan-1",
        attempt_id="attempt-1",
        market=MarketId(dex="", coin="BTC"),
        side=OrderSide.SELL,
        price=Decimal("65000.5"),
        quantity=Decimal("0.01"),
        notional=Decimal("650.005"),
        taker_fee=Decimal("0.29250225"),
        source_event_key="segment-1:42",
        timestamp_ms=3_000,
    )

    assert fill.fill_id == same.fill_id
    assert isinstance(fill.price, Decimal)
    assert isinstance(fill.taker_fee, Decimal)


def test_position_action_reduction_and_exit_actions_require_positive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity"):
        PositionAction(
            action_type=PositionActionType.REDUCE,
            market=MarketId(dex="", coin="SOL"),
            quantity=Decimal("0"),
            new_stop_price=None,
            reason_codes=("risk_reduce",),
            timestamp_ms=4_000,
        )


def test_execution_result_enum_includes_zero_fill_as_first_class_result() -> None:
    assert ExecutionResult.FULL.value == "full"
    assert ExecutionResult.PARTIAL.value == "partial"
    assert ExecutionResult.NO_FILL.value == "no_fill"
    assert ExecutionResult.REJECTED.value == "rejected"


def test_decimal_contract_construction_does_not_mutate_global_context() -> None:
    before = getcontext().copy()
    with localcontext() as ctx:
        ctx.prec = 7
        PaperExecutionConfig()
    after = getcontext()
    assert after.prec == before.prec
    assert after.rounding == before.rounding
