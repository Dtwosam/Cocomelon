from decimal import Decimal

from cocomelon.domain.evaluation import EvaluationPolicy, TradeEvaluationSample
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.slices import evaluate_slices

SOL = MarketId("", "SOL")
ETH = MarketId("", "ETH")


def sample(
    suffix: str,
    *,
    market: MarketId,
    score: str,
    lead_strategy: str,
    direction: Direction,
    trend: TrendRegime,
    volatility: VolatilityRegime,
    evidence: EvidenceClass,
    decision_hour: int,
) -> TradeEvaluationSample:
    opened_at_ms = decision_hour * 3_600_000 + 10_000
    closed_at_ms = opened_at_ms + 1_000
    return TradeEvaluationSample(
        trade_id=f"trade-{suffix}",
        replay_run_id="run-1",
        strategy_decision_id=f"strategy-{suffix}",
        market=market,
        direction=direction,
        decision_timestamp_ms=decision_hour * 3_600_000,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        score=Decimal(score),
        lead_strategy=lead_strategy,
        trend_regime=trend,
        volatility_regime=volatility,
        evidence_class=evidence,
        gross_realized_pnl=Decimal("1"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("1"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        net_r=Decimal("0.1"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10001"),
        holding_duration_ms=1_000,
        reason_codes=("TEST",),
    )


def samples() -> tuple[TradeEvaluationSample, ...]:
    return (
        sample(
            "a",
            market=SOL,
            score="72",
            lead_strategy="trend",
            direction=Direction.LONG,
            trend=TrendRegime.UP,
            volatility=VolatilityRegime.NORMAL,
            evidence=EvidenceClass.MICROSTRUCTURE,
            decision_hour=9,
        ),
        sample(
            "b",
            market=SOL,
            score="79.9",
            lead_strategy="trend",
            direction=Direction.LONG,
            trend=TrendRegime.UP,
            volatility=VolatilityRegime.NORMAL,
            evidence=EvidenceClass.MICROSTRUCTURE,
            decision_hour=9,
        ),
        sample(
            "c",
            market=ETH,
            score="95",
            lead_strategy="breakout",
            direction=Direction.SHORT,
            trend=TrendRegime.DOWN,
            volatility=VolatilityRegime.HIGH,
            evidence=EvidenceClass.CANDLE_CONTEXT,
            decision_hour=14,
        ),
    )


def test_slices_cover_all_predeclared_dimensions_deterministically() -> None:
    reports = evaluate_slices(
        tuple(reversed(samples())),
        policy=EvaluationPolicy(min_score_bucket_trades=2),
    )

    kinds = {report.slice_kind for report in reports}
    assert kinds == {
        "market",
        "lead_strategy",
        "direction",
        "trend_regime",
        "volatility_regime",
        "utc_hour",
        "score_bucket",
        "evidence_class",
    }
    assert reports == tuple(sorted(reports, key=lambda item: (item.slice_kind, item.slice_key)))


def test_score_buckets_are_fixed_ten_point_ranges_not_probabilities() -> None:
    reports = evaluate_slices(samples(), policy=EvaluationPolicy(min_score_bucket_trades=2))
    buckets = {
        report.slice_key: report
        for report in reports
        if report.slice_kind == "score_bucket"
    }

    assert set(buckets) == {"[70,80)", "[90,100]"}
    assert buckets["[70,80)"].sample_size == 2
    assert buckets["[70,80)"].research_ready is True
    assert buckets["[90,100]"].sample_size == 1
    assert buckets["[90,100]"].research_ready is False
    assert buckets["[90,100]"].reason_codes == ("INSUFFICIENT_SCORE_BUCKET_TRADES",)
    assert all("probability" not in report.slice_kind for report in reports)


def test_fixed_score_bucket_does_not_move_when_distribution_changes() -> None:
    original = evaluate_slices(samples(), policy=EvaluationPolicy(min_score_bucket_trades=1))
    extra = sample(
        "d",
        market=ETH,
        score="5",
        lead_strategy="breakout",
        direction=Direction.SHORT,
        trend=TrendRegime.DOWN,
        volatility=VolatilityRegime.HIGH,
        evidence=EvidenceClass.CANDLE_CONTEXT,
        decision_hour=3,
    )
    changed = evaluate_slices(
        (*samples(), extra),
        policy=EvaluationPolicy(min_score_bucket_trades=1),
    )

    original_70 = next(
        report
        for report in original
        if report.slice_kind == "score_bucket" and report.slice_key == "[70,80)"
    )
    changed_70 = next(
        report
        for report in changed
        if report.slice_kind == "score_bucket" and report.slice_key == "[70,80)"
    )
    assert original_70.metrics == changed_70.metrics
