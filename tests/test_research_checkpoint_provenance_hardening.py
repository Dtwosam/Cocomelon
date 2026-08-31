from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from pytest import raises

from cocomelon.research.artifact import verify_research_batch_artifact
from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

DAY_MS = 86_400_000
EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"risk_per_trade":"0.0025","stops_required":true}'


def _candidate(candidate_id: str = "provenance-r1") -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id="provenance-family",
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


def _content_id(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_trade_observation_persists_canonical_sample_identity_and_provenance(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=3 * DAY_MS,
        source_id="authoritative-v4-inventory",
    )
    registry.create_candidate(_candidate())
    artifact = write_research_artifact(
        tmp_path / "artifact",
        batch_id="provenance-batch-1",
        source_id="provenance-source-1",
        replay_run_id="provenance-replay-1",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 16_000,
                net_r=Decimal("0.1"),
                score=Decimal("73"),
                lead_strategy="trend",
                reason_codes=("MAX_HOLD_EXPIRED",),
            ),
        ),
    )
    verified = verify_research_batch_artifact(
        artifact.artifact_root,
        batch_id=artifact.batch_id,
        source_id=artifact.source_id,
    )
    sample = verified.samples[0]

    evaluate_research_checkpoint(
        registry=registry,
        candidate_id="provenance-r1",
        artifact_batches=(artifact,),
    )

    row = registry.connection.execute(
        "SELECT payload_json FROM research_trade_observations WHERE candidate_id = ?",
        ("provenance-r1",),
    ).fetchone()
    assert row is not None
    payload = json.loads(str(row["payload_json"]))
    assert payload["sample_id"] == sample.sample_id
    assert payload["trade_id"] == sample.trade_id
    assert payload["batch_id"] == artifact.batch_id
    assert payload["source_id"] == artifact.source_id
    assert payload["replay_run_id"] == sample.replay_run_id
    assert payload["strategy_decision_id"] == sample.strategy_decision_id
    assert payload["evidence_class"] == sample.evidence_class.value
    assert payload["lead_strategy"] == sample.lead_strategy
    assert payload["trend_regime"] == sample.trend_regime.value
    assert payload["volatility_regime"] == sample.volatility_regime.value
    assert payload["score"] == str(sample.score)
    assert payload["gross_realized_pnl"] == str(sample.gross_realized_pnl)
    assert payload["planned_risk_fraction"] == "0.0025"
    registry.close()


def test_zero_trade_batches_remain_in_cumulative_report_provenance(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=4 * DAY_MS,
        source_id="authoritative-v4-inventory",
    )
    registry.create_candidate(_candidate())
    first = write_research_artifact(
        tmp_path / "zero-1",
        batch_id="no-trade-batch-1",
        source_id="no-trade-source-1",
        replay_run_id="no-trade-replay-1",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
    )
    second = write_research_artifact(
        tmp_path / "zero-2",
        batch_id="no-trade-batch-2",
        source_id="no-trade-source-2",
        replay_run_id="no-trade-replay-2",
        start_ms=2 * DAY_MS,
        end_ms=3 * DAY_MS,
    )

    first_report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id="provenance-r1",
        artifact_batches=(first,),
    )
    second_report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id="provenance-r1",
        artifact_batches=(second,),
    )

    assert first_report.batch_ids == ("no-trade-batch-1",)
    assert first_report.source_ids == ("no-trade-source-1",)
    assert second_report.batch_ids == ("no-trade-batch-1", "no-trade-batch-2")
    assert second_report.source_ids == ("no-trade-source-1", "no-trade-source-2")
    assert second_report.report_id != first_report.report_id
    registry.close()


def test_checkpoint_report_authenticates_attested_batch_provenance(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=3 * DAY_MS,
        source_id="authoritative-v4-inventory",
    )
    registry.create_candidate(_candidate())
    artifact = write_research_artifact(
        tmp_path / "auth-zero",
        batch_id="auth-no-trade-batch",
        source_id="auth-no-trade-source",
        replay_run_id="auth-no-trade-replay",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
    )
    report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id="provenance-r1",
        artifact_batches=(artifact,),
    )
    forged = report.to_dict()
    forged.pop("report_id")
    forged["batch_ids"] = []
    forged["source_ids"] = []
    forged_id = _content_id(forged)
    registry.record_performance_report(
        candidate_id="provenance-r1",
        report_id=forged_id,
        payload=forged,
    )

    with raises(ResearchRegistryError, match="batch_ids|provenance"):
        registry.apply_checkpoint_state(
            "provenance-r1",
            ResearchCandidateState.RESEARCHING,
            report_id=forged_id,
        )
    registry.close()