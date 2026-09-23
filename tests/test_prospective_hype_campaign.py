from __future__ import annotations

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V2,
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V3,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
    HYPE_PROSPECTIVE_VALIDATION_V2,
    HYPE_PROSPECTIVE_VALIDATION_V3,
)
from cocomelon.research.prospective_hype_campaign import (
    HYPE_PROSPECTIVE_CAMPAIGN_V1,
    HYPE_PROSPECTIVE_CAMPAIGN_V2,
    HYPE_PROSPECTIVE_CAMPAIGN_V3,
    resolve_prospective_hype_campaign,
)

DAY_MS = 86_400_000


def test_v2_preserves_economic_hypothesis_but_has_fresh_identity() -> None:
    v1 = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    v2 = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V2

    assert v2.candidate_id == "hype-down-bearish-near-basket-long-4h-v2"
    assert v2.spec_id != v1.spec_id
    assert v2.market == v1.market
    assert v2.anchor_interval == v1.anchor_interval
    assert v2.context_state_1h == v1.context_state_1h
    assert v2.direction == v1.direction
    assert v2.horizon_ms == v1.horizon_ms
    assert v2.discovery_start_ms == v1.discovery_start_ms
    assert v2.discovery_end_ms == v1.discovery_end_ms
    assert v2.discovery_report_id == v1.discovery_report_id
    assert v2.discovery_dataset_id == v1.discovery_dataset_id
    assert v2.occupancy_report_id == v1.occupancy_report_id
    assert v2.occupancy_dataset_id == v1.occupancy_dataset_id
    assert v2.costs == v1.costs
    assert v2.occupancy_mode == v1.occupancy_mode
    assert v2.validation_not_before_ms == 1_790_294_400_000


def test_v2_plan_preserves_thresholds_and_restarts_full_clean_window() -> None:
    v1 = HYPE_PROSPECTIVE_VALIDATION_V1
    v2 = HYPE_PROSPECTIVE_VALIDATION_V2

    assert v2.candidate_spec_id == HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V2.spec_id
    assert v2.plan_id != v1.plan_id
    assert v2.validation_start_ms == 1_790_294_400_000
    assert v2.validation_end_ms == v2.validation_start_ms + 45 * DAY_MS
    assert v2.horizon_ms == v1.horizon_ms
    assert v2.anchor_interval_ms == v1.anchor_interval_ms
    assert v2.anchor_end_offset_ms == v1.anchor_end_offset_ms
    assert v2.min_capture_coverage == v1.min_capture_coverage
    assert v2.min_settled_trades == v1.min_settled_trades
    assert v2.stability_blocks == v1.stability_blocks
    assert v2.min_block_trades == v1.min_block_trades
    assert v2.expected_anchor_count == 1080


def test_campaign_resolver_is_explicit_and_v1_remains_default_identity() -> None:
    assert resolve_prospective_hype_campaign("v1") is HYPE_PROSPECTIVE_CAMPAIGN_V1
    assert resolve_prospective_hype_campaign("v2") is HYPE_PROSPECTIVE_CAMPAIGN_V2


def test_v3_preserves_economic_hypothesis_but_has_fresh_identity() -> None:
    v2 = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V2
    v3 = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V3

    assert v3.candidate_id == "hype-down-bearish-near-basket-long-4h-v3"
    assert v3.spec_id != v2.spec_id
    assert v3.market == v2.market
    assert v3.anchor_interval == v2.anchor_interval
    assert v3.context_state_1h == v2.context_state_1h
    assert v3.direction == v2.direction
    assert v3.horizon_ms == v2.horizon_ms
    assert v3.discovery_start_ms == v2.discovery_start_ms
    assert v3.discovery_end_ms == v2.discovery_end_ms
    assert v3.discovery_report_id == v2.discovery_report_id
    assert v3.discovery_dataset_id == v2.discovery_dataset_id
    assert v3.occupancy_report_id == v2.occupancy_report_id
    assert v3.occupancy_dataset_id == v2.occupancy_dataset_id
    assert v3.costs == v2.costs
    assert v3.occupancy_mode == v2.occupancy_mode
    assert v3.validation_not_before_ms == 1_790_380_800_000


def test_v3_plan_restarts_full_clean_window_with_same_thresholds() -> None:
    v2 = HYPE_PROSPECTIVE_VALIDATION_V2
    v3 = HYPE_PROSPECTIVE_VALIDATION_V3

    assert v3.candidate_spec_id == HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V3.spec_id
    assert v3.plan_id != v2.plan_id
    assert v3.validation_start_ms == 1_790_380_800_000
    assert v3.validation_end_ms == v3.validation_start_ms + 45 * DAY_MS
    assert v3.horizon_ms == v2.horizon_ms
    assert v3.anchor_interval_ms == v2.anchor_interval_ms
    assert v3.anchor_end_offset_ms == v2.anchor_end_offset_ms
    assert v3.min_capture_coverage == v2.min_capture_coverage
    assert v3.min_settled_trades == v2.min_settled_trades
    assert v3.stability_blocks == v2.stability_blocks
    assert v3.min_block_trades == v2.min_block_trades
    assert v3.expected_anchor_count == 1080


def test_campaign_resolver_includes_v3_without_changing_v1_default() -> None:
    assert resolve_prospective_hype_campaign("v3") is HYPE_PROSPECTIVE_CAMPAIGN_V3
