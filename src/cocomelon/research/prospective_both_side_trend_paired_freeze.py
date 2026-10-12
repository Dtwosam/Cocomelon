"""Frozen, paper-only paired-account identity for the October 12 trend hypothesis.

The original booked-contribution study is NOT a capital-matched challenger.
This separate, deterministic identity can be supplied to the existing
paired-account engine only with a new, isolated shadow state root and genuine
post-embargo market records. Creating the identity does not start an account.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)
from cocomelon.research.paper_profitability_scoreboard import (
    BOTH_SIDE_TREND_DISCOVERY_ARTIFACT_ID,
    BOTH_SIDE_TREND_DISCOVERY_GITHUB_ARTIFACT_SHA256,
    BOTH_SIDE_TREND_DISCOVERY_RUN_ID,
    BOTH_SIDE_TREND_FORWARD_MS,
    BOTH_SIDE_TREND_FREEZE_MS,
)

# The completed real GitHub source worker supplied the 210-close discovery
# scoreboard. Its GitHub updated_at is an upper time bound, NOT the last
# original market observation or an authenticated exchange data timestamp.
DISCOVERY_HEAD_SHA: Final = "070d915625a36f7d6624d821fb3b3b4dcabab2ec"
DISCOVERY_RUN_ATTEMPT: Final = 1
DISCOVERY_WORKER_UPDATED_UPPER_BOUND_MS: Final = 1_791_802_836_000
TRIAL_ID: Final = "prospective-both-sides-trend-lead-capital-matched-shadow-v1"
# Compatibility-only frozen field: the underlying paired engine does not
# select or aggregate exit horizons. It trades the ordinary paper exit logic.
UNSELECTED_COMPATIBILITY_HORIZON_MS: Final = (300_000,)


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def both_side_trend_matched_shadow_freeze() -> LossContextPortfolioShadowFreeze:
    """Describe one independent baseline-vs-trend-abstention paper pair.

    The candidate excludes LONG and SHORT trend leads, without selecting
    winning/losing outcomes. Both accounts get the same prospective market
    records, execution model, original strategies, risk rules and stop logic.
    No historical completed fills may be imported as challenger economics.
    """
    if not (
        0 < DISCOVERY_WORKER_UPDATED_UPPER_BOUND_MS
        < BOTH_SIDE_TREND_FREEZE_MS
        < BOTH_SIDE_TREND_FORWARD_MS
    ):
        raise ValueError("paired trend trial crosses the immutable time embargo")

    witness = {
        "hypothesis_id": TRIAL_ID,
        "discovery_worker_run_id": BOTH_SIDE_TREND_DISCOVERY_RUN_ID,
        "discovery_worker_attempt": DISCOVERY_RUN_ATTEMPT,
        "discovery_worker_head_sha": DISCOVERY_HEAD_SHA,
        "discovery_worker_updated_upper_bound_ms": (
            DISCOVERY_WORKER_UPDATED_UPPER_BOUND_MS
        ),
        "upper_bound_not_last_market_observation": True,
        "discovery_scoreboard_artifact_id": (
            BOTH_SIDE_TREND_DISCOVERY_ARTIFACT_ID
        ),
        "discovery_scoreboard_outer_zip_sha256": (
            BOTH_SIDE_TREND_DISCOVERY_GITHUB_ARTIFACT_SHA256
        ),
        "discovery_is_not_profitable_prospective_evidence": True,
        "frozen_at_ms": BOTH_SIDE_TREND_FREEZE_MS,
        "forward_not_before_ms": BOTH_SIDE_TREND_FORWARD_MS,
        "both_long_and_short_trend_leads_abstained": True,
        "baseline_and_candidate_start_at_same_forward_boundary": True,
        "independent_new_shadow_state_root_required": True,
        "historical_booked_trade_skips_are_not_account_results": True,
        "real_paper_orders_changed": False,
        "promotion_authority": False,
    }
    return LossContextPortfolioShadowFreeze(
        loss_context_candidate_id=_digest({
            "witness": witness,
            "candidate_opening_filter": ("lead_strategy", "trend"),
        }),
        source_composition_digest=_digest(witness),
        # Conservative API completion upper bound: never treated as a
        # producer-signed last market event or proof of full feed coverage.
        source_max_timestamp_ms=DISCOVERY_WORKER_UPDATED_UPPER_BOUND_MS,
        source_paper_run_id=BOTH_SIDE_TREND_DISCOVERY_RUN_ID,
        source_paper_run_attempt=DISCOVERY_RUN_ATTEMPT,
        source_paper_head_sha=DISCOVERY_HEAD_SHA,
        dimensions=("lead_strategy",),
        values=("trend",),
        horizons_ms=UNSELECTED_COMPATIBILITY_HORIZON_MS,
        frozen_at_ms=BOTH_SIDE_TREND_FREEZE_MS,
        prospective_not_before_ms=BOTH_SIDE_TREND_FORWARD_MS,
    )
