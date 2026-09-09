from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.evidence.bundle import load_baseline_replay_bundle
from cocomelon.research.artifact import verify_research_batch_artifact
from cocomelon.research.attestation import (
    attest_verified_research_batch,
    ensure_batch_attestation_schema,
    load_candidate_attested_decision_throughput,
)
from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from tests.test_research_cohort import _cohort_roots

CANDIDATE_ID = "throughput-attestation-candidate"


def _verified_batch(tmp_path: Path):
    recording_root, output_root, _ = _cohort_roots(tmp_path)
    from cocomelon.research.cohort import build_research_cohort

    build_research_cohort(
        recording_root,
        output_root,
        Decimal("10000"),
        trigger_head_sha="f" * 40,
    )
    verified = verify_research_batch_artifact(
        output_root,
        batch_id="throughput-attestation-batch",
        source_id="throughput-attestation-source",
    )
    bundle = load_baseline_replay_bundle(output_root / "bundle.json")
    return verified, bundle


def _registry_for_verified(tmp_path: Path, verified, bundle) -> ResearchRegistry:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=verified.interval.end_ms,
        source_id="authoritative-v4-test-inventory",
    )
    registry.create_candidate(
        ResearchCandidateManifest(
            candidate_id=CANDIDATE_ID,
            family_id="throughput-attestation-family",
            parent_candidate_id=None,
            ancestor_candidate_ids=(),
            config_digest=bundle.replay_config.config_digest,
            code_revision=verified.code_revision,
            execution_config_json='{"mode":"paper"}',
            risk_config_json='{"risk_per_trade":"0.0025"}',
            state=ResearchCandidateState.DRAFT,
            first_observation_ms=None,
            last_observation_ms=None,
            source_provenance_ids=(),
            local_touched_intervals=(),
            effective_touched_intervals=(),
            performance_report_ids=(),
        )
    )
    registry.record_batch(
        candidate_id=CANDIDATE_ID,
        batch_id=verified.batch_id,
        source_id=verified.source_id,
        replay_run_id=verified.replay_run_id,
        interval=verified.interval,
    )
    return registry


def test_verified_throughput_is_persisted_in_batch_attestation(tmp_path: Path) -> None:
    verified, bundle = _verified_batch(tmp_path / "artifact")
    assert verified.decision_throughput is not None

    registry = _registry_for_verified(tmp_path, verified, bundle)
    try:
        attest_verified_research_batch(
            registry.connection,
            candidate_id=CANDIDATE_ID,
            verified=verified,
        )

        row = registry.connection.execute(
            """
            SELECT decision_throughput_json
            FROM research_batch_attestations
            WHERE batch_id = ?
            """,
            (verified.batch_id,),
        ).fetchone()
        assert row is not None
        assert json.loads(str(row["decision_throughput_json"])) == verified.decision_throughput

        loaded = load_candidate_attested_decision_throughput(
            registry.connection,
            candidate_id=CANDIDATE_ID,
        )
    finally:
        registry.close()

    assert loaded == {verified.batch_id: verified.decision_throughput}


def test_batch_attestation_schema_migrates_legacy_rows_without_loss(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.connection.execute(
            """
            CREATE TABLE research_batch_attestations (
                batch_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                source_digest TEXT NOT NULL,
                manifest_id TEXT NOT NULL,
                result_digest TEXT NOT NULL,
                sample_digest TEXT NOT NULL,
                sample_identities_json TEXT NOT NULL,
                planned_risk_fractions_json TEXT NOT NULL,
                operational_failure INTEGER NOT NULL,
                hard_risk_failure INTEGER NOT NULL,
                health_reason_codes_json TEXT NOT NULL
            )
            """
        )
        registry.connection.execute(
            """
            INSERT INTO research_batch_attestations (
                batch_id, candidate_id, source_digest, manifest_id, result_digest,
                sample_digest, sample_identities_json, planned_risk_fractions_json,
                operational_failure, hard_risk_failure, health_reason_codes_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-batch",
                "legacy-candidate",
                "a" * 64,
                "legacy-manifest",
                "b" * 64,
                "c" * 64,
                "[]",
                "[]",
                0,
                0,
                "[]",
            ),
        )
        registry.connection.commit()

        ensure_batch_attestation_schema(registry.connection)

        columns = {
            str(row["name"])
            for row in registry.connection.execute(
                "PRAGMA table_info(research_batch_attestations)"
            ).fetchall()
        }
        row = registry.connection.execute(
            """
            SELECT candidate_id, decision_throughput_json
            FROM research_batch_attestations
            WHERE batch_id = 'legacy-batch'
            """
        ).fetchone()
    finally:
        registry.close()

    assert "decision_throughput_json" in columns
    assert row is not None
    assert str(row["candidate_id"]) == "legacy-candidate"
    assert row["decision_throughput_json"] is None


def test_batch_attestation_rejects_changed_decision_throughput(tmp_path: Path) -> None:
    verified, bundle = _verified_batch(tmp_path / "artifact")
    assert verified.decision_throughput is not None
    registry = _registry_for_verified(tmp_path, verified, bundle)
    try:
        attest_verified_research_batch(
            registry.connection,
            candidate_id=CANDIDATE_ID,
            verified=verified,
        )
        changed_payload = dict(verified.decision_throughput)
        changed_payload["new_exposure_cutoff_ms"] = (
            int(changed_payload["new_exposure_cutoff_ms"]) + 1
        )
        changed = replace(verified, decision_throughput=changed_payload)

        with pytest.raises(
            ResearchRegistryError,
            match="different authoritative attestation",
        ):
            attest_verified_research_batch(
                registry.connection,
                candidate_id=CANDIDATE_ID,
                verified=changed,
            )
    finally:
        registry.close()
