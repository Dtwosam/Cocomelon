from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.evidence.bundle import load_baseline_replay_bundle
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research import cohort as cohort_module
from cocomelon.research.artifact import verify_research_batch_artifact
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


def test_research_workflow_binds_capture_to_registered_candidate_execution_config() -> None:
    source = Path(".github/workflows/research-campaign-scheduled.yml").read_text(
        encoding="utf-8"
    )

    assert "research_replay_config_from_candidate" in source
    assert "registry.load_candidate(candidate_id)" in source
    assert "replay_config=replay_config" in source
