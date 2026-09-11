from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research import cohort as cohort_module
from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError


def _candidate(candidate_id: str, *, revision: str, max_age_ms: int) -> ResearchCandidateManifest:
    config = BaselineReplayConfig(
        starting_cash=Decimal("10000"),
        execution=PaperExecutionConfig(
            config_version=f"{candidate_id}-execution-v1",
            max_position_age_ms=max_age_ms,
        ),
        replay_engine_version=cohort_module.RESEARCH_REPLAY_ENGINE_VERSION,
        config_version=cohort_module.RESEARCH_REPLAY_CONFIG_VERSION,
    )
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


def _registry(tmp_path: Path) -> ResearchRegistry:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(
        _candidate(
            "scheduled-research-root",
            revision="1" * 40,
            max_age_ms=cohort_module.RESEARCH_MAX_POSITION_AGE_MS,
        )
    )
    registry.create_candidate(
        _candidate(
            "execution-challenger",
            revision="2" * 40,
            max_age_ms=900_000,
        )
    )
    return registry


def test_root_only_fanout_is_required_and_uses_shared_source_identity(tmp_path: Path) -> None:
    from cocomelon.research.fanout import resolve_research_fanout

    registry = _registry(tmp_path)
    try:
        resolved = resolve_research_fanout(
            registry,
            root_candidate_id="scheduled-research-root",
            challenger_candidate_id=None,
            run_id="123",
            run_attempt=2,
        )
    finally:
        registry.close()

    assert len(resolved) == 1
    root = resolved[0]
    assert root.candidate_id == "scheduled-research-root"
    assert root.code_revision == "1" * 40
    assert root.required is True
    assert root.attempt_id == "research-123-2-scheduled-research-root"
    assert root.batch_id == "research-batch-123-2-scheduled-research-root"
    assert root.source_id == "research-mainnet-123-2"


def test_root_and_challenger_share_source_but_keep_candidate_identity(tmp_path: Path) -> None:
    from cocomelon.research.fanout import resolve_research_fanout

    registry = _registry(tmp_path)
    try:
        resolved = resolve_research_fanout(
            registry,
            root_candidate_id="scheduled-research-root",
            challenger_candidate_id="execution-challenger",
            run_id="456",
            run_attempt=1,
        )
    finally:
        registry.close()

    assert [item.candidate_id for item in resolved] == [
        "scheduled-research-root",
        "execution-challenger",
    ]
    assert [item.required for item in resolved] == [True, False]
    assert [item.code_revision for item in resolved] == ["1" * 40, "2" * 40]
    assert len({item.attempt_id for item in resolved}) == 2
    assert len({item.batch_id for item in resolved}) == 2
    assert {item.source_id for item in resolved} == {"research-mainnet-456-1"}
    assert len({item.artifact_key for item in resolved}) == 2


def test_fanout_rejects_challenger_equal_to_root(tmp_path: Path) -> None:
    from cocomelon.research.fanout import resolve_research_fanout

    registry = _registry(tmp_path)
    try:
        with pytest.raises(ValueError, match="distinct"):
            resolve_research_fanout(
                registry,
                root_candidate_id="scheduled-research-root",
                challenger_candidate_id="scheduled-research-root",
                run_id="789",
                run_attempt=1,
            )
    finally:
        registry.close()


def test_fanout_requires_challenger_to_exist_in_authoritative_registry(tmp_path: Path) -> None:
    from cocomelon.research.fanout import resolve_research_fanout

    registry = _registry(tmp_path)
    try:
        with pytest.raises(ResearchRegistryError, match="candidate not found"):
            resolve_research_fanout(
                registry,
                root_candidate_id="scheduled-research-root",
                challenger_candidate_id="missing-challenger",
                run_id="999",
                run_attempt=1,
            )
    finally:
        registry.close()
