from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_UP, Context, Decimal, localcontext
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
from cocomelon.research.evaluator import ResearchBatch, evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"max_position_r":"1","stops_required":true}'


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="decimal-context-candidate",
        family_id="decimal-context-family",
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


def _samples() -> tuple[TradeEvaluationSample, ...]:
    values = (
        ("0.123456789123456789", "1.111111111111111111"),
        ("0.234567891234567891", "2.222222222222222222"),
        ("0.345678912345678912", "3.333333333333333333"),
    )
    result: list[TradeEvaluationSample] = []
    for index, (net_r, net_pnl) in enumerate(values, start=1):
        decision_ms = 1_000 + index * 100
        result.append(
            TradeEvaluationSample(
                trade_id=f"decimal-trade-{index}",
                replay_run_id="decimal-replay",
                strategy_decision_id=f"decimal-decision-{index}",
                market=MarketId(dex="", coin="BTC"),
                direction=Direction.LONG,
                decision_timestamp_ms=decision_ms,
                opened_at_ms=decision_ms + 10,
                closed_at_ms=decision_ms + 20,
                score=Decimal("70.123456789123456789"),
                lead_strategy="decimal-context",
                trend_regime=TrendRegime.UP,
                volatility_regime=VolatilityRegime.NORMAL,
                evidence_class=EvidenceClass.MICROSTRUCTURE,
                gross_realized_pnl=Decimal(net_pnl) + Decimal("0.02"),
                entry_fees=Decimal("0.01"),
                exit_fees=Decimal("0.01"),
                funding_cash_pnl=Decimal("0.000123456789123456"),
                net_pnl=Decimal(net_pnl),
                entry_slippage_amount=Decimal("0.000111111111111111"),
                exit_slippage_amount=Decimal("0.000222222222222222"),
                net_r=Decimal(net_r),
                equity_before=Decimal("10000"),
                equity_after=Decimal("10001"),
                holding_duration_ms=10,
                reason_codes=("THESIS_EXPIRED",),
            )
        )
    return tuple(result)


def _evaluate(path: Path, context: Context) -> dict[str, object]:
    registry = ResearchRegistry(path)
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=10_000,
            source_id="authoritative-v4-inventory",
        )
        batch = ResearchBatch(
            batch_id="decimal-batch",
            source_id="decimal-source",
            replay_run_id="decimal-replay",
            interval=TimeInterval(1_000, 2_000),
        )
        with localcontext(context):
            report = evaluate_research_checkpoint(
                registry=registry,
                candidate_id="decimal-context-candidate",
                batches=(batch,),
                samples=_samples(),
            )
        return report.to_dict()
    finally:
        registry.close()


def test_research_report_is_independent_of_ambient_decimal_context(tmp_path: Path) -> None:
    low_precision = Context(prec=6, rounding=ROUND_DOWN)
    high_precision = Context(prec=50, rounding=ROUND_UP)

    low_report = _evaluate(tmp_path / "low.sqlite3", low_precision)
    high_report = _evaluate(tmp_path / "high.sqlite3", high_precision)

    assert low_report == high_report
