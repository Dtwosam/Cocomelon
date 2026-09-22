from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

import cocomelon.research.historical_archive_presets as presets
from cocomelon.research.historical_archive_presets import (
    JUL_SEP_2026_V2,
    get_archive_experiment_preset,
    run_archive_experiment_preset,
)
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
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
    sentinel = object()

    def fake_run(client: object, **kwargs: object) -> object:
        captured["client"] = client
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(presets, "run_archive_historical_experiment", fake_run)
    client = object()

    def clock() -> int:
        return 123

    result = run_archive_experiment_preset(
        client,  # type: ignore[arg-type]
        preset=JUL_SEP_2026_V2,
        archive_root=tmp_path / "archive",
        source_root=tmp_path / "sources",
        output_root=tmp_path / "output",
        clock_ms=clock,
    )

    assert result is sentinel
    assert captured["markets"] == JUL_SEP_2026_V2.markets
    assert captured["intervals"] == JUL_SEP_2026_V2.intervals
    assert captured["horizons_ms"] == JUL_SEP_2026_V2.horizons_ms
    assert captured["start_ms"] == JUL_SEP_2026_V2.start_ms
    assert captured["end_ms"] == JUL_SEP_2026_V2.end_ms
    assert captured["config"] == JUL_SEP_2026_V2.comparison_config
    assert captured["max_funding_items"] == JUL_SEP_2026_V2.max_funding_items
    assert captured["overlap_candles"] == JUL_SEP_2026_V2.overlap_candles
