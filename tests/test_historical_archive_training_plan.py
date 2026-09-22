from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.research.historical_archive_training_plan as planning
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_archive_presets import (
    JUL_SEP_2026_V2,
    HistoricalArchiveExperimentPreset,
)
from cocomelon.research.historical_archive_training_plan import (
    HistoricalArchiveTrainingPlanError,
    build_archive_candidate_training_plan,
    verify_archive_candidate_training_plan,
    write_archive_candidate_training_plan,
)

BTC = MarketId(dex="", coin="BTC")
FIVE = 300_000


def _preset(
    *,
    horizons_ms: tuple[int, ...] = (FIVE,),
    embargo_anchors: int = 1,
) -> HistoricalArchiveExperimentPreset:
    config = replace(
        JUL_SEP_2026_V2.comparison_config,
        min_train_anchors=4,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=2,
        embargo_anchors=embargo_anchors,
    )
    return HistoricalArchiveExperimentPreset(
        name="archive-training-plan-test",
        start_ms=0,
        end_ms=7 * FIVE,
        markets=(BTC,),
        intervals=("5m",),
        horizons_ms=horizons_ms,
        comparison_config=config,
        overlap_candles=2,
        max_funding_items=10,
    )


def _manifest(
    output_root: Path,
    *,
    preset: HistoricalArchiveExperimentPreset,
    dataset_id: str = "d" * 64,
    logical_sha256: str = "l" * 64,
    row_count: int = 8,
) -> None:
    path = output_root / "dataset" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "logical_sha256": logical_sha256,
                "row_count": row_count,
                "anchor_interval": "5m",
                "markets": [market.canonical for market in preset.markets],
                "horizons_ms": list(preset.horizons_ms),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _rows(count: int = 8) -> tuple[SimpleNamespace, ...]:
    return tuple(
        SimpleNamespace(anchor_end_ms=index * FIVE)
        for index in range(count)
    )


def _install_verified_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    preset: HistoricalArchiveExperimentPreset,
    rows: tuple[SimpleNamespace, ...] | None = None,
    dataset_id: str = "d" * 64,
    logical_sha256: str = "l" * 64,
    row_count: int = 8,
) -> Path:
    output_root = tmp_path / "output"
    _manifest(
        output_root,
        preset=preset,
        dataset_id=dataset_id,
        logical_sha256=logical_sha256,
        row_count=row_count,
    )
    freeze = SimpleNamespace(
        candidate_id="a" * 64,
        bundle_id="b" * 64,
        model_family="stable_tree",
        calibration_variant="shared",
        qualified_variant_sha256="c" * 64,
        validation_not_before_ms=99_000_000,
    )
    monkeypatch.setattr(
        planning,
        "verify_archive_candidate_freeze",
        lambda *args, **kwargs: freeze,
    )
    monkeypatch.setattr(
        planning,
        "verify_prepared_archive_historical_sources",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        planning,
        "verify_archive_preset_run_receipt",
        lambda *args, **kwargs: SimpleNamespace(dataset_id=dataset_id),
    )
    resolved_rows = _rows() if rows is None else rows
    monkeypatch.setattr(
        planning,
        "build_training_rows_from_source_root",
        lambda *args, **kwargs: resolved_rows,
    )
    monkeypatch.setattr(
        planning,
        "canonical_training_rows",
        lambda value: tuple(value),
    )
    monkeypatch.setattr(
        planning,
        "training_rows_logical_sha256",
        lambda value: logical_sha256,
    )
    return output_root


def test_training_plan_freezes_exact_fit_embargo_calibration_geometry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preset = _preset()
    output_root = _install_verified_evidence(
        monkeypatch,
        tmp_path,
        preset=preset,
    )

    plan = build_archive_candidate_training_plan(
        preset,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    assert plan.model_family == "stable_tree"
    assert plan.calibration_variant == "shared"
    assert plan.dataset_id == "d" * 64
    assert plan.dataset_logical_sha256 == "l" * 64
    assert plan.total_anchor_count == 8
    assert plan.fit_anchor_count == 5
    assert plan.fit_row_count == 5
    assert plan.fit_start_ms == 0
    assert plan.fit_end_ms == 4 * FIVE
    assert plan.embargo_anchor_count == 1
    assert plan.embargo_row_count == 1
    assert plan.embargo_start_ms == 5 * FIVE
    assert plan.embargo_end_ms == 5 * FIVE
    assert plan.calibration_anchor_count == 2
    assert plan.calibration_row_count == 2
    assert plan.calibration_start_ms == 6 * FIVE
    assert plan.calibration_end_ms == 7 * FIVE
    assert plan.maximum_horizon_ms == FIVE
    assert plan.selection_algorithm == "stable_tree_final_calibration_v1"
    assert plan.training_policy == "chronological-final-fit-calibration-v1"
    assert plan.validation_not_before_ms == 99_000_000
    assert plan.prospective_only is True
    assert plan.promotion_eligible is False
    assert plan.execution_ready is False
    assert len(plan.comparison_config_sha256) == 64
    assert len(plan.plan_id) == 64


def test_training_plan_rejects_dataset_id_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preset = _preset()
    output_root = _install_verified_evidence(
        monkeypatch,
        tmp_path,
        preset=preset,
        dataset_id="d" * 64,
    )
    monkeypatch.setattr(
        planning,
        "verify_archive_preset_run_receipt",
        lambda *args, **kwargs: SimpleNamespace(dataset_id="x" * 64),
    )

    with pytest.raises(
        HistoricalArchiveTrainingPlanError,
        match="ARCHIVE_TRAINING_DATASET_ID_MISMATCH",
    ):
        build_archive_candidate_training_plan(
            preset,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
        )


def test_training_plan_rejects_rebuilt_dataset_logical_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preset = _preset()
    output_root = _install_verified_evidence(
        monkeypatch,
        tmp_path,
        preset=preset,
    )
    monkeypatch.setattr(
        planning,
        "training_rows_logical_sha256",
        lambda value: "x" * 64,
    )

    with pytest.raises(
        HistoricalArchiveTrainingPlanError,
        match="ARCHIVE_TRAINING_DATASET_LOGICAL_SHA256_MISMATCH",
    ):
        build_archive_candidate_training_plan(
            preset,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
        )


def test_training_plan_rejects_dataset_too_short(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preset = _preset()
    short_rows = _rows(6)
    output_root = _install_verified_evidence(
        monkeypatch,
        tmp_path,
        preset=preset,
        rows=short_rows,
        row_count=6,
    )

    with pytest.raises(
        HistoricalArchiveTrainingPlanError,
        match="ARCHIVE_TRAINING_DATASET_TOO_SHORT",
    ):
        build_archive_candidate_training_plan(
            preset,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
        )


def test_training_plan_rejects_embargo_shorter_than_maximum_horizon(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preset = _preset(horizons_ms=(3 * FIVE,), embargo_anchors=1)
    output_root = _install_verified_evidence(
        monkeypatch,
        tmp_path,
        preset=preset,
    )

    with pytest.raises(
        HistoricalArchiveTrainingPlanError,
        match="ARCHIVE_TRAINING_EMBARGO_TOO_SHORT",
    ):
        build_archive_candidate_training_plan(
            preset,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
        )


def test_training_plan_round_trips_and_detects_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preset = _preset()
    output_root = _install_verified_evidence(
        monkeypatch,
        tmp_path,
        preset=preset,
    )
    plan = build_archive_candidate_training_plan(
        preset,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )
    path = write_archive_candidate_training_plan(output_root, plan)

    verified = verify_archive_candidate_training_plan(
        path,
        preset=preset,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    assert verified == plan

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fit_anchor_count"] = 4
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        HistoricalArchiveTrainingPlanError,
        match="ARCHIVE_TRAINING_PLAN_EVIDENCE_MISMATCH",
    ):
        verify_archive_candidate_training_plan(
            path,
            preset=preset,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
        )


def test_training_plan_write_refuses_conflicting_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preset = _preset()
    output_root = _install_verified_evidence(
        monkeypatch,
        tmp_path,
        preset=preset,
    )
    plan = build_archive_candidate_training_plan(
        preset,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )
    path = write_archive_candidate_training_plan(output_root, plan)
    path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(
        HistoricalArchiveTrainingPlanError,
        match="ARCHIVE_TRAINING_PLAN_CONFLICT",
    ):
        write_archive_candidate_training_plan(output_root, plan)
