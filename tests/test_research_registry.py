from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from pytest import raises

from cocomelon.research.contracts import (
    SIX_HOURS_MS,
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import (
    ResearchContaminationError,
    ResearchRegistry,
    ResearchRegistryError,
)
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

DAY_MS = 86_400_000
EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"max_position_r":"1","risk_per_trade":"0.0025","stops_required":true}'
V4_TEST_SOURCE = "authoritative-v4-test-inventory"


def _candidate(
    candidate_id: str,
    *,
    family_id: str = "family-a",
    parent_candidate_id: str | None = None,
    ancestor_candidate_ids: tuple[str, ...] = (),
    digest_char: str = "a",
) -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id=family_id,
        parent_candidate_id=parent_candidate_id,
        ancestor_candidate_ids=ancestor_candidate_ids,
        config_digest=digest_char * 64,
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


def _payload_report_id(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_promising_report(
    registry: ResearchRegistry,
    candidate_id: str,
) -> str:
    registry.mark_v4_registry_complete_through(
        through_ms=8 * DAY_MS,
        source_id=V4_TEST_SOURCE,
    )
    artifact = write_research_artifact(
        registry.path.parent / f"{candidate_id}-registry-promising-artifact",
        batch_id=f"{candidate_id}-registry-promising-batch",
        source_id=f"{candidate_id}-registry-promising-source",
        replay_run_id=f"{candidate_id}-registry-promising-replay",
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
    report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate_id,
        artifact_batches=(artifact,),
    )
    assert report.candidate_state is ResearchCandidateState.RESEARCH_PROMISING
    return report.report_id


def test_registry_persists_lineage_and_inherits_ancestor_touched_intervals(
    tmp_path: Path,
) -> None:
    path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(path)
    root = _candidate("r1", digest_char="a")
    child = _candidate(
        "r2",
        parent_candidate_id="r1",
        ancestor_candidate_ids=("r1",),
        digest_char="b",
    )
    grandchild = _candidate(
        "r3",
        parent_candidate_id="r2",
        ancestor_candidate_ids=("r1", "r2"),
        digest_char="c",
    )

    registry.create_candidate(root)
    registry.record_touched_interval("r1", TimeInterval(10, 20), source_id="root-source")
    registry.create_candidate(child)
    registry.record_touched_interval("r2", TimeInterval(30, 40), source_id="child-source")
    registry.create_candidate(grandchild)
    registry.record_touched_interval("r3", TimeInterval(19, 31), source_id="grandchild-source")
    registry.close()

    reopened = ResearchRegistry(path)
    loaded = reopened.load_candidate("r3")
    assert reopened.effective_touched_intervals("r3") == (TimeInterval(10, 40),)
    assert loaded.candidate_id == grandchild.candidate_id
    assert loaded.family_id == grandchild.family_id
    assert loaded.parent_candidate_id == grandchild.parent_candidate_id
    assert loaded.ancestor_candidate_ids == grandchild.ancestor_candidate_ids
    assert loaded.config_digest == grandchild.config_digest
    assert loaded.code_revision == grandchild.code_revision
    assert loaded.execution_config_json == grandchild.execution_config_json
    assert loaded.risk_config_json == grandchild.risk_config_json
    assert loaded.first_observation_ms == 19
    assert loaded.last_observation_ms == 31
    assert loaded.source_provenance_ids == ("grandchild-source",)
    assert loaded.local_touched_intervals == (TimeInterval(19, 31),)
    assert loaded.effective_touched_intervals == (TimeInterval(10, 40),)
    assert loaded.performance_report_ids == ()
    reopened.close()


def test_registry_rejects_cross_family_or_inexact_parent_lineage(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate("r1", family_id="family-a"))

    with raises(ResearchRegistryError, match="family"):
        registry.create_candidate(
            _candidate(
                "r2",
                family_id="family-b",
                parent_candidate_id="r1",
                ancestor_candidate_ids=("r1",),
                digest_char="b",
            )
        )

    with raises(ResearchRegistryError, match="ancestor"):
        registry.create_candidate(
            _candidate(
                "r3",
                family_id="family-a",
                parent_candidate_id="r1",
                ancestor_candidate_ids=("missing", "r1"),
                digest_char="c",
            )
        )
    registry.close()


def test_any_registered_v4_interval_blocks_overlapping_research_source(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.record_v4_interval(
        run_id="v4-failed-run",
        interval=TimeInterval(1_000, 2_000),
        disposition="diagnostic_failure",
    )

    with raises(ResearchContaminationError, match="v4-failed-run"):
        registry.assert_batch_disjoint_from_v4(TimeInterval(1_999, 2_500))

    registry.mark_v4_registry_complete_through(
        through_ms=2_500,
        source_id=V4_TEST_SOURCE,
    )
    registry.assert_batch_disjoint_from_v4(TimeInterval(2_000, 2_500))
    registry.close()


def test_late_v4_interval_retroactively_contaminates_batch_and_descendants(
    tmp_path: Path,
) -> None:
    path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(path)
    registry.create_candidate(_candidate("r1"))
    registry.mark_v4_registry_complete_through(
        through_ms=2_000,
        source_id=V4_TEST_SOURCE,
    )
    registry.record_batch(
        candidate_id="r1",
        batch_id="research-batch-1",
        source_id="research-source-1",
        replay_run_id="research-replay-1",
        interval=TimeInterval(1_000, 2_000),
    )
    child = _candidate(
        "r2",
        parent_candidate_id="r1",
        ancestor_candidate_ids=("r1",),
        digest_char="b",
    )
    registry.create_candidate(child)

    registry.record_v4_interval(
        run_id="late-v4-run",
        interval=TimeInterval(1_500, 2_500),
        disposition="accepted",
    )

    assert registry.load_candidate("r1").state is ResearchCandidateState.REJECTED_CONTAMINATION
    assert registry.load_candidate("r2").state is ResearchCandidateState.REJECTED_CONTAMINATION
    assert registry.effective_touched_intervals("r2") == (TimeInterval(1_000, 2_000),)
    registry.close()

    connection = sqlite3.connect(path)
    try:
        batch_status = connection.execute(
            "SELECT status, contamination_v4_run_id FROM research_batches WHERE batch_id = ?",
            ("research-batch-1",),
        ).fetchone()
    finally:
        connection.close()
    assert batch_status == ("rejected_contamination", "late-v4-run")


def test_child_of_contaminated_parent_is_contaminated_at_creation(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate("r1"))
    registry.transition_candidate(
        "r1",
        ResearchCandidateState.REJECTED_CONTAMINATION,
        reason="source_overlap",
    )
    child = _candidate(
        "r2",
        parent_candidate_id="r1",
        ancestor_candidate_ids=("r1",),
        digest_char="b",
    )

    registry.create_candidate(child)

    assert registry.load_candidate("r2").state is ResearchCandidateState.REJECTED_CONTAMINATION
    registry.close()


def test_terminal_candidate_state_cannot_return_to_researching(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate("r1"))
    registry.transition_candidate("r1", ResearchCandidateState.RESEARCHING, reason="started")
    registry.transition_candidate(
        "r1",
        ResearchCandidateState.REJECTED_CONTAMINATION,
        reason="contaminated",
    )

    with raises(ResearchRegistryError, match="terminal"):
        registry.transition_candidate("r1", ResearchCandidateState.RESEARCHING, reason="resume")
    registry.close()


def test_generic_state_api_cannot_enter_evidence_derived_or_validation_states(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate("r1"))

    for state in (
        ResearchCandidateState.RESEARCH_PROMISING,
        ResearchCandidateState.REJECTED_FUTILITY,
        ResearchCandidateState.VALIDATING,
        ResearchCandidateState.VALIDATED_EDGE,
        ResearchCandidateState.NO_EDGE,
    ):
        with raises(ResearchRegistryError, match="transition"):
            registry.transition_candidate("r1", state, reason="skip-evidence")
    registry.close()


def test_checkpoint_state_requires_authenticated_observation_backing(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate("r1"))
    registry.transition_candidate("r1", ResearchCandidateState.RESEARCHING, reason="started")

    with raises(ResearchRegistryError, match="report"):
        registry.apply_checkpoint_state(
            "r1",
            ResearchCandidateState.RESEARCH_PROMISING,
            report_id="missing-report",
        )

    fabricated: dict[str, object] = {
        "candidate_id": "r1",
        "candidate_state": ResearchCandidateState.RESEARCH_PROMISING.value,
        "checkpoint_state": "research_promising",
        "closed_trade_count": 40,
        "closed_trade_days": 7,
        "posterior_probability_positive": "0.990000",
        "policy_digest": "f" * 64,
        "reason_codes": [],
        "batch_ids": [],
        "source_ids": [],
    }
    fabricated_id = _payload_report_id(fabricated)
    registry.record_performance_report(
        candidate_id="r1",
        report_id=fabricated_id,
        payload=fabricated,
    )
    with raises(ResearchRegistryError, match="immutable observations"):
        registry.apply_checkpoint_state(
            "r1",
            ResearchCandidateState.RESEARCH_PROMISING,
            report_id=fabricated_id,
        )

    report_id = _record_promising_report(registry, "r1")
    assert report_id in registry.load_candidate("r1").performance_report_ids
    assert registry.load_candidate("r1").state is ResearchCandidateState.RESEARCH_PROMISING
    registry.close()


def test_frozen_candidate_cutover_uses_inherited_touched_history(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate("r1"))
    inherited_end_ms = 10 * DAY_MS + 20_000
    registry.record_touched_interval(
        "r1",
        TimeInterval(10 * DAY_MS + 10_000, inherited_end_ms),
        source_id="source",
    )
    child = _candidate(
        "r2",
        parent_candidate_id="r1",
        ancestor_candidate_ids=("r1",),
        digest_char="b",
    )
    registry.create_candidate(child)
    registry.transition_candidate("r2", ResearchCandidateState.RESEARCHING, reason="started")
    _record_promising_report(registry, "r2")
    freeze_ms = inherited_end_ms + 1
    registry.freeze_candidate("r2", freeze_ms=freeze_ms)

    with raises(ResearchRegistryError, match="embargo"):
        registry.assert_validation_cutover(
            "r2",
            validation_start_ms=inherited_end_ms + SIX_HOURS_MS - 1,
        )

    registry.assert_validation_cutover(
        "r2",
        validation_start_ms=max(freeze_ms + 1, inherited_end_ms + SIX_HOURS_MS),
    )
    registry.close()
