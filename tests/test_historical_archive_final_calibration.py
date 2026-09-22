from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.research.historical_archive_final_calibration as final
from cocomelon.research.historical_archive_final_calibration import (
    HistoricalArchiveFinalCalibrationError,
    build_archive_final_calibration,
    verify_archive_final_calibration,
    write_archive_final_calibration,
)
from cocomelon.research.historical_archive_presets import JUL_SEP_2026_V2


def _evaluation(
    *,
    trades: int = 30,
    mean: Decimal | None = Decimal("0.002"),
) -> SimpleNamespace:
    total = Decimal("0") if mean is None else mean * trades
    return SimpleNamespace(
        trade_count=trades,
        long_count=trades // 2,
        short_count=trades - trades // 2,
        total_realized_net_return=total,
        mean_realized_net_return=mean,
    )


def _horizons(
    thresholds: tuple[tuple[int, Decimal | None], ...] = (
        (900_000, Decimal("0.001")),
        (3_600_000, Decimal("0.002")),
    ),
) -> tuple[SimpleNamespace, ...]:
    return tuple(
        SimpleNamespace(
            horizon_ms=horizon_ms,
            calibration=SimpleNamespace(selected_threshold=threshold),
        )
        for horizon_ms, threshold in thresholds
    )


def _ridge_candidate(
    alpha: str,
    *,
    trades: int = 30,
    mean: Decimal | None = Decimal("0.002"),
    thresholds: tuple[tuple[int, Decimal | None], ...] = (
        (900_000, Decimal("0.001")),
        (3_600_000, Decimal("0.002")),
    ),
) -> SimpleNamespace:
    return SimpleNamespace(
        alpha=Decimal(alpha),
        horizons=_horizons(thresholds),
        evaluation=_evaluation(trades=trades, mean=mean),
    )


def _plan(
    *,
    family: str = "stable_horizon_ridge",
    calibration_variant: str = "shared",
) -> SimpleNamespace:
    algorithm = {
        "stable_horizon_ridge": "stable_horizon_ridge_final_calibration_v1",
        "occupancy_stable_ridge": "occupancy_stable_ridge_final_calibration_v1",
        "portfolio_capacity_stable_ridge": (
            "portfolio_capacity_stable_ridge_final_calibration_v1"
        ),
        "stable_tree": "stable_tree_final_calibration_v1",
    }[family]
    return SimpleNamespace(
        candidate_id="a" * 64,
        plan_id="p" * 64,
        bundle_id="b" * 64,
        dataset_id="d" * 64,
        model_family=family,
        calibration_variant=calibration_variant,
        selection_algorithm=algorithm,
        fit_anchor_count=8000,
        calibration_anchor_count=2000,
        validation_not_before_ms=99_000_000,
    )


def _install_plan(
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        final,
        "verify_archive_candidate_training_plan",
        lambda *args, **kwargs: plan,
    )
    monkeypatch.setattr(
        final,
        "materialize_archive_candidate_training_rows",
        lambda *args, **kwargs: (
            (object(), object()),
            (object(),),
            (object(), object()),
        ),
    )


def test_final_ridge_calibration_persists_exact_selected_recipe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan()
    _install_plan(monkeypatch, plan=plan)
    first = _ridge_candidate("0.01", mean=Decimal("0.001"))
    selected = _ridge_candidate("0.1", mean=Decimal("0.003"))
    monkeypatch.setattr(
        final,
        "select_final_stable_horizon_ridge",
        lambda *args, **kwargs: (selected, (first, selected)),
    )

    result = build_archive_final_calibration(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=tmp_path / "output",
    )

    assert result.model_family == "stable_horizon_ridge"
    assert result.calibration_variant == "shared"
    assert result.selected_alpha == Decimal("0.1")
    assert result.selected_horizon_thresholds == (
        (900_000, Decimal("0.001")),
        (3_600_000, Decimal("0.002")),
    )
    assert len(result.candidates) == 2
    assert [item.selected for item in result.candidates] == [False, True]
    assert result.calibration_trade_count == 30
    assert result.calibration_mean_realized_net_return == Decimal("0.003")
    assert result.prospective_only is True
    assert result.promotion_eligible is False
    assert result.trained_model_persisted is False
    assert result.execution_ready is False
    assert len(result.calibration_id) == 64


def test_final_calibration_passes_market_flag_to_family_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan(
        family="occupancy_stable_ridge",
        calibration_variant="market",
    )
    _install_plan(monkeypatch, plan=plan)
    selected = _ridge_candidate("0.1")
    captured: dict[str, object] = {}

    def selector(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return selected, (selected,)

    monkeypatch.setattr(
        final,
        "select_final_occupancy_stable_ridge",
        selector,
    )

    build_archive_final_calibration(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=tmp_path / "output",
    )

    assert captured["allow_coin_calibration"] is True


def test_final_calibration_rejects_no_eligible_ridge_recipe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan()
    _install_plan(monkeypatch, plan=plan)
    losing = _ridge_candidate(
        "0.1",
        trades=10,
        mean=Decimal("-0.001"),
        thresholds=((900_000, None),),
    )
    monkeypatch.setattr(
        final,
        "select_final_stable_horizon_ridge",
        lambda *args, **kwargs: (None, (losing,)),
    )

    with pytest.raises(
        HistoricalArchiveFinalCalibrationError,
        match="ARCHIVE_FINAL_CALIBRATION_NO_ELIGIBLE_RECIPE",
    ):
        build_archive_final_calibration(
            JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=tmp_path / "output",
        )


def test_final_tree_calibration_must_clear_frozen_floor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan(family="stable_tree")
    _install_plan(monkeypatch, plan=plan)
    validation = SimpleNamespace(
        horizons=_horizons(((900_000, None),)),
        evaluation=_evaluation(
            trades=10,
            mean=Decimal("-0.001"),
        ),
    )
    monkeypatch.setattr(
        final,
        "calibrate_final_stable_tree",
        lambda *args, **kwargs: validation,
    )

    with pytest.raises(
        HistoricalArchiveFinalCalibrationError,
        match="ARCHIVE_FINAL_CALIBRATION_NO_ELIGIBLE_RECIPE",
    ):
        build_archive_final_calibration(
            JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=tmp_path / "output",
        )


def test_final_tree_calibration_records_fixed_tree_recipe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan(family="stable_tree", calibration_variant="market")
    _install_plan(monkeypatch, plan=plan)
    validation = SimpleNamespace(
        horizons=_horizons(),
        evaluation=_evaluation(mean=Decimal("0.004")),
    )
    monkeypatch.setattr(
        final,
        "calibrate_final_stable_tree",
        lambda *args, **kwargs: validation,
    )

    result = build_archive_final_calibration(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=tmp_path / "output",
    )

    assert result.model_family == "stable_tree"
    assert result.calibration_variant == "market"
    assert result.selected_alpha is None
    assert len(result.candidates) == 1
    assert result.candidates[0].selected is True
    assert result.candidates[0].qualifies is True


def test_final_calibration_round_trips_and_detects_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan()
    _install_plan(monkeypatch, plan=plan)
    selected = _ridge_candidate("0.1", mean=Decimal("0.003"))
    monkeypatch.setattr(
        final,
        "select_final_stable_horizon_ridge",
        lambda *args, **kwargs: (selected, (selected,)),
    )
    output_root = tmp_path / "output"
    output_root.mkdir()
    result = build_archive_final_calibration(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )
    path = write_archive_final_calibration(output_root, result)

    verified = verify_archive_final_calibration(
        path,
        preset=JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    assert verified == result

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["selected_alpha"] = "10"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        HistoricalArchiveFinalCalibrationError,
        match="ARCHIVE_FINAL_CALIBRATION_EVIDENCE_MISMATCH",
    ):
        verify_archive_final_calibration(
            path,
            preset=JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
        )


def test_final_calibration_write_refuses_conflicting_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan()
    _install_plan(monkeypatch, plan=plan)
    selected = _ridge_candidate("0.1")
    monkeypatch.setattr(
        final,
        "select_final_stable_horizon_ridge",
        lambda *args, **kwargs: (selected, (selected,)),
    )
    output_root = tmp_path / "output"
    output_root.mkdir()
    result = build_archive_final_calibration(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )
    path = write_archive_final_calibration(output_root, result)
    path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(
        HistoricalArchiveFinalCalibrationError,
        match="ARCHIVE_FINAL_CALIBRATION_CONFLICT",
    ):
        write_archive_final_calibration(output_root, result)
