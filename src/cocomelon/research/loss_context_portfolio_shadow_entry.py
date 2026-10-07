from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.evidence.epochs import EpochMarketEvaluation
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)

ZERO: Final = Decimal("0")
SUPPORTED_CONTEXT_DIMENSIONS: Final = frozenset(
    {
        "lead_strategy",
        "trend_regime",
        "volatility_regime",
        "return_15m_sign",
        "return_1h_sign",
        "rank_band",
        "direction",
    }
)
PRE_BOUNDARY_REASON: Final = "loss_context_portfolio_shadow_pre_boundary"
CONTEXT_BLOCK_REASON: Final = "loss_context_portfolio_shadow_context_block"

RankOrdinalProvider = Callable[[MarketId, int], int | None]


class LossContextPortfolioShadowEntryFilterError(RuntimeError):
    pass


def _sign(value: Decimal | None) -> str:
    if value is None:
        return "missing"
    if value > ZERO:
        return "positive"
    if value < ZERO:
        return "negative"
    return "flat"


def _rank_band(ordinal: int | None) -> str:
    if ordinal is None:
        return "missing"
    if ordinal <= 0:
        raise LossContextPortfolioShadowEntryFilterError(
            "rank ordinal must be positive"
        )
    if ordinal <= 3:
        return "top3"
    if ordinal <= 10:
        return "top10"
    return "outside10"


def _entry_context(
    evaluation: EpochMarketEvaluation,
    *,
    attempt_timestamp_ms: int,
    rank_ordinal_provider: RankOrdinalProvider | None,
    required_dimensions: tuple[str, ...],
) -> dict[str, str]:
    unknown = set(required_dimensions) - SUPPORTED_CONTEXT_DIMENSIONS
    if unknown:
        raise LossContextPortfolioShadowEntryFilterError(
            "unsupported frozen context dimensions: "
            + ",".join(sorted(unknown))
        )

    decision = evaluation.decision
    feature = evaluation.feature
    if decision.feature_snapshot_id != feature.snapshot_id:
        raise LossContextPortfolioShadowEntryFilterError(
            "shadow entry decision/feature lineage mismatch"
        )
    if decision.market != feature.market:
        raise LossContextPortfolioShadowEntryFilterError(
            "shadow entry market lineage mismatch"
        )
    if attempt_timestamp_ms < decision.timestamp_ms:
        raise LossContextPortfolioShadowEntryFilterError(
            "shadow entry attempt precedes decision"
        )

    context = {
        "lead_strategy": decision.lead_strategy or "unknown",
        "trend_regime": feature.trend_regime.value,
        "volatility_regime": feature.volatility_regime.value,
        "return_15m_sign": _sign(feature.return_15m),
        "return_1h_sign": _sign(feature.return_1h),
        "direction": decision.direction.value,
    }
    if "rank_band" in required_dimensions:
        if rank_ordinal_provider is None:
            raise LossContextPortfolioShadowEntryFilterError(
                "rank-band shadow context requires a contemporaneous rank provider"
            )
        ordinal = rank_ordinal_provider(
            decision.market,
            attempt_timestamp_ms,
        )
        context["rank_band"] = _rank_band(ordinal)
    return context


@dataclass(slots=True)
class LossContextPortfolioShadowEntryFilter:
    freeze: LossContextPortfolioShadowFreeze
    block_matching_context: bool
    rank_ordinal_provider: RankOrdinalProvider | None = None
    pre_boundary_blocked: int = 0
    matching_context_blocked: int = 0
    matching_context_blocked_by_market: dict[str, int] = field(
        default_factory=dict
    )
    admitted_after_boundary: int = 0

    def __post_init__(self) -> None:
        unknown = set(self.freeze.dimensions) - SUPPORTED_CONTEXT_DIMENSIONS
        if unknown:
            raise ValueError(
                "unsupported frozen context dimensions: "
                + ",".join(sorted(unknown))
            )
        if (
            "rank_band" in self.freeze.dimensions
            and self.rank_ordinal_provider is None
        ):
            raise ValueError(
                "rank-band shadow context requires a rank provider"
            )

    def block_reason(
        self,
        evaluation: EpochMarketEvaluation,
        *,
        attempt_timestamp_ms: int,
    ) -> str | None:
        decision: StrategyDecision = evaluation.decision
        if decision.direction is Direction.NO_TRADE:
            raise LossContextPortfolioShadowEntryFilterError(
                "opening filter received a non-directional decision"
            )
        if attempt_timestamp_ms < self.freeze.prospective_not_before_ms:
            self.pre_boundary_blocked += 1
            return PRE_BOUNDARY_REASON

        context = _entry_context(
            evaluation,
            attempt_timestamp_ms=attempt_timestamp_ms,
            rank_ordinal_provider=self.rank_ordinal_provider,
            required_dimensions=self.freeze.dimensions,
        )
        values = tuple(
            context[dimension] for dimension in self.freeze.dimensions
        )
        if self.block_matching_context and values == self.freeze.values:
            self.matching_context_blocked += 1
            market = decision.market.canonical
            self.matching_context_blocked_by_market[market] = (
                self.matching_context_blocked_by_market.get(market, 0) + 1
            )
            return CONTEXT_BLOCK_REASON

        self.admitted_after_boundary += 1
        return None

    def summary_payload(self) -> dict[str, object]:
        return {
            "portfolio_shadow_candidate_id": self.freeze.candidate_id,
            "loss_context_candidate_id": (
                self.freeze.loss_context_candidate_id
            ),
            "dimensions": self.freeze.dimensions,
            "values": self.freeze.values,
            "prospective_not_before_ms": (
                self.freeze.prospective_not_before_ms
            ),
            "block_matching_context": self.block_matching_context,
            "pre_boundary_blocked": self.pre_boundary_blocked,
            "matching_context_blocked": self.matching_context_blocked,
            "matching_context_blocked_by_market": dict(
                sorted(self.matching_context_blocked_by_market.items())
            ),
            "admitted_after_boundary": self.admitted_after_boundary,
            "research_only": True,
            "shadow_only": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "changes_positions": False,
            "promotion_authority": False,
            "execution_authority": False,
        }
