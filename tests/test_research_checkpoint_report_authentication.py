from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
)
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"max_position_r":"1","stops_required":true}'


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="report-auth-candidate",
        family_id="report-auth-family",
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


def _report_id(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_promising_checkpoint_must_be_reproducible_from_immutable_observations(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.transition_candidate(
            "report-auth-candidate",
            ResearchCandidateState.RESEARCHING,
            reason="test-start",
        )
        fabricated = {
            "candidate_id": "report-auth-candidate",
            "candidate_state": ResearchCandidateState.RESEARCH_PROMISING.value,
            "checkpoint_state": "research_promising",
            "closed_trade_count": 40,
            "closed_trade_days": 7,
            "posterior_probability_positive": "0.800000",
            "policy_digest": "f" * 64,
            "reason_codes": [],
        }
        report_id = _report_id(fabricated)
        registry.record_performance_report(
            candidate_id="report-auth-candidate",
            report_id=report_id,
            payload=fabricated,
        )

        with pytest.raises(ResearchRegistryError, match="immutable observations"):
            registry.apply_checkpoint_state(
                "report-auth-candidate",
                ResearchCandidateState.RESEARCH_PROMISING,
                report_id=report_id,
            )

        assert registry.load_candidate("report-auth-candidate").state is (
            ResearchCandidateState.RESEARCHING
        )
    finally:
        registry.close()
