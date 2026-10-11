from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayManifest
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import DecisionEpochEngine
from cocomelon.research.prospective_short_breakout_paired_entry import (
    ObservedRankWitness,
)
from cocomelon.research.prospective_short_breakout_paired_replay import (
    ShortRankIndependentPairedPaperReplay,
)
from cocomelon.research.prospective_short_breakout_pinned_source import (
    PinnedShortRankReplaySource,
)
from cocomelon.research.prospective_short_breakout_rank import (
    ProspectiveShortBreakoutRankState,
)
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    FirstSeenRankSnapshotStore,
    ShortRankFirstSeenError,
)

SHA256_HEX: Final = frozenset("0123456789abcdef")


class BoundShortRankArchiveError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PinnedFirstSeenRankArchive:
    """Verify complete local rank archive before creating either paper account.

    The expected digest must come from an independently preserved receipt.
    A matching caller-provided pin never proves authenticated worker origin.
    """

    root: Path
    expected_state_digest: str
    manifest: ReplayManifest
    freeze: ProspectiveShortBreakoutRankState

    def verified_snapshots(self) -> tuple[FirstSeenRankSnapshot, ...]:
        if (
            len(self.expected_state_digest) != 64
            or any(char not in SHA256_HEX for char in self.expected_state_digest)
        ):
            raise BoundShortRankArchiveError("rank archive pin must be sha256 hex")
        if (
            not self.root.is_dir()
            or self.root.is_symlink()
            or not (self.root / "snapshots").is_dir()
            or (self.root / "snapshots").is_symlink()
        ):
            raise BoundShortRankArchiveError("rank archive root is missing or symlinked")
        snapshot_root = self.root / "snapshots"
        # The original store ignores non-.json files; a source gate cannot.
        # A stray file, future-written .tmp, or symlink is an incomplete archive.
        entries = sorted(snapshot_root.iterdir())
        if not entries or any(
            entry.is_symlink()
            or not entry.is_file()
            or not entry.name.endswith(".json")
            or len(entry.name) != 21
            or not entry.name[:16].isdigit()
            for entry in entries
        ):
            raise BoundShortRankArchiveError(
                "rank archive has missing, noncanonical, or symlinked records"
            )
        try:
            snapshots = FirstSeenRankSnapshotStore(self.root).iter_records()
        except (OSError, ValueError, ShortRankFirstSeenError) as exc:
            raise BoundShortRankArchiveError(
                "rank archive rows failed canonical/digest validation"
            ) from exc
        actual_digest = hashlib.sha256(
            json.dumps(
                [snapshot.snapshot_digest for snapshot in snapshots],
                sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        if actual_digest != self.expected_state_digest:
            raise BoundShortRankArchiveError(
                "rank archive state digest differs from independently supplied pin"
            )
        if any(
            snapshot.observed_at_ms < self.manifest.start_ms
            or snapshot.captured_at_ms > self.manifest.end_ms
            for snapshot in snapshots
        ):
            raise BoundShortRankArchiveError(
                "rank archive falls outside full replay manifest coverage"
            )
        if not any(
            snapshot.captured_at_ms >= self.freeze.started_at_ms
            for snapshot in snapshots
        ):
            raise BoundShortRankArchiveError(
                "no first-seen rank snapshot in frozen forward interval"
            )
        return snapshots

    def receipt(
        self, snapshots: Sequence[FirstSeenRankSnapshot],
    ) -> dict[str, object]:
        return {
            "frozen_candidate_id": self.freeze.candidate_id,
            "expected_rank_archive_state_digest": self.expected_state_digest,
            "rank_snapshot_count": len(snapshots),
            "rank_observed_first_ms": snapshots[0].observed_at_ms,
            "rank_observed_last_ms": snapshots[-1].observed_at_ms,
            "rank_captured_first_ms": snapshots[0].captured_at_ms,
            "rank_captured_last_ms": snapshots[-1].captured_at_ms,
            "rank_capture_gaps_max_ms": max(
                (
                    later.captured_at_ms - earlier.captured_at_ms
                    for earlier, later in zip(snapshots, snapshots[1:])
                ),
                default=0,
            ),
            "entire_local_rank_archive_digest_matched": True,
            "rank_archive_pin_origin_authenticated": False,
            "rank_feature_provenance_against_market_archive_verified": False,
            "rank_capture_continuity_certified": False,
            "forward_maturity_certified": False,
            "promotion_authority": False,
            "execution_authority": False,
            "research_only": True,
        }


@dataclass(frozen=True, slots=True)
class FrozenFirstSeenRankWitnesses:
    """Read one fully checked archive exactly once for both paper lanes."""

    snapshots: tuple[FirstSeenRankSnapshot, ...]

    def witness_for_decision(
        self, market: MarketId, decision_ms: int,
    ) -> ObservedRankWitness | None:
        if type(decision_ms) is not int or decision_ms < 0:
            raise BoundShortRankArchiveError("rank decision timestamp invalid")
        # Strictly less than the actual post-calculation capture time; never
        # use a rank first persisted at the same millisecond as a decision.
        capture_times = [s.captured_at_ms for s in self.snapshots]
        index = bisect_left(capture_times, decision_ms) - 1
        if index < 0:
            return None
        snapshot = self.snapshots[index]
        for ranked_market, ordinal, _score, _reasons in snapshot.ranks:
            if ranked_market == market.canonical:
                return ObservedRankWitness(
                    ordinal=ordinal, observed_at_ms=snapshot.captured_at_ms,
                )
        # The latest *complete* rank snapshot omits the market. Never search
        # older snapshots and accidentally resurrect a filtered loser.
        return None


def run_rank_archive_bound_short_rank_paired_replay(
    *,
    market_source_root: str | Path,
    market_manifest: ReplayManifest,
    expected_market_manifest_id: str,
    rank_archive_root: str | Path,
    expected_rank_state_digest: str,
    freeze: ProspectiveShortBreakoutRankState,
    config: BaselineReplayConfig,
    selected_markets: Sequence[MarketId],
    account_root: str | Path,
    decision_engine_factory: Callable[[], DecisionEpochEngine] | None = None,
) -> dict[str, object]:
    """Replay exact pinned market + first-seen rank archives on two paper accounts.

    This offline runner intentionally has NO caller-controlled rank callback.
    The separately pinned archives are fully checked BEFORE either isolated
    paper account exists. The archive origins, completeness, handoff continuity
    and profitability still require independent external verification.
    """
    market_source = PinnedShortRankReplaySource(
        root=Path(market_source_root),
        manifest=market_manifest,
        expected_manifest_id=expected_market_manifest_id,
    )
    records = market_source.verified_records(
        forward_not_before_ms=freeze.started_at_ms
    )
    rank_source = PinnedFirstSeenRankArchive(
        root=Path(rank_archive_root),
        expected_state_digest=expected_rank_state_digest,
        manifest=market_manifest,
        freeze=freeze,
    )
    snapshots = rank_source.verified_snapshots()
    rank_witnesses = FrozenFirstSeenRankWitnesses(snapshots)
    root = Path(account_root).resolve()
    market_root = Path(market_source_root).resolve()
    rank_root = Path(rank_archive_root).resolve()
    if (
        root == market_root or market_root in root.parents
        or root == rank_root or rank_root in root.parents
        or root in market_root.parents or root in rank_root.parents
    ):
        raise BoundShortRankArchiveError(
            "paired paper account root overlaps immutable research evidence"
        )
    replay = ShortRankIndependentPairedPaperReplay(
        freeze=freeze,
        config=config,
        manifest=market_manifest,
        selected_markets=selected_markets,
        rank_witness_provider=rank_witnesses.witness_for_decision,
        state_root=account_root,
        decision_engine_factory=decision_engine_factory,
    )
    try:
        for record in records:
            replay.on_record(record)
        result = replay.summary()
        result["local_market_source_receipt"] = market_source.verification_receipt(
            records
        )
        result["local_rank_source_receipt"] = rank_source.receipt(snapshots)
        result["market_and_rank_sources_pinned_before_paper_accounts"] = True
        result["rank_evidence_source"] = "append_only_original_first_seen_rank_archive"
        # Deliberately leave source authenticity/continuity, full trial,
        # economic review readiness, and execution authority FALSE.
        return result
    finally:
        replay.close()
