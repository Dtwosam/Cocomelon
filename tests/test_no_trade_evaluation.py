from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import DecisionEvaluationFact, EvaluationPolicy
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.no_trade import evaluate_no_trade_outcomes

SOL = MarketId("", "SOL")
HOUR_MS = 3_600_000


def decision(*, timestamp_ms: int = 10_000, suffix: str = "a") -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=f"strategy-{suffix}",
        feature_snapshot_id=f"feature-{suffix}",
        replay_run_id="run-1",
        market=SOL,
        direction=Direction.NO_TRADE,
        timestamp_ms=timestamp_ms,
        score=Decimal("40"),
        lead_strategy=None,
        signal_ids=(),
        reason_codes=("NO_SETUP",),
        trend_regime=TrendRegime.MIXED,
        volatility_regime=VolatilityRegime.NORMAL,
    )


def mark(
    *,
    available_at_ms: int,
    price: str,
    exchange_time_ms: int | None = None,
    event_key: str | None = None,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=available_at_ms,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="SOL",
        exchange_time_ms=exchange_time_ms,
        event_key=event_key or f"mark:{available_at_ms}:{price}",
        event_kind="active_asset_ctx",
        payload_json=f'{{"mark_px":"{price}"}}',
    )


def gap(*, started_ms: int, ended_ms: int | None) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=started_ms,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key=f"gap:activeAssetCtx:SOL:{started_ms}:{ended_ms}",
        event_kind=None,
        payload_json=(
            '{"ended_ms":'
            + ("null" if ended_ms is None else str(ended_ms))
            + f',"reason":"disconnect","started_ms":{started_ms},'
            '"stream_id":"activeAssetCtx:SOL"}'
        ),
    )


def one_hour_policy() -> EvaluationPolicy:
    return EvaluationPolicy(
        min_oos_trades=1,
        min_oos_days=1,
        no_trade_horizons_ms=(HOUR_MS,),
    )


def test_start_mark_uses_receive_time_not_earlier_exchange_timestamp() -> None:
    item = decision(timestamp_ms=10_000)
    records = (
        mark(available_at_ms=9_000, price="100", exchange_time_ms=8_000),
        mark(available_at_ms=10_001, price="90", exchange_time_ms=7_000),
        mark(available_at_ms=10_500, price="110", exchange_time_ms=10_400),
    )

    outcomes = evaluate_no_trade_outcomes(
        (item,),
        records,
        policy=one_hour_policy(),
        sample_numerator=1,
        sample_denominator=1,
    )

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.start_mark == Decimal("100")
    assert outcome.end_mark == Decimal("110")
    assert outcome.end_return_fraction == Decimal("0.1")
    assert outcome.max_up_fraction == Decimal("0.1")
    assert outcome.max_down_fraction == Decimal("-0.1")
    assert outcome.complete is True
    assert outcome.reason_codes == ()


def test_known_mark_stream_gap_intersecting_horizon_marks_outcome_incomplete() -> None:
    item = decision(timestamp_ms=10_000)
    records = (
        mark(available_at_ms=9_000, price="100"),
        mark(available_at_ms=11_000, price="101"),
        gap(started_ms=12_000, ended_ms=13_000),
        mark(available_at_ms=14_000, price="102"),
    )

    outcome = evaluate_no_trade_outcomes(
        (item,),
        records,
        policy=one_hour_policy(),
        sample_numerator=1,
        sample_denominator=1,
    )[0]

    assert outcome.complete is False
    assert outcome.end_mark == Decimal("102")
    assert outcome.reason_codes == ("DATA_GAP_INTERSECTS_HORIZON",)


def test_sampling_and_direction_filter_are_deterministic() -> None:
    no_trade = decision(suffix="no-trade")
    directional = DecisionEvaluationFact(
        strategy_decision_id="strategy-long",
        feature_snapshot_id="feature-long",
        replay_run_id="run-1",
        market=SOL,
        direction=Direction.LONG,
        timestamp_ms=10_000,
        score=Decimal("70"),
        lead_strategy="trend",
        signal_ids=("signal-long",),
        reason_codes=("TREND_UP",),
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
    )
    records = (
        mark(available_at_ms=9_000, price="100"),
        mark(available_at_ms=11_000, price="101"),
    )

    none = evaluate_no_trade_outcomes(
        (directional, no_trade),
        records,
        policy=one_hour_policy(),
        sample_numerator=0,
        sample_denominator=1,
    )
    all_sampled = evaluate_no_trade_outcomes(
        (directional, no_trade),
        records,
        policy=one_hour_policy(),
        sample_numerator=1,
        sample_denominator=1,
    )

    assert none == ()
    assert tuple(item.decision_fact_id for item in all_sampled) == (no_trade.fact_id,)


def test_missing_marks_are_unavailable_not_fabricated() -> None:
    item = decision(timestamp_ms=10_000)

    outcome = evaluate_no_trade_outcomes(
        (item,),
        (),
        policy=one_hour_policy(),
        sample_numerator=1,
        sample_denominator=1,
    )[0]

    assert outcome.start_mark is None
    assert outcome.end_mark is None
    assert outcome.end_return_fraction is None
    assert outcome.max_up_fraction is None
    assert outcome.max_down_fraction is None
    assert outcome.complete is False
    assert outcome.reason_codes == ("MISSING_START_MARK", "MISSING_FUTURE_MARK")


def test_no_trade_module_has_no_fill_or_book_simulator_dependency() -> None:
    source = Path("src/cocomelon/evaluation/no_trade.py").read_text(encoding="utf-8").lower()

    assert "execution.simulator" not in source
    assert "paperfillsimulator" not in source
    assert "l2book" not in source
    assert "synthetic_book" not in source
    assert "hypothetical_pnl" not in source
