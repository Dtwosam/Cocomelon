import importlib
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
NOW_MS = 1_000_000


def _capacity(request: RiskRequest, target: Decimal):
    module = importlib.import_module("cocomelon.risk.capacity")
    return module.calculate_risk_capacity(request, target_risk_amount=target)


def _position(
    coin: str,
    *,
    planned_risk: str,
    bucket: str = "crypto_beta",
    direction: Direction = Direction.LONG,
) -> OpenPositionRisk:
    return OpenPositionRisk(
        market=MarketId("", coin),
        direction=direction,
        planned_risk=Decimal(planned_risk),
        notional=Decimal("1000"),
        correlation_bucket=bucket,
        entry_price=Decimal("100"),
        stop_price=Decimal("99") if direction is Direction.LONG else Decimal("101"),
    )


def _request(open_positions: tuple[OpenPositionRisk, ...] = ()) -> RiskRequest:
    strategy = StrategyDecision(
        market=MARKET,
        direction=Direction.LONG,
        score=Decimal("80"),
        timestamp_ms=NOW_MS - 100,
        feature_snapshot_id="feature-1",
        lead_strategy="trend",
        invalidation_price=Decimal("99"),
        signal_ids=("signal-1",),
        reason_codes=("test",),
    )
    return RiskRequest(
        strategy_decision=strategy,
        entry_reference_price=Decimal("100"),
        correlation_bucket="crypto_beta",
        account_state=RiskAccountState(
            equity=Decimal("10000"),
            day_start_equity=Decimal("10000"),
            daily_realized_pnl=Decimal("0"),
            rolling_7d_peak_equity=Decimal("10000"),
            available_margin=Decimal("5000"),
            gross_open_notional=Decimal("0"),
            consecutive_losses=0,
            last_closed_trade_ms=None,
            as_of_ms=NOW_MS - 100,
        ),
        open_positions=open_positions,
        health_state=RiskHealthState(
            market_data_fresh=True,
            account_state_fresh=True,
            execution_health_ok=True,
            state_consistent=True,
            as_of_ms=NOW_MS - 100,
        ),
        cost_estimate=ExecutionCostEstimate(
            entry_slippage_fraction=Decimal("0.0005"),
            stop_slippage_fraction=Decimal("0.001"),
            round_trip_fee_fraction=Decimal("0.0009"),
        ),
        liquidity_state=LiquidityRiskState(
            entry_side_visible_notional_25bps=Decimal("100000"),
            exit_side_visible_notional_25bps=Decimal("100000"),
            venue_max_leverage=Decimal("20"),
            liquidation_price=Decimal("95"),
            venue_min_notional=Decimal("10"),
            as_of_ms=NOW_MS - 100,
        ),
        limits=RiskLimits(),
        timestamp_ms=NOW_MS,
    )


def test_empty_portfolio_has_full_aggregate_and_bucket_capacity() -> None:
    result = _capacity(_request(), Decimal("25"))

    assert result.remaining_aggregate_risk == Decimal("75.0000")
    assert result.remaining_bucket_risk == Decimal("50.000")
    assert result.approved_risk_amount == Decimal("25")
    assert result.binding_caps == ()
    assert result.rejection_reason is None


def test_existing_half_percent_open_risk_leaves_quarter_percent_aggregate_capacity() -> None:
    positions = (
        _position("ETH", planned_risk="25", bucket="eth_beta"),
        _position("SOL", planned_risk="25", bucket="sol_beta"),
    )
    result = _capacity(_request(positions), Decimal("30"))

    assert result.remaining_aggregate_risk == Decimal("25.0000")
    assert result.approved_risk_amount == Decimal("25.0000")
    assert result.binding_caps == ("aggregate_risk",)


def test_aggregate_capacity_is_exhausted_at_exact_three_quarter_percent() -> None:
    positions = (
        _position("ETH", planned_risk="25", bucket="eth_beta"),
        _position("SOL", planned_risk="25", bucket="sol_beta"),
        _position("HYPE", planned_risk="25", bucket="hype_beta"),
    )
    result = _capacity(_request(positions), Decimal("25"))

    assert result.approved_risk_amount == Decimal("0")
    assert result.rejection_reason == "aggregate_risk_exhausted"


def test_existing_quarter_percent_same_bucket_leaves_quarter_percent_bucket_capacity() -> None:
    result = _capacity(
        _request((_position("ETH", planned_risk="25"),)),
        Decimal("30"),
    )

    assert result.remaining_bucket_risk == Decimal("25.000")
    assert result.approved_risk_amount == Decimal("25.000")
    assert result.binding_caps == ("correlation_bucket",)


def test_correlation_bucket_is_exhausted_at_exact_half_percent() -> None:
    positions = (
        _position("ETH", planned_risk="25"),
        _position("SOL", planned_risk="25"),
    )
    result = _capacity(_request(positions), Decimal("25"))

    assert result.approved_risk_amount == Decimal("0")
    assert result.rejection_reason == "correlation_bucket_exhausted"


def test_opposite_directions_do_not_net_planned_risk() -> None:
    positions = (
        _position("ETH", planned_risk="20", direction=Direction.LONG),
        _position("SOL", planned_risk="20", direction=Direction.SHORT),
    )
    result = _capacity(_request(positions), Decimal("25"))

    assert result.remaining_bucket_risk == Decimal("10.000")
    assert result.approved_risk_amount == Decimal("10.000")
    assert result.binding_caps == ("correlation_bucket",)


def test_other_bucket_consumes_aggregate_but_not_target_bucket_capacity() -> None:
    positions = (
        _position("ETH", planned_risk="40", bucket="other_bucket"),
    )
    result = _capacity(_request(positions), Decimal("25"))

    assert result.remaining_aggregate_risk == Decimal("35.0000")
    assert result.remaining_bucket_risk == Decimal("50.000")
    assert result.approved_risk_amount == Decimal("25")
    assert result.binding_caps == ()


def test_approved_risk_uses_stricter_of_aggregate_and_bucket_capacity() -> None:
    positions = (
        _position("ETH", planned_risk="45"),
        _position("SOL", planned_risk="20", bucket="other_bucket"),
    )
    result = _capacity(_request(positions), Decimal("25"))

    assert result.remaining_aggregate_risk == Decimal("10.0000")
    assert result.remaining_bucket_risk == Decimal("5.000")
    assert result.approved_risk_amount == Decimal("5.000")
    assert result.binding_caps == ("correlation_bucket",)
