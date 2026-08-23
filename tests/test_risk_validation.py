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
NOW_MS = 100_000


def _validate(request: RiskRequest) -> tuple[str, ...]:
    module = importlib.import_module("cocomelon.risk.validation")
    return module.validate_request(request)


def _strategy(
    *,
    direction: Direction = Direction.LONG,
    invalidation: Decimal | None = Decimal("99"),
    timestamp_ms: int = NOW_MS - 1_000,
) -> StrategyDecision:
    return StrategyDecision(
        market=MARKET,
        direction=direction,
        score=Decimal("80") if direction is not Direction.NO_TRADE else Decimal("0"),
        timestamp_ms=timestamp_ms,
        feature_snapshot_id="feature-1",
        lead_strategy="trend" if direction is not Direction.NO_TRADE else None,
        invalidation_price=invalidation,
        signal_ids=("signal-1",),
        reason_codes=("test",),
    )


def _request(
    *,
    strategy: StrategyDecision | None = None,
    entry: Decimal = Decimal("100"),
    account_as_of_ms: int = NOW_MS - 100,
    health_as_of_ms: int = NOW_MS - 100,
    liquidity_as_of_ms: int = NOW_MS - 100,
    timestamp_ms: int = NOW_MS,
    health: RiskHealthState | None = None,
) -> RiskRequest:
    return RiskRequest(
        strategy_decision=_strategy() if strategy is None else strategy,
        entry_reference_price=entry,
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
            as_of_ms=account_as_of_ms,
        ),
        open_positions=(),
        health_state=(
            RiskHealthState(
                market_data_fresh=True,
                account_state_fresh=True,
                execution_health_ok=True,
                state_consistent=True,
                as_of_ms=health_as_of_ms,
            )
            if health is None
            else health
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
            as_of_ms=liquidity_as_of_ms,
        ),
        limits=RiskLimits(),
        timestamp_ms=timestamp_ms,
    )


def test_valid_request_has_no_validation_reasons() -> None:
    assert _validate(_request()) == ()


def test_no_trade_strategy_fails_closed_first() -> None:
    decision = _strategy(direction=Direction.NO_TRADE, invalidation=None)

    assert _validate(_request(strategy=decision)) == ("strategy_no_trade",)


def test_long_and_short_require_stop_on_correct_side() -> None:
    long_bad = _strategy(direction=Direction.LONG, invalidation=Decimal("101"))
    short_bad = _strategy(direction=Direction.SHORT, invalidation=Decimal("99"))

    assert _validate(_request(strategy=long_bad)) == ("invalid_stop_side",)
    assert _validate(_request(strategy=short_bad)) == ("invalid_stop_side",)


def test_request_timestamp_cannot_precede_strategy_or_state() -> None:
    future_strategy = _strategy(timestamp_ms=NOW_MS + 1)
    assert _validate(_request(strategy=future_strategy)) == ("risk_state_inconsistent",)

    assert _validate(_request(account_as_of_ms=NOW_MS + 1)) == (
        "risk_state_inconsistent",
    )
    assert _validate(_request(health_as_of_ms=NOW_MS + 1)) == (
        "risk_state_inconsistent",
    )
    assert _validate(_request(liquidity_as_of_ms=NOW_MS + 1)) == (
        "risk_state_inconsistent",
    )


def test_account_and_liquidity_age_use_request_time_only() -> None:
    stale_account = _request(account_as_of_ms=NOW_MS - 5_001)
    stale_liquidity = _request(liquidity_as_of_ms=NOW_MS - 5_001)

    assert _validate(stale_account) == ("stale_account_state",)
    assert _validate(stale_liquidity) == ("stale_market_data",)


def test_health_flags_fail_closed_in_precedence_order() -> None:
    base = RiskHealthState(
        market_data_fresh=True,
        account_state_fresh=True,
        execution_health_ok=True,
        state_consistent=True,
        as_of_ms=NOW_MS - 100,
    )

    assert _validate(_request(health=replace(base, market_data_fresh=False))) == (
        "stale_market_data",
    )
    assert _validate(_request(health=replace(base, account_state_fresh=False))) == (
        "stale_account_state",
    )
    assert _validate(_request(health=replace(base, execution_health_ok=False))) == (
        "execution_health_degraded",
    )
    assert _validate(_request(health=replace(base, state_consistent=False))) == (
        "risk_state_inconsistent",
    )


def test_health_timestamp_itself_can_be_stale() -> None:
    stale_health = RiskHealthState(
        market_data_fresh=True,
        account_state_fresh=True,
        execution_health_ok=True,
        state_consistent=True,
        as_of_ms=NOW_MS - 5_001,
    )

    assert _validate(_request(health=stale_health)) == ("stale_market_data",)
