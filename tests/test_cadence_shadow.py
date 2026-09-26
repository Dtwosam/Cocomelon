from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    FIVE_MINUTES_MS,
    CadenceShadowComparator,
    ShadowCadenceDecision,
    ShadowCadenceDecisionEngine,
    _initial_boundary_for_interval,
    settle_shadow_decision,
)

MARKET = MarketId("", "BTC")


def _gap(available_at_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=available_at_ms,
        source="test",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key=f"gap-{available_at_ms}",
        payload_json='{"stream_id":"test","started_ms":0,"ended_ms":null}',
        event_kind=None,
    )


def _sample(direction: Direction) -> ShadowCadenceDecision:
    return ShadowCadenceDecision(
        cadence_ms=FIVE_MINUTES_MS,
        boundary_ms=FIVE_MINUTES_MS,
        evaluated_at_ms=FIVE_MINUTES_MS + 30_000,
        market=MARKET,
        direction=direction,
        score=Decimal("70"),
        decision_id=f"decision-{direction.value}",
        feature_snapshot_id="feature-1",
        entry_px=Decimal("100"),
        horizon_ms=FIFTEEN_MINUTES_MS,
        target_end_ms=FIVE_MINUTES_MS + FIFTEEN_MINUTES_MS,
        cost_fraction=Decimal("0.0015"),
        off_primary_boundary=True,
    )


def test_initial_boundary_respects_interval_and_grace() -> None:
    assert _initial_boundary_for_interval(
        10_000,
        grace_ms=30_000,
        interval_ms=FIVE_MINUTES_MS,
    ) == 0
    assert _initial_boundary_for_interval(
        31_000,
        grace_ms=30_000,
        interval_ms=FIVE_MINUTES_MS,
    ) == FIVE_MINUTES_MS


def test_five_minute_shadow_clock_emits_more_epochs_than_primary_clock() -> None:
    config = BaselineReplayConfig()
    five = ShadowCadenceDecisionEngine(
        (MARKET,),
        replay_config=config,
        interval_ms=FIVE_MINUTES_MS,
    )
    fifteen = ShadowCadenceDecisionEngine(
        (MARKET,),
        replay_config=config,
        interval_ms=FIFTEEN_MINUTES_MS,
    )

    first = _gap(0)
    assert five.observe(first, 0) == ()
    assert fifteen.observe(first, 0) == ()

    after_first_grace = _gap(31_000)
    five_first = five.observe(after_first_grace, 31_000)
    fifteen_first = fifteen.observe(after_first_grace, 31_000)
    assert tuple(item.boundary_ms for item in five_first) == (0,)
    assert tuple(item.boundary_ms for item in fifteen_first) == (0,)

    after_five_minute_grace = _gap(FIVE_MINUTES_MS + 31_000)
    five_second = five.observe(
        after_five_minute_grace,
        FIVE_MINUTES_MS + 31_000,
    )
    fifteen_second = fifteen.observe(
        after_five_minute_grace,
        FIVE_MINUTES_MS + 31_000,
    )
    assert tuple(item.boundary_ms for item in five_second) == (
        FIVE_MINUTES_MS,
    )
    assert fifteen_second == ()


def test_shadow_settlement_applies_direction_and_frozen_costs() -> None:
    long = settle_shadow_decision(
        _sample(Direction.LONG),
        exit_px=Decimal("101"),
    )
    short = settle_shadow_decision(
        _sample(Direction.SHORT),
        exit_px=Decimal("99"),
    )

    assert long.gross_return == Decimal("0.01")
    assert long.net_return == Decimal("0.0085")
    assert short.gross_return == Decimal("0.01")
    assert short.net_return == Decimal("0.0085")


def test_shadow_sample_rejects_no_trade() -> None:
    with pytest.raises(ValueError, match="directional"):
        _sample(Direction.NO_TRADE)


def test_comparator_is_explicitly_non_economic_before_evidence() -> None:
    comparator = CadenceShadowComparator((MARKET,))
    payload = comparator.summary_payload()

    assert payload["shadow_only"] is True
    assert payload["execution_authority"] is False
    assert payload["primary_execution_cadence_ms"] == FIFTEEN_MINUTES_MS
    assert payload["candidate_cadence_ms"] == FIVE_MINUTES_MS
    assert payload["pending_outcome_count"] == 0
