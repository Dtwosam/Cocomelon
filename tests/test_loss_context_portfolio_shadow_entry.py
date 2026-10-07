from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.evidence.epochs import EpochMarketEvaluation
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)
from cocomelon.research.loss_context_portfolio_shadow_entry import (
    CONTEXT_BLOCK_REASON,
    PRE_BOUNDARY_REASON,
    LossContextPortfolioShadowEntryFilter,
)

MARKET = MarketId("", "TEST")


def _freeze(
    *,
    dimensions: tuple[str, ...] = (
        "lead_strategy",
        "trend_regime",
    ),
    values: tuple[str, ...] = ("mean_reversion", "down"),
) -> LossContextPortfolioShadowFreeze:
    frozen_at_ms = 10_000
    return LossContextPortfolioShadowFreeze(
        loss_context_candidate_id="a" * 64,
        source_composition_digest="b" * 64,
        source_max_timestamp_ms=9_000,
        source_paper_run_id=123,
        source_paper_run_attempt=1,
        source_paper_head_sha="c" * 40,
        dimensions=dimensions,
        values=values,
        horizons_ms=(300_000, 900_000),
        frozen_at_ms=frozen_at_ms,
        prospective_not_before_ms=(
            frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ),
    )


def _evaluation(
    *,
    direction: Direction = Direction.LONG,
    lead_strategy: str = "mean_reversion",
    trend: TrendRegime = TrendRegime.DOWN,
    volatility: VolatilityRegime = VolatilityRegime.HIGH,
    return_15m: Decimal | None = Decimal("-0.01"),
    return_1h: Decimal | None = Decimal("-0.02"),
) -> EpochMarketEvaluation:
    feature = FeatureSnapshot(
        market=MARKET,
        as_of_ms=30_000,
        source_received_at_ms=29_000,
        schema_version=1,
        day_return=Decimal("-0.03"),
        funding=Decimal("0"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("500000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=Decimal("-0.005"),
        return_15m=return_15m,
        return_1h=return_1h,
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("-0.2"),
        book_age_ms=10,
        trend_regime=trend,
        volatility_regime=volatility,
        provenance=("test",),
    )
    decision = StrategyDecision(
        market=MARKET,
        direction=direction,
        score=Decimal("80"),
        timestamp_ms=30_000,
        feature_snapshot_id=feature.snapshot_id,
        lead_strategy=lead_strategy,
        invalidation_price=Decimal("105"),
        signal_ids=("signal:test",),
        reason_codes=("fixture",),
    )
    return EpochMarketEvaluation(
        feature=feature,
        eligibility=EligibilityDecision(
            market=MARKET,
            rankable=True,
            deep_ready=True,
            reasons=(),
        ),
        decision=decision,
    )


def test_shadow_entry_blocks_exact_context_not_entire_direction() -> None:
    freeze = _freeze()
    candidate = LossContextPortfolioShadowEntryFilter(
        freeze,
        block_matching_context=True,
    )
    timestamp = freeze.prospective_not_before_ms + 1

    assert (
        candidate.block_reason(
            _evaluation(),
            attempt_timestamp_ms=timestamp,
        )
        == CONTEXT_BLOCK_REASON
    )
    assert (
        candidate.block_reason(
            _evaluation(lead_strategy="trend"),
            attempt_timestamp_ms=timestamp,
        )
        is None
    )
    assert (
        candidate.block_reason(
            _evaluation(
                direction=Direction.SHORT,
                lead_strategy="trend",
            ),
            attempt_timestamp_ms=timestamp,
        )
        is None
    )
    assert candidate.matching_context_blocked == 1
    assert candidate.matching_context_blocked_by_market == {"TEST": 1}
    assert candidate.matching_context_blocked_unattributed == 0
    assert candidate.admitted_after_boundary == 2


def test_shadow_baseline_lane_only_enforces_prospective_boundary() -> None:
    freeze = _freeze()
    baseline = LossContextPortfolioShadowEntryFilter(
        freeze,
        block_matching_context=False,
    )

    assert (
        baseline.block_reason(
            _evaluation(),
            attempt_timestamp_ms=freeze.prospective_not_before_ms - 1,
        )
        == PRE_BOUNDARY_REASON
    )
    assert (
        baseline.block_reason(
            _evaluation(),
            attempt_timestamp_ms=freeze.prospective_not_before_ms,
        )
        is None
    )
    assert baseline.pre_boundary_blocked == 1
    assert baseline.matching_context_blocked == 0
    assert baseline.admitted_after_boundary == 1


def test_shadow_entry_rank_band_uses_attempt_time_rank() -> None:
    freeze = _freeze(
        dimensions=("lead_strategy", "rank_band"),
        values=("mean_reversion", "top3"),
    )
    calls: list[tuple[MarketId, int]] = []

    def rank_provider(
        market: MarketId,
        at_ms: int,
    ) -> int | None:
        calls.append((market, at_ms))
        return 2

    candidate = LossContextPortfolioShadowEntryFilter(
        freeze,
        block_matching_context=True,
        rank_ordinal_provider=rank_provider,
    )
    timestamp = freeze.prospective_not_before_ms + 123
    assert (
        candidate.block_reason(
            _evaluation(),
            attempt_timestamp_ms=timestamp,
        )
        == CONTEXT_BLOCK_REASON
    )
    assert calls == [(MARKET, timestamp)]


def test_shadow_entry_requires_rank_provider_for_rank_context() -> None:
    freeze = _freeze(
        dimensions=("lead_strategy", "rank_band"),
        values=("mean_reversion", "top10"),
    )
    with pytest.raises(
        ValueError,
        match="rank-band shadow context requires a rank provider",
    ):
        LossContextPortfolioShadowEntryFilter(
            freeze,
            block_matching_context=True,
        )


def test_shadow_entry_matches_all_frozen_market_context_dimensions() -> None:
    freeze = _freeze(
        dimensions=(
            "lead_strategy",
            "trend_regime",
            "volatility_regime",
            "return_15m_sign",
            "return_1h_sign",
            "direction",
        ),
        values=(
            "mean_reversion",
            "down",
            "high",
            "negative",
            "negative",
            "long",
        ),
    )
    candidate = LossContextPortfolioShadowEntryFilter(
        freeze,
        block_matching_context=True,
    )
    timestamp = freeze.prospective_not_before_ms + 1

    assert (
        candidate.block_reason(
            _evaluation(),
            attempt_timestamp_ms=timestamp,
        )
        == CONTEXT_BLOCK_REASON
    )
    assert (
        candidate.block_reason(
            _evaluation(volatility=VolatilityRegime.NORMAL),
            attempt_timestamp_ms=timestamp,
        )
        is None
    )
