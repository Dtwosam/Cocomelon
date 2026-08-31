from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.evaluation import TradeEvaluationSample
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research import evaluator
from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"max_position_r":"1","stops_required":true}'


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="sealed-candidate",
        family_id="sealed-family",
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


def _sample(trade_id: str, *, net_pnl: str, net_r: str, offset_ms: int) -> TradeEvaluationSample:
    decision_ms = 1_000 + offset_ms
    opened_ms = decision_ms + 100
    closed_ms = opened_ms + 100
    pnl = Decimal(net_pnl)
    return TradeEvaluationSample(
        trade_id=trade_id,
        replay_run_id="sealed-replay",
        strategy_decision_id=f"decision-{trade_id}",
        market=MarketId(dex="", coin="BTC"),
        direction=Direction.LONG,
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
        funding_cash_pnl=Decimal("0"),
        net_pnl=pnl,
        entry_slippage_amount=Decimal("0.001"),
        exit_slippage_amount=Decimal("0.001"),
        net_r=Decimal(net_r),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + pnl,
        holding_duration_ms=100,
        reason_codes=("THESIS_EXPIRED",),
    )


def test_checkpoint_rejects_first_submission_that_omits_a_sealed_trade(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=10_000,
        source_id="authoritative-v4-inventory",
    )
    candidate = _candidate()
    registry.create_candidate(candidate)

    winner = _sample("winner", net_pnl="5", net_r="0.5", offset_ms=0)
    loser = _sample("loser", net_pnl="-4", net_r="-0.4", offset_ms=500)
    batch = evaluator.ResearchBatch(
        batch_id="sealed-batch",
        source_id="sealed-source",
        replay_run_id="sealed-replay",
        interval=TimeInterval(1_000, 3_000),
    )
    seal = evaluator.build_research_batch_seal(batch=batch, samples=(winner, loser))

    with pytest.raises(ResearchRegistryError, match="sealed trade set"):
        evaluator.evaluate_research_checkpoint(
            registry=registry,
            candidate_id=candidate.candidate_id,
            batches=(batch,),
            batch_seals=(seal,),
            samples=(winner,),
        )

    registry.close()
