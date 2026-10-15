"""Predeclared NEW one-shot paired PAPER replay of LONG trend abstention.

Only a future original mainnet microstructure archive from a separately pinned
manifest can be replayed. The caller must independently authenticate original
GitHub artifact/run/attempt identity, venue coverage, gaps and cohort maturity.
No v1/v2 signed/account history can enter the independently new pair.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Final

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayManifest, ReplayRecord
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import DecisionEpochEngine
from cocomelon.research.fresh_long_trend_account_audit import (
    audit_fresh_v3_paired_accounts,
)
from cocomelon.research.fresh_long_trend_source_integrity import (
    audit_fresh_long_trend_original_records,
)
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_paired_portfolio_shadow import (
    LossContextPairedPortfolioShadow,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    both_side_trend_matched_shadow_v2_freeze,
)
from cocomelon.research.prospective_short_breakout_pinned_source import (
    PinnedShortRankReplaySource,
)

TRIAL_ID: Final = "fresh-long-trend-admission-matched-paper-v3"
FROZEN_AT_MS: Final = 1_792_108_800_000  # 2026-10-16 00:00 UTC
FORWARD_NOT_BEFORE_MS: Final = FROZEN_AT_MS + MIN_PROSPECTIVE_EMBARGO_MS
MINIMUM_FORWARD_MS: Final = 72 * 60 * 60 * 1000
MAX_RECORDS: Final = 5_000_000
BASELINE_SOURCE_ARTIFACT_ID: Final = 11982185958
BASELINE_SOURCE_WORKER_RUN_ID: Final = 38737278661
BASELINE_SOURCE_WORKER_ATTEMPT: Final = 1
BASELINE_SOURCE_WORKER_HEAD_SHA: Final = (
    "bcfd0eab058cda4ba9270dcd449a8cdf67b9199c"
)
# Upper bound at verified GitHub artifact creation (not exchange-event time).
BASELINE_SOURCE_UPLOAD_UPPER_BOUND_MS: Final = 1_792_074_581_000
BASELINE_SOURCE_ZIP_SHA256: Final = (
    "37150b47e701c3ab8c1af23808254f305b443862c90c040b0a49fe002a9a1d93"
)

PRECOMMITMENT: Final = {
    "trial_id": TRIAL_ID,
    "frozen_at_ms": FROZEN_AT_MS,
    "forward_not_before_ms": FORWARD_NOT_BEFORE_MS,
    "primary_hypothesis": "avoid_long_trend_only_at_original_approved_entry",
    "baseline": "unchanged_all_strategy_both_directions",
    "candidate": "block_direction_long_and_lead_strategy_trend_only",
    "minimum_forward_ms": MINIMUM_FORWARD_MS,
    "baseline_source_artifact_id": BASELINE_SOURCE_ARTIFACT_ID,
    "discovery_run_id": BASELINE_SOURCE_WORKER_RUN_ID,
    "discovery_run_attempt": BASELINE_SOURCE_WORKER_ATTEMPT,
    "discovery_head_sha": BASELINE_SOURCE_WORKER_HEAD_SHA,
    "discovery_uploaded_upper_bound_ms": BASELINE_SOURCE_UPLOAD_UPPER_BOUND_MS,
    "discovery_upload_time_not_original_market_event_time": True,
    "discovery_outer_zip_sha256": BASELINE_SOURCE_ZIP_SHA256,
    "discovery_cohort_not_evidence_of_future_edge": True,
    "post_selection_rule_change_allowed": False,
    "source_manifest_pin_required": True,
    "full_venue_continuity_independently_authenticated": False,
    "same_records_risk_execution_fees_funding_and_initial_cash": True,
    "actual_independent_account_fills_not_retrospective_skips": True,
    "previous_v1_v2_accounts_and_signed_records_admissible": False,
    "minimum_72h_alone_sufficient_for_promotion": False,
    "paper_only": True,
    "research_only": True,
    "execution_authority": False,
    "promotion_authority": False,
}


class LongTrendForwardTrialError(RuntimeError):
    """A forward paired account cannot start with this source or state."""


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def fresh_long_trend_freeze() -> LossContextPortfolioShadowFreeze:
    """An immutable NEW candidate; never a rename of v1/v2 economics."""
    old = both_side_trend_matched_shadow_v2_freeze()
    return replace(
        old,
        loss_context_candidate_id=_digest({
            "precommitment": PRECOMMITMENT,
            "policy": ["lead_strategy=trend", "direction=long"],
        }),
        source_composition_digest=_digest(PRECOMMITMENT),
        source_max_timestamp_ms=BASELINE_SOURCE_UPLOAD_UPPER_BOUND_MS,
        source_paper_run_id=BASELINE_SOURCE_WORKER_RUN_ID,
        source_paper_run_attempt=BASELINE_SOURCE_WORKER_ATTEMPT,
        source_paper_head_sha=BASELINE_SOURCE_WORKER_HEAD_SHA,
        dimensions=("lead_strategy", "direction"),
        values=("trend", "long"),
        frozen_at_ms=FROZEN_AT_MS,
        prospective_not_before_ms=FORWARD_NOT_BEFORE_MS,
    )


def run_digest_pinned_long_trend_matched_paper(
    *,
    source_root: str | Path,
    manifest: ReplayManifest,
    expected_manifest_id: str,
    config: BaselineReplayConfig,
    selected_markets: Sequence[MarketId],
    account_root: str | Path,
    decision_engine_factory: Callable[[], DecisionEpochEngine] | None = None,
) -> dict[str, object]:
    """Run a ONE-SHOT independent paper pair, with absolutely no promotion.

    The same untouched source records are delivered in strict order to both
    isolated paper engines. Account file existence is a hard rejection, not a
    way to resume or splice an older losing hypothesis. The source loader
    validates every recorded segment against the caller-supplied manifest,
    but cannot itself prove completeness of the exchange feed.
    """
    freeze = fresh_long_trend_freeze()
    if manifest.start_ms > freeze.prospective_not_before_ms:
        raise LongTrendForwardTrialError(
            "forward manifest starts after frozen trial; left-censored history"
        )
    source = PinnedShortRankReplaySource(
        root=Path(source_root),
        manifest=manifest,
        expected_manifest_id=expected_manifest_id,
    )
    # Validate the ENTIRE archive before creating even an empty paper account.
    original: tuple[ReplayRecord, ...] = source.verified_records(
        forward_not_before_ms=freeze.prospective_not_before_ms,
    )
    if len(original) > MAX_RECORDS:
        raise LongTrendForwardTrialError("forward source exceeds bounded replay")
    markets = tuple(sorted(selected_markets, key=lambda item: item.canonical))
    if not markets or len({m.canonical for m in markets}) != len(markets):
        raise LongTrendForwardTrialError("paired account markets not unique")
    # Never count a late gap or non-L2 snapshot as a full 72-hour
    # market-observable paired-account horizon. This check runs before any
    # account root can be created and rejects ALL original source gaps.
    source_audit = audit_fresh_long_trend_original_records(
        original, manifest=manifest, selected_markets=markets,
        forward_not_before_ms=freeze.prospective_not_before_ms,
    )
    terminal_record_ms = int(source_audit["last_record_available_at_ms"])
    common_l2_end_ms = int(source_audit["common_selected_market_l2_end_ms"])
    root = Path(account_root)
    if root.exists() and (
        not root.is_dir() or root.is_symlink() or any(root.iterdir())
    ):
        raise LongTrendForwardTrialError(
            "new long-trend paired research accounts must have empty root"
        )
    # V1/V2 account roots and prefixes cannot ever become the new campaign.
    if root.name in {
        "both-side-trend-paired-shadow-v1",
        "both-side-trend-paired-shadow-v2",
        "loss-context-paired-v5",
    }:
        raise LongTrendForwardTrialError("prior shadow root may not be reused")
    root.mkdir(parents=True, exist_ok=True)
    actor = LossContextPairedPortfolioShadow(
        freeze=freeze,
        replay_config=config,
        selected_markets=markets,
        state_root=root,
        startup_timestamp_ms=manifest.start_ms,
        decision_engine_factory=decision_engine_factory,
    )
    try:
        for row in original:
            actor.on_record(row, row.available_at_ms)
        # Atomically persist both original PAPER execution stores and
        # publish a LOCAL self-digested checkpoint. The v1/v2 failure
        # showed that a summary without durable parity is not evidence.
        # This is NOT a source-authenticated inter-worker checkpoint.
        checkpoint = actor.checkpoint(end_ms=terminal_record_ms)
        summary = actor.summary_payload(end_ms=terminal_record_ms)
        if summary["record_count"] != len(original):
            raise LongTrendForwardTrialError("paired source row count mismatch")
    finally:
        actor.close()

    # Independently reopen both CLOSED paper execution stores immutable/RO,
    # reconstruct their actual state IDs, fill fee/funding ledgers, and
    # reconcile their marked equity to both the local checkpoint and report.
    local_account_audit = audit_fresh_v3_paired_accounts(
        root, checkpoint=checkpoint, summary=summary,
        starting_cash=config.starting_cash,
        expected_candidate_id=freeze.candidate_id,
        expected_record_count=len(original),
    )
    # No local digest proves original venue market completeness or that the
    # full 72h prospective account evidence passed independent review.
    return {
            "schema": "fresh-long-trend-matched-paper-v3-one-shot-v1",
            "trial_id": TRIAL_ID,
            "frozen_precommitment": PRECOMMITMENT,
            "frozen_candidate_id": freeze.candidate_id,
            "expected_manifest_id": expected_manifest_id,
            "unverified_locally_pinned_source": source.verification_receipt(original),
            "source_records_replayed": len(original),
            "locally_checked_market_gap_and_l2_receipt": source_audit,
            "last_original_forward_record_at_ms": terminal_record_ms,
            "last_common_original_l2_at_ms": common_l2_end_ms,
            "record_observed_forward_elapsed_ms": (
                common_l2_end_ms - freeze.prospective_not_before_ms
            ),
            "minimum_forward_elapsed": (
                common_l2_end_ms - freeze.prospective_not_before_ms >= MINIMUM_FORWARD_MS
            ),
            "paired_account_original_runtime_summary": summary,
            "locally_reconciled_original_paired_sqlite_accounts": local_account_audit,
            "independent_record_gap_continuity_authenticated": False,
            "independent_signed_terminal_account_parity_certified": False,
            "after_cost_72h_profitability_verified": False,
            "full_account_study_admissible": False,
            "replayed_original_v1_or_v2_account_history": False,
            "paper_only": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }
