from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.dashboard import (
    RESEARCH_STATUS_LABEL,
    build_research_status,
)
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"max_position_r":"1","risk_per_trade":"0.0025","stops_required":true}'


def _candidate(candidate_id: str) -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id=f"{candidate_id}-family",
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


def test_research_status_is_empty_and_permanently_labeled(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        status = build_research_status(registry)
    finally:
        registry.close()

    assert status == {
        "label": RESEARCH_STATUS_LABEL,
        "candidate_count": 0,
        "state_counts": {},
        "candidates": [],
    }
    assert RESEARCH_STATUS_LABEL == "TOUCHED / NON-PROMOTIONAL"


def test_research_status_includes_draft_candidate_without_economics(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate("draft-candidate"))
        status = build_research_status(registry)
    finally:
        registry.close()

    candidate = status["candidates"][0]
    assert candidate["candidate_id"] == "draft-candidate"
    assert candidate["state"] == "draft"
    assert candidate["checkpoints"] == []
    assert status["state_counts"] == {"draft": 1}


def test_research_status_authenticates_and_orders_checkpoint_history(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate("candidate-a"))
        registry.mark_v4_registry_complete_through(
            through_ms=400_000,
            source_id="authoritative-v4-test-inventory",
        )
        first_artifact = write_research_artifact(
            tmp_path / "first",
            batch_id="batch-first",
            source_id="source-first",
            replay_run_id="replay-first",
            start_ms=1_000,
            end_ms=200_000,
            trades=(
                ArtifactTradeSpec(closed_at_ms=100_000, net_r=Decimal("0.25")),
            ),
        )
        first_report = evaluate_research_checkpoint(
            registry=registry,
            candidate_id="candidate-a",
            artifact_batches=(first_artifact,),
        )
        second_artifact = write_research_artifact(
            tmp_path / "second",
            batch_id="batch-second",
            source_id="source-second",
            replay_run_id="replay-second",
            start_ms=200_000,
            end_ms=400_000,
            trades=(
                ArtifactTradeSpec(closed_at_ms=300_000, net_r=Decimal("-0.10")),
            ),
        )
        second_report = evaluate_research_checkpoint(
            registry=registry,
            candidate_id="candidate-a",
            artifact_batches=(second_artifact,),
        )

        status = build_research_status(registry)
    finally:
        registry.close()

    candidate = status["candidates"][0]
    checkpoints = candidate["checkpoints"]
    assert [item["report_id"] for item in checkpoints] == [
        first_report.report_id,
        second_report.report_id,
    ]
    assert [item["source_end_ms"] for item in checkpoints] == [200_000, 400_000]
    assert checkpoints[0]["closed_trade_count"] == 1
    assert checkpoints[1]["closed_trade_count"] == 2
    assert checkpoints[1]["batch_ids"] == ["batch-first", "batch-second"]
    assert checkpoints[1]["source_ids"] == ["source-first", "source-second"]
    assert checkpoints[1]["net_pnl"] == "3.75"
    assert checkpoints[1]["mean_net_r"] == "0.075"


def test_research_status_fails_closed_on_unauthenticated_report(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate("fabricated-candidate"))
        fabricated: dict[str, object] = {
            "candidate_id": "fabricated-candidate",
            "candidate_state": ResearchCandidateState.RESEARCHING.value,
        }
        report_id = _report_id(fabricated)
        registry.record_performance_report(
            candidate_id="fabricated-candidate",
            report_id=report_id,
            payload=fabricated,
        )

        with pytest.raises(ResearchRegistryError, match="attested batch provenance"):
            build_research_status(registry)
    finally:
        registry.close()
