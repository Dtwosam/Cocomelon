from decimal import Decimal

from cocomelon.domain.evaluation import EvaluationPolicy, SplitName, TradeEvaluationSample
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.walkforward import (
    WalkForwardPlan,
    evaluate_walkforward,
    generate_walkforward_windows,
)

MARKET = MarketId("", "SOL")


def policy(*, min_window_trades: int = 2) -> EvaluationPolicy:
    return EvaluationPolicy(
        min_trades_per_walkforward_window=min_window_trades,
        split_embargo_ms=0,
    )


def plan(*, expanding: bool) -> WalkForwardPlan:
    rules = policy()
    return WalkForwardPlan(
        dataset_manifest_id="dataset-1",
        first_window_start_ms=0,
        development_duration_ms=10_000,
        validation_duration_ms=2_000,
        evaluation_duration_ms=3_000,
        step_ms=5_000,
        embargo_ms=0,
        expanding=expanding,
        policy_id=rules.policy_id,
    )


def sample(
    suffix: str,
    *,
    opened_at_ms: int,
    closed_at_ms: int,
    net_r: str = "0.2",
) -> TradeEvaluationSample:
    value = Decimal(net_r)
    return TradeEvaluationSample(
        trade_id=f"trade-{suffix}",
        replay_run_id="run-1",
        strategy_decision_id=f"strategy-{suffix}",
        market=MARKET,
        direction=Direction.LONG,
        decision_timestamp_ms=max(0, opened_at_ms - 100),
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        score=Decimal("70"),
        lead_strategy="trend",
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        gross_realized_pnl=value,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=value,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        net_r=value,
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + value,
        holding_duration_ms=closed_at_ms - opened_at_ms,
        reason_codes=("TEST",),
    )


def bounds(window) -> tuple[int, int, int, int, int, int]:
    return (
        window.train.start_ms,
        window.train.end_ms,
        window.validation.start_ms,
        window.validation.end_ms,
        window.test.start_ms,
        window.test.end_ms,
    )


def test_expanding_walkforward_generation_is_anchored_and_exact() -> None:
    windows = generate_walkforward_windows(plan(expanding=True), dataset_end_ms=25_000)

    assert tuple(bounds(window) for window in windows) == (
        (0, 10_000, 10_000, 12_000, 12_000, 15_000),
        (0, 15_000, 15_000, 17_000, 17_000, 20_000),
        (0, 20_000, 20_000, 22_000, 22_000, 25_000),
    )
    assert all(window.test.name is SplitName.TEST for window in windows)


def test_rolling_walkforward_generation_moves_development_window() -> None:
    windows = generate_walkforward_windows(plan(expanding=False), dataset_end_ms=25_000)

    assert tuple(bounds(window) for window in windows) == (
        (0, 10_000, 10_000, 12_000, 12_000, 15_000),
        (5_000, 15_000, 15_000, 17_000, 17_000, 20_000),
        (10_000, 20_000, 20_000, 22_000, 22_000, 25_000),
    )


def test_future_samples_do_not_change_earlier_window_result() -> None:
    rules = policy(min_window_trades=1)
    windows = generate_walkforward_windows(plan(expanding=True), dataset_end_ms=20_000)
    early = sample("early", opened_at_ms=12_500, closed_at_ms=13_000)
    future = sample("future", opened_at_ms=17_500, closed_at_ms=18_000, net_r="9")

    first = evaluate_walkforward((early,), windows, policy=rules)[0]
    with_future = evaluate_walkforward((future, early), windows, policy=rules)[0]

    assert with_future == first
    assert first.included_trade_ids == (early.trade_id,)
    assert future.trade_id not in first.excluded_trade_ids


def test_window_readiness_depends_only_on_evaluation_partition_trade_count() -> None:
    rules = policy(min_window_trades=2)
    windows = generate_walkforward_windows(plan(expanding=True), dataset_end_ms=20_000)
    first_only = sample("first", opened_at_ms=12_500, closed_at_ms=13_000)
    second_a = sample("second-a", opened_at_ms=17_500, closed_at_ms=18_000)
    second_b = sample("second-b", opened_at_ms=18_100, closed_at_ms=19_000)

    results = evaluate_walkforward(
        (second_b, first_only, second_a),
        windows,
        policy=rules,
    )

    assert results[0].eligible is False
    assert results[0].reason_codes == ("INSUFFICIENT_WALKFORWARD_TRADES",)
    assert results[0].metrics.trade_count == 1
    assert results[1].eligible is True
    assert results[1].reason_codes == ()
    assert results[1].metrics.trade_count == 2


def test_evaluation_boundary_crossing_trade_is_reported_excluded() -> None:
    rules = policy(min_window_trades=1)
    window = generate_walkforward_windows(plan(expanding=True), dataset_end_ms=15_000)[0]
    crossing = sample("crossing", opened_at_ms=14_500, closed_at_ms=15_500)

    result = evaluate_walkforward((crossing,), (window,), policy=rules)[0]

    assert result.included_trade_ids == ()
    assert result.excluded_trade_ids == (crossing.trade_id,)
    assert result.eligible is False
