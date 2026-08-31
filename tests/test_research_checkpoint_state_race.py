from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.observations import record_trade_observations
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.sequential import evaluate_checkpoint

DAY_MS = 86_400_000
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


def _record_promising_report(registry: ResearchRegistry) -> str:
    observations = tuple(
        {
            "trade_id": f"race-trade-{index}",
            "closed_at_ms": (index % 7) * DAY_MS + 2_000 + index,
            "net_r": "0.5",
        }
        for index in range(40)
    )
    record_trade_observations(
        registry.connection,
        candidate_id="race-candidate",
        observations=observations,
    )
    checkpoint = evaluate_checkpoint(
        net_r_values=tuple(Decimal("0.5") for _ in observations),
        closed_trade_days=7,
    )
    assert checkpoint.candidate_state is ResearchCandidateState.RESEARCH_PROMISING
    payload: dict[str, object] = {
        "candidate_id": "race-candidate",
        "candidate_state": checkpoint.candidate_state.value,
        "checkpoint_state": checkpoint.checkpoint_state.value,
        "closed_trade_count": checkpoint.trade_count,
        "closed_trade_days": checkpoint.closed_trade_days,
        "posterior_probability_positive": (
            None
            if checkpoint.posterior_probability_positive is None
            else str(checkpoint.posterior_probability_positive)
        ),
        "policy_digest": checkpoint.policy_digest,
        "reason_codes": list(checkpoint.reason_codes),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    report_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    registry.record_performance_report(
        candidate_id="race-candidate",
        report_id=report_id,
        payload=payload,
    )
    return report_id


def test_checkpoint_update_cannot_overwrite_late_v4_contamination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(registry_path)
    registry.mark_v4_registry_complete_through(
        through_ms=8 * DAY_MS,
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
        interval=TimeInterval(1_000, 8 * DAY_MS),
    )
    report_id = _record_promising_report(registry)

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
            report_id=report_id,
        )

    assert original_load("race-candidate").state is ResearchCandidateState.REJECTED_CONTAMINATION
    registry.close()
