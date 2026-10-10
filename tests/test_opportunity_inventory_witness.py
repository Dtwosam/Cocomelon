from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.research.opportunity_inventory_witness import (
    OpportunityInventoryWitnessError,
    OpportunityInventoryWitnessStore,
    opportunity_inventory_witness,
    original_inventory_overlap_audit,
)


def _opportunity(
    identity: str = "private-original-opportunity",
    *,
    timestamp: int = 400,
    market: str = "ADA",
    direction: str = "short",
) -> SimpleNamespace:
    return SimpleNamespace(
        opportunity_id=identity,
        opportunity_timestamp_ms=timestamp,
        market=market,
        direction=direction,
    )


def _position(
    *,
    plan: str = "original-paper-plan",
    opened: int = 300,
    market: str = "ADA",
    direction: str = "short",
) -> SimpleNamespace:
    return SimpleNamespace(
        opening_plan_id=plan,
        opened_at_ms=opened,
        market=SimpleNamespace(canonical=market),
        side=SimpleNamespace(value=direction),
    )


def _trade(
    *,
    plan: str = "original-paper-plan",
    opened: int = 300,
    closed: int = 600,
    market: str = "ADA",
    direction: str = "short",
) -> SimpleNamespace:
    return SimpleNamespace(
        opening_plan_id=plan,
        opened_at_ms=opened,
        closed_at_ms=closed,
        market=SimpleNamespace(canonical=market),
        direction=SimpleNamespace(value=direction),
    )


def test_record_at_actual_opportunity_cannot_invent_future_position(
    tmp_path: Path,
) -> None:
    store = OpportunityInventoryWitnessStore(tmp_path)
    opp = _opportunity()
    positions = (
        _position(),
        _position(plan="not-yet-open", opened=400),
        _position(plan="later-open", opened=500),
        _position(plan="different-side", direction="long"),
        _position(plan="different-market", market="ETH"),
    )
    assert store.record(opp, positions, recorded_at_ms=405)
    record = store.iter_records()[0]
    assert len(record["prior_opening_plan_sha256"]) == 1
    assert record["opportunity_id"] == opp.opportunity_id
    assert record["independently_archived_before_opportunity"] is False
    assert record["original_filter_state_certified"] is False
    assert "original-paper-plan" not in json.dumps(record)
    assert "not-yet-open" not in json.dumps(record)
    assert store.record(opp, positions, recorded_at_ms=407) is False
    assert store.iter_records()[0]["recorded_at_ms"] == 405


def test_future_finalized_trade_matches_first_actual_position_census(
    tmp_path: Path,
) -> None:
    store = OpportunityInventoryWitnessStore(tmp_path)
    opp = _opportunity()
    store.record(opp, (_position(),), recorded_at_ms=405)
    report = original_inventory_overlap_audit(
        (opp,),
        (_trade(),),
        store.iter_records(),
        overlap_started_at_ms=100,
    )
    assert report["eligible_opportunity_count"] == 1
    assert report["later_finalized_overlap_opportunities"] == 1
    assert report["overlap_original_census_matches"] == 1
    assert report["overlap_missing_original_census"] == 0
    assert report["overlap_original_census_mismatches"] == 0
    assert report["independently_archived_before_opportunity"] is False
    assert report["research_readiness_grant"] is False
    assert report["promotion_authority"] is False
    assert "original-paper-plan" not in json.dumps(report)


def test_missing_or_wrong_original_census_never_automatically_passes(
    tmp_path: Path,
) -> None:
    store = OpportunityInventoryWitnessStore(tmp_path)
    opp1 = _opportunity()
    opp2 = _opportunity("second", timestamp=450)
    store.record(opp2, (_position(plan="different"),), recorded_at_ms=455)
    report = original_inventory_overlap_audit(
        (opp1, opp2),
        (_trade(),),
        store.iter_records(),
        overlap_started_at_ms=100,
    )
    assert report["later_finalized_overlap_opportunities"] == 2
    assert report["overlap_missing_original_census"] == 1
    assert report["overlap_original_census_mismatches"] == 1
    assert report["overlap_original_census_matches"] == 0
    assert report["decision_time_filter_state_verified"] is False


def test_census_is_append_only_and_fails_on_retroactive_rewrite(
    tmp_path: Path,
) -> None:
    store = OpportunityInventoryWitnessStore(tmp_path)
    opp = _opportunity()
    store.record(opp, (_position(),), recorded_at_ms=420)
    with pytest.raises(
        OpportunityInventoryWitnessError,
        match="first-seen opportunity census has changed",
    ):
        store.record(opp, (), recorded_at_ms=450)

    path = next((tmp_path / "records").glob("*.json"))
    doc = json.loads(path.read_text())
    doc["prior_opening_plan_sha256"] = []
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(OpportunityInventoryWitnessError, match="digest"):
        store.iter_records()


def test_market_side_and_close_clock_never_generate_false_overlap(
    tmp_path: Path,
) -> None:
    store = OpportunityInventoryWitnessStore(tmp_path)
    opp = _opportunity()
    store.record(opp, (), recorded_at_ms=401)
    records = store.iter_records()
    for trade in (
        _trade(closed=400),
        _trade(opened=400),
        _trade(market="BTC"),
        _trade(direction="long"),
    ):
        report = original_inventory_overlap_audit(
            (opp,), (trade,), records, overlap_started_at_ms=100
        )
        assert report["later_finalized_overlap_opportunities"] == 0


def test_census_conflicting_immutable_opportunity_fails_closed() -> None:
    first = _opportunity()
    witness = opportunity_inventory_witness(
        first, (_position(),), recorded_at_ms=405
    )
    with pytest.raises(
        OpportunityInventoryWitnessError,
        match="contradicts immutable opportunity",
    ):
        original_inventory_overlap_audit(
            (_opportunity(timestamp=420),),
            (_trade(),),
            (witness,),
            overlap_started_at_ms=100,
        )


@pytest.mark.parametrize("invalid", [-1, 399, True])
def test_invalid_observation_clocks_are_rejected(invalid: object) -> None:
    with pytest.raises(OpportunityInventoryWitnessError, match="observation time"):
        opportunity_inventory_witness(
            _opportunity(),
            (),
            recorded_at_ms=invalid,  # type: ignore[arg-type]
        )
