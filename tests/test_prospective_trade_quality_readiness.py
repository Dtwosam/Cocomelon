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


def test_cadence_candidate_can_become_review_ready() -> None:
    rows = _scored_rows(100, prediction="0.01", realized="0.02")
    result = prospective_trade_quality_readiness(
        _prediction_ledger(rows),
        _comparison_ledger(rows),
        _timing_ledger(0),
    )

    cadence = result["cadence"]
    assert result["status"] == "review_ready"
    assert result["any_candidate_ready_for_review"] is True
    assert cadence["ready_for_review"] is True
    assert cadence["long_admitted_rows"] == 50
    assert cadence["short_admitted_rows"] == 50
    assert all(
        block["passes"] is True
        for block in cadence["stability_blocks"]
    )
    assert result["authority"]["paper_execution_change_allowed"] is False


def test_timing_candidate_can_be_review_ready_independently() -> None:
    rows = _scored_rows(3, prediction="-0.01", realized="0.01")
    result = prospective_trade_quality_readiness(
        _prediction_ledger(rows),
        _comparison_ledger(rows),
        _timing_ledger(20, prospective_closed=30),
    )

    assert result["cadence"]["ready_for_review"] is False
    timing = result["timing"]
    assert timing["ready_for_review"] is True
    assert timing["long_rows"] == 10
    assert timing["short_rows"] == 10
    assert timing["integrity_clean"] is True
    assert result["status"] == "review_ready"


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
