from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.evidence.epochs import EpochMarketEvaluation
from cocomelon.research.prospective_short_breakout_paired_entry import (
    PRE_START_REASON,
    RANK_FILTER_REASON,
    ObservedRankWitness,
    ProspectiveShortBreakoutPairedEntryError,
    ProspectiveShortBreakoutPairedEntryFilter,
)
from cocomelon.research.prospective_short_breakout_rank import (
    ProspectiveShortBreakoutRankState,
)

MARKET = MarketId("", "BTC")


def _evaluation(
    *,
    direction: Direction = Direction.SHORT,
    lead: str | None = "breakout",
    decision_ms: int = 21_603_000,
    feature_id: str = "real-feature",
    market: MarketId = MARKET,
) -> EpochMarketEvaluation:
    # The admission policy only reads authentic decision/feature identity
    # fields. The lightweight fixture deliberately does not invent fills.
    return cast(
        EpochMarketEvaluation,
        SimpleNamespace(
            decision=SimpleNamespace(
                market=market,
                feature_snapshot_id="real-feature",
                direction=direction,
                timestamp_ms=decision_ms,
                lead_strategy=lead,
            ),
            feature=SimpleNamespace(
                market=market,
                snapshot_id=feature_id,
            ),
        ),
    )


def _filters(
    rank: ObservedRankWitness | None,
) -> tuple[
    ProspectiveShortBreakoutPairedEntryFilter,
    ProspectiveShortBreakoutPairedEntryFilter,
    list[tuple[MarketId, int]],
]:
    calls: list[tuple[MarketId, int]] = []

    def provider(market: MarketId, at_ms: int) -> ObservedRankWitness | None:
        calls.append((market, at_ms))
        return rank

    freeze = ProspectiveShortBreakoutRankState(frozen_at_ms=1_000)
    baseline = ProspectiveShortBreakoutPairedEntryFilter(
        freeze=freeze,
        block_rank4plus=False,
        rank_witness_provider=provider,
    )
    candidate = ProspectiveShortBreakoutPairedEntryFilter(
        freeze=freeze,
        block_rank4plus=True,
        rank_witness_provider=provider,
    )
    return baseline, candidate, calls


def test_same_predecision_rank_and_starting_boundary_for_both_lanes() -> None:
    baseline, candidate, calls = _filters(
        ObservedRankWitness(ordinal=5, observed_at_ms=21_602_000)
    )
    evaluation = _evaluation()
    start = candidate.freeze.started_at_ms
    assert start == 21_601_000
    for lane in (baseline, candidate):
        assert lane.block_reason(
            evaluation, attempt_timestamp_ms=start - 1
        ) == PRE_START_REASON
        assert lane.pre_start_blocked == 1
    assert baseline.block_reason(
        evaluation, attempt_timestamp_ms=21_603_001
    ) is None
    assert candidate.block_reason(
        evaluation, attempt_timestamp_ms=21_603_001
    ) == RANK_FILTER_REASON
    assert calls == [(MARKET, 21_603_000), (MARKET, 21_603_000)]
    assert baseline.rank4plus_blocked == 0
    assert candidate.rank4plus_blocked_by_market == {"BTC": 1}
    assert candidate.admitted_after_start == 0
    summary = candidate.summary_payload()
    assert summary["source_gap_free"] is True
    assert summary["actual_paired_accounts_running"] is False
    assert summary["full_account_trial"] is False
    assert summary["execution_authority"] is False
    assert summary["promotion_authority"] is False


def test_rank_one_to_three_still_fills_in_both_independent_accounts() -> None:
    for ordinal in (1, 3):
        baseline, candidate, _ = _filters(
            ObservedRankWitness(ordinal, 21_602_000)
        )
        assert baseline.block_reason(
            _evaluation(), attempt_timestamp_ms=21_603_000
        ) is None
        assert candidate.block_reason(
            _evaluation(), attempt_timestamp_ms=21_603_000
        ) is None
        assert candidate.rank4plus_blocked == 0


def test_only_short_breakout_is_filtered() -> None:
    baseline, candidate, calls = _filters(
        ObservedRankWitness(10, 21_602_000)
    )
    assert candidate.block_reason(
        _evaluation(direction=Direction.LONG), attempt_timestamp_ms=21_603_000
    ) is None
    assert candidate.block_reason(
        _evaluation(lead="trend"), attempt_timestamp_ms=21_603_000
    ) is None
    assert baseline.block_reason(
        _evaluation(lead="mean_reversion"), attempt_timestamp_ms=21_603_000
    ) is None
    assert calls == []


@pytest.mark.parametrize(
    ("rank", "reason"),
    [
        (None, "missing_rank_witness"),
        (ObservedRankWitness(8, 21_603_000), "same_millisecond_rank_not_predecision"),
        (ObservedRankWitness(8, 21_302_999), "stale_rank_witness"),
    ],
)
def test_unprovable_rank_never_earns_a_hypothetical_skip(
    rank: ObservedRankWitness | None,
    reason: str,
) -> None:
    baseline, candidate, _ = _filters(rank)
    for lane in (baseline, candidate):
        assert lane.block_reason(
            _evaluation(), attempt_timestamp_ms=21_603_002
        ) is None
        assert lane.summary_payload()["source_gap_free"] is False
        assert lane.unverifiable_by_reason == {reason: 1}
        assert lane.rank4plus_blocked == 0


def test_future_rank_and_inconsistent_identity_fail_closed() -> None:
    baseline, candidate, _ = _filters(
        ObservedRankWitness(6, 21_603_001)
    )
    with pytest.raises(ProspectiveShortBreakoutPairedEntryError, match="future"):
        candidate.block_reason(
            _evaluation(), attempt_timestamp_ms=21_603_002
        )
    with pytest.raises(
        ProspectiveShortBreakoutPairedEntryError, match="lineage"
    ):
        baseline.block_reason(
            _evaluation(feature_id="mismatched"), attempt_timestamp_ms=21_603_002
        )
    with pytest.raises(ProspectiveShortBreakoutPairedEntryError, match="precedes"):
        candidate.block_reason(
            _evaluation(), attempt_timestamp_ms=21_602_999
        )
    with pytest.raises(ProspectiveShortBreakoutPairedEntryError, match="NO_TRADE"):
        candidate.block_reason(
            _evaluation(direction=Direction.NO_TRADE),
            attempt_timestamp_ms=21_603_002,
        )


def test_unknown_strategy_is_retained_but_disqualifies_complete_source() -> None:
    baseline, candidate, calls = _filters(
        ObservedRankWitness(12, 21_602_000)
    )
    for lane in (baseline, candidate):
        assert lane.block_reason(
            _evaluation(lead=None), attempt_timestamp_ms=21_603_000
        ) is None
        assert lane.unverifiable_by_reason == {"missing_lead_strategy": 1}
    assert calls == []


def test_invalid_timestamp_types_and_rank_types_rejected() -> None:
    with pytest.raises(ValueError, match="ordinal"):
        ObservedRankWitness(ordinal=True, observed_at_ms=1)
    with pytest.raises(ValueError, match="observed time"):
        ObservedRankWitness(ordinal=4, observed_at_ms=-1)
    _, candidate, _ = _filters(
        ObservedRankWitness(4, 21_602_000)
    )
    with pytest.raises(
        ProspectiveShortBreakoutPairedEntryError, match="timestamp"
    ):
        candidate.block_reason(
            _evaluation(), attempt_timestamp_ms=True
        )
