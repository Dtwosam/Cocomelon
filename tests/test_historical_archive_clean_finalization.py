from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.historical_archive_clean_checkpoint import (
    ArchiveCleanBlockEconomics,
    ArchiveCleanOperationalCheckpoint,
)
from cocomelon.research.historical_archive_clean_evidence import (
    ArchiveCleanCampaignManifest,
)
from cocomelon.research.historical_archive_clean_finalization import (
    VERDICT_ELIGIBLE,
    VERDICT_FAILED,
    HistoricalArchiveCleanFinalizationError,
    build_archive_clean_finalization,
    verify_archive_clean_finalization,
    write_archive_clean_finalization,
)
from cocomelon.research.historical_archive_paper_scorer import (
    ArchivePaperState,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
)
from cocomelon.research.prospective_context_evidence import (
    PROSPECTIVE_EVIDENCE_CLASS,
)

FIFTEEN = 900_000
DAY_MS = 86_400_000
RUNTIME_ID = "7" * 64
PIN_ID = "8" * 64


def _spec() -> HistoricalArchiveCleanValidationSpec:
    return HistoricalArchiveCleanValidationSpec(
        preset_name="test-preset",
        preset_id="preset-id",
        source_evidence_class="touched_development",
        validation_evidence_class=PROSPECTIVE_EVIDENCE_CLASS,
        candidate_id="a" * 64,
        training_plan_id="b" * 64,
        calibration_id="c" * 64,
        model_artifact_id="d" * 64,
        model_payload_sha256="e" * 64,
        model_family="stable_horizon_ridge",
        calibration_variant="shared",
        model_format="ridge-directional-json-v1",
        markets=("BTC", "ETH"),
        anchor_interval="15m",
        anchor_interval_ms=FIFTEEN,
        anchor_end_offset_ms=FIFTEEN - 1,
        horizon_thresholds=((FIFTEEN, Decimal("0.001")),),
        allow_coin_calibration=False,
        min_sample_count=20,
        decision_policy="cost_adjusted_directional_threshold_v1",
        execution_policy="independent_horizon",
        max_concurrent_positions=None,
        costs={
            "round_trip_fee_fraction": "0.0007",
            "round_trip_slippage_fraction": "0.0005",
            "funding_reserve_fraction_per_hour": "0.0001",
        },
        validation_start_ms=0,
        validation_end_ms=45 * DAY_MS,
        min_capture_coverage=Decimal("0.90"),
        min_settled_trades=80,
        stability_blocks=4,
        min_block_trades=15,
        min_mean_net_return=Decimal("0"),
        min_block_mean_net_return=Decimal("0"),
    )


def _campaign_id(spec: HistoricalArchiveCleanValidationSpec) -> str:
    return ArchiveCleanCampaignManifest(
        validation_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        model_artifact_id=spec.model_artifact_id,
        model_payload_sha256=spec.model_payload_sha256,
        markets=spec.markets,
        active_horizons=spec.active_horizons,
        validation_start_ms=spec.validation_start_ms,
        validation_end_ms=spec.validation_end_ms,
        finalization_not_before_ms=spec.finalization_not_before_ms,
        expected_anchor_count=spec.expected_anchor_count,
    ).campaign_id


def _blocks(
    *,
    trades_per_block: int = 20,
    net_per_block: str = "0.20",
) -> tuple[ArchiveCleanBlockEconomics, ...]:
    net = Decimal(net_per_block)
    cost = Decimal("0.02")
    gross = net + cost
    return tuple(
        ArchiveCleanBlockEconomics(
            block_index=index,
            settled_trade_count=trades_per_block,
            long_trade_count=trades_per_block // 2,
            short_trade_count=trades_per_block - (trades_per_block // 2),
            gross_return_sum=gross,
            modeled_cost_sum=cost,
            net_return_sum=net,
        )
        for index in range(4)
    )


def _checkpoint(
    spec: HistoricalArchiveCleanValidationSpec,
    *,
    blocks: tuple[ArchiveCleanBlockEconomics, ...] | None = None,
    captured_anchor_count: int | None = None,
    as_of_ms: int | None = None,
) -> ArchiveCleanOperationalCheckpoint:
    resolved_blocks = blocks or _blocks()
    captured = (
        spec.expected_anchor_count
        if captured_anchor_count is None
        else captured_anchor_count
    )
    bitmap = (1 << captured) - 1 if captured else 0
    latest_anchor = (
        None
        if captured == 0
        else spec.first_expected_anchor_ms
        + (captured - 1) * spec.anchor_interval_ms
    )
    return ArchiveCleanOperationalCheckpoint(
        validation_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        model_artifact_id=spec.model_artifact_id,
        campaign_id=_campaign_id(spec),
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
        first_expected_anchor_ms=spec.first_expected_anchor_ms,
        anchor_interval_ms=spec.anchor_interval_ms,
        expected_anchor_count=spec.expected_anchor_count,
        stability_blocks=spec.stability_blocks,
        anchors_per_stability_block=spec.anchors_per_stability_block,
        captured_bitmap_hex=format(bitmap, "x"),
        latest_anchor_end_ms=latest_anchor,
        latest_observation_id=(None if latest_anchor is None else "f" * 64),
        latest_state=ArchivePaperState(),
        pending_observations=(),
        settled_outcome_count=sum(
            item.settled_trade_count for item in resolved_blocks
        ),
        block_economics=resolved_blocks,
        as_of_ms=(
            spec.finalization_not_before_ms
            if as_of_ms is None
            else as_of_ms
        ),
    )


def test_terminal_finalization_passes_only_when_every_frozen_gate_passes() -> None:
    spec = _spec()
    checkpoint = _checkpoint(spec)

    finalization = build_archive_clean_finalization(
        spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
        checkpoint=checkpoint,
        finalized_at_ms=spec.finalization_not_before_ms + 1,
    )

    assert finalization.verdict == VERDICT_ELIGIBLE
    assert finalization.eligible_for_candidate_review is True
    assert finalization.reason_codes == ()
    assert finalization.capture_coverage == Decimal("1")
    assert finalization.settled_trade_count == 80
    assert finalization.mean_net_return == Decimal("0.01")
    assert all(item.passes_trade_floor for item in finalization.block_results)
    assert all(item.passes_mean_floor for item in finalization.block_results)
    assert finalization.promotion_eligible is False
    assert finalization.execution_ready is False
    assert finalization.paper_only is True
    assert len(finalization.finalization_id) == 64


def test_terminal_finalization_rejects_undertraded_campaign_and_blocks() -> None:
    spec = _spec()
    checkpoint = _checkpoint(
        spec,
        blocks=_blocks(trades_per_block=10, net_per_block="0.10"),
    )

    finalization = build_archive_clean_finalization(
        spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
        checkpoint=checkpoint,
        finalized_at_ms=spec.finalization_not_before_ms,
    )

    assert finalization.verdict == VERDICT_FAILED
    assert finalization.eligible_for_candidate_review is False
    assert finalization.mean_net_return == Decimal("0.01")
    assert finalization.reason_codes == (
        "block_0_trade_count_below_minimum",
        "block_1_trade_count_below_minimum",
        "block_2_trade_count_below_minimum",
        "block_3_trade_count_below_minimum",
        "settled_trade_count_below_minimum",
    )


def test_terminal_finalization_rejects_one_negative_stability_block() -> None:
    spec = _spec()
    blocks = list(_blocks())
    blocks[2] = ArchiveCleanBlockEconomics(
        block_index=2,
        settled_trade_count=20,
        long_trade_count=10,
        short_trade_count=10,
        gross_return_sum=Decimal("0"),
        modeled_cost_sum=Decimal("0.02"),
        net_return_sum=Decimal("-0.02"),
    )
    checkpoint = _checkpoint(spec, blocks=tuple(blocks))

    finalization = build_archive_clean_finalization(
        spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
        checkpoint=checkpoint,
        finalized_at_ms=spec.finalization_not_before_ms,
    )

    assert finalization.mean_net_return is not None
    assert finalization.mean_net_return > Decimal("0")
    assert finalization.verdict == VERDICT_FAILED
    assert finalization.reason_codes == (
        "block_2_mean_net_return_not_above_minimum",
    )


def test_terminal_finalization_rejects_low_capture_coverage() -> None:
    spec = _spec()
    captured = int(
        Decimal(spec.expected_anchor_count) * Decimal("0.89")
    )
    checkpoint = _checkpoint(spec, captured_anchor_count=captured)

    finalization = build_archive_clean_finalization(
        spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
        checkpoint=checkpoint,
        finalized_at_ms=spec.finalization_not_before_ms,
    )

    assert finalization.capture_coverage < spec.min_capture_coverage
    assert "capture_coverage_below_minimum" in finalization.reason_codes
    assert finalization.verdict == VERDICT_FAILED


def test_terminal_finalization_fails_closed_before_terminal_boundary() -> None:
    spec = _spec()
    checkpoint = _checkpoint(spec)

    with pytest.raises(
        HistoricalArchiveCleanFinalizationError,
        match="ARCHIVE_CLEAN_FINALIZATION_PREMATURE",
    ):
        build_archive_clean_finalization(
            spec,
            runtime_id=RUNTIME_ID,
            pin_id=PIN_ID,
            checkpoint=checkpoint,
            finalized_at_ms=spec.finalization_not_before_ms - 1,
        )


def test_terminal_finalization_rejects_stale_checkpoint() -> None:
    spec = _spec()
    checkpoint = _checkpoint(
        spec,
        as_of_ms=spec.finalization_not_before_ms - 1,
    )

    with pytest.raises(
        HistoricalArchiveCleanFinalizationError,
        match="ARCHIVE_CLEAN_FINALIZATION_CHECKPOINT_STALE",
    ):
        build_archive_clean_finalization(
            spec,
            runtime_id=RUNTIME_ID,
            pin_id=PIN_ID,
            checkpoint=checkpoint,
            finalized_at_ms=spec.finalization_not_before_ms,
        )


def test_terminal_finalization_rejects_campaign_lineage_drift() -> None:
    spec = _spec()
    checkpoint = replace(_checkpoint(spec), campaign_id="9" * 64)

    with pytest.raises(
        HistoricalArchiveCleanFinalizationError,
        match="ARCHIVE_CLEAN_FINALIZATION_LINEAGE_MISMATCH",
    ):
        build_archive_clean_finalization(
            spec,
            runtime_id=RUNTIME_ID,
            pin_id=PIN_ID,
            checkpoint=checkpoint,
            finalized_at_ms=spec.finalization_not_before_ms,
        )


def test_finalization_write_verify_and_tamper_detection(
    tmp_path: Path,
) -> None:
    spec = _spec()
    checkpoint = _checkpoint(spec)
    finalization = build_archive_clean_finalization(
        spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
        checkpoint=checkpoint,
        finalized_at_ms=spec.finalization_not_before_ms,
    )
    path = write_archive_clean_finalization(tmp_path, finalization)

    verified = verify_archive_clean_finalization(
        path,
        spec=spec,
        runtime_id=RUNTIME_ID,
        pin_id=PIN_ID,
        checkpoint=checkpoint,
    )
    assert verified == finalization
    assert write_archive_clean_finalization(tmp_path, finalization) == path

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["verdict"] = VERDICT_FAILED
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HistoricalArchiveCleanFinalizationError,
        match="ARCHIVE_CLEAN_FINALIZATION_EVIDENCE_MISMATCH",
    ):
        verify_archive_clean_finalization(
            path,
            spec=spec,
            runtime_id=RUNTIME_ID,
            pin_id=PIN_ID,
            checkpoint=checkpoint,
        )
