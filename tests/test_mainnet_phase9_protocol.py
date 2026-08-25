from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from cocomelon.domain.evaluation import (
    EvaluationDatasetManifest,
    ReplayEvaluationSource,
    TradeEvaluationSample,
)
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.mainnet_protocol import (
    DAY_MS,
    V2_TEST_DAYS,
    V2_TRAIN_DAYS,
    V2_VALIDATION_DAYS,
    build_v2_protocol,
    evaluate_v2_readiness,
    select_v2_snapshot_run_ids,
)

MARKET = MarketId("", "BTC")


def _sample(index: int, *, day: int, net_r: str = "0.10") -> TradeEvaluationSample:
    opened = day * DAY_MS + 12 * 60 * 60 * 1000 + index
    closed = opened + 60_000
    value = Decimal(net_r)
    return TradeEvaluationSample(
        trade_id=f"trade-{index}",
        replay_run_id="run-v2",
        strategy_decision_id=f"decision-{index}",
        market=MARKET,
        direction=Direction.LONG,
        decision_timestamp_ms=opened - 1_000,
        opened_at_ms=opened,
        closed_at_ms=closed,
        score=Decimal("70"),
        lead_strategy="baseline",
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
        holding_duration_ms=closed - opened,
        reason_codes=("TEST",),
    )


def _samples(count: int = 120) -> tuple[TradeEvaluationSample, ...]:
    # Test begins after one train day + one validation day. Four trades on each
    # of 30 UTC close days satisfy the Phase 9 count/coverage minimums and give
    # each predeclared 7-day walk-forward window enough observations.
    return tuple(_sample(index, day=2 + index // 4) for index in range(count))


def _source(run_id: str, start_day: Decimal, end_day: Decimal) -> ReplayEvaluationSource:
    return ReplayEvaluationSource(
        run_id=run_id,
        manifest_id=f"manifest-{run_id}",
        result_digest=(run_id.encode().hex() + "0" * 64)[:64],
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=int(start_day * DAY_MS),
        end_ms=int(end_day * DAY_MS),
        data_complete=True,
    )


def _dataset(
    samples: tuple[TradeEvaluationSample, ...],
    *,
    end_day: int = 47,
) -> EvaluationDatasetManifest:
    return EvaluationDatasetManifest(
        sources=(
            ReplayEvaluationSource(
                run_id="run-v2",
                manifest_id="manifest-v2",
                result_digest="a" * 64,
                evidence_class=EvidenceClass.MICROSTRUCTURE,
                start_ms=0,
                end_ms=end_day * DAY_MS,
                data_complete=True,
            ),
        ),
        trade_ids=tuple(item.trade_id for item in samples),
        decision_fact_ids=tuple(f"fact-{index}" for index in range(len(samples))),
        equity_fact_ids=(),
        start_ms=0,
        end_ms=end_day * DAY_MS,
        code_revision="7cf19ab81fa609fed4171ea8ed1f06d85f91e793",
        data_complete=True,
        gap_refs=(),
        mixed_evidence_diagnostic=False,
    )


def test_v2_protocol_is_predeclared_and_leaves_full_untouched_test() -> None:
    samples = _samples()
    dataset = _dataset(samples)

    protocol = build_v2_protocol(dataset)

    assert V2_TRAIN_DAYS == 1
    assert V2_VALIDATION_DAYS == 1
    assert V2_TEST_DAYS == 45
    assert protocol.split.train.start_ms == dataset.start_ms
    assert protocol.split.train.end_ms == DAY_MS
    assert protocol.split.validation.start_ms == DAY_MS
    assert protocol.split.validation.end_ms == 2 * DAY_MS
    assert protocol.split.test.start_ms == 2 * DAY_MS
    assert protocol.split.test.end_ms == 47 * DAY_MS
    assert protocol.walkforward.first_window_start_ms == dataset.start_ms
    assert protocol.walkforward.evaluation_duration_ms == 7 * DAY_MS
    assert protocol.walkforward.step_ms == 7 * DAY_MS
    assert protocol.walkforward.expanding is True


def test_v2_snapshot_source_set_stops_growing_after_calendar_cutoff() -> None:
    initial = (
        _source("run-a", Decimal("0"), Decimal("0.04")),
        _source("run-b", Decimal("46.75"), Decimal("46.79")),
        _source("run-c", Decimal("47.25"), Decimal("47.29")),
    )
    later = initial + (
        _source("run-d", Decimal("48"), Decimal("48.04")),
        _source("run-e", Decimal("60"), Decimal("60.04")),
    )

    assert select_v2_snapshot_run_ids(initial) == ("run-a", "run-b", "run-c")
    assert select_v2_snapshot_run_ids(later) == ("run-a", "run-b", "run-c")


def test_v2_snapshot_source_set_needs_no_bridge_when_cutoff_is_covered() -> None:
    sources = (
        _source("run-a", Decimal("0"), Decimal("0.04")),
        _source("run-b", Decimal("46.98"), Decimal("47.02")),
        _source("run-c", Decimal("47.25"), Decimal("47.29")),
    )

    assert select_v2_snapshot_run_ids(sources) == ("run-a", "run-b")


def test_v2_readiness_requires_window_trades_days_and_walkforward_counts() -> None:
    samples = _samples()
    dataset = _dataset(samples)

    readiness = evaluate_v2_readiness(dataset, samples)

    assert readiness.ready is True
    assert readiness.test_window_complete is True
    assert readiness.test_trade_count == 120
    assert readiness.test_covered_days == 30
    assert readiness.eligible_walkforward_windows >= 3
    assert readiness.reason_codes == ()

    short_window = evaluate_v2_readiness(_dataset(samples, end_day=46), samples)
    assert short_window.ready is False
    assert "TEST_WINDOW_INCOMPLETE" in short_window.reason_codes

    too_few = _samples(99)
    insufficient = evaluate_v2_readiness(_dataset(too_few), too_few)
    assert insufficient.ready is False
    assert "OOS_TRADES_SHORTFALL" in insufficient.reason_codes


def test_v2_readiness_is_independent_of_pnl_and_net_r() -> None:
    samples = _samples()
    dataset = _dataset(samples)
    losing = tuple(
        replace(
            item,
            gross_realized_pnl=Decimal("-0.50"),
            net_pnl=Decimal("-0.50"),
            net_r=Decimal("-0.50"),
            equity_after=Decimal("9999.50"),
        )
        for item in samples
    )

    first = evaluate_v2_readiness(dataset, samples)
    second = evaluate_v2_readiness(dataset, losing)

    assert second == first
