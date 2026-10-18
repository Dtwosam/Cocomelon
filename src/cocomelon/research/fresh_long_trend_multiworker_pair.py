"""Bounded-memory, forward-only v3 paired PAPER replay across real handoffs.

A 4h PAPER worker cannot by itself witness the frozen 72h forward trial.
Every worker archive is independently SHA/manifest checked, then its
first-received ordinal sequence is restored. TWO complete passes are made:
source admission BEFORE any account creation, and identical records to two
independent capital-matched PAPER accounts. No historical skips or PnL claims.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import DecisionEpochEngine
from cocomelon.research.fresh_long_trend_account_audit import (
    audit_fresh_v3_paired_accounts,
)
from cocomelon.research.fresh_long_trend_economic_hurdle import (
    fresh_long_trend_economic_hurdle,
)
from cocomelon.research.fresh_long_trend_forward_pair import (
    FORWARD_NOT_BEFORE_MS,
    MINIMUM_FORWARD_MS,
    TRIAL_ID,
    fresh_long_trend_freeze,
)
from cocomelon.research.fresh_long_trend_receipt_order import (
    restore_original_v3_received_order,
)
from cocomelon.research.fresh_long_trend_source_chain import (
    OriginalV3WorkerSourceWitness,
    audit_original_v3_worker_source_chain,
)
from cocomelon.research.fresh_long_trend_source_integrity import (
    audit_fresh_long_trend_original_records,
)
from cocomelon.research.loss_context_paired_portfolio_shadow import (
    LossContextPairedPortfolioShadow,
)
from cocomelon.research.prospective_short_breakout_pinned_source import (
    PinnedShortRankReplaySource,
)

# Deliberately bounded total SOURCE rows without constructing one huge tuple.
# Each worker recorder has its own independently enforced 5M-row limit.
MAX_CHAIN_ROWS: Final = 100_000_000
MIN_CHAIN_WORKERS: Final = 2


class OriginalV3MultiworkerPairError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OriginalV3PinnedWorker:
    source_root: Path
    witness: OriginalV3WorkerSourceWitness


@dataclass(frozen=True, slots=True)
class _WholeWindow:
    start_ms: int
    end_ms: int
    gap_refs: tuple[str, ...] = ()


def _source_records(
    workers: Sequence[OriginalV3PinnedWorker],
) -> Iterator[ReplayRecord]:
    """Load one authentic local worker at a time, never a merged fake manifest."""
    for index, worker in enumerate(workers):
        manifest = worker.witness.manifest
        pin = worker.witness.github_source["manifest_id"]
        if type(pin) is not str:
            raise OriginalV3MultiworkerPairError("worker manifest pin invalid")
        source = PinnedShortRankReplaySource(
            root=worker.source_root,
            manifest=manifest,
            expected_manifest_id=pin,
        )
        # Only the FIRST original archive must span frozen eligibility.
        # All successor archives begin later, without re-freezing the rule.
        boundary = FORWARD_NOT_BEFORE_MS if index == 0 else manifest.start_ms
        independent = source.verified_records(forward_not_before_ms=boundary)
        ordered = restore_original_v3_received_order(
            worker.source_root, manifest, independent,
        )
        if len(ordered) != sum(s.row_count for s in manifest.segments):
            raise OriginalV3MultiworkerPairError("worker ordinal count mismatch")
        yield from ordered


def run_frozen_long_trend_multiworker_paper(
    *,
    workers: Sequence[OriginalV3PinnedWorker],
    config: BaselineReplayConfig,
    selected_markets: Sequence[MarketId],
    account_root: str | Path,
    decision_engine_factory: Callable[[], DecisionEpochEngine] | None = None,
) -> dict[str, object]:
    """Pre-validate complete multiworker market sequence before any cash replay.

    This offline study checks local immutable archives and reported worker
    lineage, not independently witnessed GitHub, original feed completeness,
    real signed interworker checkpoints, or LIVE readiness.
    """
    if len(workers) < MIN_CHAIN_WORKERS:
        raise OriginalV3MultiworkerPairError(
            "72-hour v3 requires consecutive original worker archives"
        )
    witnesses = tuple(worker.witness for worker in workers)
    chain = audit_original_v3_worker_source_chain(witnesses)
    first, last = witnesses[0].manifest, witnesses[-1].manifest
    if not (first.start_ms <= FORWARD_NOT_BEFORE_MS < first.end_ms):
        raise OriginalV3MultiworkerPairError(
            "first worker does not cover frozen forward entry boundary"
        )
    if last.end_ms - FORWARD_NOT_BEFORE_MS < MINIMUM_FORWARD_MS:
        raise OriginalV3MultiworkerPairError(
            "real source manifest horizon shorter than frozen 72 hours"
        )
    for worker in workers:
        manifest = worker.witness.manifest
        if (
            manifest.config_digest != config.config_digest
            or manifest.execution_config_version != config.execution.config_version
            or manifest.fee_schedule_id != config.execution.fee_schedule_id
            or manifest.feature_version != config.feature_version
            or manifest.strategy_version != config.strategy_version
            or manifest.risk_version != config.risk_version
            or manifest.replay_engine_version != config.replay_engine_version
        ):
            raise OriginalV3MultiworkerPairError(
                "worker risk/fee/strategy differs from frozen original PAPER"
            )
    expected_count = chain["original_manifest_record_rows"]
    if (
        type(expected_count) is not int
        or not 0 < expected_count <= MAX_CHAIN_ROWS
    ):
        raise OriginalV3MultiworkerPairError("bounded worker source row total invalid")
    markets = tuple(sorted(selected_markets, key=lambda m: m.canonical))
    if not markets or len({m.canonical for m in markets}) != len(markets):
        raise OriginalV3MultiworkerPairError("original cohort markets invalid")
    root = Path(account_root)
    if root.exists() and (
        not root.is_dir() or root.is_symlink() or any(root.iterdir())
    ):
        raise OriginalV3MultiworkerPairError(
            "new v3 paired account root must be empty and never reused"
        )
    if root.name in {
        "both-side-trend-paired-shadow-v1",
        "both-side-trend-paired-shadow-v2",
        "loss-context-paired-v5",
    }:
        raise OriginalV3MultiworkerPairError("quarantined prior account root")
    account_real = root.resolve()
    seen_roots: set[Path] = set()
    for worker in workers:
        source_real = worker.source_root.resolve(strict=True)
        if (
            source_real in seen_roots or worker.source_root.is_symlink()
            or source_real == account_real
            or source_real in account_real.parents
            or account_real in source_real.parents
        ):
            raise OriginalV3MultiworkerPairError(
                "source archives duplicate or overlap new account path"
            )
        seen_roots.add(source_real)

    bounds = _WholeWindow(start_ms=first.start_ms, end_ms=last.end_ms)
    # Stream each validated worker independently; no multiworker in-memory
    # concat and no fabricated replacement timestamp at a worker handoff.
    source_audit = audit_fresh_long_trend_original_records(
        _source_records(workers),
        manifest=bounds, selected_markets=markets,
        forward_not_before_ms=FORWARD_NOT_BEFORE_MS,
    )
    if source_audit["record_count"] != expected_count:
        raise OriginalV3MultiworkerPairError("whole original row count mismatched")
    common_end = source_audit["common_selected_market_l2_end_ms"]
    if type(common_end) is not int or (
        common_end - FORWARD_NOT_BEFORE_MS < MINIMUM_FORWARD_MS
    ):
        raise OriginalV3MultiworkerPairError(
            "genuine common-market L2 horizon shorter than 72 hours"
        )
    terminal_ms = source_audit["last_record_available_at_ms"]
    if type(terminal_ms) is not int:
        raise OriginalV3MultiworkerPairError("source terminal clock invalid")
    freeze = fresh_long_trend_freeze()
    root.mkdir(parents=True, exist_ok=True)
    actor = LossContextPairedPortfolioShadow(
        freeze=freeze, replay_config=config, selected_markets=markets,
        state_root=root, startup_timestamp_ms=first.start_ms,
        decision_engine_factory=decision_engine_factory,
    )
    # Repeat byte-pinned reads to forbid switching a worker ZIP after
    # qualification. A second-pass failure leaves accounts nonpromotable.
    observed_count = 0
    second_audit: dict[str, object] | None = None

    def apply_same_events() -> Iterator[ReplayRecord]:
        nonlocal observed_count
        for record in _source_records(workers):
            actor.on_record(record, record.available_at_ms)
            observed_count += 1
            yield record

    try:
        second_audit = audit_fresh_long_trend_original_records(
            apply_same_events(), manifest=bounds, selected_markets=markets,
            forward_not_before_ms=FORWARD_NOT_BEFORE_MS,
        )
        if (
            second_audit != source_audit
            or observed_count != expected_count
        ):
            raise OriginalV3MultiworkerPairError(
                "original source changed between audit and PAPER account replay"
            )
        checkpoint = actor.checkpoint(end_ms=terminal_ms)
        summary = actor.summary_payload(end_ms=terminal_ms)
        if summary["record_count"] != expected_count:
            raise OriginalV3MultiworkerPairError("paired accounts missed input rows")
    finally:
        actor.close()

    account_audit = audit_fresh_v3_paired_accounts(
        root, checkpoint=checkpoint, summary=summary,
        starting_cash=config.starting_cash,
        expected_candidate_id=freeze.candidate_id,
        expected_record_count=expected_count,
    )
    economic = fresh_long_trend_economic_hurdle(account_audit)
    return {
        "schema": "v3-frozen-multiworker-paired-paper-local-review-v1",
        "trial_id": TRIAL_ID,
        "original_worker_chain_local_preflight": chain,
        "local_pinned_received_event_source_audit": source_audit,
        "source_second_pass_exact_digest_and_row_parity": True,
        "same_unmodified_records_to_independent_accounts": True,
        "original_worker_count": len(workers),
        "source_original_row_count": expected_count,
        "account_original_runtime_summary": summary,
        "local_sqlite_paired_account_audit": account_audit,
        "local_after_cost_economic_hurdle": economic,
        "frozen_forward_common_l2_elapsed_ms": (
            common_end - FORWARD_NOT_BEFORE_MS
        ),
        "actual_local_72h_common_l2_observed": True,
        "externally_witnessed_source_and_signed_handoff_continuity": False,
        "independent_mainnet_venue_completeness_certified": False,
        "source_after_cost_edge_certified": False,
        "whole_account_profitable_edge_verified": False,
        "full_account_study_admissible": False,
        "execution_authority": False,
        "promotion_authority": False,
        "paper_only": True,
        "research_only": True,
    }
