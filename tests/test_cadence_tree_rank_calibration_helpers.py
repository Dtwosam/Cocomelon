from __future__ import annotations

from decimal import Decimal

from cocomelon.research.cadence_tree_rank_calibration import (
    CadenceTreeCalibrationConfig,
    _BandStats,
    _rank_band,
    _selected_bands,
)


def test_rank_band_maps_higher_predictions_to_lower_band_index() -> None:
    reference = tuple(
        Decimal(value)
        for value in ("5", "4", "3", "2", "1")
    )

    assert _rank_band(
        Decimal("6"),
        reference,
        band_count=5,
    ) == 0
    assert _rank_band(
        Decimal("4.5"),
        reference,
        band_count=5,
    ) == 1
    assert _rank_band(
        Decimal("0"),
        reference,
        band_count=5,
    ) == 4


def test_selected_bands_use_only_positive_calibration_lower_bounds() -> None:
    stats = {
        0: _BandStats(
            rows=20,
            total=Decimal("0.20"),
            total_sq=Decimal("0.01"),
            long_rows=10,
            short_rows=10,
        ),
        1: _BandStats(
            rows=20,
            total=Decimal("0.01"),
            total_sq=Decimal("0.04"),
            long_rows=10,
            short_rows=10,
        ),
        2: _BandStats(
            rows=10,
            total=Decimal("0.30"),
            total_sq=Decimal("0.02"),
            long_rows=5,
            short_rows=5,
        ),
    }
    config = CadenceTreeCalibrationConfig(
        calibration_rows=40,
        band_count=3,
        min_band_rows=15,
        standard_error_multiplier=Decimal("1"),
    )

    selected = _selected_bands(stats, config=config)

    assert selected == (0,)
