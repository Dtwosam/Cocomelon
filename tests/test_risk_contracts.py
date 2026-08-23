from dataclasses import FrozenInstanceError, fields
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import (
    ExecutionCostEstimate,
    LiquidityRiskState,
    OpenPositionRisk,
    RiskAccountState,
    RiskDecision,
    RiskHealthState,
    RiskLimits,
    RiskRequest,
)
from cocomelon.domain.strategy import Direction, StrategyDecision

MARKET = MarketId("", "BTC")
NOW_MS = 100_000


def _strategy(
    *,
    direction: Direction = Direction.LONG,
    score: Decimal = Decimal("80"),
    invalidation: Decimal | None = Decimal("99"),
) -> StrategyDecision:
    return StrategyDecision(
        market=MARKET,
        direction=direction,
        score=score,
        timestamp_ms=NOW_MS - 1_000,
        feature_snapshot_id="feature-1",
        lead_strategy="trend" if direction is not Direction.NO_TRADE else None,
        invalidation_price=invalidation,
        signal_ids=("signal-1",),
        reason_codes=("decision_threshold_met",),
    )


def _account() -> RiskAccountState:
    return RiskAccountState(
        equity=Decimal("10000"),
        day_start_equity=Decimal("10000"),
        daily_realized_pnl=Decimal("0"),
        rolling_7d_peak_equity=Decimal("10000"),
        available_margin=Decimal("5000"),
        gross_open_notional=Decimal("0"),
        consecutive_losses=0,
        last_closed_trade_ms=None,
        as_of_ms=NOW_MS - 100,
    )


def _health() -> RiskHealthState:
    return RiskHealthState(
        market_data_fresh=True,
        account_state_fresh=True,
        execution_health_ok=True,
        state_consistent=True,
        as_of_ms=NOW_MS - 100,
    )


def _costs() -> ExecutionCostEstimate:
    return ExecutionCostEstimate(
        entry_slippage_fraction=Decimal("0.0005"),
        stop_slippage_fraction=Decimal("0.0010"),
        round_trip_fee_fraction=Decimal("0.0009"),
    )


def _liquidity() -> LiquidityRiskState:
    return LiquidityRiskState(
        entry_side_visible_notional_25bps=Decimal("100000"),
        exit_side_visible_notional_25bps=Decimal("100000"),
        venue_max_leverage=Decimal("20"),
        liquidation_price=Decimal("95"),
        venue_min_notional=Decimal("10"),
        as_of_ms=NOW_MS - 100,
    )


def _request() -> RiskRequest:
    return RiskRequest(
        strategy_decision=_strategy(),
        entry_reference_price=Decimal("100"),
        correlation_bucket="crypto_beta",
        account_state=_account(),
        open_positions=(),
        health_state=_health(),
        cost_estimate=_costs(),
        liquidity_state=_liquidity(),
        limits=RiskLimits(),
        timestamp_ms=NOW_MS,
    )


def test_risk_limits_lock_exact_decimal_defaults() -> None:
    limits = RiskLimits()

    assert limits.risk_per_trade == Decimal("0.0025")
    assert limits.max_open_risk == Decimal("0.0075")
    assert limits.daily_loss_limit == Decimal("0.01")
    assert limits.weekly_drawdown_limit == Decimal("0.03")
    assert limits.consecutive_loss_cooldown == 3
    assert limits.cooldown_ms == 3_600_000
    assert limits.correlation_bucket_risk_limit == Decimal("0.005")
    assert limits.max_gross_leverage == Decimal("3")
    assert limits.max_available_margin_fraction == Decimal("0.50")
    assert limits.max_visible_depth_fraction == Decimal("0.10")
    assert limits.min_liquidation_stop_multiple == Decimal("2")
    assert limits.max_state_age_ms == 5_000


def test_risk_contracts_are_frozen_and_use_decimal_financial_fields() -> None:
    account = _account()
    with pytest.raises(FrozenInstanceError):
        account.equity = Decimal("1")  # type: ignore[misc]

    assert isinstance(account.equity, Decimal)
    assert isinstance(_costs().entry_slippage_fraction, Decimal)
    assert isinstance(_liquidity().venue_max_leverage, Decimal)


def test_account_state_has_deterministic_identity() -> None:
    first = _account()
    second = _account()

    assert first.state_id == second.state_id
    assert len(first.state_id) == 24


def test_account_state_rejects_inconsistent_or_non_finite_values() -> None:
    with pytest.raises(ValueError, match="equity"):
        RiskAccountState(
            equity=Decimal("0"),
            day_start_equity=Decimal("10000"),
            daily_realized_pnl=Decimal("0"),
            rolling_7d_peak_equity=Decimal("10000"),
            available_margin=Decimal("5000"),
            gross_open_notional=Decimal("0"),
            consecutive_losses=0,
            last_closed_trade_ms=None,
            as_of_ms=NOW_MS,
        )

    with pytest.raises(ValueError, match="rolling_7d_peak_equity"):
        RiskAccountState(
            equity=Decimal("10000"),
            day_start_equity=Decimal("10000"),
            daily_realized_pnl=Decimal("0"),
            rolling_7d_peak_equity=Decimal("9999"),
            available_margin=Decimal("5000"),
            gross_open_notional=Decimal("0"),
            consecutive_losses=0,
            last_closed_trade_ms=None,
            as_of_ms=NOW_MS,
        )

    with pytest.raises(ValueError, match="daily_realized_pnl"):
        RiskAccountState(
            equity=Decimal("10000"),
            day_start_equity=Decimal("10000"),
            daily_realized_pnl=Decimal("NaN"),
            rolling_7d_peak_equity=Decimal("10000"),
            available_margin=Decimal("5000"),
            gross_open_notional=Decimal("0"),
            consecutive_losses=0,
            last_closed_trade_ms=None,
            as_of_ms=NOW_MS,
        )


def test_open_position_risk_rejects_no_trade_and_empty_bucket() -> None:
    with pytest.raises(ValueError, match="direction"):
        OpenPositionRisk(
            market=MARKET,
            direction=Direction.NO_TRADE,
            planned_risk=Decimal("10"),
            notional=Decimal("1000"),
            correlation_bucket="crypto_beta",
            entry_price=Decimal("100"),
            stop_price=Decimal("99"),
        )

    with pytest.raises(ValueError, match="correlation_bucket"):
        OpenPositionRisk(
            market=MARKET,
            direction=Direction.LONG,
            planned_risk=Decimal("10"),
            notional=Decimal("1000"),
            correlation_bucket=" ",
            entry_price=Decimal("100"),
            stop_price=Decimal("99"),
        )


def test_cost_and_liquidity_contracts_fail_closed_on_invalid_values() -> None:
    with pytest.raises(ValueError, match="entry_slippage_fraction"):
        ExecutionCostEstimate(
            entry_slippage_fraction=Decimal("-0.1"),
            stop_slippage_fraction=Decimal("0"),
            round_trip_fee_fraction=Decimal("0"),
        )

    with pytest.raises(ValueError, match="venue_max_leverage"):
        LiquidityRiskState(
            entry_side_visible_notional_25bps=Decimal("100"),
            exit_side_visible_notional_25bps=Decimal("100"),
            venue_max_leverage=Decimal("0"),
            liquidation_price=Decimal("95"),
            venue_min_notional=None,
            as_of_ms=NOW_MS,
        )


def test_risk_request_preserves_strategy_identity_and_normalizes_open_positions() -> None:
    open_position = OpenPositionRisk(
        market=MarketId("", "ETH"),
        direction=Direction.SHORT,
        planned_risk=Decimal("12"),
        notional=Decimal("1000"),
        correlation_bucket="crypto_beta",
        entry_price=Decimal("2000"),
        stop_price=Decimal("2024"),
    )
    request = RiskRequest(
        strategy_decision=_strategy(),
        entry_reference_price=Decimal("100"),
        correlation_bucket="crypto_beta",
        account_state=_account(),
        open_positions=(open_position,),
        health_state=_health(),
        cost_estimate=_costs(),
        liquidity_state=_liquidity(),
        limits=RiskLimits(),
        timestamp_ms=NOW_MS,
    )

    assert request.strategy_decision_id == request.strategy_decision.decision_id
    assert request.feature_snapshot_id == request.strategy_decision.feature_snapshot_id
    assert request.market == MARKET
    assert request.direction is Direction.LONG


def test_rejected_risk_decision_can_never_carry_exposure() -> None:
    with pytest.raises(ValueError, match="rejected"):
        RiskDecision(
            strategy_decision_id=_strategy().decision_id,
            market=MARKET,
            direction=Direction.LONG,
            approved=False,
            reason_codes=("daily_loss_lockout",),
            target_risk_amount=Decimal("25"),
            approved_risk_amount=Decimal("1"),
            approved_notional=Decimal("100"),
            entry_reference_price=Decimal("100"),
            stop_price=Decimal("99"),
            stop_distance_fraction=Decimal("0.01"),
            effective_loss_fraction=Decimal("0.0124"),
            correlation_bucket="crypto_beta",
            binding_caps=(),
            timestamp_ms=NOW_MS,
        )


def test_risk_decision_id_is_deterministic_and_public_fields_have_no_order_api() -> None:
    kwargs = dict(
        strategy_decision_id=_strategy().decision_id,
        market=MARKET,
        direction=Direction.LONG,
        approved=True,
        reason_codes=("risk_approved",),
        target_risk_amount=Decimal("25"),
        approved_risk_amount=Decimal("25"),
        approved_notional=Decimal("2000"),
        entry_reference_price=Decimal("100"),
        stop_price=Decimal("99"),
        stop_distance_fraction=Decimal("0.01"),
        effective_loss_fraction=Decimal("0.0125"),
        correlation_bucket="crypto_beta",
        binding_caps=("liquidity",),
        timestamp_ms=NOW_MS,
    )
    first = RiskDecision(**kwargs)
    second = RiskDecision(**kwargs)

    assert first.risk_decision_id == second.risk_decision_id
    assert len(first.risk_decision_id) == 24

    names = {field.name for field in fields(RiskDecision)}
    forbidden = {
        "order_type",
        "order_id",
        "quantity",
        "wallet",
        "private_key",
        "fill",
        "leverage_request",
    }
    assert names.isdisjoint(forbidden)


def test_request_helper_builds_expected_baseline() -> None:
    request = _request()

    assert request.market == MARKET
    assert request.account_state.equity == Decimal("10000")
    assert request.limits.risk_per_trade == Decimal("0.0025")
