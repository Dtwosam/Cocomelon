from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from cocomelon.cli import (
    build_parser,
    compact_recording_payload,
    inspect_journal_payload,
    main,
    replay_payload,
    validate_recording_payload,
)
from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.replay import EvidenceClass
from cocomelon.replay.compaction import ResearchDependencyError
from cocomelon.replay.manifest import build_replay_manifest
from cocomelon.replay.source import validate_recording


def _write_event(root: Path) -> None:
    path = root / "events/2026-08-23/trade/SOL/segment-000001.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "record_type": "normalized_event",
        "schema_version": 1,
        "source": "hyperliquid-mainnet-ws",
        "kind": "trade",
        "market": "SOL",
        "exchange_time_ms": 1_000,
        "receive_time": "2026-08-23T00:00:01Z",
        "event_key": "trades:SOL:1000:1",
        "payload": {"side": "B", "price": "100", "size": "1", "tid": 1},
    }
    path.write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _manifest_payload(root: Path) -> tuple[dict[str, object], str]:
    segments = validate_recording(root)
    manifest = build_replay_manifest(
        segments,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=1_787_443_201_000,
        end_ms=1_787_443_201_000,
        code_revision="phase8-cli-test",
        config_snapshot={"mode": "paper"},
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config=PaperExecutionConfig(),
    )
    payload: dict[str, object] = {
        "evidence_class": manifest.evidence_class.value,
        "start_ms": manifest.start_ms,
        "end_ms": manifest.end_ms,
        "segments": [item.canonical_payload() for item in manifest.segments],
        "gap_refs": list(manifest.gap_refs),
        "code_revision": manifest.code_revision,
        "config_digest": manifest.config_digest,
        "feature_version": manifest.feature_version,
        "strategy_version": manifest.strategy_version,
        "risk_version": manifest.risk_version,
        "execution_config_version": manifest.execution_config_version,
        "fee_schedule_id": manifest.fee_schedule_id,
        "replay_engine_version": manifest.replay_engine_version,
        "dataset_manifest_id": manifest.dataset_manifest_id,
        "schema_version": manifest.schema_version,
    }
    return payload, manifest.manifest_id


def test_validate_recording_returns_machine_readable_hash_summary(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    _write_event(root)

    payload = validate_recording_payload(root)

    assert payload["segment_count"] == 1
    assert payload["row_count"] == 1
    assert payload["byte_count"] > 0
    assert len(str(payload["source_set_sha256"])) == 64
    assert payload["segments"][0]["relative_path"].endswith("segment-000001.jsonl")


def test_compaction_surfaces_research_dependency_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "recordings"
    _write_event(root)

    def missing(*args: object, **kwargs: object) -> object:
        raise ResearchDependencyError("install research extra")

    monkeypatch.setattr("cocomelon.cli.compact_recording", missing)

    with pytest.raises(ResearchDependencyError, match="research"):
        compact_recording_payload(root, tmp_path / "datasets")


def test_replay_audit_requires_frozen_manifest_and_writes_only_output_journal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "recordings"
    _write_event(root)
    raw_source = next(root.rglob("*.jsonl"))
    source_before = raw_source.read_bytes()
    payload, manifest_id = _manifest_payload(root)
    manifest_path = root / "replay-manifest.json"
    manifest_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    journal_path = tmp_path / "journal.sqlite3"

    result = replay_payload(manifest_path, journal_path)

    assert result["mode"] == "evidence_audit"
    assert result["manifest_id"] == manifest_id
    assert result["record_count"] == 1
    assert result["data_gap_count"] == 0
    assert result["network_access"] is False
    assert journal_path.is_file()
    assert raw_source.read_bytes() == source_before


def test_inspect_journal_is_read_only(tmp_path: Path) -> None:
    journal = tmp_path / "journal.sqlite3"
    connection = sqlite3.connect(journal)
    connection.execute(
        "CREATE TABLE journal_trades(trade_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO journal_trades(trade_id, payload_json) VALUES (?, ?)",
        ("trade-1", '{"trade_id":"trade-1","net_pnl":"12.5"}'),
    )
    connection.commit()
    connection.close()
    before = hashlib.sha256(journal.read_bytes()).hexdigest()

    payload = inspect_journal_payload(journal, "trade-1")

    after = hashlib.sha256(journal.read_bytes()).hexdigest()
    assert payload == {"net_pnl": "12.5", "trade_id": "trade-1"}
    assert after == before


def test_offline_commands_do_not_require_settings_or_networkish_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "recordings"
    _write_event(root)

    def forbidden_settings() -> object:
        raise AssertionError("offline Phase 8 command must not load network settings")

    monkeypatch.setattr("cocomelon.cli.Settings.from_env", forbidden_settings)
    main(["validate-recording", "--root", str(root)])
    output = json.loads(capsys.readouterr().out)
    assert output["segment_count"] == 1

    parser = build_parser()
    help_text = parser.format_help().casefold()
    for forbidden in ("testnet", "wallet", "private-key", "api-url", "ws-url"):
        assert forbidden not in help_text
