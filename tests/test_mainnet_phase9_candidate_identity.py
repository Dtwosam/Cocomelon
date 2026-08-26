from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayResult, SourceSegment
from cocomelon.evaluation.mainnet_phase9 import MainnetPhase9Error, _candidate_from_sources
from cocomelon.journal.store import JournalStore


def _segment(name: str, *, digest: str, start_ms: int) -> SourceSegment:
    return SourceSegment(
        relative_path=f"events/{name}.jsonl",
        partition=f"events/2026-08-26/l2_book/{name}",
        sha256=digest,
        byte_count=100,
        row_count=2,
        schema_version=1,
        first_available_at_ms=start_ms,
        last_available_at_ms=start_ms + 1_000,
    )


def _manifest(
    name: str,
    *,
    config_digest: str,
    start_ms: int,
    fee_schedule_id: str = "hyperliquid-native-base-2026-08-23",
) -> ReplayManifest:
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=start_ms,
        end_ms=start_ms + 2_000,
        segments=(
            _segment(
                name,
                digest=("a" if name == "a" else "b") * 64,
                start_ms=start_ms,
            ),
        ),
        gap_refs=(),
        code_revision="6de9d86aa7c36fce4f459e0bcc4e004de9215f25",
        config_digest=config_digest,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id=fee_schedule_id,
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def _result(manifest: ReplayManifest, run_id: str) -> ReplayResult:
    return ReplayResult(
        manifest_id=manifest.manifest_id,
        run_id=run_id,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=manifest.start_ms,
        end_ms=manifest.end_ms,
        processed_events=2,
        processed_gaps=0,
        strategy_decisions=1,
        risk_approvals=0,
        risk_rejections=0,
        execution_attempts=0,
        fills=0,
        opened_positions=0,
        closed_positions=0,
        journal_observations=1,
        closed_trade_ids=(),
        final_account_state_id=f"account-{run_id}",
        data_complete=True,
    )


def _record_run(store: JournalStore, manifest: ReplayManifest, run_id: str) -> None:
    store.record_manifest(manifest)
    store.begin_run(manifest.manifest_id, run_id)
    store.finish_run(_result(manifest, run_id))


def _expected_candidate_digest(manifest: ReplayManifest) -> str:
    payload = {
        "code_revision": manifest.code_revision,
        "evidence_class": manifest.evidence_class.value,
        "execution_config_version": manifest.execution_config_version,
        "feature_version": manifest.feature_version,
        "fee_schedule_id": manifest.fee_schedule_id,
        "replay_engine_version": manifest.replay_engine_version,
        "risk_version": manifest.risk_version,
        "strategy_version": manifest.strategy_version,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_candidate_identity_ignores_recording_session_bound_manifest_digest(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "journal.sqlite3"
    first = _manifest("a", config_digest="1" * 64, start_ms=1_000)
    second = _manifest("b", config_digest="2" * 64, start_ms=10_000)
    store = JournalStore(journal_path)
    try:
        _record_run(store, first, "run-a")
        _record_run(store, second, "run-b")
    finally:
        store.close()

    candidate = _candidate_from_sources(journal_path, ("run-a", "run-b"))

    assert candidate.strategy_version == "phase5-v1"
    assert candidate.risk_version == "phase6-v1"
    assert candidate.execution_config_version == "phase7-v1"
    assert candidate.code_revision == first.code_revision
    assert candidate.config_digest == _expected_candidate_digest(first)


def test_candidate_identity_still_rejects_real_execution_semantic_change(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "journal.sqlite3"
    first = _manifest("a", config_digest="1" * 64, start_ms=1_000)
    second = _manifest(
        "b",
        config_digest="1" * 64,
        start_ms=10_000,
        fee_schedule_id="different-fees-v2",
    )
    store = JournalStore(journal_path)
    try:
        _record_run(store, first, "run-a")
        _record_run(store, second, "run-b")
    finally:
        store.close()

    with pytest.raises(MainnetPhase9Error, match="frozen candidate definition"):
        _candidate_from_sources(journal_path, ("run-a", "run-b"))
