from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.evidence.bundle import load_baseline_replay_bundle
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research import cohort as cohort_module
from cocomelon.research.artifact import verify_research_batch_artifact
from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.registry import ResearchRegistry
from tests.test_research_cohort import _cohort_roots


def _challenger_config() -> BaselineReplayConfig:
    return BaselineReplayConfig(
        starting_cash=Decimal("10000"),
        execution=PaperExecutionConfig(
            config_version="research-paper-15m-expiry-challenger-v1",
            max_position_age_ms=900_000,
        ),
        replay_engine_version=cohort_module.RESEARCH_REPLAY_ENGINE_VERSION,
        config_version=cohort_module.RESEARCH_REPLAY_CONFIG_VERSION,
    )


def _candidate(config: BaselineReplayConfig) -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="execution-challenger",
        family_id="execution-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest=config.config_digest,
        code_revision="1" * 40,
        execution_config_json=json.dumps(
            {
                "config_version": config.execution.config_version,
                "max_position_age_ms": config.execution.max_position_age_ms,
                "starting_cash": str(config.starting_cash),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        risk_config_json='{"paper_only":true,"risk_per_trade":"0.0025"}',
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def test_research_cohort_replays_explicit_candidate_execution_config(tmp_path: Path) -> None:
    recording_root, output_root, _ = _cohort_roots(tmp_path)
    config = _challenger_config()

    cohort_module.build_research_cohort(
        recording_root,
        output_root,
        config.starting_cash,
        trigger_head_sha="f" * 40,
        replay_config=config,
    )

    bundle = load_baseline_replay_bundle(output_root / "bundle.json")
    replay = json.loads((output_root / "replay.json").read_text(encoding="utf-8"))
    verified = verify_research_batch_artifact(
        output_root,
        batch_id="candidate-execution-batch",
        source_id="candidate-execution-source",
    )

    assert bundle.replay_config.config_digest == config.config_digest
    assert bundle.replay_config.execution.config_version == config.execution.config_version
    assert bundle.replay_config.execution.max_position_age_ms == 900_000
    assert replay["max_position_age_ms"] == 900_000
    assert verified.candidate_config_digest == config.config_digest


def test_research_source_binds_active_candidate_execution_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording_root, output_root, _ = _cohort_roots(tmp_path)
    config = _challenger_config()
    workspace = tmp_path / "workspace"
    registry_path = workspace / "research-control" / "state" / "research.sqlite3"
    registry_path.parent.mkdir(parents=True)
    registry = ResearchRegistry(registry_path)
    try:
        registry.create_candidate(_candidate(config))
    finally:
        registry.close()

    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    monkeypatch.setenv("RESEARCH_CANDIDATE_ID", "execution-challenger")

    cohort_module.prepare_research_cohort_source(
        recording_root,
        output_root,
        config.starting_cash,
        trigger_head_sha="f" * 40,
    )

    bundle = load_baseline_replay_bundle(output_root / "bundle.json")
    assert bundle.replay_config.config_digest == config.config_digest
    assert bundle.replay_config.execution.config_version == config.execution.config_version
    assert bundle.replay_config.execution.max_position_age_ms == 900_000
