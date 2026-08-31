from __future__ import annotations

from pathlib import Path

import pytest

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
        candidate_id="race-candidate",
        family_id="race-family",
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


def test_checkpoint_update_cannot_overwrite_late_v4_contamination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(registry_path)
    registry.mark_v4_registry_complete_through(
        through_ms=10_000,
        source_id="authoritative-v4-inventory",
    )
    registry.create_candidate(_candidate())
    registry.transition_candidate(
        "race-candidate",
        ResearchCandidateState.RESEARCHING,
        reason="test-start",
    )
    registry.record_batch(
        candidate_id="race-candidate",
        batch_id="race-batch",
        source_id="race-source",
        replay_run_id="race-replay",
        interval=TimeInterval(1_000, 2_000),
    )
    registry.record_performance_report(
        candidate_id="race-candidate",
        report_id="race-promising-report",
        payload={
            "candidate_id": "race-candidate",
            "candidate_state": ResearchCandidateState.RESEARCH_PROMISING.value,
            "checkpoint_state": "research_promising",
            "closed_trade_count": 40,
            "closed_trade_days": 7,
            "posterior_probability_positive": "0.80",
            "reason_codes": [],
        },
    )

    original_load = registry.load_candidate
    contaminated = False

    def load_then_contaminate(candidate_id: str) -> ResearchCandidateManifest:
        nonlocal contaminated
        candidate = original_load(candidate_id)
        if candidate_id == "race-candidate" and not contaminated:
            contaminated = True
            late_registry = ResearchRegistry(registry_path)
            try:
                late_registry.record_v4_interval(
                    run_id="late-v4-run",
                    interval=TimeInterval(1_500, 1_600),
                    disposition="diagnostic_failure",
                )
            finally:
                late_registry.close()
        return candidate

    monkeypatch.setattr(registry, "load_candidate", load_then_contaminate)

    with pytest.raises(ResearchRegistryError, match="changed concurrently"):
        registry.apply_checkpoint_state(
            "race-candidate",
            ResearchCandidateState.RESEARCH_PROMISING,
            report_id="race-promising-report",
        )

    assert original_load("race-candidate").state is ResearchCandidateState.REJECTED_CONTAMINATION
    registry.close()
