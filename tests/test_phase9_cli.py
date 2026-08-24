from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cocomelon import cli
from cocomelon.domain.evaluation import (
    EdgeEvidenceStatus,
    EvaluationDatasetManifest,
    EvaluationPolicy,
    EvaluationResult,
    OOSStatus,
    ReplayEvaluationSource,
)
from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    ReplayResult,
    SourceSegment,
)
from cocomelon.evaluation.engine import build_promotion_preview
from cocomelon.evaluation.metrics import compute_performance_metrics
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore


def _empty_result() -> EvaluationResult:
    metrics = compute_performance_metrics(())
    return EvaluationResult(
        dataset_manifest_id="dataset-1",
        split_manifest_id="split-1",
        candidate_set_id="candidates-1",
        policy_id="policy-1",
        oos_status=OOSStatus.UNTOUCHED,
        train_metrics=metrics,
        validation_metrics=metrics,
        test_metrics=metrics,
        mean_net_r_confidence_interval=None,
        walkforward_results=(),
        slice_reports=(),
        sensitivity_report_ids=(),
        no_trade_report_ids=(),
        edge_status=EdgeEvidenceStatus.INSUFFICIENT_EVIDENCE,
        promotion_preview=build_promotion_preview(metrics, invariant_health_pass=None),
        included_sample_count=0,
        excluded_sample_count=0,
        reason_codes=("INSUFFICIENT_EVIDENCE",),
    )


def _dataset() -> EvaluationDatasetManifest:
    return EvaluationDatasetManifest(
        sources=(
            ReplayEvaluationSource(
                run_id="run-1",
                manifest_id="manifest-1",
                result_digest="a" * 64,
                evidence_class=EvidenceClass.MICROSTRUCTURE,
                start_ms=0,
                end_ms=100_000,
                data_complete=True,
            ),
        ),
        trade_ids=(),
        decision_fact_ids=(),
        equity_fact_ids=(),
        start_ms=0,
        end_ms=100_000,
        code_revision="phase9-cli-test",
        data_complete=True,
        gap_refs=(),
        mixed_evidence_diagnostic=False,
    )


def _policy_payload(policy: EvaluationPolicy | None = None) -> dict[str, object]:
    rules = policy or EvaluationPolicy()
    return {
        "policy_version": rules.policy_version,
        "min_oos_trades": rules.min_oos_trades,
        "min_oos_days": rules.min_oos_days,
        "min_walkforward_windows": rules.min_walkforward_windows,
        "min_trades_per_walkforward_window": rules.min_trades_per_walkforward_window,
        "min_score_bucket_trades": rules.min_score_bucket_trades,
        "positive_walkforward_fraction": str(rules.positive_walkforward_fraction),
        "bootstrap_confidence": str(rules.bootstrap_confidence),
        "bootstrap_block_days": rules.bootstrap_block_days,
        "bootstrap_resamples": rules.bootstrap_resamples,
        "split_embargo_ms": rules.split_embargo_ms,
        "no_trade_horizons_ms": list(rules.no_trade_horizons_ms),
    }


def _persist_empty_replay(journal_path: Path) -> ReplayManifest:
    manifest = ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=0,
        end_ms=100_000,
        segments=(
            SourceSegment(
                relative_path="events/empty.jsonl",
                partition="events/2026-08-24/l2book/SOL",
                sha256="a" * 64,
                byte_count=1,
                row_count=1,
                schema_version=1,
                first_available_at_ms=0,
                last_available_at_ms=100_000,
            ),
        ),
        gap_refs=(),
        code_revision="phase9-cli-source",
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="native-taker-v1",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )
    journal = JournalStore(journal_path)
    journal.record_manifest(manifest)
    journal.begin_run(manifest.manifest_id, "run-a")
    journal.finish_run(
        ReplayResult(
            manifest_id=manifest.manifest_id,
            run_id="run-a",
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            start_ms=0,
            end_ms=100_000,
            processed_events=1,
            processed_gaps=0,
            strategy_decisions=0,
            risk_approvals=0,
            risk_rejections=0,
            execution_attempts=0,
            fills=0,
            opened_positions=0,
            closed_positions=0,
            journal_observations=0,
            closed_trade_ids=(),
            final_account_state_id="account-final",
            data_complete=True,
        )
    )
    journal.close()
    return manifest


def test_phase9_parser_requires_explicit_local_inputs() -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["freeze-evaluation-dataset"])
    with pytest.raises(SystemExit):
        parser.parse_args(["freeze-evaluation-splits"])
    with pytest.raises(SystemExit):
        parser.parse_args(["evaluate"])
    with pytest.raises(SystemExit):
        parser.parse_args(["inspect-evaluation"])

    dataset = parser.parse_args(
        [
            "freeze-evaluation-dataset",
            "--journal",
            "journal.sqlite3",
            "--facts",
            "facts.sqlite3",
            "--run-id",
            "run-1",
            "--run-id",
            "run-2",
        ]
    )
    assert dataset.run_id == ["run-1", "run-2"]

    evaluate = parser.parse_args(
        [
            "evaluate",
            "--journal",
            "journal.sqlite3",
            "--facts",
            "facts.sqlite3",
            "--dataset-id",
            "dataset-1",
            "--split-id",
            "split-1",
            "--candidate-spec",
            "candidate.json",
            "--walkforward-spec",
            "walkforward.json",
        ]
    )
    assert evaluate.dataset_id == "dataset-1"
    assert evaluate.split_id == "split-1"

    for forbidden in ("--testnet", "--live", "--optimize", "--api-url", "--ws-url"):
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "inspect-evaluation",
                    "--facts",
                    "facts.sqlite3",
                    "--evaluation-id",
                    "eval-1",
                    forbidden,
                ]
            )


def test_freeze_evaluation_dataset_uses_existing_replay_lineage(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.sqlite3"
    facts_path = tmp_path / "facts.sqlite3"
    source = _persist_empty_replay(journal_path)

    payload = cli.freeze_evaluation_dataset_payload(
        journal_path,
        facts_path,
        ("run-a",),
    )

    assert payload["dataset_manifest_id"]
    assert payload["source_run_ids"] == ["run-a"]
    assert payload["code_revision"] == source.code_revision
    assert payload["trade_count"] == 0
    assert payload["excluded_trade_count"] == 0
    assert payload["network_access"] is False

    store = EvaluationFactStore(facts_path)
    assert store.load_dataset_manifest(str(payload["dataset_manifest_id"])) is not None
    store.close()


def test_freeze_evaluation_splits_persists_canonical_split(tmp_path: Path) -> None:
    facts_path = tmp_path / "facts.sqlite3"
    store = EvaluationFactStore(facts_path)
    dataset = _dataset()
    store.record_dataset_manifest(dataset)
    store.close()

    spec = {
        "policy": _policy_payload(),
        "train": {"start_ms": 0, "end_ms": 60_000},
        "validation": {"start_ms": 60_000, "end_ms": 80_000},
        "test": {"start_ms": 80_000, "end_ms": 100_000},
    }
    spec_path = tmp_path / "split.json"
    spec_path.write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")

    payload = cli.freeze_evaluation_splits_payload(
        facts_path,
        dataset.manifest_id,
        spec_path,
    )

    assert payload["dataset_manifest_id"] == dataset.manifest_id
    assert payload["split_manifest_id"]
    assert payload["policy_id"] == EvaluationPolicy().policy_id
    assert payload["train"] == {"name": "train", "start_ms": 0, "end_ms": 60_000}
    assert payload["validation"]["name"] == "validation"
    assert payload["test"]["name"] == "test"
    assert payload["network_access"] is False

    reopened = EvaluationFactStore(facts_path)
    row = reopened.connection.execute(
        "SELECT payload_json FROM evaluation_split_manifests WHERE split_manifest_id = ?",
        (payload["split_manifest_id"],),
    ).fetchone()
    reopened.close()
    assert row is not None
    assert json.loads(str(row[0]))["policy_id"] == EvaluationPolicy().policy_id


def test_evaluate_command_runs_only_from_frozen_local_specs(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.sqlite3"
    facts_path = tmp_path / "facts.sqlite3"
    _persist_empty_replay(journal_path)
    dataset_payload = cli.freeze_evaluation_dataset_payload(
        journal_path,
        facts_path,
        ("run-a",),
    )
    dataset_id = str(dataset_payload["dataset_manifest_id"])
    policy = EvaluationPolicy(
        min_oos_trades=1,
        min_oos_days=1,
        min_walkforward_windows=1,
        min_trades_per_walkforward_window=1,
        min_score_bucket_trades=1,
        bootstrap_block_days=1,
        bootstrap_resamples=20,
        split_embargo_ms=0,
    )
    split_spec_path = tmp_path / "split.json"
    split_spec_path.write_text(
        json.dumps(
            {
                "policy": _policy_payload(policy),
                "train": {"start_ms": 0, "end_ms": 30_000},
                "validation": {"start_ms": 30_000, "end_ms": 60_000},
                "test": {"start_ms": 60_000, "end_ms": 100_000},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    split_payload = cli.freeze_evaluation_splits_payload(
        facts_path,
        dataset_id,
        split_spec_path,
    )
    candidate_spec = tmp_path / "candidate.json"
    candidate_spec.write_text(
        json.dumps(
            {
                "policy": _policy_payload(policy),
                "candidates": [
                    {
                        "name": "baseline",
                        "strategy_version": "phase5-v1",
                        "risk_version": "phase6-v1",
                        "execution_config_version": "phase7-v1",
                        "code_revision": "phase9-cli-source",
                        "config_digest": "c" * 64,
                    }
                ],
                "sensitivity_profile_ids": ["base", "combined_stress"],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    walkforward_spec = tmp_path / "walkforward.json"
    walkforward_spec.write_text(
        json.dumps(
            {
                "first_window_start_ms": 0,
                "development_duration_ms": 30_000,
                "validation_duration_ms": 30_000,
                "evaluation_duration_ms": 40_000,
                "step_ms": 40_000,
                "embargo_ms": 0,
                "expanding": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payload = cli.evaluate_payload(
        journal_path,
        facts_path,
        dataset_id,
        str(split_payload["split_manifest_id"]),
        candidate_spec,
        walkforward_spec,
    )

    assert payload["edge_status"] == "insufficient_evidence"
    assert payload["oos_status"] == "untouched"
    assert payload["test_trade_count"] == 0
    assert payload["promotion_preview"]["preview_only"] is True
    assert payload["network_access"] is False


def test_evaluation_summary_exposes_status_digest_counts_and_preview() -> None:
    result = _empty_result()

    payload = cli.evaluation_result_payload(result)

    assert payload["evaluation_id"] == result.evaluation_id
    assert payload["result_digest"] == result.result_digest
    assert payload["edge_status"] == "insufficient_evidence"
    assert payload["oos_status"] == "untouched"
    assert payload["test_trade_count"] == 0
    assert payload["included_sample_count"] == 0
    assert payload["excluded_sample_count"] == 0
    assert payload["promotion_preview"]["preview_only"] is True
    assert payload["network_access"] is False


def test_inspect_evaluation_is_read_only_and_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    facts_path = tmp_path / "facts.sqlite3"
    result = _empty_result()
    store = EvaluationFactStore(facts_path)
    store.record_evaluation_result(result)
    store.close()
    before = hashlib.sha256(facts_path.read_bytes()).hexdigest()

    def forbidden_settings() -> object:
        raise AssertionError("offline Phase 9 command must not load network settings")

    monkeypatch.setattr("cocomelon.cli.Settings.from_env", forbidden_settings)
    cli.main(
        [
            "inspect-evaluation",
            "--facts",
            str(facts_path),
            "--evaluation-id",
            result.evaluation_id,
        ]
    )

    output = json.loads(capsys.readouterr().out)
    after = hashlib.sha256(facts_path.read_bytes()).hexdigest()
    assert output["evaluation_id"] == result.evaluation_id
    assert output["result_digest"] == result.result_digest
    assert output["network_access"] is False
    assert after == before
