from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("numpy")
pytest.importorskip("sklearn")

import cocomelon.research.historical_archive_model_artifact as artifact
from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_archive_model_artifact import (
    RIDGE_MODEL_FORMAT,
    TREE_MODEL_FORMAT,
    HistoricalArchiveCandidateModelArtifact,
    HistoricalArchiveModelArtifactError,
    build_archive_candidate_model_artifact,
    load_archive_candidate_model_artifact,
    predict_archive_candidate_model,
    verify_archive_candidate_model_artifact,
    write_archive_candidate_model_artifact,
)
from cocomelon.research.historical_archive_presets import JUL_SEP_2026_V2
from cocomelon.research.historical_features import (
    HistoricalFeatureRow,
    HistoricalTrainingRow,
)
from cocomelon.research.historical_learning import DirectionalOutcome
from cocomelon.research.historical_ridge import fit_ridge_directional_model
from cocomelon.research.historical_tree import (
    TreeModelConfig,
    fit_tree_directional_model,
)

BTC = MarketId(dex="", coin="BTC")
ETH = MarketId(dex="", coin="ETH")
FIVE = 300_000


def _feature(
    *,
    market: MarketId,
    anchor_index: int,
    momentum: Decimal,
) -> HistoricalFeatureRow:
    anchor_end_ms = anchor_index * FIVE
    return HistoricalFeatureRow(
        market=market,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=momentum,
        return_15m=momentum / Decimal("2"),
        return_1h=momentum,
        return_4h=momentum * Decimal("2"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        funding_rate=Decimal("0.0001"),
        funding_change=Decimal("0.00001"),
        funding_premium=Decimal("0.0002"),
        funding_premium_change=Decimal("0.00001"),
        funding_age_ms=0,
        candle_15m_age_ms=0,
        trend_regime=(
            TrendRegime.UP if momentum >= 0 else TrendRegime.DOWN
        ),
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=99_000_000,
        retrieved_after_anchor=True,
        available_features=(),
        unavailable_features=(),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-a",),
    )


def _row(
    *,
    market: MarketId,
    anchor_index: int,
    momentum: Decimal,
    long_return: Decimal,
) -> HistoricalTrainingRow:
    feature = _feature(
        market=market,
        anchor_index=anchor_index,
        momentum=momentum,
    )
    return HistoricalTrainingRow(
        feature=feature,
        outcome=DirectionalOutcome(
            market=market,
            interval="5m",
            anchor_end_ms=feature.anchor_end_ms,
            target_end_ms=feature.anchor_end_ms + FIVE,
            horizon_ms=FIVE,
            entry_px=Decimal("100"),
            exit_px=Decimal("100") * (Decimal("1") + long_return),
            long_gross_return=long_return,
            short_gross_return=-long_return,
            provenance=("hyperliquid-mainnet-info",),
        ),
    )


def _artifact(
    *,
    model_family: str,
    model_format: str,
    model_payload: dict[str, object],
    selected_alpha: Decimal | None,
    calibration_variant: str = "shared",
) -> HistoricalArchiveCandidateModelArtifact:
    policy = {
        "stable_horizon_ridge": "independent_horizon",
        "occupancy_stable_ridge": "single_position_occupancy",
        "portfolio_capacity_stable_ridge": "portfolio_capacity",
        "stable_tree": "independent_horizon",
    }[model_family]
    return HistoricalArchiveCandidateModelArtifact(
        preset_name=JUL_SEP_2026_V2.name,
        preset_id=JUL_SEP_2026_V2.preset_id,
        evidence_class="touched_development",
        candidate_id="a" * 64,
        training_plan_id="b" * 64,
        calibration_id="c" * 64,
        bundle_id="d" * 64,
        dataset_id="e" * 64,
        model_family=model_family,
        calibration_variant=calibration_variant,
        model_format=model_format,
        model_payload=model_payload,
        model_payload_sha256=artifact._sha256_json(model_payload),
        selected_candidate_sha256="f" * 64,
        selected_alpha=selected_alpha,
        selected_horizon_thresholds=((FIVE, Decimal("0.001")),),
        allow_coin_calibration=calibration_variant == "market",
        min_sample_count=20,
        min_market_samples=int(model_payload["min_market_samples"]),
        execution_policy=policy,
        max_concurrent_positions=(
            2 if model_family == "portfolio_capacity_stable_ridge" else None
        ),
        costs={
            "round_trip_fee_fraction": "0.0007",
            "round_trip_slippage_fraction": "0.0005",
            "funding_reserve_fraction_per_hour": "0.0001",
        },
        numpy_version="test-numpy",
        scikit_learn_version="test-sklearn",
        validation_not_before_ms=99_000_000,
    )


def test_ridge_json_artifact_reproduces_shared_and_market_predictions() -> None:
    rows = tuple(
        _row(
            market=market,
            anchor_index=index,
            momentum=Decimal(index - 7) / Decimal("100"),
            long_return=(
                Decimal("0.02") if market == BTC else Decimal("-0.01")
            ),
        )
        for index, market in enumerate(
            (BTC, BTC, BTC, BTC, ETH, ETH, ETH, ETH),
            start=1,
        )
    )
    model = fit_ridge_directional_model(
        rows,
        alpha=Decimal("0.1"),
        min_market_samples=3,
    )
    payload = artifact._ridge_payload(model)
    frozen_market = _artifact(
        model_family="stable_horizon_ridge",
        model_format=RIDGE_MODEL_FORMAT,
        model_payload=payload,
        selected_alpha=Decimal("0.1"),
        calibration_variant="market",
    )
    frozen_shared = _artifact(
        model_family="stable_horizon_ridge",
        model_format=RIDGE_MODEL_FORMAT,
        model_payload=payload,
        selected_alpha=Decimal("0.1"),
    )
    feature = _feature(
        market=BTC,
        anchor_index=20,
        momentum=Decimal("0.03"),
    )

    expected_market = model.predict(
        feature,
        horizon_ms=FIVE,
        allow_coin_calibration=True,
    )
    expected_shared = model.predict(
        feature,
        horizon_ms=FIVE,
        allow_coin_calibration=False,
    )

    assert predict_archive_candidate_model(
        frozen_market,
        feature,
        horizon_ms=FIVE,
    ) == expected_market.expected_long_return
    assert predict_archive_candidate_model(
        frozen_shared,
        feature,
        horizon_ms=FIVE,
    ) == expected_shared.expected_long_return


def test_tree_json_artifact_reproduces_sklearn_prediction() -> None:
    rows = tuple(
        _row(
            market=BTC,
            anchor_index=index,
            momentum=Decimal(index - 11) / Decimal("100"),
            long_return=(
                Decimal("0.03")
                if abs(Decimal(index - 11) / Decimal("100"))
                >= Decimal("0.05")
                else Decimal("-0.03")
            ),
        )
        for index in range(1, 22)
    )
    model = fit_tree_directional_model(
        rows,
        config=TreeModelConfig(
            max_leaf_nodes=7,
            min_samples_leaf=2,
            learning_rate=Decimal("0.1"),
            max_iter=20,
            l2_regularization=Decimal("0.1"),
        ),
        min_market_samples=100,
    )
    payload = artifact._tree_payload(model)
    frozen = _artifact(
        model_family="stable_tree",
        model_format=TREE_MODEL_FORMAT,
        model_payload=payload,
        selected_alpha=None,
    )
    feature = _feature(
        market=BTC,
        anchor_index=30,
        momentum=Decimal("0.08"),
    )

    expected = model.predict(
        feature,
        horizon_ms=FIVE,
        allow_coin_calibration=False,
    ).expected_long_return
    actual = predict_archive_candidate_model(
        frozen,
        feature,
        horizon_ms=FIVE,
    )

    assert abs(actual - expected) <= Decimal("1e-12")


def test_build_model_artifact_binds_calibration_and_family_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calibration = SimpleNamespace(
        candidate_id="a" * 64,
        training_plan_id="b" * 64,
        calibration_id="c" * 64,
        bundle_id="d" * 64,
        dataset_id="e" * 64,
        model_family="portfolio_capacity_stable_ridge",
        calibration_variant="market",
        selected_candidate_sha256="f" * 64,
        selected_alpha=Decimal("0.1"),
        selected_horizon_thresholds=((900_000, Decimal("0.001")),),
        validation_not_before_ms=99_000_000,
    )
    plan = SimpleNamespace(
        candidate_id=calibration.candidate_id,
        plan_id=calibration.training_plan_id,
        bundle_id=calibration.bundle_id,
        dataset_id=calibration.dataset_id,
        model_family=calibration.model_family,
        calibration_variant=calibration.calibration_variant,
        validation_not_before_ms=calibration.validation_not_before_ms,
    )
    fake_model = SimpleNamespace(
        alpha=Decimal("0.1"),
        min_market_samples=100,
        horizons={},
    )
    monkeypatch.setattr(
        artifact,
        "verify_archive_final_calibration",
        lambda *args, **kwargs: calibration,
    )
    monkeypatch.setattr(
        artifact,
        "verify_archive_candidate_training_plan",
        lambda *args, **kwargs: plan,
    )
    monkeypatch.setattr(
        artifact,
        "materialize_archive_candidate_training_rows",
        lambda *args, **kwargs: ((object(),), (object(),), (object(),)),
    )
    monkeypatch.setattr(
        artifact,
        "fit_ridge_directional_model",
        lambda *args, **kwargs: fake_model,
    )
    monkeypatch.setattr(
        artifact,
        "_ridge_payload",
        lambda _model: {
            "format": RIDGE_MODEL_FORMAT,
            "alpha": "0.1",
            "min_market_samples": 100,
            "numeric_features": (),
            "trend_regimes": (),
            "horizons": ({"horizon_ms": 900_000},),
        },
    )
    monkeypatch.setattr(
        artifact,
        "_versions",
        lambda: ("numpy-test", "sklearn-test"),
    )

    result = build_archive_candidate_model_artifact(
        JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=tmp_path / "output",
    )

    assert result.candidate_id == calibration.candidate_id
    assert result.calibration_id == calibration.calibration_id
    assert result.model_family == "portfolio_capacity_stable_ridge"
    assert result.model_format == RIDGE_MODEL_FORMAT
    assert result.allow_coin_calibration is True
    assert result.execution_policy == "portfolio_capacity"
    assert result.max_concurrent_positions == 2
    assert result.selected_alpha == Decimal("0.1")
    assert result.trained_model_persisted is True
    assert result.execution_ready is False
    assert result.promotion_eligible is False
    assert len(result.artifact_id) == 64



def test_model_artifact_runtime_loader_does_not_rebuild_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = _artifact(
        model_family="stable_horizon_ridge",
        model_format=RIDGE_MODEL_FORMAT,
        model_payload={
            "format": RIDGE_MODEL_FORMAT,
            "alpha": "0.1",
            "min_market_samples": 3,
            "numeric_features": (),
            "trend_regimes": (),
            "horizons": ({"horizon_ms": FIVE},),
        },
        selected_alpha=Decimal("0.1"),
    )
    path = write_archive_candidate_model_artifact(tmp_path, expected)
    monkeypatch.setattr(
        artifact,
        "build_archive_candidate_model_artifact",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("runtime loader must not rebuild historical model")
        ),
    )

    loaded = load_archive_candidate_model_artifact(path)

    assert loaded == expected
    assert loaded.artifact_id == expected.artifact_id


def test_model_artifact_runtime_loader_rejects_internal_tampering(
    tmp_path: Path,
) -> None:
    expected = _artifact(
        model_family="stable_horizon_ridge",
        model_format=RIDGE_MODEL_FORMAT,
        model_payload={
            "format": RIDGE_MODEL_FORMAT,
            "alpha": "0.1",
            "min_market_samples": 3,
            "numeric_features": (),
            "trend_regimes": (),
            "horizons": ({"horizon_ms": FIVE},),
        },
        selected_alpha=Decimal("0.1"),
    )
    path = write_archive_candidate_model_artifact(tmp_path, expected)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["execution_policy"] = "tampered"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveModelArtifactError,
        match="ARCHIVE_MODEL_ARTIFACT_INVALID",
    ):
        load_archive_candidate_model_artifact(path)

def test_model_artifact_round_trips_and_detects_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = _artifact(
        model_family="stable_horizon_ridge",
        model_format=RIDGE_MODEL_FORMAT,
        model_payload={
            "format": RIDGE_MODEL_FORMAT,
            "alpha": "0.1",
            "min_market_samples": 3,
            "numeric_features": (),
            "trend_regimes": (),
            "horizons": ({"horizon_ms": FIVE},),
        },
        selected_alpha=Decimal("0.1"),
    )
    monkeypatch.setattr(
        artifact,
        "build_archive_candidate_model_artifact",
        lambda *args, **kwargs: expected,
    )
    output_root = tmp_path / "output"
    output_root.mkdir()
    path = write_archive_candidate_model_artifact(output_root, expected)

    verified = verify_archive_candidate_model_artifact(
        path,
        preset=JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=output_root,
    )

    assert verified == expected
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["execution_policy"] = "tampered"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        HistoricalArchiveModelArtifactError,
        match="ARCHIVE_MODEL_ARTIFACT_EVIDENCE_MISMATCH",
    ):
        verify_archive_candidate_model_artifact(
            path,
            preset=JUL_SEP_2026_V2,
            archive_root=tmp_path / "archive",
            source_root=tmp_path / "sources",
            output_root=output_root,
        )


def test_model_artifact_write_refuses_conflicting_overwrite(
    tmp_path: Path,
) -> None:
    value = _artifact(
        model_family="stable_horizon_ridge",
        model_format=RIDGE_MODEL_FORMAT,
        model_payload={
            "format": RIDGE_MODEL_FORMAT,
            "alpha": "0.1",
            "min_market_samples": 3,
            "numeric_features": (),
            "trend_regimes": (),
            "horizons": ({"horizon_ms": FIVE},),
        },
        selected_alpha=Decimal("0.1"),
    )
    tmp_path.mkdir(exist_ok=True)
    path = write_archive_candidate_model_artifact(tmp_path, value)
    path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(
        HistoricalArchiveModelArtifactError,
        match="ARCHIVE_MODEL_ARTIFACT_CONFLICT",
    ):
        write_archive_candidate_model_artifact(tmp_path, value)
