from __future__ import annotations

import hashlib
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

import scripts.seal_paper_short_rank_full_features as full_rank_sealer
from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    FirstSeenRankSnapshotStore,
)
from cocomelon.research.prospective_short_rank_full_features import (
    OriginalRankFeatureInputBatch,
    OriginalRankFeatureInputBatchStore,
)
from scripts.seal_paper_short_rank_full_features import (
    BUNDLE_FILE,
    RECEIPT_FILE,
    OriginalFullRankFeatureSealError,
    seal_original_short_rank_full_feature_inputs,
)

ORIGINAL_OBS = 1_790_000_000_000
HEAD_SHA = "a" * 40


def _feature(market: str, observed_ms: int) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", market),
        as_of_ms=observed_ms,
        source_received_at_ms=observed_ms - 100,
        schema_version=1,
        day_return=Decimal("-0.03"),
        funding=Decimal("0.0002"),
        open_interest=Decimal("100000"),
        day_notional_volume=Decimal("2000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("2.4"),
        return_5m=Decimal("-0.005"),
        return_15m=Decimal("-0.015"),
        return_1h=Decimal("-0.02"),
        return_4h=Decimal("-0.04"),
        realized_vol_15m=Decimal("0.025"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.3"),
        spread_bps=Decimal("1"),
        bid_depth_25bps=Decimal("10000"),
        ask_depth_25bps=Decimal("9000"),
        book_imbalance=Decimal("-0.1"),
        book_age_ms=35,
        trend_regime=TrendRegime.DOWN,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("normalized-original-price",),
    )


def _record(
    rank_store: FirstSeenRankSnapshotStore,
    observed: int,
    *,
    full: OriginalRankFeatureInputBatchStore | None,
    market: str,
) -> FirstSeenRankSnapshot:
    features = {market: _feature(market, observed)}
    row = FirstSeenRankSnapshot.from_observation(
        observed_at_ms=observed,
        captured_at_ms=observed + 100,
        features=features,
        ranks=(),
    )
    assert rank_store.append(row)
    if full is not None:
        assert full.append(OriginalRankFeatureInputBatch.from_original_rank(
            row, features,
        ))
    return row


def _sources(
    root: Path, *, old_count: int = 1, new_count: int = 2,
    missing_middle: bool = False,
) -> tuple[FirstSeenRankSnapshotStore, OriginalRankFeatureInputBatchStore]:
    root.mkdir(parents=True, exist_ok=True)
    ranks = FirstSeenRankSnapshotStore(
        root / "prospective-short-rank-first-seen"
    )
    full = OriginalRankFeatureInputBatchStore(
        root / "prospective-short-rank-full-feature-inputs"
    )
    for n in range(old_count):
        _record(
            ranks, ORIGINAL_OBS + n * 30_000,
            full=None, market="BTC",
        )
    for n in range(new_count):
        _record(
            ranks, ORIGINAL_OBS + (n + old_count) * 30_000,
            full=(None if missing_middle and n == 1 else full),
            market="ETH" if n % 2 else "BTC",
        )
    return ranks, full


def _seal(root: Path, out: Path) -> dict[str, object]:
    return seal_original_short_rank_full_feature_inputs(
        root, out,
        worker_run_id=38166151613,
        worker_run_attempt=1,
        worker_head_sha=HEAD_SHA,
        sealed_at_ms=ORIGINAL_OBS + 100_000_000,
    )


def test_original_full_rank_inputs_are_sealed_exactly_without_backfilling_legacy(
    tmp_path: Path,
) -> None:
    root, out = tmp_path / "original", tmp_path / "independent"
    ranks, full = _sources(root)
    before = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*.json")
    }
    receipt = _seal(root, out)
    assert receipt["full_rank_feature_status"] == (
        "locally_sealed_prospective_suffix"
    )
    assert receipt["verified_full_input_batch_count"] == 2
    assert receipt["rank_snapshot_count"] == 3
    assert receipt["historical_rank_snapshots_without_full_inputs"] == 1
    assert receipt["entire_rank_history_full_feature_inputs_complete"] is False
    assert receipt["rank_state_digest"] == ranks.state_digest
    assert receipt["feature_input_source_digest"] == full.source_digest
    assert receipt["full_mainnet_market_inputs_authenticated"] is False
    assert receipt["ready_for_review"] is False
    assert receipt["promotion_authority"] is False
    assert receipt["execution_authority"] is False
    assert (out / RECEIPT_FILE).exists()
    data = (out / BUNDLE_FILE).read_bytes()
    assert hashlib.sha256(data).hexdigest() == receipt["zip_sha256"]
    assert len(data) == receipt["zip_size_bytes"]
    with zipfile.ZipFile(out / BUNDLE_FILE) as bundle:
        assert len(bundle.namelist()) == 3
        assert bundle.namelist()[0] == "manifest.json"
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["verified_full_input_batch_count"] == 2
        assert manifest["historical_rank_snapshots_without_full_inputs"] == 1
        assert manifest["feature_input_source_digest"] == full.source_digest
        for row in manifest["files"]:
            original = before[
                "prospective-short-rank-full-feature-inputs/" + row["path"]
            ]
            saved = bundle.read(row["path"])
            assert saved == original
            assert hashlib.sha256(saved).hexdigest() == row["sha256"]
            decoded = json.loads(saved)
            assert decoded["rank_snapshot_digest"] == row["rank_snapshot_digest"]
            assert decoded["features"][0]["feature"]["funding"] == "0.0002"
    after = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*.json")
    }
    assert before == after


def test_missing_rank_input_between_two_complete_batches_rejected(
    tmp_path: Path,
) -> None:
    root, out = tmp_path / "original", tmp_path / "independent"
    _sources(root, old_count=1, new_count=3, missing_middle=True)
    receipt = _seal(root, out)
    assert receipt["full_rank_feature_status"] == "rejected"
    assert "missing intermediary" in str(receipt["failure_reason"])
    assert not (out / BUNDLE_FILE).exists()
    assert (out / RECEIPT_FILE).exists()


@pytest.mark.parametrize("failure", [
    "no_batches", "capture_failure", "bad_rank_file",
    "changed_input_bytes", "unexpected_pending_batch",
])
def test_absent_or_tampered_original_inputs_never_produce_zip(
    tmp_path: Path, failure: str,
) -> None:
    root, out = tmp_path / "original", tmp_path / "independent"
    if failure == "no_batches":
        _sources(root, old_count=1, new_count=0)
    else:
        _sources(root, old_count=0, new_count=2)
        if failure == "capture_failure":
            (root / "prospective-short-rank-full-feature-inputs-error.json").write_text(
                '{"error":"rank source capture failed"}\n',
                encoding="utf-8",
            )
        elif failure == "bad_rank_file":
            file = next(
                (root / "prospective-short-rank-first-seen" / "snapshots")
                .glob("*.json")
            )
            file.write_bytes(b'{"rewritten":"bad"}\n')
        elif failure == "changed_input_bytes":
            file = next(
                (root / "prospective-short-rank-full-feature-inputs" / "batches")
                .glob("*.json")
            )
            changed = json.loads(file.read_text())
            changed["features"][0]["feature"]["funding"] = "0.5"
            file.write_text(json.dumps(changed) + "\n", encoding="utf-8")
        elif failure == "unexpected_pending_batch":
            (root / "prospective-short-rank-full-feature-inputs" / "batches"
             / ".pending.json.tmp").write_bytes(b"extra")
    receipt = _seal(root, out)
    assert receipt["full_rank_feature_status"] == "rejected"
    assert receipt["zip_sha256"] is None
    assert receipt["failure_reason"]
    assert not (out / BUNDLE_FILE).exists()
    assert (out / RECEIPT_FILE).exists()


def test_full_rank_source_cannot_overwrite_original_state_or_existing_export(
    tmp_path: Path,
) -> None:
    root = tmp_path / "original"
    _sources(root, old_count=0, new_count=1)
    with pytest.raises(OriginalFullRankFeatureSealError, match="overlaps"):
        _seal(root, root / "research")
    with pytest.raises(OriginalFullRankFeatureSealError, match="overlaps"):
        _seal(root, tmp_path)
    out = tmp_path / "sealed"
    assert _seal(root, out)["full_rank_feature_status"] == (
        "locally_sealed_prospective_suffix"
    )
    with pytest.raises(OriginalFullRankFeatureSealError, match="new and empty"):
        _seal(root, out)


def test_worker_full_rank_input_export_is_after_original_rank_seal_and_handoff(
) -> None:
    workflow = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    retired = workflow.index("- name: Remove local fast resume archive")
    rank = workflow.index(
        "- name: Seal original first-seen SHORT rank source after worker exit"
    )
    full = workflow.index(
        "- name: Seal entire original SHORT rank input features after paper exit"
    )
    full_upload = workflow.index(
        "- name: Upload original SHORT rank full-input seal or rejection"
    )
    learning = workflow.index(
        "- name: Export compact continuous decision facts"
    )
    assert retired < rank < full < full_upload < learning
    assert "continue-on-error: true" in workflow[full:full_upload]
    assert "if-no-files-found: error" in workflow[full_upload:learning]
    assert "scripts/seal_paper_short_rank_full_features.py" in workflow
    assert "src/cocomelon/research/prospective_short_rank_full_features.py" in workflow


def test_full_rank_source_change_between_verification_and_zip_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No stale source digest can survive a rewrite during archive emission."""
    root = tmp_path / "original"
    out = tmp_path / "sealed"
    _sources(root, old_count=0, new_count=2)
    source = sorted(
        (root / "prospective-short-rank-full-feature-inputs" / "batches")
        .glob("*.json")
    )[0]
    write_member = full_rank_sealer._zip_member

    def rewrite_after_manifest(
        archive: zipfile.ZipFile, name: str, data: bytes,
    ) -> None:
        write_member(archive, name, data)
        if name == "manifest.json":
            # The original input batch was already authenticated on the
            # first pass. Simulate a concurrent silent producer rewrite.
            source.write_bytes(source.read_bytes() + b" ")

    monkeypatch.setattr(full_rank_sealer, "_zip_member", rewrite_after_manifest)
    result = _seal(root, out)
    assert result["full_rank_feature_status"] == "rejected"
    assert result["failure_reason"] == (
        "original full rank input changed during source sealing"
    )
    assert result["zip_sha256"] is None
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
    assert not (out / BUNDLE_FILE).exists()
    assert (out / RECEIPT_FILE).is_file()
