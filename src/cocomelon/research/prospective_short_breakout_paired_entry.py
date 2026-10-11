from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.evidence.epochs import EpochMarketEvaluation
from cocomelon.research.prospective_short_breakout_rank import (
    RANK_CUTOFF,
    ProspectiveShortBreakoutRankState,
)

# This is an admission policy for a FUTURE separate simulated account.
# It does not authorize the original paper trader or replace skip-only economics.
PRE_START_REASON: Final = "paired_short_breakout_pre_start"
RANK_FILTER_REASON: Final = "paired_short_breakout_rank4plus"
MAX_RANK_AGE_MS: Final = 300_000

RankWitnessProvider = Callable[[MarketId, int], "ObservedRankWitness | None"]


class ProspectiveShortBreakoutPairedEntryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ObservedRankWitness:
    """A genuinely observed rank, never a reconstructed end-of-trade rank."""

    ordinal: int
    observed_at_ms: int

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal <= 0:
            raise ValueError("rank witness ordinal must be positive")
        if type(self.observed_at_ms) is not int or self.observed_at_ms < 0:
            raise ValueError("rank witness observed time must be non-negative")


@dataclass(slots=True)
class ProspectiveShortBreakoutPairedEntryFilter:
    """Predeclared SHORT breakout rank>3 admission, for paired paper replay only.

    Baseline and challenger MUST consume the same recorded decision and rank
    witness, before either account attempts a fill. Unknown, stale, same-ms,
    and unwitnessed opening decisions are retained by both lanes and marked
    incomplete; they cannot become skipped losers. Rank data must precede the
    actual decision, not merely the later simulated opening attempt.
    """

    freeze: ProspectiveShortBreakoutRankState
    block_rank4plus: bool
    rank_witness_provider: RankWitnessProvider
    pre_start_blocked: int = 0
    rank4plus_blocked: int = 0
    rank4plus_blocked_by_market: dict[str, int] = field(default_factory=dict)
    admitted_after_start: int = 0
    unverifiable_by_reason: dict[str, int] = field(default_factory=dict)

    def _unverified(self, reason: str) -> None:
        self.unverifiable_by_reason[reason] = (
            self.unverifiable_by_reason.get(reason, 0) + 1
        )

    def block_reason(
        self,
        evaluation: EpochMarketEvaluation,
        *,
        attempt_timestamp_ms: int,
    ) -> str | None:
        decision = evaluation.decision
        feature = evaluation.feature
        if type(attempt_timestamp_ms) is not int or attempt_timestamp_ms < 0:
            raise ProspectiveShortBreakoutPairedEntryError(
                "paired opening attempt timestamp invalid"
            )
        if decision.direction is Direction.NO_TRADE:
            raise ProspectiveShortBreakoutPairedEntryError(
                "paired opening admission received NO_TRADE"
            )
        if (
            decision.market != feature.market
            or decision.feature_snapshot_id != feature.snapshot_id
        ):
            raise ProspectiveShortBreakoutPairedEntryError(
                "paired decision feature lineage mismatch"
            )
        if decision.timestamp_ms > attempt_timestamp_ms:
            raise ProspectiveShortBreakoutPairedEntryError(
                "paired opening attempt precedes its decision"
            )
        if attempt_timestamp_ms < self.freeze.started_at_ms:
            self.pre_start_blocked += 1
            return PRE_START_REASON

        if decision.lead_strategy in (None, "", "unknown"):
            self._unverified("missing_lead_strategy")
            self.admitted_after_start += 1
            return None

        if (
            decision.direction is Direction.SHORT
            and decision.lead_strategy == "breakout"
        ):
            witness = self.rank_witness_provider(
                decision.market, decision.timestamp_ms
            )
            if witness is None:
                self._unverified("missing_rank_witness")
            elif witness.observed_at_ms > decision.timestamp_ms:
                raise ProspectiveShortBreakoutPairedEntryError(
                    "future rank witness cannot justify paired opening"
                )
            elif witness.observed_at_ms == decision.timestamp_ms:
                self._unverified("same_millisecond_rank_not_predecision")
            elif decision.timestamp_ms - witness.observed_at_ms > MAX_RANK_AGE_MS:
                self._unverified("stale_rank_witness")
            elif witness.ordinal > RANK_CUTOFF and self.block_rank4plus:
                self.rank4plus_blocked += 1
                market = decision.market.canonical
                self.rank4plus_blocked_by_market[market] = (
                    self.rank4plus_blocked_by_market.get(market, 0) + 1
                )
                return RANK_FILTER_REASON

        self.admitted_after_start += 1
        return None

    def summary_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.freeze.candidate_id,
            "frozen_at_ms": self.freeze.frozen_at_ms,
            "prospective_not_before_ms": self.freeze.started_at_ms,
            "rank_cutoff": RANK_CUTOFF,
            "max_rank_age_ms": MAX_RANK_AGE_MS,
            "block_rank4plus": self.block_rank4plus,
            "pre_start_blocked": self.pre_start_blocked,
            "rank4plus_blocked": self.rank4plus_blocked,
            "rank4plus_blocked_by_market": dict(
                sorted(self.rank4plus_blocked_by_market.items())
            ),
            "admitted_after_start": self.admitted_after_start,
            "unverifiable_by_reason": dict(
                sorted(self.unverifiable_by_reason.items())
            ),
            "source_gap_free": not self.unverifiable_by_reason,
            "actual_paired_accounts_running": False,
            "full_account_trial": False,
            "ready_for_review": False,
            "research_only": True,
            "promotion_authority": False,
            "execution_authority": False,
        }
