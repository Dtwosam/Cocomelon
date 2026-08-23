import importlib
from decimal import Decimal

import pytest

from cocomelon.domain.risk import ExecutionCostEstimate, RiskLimits


def _calculate(
    *,
    entry: Decimal = Decimal("100"),
    stop: Decimal = Decimal("99"),
    equity: Decimal = Decimal("10000"),
    costs: ExecutionCostEstimate | None = None,
):
    module = importlib.import_module("cocomelon.risk.sizing")
    return module.calculate_base_sizing(
        entry_price=entry,
        stop_price=stop,
        equity=equity,
        costs=(
            ExecutionCostEstimate(
                entry_slippage_fraction=Decimal("0.0005"),
                stop_slippage_fraction=Decimal("0.0010"),
                round_trip_fee_fraction=Decimal("0.0009"),
            )
            if costs is None
            else costs
        ),
        limits=RiskLimits(),
    )


def test_cost_aware_sizing_uses_exact_decimal_arithmetic() -> None:
    result = _calculate()

    assert result.target_risk_amount == Decimal("25.0000")
    assert result.stop_distance_fraction == Decimal("0.01")
    assert result.effective_loss_fraction == Decimal("0.0124")
    assert result.raw_notional == Decimal("2016.129032258064516129032258")


def test_short_stop_distance_is_symmetric() -> None:
    long = _calculate(entry=Decimal("100"), stop=Decimal("99"))
    short = _calculate(entry=Decimal("100"), stop=Decimal("101"))

    assert short.stop_distance_fraction == long.stop_distance_fraction
    assert short.raw_notional == long.raw_notional


def test_higher_execution_costs_reduce_notional_without_increasing_risk_budget() -> None:
    low_cost = _calculate(
        costs=ExecutionCostEstimate(
            entry_slippage_fraction=Decimal("0"),
            stop_slippage_fraction=Decimal("0"),
            round_trip_fee_fraction=Decimal("0"),
        )
    )
    high_cost = _calculate(
        costs=ExecutionCostEstimate(
            entry_slippage_fraction=Decimal("0.002"),
            stop_slippage_fraction=Decimal("0.003"),
            round_trip_fee_fraction=Decimal("0.001"),
        )
    )

    assert low_cost.target_risk_amount == high_cost.target_risk_amount == Decimal("25.0000")
    assert high_cost.raw_notional < low_cost.raw_notional


def test_strategy_score_is_not_an_input_to_risk_sizing() -> None:
    module = importlib.import_module("cocomelon.risk.sizing")

    assert "score" not in module.calculate_base_sizing.__annotations__


def test_zero_stop_distance_and_zero_costs_fail_closed() -> None:
    zero_costs = ExecutionCostEstimate(
        entry_slippage_fraction=Decimal("0"),
        stop_slippage_fraction=Decimal("0"),
        round_trip_fee_fraction=Decimal("0"),
    )

    with pytest.raises(ValueError, match="effective_loss_fraction"):
        _calculate(entry=Decimal("100"), stop=Decimal("100"), costs=zero_costs)


def test_non_positive_entry_or_equity_fail_closed() -> None:
    with pytest.raises(ValueError, match="entry_price"):
        _calculate(entry=Decimal("0"))

    with pytest.raises(ValueError, match="equity"):
        _calculate(equity=Decimal("0"))
