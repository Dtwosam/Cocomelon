from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from cocomelon.domain.market import Candle, MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
    ProspectiveContextDecision,
)
from cocomelon.research.prospective_context_evidence import (
    ProspectiveEvidenceConsistencyError,
    ProspectiveEvidenceStore,
    build_prospective_observation,
    build_prospective_outcome,
    candle_identity,
)

HYPE = MarketId("", "HYPE")
HOUR = 3_600_000
FOUR_HOURS = 14_400_000
CUTOVER = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.validation_not_before_ms


def _decision(
    *,
    as_of_ms: int,
    direction: Direction = Direction.LONG,
    reason: str = "frozen_historical_context_match",
) -> ProspectiveContextDecision:
    return ProspectiveContextDecision(
        candidate_spec_id=HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.spec_id,
        market=HYPE,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms - 1_000,
        direction=direction,
        hold_until_ms=None if direction is Direction.NO_TRADE else as_of_ms + FOUR_HOURS,
        context_state_1h=(
            "down/bearish/near_basket"
            if direction is Direction.LONG
            else "up/bullish/near_basket"
        ),
        feature_snapshot_id="feature-1",
        cross_market_snapshot_id="cross-1",
        reason_codes=(reason,),
    )


def _candle(*, end_ms: int, close: str, received_at_ms: int | None = None) -> Candle:
    return Candle(
        market=HYPE,
        interval="1h",
        start_ms=end_ms - HOUR + 1,
        end_ms=end_ms,
        open_px=Decimal(close),
        high_px=Decimal(close),
        low_px=Decimal(close),
        close_px=Decimal(close),
        volume=Decimal("1000"),
        trade_count=100,
        source="hyperliquid-mainnet-info",
        received_at_ms=end_ms + 1_000 if received_at_ms is None else received_at_ms,
        schema_version=1,
    )


def test_first_matching_context_becomes_effective_long() -> None:
    anchor_end = CUTOVER + HOUR
    decision = _decision(as_of_ms=anchor_end + 5_000)
    entry = _candle(end_ms=anchor_end, close="50")

    observation = build_prospective_observation(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
        raw_decision=decision,
        entry_candle=entry,
        prior_observations=(),
    )

    assert observation.raw_direction is Direction.LONG
    assert observation.effective_direction is Direction.LONG
    assert observation.entry_px == Decimal("50")
    assert observation.anchor_end_ms == anchor_end
    assert observation.target_end_ms == anchor_end + FOUR_HOURS
    assert observation.hold_until_ms == anchor_end + FOUR_HOURS
    assert observation.occupancy_blocked_by_observation_id is None
    assert observation.modeled_cost_fraction == Decimal("0.0016")
    assert len(observation.observation_id) == 24
    assert observation.entry_candle_id == candle_identity(entry)


def test_repeated_match_is_blocked_until_prior_four_hour_position_expires() -> None:
    first_anchor = CUTOVER + HOUR
    first = build_prospective_observation(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
        raw_decision=_decision(as_of_ms=first_anchor + 5_000),
        entry_candle=_candle(end_ms=first_anchor, close="50"),
        prior_observations=(),
    )
    second_anchor = first_anchor + HOUR
    second = build_prospective_observation(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
        raw_decision=_decision(as_of_ms=second_anchor + 5_000),
        entry_candle=_candle(end_ms=second_anchor, close="51"),
        prior_observations=(first,),
    )

    assert second.raw_direction is Direction.LONG
    assert second.effective_direction is Direction.NO_TRADE
    assert second.hold_until_ms is None
    assert second.occupancy_blocked_by_observation_id == first.observation_id
    assert second.reason_codes[-1] == "one_position_per_market_occupied"

    next_anchor = first.target_end_ms
    third = build_prospective_observation(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
        raw_decision=_decision(as_of_ms=next_anchor + 5_000),
        entry_candle=_candle(end_ms=next_anchor, close="52"),
        prior_observations=(first, second),
    )
    assert third.effective_direction is Direction.LONG


def test_context_mismatch_remains_no_trade_without_occupancy_side_effects() -> None:
    anchor_end = CUTOVER + HOUR
    observation = build_prospective_observation(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
        raw_decision=_decision(
            as_of_ms=anchor_end + 5_000,
            direction=Direction.NO_TRADE,
            reason="context_mismatch",
        ),
        entry_candle=_candle(end_ms=anchor_end, close="50"),
        prior_observations=(),
    )

    assert observation.raw_direction is Direction.NO_TRADE
    assert observation.effective_direction is Direction.NO_TRADE
    assert observation.hold_until_ms is None
    assert observation.reason_codes == ("context_mismatch",)


def test_entry_candle_must_be_recent_closed_hourly_hype_candle() -> None:
    anchor_end = CUTOVER + HOUR
    decision = _decision(as_of_ms=anchor_end + 5_000)

    with pytest.raises(ValueError, match="1h"):
        build_prospective_observation(
            HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
            raw_decision=decision,
            entry_candle=replace(_candle(end_ms=anchor_end, close="50"), interval="15m"),
            prior_observations=(),
        )

    with pytest.raises(ValueError, match="received after decision"):
        build_prospective_observation(
            HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
            raw_decision=decision,
            entry_candle=_candle(
                end_ms=anchor_end,
                close="50",
                received_at_ms=decision.as_of_ms + 1,
            ),
            prior_observations=(),
        )

    with pytest.raises(ValueError, match="stale"):
        build_prospective_observation(
            HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
            raw_decision=decision,
            entry_candle=_candle(end_ms=anchor_end - HOUR, close="50"),
            prior_observations=(),
        )


def test_directional_observation_scores_only_exact_future_hourly_close() -> None:
    anchor_end = CUTOVER + HOUR
    observation = build_prospective_observation(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
        raw_decision=_decision(as_of_ms=anchor_end + 5_000),
        entry_candle=_candle(end_ms=anchor_end, close="50"),
        prior_observations=(),
    )

    with pytest.raises(ValueError, match="target candle end"):
        build_prospective_outcome(
            HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
            observation=observation,
            exit_candle=_candle(
                end_ms=observation.target_end_ms - HOUR,
                close="55",
            ),
        )

    outcome = build_prospective_outcome(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
        observation=observation,
        exit_candle=_candle(end_ms=observation.target_end_ms, close="55"),
    )

    assert outcome.gross_return == Decimal("0.1")
    assert outcome.modeled_cost_fraction == Decimal("0.0016")
    assert outcome.net_return == Decimal("0.0984")
    assert outcome.entry_px == Decimal("50")
    assert outcome.exit_px == Decimal("55")
    assert outcome.exit_candle_id
    assert len(outcome.outcome_id) == 24


def test_no_trade_observation_cannot_be_scored() -> None:
    anchor_end = CUTOVER + HOUR
    observation = build_prospective_observation(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
        raw_decision=_decision(
            as_of_ms=anchor_end + 5_000,
            direction=Direction.NO_TRADE,
            reason="context_mismatch",
        ),
        entry_candle=_candle(end_ms=anchor_end, close="50"),
        prior_observations=(),
    )

    with pytest.raises(ValueError, match="directional observation"):
        build_prospective_outcome(
            HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
            observation=observation,
            exit_candle=_candle(end_ms=anchor_end + FOUR_HOURS, close="55"),
        )


def test_store_is_idempotent_and_tracks_due_unsettled_observations(tmp_path) -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    store = ProspectiveEvidenceStore(tmp_path, spec=spec)
    anchor_end = CUTOVER + HOUR
    observation = build_prospective_observation(
        spec,
        raw_decision=_decision(as_of_ms=anchor_end + 5_000),
        entry_candle=_candle(end_ms=anchor_end, close="50"),
        prior_observations=(),
    )

    first_path = store.record_observation(observation)
    second_path = store.record_observation(observation)

    assert first_path == second_path
    assert store.load_observation(observation.observation_id) == observation
    assert store.due_unsettled_observations(as_of_ms=observation.target_end_ms - 1) == ()
    assert store.due_unsettled_observations(
        as_of_ms=observation.target_end_ms
    ) == (observation,)

    outcome = build_prospective_outcome(
        spec,
        observation=observation,
        exit_candle=_candle(end_ms=observation.target_end_ms, close="55"),
    )
    store.record_outcome(outcome)

    assert store.load_outcome(outcome.outcome_id) == outcome
    assert store.due_unsettled_observations(
        as_of_ms=observation.target_end_ms
    ) == ()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["candidate_spec_id"] == spec.spec_id
    assert manifest["basket_markets"] == ["BTC", "ETH", "HYPE", "SOL"]
    assert manifest["evidence_class"] == "prospective_clean"
    assert manifest["promotion_eligible"] is False


def test_store_rejects_conflicting_existing_record_and_wrong_spec(tmp_path) -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    store = ProspectiveEvidenceStore(tmp_path, spec=spec)
    anchor_end = CUTOVER + HOUR
    observation = build_prospective_observation(
        spec,
        raw_decision=_decision(as_of_ms=anchor_end + 5_000),
        entry_candle=_candle(end_ms=anchor_end, close="50"),
        prior_observations=(),
    )
    path = store.record_observation(observation)
    path.write_text('{"corrupted":true}\n', encoding="utf-8")

    with pytest.raises(ProspectiveEvidenceConsistencyError, match="conflicting"):
        store.record_observation(observation)

    changed = replace(spec, context_state_1h="down/mixed/near_basket")
    with pytest.raises(ProspectiveEvidenceConsistencyError, match="campaign manifest"):
        ProspectiveEvidenceStore(tmp_path, spec=changed)



def test_directional_clean_entry_anchor_cannot_predate_cutover() -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    anchor_end = CUTOVER - 1
    decision = _decision(as_of_ms=CUTOVER + 5_000)

    with pytest.raises(ValueError, match="predates prospective cutover"):
        build_prospective_observation(
            spec,
            raw_decision=decision,
            entry_candle=_candle(end_ms=anchor_end, close="50"),
            prior_observations=(),
        )
