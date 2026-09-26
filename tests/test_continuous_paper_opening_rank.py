from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.domain.features import OpportunityRank
from cocomelon.domain.market import MarketId
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankError,
    ContinuousPaperOpeningRankStore,
    LatestCoarseRankTracker,
    opening_rank_attribution,
)

BTC = MarketId("", "BTC")
ETH = MarketId("", "ETH")


def _rank(
    market: MarketId,
    ordinal: int,
    score: str,
) -> OpportunityRank:
    return OpportunityRank(
        market=market,
        ordinal=ordinal,
        score=Decimal(score),
        components=(),
        reason_codes=("coarse",),
    )


def test_tracker_records_latest_rank_before_open() -> None:
    tracker = LatestCoarseRankTracker()
    tracker.update(
        (
            _rank(BTC, 1, "0.9"),
            _rank(ETH, 2, "0.8"),
        ),
        observed_at_ms=1_000,
    )

    evidence = tracker.evidence_for_opening(
        opening_plan_id="plan-1",
        market=ETH,
        opened_at_ms=1_250,
    )

    assert evidence is not None
    assert evidence.ordinal == 2
    assert evidence.score == Decimal("0.8")
    assert evidence.rank_observed_at_ms == 1_000
    assert evidence.rank_age_ms == 250
    assert evidence.rank_pool_size == 2


def test_tracker_never_uses_rank_observed_after_open() -> None:
    tracker = LatestCoarseRankTracker()
    tracker.update(
        (_rank(BTC, 1, "0.9"),),
        observed_at_ms=2_000,
    )

    assert (
        tracker.evidence_for_opening(
            opening_plan_id="plan-1",
            market=BTC,
            opened_at_ms=1_999,
        )
        is None
    )


def test_store_is_idempotent_and_conflict_detecting(
    tmp_path: Path,
) -> None:
    tracker = LatestCoarseRankTracker()
    tracker.update(
        (_rank(BTC, 1, "0.9"),),
        observed_at_ms=1_000,
    )
    evidence = tracker.evidence_for_opening(
        opening_plan_id="plan-1",
        market=BTC,
        opened_at_ms=1_100,
    )
    assert evidence is not None
    store = ContinuousPaperOpeningRankStore(tmp_path / "rank")

    assert store.record(evidence) is True
    assert store.record(evidence) is False
    assert store.record_count == 1
    assert len(store.state_digest) == 64

    with pytest.raises(
        ContinuousPaperOpeningRankError,
        match="OPENING_RANK_EVIDENCE_CONFLICT",
    ):
        store.record(replace(evidence, ordinal=2, rank_pool_size=2))


def test_closed_trade_attribution_groups_rank_buckets(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperOpeningRankStore(tmp_path / "rank")
    tracker = LatestCoarseRankTracker()
    ranks = tuple(
        _rank(
            MarketId("", f"M{index}"),
            index,
            str(Decimal("1") - Decimal(index) / Decimal("100")),
        )
        for index in range(1, 22)
    )
    tracker.update(ranks, observed_at_ms=1_000)

    trades: list[SimpleNamespace] = []
    for suffix, ordinal, pnl, net_r in (
        ("a", 3, "5", "0.5"),
        ("b", 8, "-2", "-0.2"),
        ("c", 15, "-3", "-0.3"),
        ("d", 21, "4", "0.4"),
    ):
        market = MarketId("", f"M{ordinal}")
        evidence = tracker.evidence_for_opening(
            opening_plan_id=f"plan-{suffix}",
            market=market,
            opened_at_ms=1_500,
        )
        assert evidence is not None
        store.record(evidence)
        trades.append(
            SimpleNamespace(
                opening_plan_id=f"plan-{suffix}",
                market=market,
                opened_at_ms=1_500,
                net_pnl=Decimal(pnl),
                net_r=Decimal(net_r),
            )
        )
    trades.append(
        SimpleNamespace(
            opening_plan_id="missing",
            market=BTC,
            opened_at_ms=1_500,
            net_pnl=Decimal("-9"),
            net_r=Decimal("-0.9"),
        )
    )

    result = opening_rank_attribution(  # type: ignore[arg-type]
        tuple(trades),
        store,
    )

    assert result["attributed_closed_trades"] == 4
    assert result["closed_trades_without_rank_evidence"] == 1
    assert result["mean_rank_age_ms"] == 500
    groups = result["by_rank_bucket"]
    assert isinstance(groups, dict)
    assert groups["1-5"]["net_pnl"] == "5"
    assert groups["6-10"]["net_pnl"] == "-2"
    assert groups["11-20"]["net_pnl"] == "-3"
    assert groups["21+"]["net_pnl"] == "4"
