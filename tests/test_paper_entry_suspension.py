from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.paper_entry_suspension import (
    ENTRY_SUSPENSION_FILENAME,
    load_entry_suspension,
)


def test_ordinary_factory_constructs_a_suspended_execution_boundary(tmp_path: Path) -> None:
    from cocomelon.continuous_paper import _ordinary_paper_execution
    from cocomelon.domain.execution import PaperExecutionConfig

    execution, policy = _ordinary_paper_execution(
        tmp_path,
        PaperExecutionConfig(),
        timestamp_ms=1_000,
        runtime_identity=None,
    )
    try:
        assert execution.entries_suspended is True
        assert execution.health.healthy_for_new_exposure is True
        assert execution.account.starting_cash == 10_000
        assert policy.entries_suspended is True
    finally:
        execution.close()


@pytest.mark.parametrize(
    "cutoff, expected", [(0, True), (False, False), (None, False), (2_000, False)]
)
def test_acknowledgment_requires_actual_lifecycle_gate(
    tmp_path: Path,
    cutoff: int | None,
    expected: bool,
) -> None:
    from cocomelon.continuous_paper import (
        _entry_suspension_payload,
        _ordinary_paper_execution,
    )
    from cocomelon.domain.execution import PaperExecutionConfig

    execution, policy = _ordinary_paper_execution(
        tmp_path,
        PaperExecutionConfig(),
        timestamp_ms=1_000,
        runtime_identity=None,
    )
    pump = SimpleNamespace(
        entry_suspension=policy,
        pipeline=SimpleNamespace(new_exposure_cutoff_ms=cutoff, pending_opening_markets=("BTC",)),
    )
    try:
        payload = _entry_suspension_payload(execution, pump)
        assert payload is not None
        assert payload["runtime_enforced"] is expected
        assert payload["pending_opening_candidate_count"] == 1
        assert payload["pending_reduce_only_count"] == 0
        assert payload["session_opening_attempts"] == 0
        assert payload["session_opening_fills"] == 0
    finally:
        execution.close()


def test_legacy_pump_cannot_claim_suspension_acknowledgment(tmp_path: Path) -> None:
    from cocomelon.continuous_paper import _entry_suspension_payload
    from cocomelon.domain.execution import PaperExecutionConfig
    from cocomelon.execution.paper import PaperExecutionAdapter

    execution = PaperExecutionAdapter(
        tmp_path / "paper.sqlite3",
        PaperExecutionConfig(),
        starting_cash=Decimal("10000"),
        startup_timestamp_ms=1_000,
    )
    try:
        assert _entry_suspension_payload(execution, SimpleNamespace()) is None
    finally:
        execution.close()


def test_invalid_origin_is_not_rendered_as_authenticated_provenance(tmp_path: Path) -> None:
    load_entry_suspension(tmp_path, timestamp_ms=1_000)
    path = tmp_path / ENTRY_SUSPENSION_FILENAME
    raw = json.loads(path.read_text())
    raw["origin_worker_head_sha"] = "[" * 40
    path.write_text(json.dumps(raw))
    policy = load_entry_suspension(tmp_path, timestamp_ms=2_000)
    assert policy.payload()["durable"] is False
    assert policy.payload()["origin_worker_head_sha"] is None


@pytest.mark.parametrize(
    "identity",
    [
        {"worker_run_id": True},
        {"worker_run_id": -1},
        {"worker_head_sha": "[" * 40},
    ],
)
def test_invalid_creation_identity_is_rejected(tmp_path: Path, identity: dict) -> None:
    with pytest.raises(ValueError, match="worker"):
        load_entry_suspension(tmp_path, timestamp_ms=1_000, **identity)


def test_missing_policy_suspends_and_records_first_worker(tmp_path: Path) -> None:
    policy = load_entry_suspension(
        tmp_path,
        timestamp_ms=1_000,
        worker_run_id=12,
        worker_head_sha="a" * 40,
    )
    persisted = json.loads((tmp_path / ENTRY_SUSPENSION_FILENAME).read_text())
    assert persisted["entries_suspended"] is True
    assert persisted["effective_at_ms"] == 1_000
    assert persisted["origin_worker_run_id"] == 12
    assert persisted["origin_worker_head_sha"] == "a" * 40
    assert policy.entries_suspended is True
    assert policy.new_exposure_cutoff_ms == 0
    assert policy.payload()["durable"] is True


def test_successor_keeps_original_suspension_clock_and_bytes(tmp_path: Path) -> None:
    load_entry_suspension(tmp_path, timestamp_ms=1_000, worker_run_id=12)
    path = tmp_path / ENTRY_SUSPENSION_FILENAME
    original = path.read_bytes()
    successor = load_entry_suspension(tmp_path, timestamp_ms=2_000, worker_run_id=13)
    assert successor.payload()["effective_at_ms"] == 1_000
    assert successor.payload()["origin_worker_run_id"] == 12
    assert successor.payload()["restore_status"] == "restored"
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "replacement",
    [
        b"not JSON",
        b"[]",
        b'{"schema_version":99}',
        b'{"schema_version":1,"entries_suspended":false}',
    ],
)
def test_invalid_policy_cannot_resume_and_original_evidence_is_preserved(
    tmp_path: Path,
    replacement: bytes,
) -> None:
    path = tmp_path / ENTRY_SUSPENSION_FILENAME
    path.write_bytes(replacement)
    policy = load_entry_suspension(tmp_path, timestamp_ms=2_000)
    assert policy.entries_suspended is True
    assert policy.payload()["durable"] is False
    assert policy.payload()["restore_status"] == "invalid_preserved"
    assert path.read_bytes() == replacement


def test_future_policy_clock_cannot_postpone_blocking(tmp_path: Path) -> None:
    load_entry_suspension(tmp_path, timestamp_ms=3_000)
    path = tmp_path / ENTRY_SUSPENSION_FILENAME
    original = path.read_bytes()
    policy = load_entry_suspension(tmp_path, timestamp_ms=2_000)
    assert policy.entries_suspended is True
    assert policy.payload()["durable"] is False
    assert path.read_bytes() == original


def test_policy_write_failure_keeps_in_memory_suspension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def disk_failure(*_args: object, **_kwargs: object) -> None:
        raise OSError("isolated disk failure")

    monkeypatch.setattr("os.replace", disk_failure)
    policy = load_entry_suspension(tmp_path, timestamp_ms=1_000)
    assert policy.entries_suspended is True
    assert policy.payload()["durable"] is False
    assert policy.payload()["restore_status"] == "write_failed"
    assert not (tmp_path / ENTRY_SUSPENSION_FILENAME).exists()
