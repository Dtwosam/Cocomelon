import random
from decimal import ROUND_UP, Context, Decimal, localcontext

from cocomelon.domain.evaluation import EvaluationPolicy, TradeEvaluationSample
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.uncertainty import (
    _bootstrap_seed,
    _sampled_day_indices,
    mean_net_r_confidence_interval,
)

DAY_MS = 86_400_000
MARKET = MarketId("", "SOL")


def sample(suffix: str, *, day: int, net_r: str) -> TradeEvaluationSample:
    closed_at_ms = day * DAY_MS + 10_000
    opened_at_ms = closed_at_ms - 1_000
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
        holding_duration_ms=1_000,
        reason_codes=("TEST",),
    )


def policy(
    *,
    min_oos_trades: int = 6,
    min_oos_days: int = 3,
) -> EvaluationPolicy:
    return EvaluationPolicy(
        min_oos_trades=min_oos_trades,
        min_oos_days=min_oos_days,
        bootstrap_block_days=2,
        bootstrap_resamples=101,
        bootstrap_confidence=Decimal("0.95"),
    )


def ready_samples() -> tuple[TradeEvaluationSample, ...]:
    return (
        sample("a", day=0, net_r="-0.4"),
        sample("b", day=0, net_r="0.1"),
        sample("c", day=1, net_r="0.2"),
        sample("d", day=1, net_r="0.3"),
        sample("e", day=2, net_r="0.5"),
        sample("f", day=2, net_r="0.8"),
    )


def test_bootstrap_interval_is_deterministic_under_hostile_ambient_state() -> None:
    items = ready_samples()
    rules = policy()
    expected = mean_net_r_confidence_interval(
        items,
        evaluation_manifest_id="evaluation-a",
        policy=rules,
    )

    random.seed(999)
    for _ in range(50):
        random.random()
    with localcontext(Context(prec=5, rounding=ROUND_UP)):
        hostile = mean_net_r_confidence_interval(
            tuple(reversed(items)),
            evaluation_manifest_id="evaluation-a",
            policy=rules,
        )

    assert hostile == expected
    assert expected is not None
    assert expected.metric == "mean_net_r"
    assert expected.confidence == Decimal("0.95")
    assert expected.resamples == 101
    assert expected.block_days == 2
    assert expected.lower <= expected.upper


def test_manifest_identity_changes_bootstrap_seed() -> None:
    assert _bootstrap_seed("evaluation-a") != _bootstrap_seed("evaluation-b")


def test_day_block_sampler_keeps_each_selected_block_contiguous() -> None:
    rng = random.Random(7)

    selected = _sampled_day_indices(day_count=7, block_days=3, rng=rng)

    assert len(selected) == 7
    for start in range(0, len(selected), 3):
        block = selected[start : start + 3]
        assert all(
            value == (block[0] + offset) % 7
            for offset, value in enumerate(block)
        )


def test_insufficient_trade_count_returns_no_interval() -> None:
    assert (
        mean_net_r_confidence_interval(
            ready_samples()[:5],
            evaluation_manifest_id="evaluation-a",
            policy=policy(min_oos_trades=6, min_oos_days=2),
        )
        is None
    )


def test_insufficient_distinct_close_days_returns_no_interval() -> None:
    same_day = tuple(sample(str(index), day=0, net_r="0.1") for index in range(6))

    assert (
        mean_net_r_confidence_interval(
            same_day,
            evaluation_manifest_id="evaluation-a",
            policy=policy(min_oos_trades=6, min_oos_days=3),
        )
        is None
    )
