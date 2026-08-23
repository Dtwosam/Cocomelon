import importlib
from dataclasses import replace
from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import (
    ExecutionCostEstimate,
    LiquidityRiskState,
    OpenPositionRisk,
    RiskAccountState,
    RiskHealthState,
    RiskLimits,
    RiskRequest,
)
from cocomelon.domain.strategy import Direction, StrategyDecision

MARKET = MarketId("", "BTC")
NOW_MS = 3_000_000


def _evaluate(request: RiskRequest):
    module = importlib.import_module("cocomelon.risk.engine")
    return module.evaluate_risk(request)


def _position(
    coin: str,
    *,
    risk: str,
    bucket: str = "crypto_beta",
) -> OpenPositionRisk:
    return OpenPositionRisk(
        market=MarketId("", coin),
        direction=Direction.LONG,
        planned_risk=Decimal(risk),
        notional=Decimal("1000"),
        correlation_bucket=bucket,
        entry_price=Decimal("100"),
        stop_price=Decimal("99"),
    )


def _request(
    *,
    score: Decimal = Decimal("80"),
    direction: Direction = Direction.LONG,
    stop: Decimal | None = None,
    account: RiskAccountState | None = None,
    open_positions: tuple[OpenPositionRisk, ...] = (),
    health: RiskHealthState | None = None,
    liquidity: LiquidityRiskState | None = None,
) -> RiskRequest:
    resolved_stop = stop
    if stop is None and direction is Direction.LONG:
        resolved_stop = Decimal("99")
    elif stop is None and direction is Direction.SHORT:
        resolved_stop = Decimal("101")
    strategy = StrategyDecision(
        market=MARKET,
        direction=direction,
        score=score if direction is not Direction.NO_TRADE else Decimal("0"),
        timestamp_ms=NOW_MS - 100,
        feature_snapshot_id="feature-1",
        lead_strategy="trend" if direction is not Direction.NO_TRADE else None,
        invalidation_price=resolved_stop,
        signal_ids=("signal-1",),
        reason_codes=("test",),
    )
    return RiskRequest(
        strategy_decision=strategy,
        entry_reference_price=Decimal("100"),
        correlation_bucket="crypto_beta",
        account_state=(
            RiskAccountState(
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
            if account is None
            else account
        ),
        open_positions=open_positions,
        health_state=(
            RiskHealthState(
                market_data_fresh=True,
                account_state_fresh=True,
                execution_health_ok=True,
                state_consistent=True,
                as_of_ms=NOW_MS - 100,
            )
            if health is None
            else health
        ),
        cost_estimate=ExecutionCostEstimate(
            entry_slippage_fraction=Decimal("0.0005"),
            stop_slippage_fraction=Decimal("0.0010"),
            round_trip_fee_fraction=Decimal("0.0009"),
        ),
        liquidity_state=(
            LiquidityRiskState(
                entry_side_visible_notional_25bps=Decimal("100000"),
                exit_side_visible_notional_25bps=Decimal("100000"),
                venue_max_leverage=Decimal("20"),
                liquidation_price=(
                    Decimal("97")
                    if direction is not Direction.SHORT
                    else Decimal("103")
                ),
                venue_min_notional=Decimal("10"),
                as_of_ms=NOW_MS - 100,
            )
            if liquidity is None
            else liquidity
        ),
        limits=RiskLimits(),
        timestamp_ms=NOW_MS,
    )


def test_safe_request_is_approved_with_exact_cost_aware_risk() -> None:
    decision = _evaluate(_request())

    assert decision.approved is True
    assert decision.reason_codes == ("risk_approved",)
    assert decision.target_risk_amount == Decimal("25.0000")
    assert decision.approved_risk_amount == Decimal("25.0000")
    assert decision.approved_notional == Decimal("2016.129032258064516129032258")
    assert decision.stop_distance_fraction == Decimal("0.01")
    assert decision.effective_loss_fraction == Decimal("0.0124")
    assert decision.binding_caps == ()


def test_validation_rejection_has_zero_exposure() -> None:
    decision = _evaluate(_request(direction=Direction.NO_TRADE))

    assert decision.approved is False
    assert decision.reason_codes == ("strategy_no_trade",)
    assert decision.approved_risk_amount == Decimal("0")
    assert decision.approved_notional == Decimal("0")


def test_same_market_and_account_circuit_breakers_reject() -> None:
    same_market = _position("BTC", risk="10")
    assert _evaluate(_request(open_positions=(same_market,))).reason_codes == (
        "existing_market_exposure",
    )

    daily = replace(_request().account_state, daily_realized_pnl=Decimal("-100"))
    assert _evaluate(_request(account=daily)).reason_codes == ("daily_loss_lockout",)

    weekly = replace(
        _request().account_state,
        equity=Decimal("9700"),
        rolling_7d_peak_equity=Decimal("10000"),
    )
    assert _evaluate(_request(account=weekly)).reason_codes == (
        "weekly_drawdown_lockout",
    )

    cooldown = replace(
        _request().account_state,
        consecutive_losses=3,
        last_closed_trade_ms=NOW_MS - 1_000,
    )
    assert _evaluate(_request(account=cooldown)).reason_codes == (
        "consecutive_loss_cooldown",
    )


def test_aggregate_and_bucket_exhaustion_reject() -> None:
    aggregate = (
        _position("ETH", risk="25", bucket="eth"),
        _position("SOL", risk="25", bucket="sol"),
        _position("HYPE", risk="25", bucket="hype"),
    )
    assert _evaluate(_request(open_positions=aggregate)).reason_codes == (
        "aggregate_risk_exhausted",
    )

    bucket = (
        _position("ETH", risk="25"),
        _position("SOL", risk="25"),
    )
    assert _evaluate(_request(open_positions=bucket)).reason_codes == (
        "correlation_bucket_exhausted",
    )


def test_partial_risk_capacity_reduces_approved_exposure() -> None:
    positions = (_position("ETH", risk="40"),)
    decision = _evaluate(_request(open_positions=positions))

    assert decision.approved is True
    assert decision.approved_risk_amount == Decimal("10.000")
    assert decision.approved_notional == Decimal("806.4516129032258064516129032")
    assert decision.binding_caps == ("correlation_bucket",)


def test_gross_margin_liquidity_liquidation_and_venue_min_rejections_propagate() -> None:
    gross = replace(_request().account_state, gross_open_notional=Decimal("30000"))
    assert _evaluate(_request(account=gross)).reason_codes == (
        "gross_leverage_exhausted",
    )

    margin = replace(_request().account_state, available_margin=Decimal("0"))
    assert _evaluate(_request(account=margin)).reason_codes == (
        "margin_capacity_exhausted",
    )

    liquidity = replace(
        _request().liquidity_state,
        exit_side_visible_notional_25bps=Decimal("0"),
    )
    assert _evaluate(_request(liquidity=liquidity)).reason_codes == (
        "liquidity_capacity_exhausted",
    )

    bad_liquidation = replace(
        _request().liquidity_state,
        liquidation_price=Decimal("98.5"),
    )
    assert _evaluate(_request(liquidity=bad_liquidation)).reason_codes == (
        "liquidation_buffer_insufficient",
    )

    below_min = replace(
        _request().liquidity_state,
        entry_side_visible_notional_25bps=Decimal("50"),
        exit_side_visible_notional_25bps=Decimal("50"),
        venue_min_notional=Decimal("10"),
    )
    assert _evaluate(_request(liquidity=below_min)).reason_codes == (
        "below_venue_min_notional",
    )


def test_market_caps_can_reduce_safe_trade_and_record_binding_cap() -> None:
    liquidity = replace(
        _request().liquidity_state,
        exit_side_visible_notional_25bps=Decimal("8000"),
    )
    decision = _evaluate(_request(liquidity=liquidity))

    assert decision.approved is True
    assert decision.approved_notional == Decimal("800.00")
    assert decision.approved_risk_amount == Decimal("9.920000")
    assert decision.binding_caps == ("liquidity",)


def test_strategy_score_alone_never_changes_risk_or_notional() -> None:
    low = _evaluate(_request(score=Decimal("65")))
    high = _evaluate(_request(score=Decimal("100")))

    assert low.approved is high.approved is True
    assert low.approved_risk_amount == high.approved_risk_amount
    assert low.approved_notional == high.approved_notional


def test_repeated_evaluation_is_deterministic() -> None:
    request = _request()

    first = _evaluate(request)
    second = _evaluate(request)

    assert first == second
    assert first.risk_decision_id == second.risk_decision_id
