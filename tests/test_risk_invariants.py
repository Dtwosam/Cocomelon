import decimal
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
from cocomelon.risk.engine import evaluate_risk

MARKET = MarketId("", "BTC")
NOW_MS = 4_000_000


def _position(
    coin: str,
    *,
    planned_risk: Decimal,
    bucket: str = "crypto_beta",
) -> OpenPositionRisk:
    return OpenPositionRisk(
        market=MarketId("", coin),
        direction=Direction.LONG,
        planned_risk=planned_risk,
        notional=Decimal("1000"),
        correlation_bucket=bucket,
        entry_price=Decimal("100"),
        stop_price=Decimal("99"),
    )


def _request(
    *,
    equity: Decimal = Decimal("10000"),
    stop: Decimal = Decimal("99"),
    score: Decimal = Decimal("80"),
    available_margin: Decimal = Decimal("5000"),
    entry_depth: Decimal = Decimal("100000"),
    exit_depth: Decimal = Decimal("100000"),
    costs: ExecutionCostEstimate | None = None,
    open_positions: tuple[OpenPositionRisk, ...] = (),
) -> RiskRequest:
    strategy = StrategyDecision(
        market=MARKET,
        direction=Direction.LONG,
        score=score,
        timestamp_ms=NOW_MS - 100,
        feature_snapshot_id="feature-1",
        lead_strategy="trend",
        invalidation_price=stop,
        signal_ids=("signal-1",),
        reason_codes=("test",),
    )
    return RiskRequest(
        strategy_decision=strategy,
        entry_reference_price=Decimal("100"),
        correlation_bucket="crypto_beta",
        account_state=RiskAccountState(
            equity=equity,
            day_start_equity=equity,
            daily_realized_pnl=Decimal("0"),
            rolling_7d_peak_equity=equity,
            available_margin=available_margin,
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
        cost_estimate=(
            ExecutionCostEstimate(
                entry_slippage_fraction=Decimal("0.0005"),
                stop_slippage_fraction=Decimal("0.0010"),
                round_trip_fee_fraction=Decimal("0.0009"),
            )
            if costs is None
            else costs
        ),
        liquidity_state=LiquidityRiskState(
            entry_side_visible_notional_25bps=entry_depth,
            exit_side_visible_notional_25bps=exit_depth,
            venue_max_leverage=Decimal("20"),
            liquidation_price=Decimal("95"),
            venue_min_notional=Decimal("10"),
            as_of_ms=NOW_MS - 100,
        ),
        limits=RiskLimits(),
        timestamp_ms=NOW_MS,
    )


def test_approved_risk_never_exceeds_per_trade_aggregate_or_bucket_limits() -> None:
    for equity in (Decimal("5000"), Decimal("10000"), Decimal("25000")):
        for stop in (Decimal("99.5"), Decimal("99"), Decimal("98")):
            existing = (
                _position("ETH", planned_risk=equity * Decimal("0.001")),
                _position(
                    "SOL",
                    planned_risk=equity * Decimal("0.001"),
                    bucket="other_beta",
                ),
            )
            request = _request(
                equity=equity,
                stop=stop,
                available_margin=equity / Decimal("2"),
                open_positions=existing,
            )
            decision = evaluate_risk(request)

            assert decision.approved_risk_amount <= equity * Decimal("0.0025")
            assert (
                sum((item.planned_risk for item in existing), Decimal("0"))
                + decision.approved_risk_amount
                <= equity * Decimal("0.0075")
            )
            same_bucket = sum(
                (
                    item.planned_risk
                    for item in existing
                    if item.correlation_bucket == request.correlation_bucket
                ),
                Decimal("0"),
            )
            assert same_bucket + decision.approved_risk_amount <= (
                equity * Decimal("0.005")
            )


def test_approved_notional_never_exceeds_weak_side_visible_depth_fraction() -> None:
    for entry_depth, exit_depth in (
        (Decimal("100000"), Decimal("100000")),
        (Decimal("50000"), Decimal("12000")),
        (Decimal("9000"), Decimal("60000")),
    ):
        request = _request(entry_depth=entry_depth, exit_depth=exit_depth)
        decision = evaluate_risk(request)
        weak_side_cap = min(entry_depth, exit_depth) * Decimal("0.10")

        assert decision.approved_notional <= weak_side_cap


def test_raising_execution_costs_never_increases_approved_notional() -> None:
    cost_levels = (
        ExecutionCostEstimate(
            entry_slippage_fraction=Decimal("0"),
            stop_slippage_fraction=Decimal("0"),
            round_trip_fee_fraction=Decimal("0"),
        ),
        ExecutionCostEstimate(
            entry_slippage_fraction=Decimal("0.0005"),
            stop_slippage_fraction=Decimal("0.0010"),
            round_trip_fee_fraction=Decimal("0.0009"),
        ),
        ExecutionCostEstimate(
            entry_slippage_fraction=Decimal("0.002"),
            stop_slippage_fraction=Decimal("0.003"),
            round_trip_fee_fraction=Decimal("0.0015"),
        ),
    )
    notionals = tuple(
        evaluate_risk(_request(costs=cost)).approved_notional for cost in cost_levels
    )

    assert notionals[0] >= notionals[1] >= notionals[2]


def test_reducing_available_margin_never_increases_approved_notional() -> None:
    notionals = tuple(
        evaluate_risk(_request(available_margin=value)).approved_notional
        for value in (Decimal("5000"), Decimal("1000"), Decimal("100"))
    )

    assert notionals[0] >= notionals[1] >= notionals[2]


def test_reducing_visible_depth_never_increases_approved_notional() -> None:
    notionals = tuple(
        evaluate_risk(_request(entry_depth=value, exit_depth=value)).approved_notional
        for value in (Decimal("100000"), Decimal("10000"), Decimal("1000"))
    )

    assert notionals[0] >= notionals[1] >= notionals[2]


def test_strategy_score_alone_never_increases_approved_risk_or_notional() -> None:
    low = evaluate_risk(_request(score=Decimal("65")))
    medium = evaluate_risk(_request(score=Decimal("80")))
    high = evaluate_risk(_request(score=Decimal("100")))

    assert low.approved_risk_amount == medium.approved_risk_amount == high.approved_risk_amount
    assert low.approved_notional == medium.approved_notional == high.approved_notional


def test_risk_evaluation_ignores_ambient_decimal_context() -> None:
    request = _request(stop=Decimal("98"))
    baseline = evaluate_risk(request)

    with decimal.localcontext() as context:
        context.prec = 8
        context.rounding = decimal.ROUND_UP
        hostile = evaluate_risk(request)

    assert hostile == baseline
    assert hostile.risk_decision_id == baseline.risk_decision_id


def test_rejected_decisions_remain_zero_exposure_under_matrix_changes() -> None:
    base = _request()
    locked_account = replace(base.account_state, daily_realized_pnl=Decimal("-100"))

    for score in (Decimal("65"), Decimal("80"), Decimal("100")):
        strategy = replace(base.strategy_decision, score=score)
        request = replace(base, strategy_decision=strategy, account_state=locked_account)
        decision = evaluate_risk(request)

        assert decision.approved is False
        assert decision.approved_risk_amount == Decimal("0")
        assert decision.approved_notional == Decimal("0")
