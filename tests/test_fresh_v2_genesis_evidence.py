"""Write-once v2 research genesis must precede both account stores."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    FROZEN_AT_MS_V2,
    both_side_trend_matched_shadow_v2_freeze,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_genesis import (
    GENESIS_FILE_V2,
    V2GenesisError,
    prepare_v2_genesis,
    verify_v2_genesis,
)


def _prepare(path: Path) -> dict[str, object]:
    return prepare_v2_genesis(
        path,
        freeze=both_side_trend_matched_shadow_v2_freeze(),
        startup_timestamp_ms=FROZEN_AT_MS_V2 + 1000,
        selected_markets=["ETH", "BTC"],
        replay_config_digest="f" * 64,
        starting_cash=Decimal("10000"),
    )


def _write_signed_checkpoint(
    root: Path, *,
    markets: list[str],
    candidate_id: str | None = None,
) -> None:
    from cocomelon.research.prospective_both_side_trend_paired_v2_genesis import (
        _digest,
    )

    from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
        FILE_NAME,
        V2SourceGapWitness,
        read_source_gap_witness,
    )

    if not (root / FILE_NAME).exists():
        V2SourceGapWitness(root, restoring=False)
    receipt = read_source_gap_witness(
        root / FILE_NAME, total_processed_records=0,
    )
    payload: dict[str, object] = {
        "record_count": 0,
        "v2_source_gap_event_witness": receipt,
        "baseline": {"account_state_id": "signed-baseline"},
        "candidate": {"account_state_id": "signed-candidate"},
        "portfolio_shadow_candidate_id": (
            candidate_id or both_side_trend_matched_shadow_v2_freeze().candidate_id
        ),
        "replay_config_digest": "f" * 64,
        "selected_markets": markets,
        "handoff_safe": True,
        "paper_only": True,
        "execution_authority": False,
    }
    payload["state_digest"] = _digest(payload)
    (root / "paired-shadow-state.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )


def _write_test_accounts(root: Path) -> None:
    for lane in ("baseline", "candidate"):
        database = root / f"{lane}-execution.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE paper_account_state "
                "(singleton_id INTEGER PRIMARY KEY, state_id TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO paper_account_state VALUES (1, ?)",
                (f"signed-{lane}",),
            )


def test_only_new_accounts_can_create_write_once_git_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "40001")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    payload = _prepare(tmp_path)
    assert payload["selected_markets"] == ["BTC", "ETH"]
    assert payload["source_github_run_id"] == 40001
    assert payload["source_github_attempt"] == 1
    assert payload["source_github_head_sha"] == "a" * 40
    assert payload["initial_cash_each_lane"] == "10000"
    assert payload["initial_record_count"] == 0
    original = (tmp_path / GENESIS_FILE_V2).read_bytes()
    assert verify_v2_genesis(json.loads(original)) == payload
    # Simulate a signed original checkpoint and both independently stored
    # paper accounts. Real market rankings may be different next worker.
    _write_signed_checkpoint(tmp_path, markets=["BTC", "ETH"])
    _write_test_accounts(tmp_path)
    monkeypatch.setenv("GITHUB_RUN_ID", "40002")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    restored = _prepare(tmp_path)
    assert restored == payload
    assert (tmp_path / GENESIS_FILE_V2).read_bytes() == original


@pytest.mark.parametrize("missing_file", [
    "paired-shadow-state.json", "baseline-execution.sqlite3",
    "candidate-execution.sqlite3",
])
def test_restore_missing_signed_checkpoint_or_account_never_repairs_genesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_file: str,
) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "40001")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    _prepare(tmp_path)
    for file in (
        "paired-shadow-state.json", "baseline-execution.sqlite3",
        "candidate-execution.sqlite3",
    ):
        if file != missing_file:
            (tmp_path / file).write_bytes(b"old-worker")
    with pytest.raises(V2GenesisError, match="lacks signed state"):
        _prepare(tmp_path)


@pytest.mark.parametrize("orphan", [
    "paired-shadow-state.json", "baseline-execution.sqlite3",
    "candidate-execution.sqlite3", "review-ledger.jsonl",
])
def test_preexisting_v2_artifact_without_origin_is_quarantined(
    tmp_path: Path, orphan: str,
) -> None:
    (tmp_path / orphan).write_bytes(b"non-empty")
    with pytest.raises(V2GenesisError, match="already advanced"):
        _prepare(tmp_path)
    assert not (tmp_path / GENESIS_FILE_V2).exists()


def test_unauthenticated_github_origin_is_never_first_worker_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for env in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA"):
        monkeypatch.delenv(env, raising=False)
    payload = _prepare(tmp_path)
    assert payload["source_github_run_id"] is None
    with pytest.raises(V2GenesisError, match="positive integer"):
        verify_v2_genesis(payload)


@pytest.mark.parametrize("field,wrong", [
    ("initial_record_count", 10),
    ("original_v1_account_reuse", True),
    ("source_github_head_sha", "not-a-hash"),
    ("initial_cash_each_lane", "NaN"),
    ("forward_not_before_ms", 0),
    ("selected_markets", ["ETH", "BTC"]),
])
def test_forged_or_mutated_source_genesis_fails_even_if_digest_recomputed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    field: str, wrong: object,
) -> None:
    from cocomelon.research.prospective_both_side_trend_paired_v2_genesis import (
        _digest,
    )

    monkeypatch.setenv("GITHUB_RUN_ID", "40001")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    payload = dict(_prepare(tmp_path))
    payload[field] = wrong
    payload.pop("genesis_digest")
    payload["genesis_digest"] = _digest(payload)
    with pytest.raises(V2GenesisError):
        verify_v2_genesis(payload)


def test_startup_before_freeze_never_writes_v2_genesis(tmp_path: Path) -> None:
    from cocomelon.research.prospective_both_side_trend_paired_v2_genesis import (
        prepare_v2_genesis,
    )

    with pytest.raises(V2GenesisError, match="predates frozen"):
        prepare_v2_genesis(
            tmp_path,
            freeze=both_side_trend_matched_shadow_v2_freeze(),
            startup_timestamp_ms=FROZEN_AT_MS_V2 - 1,
            selected_markets=["BTC"],
            replay_config_digest="a" * 64,
            starting_cash=Decimal("10000"),
        )
    # An incomplete process cannot place any signed account evidence.
    assert not (tmp_path / GENESIS_FILE_V2).exists()


def test_frozen_initial_selection_can_evolve_on_signed_ranked_worker_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "40001")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    first = _prepare(tmp_path)
    original = (tmp_path / GENESIS_FILE_V2).read_bytes()
    # The original paper scanner reranked its universe DURING the first
    # worker. Both matched lanes consumed that signed selection.
    _write_signed_checkpoint(tmp_path, markets=["BTC", "SOL"])
    _write_test_accounts(tmp_path)
    monkeypatch.setenv("GITHUB_RUN_ID", "40002")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    # A different current startup ranking is a future reconciliation,
    # not an attempt to alter the first worker's immutable genesis.
    resumed = prepare_v2_genesis(
        tmp_path,
        freeze=both_side_trend_matched_shadow_v2_freeze(),
        startup_timestamp_ms=FROZEN_AT_MS_V2 + 2000,
        selected_markets=["AVAX", "BTC"],
        replay_config_digest="f" * 64,
        starting_cash=Decimal("10000"),
    )
    assert resumed == first
    assert resumed["selected_markets"] == ["BTC", "ETH"]
    assert (tmp_path / GENESIS_FILE_V2).read_bytes() == original


@pytest.mark.parametrize("mutation", [
    "unsigned_market_change",
    "wrong_candidate",
    "wrong_config",
    "noncanonical_markets",
    "empty_markets",
])
def test_unsupported_dynamic_market_change_does_not_restore(
    tmp_path: Path,
    mutation: str,
) -> None:
    _prepare(tmp_path)
    _write_signed_checkpoint(tmp_path, markets=["BTC", "SOL"])
    _write_test_accounts(tmp_path)
    if mutation == "unsigned_market_change":
        payload = json.loads(
            (tmp_path / "paired-shadow-state.json").read_text(),
        )
        payload["selected_markets"] = ["ADA", "BTC"]
        (tmp_path / "paired-shadow-state.json").write_text(json.dumps(payload))
    elif mutation == "wrong_candidate":
        _write_signed_checkpoint(
            tmp_path, markets=["BTC", "SOL"], candidate_id="b" * 64,
        )
    elif mutation == "wrong_config":
        payload = json.loads(
            (tmp_path / "paired-shadow-state.json").read_text(),
        )
        payload["replay_config_digest"] = "e" * 64
        from cocomelon.research.prospective_both_side_trend_paired_v2_genesis import (
            _digest,
        )
        payload.pop("state_digest")
        payload["state_digest"] = _digest(payload)
        (tmp_path / "paired-shadow-state.json").write_text(json.dumps(payload))
    else:
        markets = ["SOL", "BTC"] if mutation == "noncanonical_markets" else []
        _write_signed_checkpoint(tmp_path, markets=markets)
    with pytest.raises(V2GenesisError, match="ranked universe"):
        prepare_v2_genesis(
            tmp_path,
            freeze=both_side_trend_matched_shadow_v2_freeze(),
            startup_timestamp_ms=FROZEN_AT_MS_V2 + 2000,
            selected_markets=["AVAX", "BTC"],
            replay_config_digest="f" * 64,
            starting_cash=Decimal("10000"),
        )
