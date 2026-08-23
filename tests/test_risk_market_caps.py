import importlib
from dataclasses import replace
from decimal import Decimal

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

MARKET = MarketId("", "BTC")
NOW_MS = 2_000_000


def _caps(
    request: RiskRequest,
    *,
    approved_risk: Decimal = Decimal("25"),
    effective_loss: Decimal = Decimal("0.0125"),
    raw_notional: Decimal = Decimal("2000"),
):
    module = importlib.import_module("cocomelon.risk.market_caps")
    return module.calculate_market_caps(
        request,
        approved_risk_amount=approved_risk,
        effective_loss_fraction=effective_loss,
        raw_notional=raw_notional,
    )


def _request(
    *,
    direction: Direction = Direction.LONG,
    stop: Decimal | None = None,
    account: RiskAccountState | None = None,
    liquidity: LiquidityRiskState | None = None,
) -> RiskRequest:
    resolved_stop = (
        Decimal("99") if direction is Direction.LONG else Decimal("101")
    ) if stop is None else stop
    strategy = StrategyDecision(
        market=MARKET,
        direction=direction,
        score=Decimal("80"),
        timestamp_ms=NOW_MS - 100,
        feature_snapshot_id="feature-1",
        lead_strategy="trend",
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
            stop_slippage_fraction=Decimal("0.001"),
            round_trip_fee_fraction=Decimal("0.0009"),
        ),
        liquidity_state=(
            LiquidityRiskState(
                entry_side_visible_notional_25bps=Decimal("100000"),
                exit_side_visible_notional_25bps=Decimal("100000"),
                venue_max_leverage=Decimal("20"),
                liquidation_price=(
                    Decimal("97")
                    if direction is Direction.LONG
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


def test_safe_request_preserves_risk_notional_when_market_caps_are_looser() -> None:
    result = _caps(_request())

    assert result.gross_capacity == Decimal("30000")
    assert result.margin_capacity == Decimal("7500.00")
    assert result.liquidity_capacity == Decimal("10000.00")
    assert result.risk_notional == Decimal("2.0E+3")
    assert result.final_notional == Decimal("2000")
    assert result.planned_risk == Decimal("25.0000")
    assert result.binding_caps == ()
    assert result.rejection_reason is None


def test_venue_leverage_below_system_ceiling_is_respected() -> None:
    liquidity = replace(_request().liquidity_state, venue_max_leverage=Decimal("2"))
    result = _caps(_request(liquidity=liquidity), raw_notional=Decimal("15000"))

    assert result.gross_capacity == Decimal("20000")
    assert result.margin_capacity == Decimal("5000.00")


def test_gross_leverage_capacity_can_bind() -> None:
    account = replace(_request().account_state, gross_open_notional=Decimal("29200"))
    result = _caps(_request(account=account))

    assert result.final_notional == Decimal("800")
    assert result.planned_risk == Decimal("10.0000")
    assert result.binding_caps == ("gross_leverage",)


def test_non_positive_gross_capacity_rejects() -> None:
    account = replace(_request().account_state, gross_open_notional=Decimal("30000"))
    result = _caps(_request(account=account))

    assert result.final_notional == Decimal("0")
    assert result.rejection_reason == "gross_leverage_exhausted"


def test_margin_capacity_can_bind_and_exhaust() -> None:
    account = replace(_request().account_state, available_margin=Decimal("1000"))
    result = _caps(_request(account=account))
    assert result.final_notional == Decimal("1500.00")
    assert result.binding_caps == ("margin_capacity",)

    exhausted = replace(_request().account_state, available_margin=Decimal("0"))
    rejected = _caps(_request(account=exhausted))
    assert rejected.rejection_reason == "margin_capacity_exhausted"


def test_weaker_visible_depth_side_caps_new_notional() -> None:
    liquidity = replace(
        _request().liquidity_state,
        entry_side_visible_notional_25bps=Decimal("50000"),
        exit_side_visible_notional_25bps=Decimal("8000"),
    )
    result = _caps(_request(liquidity=liquidity))

    assert result.liquidity_capacity == Decimal("800.00")
    assert result.final_notional == Decimal("800.00")
    assert result.binding_caps == ("liquidity",)


def test_zero_weak_side_depth_rejects() -> None:
    liquidity = replace(
        _request().liquidity_state,
        exit_side_visible_notional_25bps=Decimal("0"),
    )
    result = _caps(_request(liquidity=liquidity))

    assert result.rejection_reason == "liquidity_capacity_exhausted"


def test_long_liquidation_must_be_beyond_stop_and_at_least_twice_stop_distance() -> None:
    at_boundary = replace(_request().liquidity_state, liquidation_price=Decimal("98"))
    assert _caps(_request(liquidity=at_boundary)).rejection_reason is None

    too_close = replace(_request().liquidity_state, liquidation_price=Decimal("98.01"))
    assert _caps(_request(liquidity=too_close)).rejection_reason == (
        "liquidation_buffer_insufficient"
    )

    wrong_side = replace(_request().liquidity_state, liquidation_price=Decimal("99.5"))
    assert _caps(_request(liquidity=wrong_side)).rejection_reason == (
        "liquidation_buffer_insufficient"
    )


def test_short_liquidation_mirrors_long_rule() -> None:
    request = _request(direction=Direction.SHORT)
    at_boundary = replace(request.liquidity_state, liquidation_price=Decimal("102"))
    assert _caps(_request(direction=Direction.SHORT, liquidity=at_boundary)).rejection_reason is None

    too_close = replace(request.liquidity_state, liquidation_price=Decimal("101.99"))
    assert _caps(_request(direction=Direction.SHORT, liquidity=too_close)).rejection_reason == (
        "liquidation_buffer_insufficient"
    )


def test_missing_liquidation_estimate_fails_closed() -> None:
    liquidity = replace(_request().liquidity_state, liquidation_price=None)

    assert _caps(_request(liquidity=liquidity)).rejection_reason == (
        "liquidation_buffer_insufficient"
    )


def test_venue_minimum_rejects_instead_of_forcing_notional_higher() -> None:
    liquidity = replace(
        _request().liquidity_state,
        entry_side_visible_notional_25bps=Decimal("50"),
        exit_side_visible_notional_25bps=Decimal("50"),
        venue_min_notional=Decimal("10"),
    )
    result = _caps(_request(liquidity=liquidity))

    assert result.final_notional == Decimal("0")
    assert result.rejection_reason == "below_venue_min_notional"
