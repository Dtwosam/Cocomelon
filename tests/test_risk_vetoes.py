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
NOW_MS = 10_000_000


def _veto(request: RiskRequest) -> str | None:
    module = importlib.import_module("cocomelon.risk.vetoes")
    return module.hard_veto_reason(request)


def _strategy() -> StrategyDecision:
    return StrategyDecision(
        market=MARKET,
        direction=Direction.LONG,
        score=Decimal("80"),
        timestamp_ms=NOW_MS - 1_000,
        feature_snapshot_id="feature-1",
        lead_strategy="trend",
        invalidation_price=Decimal("99"),
        signal_ids=("signal-1",),
        reason_codes=("test",),
    )


def _account(
    *,
    equity: Decimal = Decimal("10000"),
    day_start_equity: Decimal = Decimal("10000"),
    daily_realized_pnl: Decimal = Decimal("0"),
    rolling_7d_peak_equity: Decimal = Decimal("10000"),
    consecutive_losses: int = 0,
    last_closed_trade_ms: int | None = None,
) -> RiskAccountState:
    return RiskAccountState(
        equity=equity,
        day_start_equity=day_start_equity,
        daily_realized_pnl=daily_realized_pnl,
        rolling_7d_peak_equity=rolling_7d_peak_equity,
        available_margin=Decimal("5000"),
        gross_open_notional=Decimal("0"),
        consecutive_losses=consecutive_losses,
        last_closed_trade_ms=last_closed_trade_ms,
        as_of_ms=NOW_MS - 100,
    )


def _request(
    *,
    account: RiskAccountState | None = None,
    open_positions: tuple[OpenPositionRisk, ...] = (),
) -> RiskRequest:
    return RiskRequest(
        strategy_decision=_strategy(),
        entry_reference_price=Decimal("100"),
        correlation_bucket="crypto_beta",
        account_state=_account() if account is None else account,
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


def test_no_account_veto_for_clean_request() -> None:
    assert _veto(_request()) is None


def test_existing_same_market_exposure_is_hard_veto() -> None:
    position = OpenPositionRisk(
        market=MARKET,
        direction=Direction.SHORT,
        planned_risk=Decimal("10"),
        notional=Decimal("1000"),
        correlation_bucket="crypto_beta",
        entry_price=Decimal("101"),
        stop_price=Decimal("102"),
    )

    assert _veto(_request(open_positions=(position,))) == "existing_market_exposure"


def test_other_market_exposure_does_not_trigger_same_market_veto() -> None:
    position = OpenPositionRisk(
        market=MarketId("", "ETH"),
        direction=Direction.LONG,
        planned_risk=Decimal("10"),
        notional=Decimal("1000"),
        correlation_bucket="crypto_beta",
        entry_price=Decimal("2000"),
        stop_price=Decimal("1980"),
    )

    assert _veto(_request(open_positions=(position,))) is None


def test_daily_loss_lockout_triggers_at_exact_one_percent_boundary() -> None:
    at_limit = _account(daily_realized_pnl=Decimal("-100"))
    just_inside = _account(daily_realized_pnl=Decimal("-99.99"))

    assert _veto(_request(account=at_limit)) == "daily_loss_lockout"
    assert _veto(_request(account=just_inside)) is None


def test_weekly_drawdown_lockout_triggers_at_exact_three_percent_boundary() -> None:
    at_limit = _account(
        equity=Decimal("9700"),
        rolling_7d_peak_equity=Decimal("10000"),
    )
    just_inside = _account(
        equity=Decimal("9700.01"),
        rolling_7d_peak_equity=Decimal("10000"),
    )

    assert _veto(_request(account=at_limit)) == "weekly_drawdown_lockout"
    assert _veto(_request(account=just_inside)) is None


def test_three_loss_cooldown_blocks_until_exact_expiry() -> None:
    active = _account(
        consecutive_losses=3,
        last_closed_trade_ms=NOW_MS - 3_599_999,
    )
    expired = _account(
        consecutive_losses=3,
        last_closed_trade_ms=NOW_MS - 3_600_000,
    )

    assert _veto(_request(account=active)) == "consecutive_loss_cooldown"
    assert _veto(_request(account=expired)) is None


def test_active_loss_cooldown_without_close_timestamp_fails_closed() -> None:
    account = _account(consecutive_losses=3, last_closed_trade_ms=None)

    assert _veto(_request(account=account)) == "risk_state_inconsistent"


def test_veto_precedence_is_same_market_then_daily_then_weekly_then_cooldown() -> None:
    position = OpenPositionRisk(
        market=MARKET,
        direction=Direction.LONG,
        planned_risk=Decimal("10"),
        notional=Decimal("1000"),
        correlation_bucket="crypto_beta",
        entry_price=Decimal("100"),
        stop_price=Decimal("99"),
    )
    account = _account(
        equity=Decimal("9600"),
        rolling_7d_peak_equity=Decimal("10000"),
        daily_realized_pnl=Decimal("-100"),
        consecutive_losses=3,
        last_closed_trade_ms=NOW_MS - 1_000,
    )

    assert _veto(_request(account=account, open_positions=(position,))) == (
        "existing_market_exposure"
    )
