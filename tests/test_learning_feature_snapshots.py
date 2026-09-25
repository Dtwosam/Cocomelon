from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotError,
    LearningFeatureSnapshotStore,
)


def _snapshot(
    *,
    market: str = "HYPE",
    as_of_ms: int = 20_000,
    return_5m: str = "0.01",
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", market),
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms - 100,
        schema_version=1,
        day_return=Decimal("0.04"),
        funding=Decimal("0.0001"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("5000000"),
        oi_change_fraction=Decimal("0.03"),
        funding_change=Decimal("0.00001"),
        mark_oracle_dislocation_bps=Decimal("1.5"),
        return_5m=Decimal(return_5m),
        return_15m=Decimal("0.02"),
        return_1h=Decimal("0.03"),
        return_4h=Decimal("0.05"),
        realized_vol_15m=Decimal("0.008"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.4"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("250000"),
        ask_depth_25bps=Decimal("230000"),
        book_imbalance=Decimal("0.04"),
        book_age_ms=50,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("hyperliquid-mainnet-info", "hyperliquid-mainnet-ws"),
    )


def test_feature_snapshot_store_round_trips_and_is_idempotent(tmp_path) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    snapshot = _snapshot()

    assert store.record(snapshot) is True
    assert store.record(snapshot) is False

    loaded = store.load(snapshot.snapshot_id)
    assert loaded is not None
    assert loaded.snapshot == snapshot
    assert len(loaded.record_sha256) == 64
    assert len(store.state_digest) == 64


def test_feature_snapshot_store_rejects_tampered_snapshot_identity(tmp_path) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    snapshot = _snapshot()
    store.record(snapshot)
    path = store.records_root / f"{snapshot.snapshot_id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["feature"]["return_5m"] = "0.99"
    path.write_text(
        json.dumps(
            raw,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        LearningFeatureSnapshotError,
        match="ID_MISMATCH",
    ):
        store.load(snapshot.snapshot_id)


def test_feature_snapshot_store_rejects_conflicting_existing_record(tmp_path) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    snapshot = _snapshot()
    store.record(snapshot)
    path = store.records_root / f"{snapshot.snapshot_id}.json"
    path.write_text('{"conflict":true}\n', encoding="utf-8")

    with pytest.raises(
        LearningFeatureSnapshotError,
        match="conflicting feature snapshot",
    ):
        store.record(snapshot)


def test_feature_snapshot_state_digest_is_insertion_order_independent(tmp_path) -> None:
    first = _snapshot(market="HYPE", as_of_ms=20_000)
    second = _snapshot(market="BTC", as_of_ms=30_000, return_5m="-0.01")
    store_a = LearningFeatureSnapshotStore(tmp_path / "a")
    store_b = LearningFeatureSnapshotStore(tmp_path / "b")

    store_a.record(first)
    store_a.record(second)
    store_b.record(second)
    store_b.record(first)

    assert store_a.state_digest == store_b.state_digest
    assert tuple(
        item.snapshot.snapshot_id for item in store_a.iter_verified()
    ) == tuple(
        item.snapshot.snapshot_id for item in store_b.iter_verified()
    )


def test_feature_snapshot_store_fails_closed_on_publish_race(
    tmp_path,
    monkeypatch,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    snapshot = _snapshot()
    path = store.records_root / f"{snapshot.snapshot_id}.json"

    def conflicting_link(_source, target) -> None:
        target.write_text('{"conflict":true}\n', encoding="utf-8")
        raise FileExistsError

    monkeypatch.setattr("cocomelon.research.learning_feature_snapshots.os.link", conflicting_link)

    with pytest.raises(
        LearningFeatureSnapshotError,
        match="conflicting feature snapshot",
    ):
        store.record(snapshot)

    assert path.read_text(encoding="utf-8") == '{"conflict":true}\n'
    assert not (store.records_root / f".{snapshot.snapshot_id}.json.tmp").exists()
