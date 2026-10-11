from __future__ import annotations

import hashlib
import io
import json
import zipfile
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
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    FirstSeenRankSnapshotStore,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    ExpectedGithubRankArtifact,
    GithubShortRankArtifactError,
    run_github_original_rank_bound_paired_replay,
    verify_github_original_short_rank_artifact,
)
from scripts.seal_paper_short_rank_archive import (
    ARCHIVE_NAME,
    RECEIPT_NAME,
    seal_completed_short_rank_archive,
)

RUN = 38152483456
ATTEMPT = 1
HEAD = "a" * 40
MARKET = MarketId("", "TEST")
FREEZE = ProspectiveShortBreakoutRankState(frozen_at_ms=1_000)
OBS_MS = FREEZE.started_at_ms + 1_000
CAPTURE_MS = OBS_MS + 50
BOOK_MS = OBS_MS + 2_000


def _artifact(root: Path) -> tuple[bytes, ExpectedGithubRankArtifact]:
    state, output = root / "state", root / "output"
    store = FirstSeenRankSnapshotStore(
        state / "prospective-short-rank-first-seen"
    )
    store.append(FirstSeenRankSnapshot(
        observed_at_ms=OBS_MS,
        captured_at_ms=CAPTURE_MS,
        features=(("TEST", "paper-original-feature", OBS_MS - 1),),
        ranks=(("TEST", 1, "0.85", ("short-rank-fixture",)),),
    ))
    receipt = seal_completed_short_rank_archive(
        state, output,
        worker_run_id=RUN,
        worker_run_attempt=ATTEMPT,
        worker_head_sha=HEAD,
        sealed_at_ms=OBS_MS + 10_000,
    )
    assert receipt["rank_source_status"] == "locally_sealed"
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(RECEIPT_NAME, (output / RECEIPT_NAME).read_bytes())
        archive.writestr(ARCHIVE_NAME, (output / ARCHIVE_NAME).read_bytes())
    data = outer.getvalue()
    bound = ExpectedGithubRankArtifact(
        run_id=RUN, run_attempt=ATTEMPT, head_sha=HEAD,
        artifact_run_id=RUN, artifact_head_sha=HEAD,
        artifact_name=f"continuous-paper-first-seen-short-rank-{RUN}-{ATTEMPT}",
        artifact_digest="sha256:" + hashlib.sha256(data).hexdigest(),
        artifact_size_bytes=len(data),
    )
    return data, bound


def _outer_replace(
    data: bytes, name: str, replacement: bytes,
) -> bytes:
    original: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        for item in zin.namelist():
            original[item] = zin.read(item)
    original[name] = replacement
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as zout:
        for item, content in original.items():
            zout.writestr(item, content)
    return out.getvalue()


def _rebind(
    data: bytes, original: ExpectedGithubRankArtifact,
) -> ExpectedGithubRankArtifact:
    return replace(
        original,
        artifact_digest="sha256:" + hashlib.sha256(data).hexdigest(),
        artifact_size_bytes=len(data),
    )


def test_github_outer_and_sealed_inner_digest_bind_complete_rank_population(
    tmp_path: Path,
) -> None:
    data, api = _artifact(tmp_path)
    source = verify_github_original_short_rank_artifact(data, expected=api)
    assert source.worker_run_id == RUN
    assert source.worker_head_sha == HEAD
    assert len(source.snapshots) == 1
    assert source.snapshots[0].captured_at_ms == CAPTURE_MS
    assert source.receipt()["every_first_seen_rank_row_reconciled"] is True
    assert source.receipt()["github_outer_artifact_sha256_reconciled"] is True
    assert source.receipt()["github_api_origin_authenticated_by_caller"] is False
    assert source.receipt()["terminal_account_profitability_certified"] is False
    assert source.receipt()["promotion_authority"] is False


def test_artifact_metadata_head_run_attempt_and_bytes_cannot_disagree(
    tmp_path: Path,
) -> None:
    data, api = _artifact(tmp_path)
    with pytest.raises(GithubShortRankArtifactError, match="bytes"):
        verify_github_original_short_rank_artifact(
            data + b"altered", expected=api,
        )
    with pytest.raises(GithubShortRankArtifactError, match="identity"):
        replace(api, artifact_head_sha="b" * 40)
    with pytest.raises(GithubShortRankArtifactError, match="identity"):
        replace(api, run_attempt=2)
    with pytest.raises(GithubShortRankArtifactError, match="identity"):
        replace(api, artifact_run_id=RUN + 1)


def test_recomputed_outer_hash_cannot_hide_wrong_claimed_worker(
    tmp_path: Path,
) -> None:
    data, api = _artifact(tmp_path)
    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        receipt = json.loads(zin.read(RECEIPT_NAME))
    receipt["worker_head_sha_claimed"] = "b" * 40
    rebuilt = _outer_replace(
        data, RECEIPT_NAME,
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )
    with pytest.raises(GithubShortRankArtifactError, match="worker"):
        verify_github_original_short_rank_artifact(
            rebuilt, expected=_rebind(rebuilt, api),
        )


def test_extra_or_missing_github_zip_member_fails_closed(
    tmp_path: Path,
) -> None:
    data, api = _artifact(tmp_path)
    rebuilt = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(
        rebuilt, "w",
    ) as zout:
        for name in zin.namelist():
            zout.writestr(name, zin.read(name))
        zout.writestr("hidden-extra-cashflow.json", "{}")
    changed = rebuilt.getvalue()
    with pytest.raises(GithubShortRankArtifactError, match="unexpected"):
        verify_github_original_short_rank_artifact(
            changed, expected=_rebind(changed, api),
        )


def test_mutated_inner_snapshot_after_recomputed_github_digest_fails(
    tmp_path: Path,
) -> None:
    data, api = _artifact(tmp_path)
    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        inner = zin.read(ARCHIVE_NAME)
    modified = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(inner)) as zin, zipfile.ZipFile(
        modified, "w",
    ) as zout:
        for name in zin.namelist():
            row = zin.read(name)
            if name.startswith("snapshots/"):
                row = row.replace(b'"ordinal":1', b'"ordinal":3')
                assert row != zin.read(name)
            zout.writestr(name, row)
    rebuilt = _outer_replace(data, ARCHIVE_NAME, modified.getvalue())
    with pytest.raises(GithubShortRankArtifactError):
        verify_github_original_short_rank_artifact(
            rebuilt, expected=_rebind(rebuilt, api),
        )


def _record(
    root: Path, kind: str, at: int, payload: dict[str, object],
) -> None:
    day = datetime.fromtimestamp(at / 1_000, tz=UTC).date().isoformat()
    p = root / "events" / day / kind / MARKET.canonical / f"segment-{at}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "record_type": "normalized_event",
        "source": "test-source-not-actual-hyperliquid",
        "schema_version": 1,
        "receive_time": datetime.fromtimestamp(at / 1_000, tz=UTC).isoformat(),
        "exchange_time_ms": at,
        "market": MARKET.canonical,
        "kind": kind,
        "event_key": f"synthetic-{kind}-{at}",
        "payload": payload,
    }
    p.write_text(json.dumps(data, sort_keys=True, separators=(",", ":"))+"\n")


def _market_source(root: Path) -> ReplayManifest:
    _record(root, "market_snapshot", OBS_MS + 800, {
        "meta": {
            "wire_name": MARKET.wire_name, "sz_decimals": 4,
            "max_leverage": 20, "margin_table_id": 1,
            "only_isolated": False, "is_delisted": False, "margin_mode": None,
        },
        "context": {
            "mark_px": "100", "mid_px": "100", "oracle_px": "100",
            "funding": "0", "open_interest": "1000000",
            "day_ntl_vlm": "500000000", "premium": "0", "prev_day_px": "101",
        },
    })
    _record(root, "l2_book", BOOK_MS, {
        "bids": [{"px": "99.9", "sz": "1000", "n": 1}],
        "asks": [{"px": "100.1", "sz": "1000", "n": 1}],
    })
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=FREEZE.started_at_ms,
        end_ms=BOOK_MS + 100,
        segments=validate_recording(root), gap_refs=(),
        code_revision="unit-fixture",
        config_digest="a" * 64, feature_version="unit",
        strategy_version="unit", risk_version="unit",
        execution_config_version="unit", fee_schedule_id="unit",
        replay_engine_version="unit", dataset_manifest_id=None,
    )


def test_verified_github_worker_rank_source_feeds_both_real_paper_engines(
    tmp_path: Path,
) -> None:
    data, api = _artifact(tmp_path)
    market_root = tmp_path / "market"
    manifest = _market_source(market_root)
    accounts = tmp_path / "paper-pair"
    result = run_github_original_rank_bound_paired_replay(
        market_source_root=market_root,
        market_manifest=manifest,
        expected_market_manifest_id=manifest.manifest_id,
        github_artifact_zip=data,
        github_binding=api,
        freeze=FREEZE,
        config=BaselineReplayConfig(execution=PaperExecutionConfig()),
        selected_markets=(MARKET,), account_root=accounts,
    )
    assert result["paired_observed_record_count"] == 2
    assert result["independent_simulated_paper_accounts"] is True
    assert result["original_rank_artifact_digest_checked_before_accounts"] is True
    assert result["rank_witness_source_independently_authenticated"] is False
    assert result["full_account_trial"] is False
    assert result["ready_for_review"] is False
    assert result["promotion_authority"] is False
    assert (accounts / "baseline-execution.sqlite3").exists()
    assert (accounts / "candidate-execution.sqlite3").exists()


def test_corrupt_outer_worker_artifact_does_not_create_any_account(
    tmp_path: Path,
) -> None:
    data, api = _artifact(tmp_path)
    market_root = tmp_path / "market"
    manifest = _market_source(market_root)
    accounts = tmp_path / "paper-pair"
    with pytest.raises(GithubShortRankArtifactError, match="bytes"):
        run_github_original_rank_bound_paired_replay(
            market_source_root=market_root,
            market_manifest=manifest,
            expected_market_manifest_id=manifest.manifest_id,
            github_artifact_zip=data + b"corruption",
            github_binding=api, freeze=FREEZE,
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(MARKET,), account_root=accounts,
        )
    assert not accounts.exists()
