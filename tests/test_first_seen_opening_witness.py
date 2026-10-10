from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
    ContinuousPaperRuntimeIdentity,
)
from cocomelon.research.first_seen_opening_witness import (
    FirstSeenOpeningWitnessError,
    first_seen_opening_witness_summary,
)


def _trade(
    plan: str,
    *,
    market: str = "ADA",
    direction: str = "short",
    opened: int = 300,
    closed: int = 500,
) -> SimpleNamespace:
    return SimpleNamespace(
        opening_plan_id=plan,
        market=SimpleNamespace(canonical=market),
        direction=SimpleNamespace(value=direction),
        opened_at_ms=opened,
        closed_at_ms=closed,
        feature_snapshot_id="feature-" + plan,
    )


def _lineage(trade: SimpleNamespace) -> ContinuousPaperOpeningLineage:
    return ContinuousPaperOpeningLineage(
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        opened_at_ms=trade.opened_at_ms,
        feature_snapshot_id=trade.feature_snapshot_id,
        runtime=ContinuousPaperRuntimeIdentity(
            worker_run_id=38075355685,
            worker_run_attempt=1,
            worker_head_sha="a" * 40,
        ),
    )


def _opportunity(
    *,
    timestamp: int = 400,
    direction: str = "short",
    market: str = "ADA",
    approved: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        opportunity_timestamp_ms=timestamp,
        market=market,
        direction=direction,
        baseline_risk_approved=approved,
    )


def test_real_original_opening_witness_is_counted_but_never_grants_promotion() -> None:
    trade = _trade("first-seen")
    witness = _lineage(trade)
    before = first_seen_opening_witness_summary(
        (_opportunity(),),
        (trade,),
        (),
        overlap_started_at_ms=100,
    )
    after = first_seen_opening_witness_summary(
        (_opportunity(),),
        (trade,),
        (witness,),
        overlap_started_at_ms=100,
    )
    assert before["future_finalized_overlap_opportunities"] == 1
    assert before["unwitnessed_overlap_opportunities"] == 1
    assert before["unique_missing_lineage_exposed_openings"] == 1
    assert after["future_finalized_overlap_opportunities"] == 1
    assert after["fully_lineage_witnessed_overlap_opportunities"] == 1
    assert after["unwitnessed_overlap_opportunities"] == 0
    assert after["unique_lineage_witnessed_exposed_openings"] == 1
    assert after["witness_lineage_id_sha256"] != before["witness_lineage_id_sha256"]
    assert after["event_time_attested_by_independent_archive"] is False
    assert after["decision_time_equivalence_verified"] is False
    assert after["historical_ledger_repair_authority"] is False
    assert after["research_readiness_grant"] is False
    assert after["execution_authority"] is False
    assert after["promotion_authority"] is False


def test_partial_witness_is_never_misreported_as_full_or_unwitnessed() -> None:
    first = _trade("first")
    second = _trade("second")
    report = first_seen_opening_witness_summary(
        (_opportunity(), _opportunity(approved=True)),
        (first, second),
        (_lineage(first),),
        overlap_started_at_ms=100,
    )
    assert report["future_finalized_overlap_opportunities"] == 2
    assert report["risk_approved_overlap_opportunities"] == 1
    assert report["risk_rejected_overlap_opportunities"] == 1
    assert report["partly_lineage_witnessed_overlap_opportunities"] == 2
    assert report["fully_lineage_witnessed_overlap_opportunities"] == 0
    assert report["unwitnessed_overlap_opportunities"] == 0
    assert report["unique_exposed_actual_openings"] == 2
    assert report["unique_missing_lineage_exposed_openings"] == 1


def test_source_witness_only_counts_actual_overlapping_market_side() -> None:
    t = _trade("opened")
    report = first_seen_opening_witness_summary(
        (
            _opportunity(timestamp=400),
            _opportunity(timestamp=600),
            _opportunity(direction="long"),
            _opportunity(market="ETH"),
            _opportunity(timestamp=250),
        ),
        (t,),
        (_lineage(t),),
        overlap_started_at_ms=100,
    )
    assert report["future_finalized_overlap_opportunities"] == 1
    assert report["fully_lineage_witnessed_overlap_opportunities"] == 1
    assert report["closed_trades_seen"] == 1


@pytest.mark.parametrize("field", ["market", "opened_at_ms", "feature_snapshot_id"])
def test_conflicting_persisted_opening_lineage_fails_closed(field: str) -> None:
    t = _trade("opening")
    witness = _lineage(t)
    bad = replace(
        witness,
        **{field: 777 if field == "opened_at_ms" else "different"},
    )
    with pytest.raises(
        FirstSeenOpeningWitnessError,
        match="conflicts with closed trade",
    ):
        first_seen_opening_witness_summary(
            (_opportunity(),), (t,), (bad,), overlap_started_at_ms=100
        )


def test_duplicate_openings_and_lineages_fail_closed() -> None:
    trade = _trade("duplicate")
    witness = _lineage(trade)
    with pytest.raises(FirstSeenOpeningWitnessError, match="duplicate first-seen"):
        first_seen_opening_witness_summary(
            (_opportunity(),), (trade,), (witness, witness),
            overlap_started_at_ms=100,
        )
    with pytest.raises(FirstSeenOpeningWitnessError, match="duplicate closed"):
        first_seen_opening_witness_summary(
            (_opportunity(),), (trade, trade), (witness,),
            overlap_started_at_ms=100,
        )


def test_invalid_overlap_start_is_rejected() -> None:
    with pytest.raises(FirstSeenOpeningWitnessError, match="nonnegative"):
        first_seen_opening_witness_summary(
            (), (), (), overlap_started_at_ms=-1
        )
