from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import TradeEvaluationSample
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.evaluator import (
    ResearchBatch,
    build_research_batch_seal,
    evaluate_research_checkpoint,
)
from cocomelon.research.registry import ResearchRegistry

DAY_MS = 86_400_000


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="risk-report-candidate",
        family_id="risk-report-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest="a" * 64,
        code_revision="1" * 40,
        execution_config_json='{"mode":"paper"}',
        risk_config_json='{"risk_per_trade":"0.0025"}',
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
    net_pnl: str,
    net_r: str,
    equity_before: str,
    equity_after: str,
) -> TradeEvaluationSample:
    decision_ms = day * DAY_MS + 1_000 + index * 100
    return TradeEvaluationSample(
        trade_id=f"risk-report-trade-{index}",
        replay_run_id="risk-report-replay",
        strategy_decision_id=f"risk-report-decision-{index}",
        market=MarketId(dex="", coin="BTC"),
        direction=Direction.LONG,
        decision_timestamp_ms=decision_ms,
        opened_at_ms=decision_ms + 10,
        closed_at_ms=decision_ms + 20,
        score=Decimal("70"),
        lead_strategy="risk-report",
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        gross_realized_pnl=Decimal(net_pnl),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal(net_pnl),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        net_r=Decimal(net_r),
        equity_before=Decimal(equity_before),
        equity_after=Decimal(equity_after),
        holding_duration_ms=10,
        reason_codes=("THESIS_EXPIRED",),
    )


def test_checkpoint_persists_realized_drawdown_and_planned_risk_utilization(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=4 * DAY_MS,
            source_id="authoritative-v4-inventory",
        )
        batch = ResearchBatch(
            batch_id="risk-report-batch",
            source_id="risk-report-source",
            replay_run_id="risk-report-replay",
            interval=TimeInterval(1_000, 4 * DAY_MS),
        )
        samples = (
            _sample(
                1,
                day=0,
                net_pnl="100",
                net_r="0.4",
                equity_before="1000",
                equity_after="1100",
            ),
            _sample(
                2,
                day=1,
                net_pnl="-50",
                net_r="-0.5",
                equity_before="1100",
                equity_after="1050",
            ),
            _sample(
                3,
                day=2,
                net_pnl="-200",
                net_r="-1.2",
                equity_before="1050",
                equity_after="850",
            ),
        )
        report = evaluate_research_checkpoint(
            registry=registry,
            candidate_id="risk-report-candidate",
            batches=(batch,),
            batch_seals=(build_research_batch_seal(batch=batch, samples=samples),),
            samples=samples,
        )

        assert report.realized_closed_trade_max_drawdown_fraction == Decimal("250") / Decimal(
            "1100"
        )
        assert report.max_realized_planned_risk_utilization == Decimal("1.2")
        persisted = registry._checkpoint_report_payload(
            "risk-report-candidate",
            report.report_id,
        )
        assert persisted["realized_closed_trade_max_drawdown_fraction"] == str(
            Decimal("250") / Decimal("1100")
        )
        assert persisted["max_realized_planned_risk_utilization"] == "1.2"
    finally:
        registry.close()
