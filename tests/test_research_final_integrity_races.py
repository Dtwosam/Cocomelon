from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.lifecycle import activate_validation_cutover
from cocomelon.research.metrics import compute_checkpoint_risk_metrics
from cocomelon.research.observations import record_trade_observations
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"risk_per_trade":"0.0025","stops_required":true}'


def _candidate(candidate_id: str = "candidate-a") -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id="family-a",
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


def test_direct_trade_observation_insert_requires_authoritative_batch_attestation(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate())

    with pytest.raises(ResearchRegistryError, match="attested|sealed"):
        record_trade_observations(
            registry.connection,
            candidate_id="candidate-a",
            observations=(
                {
                    "trade_id": "forged-trade",
                    "batch_id": "missing-batch",
                    "closed_at_ms": 2_000,
                    "net_pnl": "10",
                    "net_r": "1",
                    "equity_before": "10000",
                },
            ),
        )
    registry.close()


def test_planned_risk_utilization_uses_planned_fraction_against_configured_budget() -> None:
    observations = (
        {
            "trade_id": "trade-a",
            "closed_at_ms": 2_000,
            "net_pnl": "10",
            "net_r": "0.4",
            "equity_before": "10000",
            "planned_risk_fraction": "0.0025",
        },
        {
            "trade_id": "trade-b",
            "closed_at_ms": 3_000,
            "net_pnl": "-5",
            "net_r": "-0.2",
            "equity_before": "10010",
            "planned_risk_fraction": "0.00125",
        },
    )

    metrics = compute_checkpoint_risk_metrics(
        observations,
        configured_risk_per_trade=Decimal("0.0025"),
    )

    assert metrics.max_realized_planned_risk_utilization == Decimal("1")


def test_validation_activation_cannot_authorize_stale_frozen_state_after_contamination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(path)
    registry.create_candidate(_candidate())
    registry.mark_v4_registry_complete_through(
        through_ms=100_000,
        source_id="authoritative-v4",
    )
    registry.connection.execute(
        "UPDATE research_candidates SET state = ?, freeze_ms = ? WHERE candidate_id = ?",
        (ResearchCandidateState.FROZEN_CHALLENGER.value, 20_000, "candidate-a"),
    )
    registry.connection.execute(
        "INSERT INTO research_touched_intervals (candidate_id, source_id, start_ms, end_ms) "
        "VALUES (?, ?, ?, ?)",
        ("candidate-a", "research-source", 1_000, 2_000),
    )
    registry.connection.commit()

    original_begin = registry._begin_immediate
    contaminated = False

    def contaminate_then_begin() -> None:
        nonlocal contaminated
        if not contaminated:
            contaminated = True
            late = ResearchRegistry(path)
            try:
                late.record_batch(
                    candidate_id="candidate-a",
                    batch_id="late-batch",
                    source_id="late-source",
                    replay_run_id="late-replay",
                    interval=TimeInterval(30_000, 40_000),
                )
                late.record_v4_interval(
                    run_id="late-v4",
                    interval=TimeInterval(35_000, 36_000),
                    disposition="diagnostic_failure",
                )
            finally:
                late.close()
        original_begin()

    monkeypatch.setattr(registry, "_begin_immediate", contaminate_then_begin)

    with pytest.raises(ResearchRegistryError, match="changed concurrently|contaminated|frozen"):
        activate_validation_cutover(
            registry,
            "candidate-a",
            validation_start_ms=50_000,
        )

    assert registry.load_candidate("candidate-a").state is ResearchCandidateState.REJECTED_CONTAMINATION
    registry.close()
