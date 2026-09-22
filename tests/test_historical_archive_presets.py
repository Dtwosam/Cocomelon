from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.research.historical_archive_presets as presets
from cocomelon.research.historical_archive_presets import (
    JUL_SEP_2026_V2,
    build_archive_preset_bundle_receipt,
    build_archive_preset_preflight,
    build_archive_preset_run_receipt,
    ensure_archive_preset_output_root_clean,
    get_archive_experiment_preset,
    prepare_archive_experiment_preset,
    run_archive_experiment_preset,
    run_prepared_archive_experiment_preset,
    verify_archive_preset_bundle_receipt,
    verify_archive_preset_run_receipt,
    verify_archive_preset_source_attestation,
    write_archive_preset_bundle_receipt,
    write_archive_preset_run_receipt,
)
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.python_source_attestation import (
    PythonSourceAttestationError,
    PythonSourceFileAttestation,
    PythonSourceTreeAttestation,
    write_python_source_tree_attestation,
)


def _fake_source_attestation() -> PythonSourceTreeAttestation:
    return PythonSourceTreeAttestation(
        subject_type="historical_archive_preset",
        subject_id=JUL_SEP_2026_V2.preset_id,
        source_root_name="cocomelon",
        files=(
            PythonSourceFileAttestation(
                relative_path="research/fake.py",
                sha256="a" * 64,
                byte_count=10,
            ),
        ),
    )


def _fake_experiment_result() -> SimpleNamespace:
    return SimpleNamespace(
        archive=SimpleNamespace(
            manifest_id="archive-download-manifest",
            requested_start_ms=JUL_SEP_2026_V2.start_ms,
            requested_end_ms=JUL_SEP_2026_V2.end_ms,
            shard_count=JUL_SEP_2026_V2.archive_shard_count,
            total_byte_count=123456,
        ),
        source_summary={
            "archive_manifest_id": "archive-ingest-manifest",
            "coverage_report_id": "coverage-report",
        },
        overlap=SimpleNamespace(
            overlap_candles=JUL_SEP_2026_V2.overlap_candles,
            exact=True,
            report_id="overlap-report",
            compared_count=384,
        ),
        comparison=SimpleNamespace(
            evidence_class=JUL_SEP_2026_V2.evidence_class,
            config=JUL_SEP_2026_V2.comparison_config,
            markets=tuple(
                market.canonical for market in JUL_SEP_2026_V2.markets
            ),
            horizons_ms=JUL_SEP_2026_V2.horizons_ms,
            comparison_version="historical-model-comparison-v7",
            dataset_row_count=24000,
            baseline_folds=(object(), object()),
            dataset_id="dataset-id",
            report_id="comparison-report-id",
        ),
        dataset_id="dataset-id",
        report_id="comparison-report-id",
    )


def _write_fake_bundle_files(
    archive_root: Path,
    source_root: Path,
    output_root: Path,
    *,
    include_implementation: bool = True,
) -> None:
    archive_root.mkdir(parents=True, exist_ok=True)
    source_root.mkdir(parents=True, exist_ok=True)
    (output_root / "dataset").mkdir(parents=True, exist_ok=True)

    (archive_root / "download_manifest.json").write_text(
        '{"archive":"download"}\n',
        encoding="utf-8",
    )
    (source_root / "archive_ingest.json").write_text(
        '{"archive":"ingest"}\n',
        encoding="utf-8",
    )
    (source_root / "coverage.json").write_text(
        '{"coverage":true}\n',
        encoding="utf-8",
    )
    (source_root / "archive_native_overlap.json").write_text(
        '{"overlap":"exact"}\n',
        encoding="utf-8",
    )
    (source_root / "source-preparation.json").write_text(
        '{"preparation":"receipt"}\n',
        encoding="utf-8",
    )
    (output_root / "dataset" / "manifest.json").write_text(
        '{"dataset":"manifest"}\n',
        encoding="utf-8",
    )
    (output_root / "dataset" / "training.parquet").write_bytes(
        b"fake-parquet-bytes"
    )
    (output_root / "comparison.json").write_text(
        '{"comparison":"report"}\n',
        encoding="utf-8",
    )
    if include_implementation:
        write_python_source_tree_attestation(
            output_root / "implementation.json",
            _fake_source_attestation(),
        )


def test_jul_sep_2026_v2_locks_current_multimonth_geometry() -> None:
    preset = JUL_SEP_2026_V2

    assert preset.name == "archive-jul-sep-2026-v2"
    assert tuple(market.canonical for market in preset.markets) == (
        "BTC",
        "ETH",
        "HYPE",
        "SOL",
    )
    assert preset.intervals == ("5m", "15m")
    assert preset.horizons_ms == (900_000, 3_600_000, 14_400_000)
    assert preset.archive_shard_count == 1_968
    assert preset.overlap_candles == 96
    assert preset.max_funding_items == 500
    assert preset.evidence_class == "touched_development"
    assert preset.schema_version == 2
    assert preset.end_ms < HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.validation_not_before_ms

    config = preset.comparison_config
    assert config.min_train_anchors == 8_000
    assert config.validation_anchors == 2_000
    assert config.test_anchors == 2_000
    assert config.step_anchors == 2_000
    assert config.embargo_anchors == 48
    assert config.min_validation_trades == 20
    assert config.min_validation_mean_net_return == Decimal("0")
    assert config.stability_blocks == 4
    assert config.min_validation_block_trades == 5
    assert config.tree_min_market_samples == 100
    assert config.portfolio_max_concurrent_positions == 2
    assert config.tree_config.max_leaf_nodes == 7
    assert config.tree_config.min_samples_leaf == 100
    assert config.tree_config.learning_rate == Decimal("0.05")
    assert config.tree_config.max_iter == 100
    assert config.tree_config.l2_regularization == Decimal("1")
    assert len(preset.preset_id) == 24


def test_preset_identity_is_deterministic_and_unknown_names_fail() -> None:
    first = JUL_SEP_2026_V2.to_dict()
    second = get_archive_experiment_preset(JUL_SEP_2026_V2.name).to_dict()

    assert first == second
    assert first["preset_id"] == JUL_SEP_2026_V2.preset_id

    with pytest.raises(ValueError, match="unknown archive experiment preset"):
        get_archive_experiment_preset("not-a-preset")


def test_preset_runner_forwards_only_frozen_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    experiment_result = _fake_experiment_result()

    def fake_run(client: object, **kwargs: object) -> object:
        captured["client"] = client
        captured.update(kwargs)
        archive_root = kwargs["archive_root"]
        source_root = kwargs["source_root"]
        output_root = kwargs["output_root"]
        assert isinstance(archive_root, Path)
        assert isinstance(source_root, Path)
        assert isinstance(output_root, Path)
        _write_fake_bundle_files(
            archive_root,
            source_root,
            output_root,
            include_implementation=False,
        )
        return experiment_result

    monkeypatch.setattr(presets, "run_archive_historical_experiment", fake_run)
    source_attestation = _fake_source_attestation()
    monkeypatch.setattr(
        presets,
        "build_archive_preset_source_attestation",
        lambda _preset: source_attestation,
    )
    client = object()

    def clock() -> int:
        return 123

    output_root = tmp_path / "output"
    result = run_archive_experiment_preset(
        client,  # type: ignore[arg-type]
        preset=JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
        clock_ms=clock,
    )

    assert result is experiment_result
    assert captured["markets"] == JUL_SEP_2026_V2.markets
    assert captured["intervals"] == JUL_SEP_2026_V2.intervals
    assert captured["horizons_ms"] == JUL_SEP_2026_V2.horizons_ms
    assert captured["start_ms"] == JUL_SEP_2026_V2.start_ms
    assert captured["end_ms"] == JUL_SEP_2026_V2.end_ms
    assert captured["config"] == JUL_SEP_2026_V2.comparison_config
    assert captured["max_funding_items"] == JUL_SEP_2026_V2.max_funding_items
    assert captured["overlap_candles"] == JUL_SEP_2026_V2.overlap_candles
    receipt_path = output_root / "preset-run.json"
    assert receipt_path.is_file()
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["preset_id"] == JUL_SEP_2026_V2.preset_id
    assert payload["archive_manifest_id"] == "archive-download-manifest"
    assert payload["comparison_report_id"] == "comparison-report-id"
    assert len(payload["preset_identity_sha256"]) == 64
    assert len(payload["receipt_id"]) == 64
    bundle_path = output_root / "preset-bundle.json"
    assert bundle_path.is_file()
    bundle_payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle_payload["preset_run_receipt_id"] == payload["receipt_id"]
    assert len(bundle_payload["comparison_sha256"]) == 64
    assert len(bundle_payload["implementation_sha256"]) == 64
    assert len(bundle_payload["source_preparation_sha256"]) == 64
    assert bundle_payload["schema_version"] == 3
    assert len(bundle_payload["bundle_id"]) == 64
    implementation = verify_archive_preset_source_attestation(
        output_root,
        preset=JUL_SEP_2026_V2,
    )
    assert implementation == source_attestation



def test_prepare_preset_forwards_only_frozen_source_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    expected = object()

    def fake_prepare(client: object, **kwargs: object) -> object:
        captured["client"] = client
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(
        presets,
        "prepare_archive_historical_sources",
        fake_prepare,
    )
    client = object()

    def clock() -> int:
        return 123

    result = prepare_archive_experiment_preset(
        client,  # type: ignore[arg-type]
        preset=JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        clock_ms=clock,
    )

    assert result is expected
    assert captured["client"] is client
    assert captured["markets"] == JUL_SEP_2026_V2.markets
    assert captured["intervals"] == JUL_SEP_2026_V2.intervals
    assert captured["start_ms"] == JUL_SEP_2026_V2.start_ms
    assert captured["end_ms"] == JUL_SEP_2026_V2.end_ms
    assert captured["max_funding_items"] == JUL_SEP_2026_V2.max_funding_items
    assert captured["overlap_candles"] == JUL_SEP_2026_V2.overlap_candles
    assert captured["clock_ms"] is clock


def test_prepared_preset_runner_forwards_frozen_values_and_writes_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    experiment_result = _fake_experiment_result()
    source_attestation = _fake_source_attestation()

    def fake_run(**kwargs: object) -> object:
        captured.update(kwargs)
        archive_root = kwargs["archive_root"]
        source_root = kwargs["source_root"]
        output_root = kwargs["output_root"]
        assert isinstance(archive_root, Path)
        assert isinstance(source_root, Path)
        assert isinstance(output_root, Path)
        _write_fake_bundle_files(
            archive_root,
            source_root,
            output_root,
            include_implementation=False,
        )
        return experiment_result

    monkeypatch.setattr(
        presets,
        "run_prepared_archive_historical_experiment",
        fake_run,
    )
    monkeypatch.setattr(
        presets,
        "build_archive_preset_source_attestation",
        lambda _preset: source_attestation,
    )
    output_root = tmp_path / "output"

    result = run_prepared_archive_experiment_preset(
        preset=JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    assert result is experiment_result
    assert captured["markets"] == JUL_SEP_2026_V2.markets
    assert captured["intervals"] == JUL_SEP_2026_V2.intervals
    assert captured["horizons_ms"] == JUL_SEP_2026_V2.horizons_ms
    assert captured["start_ms"] == JUL_SEP_2026_V2.start_ms
    assert captured["end_ms"] == JUL_SEP_2026_V2.end_ms
    assert captured["config"] == JUL_SEP_2026_V2.comparison_config
    assert captured["overlap_candles"] == JUL_SEP_2026_V2.overlap_candles
    assert (output_root / "preset-run.json").is_file()
    assert (output_root / "preset-bundle.json").is_file()
    assert (output_root / "implementation.json").is_file()

def test_preset_run_receipt_is_deterministic_and_binds_outputs() -> None:
    result = _fake_experiment_result()

    first = build_archive_preset_run_receipt(
        JUL_SEP_2026_V2,
        result,  # type: ignore[arg-type]
    )
    second = build_archive_preset_run_receipt(
        JUL_SEP_2026_V2,
        result,  # type: ignore[arg-type]
    )

    assert first == second
    assert first.preset_name == JUL_SEP_2026_V2.name
    assert first.preset_id == JUL_SEP_2026_V2.preset_id
    assert first.archive_ingest_manifest_id == "archive-ingest-manifest"
    assert first.coverage_report_id == "coverage-report"
    assert first.overlap_report_id == "overlap-report"
    assert first.dataset_id == "dataset-id"
    assert first.comparison_report_id == "comparison-report-id"
    assert first.evidence_class == "touched_development"
    assert len(first.receipt_id) == 64


def test_preset_run_receipt_rejects_comparison_config_drift() -> None:
    result = _fake_experiment_result()

    class DriftedConfig:
        def to_dict(self) -> dict[str, object]:
            return {"drifted": True}

    result.comparison.config = DriftedConfig()

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_COMPARISON_CONFIG_MISMATCH",
    ):
        build_archive_preset_run_receipt(
            JUL_SEP_2026_V2,
            result,  # type: ignore[arg-type]
        )


def test_preset_run_receipt_refuses_conflicting_overwrite(
    tmp_path: Path,
) -> None:
    result = _fake_experiment_result()
    receipt = build_archive_preset_run_receipt(
        JUL_SEP_2026_V2,
        result,  # type: ignore[arg-type]
    )
    path = write_archive_preset_run_receipt(tmp_path, receipt)
    path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_RUN_RECEIPT_CONFLICT",
    ):
        write_archive_preset_run_receipt(tmp_path, receipt)

def test_preset_run_receipt_verifies_round_trip_and_detects_tampering(
    tmp_path: Path,
) -> None:
    result = _fake_experiment_result()
    receipt = build_archive_preset_run_receipt(
        JUL_SEP_2026_V2,
        result,  # type: ignore[arg-type]
    )
    path = write_archive_preset_run_receipt(tmp_path, receipt)

    verified = verify_archive_preset_run_receipt(
        path,
        preset=JUL_SEP_2026_V2,
    )

    assert verified == receipt

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["dataset_id"] = "tampered-dataset"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_RUN_RECEIPT_ID_MISMATCH",
    ):
        verify_archive_preset_run_receipt(
            path,
            preset=JUL_SEP_2026_V2,
        )


def test_archive_preset_preflight_binds_verified_cache_and_source_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    source_root = tmp_path / "sources"
    output_root = tmp_path / "output"
    source_root.mkdir()
    (source_root / "resume.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        presets,
        "verify_downloaded_archive_cache",
        lambda *args, **kwargs: SimpleNamespace(
            manifest_id="verified-archive-manifest",
            shard_count=JUL_SEP_2026_V2.archive_shard_count,
            total_byte_count=987654321,
        ),
    )
    implementation = _fake_source_attestation()
    monkeypatch.setattr(
        presets,
        "build_archive_preset_source_attestation",
        lambda _preset: implementation,
    )

    preflight = build_archive_preset_preflight(
        JUL_SEP_2026_V2,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )

    assert preflight.preset_id == JUL_SEP_2026_V2.preset_id
    assert preflight.archive_manifest_id == "verified-archive-manifest"
    assert preflight.archive_shard_count == 1968
    assert preflight.expected_archive_shard_count == 1968
    assert preflight.archive_total_byte_count == 987654321
    assert preflight.implementation_attestation_id == implementation.attestation_id
    assert preflight.source_tree_sha256 == implementation.source_tree_sha256
    assert preflight.source_file_count == 1
    assert preflight.source_cache_file_count == 1
    assert preflight.output_root_clean is True
    assert preflight.paid_request_performed is False
    assert len(preflight.preflight_id) == 64
    assert not output_root.exists()


def test_archive_preset_preflight_allows_missing_source_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        presets,
        "verify_downloaded_archive_cache",
        lambda *args, **kwargs: SimpleNamespace(
            manifest_id="verified-archive-manifest",
            shard_count=JUL_SEP_2026_V2.archive_shard_count,
            total_byte_count=1,
        ),
    )
    monkeypatch.setattr(
        presets,
        "build_archive_preset_source_attestation",
        lambda _preset: _fake_source_attestation(),
    )

    preflight = build_archive_preset_preflight(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "missing-sources",
        output_root=tmp_path / "output",
    )

    assert preflight.source_cache_file_count == 0


def test_archive_preset_preflight_rejects_source_root_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    source_root.write_text("not a directory\n", encoding="utf-8")
    called = False

    def forbidden_verify(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("archive verification must not run after bad source root")

    monkeypatch.setattr(
        presets,
        "verify_downloaded_archive_cache",
        forbidden_verify,
    )

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_SOURCE_ROOT_NOT_DIRECTORY",
    ):
        build_archive_preset_preflight(
            JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=source_root,
            output_root=tmp_path / "output",
        )

    assert called is False


def test_archive_preset_preflight_rejects_wrong_verified_shard_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        presets,
        "verify_downloaded_archive_cache",
        lambda *args, **kwargs: SimpleNamespace(
            manifest_id="verified-archive-manifest",
            shard_count=JUL_SEP_2026_V2.archive_shard_count - 1,
            total_byte_count=123,
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_PREFLIGHT_SHARD_COUNT_MISMATCH",
    ):
        build_archive_preset_preflight(
            JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=tmp_path / "output",
        )

def test_preset_output_preflight_allows_missing_or_empty_directory(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    ensure_archive_preset_output_root_clean(missing)

    empty = tmp_path / "empty"
    empty.mkdir()
    ensure_archive_preset_output_root_clean(empty)


def test_preset_output_preflight_rejects_non_empty_directory(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    (output_root / "comparison.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_OUTPUT_ROOT_NOT_EMPTY",
    ):
        ensure_archive_preset_output_root_clean(output_root)


def test_preset_output_preflight_rejects_file_path(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    output_root.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_OUTPUT_ROOT_NOT_DIRECTORY",
    ):
        ensure_archive_preset_output_root_clean(output_root)


def test_preset_runner_blocks_existing_output_before_experiment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    sentinel = output_root / "preset-run.json"
    sentinel.write_text('{"existing":true}\n', encoding="utf-8")

    called = False

    def forbidden_run(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("experiment must not run for a reused output root")

    monkeypatch.setattr(
        presets,
        "run_archive_historical_experiment",
        forbidden_run,
    )

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_OUTPUT_ROOT_NOT_EMPTY",
    ):
        run_archive_experiment_preset(
            object(),  # type: ignore[arg-type]
            preset=JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
            clock_ms=lambda: 123,
        )

    assert called is False
    assert sentinel.read_text(encoding="utf-8") == '{"existing":true}\n'

def test_preset_bundle_verifies_files_and_detects_tampering(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    source_root = tmp_path / "sources"
    output_root = tmp_path / "output"
    _write_fake_bundle_files(archive_root, source_root, output_root)

    result = _fake_experiment_result()
    run_receipt = build_archive_preset_run_receipt(
        JUL_SEP_2026_V2,
        result,  # type: ignore[arg-type]
    )
    write_archive_preset_run_receipt(output_root, run_receipt)
    bundle = build_archive_preset_bundle_receipt(
        JUL_SEP_2026_V2,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    path = write_archive_preset_bundle_receipt(output_root, bundle)

    verified = verify_archive_preset_bundle_receipt(
        path,
        preset=JUL_SEP_2026_V2,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    assert verified == bundle

    (output_root / "comparison.json").write_text(
        '{"comparison":"tampered"}\n',
        encoding="utf-8",
    )
    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_BUNDLE_FILE_DIGEST_MISMATCH",
    ):
        verify_archive_preset_bundle_receipt(
            path,
            preset=JUL_SEP_2026_V2,
            archive_root=archive_root,
            source_root=source_root,
            output_root=output_root,
        )



def test_preset_bundle_detects_source_preparation_tampering(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    source_root = tmp_path / "sources"
    output_root = tmp_path / "output"
    _write_fake_bundle_files(archive_root, source_root, output_root)

    run_receipt = build_archive_preset_run_receipt(
        JUL_SEP_2026_V2,
        _fake_experiment_result(),  # type: ignore[arg-type]
    )
    write_archive_preset_run_receipt(output_root, run_receipt)
    bundle = build_archive_preset_bundle_receipt(
        JUL_SEP_2026_V2,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    path = write_archive_preset_bundle_receipt(output_root, bundle)

    (source_root / "source-preparation.json").write_text(
        '{"preparation":"tampered"}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_BUNDLE_FILE_DIGEST_MISMATCH",
    ):
        verify_archive_preset_bundle_receipt(
            path,
            preset=JUL_SEP_2026_V2,
            archive_root=archive_root,
            source_root=source_root,
            output_root=output_root,
        )

def test_preset_bundle_requires_every_canonical_file(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    source_root = tmp_path / "sources"
    output_root = tmp_path / "output"
    _write_fake_bundle_files(archive_root, source_root, output_root)

    result = _fake_experiment_result()
    run_receipt = build_archive_preset_run_receipt(
        JUL_SEP_2026_V2,
        result,  # type: ignore[arg-type]
    )
    write_archive_preset_run_receipt(output_root, run_receipt)
    (source_root / "coverage.json").unlink()

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_BUNDLE_COVERAGE_MISSING",
    ):
        build_archive_preset_bundle_receipt(
            JUL_SEP_2026_V2,
            archive_root=archive_root,
            source_root=source_root,
            output_root=output_root,
        )

def test_preset_runner_fails_if_source_tree_changes_during_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = _fake_source_attestation()
    second = PythonSourceTreeAttestation(
        subject_type=first.subject_type,
        subject_id=first.subject_id,
        source_root_name=first.source_root_name,
        files=(
            PythonSourceFileAttestation(
                relative_path="research/fake.py",
                sha256="b" * 64,
                byte_count=10,
            ),
        ),
    )
    attestations = iter((first, second))

    def fake_run(client: object, **kwargs: object) -> object:
        del client
        archive_root = kwargs["archive_root"]
        source_root = kwargs["source_root"]
        output_root = kwargs["output_root"]
        assert isinstance(archive_root, Path)
        assert isinstance(source_root, Path)
        assert isinstance(output_root, Path)
        _write_fake_bundle_files(
            archive_root,
            source_root,
            output_root,
            include_implementation=False,
        )
        return _fake_experiment_result()

    monkeypatch.setattr(presets, "run_archive_historical_experiment", fake_run)
    monkeypatch.setattr(
        presets,
        "build_archive_preset_source_attestation",
        lambda _preset: next(attestations),
    )
    output_root = tmp_path / "output"

    with pytest.raises(
        RuntimeError,
        match="ARCHIVE_PRESET_SOURCE_TREE_CHANGED_DURING_RUN",
    ):
        run_archive_experiment_preset(
            object(),  # type: ignore[arg-type]
            preset=JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
            clock_ms=lambda: 123,
        )

    assert not (output_root / "preset-run.json").exists()
    assert not (output_root / "preset-bundle.json").exists()
    assert not (output_root / "implementation.json").exists()


def test_preset_bundle_detects_implementation_attestation_tampering(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    source_root = tmp_path / "sources"
    output_root = tmp_path / "output"
    _write_fake_bundle_files(archive_root, source_root, output_root)

    run_receipt = build_archive_preset_run_receipt(
        JUL_SEP_2026_V2,
        _fake_experiment_result(),  # type: ignore[arg-type]
    )
    write_archive_preset_run_receipt(output_root, run_receipt)
    bundle = build_archive_preset_bundle_receipt(
        JUL_SEP_2026_V2,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    path = write_archive_preset_bundle_receipt(output_root, bundle)

    (output_root / "implementation.json").write_text(
        '{"tampered":true}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        PythonSourceAttestationError,
        match="SOURCE_ATTESTATION_INVALID",
    ):
        verify_archive_preset_bundle_receipt(
            path,
            preset=JUL_SEP_2026_V2,
            archive_root=archive_root,
            source_root=source_root,
            output_root=output_root,
        )

