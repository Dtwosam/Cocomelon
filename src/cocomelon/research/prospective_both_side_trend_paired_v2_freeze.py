"""Precommitted clean v2 repetition of the failed v1 trend-abstention hypothesis.

Only the frozen trial identity / calendar boundary change. The pre-existing
v1 signed rows, market gaps and SQLite accounts are not v2 source economics.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Final

from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)
from cocomelon.research.prospective_both_side_trend_paired_freeze import (
    both_side_trend_matched_shadow_freeze,
)

TRIAL_ID_V2: Final = "prospective-both-sides-trend-lead-capital-matched-shadow-v2"
FROZEN_AT_MS_V2: Final = 1_791_936_000_000  # 2026-10-14 00:00 UTC
FORWARD_NOT_BEFORE_MS_V2: Final = (
    FROZEN_AT_MS_V2 + MIN_PROSPECTIVE_EMBARGO_MS
)  # 2026-10-14 06:00 UTC

# Immutable research plan: the hypothesis stays identical; do not choose the
# candidate after looking at v2 results or restart v2 on a losing checkpoint.
PRECOMMITMENT_V2: Final = {
    "trial_id": TRIAL_ID_V2,
    "precommitted_at_utc": "2026-10-13",
    "freeze_at_ms": FROZEN_AT_MS_V2,
    "forward_not_before_ms": FORWARD_NOT_BEFORE_MS_V2,
    "source_hypothesis": "both_side_trend_abstention",
    "baseline": "unchanged_paired_paper_admission",
    "candidate": "block_lead_strategy_trend_on_both_long_and_short",
    "comparison": "matched_starting_cash_identical_feed_strategy_risk_and_cost_model",
    "primary_metric": "candidate_minus_baseline_total_account_pnl_after_all_costs",
    "other_metrics": [
        "net_expectancy_after_fees_funding_slippage",
        "max_drawdown_fraction",
        "profit_factor",
        "closed_trades_by_side",
        "source_data_gap_completeness",
    ],
    "minimum_forward_duration_ms": 72 * 60 * 60 * 1000,
    "open_source_gaps_allowed_for_certification": False,
    "unsigned_account_advances_allowed": False,
    "previous_v1_outcome_admissible": False,
    "research_only": True,
    "paper_only": True,
    "promotion_authority": False,
    "execution_authority": False,
}


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        allow_nan=False, ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def both_side_trend_matched_shadow_v2_freeze() -> LossContextPortfolioShadowFreeze:
    """Write-once identity for NEW accounts, not a v1 checkpoint relabel."""
    original = both_side_trend_matched_shadow_freeze()
    witness = {
        "precommitment": PRECOMMITMENT_V2,
        "original_discovery_candidate_id": original.candidate_id,
        "original_discovery_source_digest": original.source_composition_digest,
        "v1_state_reuse_forbidden": True,
    }
    return replace(
        original,
        loss_context_candidate_id=_digest({
            "witness": witness,
            "candidate_opening_filter": ("lead_strategy", "trend"),
        }),
        source_composition_digest=_digest(witness),
        frozen_at_ms=FROZEN_AT_MS_V2,
        prospective_not_before_ms=FORWARD_NOT_BEFORE_MS_V2,
    )
