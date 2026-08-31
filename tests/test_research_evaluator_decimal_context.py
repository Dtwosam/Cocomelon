from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_UP, Context, Decimal, localcontext
from pathlib import Path

from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"risk_per_trade":"0.0025","stops_required":true}'


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


def _evaluate(root: Path, context: Context) -> dict[str, object]:
    registry = ResearchRegistry(root / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=10_000,
            source_id="authoritative-v4-inventory",
        )
        artifact = write_research_artifact(
            root / "artifact",
            batch_id="decimal-batch",
            source_id="decimal-source",
            replay_run_id="decimal-replay",
            start_ms=1_000,
            end_ms=4_000,
            trades=(
                ArtifactTradeSpec(
                    closed_at_ms=2_300,
                    net_r=Decimal("0.123456789123456789"),
                    score=Decimal("70.123456789123456789"),
                ),
                ArtifactTradeSpec(
                    closed_at_ms=2_500,
                    net_r=Decimal("0.234567891234567891"),
                    score=Decimal("70.123456789123456789"),
                ),
                ArtifactTradeSpec(
                    closed_at_ms=2_700,
                    net_r=Decimal("0.345678912345678912"),
                    score=Decimal("70.123456789123456789"),
                ),
            ),
        )
        with localcontext(context):
            report = evaluate_research_checkpoint(
                registry=registry,
                candidate_id="decimal-context-candidate",
                artifact_batches=(artifact,),
            )
        return report.to_dict()
    finally:
        registry.close()


def test_research_report_is_independent_of_ambient_decimal_context(tmp_path: Path) -> None:
    low_precision = Context(prec=6, rounding=ROUND_DOWN)
    high_precision = Context(prec=50, rounding=ROUND_UP)

    low_report = _evaluate(tmp_path / "low", low_precision)
    high_report = _evaluate(tmp_path / "high", high_precision)

    assert low_report == high_report
