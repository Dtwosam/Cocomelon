from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType

import pytest

from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayResult, SourceSegment
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore


def _module() -> ModuleType:
    return importlib.import_module("cocomelon.evaluation.mainnet_evidence")


def _write_cohort(root: Path, *, complete: bool) -> tuple[Path, ReplayResult]:
    output = root / "output"
    recording = root / "recording"
    output.mkdir(parents=True)
    recording.mkdir(parents=True)
    revision = "a" * 40
    session_id = "b" * 64
    gap_refs = () if complete else ("gap:l2Book:SOL:1000:2000:recovered",)
    manifest = ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=1_000,
        end_ms=2_000,
        segments=(
            SourceSegment(
                relative_path="events/2026-08-24/l2book/SOL/segment-000001.jsonl",
                partition="events/2026-08-24/l2book/SOL",
                sha256="c" * 64,
                byte_count=100,
                row_count=10,
                schema_version=1,
                first_available_at_ms=1_000,
                last_available_at_ms=2_000,
            ),
        ),
        gap_refs=gap_refs,
        code_revision=revision,
        config_digest="d" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="native-taker-v1",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )
    result = ReplayResult(
        manifest_id=manifest.manifest_id,
        run_id="run-mainnet-a",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=manifest.start_ms,
        end_ms=manifest.end_ms,
        processed_events=10,
        processed_gaps=0 if complete else 1,
        strategy_decisions=1,
        risk_approvals=1,
        risk_rejections=0,
        execution_attempts=1,
        fills=1,
        opened_positions=1,
        closed_positions=0,
        journal_observations=0,
        closed_trade_ids=(),
        final_account_state_id="account-final",
        data_complete=complete,
    )
    journal = JournalStore(output / "journal.sqlite3")
    journal.record_manifest(manifest)
    journal.begin_run(manifest.manifest_id, result.run_id)
    journal.finish_run(result)
    journal.close()
    EvaluationFactStore(output / "facts.sqlite3").close()

    (recording / "recording-session.json").write_text(
        json.dumps(
            {
                "api_url": "https://api.hyperliquid.xyz",
                "ws_url": "wss://api.hyperliquid.xyz/ws",
                "recorder_code_revision": revision,
                "recording_config_digest": "e" * 64,
                "schema_version": 1,
                "selected": [],
                "selection_policy_id": "rankable-native-top-v1",
                "session_id": session_id,
                "started_at_ms": 1_000,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (output / "cohort-summary.json").write_text(
        json.dumps(
            {
                "checked_out_code_revision": revision,
                "closed_positions": 0,
                "closed_trade_count": 0,
                "data_complete": complete,
                "dataset_manifest_id": "dataset-diagnostic",
                "dataset_trade_count": 0,
                "economic_claim": "none",
                "evidence_kind": "genuine_public_hyperliquid_mainnet",
                "excluded_trade_count": 0,
                "execution_attempts": 1,
                "fills": 1,
                "final_equity": "10000",
                "opened_positions": 1,
                "recorded_duplicate_count": 0,
                "recorded_event_count": 10,
                "recorded_gap_count": 0 if complete else 1,
                "recording_session_id": session_id,
                "replay_result_digest": result.result_digest,
                "replay_run_id": result.run_id,
                "risk_approvals": 1,
                "risk_rejections": 0,
                "selected_markets": ["SOL"],
                "strategy_decisions": 1,
                "trigger_head_sha": "f" * 40,
                "validated_segment_count": 1,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (output / "record.json").write_text(
        json.dumps(
            {
                "anomaly_count": 0,
                "duplicate_count": 0,
                "duration_seconds": 1,
                "event_count": 10,
                "gap_count": 0 if complete else 1,
                "live_orders": False,
                "network_access": True,
                "reconnect_count": 0,
                "root": "evidence-cohort/recording",
                "selected_markets": ["SOL"],
                "session_id": session_id,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (output / "replay.json").write_text(
        json.dumps(
            {
                "bundle_id": "bundle-a",
                "closed_positions": 0,
                "closed_trade_ids": [],
                "data_complete": complete,
                "evidence_class": "microstructure",
                "execution": "evidence-cohort/output/execution.sqlite3",
                "execution_attempts": 1,
                "facts": "evidence-cohort/output/facts.sqlite3",
                "fills": 1,
                "final_account_state_id": "account-final",
                "final_equity": "10000",
                "journal": "evidence-cohort/output/journal.sqlite3",
                "live_orders": False,
                "manifest_id": manifest.manifest_id,
                "network_access": False,
                "opened_positions": 1,
                "result_digest": result.result_digest,
                "risk_approvals": 1,
                "risk_rejections": 0,
                "run_id": result.run_id,
                "strategy_decisions": 1,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (output / "freeze.json").write_text(
        json.dumps(
            {
                "bundle_id": "bundle-a",
                "code_revision": revision,
                "evidence_class": "microstructure",
                "live_orders": False,
                "manifest_id": manifest.manifest_id,
                "network_access": False,
                "out": "evidence-cohort/output/bundle.json",
                "recording_session_digest": session_id,
                "root": "evidence-cohort/recording",
                "source_set_digest": "1" * 64,
                "starting_cash": "10000",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (output / "bundle.json").write_text(
        json.dumps(
            {
                "bundle_id": "bundle-a",
                "manifest": {
                    "code_revision": revision,
                    "gap_refs": list(gap_refs),
                    "manifest_id": manifest.manifest_id,
                },
                "recording_session_digest": session_id,
                "replay_config": {},
                "schema_version": 1,
                "source_locator_bundle_id": "bundle-a",
                "source_root_relative": "../recording",
                "source_set_digest": "1" * 64,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (output / "workflow-head.txt").write_text(revision + "\n", encoding="utf-8")
    (output / "trigger-head.txt").write_text("f" * 40 + "\n", encoding="utf-8")
    return output, result


def test_mainnet_aggregation_rejects_incomplete_cohort_before_target_write(
    tmp_path: Path,
) -> None:
    module = _module()
    source, _ = _write_cohort(tmp_path / "artifact-a", complete=False)
    target = tmp_path / "aggregate"

    with pytest.raises(module.MainnetEvidenceError, match="complete"):
        module.aggregate_mainnet_evaluation_evidence(
            target / "journal.sqlite3",
            target / "facts.sqlite3",
            (source,),
        )

    assert not (target / "journal.sqlite3").exists()
    assert not (target / "facts.sqlite3").exists()
    assert not (target / "mainnet-attestation.json").exists()


def test_complete_mainnet_cohort_creates_attestation_without_mutating_source(
    tmp_path: Path,
) -> None:
    import hashlib

    module = _module()
    source, replay_result = _write_cohort(tmp_path / "artifact-a", complete=True)
    target = tmp_path / "aggregate"
    source_hashes = {
        name: hashlib.sha256((source / name).read_bytes()).hexdigest()
        for name in ("journal.sqlite3", "facts.sqlite3")
    }

    result = module.aggregate_mainnet_evaluation_evidence(
        target / "journal.sqlite3",
        target / "facts.sqlite3",
        (source,),
    )

    attestation = json.loads((target / "mainnet-attestation.json").read_text())
    assert result.run_ids == (replay_result.run_id,)
    assert attestation["evidence_kind"] == "genuine_public_hyperliquid_mainnet"
    assert attestation["code_revision"] == "a" * 40
    assert attestation["run_ids"] == [replay_result.run_id]
    assert attestation["real_evidence_eligible"] is True
    assert len(attestation["attestation_id"]) == 64
    assert attestation["sources"][0]["manifest_id"] == replay_result.manifest_id
    assert attestation["sources"][0]["result_digest"] == replay_result.result_digest
    assert {
        name: hashlib.sha256((source / name).read_bytes()).hexdigest()
        for name in source_hashes
    } == source_hashes


def test_mainnet_aggregation_rejects_wrong_endpoint_before_target_write(
    tmp_path: Path,
) -> None:
    module = _module()
    source, _ = _write_cohort(tmp_path / "artifact-a", complete=True)
    session_path = source.parent / "recording" / "recording-session.json"
    session = json.loads(session_path.read_text())
    session["api_url"] = "https://example.invalid"
    session_path.write_text(json.dumps(session, sort_keys=True), encoding="utf-8")
    target = tmp_path / "aggregate"

    with pytest.raises(module.MainnetEvidenceError, match="mainnet"):
        module.aggregate_mainnet_evaluation_evidence(
            target / "journal.sqlite3",
            target / "facts.sqlite3",
            (source,),
        )

    assert not (target / "journal.sqlite3").exists()
    assert not (target / "facts.sqlite3").exists()


def test_mainnet_aggregation_rejects_metadata_replay_digest_mismatch(
    tmp_path: Path,
) -> None:
    module = _module()
    source, _ = _write_cohort(tmp_path / "artifact-a", complete=True)
    summary_path = source / "cohort-summary.json"
    summary = json.loads(summary_path.read_text())
    summary["replay_result_digest"] = "0" * 64
    summary_path.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    target = tmp_path / "aggregate"

    with pytest.raises(module.MainnetEvidenceError, match="result_digest"):
        module.aggregate_mainnet_evaluation_evidence(
            target / "journal.sqlite3",
            target / "facts.sqlite3",
            (source,),
        )

    assert not (target / "journal.sqlite3").exists()
    assert not (target / "facts.sqlite3").exists()
