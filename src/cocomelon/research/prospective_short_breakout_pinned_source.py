from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayRecord
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import DecisionEpochEngine
from cocomelon.replay.adapters import (
    EvidenceClassError,
    ReplayRequirements,
    validate_replay_evidence,
)
from cocomelon.replay.clock import canonical_record_order
from cocomelon.replay.source import (
    JsonlReplaySource,
    RecordingValidationError,
    validate_recording,
)
from cocomelon.research.prospective_short_breakout_paired_entry import (
    RankWitnessProvider,
)
from cocomelon.research.prospective_short_breakout_paired_replay import (
    ShortRankIndependentPairedPaperReplay,
)
from cocomelon.research.prospective_short_breakout_rank import (
    ProspectiveShortBreakoutRankState,
)

HEX_CHARS: Final = frozenset("0123456789abcdef")


class ShortRankPinnedSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PinnedShortRankReplaySource:
    """Check every byte of a local recorder archive against an external pin.

    The pin MUST come from an independently obtained original-source receipt.
    Locally asserting a digest does NOT attest its remote origin, rank history,
    market completeness, or handoff continuity; the report stays nonpromotable.
    """

    root: Path
    manifest: ReplayManifest
    expected_manifest_id: str

    def verified_records(
        self, *, forward_not_before_ms: int,
    ) -> tuple[ReplayRecord, ...]:
        if (
            len(self.expected_manifest_id) != 24
            or any(char not in HEX_CHARS for char in self.expected_manifest_id)
            or self.expected_manifest_id != self.manifest.manifest_id
        ):
            raise ShortRankPinnedSourceError(
                "replay manifest identity does not match independent supplied pin"
            )
        if self.manifest.evidence_class is not EvidenceClass.MICROSTRUCTURE:
            raise ShortRankPinnedSourceError(
                "signed account replay requires microstructure records"
            )
        if (
            type(forward_not_before_ms) is not int
            or forward_not_before_ms < self.manifest.start_ms
            or forward_not_before_ms > self.manifest.end_ms
        ):
            raise ShortRankPinnedSourceError(
                "frozen forward boundary is not covered by source manifest"
            )
        root = self.root
        if not root.is_dir() or root.is_symlink():
            raise ShortRankPinnedSourceError("source archive root is invalid")
        # Reject both symlinked segments and symlinked parent directories,
        # including traversals pointing back into the archive.
        for segment in self.manifest.segments:
            path = root
            for part in Path(segment.relative_path).parts:
                path = path / part
                if path.is_symlink():
                    raise ShortRankPinnedSourceError(
                        "source archive contains symlinked segment path"
                    )
        try:
            actual = validate_recording(root)
        except (OSError, RecordingValidationError, ValueError) as exc:
            raise ShortRankPinnedSourceError(
                "source recorder archive failed independent byte/row validation"
            ) from exc
        if actual != self.manifest.segments:
            raise ShortRankPinnedSourceError(
                "source segment identity differs from pinned replay manifest"
            )
        if (
            min(seg.first_available_at_ms for seg in actual) < self.manifest.start_ms
            or max(seg.last_available_at_ms for seg in actual) > self.manifest.end_ms
        ):
            raise ShortRankPinnedSourceError(
                "source manifest would silently censor archived observations"
            )
        try:
            records = canonical_record_order(
                JsonlReplaySource(root).iter_records(self.manifest)
            )
            validate_replay_evidence(
                self.manifest, records, ReplayRequirements(requires_l2=True),
            )
        except (OSError, RecordingValidationError, EvidenceClassError, ValueError) as exc:
            raise ShortRankPinnedSourceError(
                "source replay cannot be reconciled to recorded microstructure"
            ) from exc
        if len(records) != sum(seg.row_count for seg in actual):
            raise ShortRankPinnedSourceError(
                "pinned archive and replay record populations differ"
            )
        if not any(record.available_at_ms >= forward_not_before_ms for record in records):
            raise ShortRankPinnedSourceError(
                "source has no actual post-freeze observation"
            )
        return records

    def verification_receipt(
        self, records: Sequence[ReplayRecord],
    ) -> dict[str, object]:
        """Describe only the locally checked digest, not exchange attestation."""
        return {
            "manifest_id": self.manifest.manifest_id,
            "expected_manifest_id": self.expected_manifest_id,
            "source_segment_count": len(self.manifest.segments),
            "source_segment_bytes": sum(s.byte_count for s in self.manifest.segments),
            "source_segment_rows": sum(s.row_count for s in self.manifest.segments),
            "loaded_record_count": len(records),
            "source_segment_sha256s": tuple(
                s.sha256 for s in self.manifest.segments
            ),
            "local_archive_exact_segment_match": True,
            "externally_supplied_manifest_pin_matched": True,
            "pin_origin_independently_authenticated": False,
            "mainnet_provenance_independently_authenticated": False,
            "source_market_data_gap_free_certified": False,
            "rank_observation_lineage_authenticated": False,
            "handoff_continuity_certified": False,
            "full_account_forward_profitability_certified": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }


def run_digest_pinned_short_rank_paired_replay(
    *,
    source_root: str | Path,
    manifest: ReplayManifest,
    expected_manifest_id: str,
    freeze: ProspectiveShortBreakoutRankState,
    config: BaselineReplayConfig,
    selected_markets: Sequence[MarketId],
    rank_witness_provider: RankWitnessProvider,
    account_root: str | Path,
    decision_engine_factory: Callable[[], DecisionEpochEngine] | None = None,
) -> dict[str, object]:
    """Validate the entire source BEFORE creating either paper account.

    A runnable offline trial needs real, independently obtained archive and
    rank-witness inputs. Neither fixture values nor the returned local hashes
    can claim independently authenticated profitability.
    """
    source = PinnedShortRankReplaySource(
        root=Path(source_root),
        manifest=manifest,
        expected_manifest_id=expected_manifest_id,
    )
    records = source.verified_records(forward_not_before_ms=freeze.started_at_ms)
    replay = ShortRankIndependentPairedPaperReplay(
        freeze=freeze,
        config=config,
        manifest=manifest,
        selected_markets=selected_markets,
        rank_witness_provider=rank_witness_provider,
        state_root=account_root,
        decision_engine_factory=decision_engine_factory,
    )
    try:
        for record in records:
            replay.on_record(record)
        summary = replay.summary()
        # Do NOT change any underlying signed account report or mark a
        # caller-supplied manifest pin as true remote-origin attestation.
        summary["local_archive_verification"] = source.verification_receipt(records)
        return summary
    finally:
        replay.close()
