from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.market import Candle, MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    FIVE_MINUTES_MS,
    CadenceShadowComparator,
    ShadowCadenceDecision,
    ShadowCadenceDecisionEngine,
    _five_minute_close_boundary_ms,
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
        lead_strategy="trend",
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



def test_hyperliquid_inclusive_candle_end_maps_to_exact_boundary() -> None:
    candle = Candle(
        market=MARKET,
        interval="5m",
        start_ms=0,
        end_ms=FIVE_MINUTES_MS - 1,
        open_px=Decimal("100"),
        high_px=Decimal("101"),
        low_px=Decimal("99"),
        close_px=Decimal("100.5"),
        volume=Decimal("10"),
        trade_count=5,
        source="hyperliquid-mainnet",
        received_at_ms=FIVE_MINUTES_MS + 1_000,
        schema_version=1,
    )
    assert _five_minute_close_boundary_ms(candle) == FIVE_MINUTES_MS


def test_shadow_settlement_uses_hyperliquid_close_boundary_not_raw_T() -> None:
    comparator = CadenceShadowComparator((MARKET,))
    sample = _sample(Direction.LONG)
    comparator._pending[(MARKET.canonical, sample.target_end_ms)].append(sample)

    target_start = sample.target_end_ms - FIVE_MINUTES_MS
    candle = Candle(
        market=MARKET,
        interval="5m",
        start_ms=target_start,
        end_ms=sample.target_end_ms - 1,
        open_px=Decimal("100"),
        high_px=Decimal("102"),
        low_px=Decimal("99"),
        close_px=Decimal("101"),
        volume=Decimal("10"),
        trade_count=5,
        source="hyperliquid-mainnet",
        received_at_ms=sample.target_end_ms + 1_000,
        schema_version=1,
    )
    comparator._settle_candle(candle)
    payload = comparator.summary_payload()
    cadence = payload["cadences"]["300000"]
    horizon = cadence["outcomes_by_horizon_ms"]["900000"]
    assert horizon["settled_count"] == 1
    assert horizon["mean_net_return"] == "0.0085"

    by_strategy = cadence["outcomes_by_lead_strategy_by_horizon_ms"]["900000"]
    assert by_strategy["trend"]["settled_count"] == 1
    assert by_strategy["trend"]["mean_net_return"] == "0.0085"

    by_score = cadence["outcomes_by_score_band_by_horizon_ms"]["900000"]
    assert by_score["70-<75"]["settled_count"] == 1
    assert by_score["70-<75"]["positive_net_count"] == 1


def test_shadow_state_round_trip_preserves_pending_and_settled_evidence() -> None:
    comparator = CadenceShadowComparator((MARKET,))
    pending = _sample(Direction.LONG)
    settled_sample = _sample(Direction.SHORT)
    settled = settle_shadow_decision(
        settled_sample,
        exit_px=Decimal("99"),
    )

    comparator._pending[
        (pending.market.canonical, pending.target_end_ms)
    ].append(pending)
    comparator._outcomes.append(settled)
    comparator._decision_counts[FIVE_MINUTES_MS][Direction.LONG.value] = 1
    comparator._decision_counts[FIVE_MINUTES_MS][Direction.SHORT.value] = 1
    comparator._directional_counts_by_lead_strategy[FIVE_MINUTES_MS][
        "trend"
    ][Direction.LONG.value] = 1
    comparator._directional_counts_by_lead_strategy[FIVE_MINUTES_MS][
        "trend"
    ][Direction.SHORT.value] = 1
    comparator._directional_counts_by_score_band[FIVE_MINUTES_MS][
        "70-<75"
    ][Direction.LONG.value] = 1
    comparator._directional_counts_by_score_band[FIVE_MINUTES_MS][
        "70-<75"
    ][Direction.SHORT.value] = 1
    comparator._seen_decisions.update(
        {
            (FIVE_MINUTES_MS, pending.decision_id),
            (FIVE_MINUTES_MS, settled_sample.decision_id),
        }
    )

    state = comparator.state_payload()
    restored = CadenceShadowComparator((MARKET,))
    restored.restore_state(state)
    summary = restored.summary_payload()

    assert summary["session_only"] is False
    assert summary["durable_state"] is True
    assert summary["state_restored"] is True
    assert summary["state_restore_error"] is None
    assert summary["pending_outcome_count"] == 1
    cadence = summary["cadences"]["300000"]
    assert cadence["decision_counts"]["long"] == 1
    assert cadence["decision_counts"]["short"] == 1
    outcome = cadence["outcomes_by_horizon_ms"]["900000"]
    assert outcome["settled_count"] == 1
    assert outcome["mean_net_return"] == "0.0085"

    target_start = pending.target_end_ms - FIVE_MINUTES_MS
    restored._settle_candle(
        Candle(
            market=MARKET,
            interval="5m",
            start_ms=target_start,
            end_ms=pending.target_end_ms - 1,
            open_px=Decimal("100"),
            high_px=Decimal("102"),
            low_px=Decimal("99"),
            close_px=Decimal("101"),
            volume=Decimal("10"),
            trade_count=5,
            source="hyperliquid-mainnet",
            received_at_ms=pending.target_end_ms + 1_000,
            schema_version=1,
        )
    )
    after = restored.summary_payload()
    assert after["pending_outcome_count"] == 0
    assert after["cadences"]["300000"]["outcomes_by_horizon_ms"]["900000"][
        "settled_count"
    ] == 2


def test_shadow_state_rejects_runtime_cost_mismatch() -> None:
    comparator = CadenceShadowComparator((MARKET,))
    state = comparator.state_payload()
    costs = state["costs"]
    assert isinstance(costs, dict)
    costs["round_trip_fee_fraction"] = "0.5"

    restored = CadenceShadowComparator((MARKET,))
    with pytest.raises(ValueError, match="costs do not match"):
        restored.restore_state(state)
