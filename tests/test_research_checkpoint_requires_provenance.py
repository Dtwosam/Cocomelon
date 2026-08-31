from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pytest import raises

from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.evaluator import ResearchCheckpointReport
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.sequential import evaluate_checkpoint

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"risk_per_trade":"0.0025","stops_required":true}'


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="provenance-required-r1",
        family_id="provenance-required-family",
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


def test_checkpoint_state_requires_at_least_one_attested_batch(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    candidate = _candidate()
    registry.create_candidate(candidate)
    checkpoint = evaluate_checkpoint(net_r_values=(), closed_trade_days=0)
    report = ResearchCheckpointReport(
        label="TOUCHED / NON-PROMOTIONAL",
        candidate_id=candidate.candidate_id,
        family_id=candidate.family_id,
        config_digest=candidate.config_digest,
        code_revision=candidate.code_revision,
        execution_config_json=candidate.execution_config_json,
        risk_config_json=candidate.risk_config_json,
        batch_ids=(),
        source_ids=(),
        closed_trade_count=0,
        closed_trade_days=0,
        net_pnl=Decimal("0"),
        mean_net_r=None,
        total_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        total_slippage_amount=Decimal("0"),
        realized_closed_trade_max_drawdown_fraction=None,
        max_realized_planned_risk_utilization=None,
        long_count=0,
        short_count=0,
        market_trade_counts=(),
        exit_reason_counts=(),
        checkpoint_state=checkpoint.checkpoint_state,
        candidate_state=checkpoint.candidate_state,
        posterior_probability_positive=checkpoint.posterior_probability_positive,
        policy_digest=checkpoint.policy_digest,
        reason_codes=checkpoint.reason_codes,
    )
    registry.record_performance_report(
        candidate_id=candidate.candidate_id,
        report_id=report.report_id,
        payload=report.to_dict(),
    )

    with raises(ResearchRegistryError, match="attested batch provenance"):
        registry.apply_checkpoint_state(
            candidate.candidate_id,
            checkpoint.candidate_state,
            report_id=report.report_id,
        )
    registry.close()
