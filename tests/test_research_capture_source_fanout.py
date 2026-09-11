from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.evidence.bundle import load_baseline_replay_bundle
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research import cohort as cohort_module
from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from tests.test_research_cohort import _cohort_roots


def _config(*, version: str, max_position_age_ms: int) -> BaselineReplayConfig:
    return BaselineReplayConfig(
        starting_cash=Decimal("10000"),
        execution=PaperExecutionConfig(
            config_version=version,
            max_position_age_ms=max_position_age_ms,
        ),
        replay_engine_version=cohort_module.RESEARCH_REPLAY_ENGINE_VERSION,
        config_version=cohort_module.RESEARCH_REPLAY_CONFIG_VERSION,
    )


def _candidate(
    candidate_id: str,
    config: BaselineReplayConfig,
    *,
    revision: str,
) -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id="fanout-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest=config.config_digest,
        code_revision=revision,
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


def test_capture_source_is_candidate_neutral_and_reusable(tmp_path: Path) -> None:
    recording_root, capture_output, _ = _cohort_roots(tmp_path)

    source = cohort_module.prepare_research_capture_source(
        recording_root,
        capture_output,
        trigger_head_sha="f" * 40,
    )

    payload = json.loads((capture_output / "capture-source.json").read_text(encoding="utf-8"))
    assert payload["recording_session_digest"] == source.recording_session_digest
    assert payload["source_set_digest"] == source.source_set_digest
    assert payload["start_ms"] == source.start_ms
    assert payload["end_ms"] == source.end_ms
    for forbidden in (
        "candidate_id",
        "config_digest",
        "execution_config",
        "max_position_age_ms",
        "starting_cash",
    ):
        assert forbidden not in payload

    root_config = _config(
        version=cohort_module.RESEARCH_EXECUTION_CONFIG_VERSION,
        max_position_age_ms=cohort_module.RESEARCH_MAX_POSITION_AGE_MS,
    )
    challenger_config = _config(
        version="research-paper-15m-expiry-challenger-v1",
        max_position_age_ms=900_000,
    )
    root_candidate = _candidate("scheduled-research-root", root_config, revision="1" * 40)
    challenger = _candidate("execution-challenger", challenger_config, revision="2" * 40)

    root_output = tmp_path / "root-output"
    challenger_output = tmp_path / "challenger-output"
    root_output.mkdir()
    challenger_output.mkdir()

    root = cohort_module.materialize_research_candidate_source(
        recording_root,
        root_output,
        capture_source_path=capture_output / "capture-source.json",
        candidate=root_candidate,
    )
    alternate = cohort_module.materialize_research_candidate_source(
        recording_root,
        challenger_output,
        capture_source_path=capture_output / "capture-source.json",
        candidate=challenger,
    )

    root_bundle = load_baseline_replay_bundle(root_output / "bundle.json")
    challenger_bundle = load_baseline_replay_bundle(challenger_output / "bundle.json")

    assert root.recording_session_digest == alternate.recording_session_digest
    assert root.source_set_digest == alternate.source_set_digest
    assert root.recording_session_digest == source.recording_session_digest
    assert root.source_set_digest == source.source_set_digest
    assert root_bundle.replay_config.config_digest == root_config.config_digest
    assert challenger_bundle.replay_config.config_digest == challenger_config.config_digest
    assert root_bundle.replay_config.config_digest != challenger_bundle.replay_config.config_digest


def test_candidate_materialization_refuses_changed_capture_source(tmp_path: Path) -> None:
    recording_root, capture_output, _ = _cohort_roots(tmp_path)
    cohort_module.prepare_research_capture_source(
        recording_root,
        capture_output,
        trigger_head_sha="f" * 40,
    )
    payload = json.loads((capture_output / "capture-source.json").read_text(encoding="utf-8"))
    payload["source_set_digest"] = "0" * 64
    (capture_output / "capture-source.json").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    config = _config(
        version=cohort_module.RESEARCH_EXECUTION_CONFIG_VERSION,
        max_position_age_ms=cohort_module.RESEARCH_MAX_POSITION_AGE_MS,
    )
    output = tmp_path / "candidate-output"
    output.mkdir()

    with pytest.raises(ValueError, match="capture source"):
        cohort_module.materialize_research_candidate_source(
            recording_root,
            output,
            capture_source_path=capture_output / "capture-source.json",
            candidate=_candidate("scheduled-research-root", config, revision="1" * 40),
        )
