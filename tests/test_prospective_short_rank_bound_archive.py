from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.replay.source import validate_recording
from cocomelon.research.prospective_short_breakout_rank import (
    ProspectiveShortBreakoutRankState,
)
from cocomelon.research.prospective_short_rank_bound_archive import (
    BoundShortRankArchiveError,
    FrozenFirstSeenRankWitnesses,
    PinnedFirstSeenRankArchive,
    run_rank_archive_bound_short_rank_paired_replay,
)
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    FirstSeenRankSnapshotStore,
)

FREEZE = ProspectiveShortBreakoutRankState(frozen_at_ms=1_000)
START_MS = FREEZE.started_at_ms
MARKET = MarketId("", "TEST")
SNAPSHOT_MS = START_MS + 100
RANK_CAPTURE_MS = SNAPSHOT_MS + 100
BOOK_MS = SNAPSHOT_MS + 1_000


def _write_event(
    root: Path,
    kind: str,
    at_ms: int,
    payload: dict[str, object],
) -> None:
    day = datetime.fromtimestamp(at_ms / 1_000, tz=UTC).date().isoformat()
    path = root / "events" / day / kind / MARKET.canonical / f"segment-{at_ms}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "record_type": "normalized_event",
        "source": "synthetic-exact-archive-unit-fixture-not-mainnet",
        "schema_version": 1,
        "receive_time": datetime.fromtimestamp(
            at_ms / 1_000, tz=UTC
        ).isoformat(),
        "exchange_time_ms": at_ms,
        "market": MARKET.canonical,
        "kind": kind,
        "event_key": f"synthetic-{kind}-{at_ms}",
        "payload": payload,
    }
    path.write_text(
        json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _manifest(root: Path) -> ReplayManifest:
    _write_event(
        root, "market_snapshot", SNAPSHOT_MS,
        {
            "meta": {
                "wire_name": MARKET.wire_name, "sz_decimals": 4,
                "max_leverage": 20, "margin_table_id": 1,
                "only_isolated": False, "is_delisted": False,
                "margin_mode": None,
            },
            "context": {
                "mark_px": "100", "mid_px": "100", "oracle_px": "100",
                "funding": "0", "open_interest": "1000000",
                "day_ntl_vlm": "500000000", "premium": "0",
                "prev_day_px": "101",
            },
        },
    )
    _write_event(
        root, "l2_book", BOOK_MS,
        {
            "bids": [{"px": "99.9", "sz": "1000", "n": 1}],
            "asks": [{"px": "100.1", "sz": "1000", "n": 1}],
        },
    )
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=START_MS,
        end_ms=BOOK_MS + 1,
        segments=validate_recording(root),
        gap_refs=(),
        code_revision="synthetic-fixture-not-authenticated",
        config_digest="a" * 64,
        feature_version="synthetic",
        strategy_version="synthetic",
        risk_version="synthetic",
        execution_config_version="synthetic",
        fee_schedule_id="synthetic",
        replay_engine_version="synthetic",
        dataset_manifest_id=None,
    )


def _first_seen(root: Path) -> FirstSeenRankSnapshotStore:
    store = FirstSeenRankSnapshotStore(root)
    universe = ("ADA", "BTC", "ETH", "TEST")
    store.append(FirstSeenRankSnapshot(
        observed_at_ms=SNAPSHOT_MS + 10,
        captured_at_ms=RANK_CAPTURE_MS,
        features=tuple(
            (market, f"synthetic-{market}-feature", SNAPSHOT_MS)
            for market in universe
        ),
        ranks=tuple(
            (market, index, "0.5", ("synthetic-coarse",))
            for index, market in enumerate(universe, start=1)
        ),
    ))
    return store


def _run(
    tmp_path: Path, *,
    override_rank_pin: str | None = None,
) -> dict[str, object]:
    market_root = tmp_path / "market-data"
    rank_root = tmp_path / "rank-receipts"
    manifest = _manifest(market_root)
    store = _first_seen(rank_root)
    return run_rank_archive_bound_short_rank_paired_replay(
        market_source_root=market_root,
        market_manifest=manifest,
        expected_market_manifest_id=manifest.manifest_id,
        rank_archive_root=rank_root,
        expected_rank_state_digest=(
            store.state_digest if override_rank_pin is None else override_rank_pin
        ),
        freeze=FREEZE,
        config=BaselineReplayConfig(execution=PaperExecutionConfig()),
        selected_markets=(MARKET,),
        account_root=tmp_path / "paper-account-pair",
    )


def test_two_sources_pinned_before_actual_independent_paper_replay(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path)
    assert result["paired_observed_record_count"] == 2
    assert result["independent_simulated_paper_accounts"] is True
    assert result["market_and_rank_sources_pinned_before_paper_accounts"] is True
    assert result["rank_evidence_source"] == (
        "append_only_original_first_seen_rank_archive"
    )
    assert result["source_manifest_independently_authenticated"] is False
    assert result["rank_witness_source_independently_authenticated"] is False
    assert result["ready_for_review"] is False
    assert result["execution_authority"] is False
    market_receipt = result["local_market_source_receipt"]
    rank_receipt = result["local_rank_source_receipt"]
    assert isinstance(market_receipt, dict)
    assert isinstance(rank_receipt, dict)
    assert rank_receipt["rank_snapshot_count"] == 1
    assert rank_receipt["rank_capture_continuity_certified"] is False
    assert rank_receipt["rank_archive_pin_origin_authenticated"] is False
    assert market_receipt["mainnet_provenance_independently_authenticated"] is False
    assert (
        tmp_path / "paper-account-pair" / "baseline-execution.sqlite3"
    ).exists()
    assert (
        tmp_path / "paper-account-pair" / "candidate-execution.sqlite3"
    ).exists()


def test_missing_or_false_rank_pin_never_starts_paper_accounts(
    tmp_path: Path,
) -> None:
    with pytest.raises(BoundShortRankArchiveError, match="state digest"):
        _run(tmp_path, override_rank_pin="f" * 64)
    assert not (tmp_path / "paper-account-pair").exists()


def test_changed_rank_archive_row_rejected_even_when_manifest_valid(
    tmp_path: Path,
) -> None:
    market_root = tmp_path / "market"
    rank_root = tmp_path / "rank"
    manifest = _manifest(market_root)
    store = _first_seen(rank_root)
    pin = store.state_digest
    row_file = next((rank_root / "snapshots").glob("*.json"))
    raw = json.loads(row_file.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["ranks"][3]["ordinal"] = 3
    row_file.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    rank_source = PinnedFirstSeenRankArchive(
        rank_root, pin, manifest, FREEZE,
    )
    with pytest.raises(BoundShortRankArchiveError, match="row"):
        rank_source.verified_snapshots()


def test_extra_unaccounted_rank_file_and_symlink_fail_closed(
    tmp_path: Path,
) -> None:
    market_root = tmp_path / "market"
    rank_root = tmp_path / "rank"
    manifest = _manifest(market_root)
    store = _first_seen(rank_root)
    pin = store.state_digest
    stray = rank_root / "snapshots" / ".incomplete.json.tmp"
    stray.write_text("partial\n", encoding="utf-8")
    source = PinnedFirstSeenRankArchive(rank_root, pin, manifest, FREEZE)
    with pytest.raises(BoundShortRankArchiveError, match="noncanonical"):
        source.verified_snapshots()
    stray.unlink()
    row_file = next((rank_root / "snapshots").glob("*.json"))
    external = tmp_path / "outsider.json"
    external.write_bytes(row_file.read_bytes())
    row_file.unlink()
    row_file.symlink_to(external)
    with pytest.raises(BoundShortRankArchiveError, match="symlink"):
        source.verified_snapshots()


def test_no_backdated_or_future_capture_can_earn_rank_skip(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rank"
    store = _first_seen(root)
    records = store.iter_records()
    provider = FrozenFirstSeenRankWitnesses(records)
    assert provider.witness_for_decision(MARKET, RANK_CAPTURE_MS) is None
    witness = provider.witness_for_decision(MARKET, RANK_CAPTURE_MS + 1)
    assert witness is not None
    assert witness.ordinal == 4
    assert witness.observed_at_ms == RANK_CAPTURE_MS
    assert provider.witness_for_decision(MARKET, RANK_CAPTURE_MS - 1) is None


def test_complete_latest_rank_universe_overrides_older_rank(
    tmp_path: Path,
) -> None:
    store = _first_seen(tmp_path / "rank")
    store.append(FirstSeenRankSnapshot(
        observed_at_ms=RANK_CAPTURE_MS + 10,
        captured_at_ms=RANK_CAPTURE_MS + 20,
        features=(("ADA", "synthetic-feature-next", SNAPSHOT_MS),),
        ranks=(("ADA", 1, "0.8", ()),),
    ))
    frozen = FrozenFirstSeenRankWitnesses(store.iter_records())
    assert frozen.witness_for_decision(MARKET, RANK_CAPTURE_MS + 10) is not None
    assert frozen.witness_for_decision(MARKET, RANK_CAPTURE_MS + 21) is None
    assert frozen.witness_for_decision(
        MarketId("", "ADA"), RANK_CAPTURE_MS + 21,
    ) is not None


def test_clipped_market_manifest_does_not_mask_rank_source_gap(
    tmp_path: Path,
) -> None:
    market_root = tmp_path / "market"
    rank_root = tmp_path / "rank"
    manifest = _manifest(market_root)
    store = _first_seen(rank_root)
    source = PinnedFirstSeenRankArchive(
        rank_root, store.state_digest,
        replace(manifest, end_ms=SNAPSHOT_MS + 50),
        FREEZE,
    )
    with pytest.raises(BoundShortRankArchiveError, match="outside"):
        source.verified_snapshots()


def test_overlapping_account_and_source_paths_are_rejected(
    tmp_path: Path,
) -> None:
    market_root = tmp_path / "market"
    rank_root = tmp_path / "rank"
    manifest = _manifest(market_root)
    store = _first_seen(rank_root)
    with pytest.raises(BoundShortRankArchiveError, match="overlaps"):
        run_rank_archive_bound_short_rank_paired_replay(
            market_source_root=market_root,
            market_manifest=manifest,
            expected_market_manifest_id=manifest.manifest_id,
            rank_archive_root=rank_root,
            expected_rank_state_digest=store.state_digest,
            freeze=FREEZE,
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(MARKET,),
            account_root=rank_root / "new-accounts",
        )
    assert not (rank_root / "new-accounts").exists()
