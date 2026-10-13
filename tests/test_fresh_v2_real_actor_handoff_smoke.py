"""Exercise the real NEW v2 paired-paper runtime across a full worker handoff.

No synthetic PnL is promoted: this only tests exact signed genesis, two
independent SQLite accounts, actual worker-thread processing, reviewed gap
witness, changing scanned market universe, and preserved append-only receipts.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.loss_context_paired_shadow_review import (
    verify_review_ledger,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    FROZEN_AT_MS_V2,
    both_side_trend_matched_shadow_v2_freeze,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_genesis import (
    GENESIS_FILE_V2,
    verify_v2_genesis,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
    FILE_NAME as GAP_WITNESS_FILE,
    read_source_gap_witness,
)
from cocomelon.research.trend_paired_shadow_sidecar import (
    TREND_V2_STATE_ROOT,
    TREND_V2_SUMMARY_FILE,
    start_trend_paired_shadow_sidecar,
)
from scripts.verify_trend_paired_terminal_snapshot import verify_terminal_snapshot

BTC = MarketId("", "BTC")
ETH = MarketId("", "ETH")
ROOT = TREND_V2_STATE_ROOT


def _mark(market: MarketId, at_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at_ms,
        source="test-original-paper-market-normalization",
        schema_version=1,
        market=market.canonical,
        exchange_time_ms=at_ms,
        event_key=f"active-asset:{market.canonical}:{at_ms}",
        event_kind="active_asset_ctx",
        payload_json=json.dumps({
            "mark_px": "100", "mid_px": "100", "oracle_px": "100",
            "funding": "0", "open_interest": "1000000",
        }, sort_keys=True),
    )


def _gap(at_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=at_ms,
        source="test-original-paper-market-normalization",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key=f"gap:allMids:{at_ms - 1}:{at_ms}:recovered",
        event_kind=None,
        payload_json=json.dumps({
            "stream_id": "allMids",
            "started_ms": at_ms - 1,
            "ended_ms": at_ms,
            "reason": "recovered",
        }, sort_keys=True),
    )


def _account_ids(root: Path) -> tuple[str, str]:
    ids: list[str] = []
    for lane in ("baseline", "candidate"):
        with sqlite3.connect(
            f"{(root / f'{lane}-execution.sqlite3').as_uri()}?mode=ro",
            uri=True,
        ) as con:
            ids.append(con.execute(
                "SELECT state_id FROM paper_account_state WHERE singleton_id=1"
            ).fetchone()[0])
    return ids[0], ids[1]


def _start(
    root: Path,
    *,
    startup_ms: int,
    markets: tuple[MarketId, ...],
) -> object:
    return start_trend_paired_shadow_sidecar(
        None,
        paper_root=root,
        replay_config=BaselineReplayConfig(
            execution=PaperExecutionConfig(),
        ),
        selected_markets=markets,
        startup_timestamp_ms=startup_ms,
        legacy_shadow_root_name="loss-context-paired-v5",
        campaign="v2",
    )


def test_real_frozen_v2_actor_checkpoint_and_changed_market_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = FROZEN_AT_MS_V2 + 1_000
    monkeypatch.setenv("GITHUB_RUN_ID", "470001")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)

    first = _start(tmp_path, startup_ms=start, markets=(BTC,))
    try:
        assert first.submit_record(
            _mark(BTC, start + 1_000),
            now_ms=start + 1_000,
            evaluate_decisions=False,
        )
        assert first.submit_record(
            _gap(start + 2_000),
            now_ms=start + 2_000,
            evaluate_decisions=False,
        )
        asyncio.run(first._checkpoint_trend(end_ms=start + 3_000))
        first_receipt = json.loads(
            (tmp_path / TREND_V2_SUMMARY_FILE).read_text(),
        )
        assert first_receipt["checkpoint_published"] is True
        assert first_receipt["checkpoint_error"] is None
        assert first_receipt["started_after_frozen_boundary"] is True
        assert first_receipt["started_after_forward_entry_embargo"] is False
        first_signed = first_receipt["checkpoint"]
        assert first_signed["record_count"] == 2
        assert first_signed["selected_markets"] == ["BTC"]
        assert first_signed["review_ledger_row_count"] == 1
        assert first_signed["v2_source_gap_event_witness"][
            "received_gap_record_count"
        ] == 1
    finally:
        asyncio.run(first.close())

    root = tmp_path / ROOT
    genesis_path = root / GENESIS_FILE_V2
    original_genesis_bytes = genesis_path.read_bytes()
    original_genesis = verify_v2_genesis(json.loads(original_genesis_bytes))
    assert original_genesis["source_github_run_id"] == 470001
    assert original_genesis["source_github_head_sha"] == "a" * 40
    initial_account_ids = _account_ids(root)
    assert initial_account_ids[0] != initial_account_ids[1]
    original_gap = (root / GAP_WITNESS_FILE).read_bytes()
    assert read_source_gap_witness(
        root / GAP_WITNESS_FILE, total_processed_records=2,
    )["received_gap_record_count"] == 1

    # Mainnet paper scanner now ranks a different market cohort. The
    # runtime MUST restore the last signed BTC-only checkpoint, then allow
    # both paired lanes to add ETH without changing original genesis.
    monkeypatch.setenv("GITHUB_RUN_ID", "470002")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    second = _start(
        tmp_path, startup_ms=start + 4_000,
        markets=(BTC, ETH),
    )
    try:
        assert second.submit_reconcile((BTC, ETH))
        assert second.submit_record(
            _mark(BTC, start + 5_000),
            now_ms=start + 5_000,
            evaluate_decisions=False,
        )
        assert second.submit_restore_warmup_complete()
        assert second.submit_record(
            _mark(ETH, start + 6_000),
            now_ms=start + 6_000,
            evaluate_decisions=True,
        )
        asyncio.run(second._checkpoint_trend(end_ms=start + 7_000))
        second_receipt = json.loads(
            (tmp_path / TREND_V2_SUMMARY_FILE).read_text(),
        )
        assert second_receipt["checkpoint_published"] is True
        assert second_receipt["checkpoint_error"] is None
        checkpoint = second_receipt["checkpoint"]
        assert checkpoint["record_count"] == 4
        assert checkpoint["selected_markets"] == ["BTC", "ETH"]
        assert checkpoint["review_ledger_row_count"] == 2
        assert checkpoint["v2_source_gap_event_witness"][
            "received_gap_record_count"
        ] == 1
    finally:
        asyncio.run(second.close())

    assert genesis_path.read_bytes() == original_genesis_bytes
    assert _account_ids(root) == initial_account_ids
    assert (root / GAP_WITNESS_FILE).read_bytes() == original_gap
    rows = verify_review_ledger(
        root / "review-ledger.jsonl",
        candidate_id=both_side_trend_matched_shadow_v2_freeze().candidate_id,
    )
    assert len(rows) == 2
    assert rows[1]["previous_row_digest"] == rows[0]["row_digest"]
    assert rows[1]["record_count"] > rows[0]["record_count"]
    independent_terminal = verify_terminal_snapshot(
        tmp_path, root_name=TREND_V2_STATE_ROOT,
        summary_name=TREND_V2_SUMMARY_FILE,
    )
    assert independent_terminal["status"] == (
        "terminal_source_account_snapshot_coherent"
    )
    assert independent_terminal[
        "terminal_account_ids_match_signed_checkpoint"
    ] is True
    assert independent_terminal["frozen_v2_candidate_identity_verified"] is True
    assert independent_terminal["execution_authority"] is False
    assert independent_terminal["promotion_authority"] is False
