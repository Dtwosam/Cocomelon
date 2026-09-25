from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research import learning_cycle
from cocomelon.research.learning_experiment import LearningExperimentResult
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _record(index: int) -> LearningEvidenceRecord:
    opened = index * 10_000
    closed = opened + 1_000
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id=f"paper-{index}",
        source_evidence_class="microstructure",
        candidate_id="scheduled-research-root",
        candidate_spec_id=None,
        campaign_id=None,
        market=MarketId("", "HYPE"),
        direction=Direction.LONG,
        opened_at_ms=opened,
        closed_at_ms=closed,
        feature_snapshot_id=f"feature-{index}",
        research_eligible_at_ms=closed,
        gross_realized_pnl=Decimal("10"),
        entry_fees=Decimal("0.5"),
        exit_fees=Decimal("0.5"),
        funding_cash_pnl=Decimal("0"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.001"),
        net_pnl=Decimal("9"),
        net_r=Decimal("0.36"),
    )


def _ledger(root: Path, count: int) -> LearningEvidenceLedger:
    ledger = LearningEvidenceLedger(root)
    for index in range(1, count + 1):
        ledger.record(_record(index))
    return ledger


def _ready_report(
    ledger: LearningEvidenceLedger,
    *,
    feature_registry: tuple[str, ...],
):
    return learning_cycle.LearningReadinessReport(
        as_of_ms=9_999_999_999,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=feature_registry,
        ledger_state_digest=ledger.state_digest,
        feature_store_state_digest="f" * 64,
        eligible_record_ids=tuple(
            sorted(record.record_id for record in ledger.iter_records())
        ),
        quarantined_record_ids=(),
        feature_complete_record_ids=tuple(
            sorted(record.record_id for record in ledger.iter_records())
        ),
        blocked_records=(),
    )


def test_learning_cycle_protocol_reuses_conservative_historical_gates() -> None:
    assert learning_cycle.MIN_TRAIN_ROWS == 200
    assert learning_cycle.VALIDATION_ROWS == 20
    assert learning_cycle.STABILITY_BLOCKS == 4
    assert learning_cycle.MIN_BLOCK_TRADES == 5
    assert learning_cycle.MIN_VALIDATION_TRADES == 20
    assert learning_cycle.TREE_MODEL_CONFIG["max_leaf_nodes"] == 7
    assert learning_cycle.TREE_MODEL_CONFIG["min_samples_leaf"] == 100
    assert learning_cycle.TREE_MODEL_CONFIG["learning_rate"] == "0.05"
    assert learning_cycle.TREE_MODEL_CONFIG["max_iter"] == 100
    assert learning_cycle.TREE_MODEL_CONFIG["l2_regularization"] == "1"


def test_learning_cycle_stays_not_ready_before_temporal_capacity(
    tmp_path,
    monkeypatch,
) -> None:
    ledger = _ledger(tmp_path / "learning", 219)

    def fake_readiness(*_args, feature_registry, **_kwargs):
        return _ready_report(ledger, feature_registry=feature_registry)

    monkeypatch.setattr(learning_cycle, "evaluate_learning_readiness", fake_readiness)

    result = learning_cycle.run_learning_cycle(
        learning_root=tmp_path / "learning",
        feature_store_dir=tmp_path / "features",
        output_root=tmp_path / "cycle",
        as_of_ms=9_999_999_999,
        implementation_commit_sha="a" * 40,
        expected_learning_state_digest=ledger.state_digest,
        expected_feature_state_digest="f" * 64,
    )

    assert result.status == "not_ready"
    assert result.eligible_record_count == 219
    assert result.settled_train_record_count == 199
    assert result.validation_record_count == 20
    assert result.baseline_experiment_id is None
    assert result.tree_experiment_id is None
    assert result.research_only is True
    assert result.promotion_eligible is False
    assert result.execution_ready is False


def test_learning_cycle_runs_both_research_experiments_when_ready(
    tmp_path,
    monkeypatch,
) -> None:
    ledger = _ledger(tmp_path / "learning", 220)
    calls: list[dict[str, object]] = []

    def fake_readiness(*_args, feature_registry, **_kwargs):
        return _ready_report(ledger, feature_registry=feature_registry)

    def fake_experiment(**kwargs):
        calls.append(kwargs)
        family = str(kwargs["model_family"])
        suffix = "1" if family == "categorical_group_mean_v1" else "2"
        return LearningExperimentResult(
            output_root=Path(kwargs["output_root"]),
            experiment_id=suffix * 64,
            dataset_id="3" * 64,
            dataset_lineage_id="4" * 64,
            run_id="5" * 64,
            training_set_id="6" * 64,
            training_bundle_id="7" * 64,
            evaluation_id="8" * 64,
            model_family=family,
            qualifies_development=(suffix == "1"),
        )

    monkeypatch.setattr(learning_cycle, "evaluate_learning_readiness", fake_readiness)
    monkeypatch.setattr(learning_cycle, "run_learning_experiment", fake_experiment)
    monkeypatch.setattr(
        learning_cycle,
        "verify_learning_experiment",
        lambda *, output_root: next(
            result
            for result in (
                LearningExperimentResult(
                    output_root=tmp_path / "cycle" / "baseline",
                    experiment_id="1" * 64,
                    dataset_id="3" * 64,
                    dataset_lineage_id="4" * 64,
                    run_id="5" * 64,
                    training_set_id="6" * 64,
                    training_bundle_id="7" * 64,
                    evaluation_id="8" * 64,
                    model_family="categorical_group_mean_v1",
                    qualifies_development=True,
                ),
                LearningExperimentResult(
                    output_root=tmp_path / "cycle" / "tree",
                    experiment_id="2" * 64,
                    dataset_id="3" * 64,
                    dataset_lineage_id="4" * 64,
                    run_id="5" * 64,
                    training_set_id="6" * 64,
                    training_bundle_id="7" * 64,
                    evaluation_id="8" * 64,
                    model_family="fixed_shallow_tree",
                    qualifies_development=False,
                ),
            )
            if result.output_root == output_root
        ),
    )

    result = learning_cycle.run_learning_cycle(
        learning_root=tmp_path / "learning",
        feature_store_dir=tmp_path / "features",
        output_root=tmp_path / "cycle",
        as_of_ms=9_999_999_999,
        implementation_commit_sha="a" * 40,
        expected_learning_state_digest=ledger.state_digest,
        expected_feature_state_digest="f" * 64,
    )

    assert result.status == "completed"
    assert result.settled_train_record_count == 200
    assert result.validation_record_count == 20
    assert result.baseline_experiment_id == "1" * 64
    assert result.tree_experiment_id == "2" * 64
    assert result.baseline_qualifies_development is True
    assert result.tree_qualifies_development is False
    assert len(calls) == 2
    assert calls[0]["feature_registry"] == learning_cycle.BASELINE_FEATURES
    assert calls[1]["feature_registry"] == learning_cycle.TREE_FEATURES


def test_learning_cycle_rejects_stale_learning_state_digest(
    tmp_path,
    monkeypatch,
) -> None:
    ledger = _ledger(tmp_path / "learning", 220)

    def fake_readiness(*_args, feature_registry, **_kwargs):
        return _ready_report(ledger, feature_registry=feature_registry)

    monkeypatch.setattr(learning_cycle, "evaluate_learning_readiness", fake_readiness)

    with pytest.raises(
        learning_cycle.LearningCycleError,
        match="LEARNING_STATE_DIGEST_MISMATCH",
    ):
        learning_cycle.run_learning_cycle(
            learning_root=tmp_path / "learning",
            feature_store_dir=tmp_path / "features",
            output_root=tmp_path / "cycle",
            as_of_ms=9_999_999_999,
            implementation_commit_sha="a" * 40,
            expected_learning_state_digest="0" * 64,
            expected_feature_state_digest="f" * 64,
        )
