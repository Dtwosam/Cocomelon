from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.research.prospective_comparison_ledger import (
    update_comparison_ledger,
)
from cocomelon.research.prospective_prediction_ledger import (
    update_prediction_ledger,
)
from cocomelon.research.prospective_side_conditioned_delay import (
    ProspectiveSideConditionedDelayState,
)
from cocomelon.research.prospective_timing_ledger import (
    update_timing_ledger,
)
from cocomelon.research.prospective_trade_quality_readiness import (
    ProspectiveTradeQualityReadinessError,
    prospective_trade_quality_readiness,
)

START_MS = 1_790_776_800_000
TRAINING_DIGEST = "a" * 64
MICRO_MODEL = "cadence_microstructure_tree_prospective_v1"
BASELINE_MODEL = "cadence_fixed_shallow_tree_v1"


def _scored_rows(
    count: int,
    *,
    prediction: str = "0.01",
    realized: str = "0.01",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(count):
        direction = "long" if index % 2 == 0 else "short"
        rows.append(
            {
                "decision_id": f"decision-{index}",
                "boundary_ms": START_MS + index * 900_000,
                "market": f"M{index}",
                "direction": direction,
                "prediction_net_return": prediction,
                "admitted": Decimal(prediction) > Decimal("0"),
                "realized_net_return": realized,
            }
        )
    return rows


def _model_report(
    model_family: str,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "status": "completed",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "model_family": model_family,
        "prospective_start_ms": START_MS,
        "cadence_ms": 900_000,
        "horizon_ms": 3_600_000,
        "frozen_training_rows": 652,
        "frozen_training_rows_sha256": TRAINING_DIGEST,
        "scored_rows": rows,
    }


def _prediction_ledger(
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return update_prediction_ledger(
        _model_report(MICRO_MODEL, rows),
        previous=None,
        source_audit_run_id=10,
        source_audit_run_attempt=1,
        source_report_artifact_name="micro-report",
    )


def _comparison_ledger(
    micro_rows: list[dict[str, object]],
    *,
    baseline_rows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    baseline_rows = (
        micro_rows if baseline_rows is None else baseline_rows
    )
    comparison = {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "source_run_id": 20,
        "source_run_attempt": 1,
        "prospective_start_ms": START_MS,
        "frozen_training_rows": 652,
        "frozen_training_rows_sha256": TRAINING_DIGEST,
        "prospective_rows": len(micro_rows),
    }
    return update_comparison_ledger(
        comparison,
        _model_report(MICRO_MODEL, micro_rows),
        _model_report(BASELINE_MODEL, baseline_rows),
        previous=None,
        source_comparison_run_id=30,
        source_comparison_run_attempt=1,
        source_artifact_name="comparison-report",
    )


def _timing_rows(count: int) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for index in range(count):
        direction = "long" if index % 2 == 0 else "short"
        base = Decimal("1")
        challenger = Decimal("2")
        selected = challenger if direction == "long" else base
        actual = Decimal("0.5")
        rows.append(
            {
                "trade_id": f"trade-{index}",
                "market": f"T{index}",
                "direction": direction,
                "opened_at_ms": START_MS + index * 1_000,
                "closed_at_ms": START_MS + index * 1_000 + 500,
                "actual_net_pnl": str(actual),
                "base_60s_net_pnl": str(base),
                "challenger_120s_net_pnl": str(challenger),
                "selected_delay_ms": (
                    120_000 if direction == "long" else 60_000
                ),
                "selected_net_pnl": str(selected),
                "selected_fill_fraction": "1",
                "selected_minus_actual_pnl": str(selected - actual),
                "selected_minus_60s_pnl": str(selected - base),
            }
        )
    return tuple(rows)


def _timing_ledger(
    row_count: int,
    *,
    prospective_closed: int | None = None,
) -> dict[str, object]:
    rows = _timing_rows(row_count)
    closed = row_count if prospective_closed is None else prospective_closed
    diagnostics = {
        "prospective_closed_trades": closed,
        "paired_evaluable_trades": row_count,
        "missing_60s_outcomes": 0,
        "missing_120s_outcomes": 0,
        "non_evaluable_60s": 0,
        "non_evaluable_120s": 0,
        "lineage_mismatches": 0,
    }
    return update_timing_ledger(
        rows,
        diagnostics,
        ProspectiveSideConditionedDelayState(
            started_at_ms=START_MS,
        ),
        previous=None,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_timing_artifact_name="timing-state",
    )


def test_current_small_sample_is_collecting() -> None:
    rows = _scored_rows(3)
    result = prospective_trade_quality_readiness(
        _prediction_ledger(rows),
        _comparison_ledger(rows),
        _timing_ledger(0),
    )

    assert result["status"] == "collecting"
    assert result["any_candidate_ready_for_review"] is False
    cadence = result["cadence"]
    assert cadence["prospective_rows"] == 3
    assert cadence["missing"]["prospective_rows"] == 97
    timing = result["timing"]
    assert timing["missing"]["prospective_closed_trades"] == 30
    assert timing["missing"]["paired_evaluable_trades"] == 20
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_partial_cadence_sample_keeps_fixed_first_block() -> None:
    rows = _scored_rows(3)
    result = prospective_trade_quality_readiness(
        _prediction_ledger(rows),
        _comparison_ledger(rows),
        _timing_ledger(0),
    )

    blocks = result["cadence"]["stability_blocks"]
    assert blocks[0]["start_row"] == 1
    assert blocks[0]["end_row"] == 25
    assert blocks[0]["prospective_rows"] == 3
    assert blocks[0]["closed"] is False
    assert all(block["prospective_rows"] == 0 for block in blocks[1:])
    assert result["cadence"]["gate_path_open"] is True


def test_closed_bad_cadence_block_cannot_recover_later() -> None:
    rows = _scored_rows(
        25,
        prediction="0.01",
        realized="-0.01",
    )
    baseline = _scored_rows(
        25,
        prediction="-0.01",
        realized="-0.01",
    )
    result = prospective_trade_quality_readiness(
        _prediction_ledger(rows),
        _comparison_ledger(rows, baseline_rows=baseline),
        _timing_ledger(0),
    )

    cadence = result["cadence"]
    block = cadence["stability_blocks"][0]
    assert block["prospective_rows"] == 25
    assert block["closed"] is True
    assert block["passes"] is False
    assert cadence["closed_stability_blocks"] == 1
    assert cadence["failed_closed_stability_blocks"] == 1
    assert cadence["gate_path_open"] is False

    comparison = result["comparison"]
    increment = comparison["incremental_stability_blocks"][0]
    assert increment["paired_rows"] == 25
    assert increment["closed"] is True
    assert increment["passes"] is False
    assert comparison["failed_closed_incremental_blocks"] == 1
    assert comparison["maximum_allowed_failed_incremental_blocks"] == 1
    assert comparison["incremental_gate_path_open"] is True


def test_two_closed_bad_incremental_blocks_are_irrecoverable() -> None:
    micro_rows = _scored_rows(
        50,
        prediction="0.01",
        realized="-0.01",
    )
    baseline_rows = _scored_rows(
        50,
        prediction="-0.01",
        realized="-0.01",
    )
    result = prospective_trade_quality_readiness(
        _prediction_ledger(micro_rows),
        _comparison_ledger(
            micro_rows,
            baseline_rows=baseline_rows,
        ),
        _timing_ledger(0),
    )

    comparison = result["comparison"]
    assert comparison["closed_incremental_blocks"] == 2
    assert comparison["failed_closed_incremental_blocks"] == 2
    assert comparison["maximum_allowed_failed_incremental_blocks"] == 1
    assert comparison["incremental_gate_path_open"] is False


def test_failed_cadence_candidate_does_not_fail_collecting_timing() -> None:
    rows = _scored_rows(
        25,
        prediction="0.01",
        realized="-0.01",
    )
    baseline = _scored_rows(
        25,
        prediction="-0.01",
        realized="-0.01",
    )
    result = prospective_trade_quality_readiness(
        _prediction_ledger(rows),
        _comparison_ledger(rows, baseline_rows=baseline),
        _timing_ledger(0),
    )

    assert result["cadence"]["lifecycle_state"] == "failed_closed_block"
    assert result["timing"]["lifecycle_state"] == "collecting"
    assert result["status"] == "collecting"
    assert result["candidate_lifecycle"] == {
        "collecting": 1,
        "review_ready": 0,
        "failed_closed_block": 1,
    }
    assert (
        "standalone_stability"
        in result["cadence"]["irrecoverable_failure_components"]
    )


def test_all_candidates_failed_is_explicit() -> None:
    cadence_rows = _scored_rows(
        25,
        prediction="0.01",
        realized="-0.01",
    )
    baseline_rows = _scored_rows(
        25,
        prediction="-0.01",
        realized="-0.01",
    )
    timing_rows = list(_timing_rows(5))
    for index, row in enumerate(timing_rows):
        selected = Decimal(str(row["selected_net_pnl"]))
        actual = selected + Decimal("1")
        timing_rows[index] = {
            **row,
            "actual_net_pnl": str(actual),
            "selected_minus_actual_pnl": "-1",
        }
    timing = update_timing_ledger(
        tuple(timing_rows),
        {
            "prospective_closed_trades": 5,
            "paired_evaluable_trades": 5,
            "missing_60s_outcomes": 0,
            "missing_120s_outcomes": 0,
            "non_evaluable_60s": 0,
            "non_evaluable_120s": 0,
            "lineage_mismatches": 0,
        },
        ProspectiveSideConditionedDelayState(started_at_ms=START_MS),
        previous=None,
        source_paper_run_id=42,
        source_paper_run_attempt=1,
        source_timing_artifact_name="timing-failed-first-block",
    )

    result = prospective_trade_quality_readiness(
        _prediction_ledger(cadence_rows),
        _comparison_ledger(
            cadence_rows,
            baseline_rows=baseline_rows,
        ),
        timing,
    )

    assert result["status"] == "all_candidates_failed"
    assert result["candidate_lifecycle"] == {
        "collecting": 0,
        "review_ready": 0,
        "failed_closed_block": 2,
    }
    assert result["cadence"]["lifecycle_state"] == "failed_closed_block"
    assert result["timing"]["lifecycle_state"] == "failed_closed_block"
    assert result["timing"]["irrecoverable_failure_components"] == (
        "temporal_stability",
    )


def test_cadence_candidate_can_become_review_ready() -> None:
    rows = _scored_rows(100, prediction="0.01", realized="0.02")
    baseline_rows = _scored_rows(
        100,
        prediction="-0.01",
        realized="0.02",
    )
    result = prospective_trade_quality_readiness(
        _prediction_ledger(rows),
        _comparison_ledger(
            rows,
            baseline_rows=baseline_rows,
        ),
        _timing_ledger(0),
    )

    cadence = result["cadence"]
    comparison = result["comparison"]
    assert result["status"] == "review_ready"
    assert result["any_candidate_ready_for_review"] is True
    assert cadence["standalone_ready_for_review"] is True
    assert cadence["complexity_justified"] is True
    assert cadence["ready_for_review"] is True
    assert cadence["long_admitted_rows"] == 50
    assert cadence["short_admitted_rows"] == 50
    assert comparison["complexity_justified"] is True
    assert comparison["positive_incremental_blocks"] == 4
    assert all(
        block["passes"] is True
        for block in cadence["stability_blocks"]
    )
    assert result["authority"]["paper_execution_change_allowed"] is False


def test_profitable_complex_model_is_blocked_without_incremental_value() -> None:
    rows = _scored_rows(100, prediction="0.01", realized="0.02")
    result = prospective_trade_quality_readiness(
        _prediction_ledger(rows),
        _comparison_ledger(rows),
        _timing_ledger(0),
    )

    cadence = result["cadence"]
    comparison = result["comparison"]
    assert cadence["standalone_ready_for_review"] is True
    assert comparison["microstructure_minus_baseline_sum"] == "0.00"
    assert comparison["complexity_justified"] is False
    assert cadence["complexity_justified"] is False
    assert cadence["ready_for_review"] is False
    assert result["any_candidate_ready_for_review"] is False
    assert result["status"] == "collecting"


def test_positive_total_increment_needs_chronological_stability() -> None:
    micro_rows = _scored_rows(100, prediction="0.01", realized="0.02")
    baseline_rows: list[dict[str, object]] = []
    for index, row in enumerate(micro_rows):
        block = index // 25
        if block < 2:
            baseline_prediction = "-0.01"
            realized = "0.02"
        else:
            is_negative_micro_only = index % 5 == 0
            baseline_prediction = (
                "-0.01" if is_negative_micro_only else "0.01"
            )
            realized = "-0.01" if is_negative_micro_only else "0.02"
        micro_rows[index] = {
            **row,
            "realized_net_return": realized,
        }
        baseline_rows.append(
            {
                **micro_rows[index],
                "prediction_net_return": baseline_prediction,
                "admitted": Decimal(baseline_prediction) > Decimal("0"),
            }
        )

    result = prospective_trade_quality_readiness(
        _prediction_ledger(micro_rows),
        _comparison_ledger(
            micro_rows,
            baseline_rows=baseline_rows,
        ),
        _timing_ledger(0),
    )

    cadence = result["cadence"]
    comparison = result["comparison"]
    assert cadence["standalone_ready_for_review"] is True
    assert Decimal(
        comparison["microstructure_minus_baseline_sum"]
    ) > Decimal("0")
    assert comparison["positive_incremental_blocks"] == 2
    assert comparison["complexity_justified"] is False
    assert cadence["ready_for_review"] is False


def test_closed_bad_timing_block_cannot_recover_later() -> None:
    rows = list(_timing_rows(5))
    for index, row in enumerate(rows):
        selected = Decimal(str(row["selected_net_pnl"]))
        actual = selected + Decimal("1")
        rows[index] = {
            **row,
            "actual_net_pnl": str(actual),
            "selected_minus_actual_pnl": "-1",
        }
    diagnostics = {
        "prospective_closed_trades": 5,
        "paired_evaluable_trades": 5,
        "missing_60s_outcomes": 0,
        "missing_120s_outcomes": 0,
        "non_evaluable_60s": 0,
        "non_evaluable_120s": 0,
        "lineage_mismatches": 0,
    }
    ledger = update_timing_ledger(
        tuple(rows),
        diagnostics,
        ProspectiveSideConditionedDelayState(started_at_ms=START_MS),
        previous=None,
        source_paper_run_id=41,
        source_paper_run_attempt=1,
        source_timing_artifact_name="timing-first-block-bad",
    )
    cadence_rows = _scored_rows(3, prediction="-0.01", realized="0.01")
    result = prospective_trade_quality_readiness(
        _prediction_ledger(cadence_rows),
        _comparison_ledger(cadence_rows),
        ledger,
    )

    timing = result["timing"]
    block = timing["temporal_blocks"][0]
    assert block["start_row"] == 1
    assert block["end_row"] == 5
    assert block["rows"] == 5
    assert block["closed"] is True
    assert block["passes"] is False
    assert timing["closed_temporal_blocks"] == 1
    assert timing["failed_closed_temporal_blocks"] == 1
    assert timing["gate_path_open"] is False


def test_timing_candidate_can_become_review_ready_independently() -> None:
    rows = _scored_rows(3, prediction="-0.01", realized="0.01")
    result = prospective_trade_quality_readiness(
        _prediction_ledger(rows),
        _comparison_ledger(rows),
        _timing_ledger(20, prospective_closed=30),
    )

    assert result["cadence"]["ready_for_review"] is False
    timing = result["timing"]
    assert timing["ready_for_review"] is True
    assert timing["sample_complete"] is True
    assert timing["economics_pass"] is True
    assert timing["long_rows"] == 10
    assert timing["short_rows"] == 10
    assert timing["integrity_clean"] is True
    assert all(
        block["passes"] is True
        for block in timing["temporal_blocks"]
    )
    assert (
        timing["market_robustness"][
            "positive_vs_60s_after_any_single_market_removed"
        ]
        is True
    )
    assert result["status"] == "review_ready"


def test_timing_counts_alone_cannot_make_losing_candidate_ready() -> None:
    timing_rows = list(_timing_rows(20))
    for index, row in enumerate(timing_rows):
        selected = Decimal(str(row["selected_net_pnl"]))
        actual = selected + Decimal("1")
        timing_rows[index] = {
            **row,
            "actual_net_pnl": str(actual),
            "selected_minus_actual_pnl": "-1",
        }
    diagnostics = {
        "prospective_closed_trades": 30,
        "paired_evaluable_trades": 20,
        "missing_60s_outcomes": 0,
        "missing_120s_outcomes": 0,
        "non_evaluable_60s": 0,
        "non_evaluable_120s": 0,
        "lineage_mismatches": 0,
    }
    ledger = update_timing_ledger(
        tuple(timing_rows),
        diagnostics,
        ProspectiveSideConditionedDelayState(started_at_ms=START_MS),
        previous=None,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_timing_artifact_name="timing-losing",
    )
    cadence_rows = _scored_rows(3, prediction="-0.01", realized="0.01")
    result = prospective_trade_quality_readiness(
        _prediction_ledger(cadence_rows),
        _comparison_ledger(cadence_rows),
        ledger,
    )

    timing = result["timing"]
    assert timing["sample_complete"] is True
    assert timing["integrity_clean"] is True
    assert timing["economics_pass"] is False
    assert timing["ready_for_review"] is False
    assert result["status"] == "collecting"


def test_timing_total_gain_needs_temporal_robustness() -> None:
    timing_rows = list(_timing_rows(20))
    for index, row in enumerate(timing_rows):
        block = index // 5
        if block < 3:
            continue
        base = Decimal(str(row["base_60s_net_pnl"]))
        challenger = Decimal(str(row["challenger_120s_net_pnl"]))
        if row["direction"] == "long":
            challenger = Decimal("0")
            selected = challenger
        else:
            selected = base
        actual = selected + Decimal("2")
        timing_rows[index] = {
            **row,
            "actual_net_pnl": str(actual),
            "challenger_120s_net_pnl": str(challenger),
            "selected_net_pnl": str(selected),
            "selected_minus_actual_pnl": str(selected - actual),
            "selected_minus_60s_pnl": str(selected - base),
        }
    diagnostics = {
        "prospective_closed_trades": 30,
        "paired_evaluable_trades": 20,
        "missing_60s_outcomes": 0,
        "missing_120s_outcomes": 0,
        "non_evaluable_60s": 0,
        "non_evaluable_120s": 0,
        "lineage_mismatches": 0,
    }
    ledger = update_timing_ledger(
        tuple(timing_rows),
        diagnostics,
        ProspectiveSideConditionedDelayState(started_at_ms=START_MS),
        previous=None,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_timing_artifact_name="timing-unstable",
    )
    cadence_rows = _scored_rows(3, prediction="-0.01", realized="0.01")
    result = prospective_trade_quality_readiness(
        _prediction_ledger(cadence_rows),
        _comparison_ledger(cadence_rows),
        ledger,
    )

    timing = result["timing"]
    assert timing["sample_complete"] is True
    assert timing["ready_for_review"] is False
    assert timing["economics_pass"] is False
    assert any(
        block["passes"] is False
        for block in timing["temporal_blocks"]
    )


def test_prediction_and_ab_ledgers_must_match_exactly() -> None:
    prediction_rows = _scored_rows(3)
    comparison_rows = _scored_rows(3)
    comparison_rows[0] = {
        **comparison_rows[0],
        "prediction_net_return": "0.02",
        "admitted": True,
    }

    with pytest.raises(
        ProspectiveTradeQualityReadinessError,
        match="cadence ledger row mismatch",
    ):
        prospective_trade_quality_readiness(
            _prediction_ledger(prediction_rows),
            _comparison_ledger(comparison_rows),
            _timing_ledger(0),
        )
