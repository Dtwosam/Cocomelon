"""Never open research execution on an old v2 checkpoint and newer source."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    FROZEN_AT_MS_V2,
    both_side_trend_matched_shadow_v2_freeze,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
    FILE_NAME,
    V2SourceGapWitness,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_genesis import (
    V2GenesisError,
    prepare_v2_genesis,
)
from cocomelon.research.v2_restore_integrity_preflight import (
    V2RestorePreflightError,
)


def _gap(timestamp: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=timestamp,
        source="test-mainnet-received-paper-gap",
        schema_version=1,
        market="BLUR",
        exchange_time_ms=timestamp,
        event_key=f"original-received-{timestamp}",
        payload_json=json.dumps({"reason": "disconnect", "at": timestamp}),
        event_kind="data_gap",
    )


def _genesis(root: Path) -> dict[str, object]:
    return prepare_v2_genesis(
        root,
        freeze=both_side_trend_matched_shadow_v2_freeze(),
        startup_timestamp_ms=FROZEN_AT_MS_V2 + 1000,
        selected_markets=["BLUR"],
        replay_config_digest="a" * 64,
        starting_cash=Decimal("10000"),
    )


def _prepare_valid_stored_checkpoint(root: Path) -> V2SourceGapWitness:
    _genesis(root)
    ledger = V2SourceGapWitness(root, restoring=False)
    ledger.append(_gap(100), ordinal=2)
    receipt = ledger.signed_receipt(total_processed_records=2)
    state: dict[str, object] = {
        "record_count": 2,
        "v2_source_gap_event_witness": receipt,
        "selected_markets": ["BLUR"],
        "portfolio_shadow_candidate_id": (
            both_side_trend_matched_shadow_v2_freeze().candidate_id
        ),
        "replay_config_digest": "a" * 64,
        "baseline": {"account_state_id": "baseline-signed"},
        "candidate": {"account_state_id": "candidate-signed"},
    }
    state["state_digest"] = hashlib.sha256(json.dumps(
        state, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()
    (root / "paired-shadow-state.json").write_text(json.dumps(state))
    for lane in ("baseline", "candidate"):
        with sqlite3.connect(root / f"{lane}-execution.sqlite3") as conn:
            conn.execute(
                "CREATE TABLE paper_account_state "
                "(singleton_id INTEGER PRIMARY KEY, state_id TEXT)"
            )
            conn.execute(
                "INSERT INTO paper_account_state VALUES (1, ?)",
                (f"{lane}-signed",),
            )
    return ledger


def _original_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.iterdir() if path.is_file()
    }


def test_coherent_v2_prefix_and_both_accounts_pass_readonly_preflight(
    tmp_path: Path,
) -> None:
    _prepare_valid_stored_checkpoint(tmp_path)
    old = _original_bytes(tmp_path)
    restored = _genesis(tmp_path)
    assert restored["initial_record_count"] == 0
    assert _original_bytes(tmp_path) == old


def test_archived_witness_tail_beyond_signed_state_is_quarantined_at_startup(
    tmp_path: Path,
) -> None:
    witness = _prepare_valid_stored_checkpoint(tmp_path)
    witness.append(_gap(200), ordinal=4)
    before = _original_bytes(tmp_path)
    with pytest.raises(V2GenesisError, match="original signed restore parity") as error:
        _genesis(tmp_path)
    assert "received_gap_witness_diverged" in str(error.value)
    assert _original_bytes(tmp_path) == before
    assert (tmp_path / FILE_NAME).read_bytes() == before[FILE_NAME]


@pytest.mark.parametrize("lane", ["baseline", "candidate"])
def test_any_advanced_sqlite_account_is_quarantined_before_actor(
    tmp_path: Path, lane: str,
) -> None:
    _prepare_valid_stored_checkpoint(tmp_path)
    with sqlite3.connect(tmp_path / f"{lane}-execution.sqlite3") as conn:
        conn.execute(
            "UPDATE paper_account_state SET state_id=? WHERE singleton_id=1",
            (f"{lane}-advanced-unsignaled",),
        )
    before = _original_bytes(tmp_path)
    with pytest.raises(V2GenesisError, match="original signed restore parity") as error:
        _genesis(tmp_path)
    assert "sqlite_account_state_diverged" in str(error.value)
    assert _original_bytes(tmp_path) == before


def test_missing_original_witness_rejected_without_recreating_it(
    tmp_path: Path,
) -> None:
    _prepare_valid_stored_checkpoint(tmp_path)
    (tmp_path / FILE_NAME).unlink()
    before = _original_bytes(tmp_path)
    with pytest.raises(V2GenesisError, match="original signed restore parity") as error:
        _genesis(tmp_path)
    assert "missing_received_gap_witness" in str(error.value)
    assert _original_bytes(tmp_path) == before
    assert not (tmp_path / FILE_NAME).exists()


def test_bad_sqlite_bytes_are_not_repaired_by_research_startup(
    tmp_path: Path,
) -> None:
    _prepare_valid_stored_checkpoint(tmp_path)
    db = tmp_path / "candidate-execution.sqlite3"
    db.write_bytes(b"not sqlite")
    original = _original_bytes(tmp_path)
    with pytest.raises(V2GenesisError, match="original signed restore parity") as error:
        _genesis(tmp_path)
    assert "sqlite_readonly_verification_failed" in str(error.value)
    assert _original_bytes(tmp_path) == original


def test_witness_byte_tampering_fails_despite_unchanged_file_length(
    tmp_path: Path,
) -> None:
    _prepare_valid_stored_checkpoint(tmp_path)
    p = tmp_path / FILE_NAME
    p.write_bytes(p.read_bytes().replace(b"disconnect", b"untrusted"))
    original = _original_bytes(tmp_path)
    with pytest.raises(V2GenesisError, match="original signed restore parity"):
        _genesis(tmp_path)
    assert _original_bytes(tmp_path) == original


def test_unknown_v2_integrity_error_cannot_leak_checkpoint_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_valid_stored_checkpoint(tmp_path)
    before = _original_bytes(tmp_path)

    def poisoned_preflight(_root: Path, _signed: dict[str, object]) -> None:
        raise V2RestorePreflightError(
            "private error /home/runner/credentials/sensitive-state-id"
        )

    monkeypatch.setattr(
        "cocomelon.research.prospective_both_side_trend_paired_v2_genesis."
        "verify_v2_restore_preflight",
        poisoned_preflight,
    )
    with pytest.raises(V2GenesisError, match="original signed restore parity") as error:
        _genesis(tmp_path)
    assert "unclassified_integrity_failure" in str(error.value)
    assert "credentials" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True
    assert _original_bytes(tmp_path) == before
