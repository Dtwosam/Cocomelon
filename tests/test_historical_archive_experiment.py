from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

import cocomelon.research.historical_archive_experiment as experiment
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_archive_acquisition import (
    ARCHIVE_BUCKET,
    ARCHIVE_PREFIX,
    plan_archive_shards,
)
from cocomelon.research.historical_archive_experiment import (
    HistoricalArchiveExperimentError,
    backfill_archive_experiment_funding,
    run_archive_historical_experiment,
    verify_downloaded_archive_cache,
)
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_model_comparison import (
    HistoricalModelComparisonConfig,
)

BTC = MarketId(dex="", coin="BTC")
ETH = MarketId(dex="", coin="ETH")
HOUR = 3_600_000


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _write_download_manifest(
    root: Path,
    *,
    start_ms: int,
    end_ms: int,
    payload_by_key: dict[str, bytes] | None = None,
) -> dict[str, object]:
    shards = plan_archive_shards(start_ms=start_ms, end_ms=end_ms)
    payloads = payload_by_key or {
        shard.key: f"payload-{index}".encode()
        for index, shard in enumerate(shards, start=1)
    }
    manifest_shards = []
    total = 0
    for index, shard in enumerate(shards, start=1):
        payload = payloads[shard.key]
        path = root / shard.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        sha256 = hashlib.sha256(payload).hexdigest()
        manifest_shards.append(
            {
                "key": shard.key,
                "hour_start_ms": shard.hour_start_ms,
                "relative_path": shard.relative_path,
                "byte_count": len(payload),
                "etag": f"etag-{index}",
                "sha256": sha256,
            }
        )
        total += len(payload)

    identity = {
        "kind": "hyperliquid-node-fills-by-block-download",
        "bucket": ARCHIVE_BUCKET,
        "prefix": ARCHIVE_PREFIX,
        "requested_start_ms": start_ms,
        "requested_end_ms": end_ms,
        "plan_total_byte_count": total,
        "shards": tuple(manifest_shards),
        "schema_version": 1,
    }
    manifest = {
        **identity,
        "transferred_byte_count": total,
        "cache_reused_count": 0,
        "downloaded_count": len(shards),
        "manifest_id": hashlib.sha256(
            _canonical_json(identity).encode("utf-8")
        ).hexdigest()[:24],
    }
    (root / "download_manifest.json").write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    return manifest


def _config() -> HistoricalModelComparisonConfig:
    return HistoricalModelComparisonConfig(
        costs=ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0.0007"),
            round_trip_slippage_fraction=Decimal("0.0005"),
            funding_reserve_fraction_per_hour=Decimal("0.0001"),
        ),
        candidate_thresholds=(Decimal("0"), Decimal("0.001")),
        candidate_ridge_alphas=(Decimal("0.1"),),
        min_train_anchors=4,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=2,
        embargo_anchors=0,
        baseline_min_state_samples=1,
        baseline_min_coin_samples=2,
        ridge_min_market_samples=2,
        min_sample_count=1,
        min_validation_trades=1,
        stability_blocks=2,
        min_validation_block_trades=1,
    )


def test_verified_archive_cache_recomputes_manifest_identity_and_file_digests(
    tmp_path: Path,
) -> None:
    manifest = _write_download_manifest(
        tmp_path,
        start_ms=0,
        end_ms=HOUR,
    )

    verified = verify_downloaded_archive_cache(
        tmp_path,
        start_ms=0,
        end_ms=HOUR,
    )

    assert verified.manifest_id == manifest["manifest_id"]
    assert verified.shard_count == 2
    assert verified.total_byte_count == manifest["plan_total_byte_count"]


def test_verified_archive_cache_rejects_tampered_manifest_identity(
    tmp_path: Path,
) -> None:
    _write_download_manifest(tmp_path, start_ms=0, end_ms=0)
    path = tmp_path / "download_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["manifest_id"] = "tampered"
    path.write_text(_canonical_json(manifest) + "\n", encoding="utf-8")

    with pytest.raises(
        HistoricalArchiveExperimentError,
        match="ARCHIVE_DOWNLOAD_MANIFEST_ID_MISMATCH",
    ):
        verify_downloaded_archive_cache(tmp_path, start_ms=0, end_ms=0)


def test_verified_archive_cache_rejects_unlisted_lz4_file(
    tmp_path: Path,
) -> None:
    _write_download_manifest(tmp_path, start_ms=0, end_ms=0)
    extra = tmp_path / "hourly" / "19700101" / "99.lz4"
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(b"extra")

    with pytest.raises(
        HistoricalArchiveExperimentError,
        match="ARCHIVE_DOWNLOAD_LOCAL_FILE_SET_MISMATCH",
    ):
        verify_downloaded_archive_cache(tmp_path, start_ms=0, end_ms=0)


def test_verified_archive_cache_rejects_corrupted_downloaded_shard(
    tmp_path: Path,
) -> None:
    _write_download_manifest(tmp_path, start_ms=0, end_ms=0)
    shard = plan_archive_shards(start_ms=0, end_ms=0)[0]
    (tmp_path / shard.relative_path).write_bytes(b"corrupted")

    with pytest.raises(
        HistoricalArchiveExperimentError,
        match="ARCHIVE_DOWNLOAD_",
    ):
        verify_downloaded_archive_cache(tmp_path, start_ms=0, end_ms=0)


class FakeFundingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object:
        assert end_ms is not None
        self.calls.append((market.canonical, start_ms, end_ms))
        return [
            {
                "coin": market.wire_name,
                "fundingRate": "0.0001",
                "premium": "0.0002",
                "time": start_ms,
            },
            {
                "coin": market.wire_name,
                "fundingRate": "0.0002",
                "premium": "0.0003",
                "time": end_ms,
            },
        ]


def test_archive_experiment_funding_backfill_writes_market_local_sources(
    tmp_path: Path,
) -> None:
    client = FakeFundingClient()

    ids = backfill_archive_experiment_funding(
        client,
        source_root=tmp_path,
        markets=(ETH, BTC),
        start_ms=0,
        end_ms=HOUR,
        clock_ms=lambda: 10_000_000,
        max_funding_items=500,
    )

    assert len(ids) == 2
    assert [call[0] for call in client.calls] == ["BTC", "ETH"]
    assert (tmp_path / "BTC" / "funding" / "manifest.json").is_file()
    assert (tmp_path / "ETH" / "funding" / "manifest.json").is_file()


class FakeComparison:
    evidence_class = "touched_development"
    report_id = "report-id"
    dataset_id = "dataset-id"
    dataset_row_count = 123
    baseline_folds = (object(),)
    markets = ("BTC",)
    horizons_ms = (900_000,)


def test_archive_experiment_orders_verification_funding_ingest_then_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        experiment,
        "verify_downloaded_archive_cache",
        lambda *args, **kwargs: (
            calls.append("verify")
            or experiment.VerifiedArchiveCache(
                manifest_id="manifest",
                requested_start_ms=0,
                requested_end_ms=HOUR,
                shard_count=2,
                total_byte_count=20,
            )
        ),
    )
    monkeypatch.setattr(
        experiment,
        "backfill_archive_experiment_funding",
        lambda *args, **kwargs: calls.append("funding") or ("funding-id",),
    )
    monkeypatch.setattr(
        experiment,
        "ingest_archive_candles",
        lambda **kwargs: calls.append("candles") or {"coverage_report_id": "coverage"},
    )
    monkeypatch.setattr(
        experiment,
        "run_historical_model_comparison_from_sources",
        lambda **kwargs: calls.append("comparison") or FakeComparison(),
    )

    result = run_archive_historical_experiment(
        FakeFundingClient(),
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=tmp_path / "out",
        markets=(BTC,),
        intervals=("5m", "15m"),
        horizons_ms=(900_000,),
        start_ms=0,
        end_ms=HOUR,
        clock_ms=lambda: 10_000_000,
        config=_config(),
    )

    assert calls == ["verify", "funding", "candles", "comparison"]
    assert result.archive.manifest_id == "manifest"
    assert result.source_summary["coverage_report_id"] == "coverage"
    assert result.report_id == "report-id"
    assert result.dataset_id == "dataset-id"
