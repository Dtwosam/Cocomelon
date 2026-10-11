from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

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
    OriginalRankInputBatchError,
)

D = Decimal


def _feature(
    market: str, at: int, *,
    funding: str = "0.001",
    source_received_at_ms: int | None = None,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", market),
        as_of_ms=at,
        source_received_at_ms=(
            at - 100 if source_received_at_ms is None
            else source_received_at_ms
        ),
        schema_version=1,
        day_return=D("-0.045"),
        funding=D(funding),
        open_interest=D("8000"),
        day_notional_volume=D("450000"),
        oi_change_fraction=D("-0.03"),
        funding_change=D("0.00002"),
        mark_oracle_dislocation_bps=D("1.2"),
        return_5m=D("-0.011"),
        return_15m=D("-0.025"),
        return_1h=D("-0.04"),
        return_4h=D("-0.07"),
        realized_vol_15m=D("0.02"),
        range_expansion_15m=D("1.8"),
        relative_volume_15m=D("1.5"),
        spread_bps=D("3"),
        bid_depth_25bps=D("180000"),
        ask_depth_25bps=D("160000"),
        book_imbalance=D("-0.12"),
        book_age_ms=125,
        trend_regime=TrendRegime.DOWN,
        volatility_regime=VolatilityRegime.HIGH,
        provenance=("source-market-context", "source-book"),
    )


def _rank(
    at: int, feats: dict[str, FeatureSnapshot],
) -> FirstSeenRankSnapshot:
    return FirstSeenRankSnapshot.from_observation(
        observed_at_ms=at, captured_at_ms=at + 35,
        features=feats, ranks=(),
    )


def test_original_rank_input_batch_is_complete_exact_and_restores_immutable(
    tmp_path: Path,
) -> None:
    observed = 1_790_000_000_000
    feats = {
        "ETH": _feature("ETH", observed),
        "BTC": _feature("BTC", observed),
    }
    rank = _rank(observed, feats)
    rank_store = FirstSeenRankSnapshotStore(tmp_path / "rank")
    assert rank_store.append(rank)
    batch = OriginalRankFeatureInputBatch.from_original_rank(rank, feats)
    assert tuple(feat.market.canonical for feat in batch.features) == ("BTC", "ETH")
    assert batch.captured_at_ms == rank.captured_at_ms
    batch.bind_to(rank)
    store = OriginalRankFeatureInputBatchStore(tmp_path / "full-input")
    assert store.append(batch)
    assert not store.append(batch)
    before = store.source_digest
    restored = OriginalRankFeatureInputBatchStore(tmp_path / "full-input")
    after = restored.iter_verified()
    assert len(after) == 1
    assert after[0].to_dict() == batch.to_dict()
    assert restored.source_digest == before
    assert after[0].batch_sha256 == batch.batch_sha256
    assert after[0].features[0].funding == D("0.001")
    with pytest.raises(OriginalRankInputBatchError, match="disagree"):
        after[0].bind_to(
            replace(rank, captured_at_ms=rank.captured_at_ms + 1)
        )


def test_conflicting_same_observation_or_backdated_append_refuses_rewrite(
    tmp_path: Path,
) -> None:
    now = 1_790_000_000_000
    feats = {"BTC": _feature("BTC", now)}
    rank = _rank(now, feats)
    store = OriginalRankFeatureInputBatchStore(tmp_path / "inputs")
    original = OriginalRankFeatureInputBatch.from_original_rank(rank, feats)
    store.append(original)
    changed = {"BTC": _feature("BTC", now, funding="0.02")}
    with pytest.raises(OriginalRankInputBatchError, match="disagree"):
        OriginalRankFeatureInputBatch.from_original_rank(rank, changed)
    altered = replace(original, features=(changed["BTC"],))
    with pytest.raises(OriginalRankInputBatchError, match="conflicts"):
        store.append(altered)
    earlier = _rank(now - 200, {"BTC": _feature("BTC", now - 200)})
    with pytest.raises(OriginalRankInputBatchError, match="backdated"):
        store.append(OriginalRankFeatureInputBatch.from_original_rank(
            earlier, {"BTC": _feature("BTC", now - 200)}
        ))


def test_missing_or_extra_feature_payload_cannot_claim_full_rank_identity() -> None:
    now = 1_790_000_000_000
    feats = {
        "BTC": _feature("BTC", now),
        "ETH": _feature("ETH", now),
    }
    rank = _rank(now, feats)
    with pytest.raises(OriginalRankInputBatchError, match="disagree"):
        OriginalRankFeatureInputBatch.from_original_rank(
            rank, {"BTC": feats["BTC"]},
        )
    with pytest.raises(OriginalRankInputBatchError, match="inconsistent"):
        OriginalRankFeatureInputBatch.from_original_rank(
            rank, {"UNRELATED": feats["BTC"], "ETH": feats["ETH"]},
        )


def test_future_received_or_feature_calculation_after_observation_rejected() -> None:
    now = 1_790_000_000_000
    feature = _feature("BTC", now + 500)
    with pytest.raises(ValueError, match="source_received_at_ms"):
        replace(feature, source_received_at_ms=now + 700)
    rank = FirstSeenRankSnapshot(
        observed_at_ms=now, captured_at_ms=now + 30,
        features=(("BTC", feature.snapshot_id, now - 100),),
        ranks=(),
    )
    with pytest.raises(OriginalRankInputBatchError, match="not known"):
        OriginalRankFeatureInputBatch(
            observed_at_ms=now, captured_at_ms=now + 30,
            rank_snapshot_digest=rank.snapshot_digest,
            features=(feature,),
        )


def test_altered_stored_feature_payload_not_recoverable_from_record_hash(
    tmp_path: Path,
) -> None:
    now = 1_790_000_000_000
    feats = {"BTC": _feature("BTC", now)}
    store = OriginalRankFeatureInputBatchStore(tmp_path / "input")
    rank = _rank(now, feats)
    store.append(OriginalRankFeatureInputBatch.from_original_rank(rank, feats))
    path = next((tmp_path / "input" / "batches").glob("*.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["features"][0]["feature"]["funding"] = "999"
    path.write_text(json.dumps(raw, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(OriginalRankInputBatchError, match="content ID mismatch"):
        OriginalRankFeatureInputBatchStore(tmp_path / "input")


def test_rank_batch_symlink_or_hidden_partial_file_is_rejected(tmp_path: Path) -> None:
    now = 1_790_000_000_000
    feats = {"BTC": _feature("BTC", now)}
    batch = OriginalRankFeatureInputBatch.from_original_rank(_rank(now, feats), feats)
    store = OriginalRankFeatureInputBatchStore(tmp_path / "input")
    store.append(batch)
    partial = tmp_path / "input" / "batches" / ".pending.json.tmp"
    partial.write_bytes(b"uncommitted")
    with pytest.raises(OriginalRankInputBatchError, match="unexpected"):
        OriginalRankFeatureInputBatchStore(tmp_path / "input")
    partial.unlink()
    file = next((tmp_path / "input" / "batches").glob("*.json"))
    target = tmp_path / "elsewhere.json"
    target.write_bytes(file.read_bytes())
    file.unlink()
    file.symlink_to(target)
    with pytest.raises(OriginalRankInputBatchError, match="unexpected"):
        OriginalRankFeatureInputBatchStore(tmp_path / "input")


def test_historical_rank_ids_not_silently_backfilled_when_new_capture_starts(
    tmp_path: Path,
) -> None:
    old_ms = 1_790_000_000_000
    rank_store = FirstSeenRankSnapshotStore(tmp_path / "rank")
    old_feats = {"BTC": _feature("BTC", old_ms)}
    rank_store.append(_rank(old_ms, old_feats))
    inputs = OriginalRankFeatureInputBatchStore(tmp_path / "full-inputs")
    assert inputs.iter_verified() == ()
    new_ms = old_ms + 30_000
    new_feats = {"BTC": _feature("BTC", new_ms)}
    newer = _rank(new_ms, new_feats)
    rank_store.append(newer)
    inputs.append(OriginalRankFeatureInputBatch.from_original_rank(
        newer, new_feats,
    ))
    assert len(rank_store.iter_records()) == 2
    assert len(inputs.iter_verified()) == 1
    assert inputs.iter_verified()[0].observed_at_ms == new_ms


def test_original_worker_records_full_inputs_only_after_first_seen_rank_capture() -> None:
    worker = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    assert "prospective-short-rank-full-feature-inputs-error.json" in worker
    assert "OriginalRankFeatureInputBatchStore(" in worker
    assert "OriginalRankFeatureInputBatch.from_original_rank(" in worker
    assert worker.index("rank_snapshot_store.append(rank_row)") < worker.index(
        "rank_input_store.append("
    )
    assert worker.count("capture_rank_first_seen(") == 4
    assert '"execution_authority": False' in worker
