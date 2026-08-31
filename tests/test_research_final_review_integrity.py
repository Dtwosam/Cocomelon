from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.artifact import ResearchArtifactError, verify_research_batch_artifact
from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.observations import load_trade_observations
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

DAY_MS = 86_400_000
EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"risk_per_trade":"0.0025","stops_required":true}'


def _candidate(
    candidate_id: str,
    *,
    code_revision: str = "1" * 40,
    config_digest: str = "a" * 64,
) -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id="final-review-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest=config_digest,
        code_revision=code_revision,
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


def _registry(tmp_path: Path, candidate: ResearchCandidateManifest) -> ResearchRegistry:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=4 * DAY_MS,
        source_id="authoritative-v4-inventory",
    )
    registry.create_candidate(candidate)
    return registry


def test_checkpoint_rejects_artifact_from_different_candidate_code_or_config(
    tmp_path: Path,
) -> None:
    candidate = _candidate("identity-candidate", config_digest="d" * 64)
    registry = _registry(tmp_path, candidate)
    artifact = write_research_artifact(
        tmp_path / "artifact",
        batch_id="identity-batch",
        source_id="identity-source",
        replay_run_id="identity-replay",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 20_000,
                net_r=Decimal("0.2"),
            ),
        ),
    )
    try:
        with pytest.raises(ResearchRegistryError, match="code|config|candidate"):
            evaluate_research_checkpoint(
                registry=registry,
                candidate_id=candidate.candidate_id,
                artifact_batches=(artifact,),
            )
    finally:
        registry.close()


def test_artifact_verifier_rejects_replay_without_genuine_mainnet_recording_provenance(
    tmp_path: Path,
) -> None:
    artifact = write_research_artifact(
        tmp_path / "artifact",
        batch_id="mainnet-batch",
        source_id="mainnet-source",
        replay_run_id="mainnet-replay",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
        trades=(),
    )
    (artifact.artifact_root.parent / "recording" / "recording-session.json").unlink()

    with pytest.raises(ResearchArtifactError, match="mainnet|recording|source"):
        verify_research_batch_artifact(
            artifact.artifact_root,
            batch_id=artifact.batch_id,
            source_id=artifact.source_id,
        )


def test_loading_observations_requires_exact_attested_sample_set(tmp_path: Path) -> None:
    candidate = _candidate("complete-set-candidate")
    registry = _registry(tmp_path, candidate)
    artifact = write_research_artifact(
        tmp_path / "artifact",
        batch_id="complete-set-batch",
        source_id="complete-set-source",
        replay_run_id="complete-set-replay",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 20_000,
                net_r=Decimal("0.2"),
            ),
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 30_000,
                net_r=Decimal("-0.1"),
            ),
        ),
    )
    try:
        evaluate_research_checkpoint(
            registry=registry,
            candidate_id=candidate.candidate_id,
            artifact_batches=(artifact,),
        )
        row = registry.connection.execute(
            """
            SELECT trade_id
            FROM research_trade_observations
            WHERE candidate_id = ?
            ORDER BY trade_id
            LIMIT 1
            """,
            (candidate.candidate_id,),
        ).fetchone()
        assert row is not None
        registry.connection.execute(
            "DELETE FROM research_trade_observations WHERE candidate_id = ? AND trade_id = ?",
            (candidate.candidate_id, str(row["trade_id"])),
        )
        registry.connection.commit()

        with pytest.raises(ResearchRegistryError, match="attested|complete|sample"):
            load_trade_observations(
                registry.connection,
                candidate_id=candidate.candidate_id,
            )
    finally:
        registry.close()


def test_checkpoint_auth_rejects_forged_non_state_economics(tmp_path: Path) -> None:
    candidate = _candidate("full-report-candidate")
    registry = _registry(tmp_path, candidate)
    artifact = write_research_artifact(
        tmp_path / "artifact",
        batch_id="full-report-batch",
        source_id="full-report-source",
        replay_run_id="full-report-replay",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 20_000,
                net_r=Decimal("0.2"),
            ),
        ),
    )
    try:
        report = evaluate_research_checkpoint(
            registry=registry,
            candidate_id=candidate.candidate_id,
            artifact_batches=(artifact,),
        )
        forged = report.to_dict()
        forged.pop("report_id")
        forged["net_pnl"] = "999999"
        forged["mean_net_r"] = "999"
        forged["total_fees"] = "123"
        forged_id = _report_id(forged)
        registry.record_performance_report(
            candidate_id=candidate.candidate_id,
            report_id=forged_id,
            payload=forged,
        )

        with pytest.raises(ResearchRegistryError, match="report|economics|immutable observations"):
            registry.apply_checkpoint_state(
                candidate.candidate_id,
                report.candidate_state,
                report_id=forged_id,
            )
    finally:
        registry.close()