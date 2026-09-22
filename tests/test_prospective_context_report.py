from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_evidence import (
    ProspectiveCampaignManifest,
    ProspectiveObservation,
    ProspectiveOutcome,
)
from cocomelon.research.prospective_campaign_health import (
    ProspectiveCampaignHealthStatus,
    build_prospective_campaign_health,
)
from cocomelon.research.prospective_context_report import (
    DAY_MS,
    HOUR_MS,
    HYPE_PROSPECTIVE_VALIDATION_V1,
    ProspectiveValidationError,
    ProspectiveValidationStatus,
    build_prospective_validation_report,
)

HYPE = MarketId("", "HYPE")
SPEC = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
PLAN = HYPE_PROSPECTIVE_VALIDATION_V1
COST = Decimal("0.0016")


@dataclass
class FakeStore:
    observations: tuple[ProspectiveObservation, ...]
    outcomes: tuple[ProspectiveOutcome, ...]
    spec = SPEC
    manifest = ProspectiveCampaignManifest(
        candidate_spec_id=SPEC.spec_id,
        candidate_id=SPEC.candidate_id,
        validation_not_before_ms=SPEC.validation_not_before_ms,
    )

    def iter_observations(self) -> tuple[ProspectiveObservation, ...]:
        return self.observations

    def iter_outcomes(self) -> tuple[ProspectiveOutcome, ...]:
        return self.outcomes


def _observation(anchor_ms: int, *, trade: bool) -> ProspectiveObservation:
    return ProspectiveObservation(
        candidate_spec_id=SPEC.spec_id,
        raw_decision_id=f"decision-{anchor_ms}",
        market=HYPE,
        decision_as_of_ms=anchor_ms + 5 * 60_000,
        source_received_at_ms=anchor_ms + 60_000,
        anchor_end_ms=anchor_ms,
        target_end_ms=anchor_ms + SPEC.horizon_ms,
        raw_direction=Direction.LONG if trade else Direction.NO_TRADE,
        effective_direction=Direction.LONG if trade else Direction.NO_TRADE,
        hold_until_ms=anchor_ms + SPEC.horizon_ms if trade else None,
        context_state_1h=(
            SPEC.context_state_1h if trade else "up/bullish/near_basket"
        ),
        feature_snapshot_id=f"feature-{anchor_ms}",
        cross_market_snapshot_id=f"cross-{anchor_ms}",
        entry_candle_id=f"entry-{anchor_ms}",
        entry_px=Decimal("100"),
        modeled_cost_fraction=COST,
        reason_codes=(
            ("frozen_historical_context_match",)
            if trade
            else ("context_mismatch",)
        ),
    )


def _outcome(
    observation: ProspectiveObservation,
    *,
    net_return: Decimal,
) -> ProspectiveOutcome:
    gross = net_return + COST
    return ProspectiveOutcome(
        candidate_spec_id=SPEC.spec_id,
        observation_id=observation.observation_id,
        market=HYPE,
        anchor_end_ms=observation.anchor_end_ms,
        target_end_ms=observation.target_end_ms,
        direction=Direction.LONG,
        entry_px=Decimal("100"),
        exit_px=Decimal("100") * (Decimal("1") + gross),
        exit_candle_id=f"exit-{observation.target_end_ms}",
        exit_source_received_at_ms=observation.target_end_ms + 60_000,
        gross_return=gross,
        modeled_cost_fraction=COST,
        net_return=net_return,
    )


def _full_campaign(
    *,
    trades_per_block: int = 20,
    negative_block: int | None = None,
) -> FakeStore:
    anchors_per_block = PLAN.expected_anchor_count // PLAN.stability_blocks
    trade_indexes: set[int] = set()
    for block in range(PLAN.stability_blocks):
        trade_indexes.update(
            range(
                block * anchors_per_block,
                block * anchors_per_block + trades_per_block,
            )
        )

    observations = tuple(
        _observation(
            PLAN.first_expected_anchor_ms + index * HOUR_MS,
            trade=index in trade_indexes,
        )
        for index in range(PLAN.expected_anchor_count)
    )
    outcomes: list[ProspectiveOutcome] = []
    for index in sorted(trade_indexes):
        observation = observations[index]
        block = index // anchors_per_block
        net = (
            Decimal("-0.01")
            if negative_block is not None and block == negative_block
            else Decimal("0.01")
        )
        outcomes.append(_outcome(observation, net_return=net))
    return FakeStore(observations=observations, outcomes=tuple(outcomes))


def test_frozen_validation_plan_has_fixed_window_and_nonpromotion_semantics() -> None:
    assert PLAN.validation_start_ms == SPEC.validation_not_before_ms
    assert PLAN.validation_end_ms == PLAN.validation_start_ms + 45 * DAY_MS
    assert PLAN.finalization_not_before_ms == PLAN.validation_end_ms + SPEC.horizon_ms
    assert PLAN.expected_anchor_count == 1080
    assert PLAN.first_expected_anchor_ms == PLAN.validation_start_ms + HOUR_MS - 1
    assert PLAN.expected_anchor_count_as_of(PLAN.validation_start_ms) == 0
    assert PLAN.expected_anchor_count_as_of(PLAN.first_expected_anchor_ms - 1) == 0
    assert PLAN.expected_anchor_count_as_of(PLAN.first_expected_anchor_ms) == 1
    assert (
        PLAN.expected_anchor_count_as_of(
            PLAN.first_expected_anchor_ms + 2 * HOUR_MS
        )
        == 3
    )
    assert PLAN.expected_anchor_count_as_of(PLAN.validation_end_ms) == 1080
    assert PLAN.min_capture_coverage == Decimal("0.90")
    assert PLAN.min_settled_trades == 80
    assert PLAN.stability_blocks == 4
    assert PLAN.min_block_trades == 15
    assert PLAN.promotion_eligible is False
    assert len(PLAN.plan_id) == 64


def test_positive_complete_campaign_becomes_candidate_review_eligible_only() -> None:
    store = _full_campaign()

    report = build_prospective_validation_report(
        store,
        as_of_ms=PLAN.finalization_not_before_ms,
    )

    assert report.status is ProspectiveValidationStatus.ELIGIBLE_FOR_CANDIDATE_REVIEW
    assert report.capture_coverage == Decimal("1")
    assert report.capture_coverage_to_date == Decimal("1")
    assert report.expected_anchor_count_to_date == 1080
    assert report.observation_count == 1080
    assert report.observation_count_to_date == 1080
    assert report.missed_anchor_count_to_date == 0
    assert report.effective_trade_count == 80
    assert report.settled_trade_count == 80
    assert report.overdue_unsettled_count == 0
    assert report.mean_net_return == Decimal("0.01")
    assert all(block.settled_trade_count == 20 for block in report.blocks)
    assert all(block.mean_net_return == Decimal("0.01") for block in report.blocks)
    assert report.promotion_eligible is False
    assert len(report.evidence_digest) == 64
    assert len(report.report_id) == 64


def test_same_positive_campaign_remains_collecting_before_fixed_finalization() -> None:
    report = build_prospective_validation_report(
        _full_campaign(),
        as_of_ms=PLAN.validation_end_ms,
    )

    assert report.status is ProspectiveValidationStatus.COLLECTING
    assert report.mean_net_return == Decimal("0.01")


def test_positive_overall_return_with_one_losing_block_is_not_qualified() -> None:
    report = build_prospective_validation_report(
        _full_campaign(negative_block=2),
        as_of_ms=PLAN.finalization_not_before_ms,
    )

    assert report.mean_net_return == Decimal("0.005")
    assert report.blocks[2].mean_net_return == Decimal("-0.01")
    assert report.status is ProspectiveValidationStatus.NOT_QUALIFIED


def test_low_capture_coverage_is_data_incomplete_even_when_trades_win() -> None:
    full = _full_campaign()
    trade_ids = {outcome.observation_id for outcome in full.outcomes}
    retained = tuple(
        observation
        for observation in full.observations
        if observation.observation_id in trade_ids
        or observation.anchor_end_ms
        >= PLAN.first_expected_anchor_ms + 250 * HOUR_MS
    )
    store = FakeStore(observations=retained, outcomes=full.outcomes)

    report = build_prospective_validation_report(
        store,
        as_of_ms=PLAN.finalization_not_before_ms,
    )

    assert report.capture_coverage < PLAN.min_capture_coverage
    assert report.status is ProspectiveValidationStatus.DATA_INCOMPLETE


def test_insufficient_settled_trade_count_is_data_incomplete() -> None:
    report = build_prospective_validation_report(
        _full_campaign(trades_per_block=10),
        as_of_ms=PLAN.finalization_not_before_ms,
    )

    assert report.settled_trade_count == 40
    assert report.status is ProspectiveValidationStatus.DATA_INCOMPLETE


def test_overdue_unsettled_trade_is_data_incomplete() -> None:
    full = _full_campaign()
    store = FakeStore(
        observations=full.observations,
        outcomes=full.outcomes[:-1],
    )

    report = build_prospective_validation_report(
        store,
        as_of_ms=PLAN.finalization_not_before_ms,
    )

    assert report.overdue_unsettled_count == 1
    assert report.status is ProspectiveValidationStatus.DATA_INCOMPLETE


def test_orphan_outcome_inside_fixed_window_fails_closed() -> None:
    full = _full_campaign()
    orphan_observation = _observation(
        PLAN.first_expected_anchor_ms + 100 * HOUR_MS,
        trade=True,
    )
    orphan = _outcome(orphan_observation, net_return=Decimal("0.01"))
    store = FakeStore(
        observations=tuple(
            item
            for item in full.observations
            if item.observation_id != orphan.observation_id
        ),
        outcomes=(*full.outcomes, orphan),
    )

    with pytest.raises(ProspectiveValidationError, match="orphan outcome"):
        build_prospective_validation_report(
            store,
            as_of_ms=PLAN.finalization_not_before_ms,
        )



def test_prevalidation_observation_fails_closed() -> None:
    early = _observation(
        PLAN.first_expected_anchor_ms - HOUR_MS,
        trade=False,
    )
    store = FakeStore(observations=(early,), outcomes=())

    with pytest.raises(ProspectiveValidationError, match="pre-validation observation"):
        build_prospective_validation_report(
            store,
            as_of_ms=PLAN.validation_start_ms,
        )



def test_postvalidation_observation_fails_closed() -> None:
    late = _observation(
        PLAN.validation_end_ms,
        trade=False,
    )
    store = FakeStore(observations=(late,), outcomes=())

    with pytest.raises(ProspectiveValidationError, match="post-validation observation"):
        build_prospective_validation_report(
            store,
            as_of_ms=PLAN.finalization_not_before_ms,
        )



def test_collecting_report_tracks_capture_health_to_date() -> None:
    first = PLAN.first_expected_anchor_ms
    observations = (
        _observation(first, trade=False),
        _observation(first + 2 * HOUR_MS, trade=False),
    )
    report = build_prospective_validation_report(
        FakeStore(observations=observations, outcomes=()),
        as_of_ms=first + 2 * HOUR_MS + 5 * 60_000,
    )

    assert report.status is ProspectiveValidationStatus.COLLECTING
    assert report.expected_anchor_count_to_date == 3
    assert report.observation_count_to_date == 2
    assert report.missed_anchor_count_to_date == 1
    assert report.capture_coverage_to_date == Decimal(2) / Decimal(3)
    assert report.capture_coverage == Decimal(2) / Decimal(1080)


def test_collecting_report_has_no_to_date_ratio_before_first_anchor() -> None:
    report = build_prospective_validation_report(
        FakeStore(observations=(), outcomes=()),
        as_of_ms=PLAN.validation_start_ms,
    )

    assert report.expected_anchor_count_to_date == 0
    assert report.observation_count_to_date == 0
    assert report.missed_anchor_count_to_date == 0
    assert report.capture_coverage_to_date is None



def test_campaign_health_is_prevalidation_ready_before_first_counted_anchor() -> None:
    report = build_prospective_validation_report(
        FakeStore(observations=(), outcomes=()),
        as_of_ms=PLAN.validation_start_ms,
    )

    health = build_prospective_campaign_health(report)

    assert health.status is ProspectiveCampaignHealthStatus.PRE_VALIDATION
    assert health.required_final_observation_count == 972
    assert health.missed_anchor_budget == 108
    assert health.remaining_missed_anchor_budget == 108
    assert health.maximum_final_capture_coverage == Decimal("1")
    assert health.irrecoverable is False
    assert len(health.health_id) == 64


def test_one_missed_anchor_degrades_but_remains_recoverable() -> None:
    first = PLAN.first_expected_anchor_ms
    observations = (
        _observation(first, trade=False),
        _observation(first + 2 * HOUR_MS, trade=False),
    )
    report = build_prospective_validation_report(
        FakeStore(observations=observations, outcomes=()),
        as_of_ms=first + 2 * HOUR_MS + 5 * 60_000,
    )

    health = build_prospective_campaign_health(report)

    assert health.status is ProspectiveCampaignHealthStatus.DEGRADED
    assert health.missed_anchor_count_to_date == 1
    assert health.remaining_missed_anchor_budget == 107
    assert health.maximum_final_capture_coverage == (
        Decimal(1079) / Decimal(1080)
    )
    assert health.irrecoverable is False


def test_capture_floor_becomes_irrecoverable_after_miss_budget_is_exceeded() -> None:
    first = PLAN.first_expected_anchor_ms
    report = build_prospective_validation_report(
        FakeStore(observations=(), outcomes=()),
        as_of_ms=first + 108 * HOUR_MS,
    )

    health = build_prospective_campaign_health(report)

    assert health.expected_anchor_count_to_date == 109
    assert health.missed_anchor_count_to_date == 109
    assert health.maximum_final_observation_count == 971
    assert health.maximum_final_capture_coverage == Decimal(971) / Decimal(1080)
    assert health.status is ProspectiveCampaignHealthStatus.IRRECOVERABLE
    assert "capture_floor_unreachable" in health.irrecoverable_reasons


def test_minimum_trade_count_can_become_irrecoverable_even_with_full_capture() -> None:
    observations = tuple(
        _observation(
            PLAN.first_expected_anchor_ms + index * HOUR_MS,
            trade=False,
        )
        for index in range(PLAN.expected_anchor_count)
    )
    report = build_prospective_validation_report(
        FakeStore(observations=observations, outcomes=()),
        as_of_ms=PLAN.validation_end_ms - 1,
    )

    health = build_prospective_campaign_health(report)

    assert health.maximum_final_capture_coverage == Decimal("1")
    assert health.maximum_possible_settled_trades == 0
    assert health.status is ProspectiveCampaignHealthStatus.IRRECOVERABLE
    assert "minimum_settled_trade_count_unreachable" in health.irrecoverable_reasons


def test_completed_block_without_enough_trades_is_irrecoverable() -> None:
    anchors_per_block = PLAN.expected_anchor_count // PLAN.stability_blocks
    observations = tuple(
        _observation(
            PLAN.first_expected_anchor_ms + index * HOUR_MS,
            trade=index >= anchors_per_block,
        )
        for index in range(PLAN.expected_anchor_count)
    )
    report = build_prospective_validation_report(
        FakeStore(observations=observations, outcomes=()),
        as_of_ms=PLAN.validation_end_ms - 1,
    )

    health = build_prospective_campaign_health(report)

    first_block = health.block_recoverability[0]
    assert first_block.remaining_expected_anchors == 0
    assert first_block.maximum_possible_settled_trades == 0
    assert first_block.recoverable is False
    assert health.status is ProspectiveCampaignHealthStatus.IRRECOVERABLE
    assert (
        "block_1_minimum_trade_count_unreachable"
        in health.irrecoverable_reasons
    )


def test_overdue_settlement_degrades_health_but_is_not_irrecoverable() -> None:
    first = PLAN.first_expected_anchor_ms
    observation = _observation(first, trade=True)
    report = build_prospective_validation_report(
        FakeStore(observations=(observation,), outcomes=()),
        as_of_ms=observation.target_end_ms + 1,
    )

    health = build_prospective_campaign_health(report)

    assert report.overdue_unsettled_count == 1
    assert health.overdue_unsettled_count == 1
    assert health.status is ProspectiveCampaignHealthStatus.DEGRADED
    assert health.irrecoverable is False



def test_future_observation_relative_to_report_clock_fails_closed() -> None:
    first = PLAN.first_expected_anchor_ms
    store = FakeStore(
        observations=(_observation(first, trade=False),),
        outcomes=(),
    )

    with pytest.raises(
        ProspectiveValidationError,
        match="future observation relative to report",
    ):
        build_prospective_validation_report(
            store,
            as_of_ms=first - 1,
        )


def test_future_outcome_relative_to_report_clock_fails_closed() -> None:
    first = PLAN.first_expected_anchor_ms
    observation = _observation(first, trade=True)
    outcome = _outcome(observation, net_return=Decimal("0.01"))
    store = FakeStore(
        observations=(observation,),
        outcomes=(outcome,),
    )

    with pytest.raises(
        ProspectiveValidationError,
        match="future outcome relative to report",
    ):
        build_prospective_validation_report(
            store,
            as_of_ms=outcome.target_end_ms - 1,
        )
