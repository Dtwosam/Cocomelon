from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
)
from cocomelon.research.dashboard import RESEARCH_STATUS_LABEL, build_research_status
from cocomelon.research.registry import ResearchRegistry
from cocomelon.research.runner import (
    ResearchRunnerRequest,
    run_research_artifact_attempt,
)
from cocomelon.research.runner_history import (
    ResearchRunnerAttemptStatus,
    load_runner_attempts,
)
from tests.research_artifact_support import (
    CODE_REVISION,
    CONFIG_DIGEST,
    ArtifactTradeSpec,
    write_research_artifact,
)


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="scheduled-runner-isolation",
        family_id="scheduled-runner-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest=CONFIG_DIGEST,
        code_revision=CODE_REVISION,
        execution_config_json='{"mode":"paper","slippage_model":"recorded"}',
        risk_config_json='{"risk_per_trade":"0.0025","stops_required":true}',
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def test_runner_checkpoint_remains_non_promotional_in_status(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=3_000,
            source_id="authoritative-v4-inventory",
        )
        artifact = write_research_artifact(
            tmp_path / "scheduled-artifact",
            batch_id="scheduled-batch",
            source_id="scheduled-source",
            replay_run_id="scheduled-replay",
            start_ms=1_000,
            end_ms=3_000,
            trades=(ArtifactTradeSpec(closed_at_ms=2_500, net_r=Decimal("0.20")),),
        )
        result = run_research_artifact_attempt(
            registry,
            ResearchRunnerRequest(
                attempt_id="scheduled-attempt",
                candidate_id="scheduled-runner-isolation",
                batch_id=artifact.batch_id,
                source_id=artifact.source_id,
                artifact_root=artifact.artifact_root,
            ),
        )
        status = build_research_status(registry)
        attempts = load_runner_attempts(registry.connection)
    finally:
        registry.close()

    assert status["label"] == RESEARCH_STATUS_LABEL == "TOUCHED / NON-PROMOTIONAL"
    assert status["candidate_count"] == 1
    candidate = status["candidates"][0]
    assert candidate["candidate_id"] == "scheduled-runner-isolation"
    assert candidate["checkpoints"][0]["report_id"] == result.report_id
    assert attempts[0].status is ResearchRunnerAttemptStatus.SUCCEEDED


def test_runner_surfaces_do_not_import_frozen_v4_or_execution_secrets() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    paths = (
        repo_root / "src/cocomelon/research/runner.py",
        repo_root / "src/cocomelon/research/cohort.py",
        repo_root / "src/cocomelon/research_runner_cli.py",
        repo_root / ".github/workflows/research-campaign-scheduled.yml",
    )
    forbidden = (
        "evidence_corpus_curator",
        "phase9_v4_one_shot",
        "v4-mainnet-corpus",
        "candidate_edge",
        "private_key",
        "wallet",
        "withdraw",
        "transfer",
        "send_order",
        "live_order",
        "v4_net_pnl",
        "v4_mean_net_r",
        "v4_posterior_probability",
    )

    for path in paths:
        source = path.read_text(encoding="utf-8").lower()
        for fragment in forbidden:
            assert fragment not in source, f"{fragment} leaked into {path}"


def test_runner_and_workflow_never_mutate_v4_interval_authority() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            repo_root / "src/cocomelon/research/runner.py",
            repo_root / "src/cocomelon/research/cohort.py",
            repo_root / ".github/workflows/research-campaign-scheduled.yml",
        )
    )

    assert "mark_v4_registry_complete_through" not in sources
    assert "record_v4_interval" not in sources
    assert "assert_batch_disjoint_from_v4" in sources
