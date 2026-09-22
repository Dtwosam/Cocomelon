from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.research.historical_archive_experiment as experiment
from cocomelon.domain.market import Candle, MarketId
from cocomelon.research.historical_archive_acquisition import (
    ARCHIVE_BUCKET,
    ARCHIVE_PREFIX,
    plan_archive_shards,
)
from cocomelon.research.historical_archive_experiment import (
    HistoricalArchiveExperimentError,
    backfill_archive_experiment_funding,
    prepare_archive_historical_sources,
    run_archive_historical_experiment,
    run_prepared_archive_historical_experiment,
    verify_downloaded_archive_cache,
    verify_prepared_archive_historical_sources,
)
from cocomelon.research.historical_archive_overlap import (
    validate_archive_native_overlap,
)
from cocomelon.research.historical_backfill import (
    build_coverage_report,
    write_coverage_report,
)
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_model_comparison import (
    HistoricalModelComparisonConfig,
)
from cocomelon.research.historical_trade_archive import (
    ARCHIVE_SOURCE,
    write_archive_candle_source,
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


class FakeCandleClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, int]] = []

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        self.calls.append((market.canonical, interval, start_ms, end_ms))
        rows = []
        cursor = start_ms
        while cursor <= end_ms:
            px = str(100 + cursor // 300_000)
            rows.append(
                {
                    "t": cursor,
                    "T": cursor + 300_000 - 1,
                    "s": market.wire_name,
                    "i": interval,
                    "o": px,
                    "c": px,
                    "h": px,
                    "l": px,
                    "v": "1",
                    "n": 1,
                }
            )
            cursor += 300_000
        return rows


def _write_prepared_source_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, object]:
    archive_root = tmp_path / "archive"
    source_root = tmp_path / "sources"
    manifest = _write_download_manifest(
        archive_root,
        start_ms=0,
        end_ms=HOUR,
    )
    archive = verify_downloaded_archive_cache(
        archive_root,
        start_ms=0,
        end_ms=HOUR,
    )

    funding_client = FakeFundingClient()
    funding_ids = backfill_archive_experiment_funding(
        funding_client,
        source_root=source_root,
        markets=(BTC,),
        start_ms=0,
        end_ms=HOUR,
        clock_ms=lambda: 10_000_000,
    )
    assert len(funding_ids) == 1

    candles = tuple(
        Candle(
            market=BTC,
            interval="5m",
            start_ms=start_ms,
            end_ms=start_ms + 300_000 - 1,
            open_px=Decimal(str(100 + start_ms // 300_000)),
            high_px=Decimal(str(100 + start_ms // 300_000)),
            low_px=Decimal(str(100 + start_ms // 300_000)),
            close_px=Decimal(str(100 + start_ms // 300_000)),
            volume=Decimal("1"),
            trade_count=1,
            source=ARCHIVE_SOURCE,
            received_at_ms=10_000_000,
            schema_version=1,
        )
        for start_ms in range(0, HOUR + 1, 300_000)
    )
    raw_shards = manifest["shards"]
    assert isinstance(raw_shards, tuple)
    shard = raw_shards[0]
    assert isinstance(shard, dict)
    candle_manifest = write_archive_candle_source(
        source_root / "BTC" / "candles" / "5m",
        candles=candles,
        market=BTC,
        interval="5m",
        start_ms=0,
        end_ms=HOUR,
        raw_archive_digests=(str(shard["sha256"]),),
    )

    from cocomelon.research.historical_dataset import load_funding_source

    funding_manifest, _ = load_funding_source(source_root / "BTC" / "funding")
    coverage = build_coverage_report(
        candle_manifests=(candle_manifest,),
        funding_manifests=(funding_manifest,),
    )
    write_coverage_report(source_root / "coverage.json", coverage)

    ingest_identity = {
        "kind": "hyperliquid-node-fills-by-block",
        "source": "s3://hl-mainnet-node-data/node_fills_by_block",
        "requested_start_ms": 0,
        "requested_end_ms": HOUR,
        "received_at_ms": 10_000_000,
        "files": tuple(
            {
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
                "byte_count": item["byte_count"],
            }
            for item in raw_shards
        ),
        "schema_version": 1,
    }
    archive_ingest = {
        **ingest_identity,
        "manifest_id": hashlib.sha256(
            _canonical_json(ingest_identity).encode("utf-8")
        ).hexdigest()[:24],
    }
    (source_root / "archive_ingest.json").write_text(
        _canonical_json(archive_ingest) + "\n",
        encoding="utf-8",
    )

    overlap = validate_archive_native_overlap(
        FakeCandleClient(),
        source_root=source_root,
        markets=(BTC,),
        intervals=("5m",),
        overlap_candles=2,
        clock_ms=lambda: 20_000_000,
    )
    source_summary = {
        "archive_file_count": archive.shard_count,
        "archive_manifest_id": archive_ingest["manifest_id"],
        "candle_manifests": 1,
        "coverage_report_id": coverage["report_id"],
        "funding_manifests": 1,
        "market_count": 1,
        "parsed_trade_count": 13,
        "source_root": str(source_root),
    }

    monkeypatch.setattr(
        experiment,
        "backfill_archive_experiment_funding",
        lambda *args, **kwargs: funding_ids,
    )
    monkeypatch.setattr(
        experiment,
        "ingest_archive_candles",
        lambda **kwargs: source_summary,
    )
    monkeypatch.setattr(
        experiment,
        "validate_archive_native_overlap",
        lambda *args, **kwargs: overlap,
    )
    preparation = prepare_archive_historical_sources(
        object(),  # type: ignore[arg-type]
        archive_root=archive_root,
        source_root=source_root,
        markets=(BTC,),
        intervals=("5m",),
        start_ms=0,
        end_ms=HOUR,
        clock_ms=lambda: 30_000_000,
        overlap_candles=2,
    )
    return archive_root, source_root, preparation


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


class FakeOverlap:
    report_id = "overlap-report"
    compared_count = 8
    exact = True


class FakeComparison:
    evidence_class = "touched_development"
    report_id = "report-id"
    dataset_id = "dataset-id"
    dataset_row_count = 123
    baseline_folds = (object(),)
    markets = ("BTC",)
    horizons_ms = (900_000,)


def test_archive_experiment_orders_preparation_then_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    preparation = SimpleNamespace(
        archive=experiment.VerifiedArchiveCache(
            manifest_id="manifest",
            requested_start_ms=0,
            requested_end_ms=HOUR,
            shard_count=2,
            total_byte_count=20,
        ),
        overlap=FakeOverlap(),
        source_summary=lambda source_root: {
            "archive_manifest_id": "archive-ingest",
            "coverage_report_id": "coverage",
            "source_root": str(source_root),
        },
    )
    monkeypatch.setattr(
        experiment,
        "prepare_archive_historical_sources",
        lambda *args, **kwargs: calls.append("prepare") or preparation,
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

    assert calls == ["prepare", "comparison"]
    assert result.archive.manifest_id == "manifest"
    assert result.source_summary["coverage_report_id"] == "coverage"
    assert result.overlap.report_id == "overlap-report"
    assert result.report_id == "report-id"
    assert result.dataset_id == "dataset-id"


def test_prepared_archive_sources_verify_end_to_end_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive_root, source_root, preparation = _write_prepared_source_fixture(
        tmp_path,
        monkeypatch,
    )

    verified = verify_prepared_archive_historical_sources(
        archive_root=archive_root,
        source_root=source_root,
        markets=(BTC,),
        intervals=("5m",),
        start_ms=0,
        end_ms=HOUR,
        overlap_candles=2,
    )

    assert verified == preparation
    assert verified.overlap.exact is True
    assert verified.coverage_report_id
    assert (source_root / "source-preparation.json").is_file()


def test_prepared_archive_sources_fail_before_modeling_on_source_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive_root, source_root, _ = _write_prepared_source_fixture(
        tmp_path,
        monkeypatch,
    )
    (source_root / "coverage.json").write_text(
        '{"tampered":true}\n',
        encoding="utf-8",
    )
    called = False

    def forbidden_comparison(**kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("comparison must not run after prepared-source drift")

    monkeypatch.setattr(
        experiment,
        "run_historical_model_comparison_from_sources",
        forbidden_comparison,
    )

    with pytest.raises(
        HistoricalArchiveExperimentError,
        match="ARCHIVE_SOURCE_PREPARATION_COVERAGE_DIGEST_MISMATCH",
    ):
        run_prepared_archive_historical_experiment(
            archive_root=archive_root,
            source_root=source_root,
            output_root=tmp_path / "output",
            markets=(BTC,),
            intervals=("5m",),
            horizons_ms=(900_000,),
            start_ms=0,
            end_ms=HOUR,
            config=_config(),
            overlap_candles=2,
        )

    assert called is False


def test_prepared_archive_experiment_runs_model_comparison_without_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive_root, source_root, preparation = _write_prepared_source_fixture(
        tmp_path,
        monkeypatch,
    )
    captured: dict[str, object] = {}

    def fake_comparison(**kwargs: object) -> FakeComparison:
        captured.update(kwargs)
        return FakeComparison()

    monkeypatch.setattr(
        experiment,
        "run_historical_model_comparison_from_sources",
        fake_comparison,
    )

    result = run_prepared_archive_historical_experiment(
        archive_root=archive_root,
        source_root=source_root,
        output_root=tmp_path / "output",
        markets=(BTC,),
        intervals=("5m",),
        horizons_ms=(900_000,),
        start_ms=0,
        end_ms=HOUR,
        config=_config(),
        overlap_candles=2,
    )

    assert result.archive == preparation.archive
    assert result.overlap == preparation.overlap
    assert result.report_id == "report-id"
    assert captured["source_root"] == source_root
    assert captured["output_root"] == tmp_path / "output"

