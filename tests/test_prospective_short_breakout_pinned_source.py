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
from cocomelon.research.prospective_short_breakout_pinned_source import (
    PinnedShortRankReplaySource,
    ShortRankPinnedSourceError,
    run_digest_pinned_short_rank_paired_replay,
)
from cocomelon.research.prospective_short_breakout_rank import (
    ProspectiveShortBreakoutRankState,
)

MARKET = MarketId("", "TEST")
FREEZE = ProspectiveShortBreakoutRankState(frozen_at_ms=1_000)
SNAPSHOT_MS = FREEZE.started_at_ms + 1_000
BOOK_MS = SNAPSHOT_MS + 2_000


def _iso(at_ms: int) -> str:
    return datetime.fromtimestamp(
        at_ms / 1000, tz=UTC,
    ).isoformat()


def _event(
    kind: str, at_ms: int, payload: dict[str, object],
) -> dict[str, object]:
    return {
        "record_type": "normalized_event",
        "source": "synthetic-test-fixture-not-a-real-mainnet-source",
        "schema_version": 1,
        "receive_time": _iso(at_ms),
        "exchange_time_ms": at_ms,
        "market": MARKET.canonical,
        "kind": kind,
        "event_key": f"fixture:{kind}:{at_ms}",
        "payload": payload,
    }


def _snapshot() -> dict[str, object]:
    return {
        "meta": {
            "wire_name": MARKET.wire_name,
            "sz_decimals": 4,
            "max_leverage": 20,
            "margin_table_id": 1,
            "only_isolated": False,
            "is_delisted": False,
            "margin_mode": None,
        },
        "context": {
            "mark_px": "100",
            "mid_px": "100",
            "oracle_px": "100",
            "funding": "0",
            "open_interest": "1000000",
            "day_ntl_vlm": "500000000",
            "premium": "0",
            "prev_day_px": "101",
        },
    }


def _write_segment(
    root: Path,
    *,
    kind: str,
    at_ms: int,
    payload: dict[str, object],
) -> Path:
    date = datetime.fromtimestamp(at_ms / 1000, tz=UTC).date().isoformat()
    path = (
        root / "events" / date / kind / MARKET.canonical
        / f"segment-{at_ms}.jsonl"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            _event(kind, at_ms, payload),
            separators=(",", ":"), sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return path


def _fixture(root: Path) -> ReplayManifest:
    _write_segment(
        root,
        kind="market_snapshot",
        at_ms=SNAPSHOT_MS,
        payload=_snapshot(),
    )
    _write_segment(
        root,
        kind="l2_book",
        at_ms=BOOK_MS,
        payload={
            "bids": [{"px": "99.9", "sz": "1000", "n": 1}],
            "asks": [{"px": "100.1", "sz": "1000", "n": 1}],
        },
    )
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=FREEZE.started_at_ms,
        end_ms=BOOK_MS + 1_000,
        segments=validate_recording(root),
        gap_refs=(),
        code_revision="synthetic-fixture-not-a-real-source",
        config_digest="a" * 64,
        feature_version="test-fixture",
        strategy_version="test-fixture",
        risk_version="test-fixture",
        execution_config_version="test-fixture",
        fee_schedule_id="test-fixture",
        replay_engine_version="test-fixture",
        dataset_manifest_id=None,
    )


def _source(root: Path, manifest: ReplayManifest) -> PinnedShortRankReplaySource:
    return PinnedShortRankReplaySource(
        root=root, manifest=manifest, expected_manifest_id=manifest.manifest_id,
    )


def test_full_segment_population_and_observation_timestamps_are_checked(
    tmp_path: Path,
) -> None:
    root = tmp_path / "original-archive"
    manifest = _fixture(root)
    source = _source(root, manifest)
    rows = source.verified_records(forward_not_before_ms=FREEZE.started_at_ms)
    assert len(rows) == 2
    assert [r.event_kind for r in rows] == ["market_snapshot", "l2_book"]
    receipt = source.verification_receipt(rows)
    assert receipt["local_archive_exact_segment_match"] is True
    assert receipt["source_segment_rows"] == 2
    assert receipt["source_segment_count"] == 2
    assert receipt["pin_origin_independently_authenticated"] is False
    assert receipt["mainnet_provenance_independently_authenticated"] is False
    assert receipt["full_account_forward_profitability_certified"] is False
    assert receipt["promotion_authority"] is False


def test_wrong_externally_supplied_manifest_pin_never_creates_accounts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "archive"
    manifest = _fixture(root)
    accounts = tmp_path / "accounts"
    with pytest.raises(ShortRankPinnedSourceError, match="manifest identity"):
        run_digest_pinned_short_rank_paired_replay(
            source_root=root,
            manifest=manifest,
            expected_manifest_id="0" * 24,
            freeze=FREEZE,
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(MARKET,),
            rank_witness_provider=lambda *_args: None,
            account_root=accounts,
        )
    assert not accounts.exists()


def test_bit_flip_fails_before_paired_accounts_or_profit_report(
    tmp_path: Path,
) -> None:
    root = tmp_path / "archive"
    manifest = _fixture(root)
    accounts = tmp_path / "accounts"
    path = next(root.rglob(f"segment-{SNAPSHOT_MS}.jsonl"))
    before = path.read_bytes()
    after = before.replace(b'"100"', b'"101"')
    assert after != before
    path.write_bytes(after)
    with pytest.raises(ShortRankPinnedSourceError, match="byte/row"):
        run_digest_pinned_short_rank_paired_replay(
            source_root=root,
            manifest=manifest,
            expected_manifest_id=manifest.manifest_id,
            freeze=FREEZE,
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(MARKET,),
            rank_witness_provider=lambda *_args: None,
            account_root=accounts,
        )
    assert not accounts.exists()


def test_archived_source_cannot_drop_losing_or_gap_segments(
    tmp_path: Path,
) -> None:
    root = tmp_path / "archive"
    manifest = _fixture(root)
    _write_segment(root, kind="trade", at_ms=BOOK_MS + 1, payload={
        "price": "100", "size": "1", "side": "buy",
    })
    with pytest.raises(ShortRankPinnedSourceError, match="segment identity"):
        _source(root, manifest).verified_records(
            forward_not_before_ms=FREEZE.started_at_ms
        )


def test_source_window_must_include_all_genuine_segment_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "archive"
    manifest = _fixture(root)
    clipped = ReplayManifest(
        evidence_class=manifest.evidence_class,
        start_ms=SNAPSHOT_MS + 1,
        end_ms=manifest.end_ms,
        segments=manifest.segments,
        gap_refs=manifest.gap_refs,
        code_revision=manifest.code_revision,
        config_digest=manifest.config_digest,
        feature_version=manifest.feature_version,
        strategy_version=manifest.strategy_version,
        risk_version=manifest.risk_version,
        execution_config_version=manifest.execution_config_version,
        fee_schedule_id=manifest.fee_schedule_id,
        replay_engine_version=manifest.replay_engine_version,
        dataset_manifest_id=manifest.dataset_manifest_id,
    )
    with pytest.raises(ShortRankPinnedSourceError, match="silently censor"):
        _source(root, clipped).verified_records(
            forward_not_before_ms=clipped.start_ms
        )


def test_symlinked_source_segment_is_never_accepted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "archive"
    manifest = _fixture(root)
    path = next(root.rglob("segment-*.jsonl"))
    outside = tmp_path / "external-copy.jsonl"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ShortRankPinnedSourceError, match="symlink"):
        _source(root, manifest).verified_records(
            forward_not_before_ms=FREEZE.started_at_ms
        )


def test_offline_runner_uses_checked_source_then_independent_simulations(
    tmp_path: Path,
) -> None:
    root = tmp_path / "archive"
    manifest = _fixture(root)
    result = run_digest_pinned_short_rank_paired_replay(
        source_root=root,
        manifest=manifest,
        expected_manifest_id=manifest.manifest_id,
        freeze=FREEZE,
        config=BaselineReplayConfig(execution=PaperExecutionConfig()),
        selected_markets=(MARKET,),
        rank_witness_provider=lambda *_args: None,
        account_root=tmp_path / "paper-only-account-pair",
    )
    assert result["paired_observed_record_count"] == 2
    assert result["independent_simulated_paper_accounts"] is True
    assert result["source_manifest_independently_authenticated"] is False
    assert result["ready_for_review"] is False
    assert result["execution_authority"] is False
    local = result["local_archive_verification"]
    assert isinstance(local, dict)
    assert local["externally_supplied_manifest_pin_matched"] is True
    assert local["pin_origin_independently_authenticated"] is False
    assert (
        tmp_path / "paper-only-account-pair" / "baseline-execution.sqlite3"
    ).exists()
    assert (
        tmp_path / "paper-only-account-pair" / "candidate-execution.sqlite3"
    ).exists()



def test_future_exchange_time_cannot_be_used_as_predecision_source(
    tmp_path: Path,
) -> None:
    root = tmp_path / "archive"
    manifest = _fixture(root)
    path = next(root.rglob(f"segment-{BOOK_MS}.jsonl"))
    original = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(original, dict)
    original["exchange_time_ms"] = BOOK_MS + 100
    path.write_text(
        json.dumps(original, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    changed_manifest = replace(manifest, segments=validate_recording(root))
    with pytest.raises(ShortRankPinnedSourceError, match="from the future"):
        _source(root, changed_manifest).verified_records(
            forward_not_before_ms=FREEZE.started_at_ms
        )
