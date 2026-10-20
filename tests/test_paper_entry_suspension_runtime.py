"""Local ordinary-runtime wiring and whole-state-root handoff checks."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tarfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_continuous_paper import _watchlist_snapshot
from test_paper_entry_suspension_integration import (
    MARKET,
    START_MS,
    _book_record,
    _context,
    _feed,
    _pipeline,
    _restored_held_position,
    _snapshot,
)

import cocomelon.continuous_paper as paper
from cocomelon.config import Settings
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.paper_entry_suspension import ENTRY_SUSPENSION_FILENAME, load_entry_suspension


def _assert_enforced(payload: dict[str, Any]) -> None:
    assert payload["entries_suspended"] is True
    assert payload["runtime_enforced"] is True
    assert payload["adapter_entries_suspended"] is True
    assert payload["new_exposure_cutoff_ms"] == 0
    assert payload["session_opening_attempts"] == 0
    assert payload["session_opening_fills"] == 0
    assert payload["live_orders"] is False


def test_real_session_wires_both_gates_and_publishes_operational_and_final_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Only transport and optional research-process launch are replaced. The
    # ordinary execution adapter, pipeline, decision engine and pump are real.
    stop_file = tmp_path / "stop"
    snapshot = _watchlist_snapshot(
        "BTC", volume="1000000000", open_interest="1000000", received_at_ms=START_MS
    )

    class Reader:
        def __init__(self, settings: Settings) -> None:
            assert settings.execution_mode.value == "paper"

        def rest_budget_snapshot(self) -> dict[str, int | bool]:
            return {}

    async def snapshots(_reader: object) -> tuple[dict, int]:
        return {MARKET.canonical: snapshot}, START_MS

    async def warmup(*_args: object, **_kwargs: object) -> tuple:
        return ()

    async def disconnected_transport(_settings: Settings) -> None:
        await asyncio.Event().wait()

    def no_optional_research_process(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("optional research subprocess disabled in local fixture")

    emitted = []
    original_emit = paper._emit_operational_live_status

    def observe_runtime(
        execution: PaperExecutionAdapter, pump: paper._RecordPump, *args: Any, **kwargs: Any
    ) -> None:
        assert isinstance(pump.pipeline, paper.BaselineReplayPipeline)
        assert execution.entries_suspended is True
        assert pump.pipeline.new_exposure_cutoff_ms == 0
        assert pump.entry_suspension is not None
        original_emit(execution, pump, *args, **kwargs)
        emitted.append(paper._entry_suspension_payload(execution, pump))
        # Stop through the ordinary session handoff path after its first ack.
        stop_file.write_text("local deterministic handoff", encoding="utf-8")

    monkeypatch.setattr(paper, "InfoClient", Reader)
    monkeypatch.setattr(paper, "utc_now_ms", lambda: START_MS)
    monkeypatch.setattr(paper, "_refresh_native_market_snapshots", snapshots)
    monkeypatch.setattr(paper, "_warmup_market", warmup)
    monkeypatch.setattr(paper, "connect_mainnet_ws", disconnected_transport)
    monkeypatch.setattr(
        paper, "activate_targeted_trend_paired_freeze", no_optional_research_process
    )
    monkeypatch.setattr(paper, "start_trend_paired_shadow_sidecar", no_optional_research_process)
    monkeypatch.setattr(paper, "_emit_operational_live_status", observe_runtime)

    summary = asyncio.run(
        paper.run_continuous_paper_session(
            tmp_path / "state",
            paper.ContinuousPaperConfig(duration_seconds=1, deep_limit=1),
            settings=Settings(),
            stop_file=stop_file,
            runtime_identity=paper.ContinuousPaperRuntimeIdentity(123, 1, "a" * 40),
        )
    )
    heartbeats = [
        json.loads(line.split(" ", 1)[1])
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("COCOMELON_PAPER_HEARTBEAT ")
    ]
    assert len(heartbeats) == len(emitted) == 1
    _assert_enforced(heartbeats[0]["entry_suspension"])
    assert heartbeats[0]["entry_suspension"]["origin_worker_run_id"] == 123
    assert heartbeats[0]["entry_suspension"]["origin_worker_head_sha"] == "a" * 40
    assert heartbeats[0]["entry_suspension"] == emitted[0]
    assert summary.exit_reason == "upgrade_requested"
    _assert_enforced(summary.payload()["entry_suspension"])
    saved_summary = json.loads((tmp_path / "state" / paper.SUMMARY_FILENAME).read_text())
    assert saved_summary["entry_suspension"] == summary.payload()["entry_suspension"]


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("exit_state", ("latency", "partial"))
def test_whole_root_archive_to_new_path_preserves_policy_account_and_protective_exit(
    tmp_path: Path, exit_state: str
) -> None:
    # This models whole-STATE_ROOT archive/restore locally, not GitHub adoption.
    original_root = tmp_path / "predecessor-state"
    original_root.mkdir()
    policy = load_entry_suspension(
        original_root,
        timestamp_ms=START_MS + 400,
        worker_run_id=123,
        worker_head_sha="a" * 40,
    )
    marker_before = (original_root / ENTRY_SUSPENSION_FILENAME).read_bytes()
    pipeline, execution, facts = _restored_held_position(original_root, policy=policy)
    quantity = execution.account.positions[0].quantity
    _feed(pipeline, _context(START_MS + 700, "94"))
    if exit_state == "latency":
        _feed(pipeline, _book_record(START_MS + 800, bid="93.9", ask="94.1"))
        assert execution.pending_reduce_only_count == 1
        assert execution.account.positions[0].quantity == quantity
    else:
        _feed(pipeline, _book_record(START_MS + 1_000, bid="93.9", ask="94.1", size="0.1"))
        assert execution.account.positions[0].quantity == quantity - Decimal("0.1")
    paper._write_json_atomic(
        original_root / paper.CHECKPOINT_FILENAME,
        paper._checkpoint_payload(
            pipeline, last_available_at_ms=START_MS + 1_000, selected_markets=(MARKET,)
        ),
    )
    before = execution.account
    counts = execution.store.table_counts()
    facts.close()
    execution.close()
    original_hashes = _file_hashes(original_root)

    archive = tmp_path / "whole-state.tar.gz"
    with tarfile.open(archive, "w:gz") as carrier:
        carrier.add(original_root, arcname="state")
    restored_parent = tmp_path / "successor"
    restored_parent.mkdir()
    with tarfile.open(archive, "r:gz") as carrier:
        carrier.extractall(restored_parent, filter="data")
    restored_root = restored_parent / "state"
    assert restored_root != original_root
    assert _file_hashes(restored_root) == original_hashes

    successor, restored_policy = paper._ordinary_paper_execution(
        restored_root,
        BaselineReplayConfig().execution,
        timestamp_ms=START_MS + 1_100,
        runtime_identity=paper.ContinuousPaperRuntimeIdentity(456, 1, "b" * 40),
    )
    successor_facts = EvaluationFactStore(restored_root / "facts.sqlite3")
    try:
        assert restored_policy.restore_status == "restored"
        assert restored_policy.origin_worker_run_id == 123
        assert restored_policy.origin_worker_head_sha == "a" * 40
        assert restored_policy.effective_at_ms == policy.effective_at_ms
        assert (restored_root / ENTRY_SUSPENSION_FILENAME).read_bytes() == marker_before
        assert successor.account == before
        assert successor.store.table_counts() == counts
        assert successor.entries_suspended is True
        assert successor.health.healthy_for_new_exposure is True
        checkpoints, *_rest = paper._load_checkpoint(restored_root / paper.CHECKPOINT_FILENAME)
        restored = _pipeline(
            successor, successor_facts, cutoff_ms=restored_policy.new_exposure_cutoff_ms
        )
        paper._restore_open_lifecycles(restored, successor, checkpoints)
        # The serialized checkpoint derives opened_at_ms from the restored
        # account rather than duplicating that field in checkpoint JSON.
        assert restored.open_lifecycle_checkpoints == (
            replace(checkpoints[0], opened_at_ms=before.positions[0].opened_at_ms),
        )
        # Baseline handoff preserves durable plans/actions/account protection;
        # its transient pending-exit cache is not an exchange order inventory.
        assert successor.pending_reduce_only_count == 0
        _feed(
            restored,
            _snapshot(START_MS + 1_100),
            _context(START_MS + 1_200, "94"),
            _book_record(START_MS + 1_300, bid="93.9", ask="94.1"),
            _book_record(START_MS + 1_500, bid="93.9", ask="94.1"),
        )
        assert successor.account.positions == ()
        assert len(restored.finalize(START_MS + 1_500)) == 1
        assert successor.store.table_counts()["paper_fills"] == counts["paper_fills"] + 1
        assert successor.session_opening_attempts == successor.session_opening_fills == 0
        assert successor.pending_reduce_only_count == 0
        assert _file_hashes(original_root) == original_hashes
    finally:
        successor_facts.close()
        successor.close()
