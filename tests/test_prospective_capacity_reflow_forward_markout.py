from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
    ContinuousPaperOpeningOpportunityPathMark,
)
from cocomelon.research.prospective_capacity_reflow_fill_feasibility import (
    candidate_caused_replacement_entry_fill_records,
)
from cocomelon.research.prospective_capacity_reflow_forward_markout import (
    ProspectiveCapacityReflowForwardMarkoutError,
    prospective_capacity_reflow_forward_markout_summary,
)
from tests.test_prospective_capacity_reflow_fill_feasibility import (
    _evidence,
    _history,
    _release,
)


def _fill_record():
    evidence = _evidence()
    return candidate_caused_replacement_entry_fill_records(
        (evidence,),
        (_release(evidence),),
        PaperExecutionConfig(),
        position_history_loader=_history,
    )[0]


def _path(
    *,
    direction: str = "short",
    complete: bool = True,
) -> ContinuousPaperOpeningOpportunityPath:
    record = _fill_record()
    marks = (
        ContinuousPaperOpeningOpportunityPathMark(
            observed_at_ms=10_500,
            mark_px=Decimal("99"),
            source="fixture",
        ),
    )
    if complete:
        marks = (
            *marks,
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=11_000,
                mark_px=Decimal("98"),
                source="fixture",
            ),
        )
    return ContinuousPaperOpeningOpportunityPath(
        opportunity_id=record.opportunity_id,
        market=record.opportunity_market,
        direction=direction,
        opportunity_timestamp_ms=record.opportunity_timestamp_ms,
        max_path_age_ms=1_000,
        max_completion_lag_ms=200,
        marks=marks,
    )


def test_forward_markout_uses_exact_partial_fill_and_completed_path() -> None:
    record = _fill_record()
    result = prospective_capacity_reflow_forward_markout_summary(
        (record,),
        (_path(),),
    )

    assert result["fillable_options"] == 1
    assert result["matched_paths"] == 1
    assert result["complete_markouts"] == 1
    assert result["pending_paths"] == 0
    assert result["missing_paths"] == 0
    assert result["positive_after_entry_fee_markouts"] == 1
    assert result["negative_after_entry_fee_markouts"] == 0
    assert result["flat_after_entry_fee_markouts"] == 0
    assert result["by_opportunity_market"] == {"SOL": 1}
    assert result["by_release_market"] == {"BTC": 1}
    assert Decimal(str(result["gross_markout_cash"])) > Decimal("0")
    assert (
        Decimal(str(result["after_entry_fee_markout_cash"]))
        < Decimal(str(result["gross_markout_cash"]))
    )
    completed = result["completed"]
    assert isinstance(completed, list)
    assert len(completed) == 1
    item = completed[0]
    assert item["opportunity_id"] == record.opportunity_id
    assert item["direction"] == "short"
    assert item["entry_vwap"] == str(record.average_fill_price)
    assert item["filled_quantity"] == str(record.filled_quantity)
    assert item["horizon_mark_px"] == "98"
    assert item["horizon_observed_at_ms"] == 11_000
    assert item["horizon_target_ms"] == 11_000
    assert item["observation_lag_ms"] == 0
    assert result["replacement_entry_fills_modeled"] is True
    assert result["forward_markouts_modeled"] is True
    assert result["replacement_exits_modeled"] is False
    assert result["replacement_trades_modeled"] is False
    assert result["pnl_modeled"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_forward_markout_waits_for_incomplete_path() -> None:
    record = _fill_record()
    result = prospective_capacity_reflow_forward_markout_summary(
        (record,),
        (_path(complete=False),),
    )

    assert result["fillable_options"] == 1
    assert result["matched_paths"] == 1
    assert result["complete_markouts"] == 0
    assert result["pending_paths"] == 1
    assert result["missing_paths"] == 0
    assert result["completed"] == []


def test_forward_markout_rejects_path_lineage_mismatch() -> None:
    record = _fill_record()

    with pytest.raises(
        ProspectiveCapacityReflowForwardMarkoutError,
        match="replacement markout path lineage mismatch",
    ):
        prospective_capacity_reflow_forward_markout_summary(
            (record,),
            (_path(direction="long"),),
        )
