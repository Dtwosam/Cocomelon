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
from cocomelon.domain.replay import EvidenceClass
from cocomelon.evaluation.engine import build_promotion_preview
from cocomelon.evaluation.metrics import compute_performance_metrics
from cocomelon.evaluation.store import EvaluationFactStore


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


def _policy_payload() -> dict[str, object]:
    policy = EvaluationPolicy()
    return {
        "policy_version": policy.policy_version,
        "min_oos_trades": policy.min_oos_trades,
        "min_oos_days": policy.min_oos_days,
        "min_walkforward_windows": policy.min_walkforward_windows,
        "min_trades_per_walkforward_window": policy.min_trades_per_walkforward_window,
        "min_score_bucket_trades": policy.min_score_bucket_trades,
        "positive_walkforward_fraction": str(policy.positive_walkforward_fraction),
        "bootstrap_confidence": str(policy.bootstrap_confidence),
        "bootstrap_block_days": policy.bootstrap_block_days,
        "bootstrap_resamples": policy.bootstrap_resamples,
        "split_embargo_ms": policy.split_embargo_ms,
        "no_trade_horizons_ms": list(policy.no_trade_horizons_ms),
    }


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
