from __future__ import annotations

from decimal import Decimal
from importlib import import_module
from pathlib import Path

from pytest import raises

from cocomelon.domain.evaluation import TradeEvaluationSample
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    ResearchCheckpointState,
    TimeInterval,
)
from cocomelon.research.registry import ResearchContaminationError, ResearchRegistry

evaluator = import_module("cocomelon.research.evaluator")

DAY_MS = 86_400_000
EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"max_position_r":"1","stops_required":true}'


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="research-r1-candidate",
        family_id="family-research",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest="a" * 64,
        code_revision="1" * 40,
        execution_config_json=EXECUTION_CONFIG,
        risk_config_json=RISK_CONFIG,
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def _sample(
    index: int,
    *,
    day: int,
    market: str,
    direction: Direction,
    net_pnl: str,
    net_r: str,
    replay_run_id: str = "research-replay-1",
) -> TradeEvaluationSample:
    decision_ms = day * DAY_MS + 10_000 + index * 10_000
    opened_ms = decision_ms + 1_000
    closed_ms = opened_ms + 5_000
    pnl = Decimal(net_pnl)
    return TradeEvaluationSample(
        trade_id=f"trade-{index}",
        replay_run_id=replay_run_id,
        strategy_decision_id=f"decision-{index}",
        market=MarketId(dex="", coin=market),
        direction=direction,
        decision_timestamp_ms=decision_ms,
        opened_at_ms=opened_ms,
        closed_at_ms=closed_ms,
        score=Decimal("70"),
        lead_strategy="trend",
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        gross_realized_pnl=pnl + Decimal("0.02"),
        entry_fees=Decimal("0.01"),
        exit_fees=Decimal("0.01"),
        funding_cash_pnl=Decimal("0.005"),
        net_pnl=pnl,
        entry_slippage_amount=Decimal("0.003"),
        exit_slippage_amount=Decimal("0.004"),
        net_r=Decimal(net_r),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + pnl,
        holding_duration_ms=5_000,
        reason_codes=("MAX_HOLD_EXPIRED",),
    )


def test_research_report_exposes_full_touched_economics_and_provenance(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    candidate = _candidate()
    registry.create_candidate(candidate)
    batch = evaluator.ResearchBatch(
        batch_id="batch-1",
        source_id="research-source-1",
        replay_run_id="research-replay-1",
        interval=TimeInterval(DAY_MS, 4 * DAY_MS),
    )
    samples = (
        _sample(1, day=1, market="BTC", direction=Direction.LONG, net_pnl="5", net_r="0.5"),
        _sample(2, day=2, market="BTC", direction=Direction.SHORT, net_pnl="-2", net_r="-0.2"),
        _sample(3, day=3, market="ETH", direction=Direction.LONG, net_pnl="4", net_r="0.4"),
    )

    report = evaluator.evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate.candidate_id,
        batches=(batch,),
        samples=samples,
    )

    assert report.label == "TOUCHED / NON-PROMOTIONAL"
    assert report.candidate_id == candidate.candidate_id
    assert report.family_id == candidate.family_id
    assert report.config_digest == candidate.config_digest
    assert report.code_revision == candidate.code_revision
    assert report.execution_config_json == EXECUTION_CONFIG
    assert report.risk_config_json == RISK_CONFIG
    assert report.closed_trade_count == 3
    assert report.closed_trade_days == 3
    assert report.net_pnl == Decimal("7")
    assert report.mean_net_r == Decimal("0.2333333333333333333333333333")
    assert report.total_fees == Decimal("0.06")
    assert report.funding_cash_pnl == Decimal("0.015")
    assert report.total_slippage_amount == Decimal("0.021")
    assert report.long_count == 2
    assert report.short_count == 1
    assert report.market_trade_counts == (("BTC", 2), ("ETH", 1))
    assert report.exit_reason_counts == (("MAX_HOLD_EXPIRED", 3),)
    assert report.checkpoint_state is ResearchCheckpointState.INSUFFICIENT_TRADES
    assert report.posterior_probability_positive is None
    assert registry.effective_touched_intervals(candidate.candidate_id) == (batch.interval,)

    loaded = registry.load_candidate(candidate.candidate_id)
    assert loaded.first_observation_ms == batch.interval.start_ms
    assert loaded.last_observation_ms == batch.interval.end_ms
    assert loaded.source_provenance_ids == (batch.source_id,)
    assert loaded.local_touched_intervals == (batch.interval,)
    assert loaded.effective_touched_intervals == (batch.interval,)
    assert loaded.performance_report_ids == (report.report_id,)
    registry.close()


def test_v4_overlap_rejects_candidate_before_research_report_is_released(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    candidate = _candidate()
    registry.create_candidate(candidate)
    registry.record_v4_interval(
        run_id="v4-diagnostic-run",
        interval=TimeInterval(DAY_MS, 2 * DAY_MS),
        disposition="diagnostic_failure",
    )
    batch = evaluator.ResearchBatch(
        batch_id="batch-overlap",
        source_id="research-source-overlap",
        replay_run_id="research-replay-1",
        interval=TimeInterval(DAY_MS + 1, 3 * DAY_MS),
    )

    with raises(ResearchContaminationError, match="v4-diagnostic-run"):
        evaluator.evaluate_research_checkpoint(
            registry=registry,
            candidate_id=candidate.candidate_id,
            batches=(batch,),
            samples=(
                _sample(
                    1,
                    day=1,
                    market="BTC",
                    direction=Direction.LONG,
                    net_pnl="999",
                    net_r="99",
                ),
            ),
        )

    assert registry.load_candidate(candidate.candidate_id).state is (
        ResearchCandidateState.REJECTED_CONTAMINATION
    )
    assert registry.effective_touched_intervals(candidate.candidate_id) == ()
    registry.close()


def test_report_rejects_samples_outside_registered_research_batches(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    candidate = _candidate()
    registry.create_candidate(candidate)
    batch = evaluator.ResearchBatch(
        batch_id="batch-1",
        source_id="research-source-1",
        replay_run_id="research-replay-1",
        interval=TimeInterval(DAY_MS, 2 * DAY_MS),
    )

    with raises(ValueError, match="outside research batch"):
        evaluator.evaluate_research_checkpoint(
            registry=registry,
            candidate_id=candidate.candidate_id,
            batches=(batch,),
            samples=(
                _sample(
                    1,
                    day=3,
                    market="BTC",
                    direction=Direction.LONG,
                    net_pnl="1",
                    net_r="0.1",
                ),
            ),
        )
    registry.close()
