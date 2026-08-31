from __future__ import annotations

from decimal import Decimal, localcontext
from pathlib import Path

from cocomelon.evaluation.metrics import AUTHORITATIVE_CONTEXT
from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

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
        artifact = write_research_artifact(
            tmp_path / "artifact",
            batch_id="risk-report-batch",
            source_id="risk-report-source",
            replay_run_id="risk-report-replay",
            start_ms=1_000,
            end_ms=4 * DAY_MS,
            trades=(
                ArtifactTradeSpec(
                    closed_at_ms=2_000,
                    net_r=Decimal("0.4"),
                    equity_before=Decimal("1000"),
                    planned_risk_fraction=Decimal("0.0025"),
                ),
                ArtifactTradeSpec(
                    closed_at_ms=DAY_MS + 2_000,
                    net_r=Decimal("-0.5"),
                    equity_before=Decimal("1000"),
                    planned_risk_fraction=Decimal("0.00125"),
                ),
                ArtifactTradeSpec(
                    closed_at_ms=2 * DAY_MS + 2_000,
                    net_r=Decimal("-1.2"),
                    equity_before=Decimal("1000"),
                    planned_risk_fraction=Decimal("0.003"),
                ),
            ),
        )
        report = evaluate_research_checkpoint(
            registry=registry,
            candidate_id="risk-report-candidate",
            artifact_batches=(artifact,),
        )

        with localcontext(AUTHORITATIVE_CONTEXT):
            expected_drawdown = Decimal("4.225") / Decimal("1001")
        assert report.realized_closed_trade_max_drawdown_fraction == expected_drawdown
        assert report.max_realized_planned_risk_utilization == Decimal("1.2")
        persisted = registry._checkpoint_report_payload(
            "risk-report-candidate",
            report.report_id,
        )
        assert persisted["realized_closed_trade_max_drawdown_fraction"] == str(
            expected_drawdown
        )
        assert persisted["max_realized_planned_risk_utilization"] == "1.2"
    finally:
        registry.close()
