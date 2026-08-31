from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.artifact import verify_research_batch_artifact
from cocomelon.research.attestation import attest_verified_research_batch
from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.evaluator import _observation_from_verified_sample
from cocomelon.research.metrics import compute_checkpoint_risk_metrics
from cocomelon.research.observations import load_trade_observations, record_trade_observations
from cocomelon.research.provenance import load_sealed_admitted_batch_provenance
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.seals import seal_research_batch
from cocomelon.research.sequential import evaluate_checkpoint
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

DAY_MS = 86_400_000
EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"risk_per_trade":"0.0025","stops_required":true}'


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


def _record_promising_report(registry: ResearchRegistry, root: Path) -> str:
    artifact = write_research_artifact(
        root,
        batch_id="race-batch",
        source_id="race-source",
        replay_run_id="race-replay",
        start_ms=1_000,
        end_ms=8 * DAY_MS,
        trades=tuple(
            ArtifactTradeSpec(
                closed_at_ms=(index % 7) * DAY_MS + 10_000 + index,
                net_r=Decimal("0.5"),
            )
            for index in range(40)
        ),
    )
    verified = verify_research_batch_artifact(
        artifact.artifact_root,
        batch_id=artifact.batch_id,
        source_id=artifact.source_id,
    )
    registry.record_batch(
        candidate_id="race-candidate",
        batch_id=verified.batch_id,
        source_id=verified.source_id,
        replay_run_id=verified.replay_run_id,
        interval=verified.interval,
    )
    seal_research_batch(
        registry.connection,
        candidate_id="race-candidate",
        batch_id=verified.batch_id,
        trade_ids=verified.trade_ids,
        sample_digest=verified.sample_digest,
    )
    attest_verified_research_batch(
        registry.connection,
        candidate_id="race-candidate",
        verified=verified,
    )
    planned = dict(verified.planned_risk_fractions)
    observations = tuple(
        _observation_from_verified_sample(
            sample,
            verified,
            planned_risk_fraction=planned[sample.trade_id],
        )
        for sample in verified.samples
    )
    record_trade_observations(
        registry.connection,
        candidate_id="race-candidate",
        observations=observations,
    )
    stored = load_trade_observations(
        registry.connection,
        candidate_id="race-candidate",
    )
    net_r_values = tuple(Decimal(str(item["net_r"])) for item in stored)
    closed_days = {int(item["closed_at_ms"]) // DAY_MS for item in stored}
    checkpoint = evaluate_checkpoint(
        net_r_values=net_r_values,
        closed_trade_days=len(closed_days),
    )
    assert checkpoint.candidate_state is ResearchCandidateState.RESEARCH_PROMISING
    risk_metrics = compute_checkpoint_risk_metrics(
        stored,
        configured_risk_per_trade=Decimal("0.0025"),
    )
    batch_ids, source_ids = load_sealed_admitted_batch_provenance(
        registry.connection,
        candidate_id="race-candidate",
    )
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
        "realized_closed_trade_max_drawdown_fraction": (
            None
            if risk_metrics.realized_closed_trade_max_drawdown_fraction is None
            else str(risk_metrics.realized_closed_trade_max_drawdown_fraction)
        ),
        "max_realized_planned_risk_utilization": (
            None
            if risk_metrics.max_realized_planned_risk_utilization is None
            else str(risk_metrics.max_realized_planned_risk_utilization)
        ),
        "batch_ids": list(batch_ids),
        "source_ids": list(source_ids),
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
    report_id = _record_promising_report(registry, tmp_path / "race-artifact")

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

    with pytest.raises(
        ResearchRegistryError,
        match="changed concurrently|immutable observations|contamin",
    ):
        registry.apply_checkpoint_state(
            "race-candidate",
            ResearchCandidateState.RESEARCH_PROMISING,
            report_id=report_id,
        )

    assert original_load("race-candidate").state is ResearchCandidateState.REJECTED_CONTAMINATION
    registry.close()
