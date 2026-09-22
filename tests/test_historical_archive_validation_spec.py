from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import cocomelon.research.historical_archive_validation_spec as validation
from cocomelon.research.historical_archive_presets import JUL_SEP_2026_V2
from cocomelon.research.historical_archive_validation_spec import (
    DECISION_POLICY,
    MIN_BLOCK_TRADES,
    MIN_CAPTURE_COVERAGE,
    MIN_SETTLED_TRADES,
    STABILITY_BLOCKS,
    VALIDATION_WINDOW_MS,
    HistoricalArchiveValidationSpecError,
    build_archive_clean_validation_spec,
    verify_archive_clean_validation_spec,
    write_archive_clean_validation_spec,
)

FIVE = 300_000


def _artifact(
    *,
    execution_policy: str = "portfolio_capacity",
    capacity: int | None = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="a" * 64,
        training_plan_id="b" * 64,
        calibration_id="c" * 64,
        artifact_id="d" * 64,
        model_payload_sha256="e" * 64,
        model_family="portfolio_capacity_stable_ridge",
        calibration_variant="market",
        model_format="ridge-directional-json-v1",
        selected_horizon_thresholds=(
            (900_000, Decimal("0.001")),
            (3_600_000, None),
            (14_400_000, Decimal("0.002")),
        ),
        allow_coin_calibration=True,
        min_sample_count=20,
        execution_policy=execution_policy,
        max_concurrent_positions=capacity,
        costs={
            "round_trip_fee_fraction": "0.0007",
            "round_trip_slippage_fraction": "0.0005",
            "funding_reserve_fraction_per_hour": "0.0001",
        },
        validation_not_before_ms=1_800_000_123_456,
    )


def _plan(artifact: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        plan_id=artifact.training_plan_id,
        candidate_id=artifact.candidate_id,
        model_family=artifact.model_family,
        calibration_variant=artifact.calibration_variant,
        validation_not_before_ms=artifact.validation_not_before_ms,
        anchor_interval="5m",
    )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    artifact: SimpleNamespace | None = None,
    plan: SimpleNamespace | None = None,
) -> tuple[SimpleNamespace, SimpleNamespace]:
    resolved_artifact = _artifact() if artifact is None else artifact
    resolved_plan = (
        _plan(resolved_artifact) if plan is None else plan
    )
    monkeypatch.setattr(
        validation,
        "verify_archive_candidate_model_artifact",
        lambda *args, **kwargs: resolved_artifact,
    )
    monkeypatch.setattr(
        validation,
        "verify_archive_candidate_training_plan",
        lambda *args, **kwargs: resolved_plan,
    )
    return resolved_artifact, resolved_plan


def test_clean_validation_spec_freezes_existing_prospective_standard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact, _plan_value = _install(monkeypatch)

    spec = build_archive_clean_validation_spec(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=tmp_path / "output",
    )

    assert spec.source_evidence_class == "touched_development"
    assert spec.validation_evidence_class == "prospective_clean"
    assert spec.candidate_id == artifact.candidate_id
    assert spec.model_artifact_id == artifact.artifact_id
    assert spec.model_payload_sha256 == artifact.model_payload_sha256
    assert spec.markets == ("BTC", "ETH", "HYPE", "SOL")
    assert spec.anchor_interval == "5m"
    assert spec.anchor_interval_ms == FIVE
    assert spec.anchor_end_offset_ms == FIVE - 1
    assert spec.horizon_thresholds == artifact.selected_horizon_thresholds
    assert spec.active_horizons == (900_000, 14_400_000)
    assert spec.maximum_active_horizon_ms == 14_400_000
    assert spec.decision_policy == DECISION_POLICY
    assert spec.execution_policy == "portfolio_capacity"
    assert spec.max_concurrent_positions == 2
    assert spec.validation_start_ms == artifact.validation_not_before_ms
    assert (
        spec.validation_end_ms - spec.validation_start_ms
        == VALIDATION_WINDOW_MS
    )
    assert spec.finalization_not_before_ms == (
        spec.validation_end_ms + 14_400_000
    )
    assert spec.min_capture_coverage == MIN_CAPTURE_COVERAGE
    assert spec.min_settled_trades == MIN_SETTLED_TRADES
    assert spec.stability_blocks == STABILITY_BLOCKS
    assert spec.min_block_trades == MIN_BLOCK_TRADES
    assert spec.expected_anchor_count == 12_960
    assert spec.anchors_per_stability_block == 3_240
    assert spec.paper_only is True
    assert spec.prospective_only is True
    assert spec.promotion_eligible is False
    assert spec.execution_ready is False
    assert len(spec.spec_id) == 64


def test_clean_validation_spec_rejects_model_plan_lineage_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = _artifact()
    drifted = _plan(candidate)
    drifted.plan_id = "9" * 64
    _install(monkeypatch, artifact=candidate, plan=drifted)

    with pytest.raises(
        HistoricalArchiveValidationSpecError,
        match="ARCHIVE_VALIDATION_SPEC_LINEAGE_MISMATCH",
    ):
        build_archive_clean_validation_spec(
            JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=tmp_path / "output",
        )


def test_clean_validation_spec_preserves_non_capacity_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = _artifact(
        execution_policy="single_position_occupancy",
        capacity=None,
    )
    candidate.model_family = "occupancy_stable_ridge"
    _install(monkeypatch, artifact=candidate)

    spec = build_archive_clean_validation_spec(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=tmp_path / "output",
    )

    assert spec.execution_policy == "single_position_occupancy"
    assert spec.max_concurrent_positions is None


def test_clean_validation_spec_round_trips_and_detects_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install(monkeypatch)
    output_root = tmp_path / "output"
    output_root.mkdir()

    spec = build_archive_clean_validation_spec(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )
    path = write_archive_clean_validation_spec(output_root, spec)

    verified = verify_archive_clean_validation_spec(
        path,
        preset=JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )
    assert verified == spec

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["min_settled_trades"] = 1
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveValidationSpecError,
        match="ARCHIVE_VALIDATION_SPEC_EVIDENCE_MISMATCH",
    ):
        verify_archive_clean_validation_spec(
            path,
            preset=JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
        )


def test_clean_validation_spec_write_refuses_conflicting_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install(monkeypatch)
    tmp_path.mkdir(exist_ok=True)
    spec = build_archive_clean_validation_spec(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=tmp_path,
    )
    path = write_archive_clean_validation_spec(tmp_path, spec)
    path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(
        HistoricalArchiveValidationSpecError,
        match="ARCHIVE_VALIDATION_SPEC_CONFLICT",
    ):
        write_archive_clean_validation_spec(tmp_path, spec)
