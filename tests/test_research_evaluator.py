from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pytest import raises

from cocomelon.domain.strategy import Direction
from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    ResearchCheckpointState,
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
RISK_CONFIG = '{"risk_per_trade":"0.0025","stops_required":true}'
V4_TEST_SOURCE = "authoritative-v4-test-inventory"


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="research-r1-candidate",
        family_id="family-research",
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


def _mark_v4_complete(registry: ResearchRegistry, through_ms: int = 20 * DAY_MS) -> None:
    registry.mark_v4_registry_complete_through(
        through_ms=through_ms,
        source_id=V4_TEST_SOURCE,
    )


def test_research_report_exposes_full_touched_economics_and_provenance(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    _mark_v4_complete(registry)
    candidate = _candidate()
    registry.create_candidate(candidate)
    artifact = write_research_artifact(
        tmp_path / "artifact",
        batch_id="batch-1",
        source_id="research-source-1",
        replay_run_id="research-replay-1",
        start_ms=DAY_MS,
        end_ms=4 * DAY_MS,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 20_000,
                net_r=Decimal("0.5"),
                market="BTC",
                direction=Direction.LONG,
                reason_codes=("MAX_HOLD_EXPIRED",),
            ),
            ArtifactTradeSpec(
                closed_at_ms=2 * DAY_MS + 20_000,
                net_r=Decimal("-0.2"),
                market="BTC",
                direction=Direction.SHORT,
                reason_codes=("MAX_HOLD_EXPIRED",),
            ),
            ArtifactTradeSpec(
                closed_at_ms=3 * DAY_MS + 20_000,
                net_r=Decimal("0.4"),
                market="ETH",
                direction=Direction.LONG,
                reason_codes=("MAX_HOLD_EXPIRED",),
            ),
        ),
    )

    report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate.candidate_id,
        artifact_batches=(artifact,),
    )

    assert report.label == "TOUCHED / NON-PROMOTIONAL"
    assert report.candidate_id == candidate.candidate_id
    assert report.family_id == candidate.family_id
    assert report.config_digest == candidate.config_digest
    assert report.code_revision == candidate.code_revision
    assert report.execution_config_json == EXECUTION_CONFIG
    assert report.risk_config_json == RISK_CONFIG
    assert report.closed_trade_count == 3
    assert report.closed_trade_days == 3
    assert report.net_pnl == Decimal("17.5")
    assert report.mean_net_r == Decimal("0.2333333333333333333333333333")
    assert report.total_fees == Decimal("0")
    assert report.funding_cash_pnl == Decimal("0")
    assert report.total_slippage_amount == Decimal("0")
    assert report.max_realized_planned_risk_utilization == Decimal("1")
    assert report.long_count == 2
    assert report.short_count == 1
    assert report.market_trade_counts == (("BTC", 2), ("ETH", 1))
    assert report.exit_reason_counts == (("MAX_HOLD_EXPIRED", 3),)
    assert report.checkpoint_state is ResearchCheckpointState.INSUFFICIENT_TRADES
    assert report.posterior_probability_positive is None
    assert registry.effective_touched_intervals(candidate.candidate_id) == (
        TimeInterval(DAY_MS, 4 * DAY_MS),
    )

    loaded = registry.load_candidate(candidate.candidate_id)
    assert loaded.first_observation_ms == DAY_MS
    assert loaded.last_observation_ms == 4 * DAY_MS
    assert loaded.source_provenance_ids == ("research-source-1",)
    assert loaded.performance_report_ids == (report.report_id,)
    registry.close()


def test_v4_overlap_rejects_candidate_before_research_report_is_released(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    _mark_v4_complete(registry)
    candidate = _candidate()
    registry.create_candidate(candidate)
    registry.record_v4_interval(
        run_id="v4-diagnostic-run",
        interval=TimeInterval(DAY_MS, 2 * DAY_MS),
        disposition="diagnostic_failure",
    )
    artifact = write_research_artifact(
        tmp_path / "overlap-artifact",
        batch_id="batch-overlap",
        source_id="research-source-overlap",
        replay_run_id="research-replay-overlap",
        start_ms=DAY_MS + 1,
        end_ms=3 * DAY_MS,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 20_000,
                net_r=Decimal("0.5"),
            ),
        ),
    )

    with raises(ResearchContaminationError, match="v4-diagnostic-run"):
        evaluate_research_checkpoint(
            registry=registry,
            candidate_id=candidate.candidate_id,
            artifact_batches=(artifact,),
        )

    assert (
        registry.load_candidate(candidate.candidate_id).state
        is ResearchCandidateState.REJECTED_CONTAMINATION
    )
    assert registry.effective_touched_intervals(candidate.candidate_id) == ()
    registry.close()


def test_later_checkpoint_includes_all_prior_candidate_observations(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    _mark_v4_complete(registry)
    candidate = _candidate()
    registry.create_candidate(candidate)
    first_artifact = write_research_artifact(
        tmp_path / "losses",
        batch_id="batch-losses",
        source_id="source-losses",
        replay_run_id="replay-losses",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
        trades=tuple(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 20_000 + index * 2_000,
                net_r=Decimal("-0.1"),
            )
            for index in range(5)
        ),
    )
    first_report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate.candidate_id,
        artifact_batches=(first_artifact,),
    )
    assert first_report.closed_trade_count == 5
    assert first_report.net_pnl == Decimal("-12.5")

    second_artifact = write_research_artifact(
        tmp_path / "winners",
        batch_id="batch-winners",
        source_id="source-winners",
        replay_run_id="replay-winners",
        start_ms=2 * DAY_MS,
        end_ms=10 * DAY_MS,
        trades=tuple(
            ArtifactTradeSpec(
                closed_at_ms=(2 + (index % 7)) * DAY_MS + 20_000 + index * 2_000,
                net_r=Decimal("0.1"),
                market="ETH",
            )
            for index in range(40)
        ),
    )
    second_report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate.candidate_id,
        artifact_batches=(second_artifact,),
    )

    assert second_report.closed_trade_count == 45
    assert second_report.net_pnl == Decimal("87.5")
    assert second_report.batch_ids == ("batch-losses", "batch-winners")
    assert second_report.source_ids == ("source-losses", "source-winners")
    registry.close()


def test_exact_artifact_replay_is_idempotent(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    _mark_v4_complete(registry)
    candidate = _candidate()
    registry.create_candidate(candidate)
    artifact = write_research_artifact(
        tmp_path / "idempotent",
        batch_id="batch-idempotent",
        source_id="source-idempotent",
        replay_run_id="replay-idempotent",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 20_000,
                net_r=Decimal("0.1"),
            ),
        ),
    )

    first_report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate.candidate_id,
        artifact_batches=(artifact,),
    )
    second_report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate.candidate_id,
        artifact_batches=(artifact,),
    )

    assert first_report.report_id == second_report.report_id
    assert second_report.closed_trade_count == 1
    assert second_report.net_pnl == Decimal("2.5")
    registry.close()


def test_existing_batch_cannot_be_rewritten_with_new_economics(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    _mark_v4_complete(registry)
    candidate = _candidate()
    registry.create_candidate(candidate)
    original = write_research_artifact(
        tmp_path / "original",
        batch_id="batch-conflict",
        source_id="source-conflict",
        replay_run_id="replay-conflict",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 20_000,
                net_r=Decimal("0.1"),
            ),
        ),
    )
    rewritten = write_research_artifact(
        tmp_path / "rewritten",
        batch_id="batch-conflict",
        source_id="source-conflict",
        replay_run_id="replay-conflict",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 20_000,
                net_r=Decimal("0.9"),
            ),
        ),
    )

    evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate.candidate_id,
        artifact_batches=(original,),
    )
    with raises(ResearchRegistryError, match="seal|attestation"):
        evaluate_research_checkpoint(
            registry=registry,
            candidate_id=candidate.candidate_id,
            artifact_batches=(rewritten,),
        )
    registry.close()
