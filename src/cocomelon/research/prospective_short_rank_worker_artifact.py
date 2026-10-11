"""Verify downloaded GitHub Actions rank artifacts against independently fetched metadata.

Accepts *bytes* from a workflow artifact and a run/attempt/head/digest binding
obtained separately through the authenticated GitHub API. Passing forged
binding metadata never creates a signature or certifies Hyperliquid source
completeness; trading and promotion authority remain disabled.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayManifest
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import DecisionEpochEngine
from cocomelon.research.prospective_short_breakout_paired_replay import (
    ShortRankIndependentPairedPaperReplay,
)
from cocomelon.research.prospective_short_breakout_pinned_source import (
    PinnedShortRankReplaySource,
)
from cocomelon.research.prospective_short_breakout_rank import (
    ProspectiveShortBreakoutRankState,
)
from cocomelon.research.prospective_short_rank_bound_archive import (
    FrozenFirstSeenRankWitnesses,
)
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    ShortRankFirstSeenError,
)

HEX: Final = frozenset("0123456789abcdef")
MAX_ARTIFACT_SIZE: Final = 64 * 1024 * 1024
MAX_SNAPSHOTS: Final = 40_000
RECEIPT_FILE: Final = "first-seen-short-rank-seal.json"
SOURCE_ZIP_FILE: Final = "first-seen-short-rank-source.zip"


class GithubShortRankArtifactError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value, separators=(",", ":"), sort_keys=True,
            ensure_ascii=False, allow_nan=False,
        ) + "\n"
    ).encode("utf-8")


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise GithubShortRankArtifactError(f"{label} invalid")
    return cast(dict[str, object], value)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ExpectedGithubRankArtifact:
    """Assertions to check against real GitHub API run/artifact responses.

    Caller MUST obtain these separately from GitHub; self-asserted values
    cannot establish provenance.
    """

    run_id: int
    run_attempt: int
    head_sha: str
    artifact_run_id: int
    artifact_head_sha: str
    artifact_name: str
    artifact_digest: str
    artifact_size_bytes: int

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not int or self.run_id <= 0
            or type(self.run_attempt) is not int or self.run_attempt <= 0
            or type(self.artifact_run_id) is not int
            or self.artifact_run_id != self.run_id
            or len(self.head_sha) != 40
            or any(char not in HEX for char in self.head_sha)
            or self.artifact_head_sha != self.head_sha
            or self.artifact_name != (
                f"continuous-paper-first-seen-short-rank-"
                f"{self.run_id}-{self.run_attempt}"
            )
            or not self.artifact_digest.startswith("sha256:")
            or len(self.artifact_digest) != 71
            or any(char not in HEX for char in self.artifact_digest[7:])
            or type(self.artifact_size_bytes) is not int
            or self.artifact_size_bytes <= 0
            or self.artifact_size_bytes > MAX_ARTIFACT_SIZE
        ):
            raise GithubShortRankArtifactError(
                "original GitHub worker/artifact identity is inconsistent"
            )


@dataclass(frozen=True, slots=True)
class VerifiedGithubShortRankEvidence:
    snapshots: tuple[FirstSeenRankSnapshot, ...]
    rank_state_digest: str
    archive_sha256: str
    worker_run_id: int
    worker_head_sha: str
    worker_run_attempt: int
    restored_from_run_id: int | None = None
    restored_from_run_attempt: int | None = None

    def receipt(self) -> dict[str, object]:
        return {
            "original_worker_run_id": self.worker_run_id,
            "original_worker_attempt": self.worker_run_attempt,
            "original_worker_head_sha": self.worker_head_sha,
            "restored_from_run_id_claimed": self.restored_from_run_id,
            "restored_from_run_attempt_claimed": self.restored_from_run_attempt,
            "rank_snapshot_count": len(self.snapshots),
            "rank_state_digest": self.rank_state_digest,
            "github_outer_artifact_sha256_reconciled": True,
            "sealed_rank_inner_zip_sha256_reconciled": True,
            "every_first_seen_rank_row_reconciled": True,
            "asserted_api_metadata_matched": True,
            "github_api_origin_authenticated_by_caller": False,
            "rank_features_bound_to_exact_mainnet_source": False,
            "terminal_account_profitability_certified": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }


def verify_github_original_short_rank_artifact(
    artifact_zip: bytes,
    *,
    expected: ExpectedGithubRankArtifact,
) -> VerifiedGithubShortRankEvidence:
    """Verify two ZIP layers and every rank digest, with zero filesystem writes."""
    if (
        not isinstance(artifact_zip, bytes)
        or len(artifact_zip) > MAX_ARTIFACT_SIZE
        or len(artifact_zip) != expected.artifact_size_bytes
        or f"sha256:{_sha256(artifact_zip)}" != expected.artifact_digest
    ):
        raise GithubShortRankArtifactError(
            "GitHub downloaded artifact bytes do not match API digest and size"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(artifact_zip)) as outer:
            entries = outer.infolist()
            if (
                len(entries) != 2
                or {entry.filename for entry in entries}
                != {RECEIPT_FILE, SOURCE_ZIP_FILE}
                or any(
                    entry.is_dir()
                    or entry.file_size > MAX_ARTIFACT_SIZE
                    for entry in entries
                )
            ):
                raise GithubShortRankArtifactError(
                    "GitHub rank artifact contains missing or unexpected members"
                )
            receipt_bytes = outer.read(RECEIPT_FILE)
            rank_zip_bytes = outer.read(SOURCE_ZIP_FILE)
        receipt = _object(json.loads(receipt_bytes), "worker rank seal")
        if receipt_bytes != _canonical(receipt):
            raise GithubShortRankArtifactError(
                "rank seal receipt has altered canonical bytes"
            )
        seal_ms = receipt.get("sealed_at_ms")
        if not isinstance(seal_ms, int) or isinstance(seal_ms, bool):
            raise GithubShortRankArtifactError(
                "worker seal completion timestamp invalid"
            )
        source_run_id = receipt.get("restored_from_run_id_claimed")
        source_attempt = receipt.get("restored_from_run_attempt_claimed")
        if (
            (source_run_id is None) != (source_attempt is None)
            or (
                source_run_id is not None and (
                    type(source_run_id) is not int or source_run_id <= 0
                    or type(source_attempt) is not int or source_attempt <= 0
                    or source_run_id == expected.run_id
                )
            )
        ):
            raise GithubShortRankArtifactError(
                "sealed predecessor run/attempt source identity invalid"
            )
        identity = {
            "worker_run_id_claimed": expected.run_id,
            "worker_run_attempt_claimed": expected.run_attempt,
            "worker_head_sha_claimed": expected.head_sha,
        }
        if (
            any(receipt.get(key) != value for key, value in identity.items())
            or receipt.get("rank_source_status") != "locally_sealed"
            or receipt.get("locally_verified_original_rank_files") is not True
            or receipt.get("ready_for_review") is not False
            or receipt.get("promotion_authority") is not False
            or receipt.get("execution_authority") is not False
            or receipt.get("archive_file_sha256") != _sha256(rank_zip_bytes)
            or receipt.get("archive_size_bytes") != len(rank_zip_bytes)
        ):
            raise GithubShortRankArtifactError(
                "source seal does not match original worker and archive bytes"
            )
        with zipfile.ZipFile(io.BytesIO(rank_zip_bytes)) as rank_zip:
            entries = rank_zip.infolist()
            if (
                not entries or entries[0].filename != "manifest.json"
                or len(entries) > MAX_SNAPSHOTS + 1
                or any(
                    entry.is_dir()
                    or entry.file_size > MAX_ARTIFACT_SIZE
                    for entry in entries
                )
            ):
                raise GithubShortRankArtifactError(
                    "sealed rank ZIP contains invalid members"
                )
            manifest_bytes = rank_zip.read("manifest.json")
            manifest = _object(
                json.loads(manifest_bytes), "inner rank manifest"
            )
            if manifest_bytes != _canonical(manifest):
                raise GithubShortRankArtifactError(
                    "rank manifest has altered canonical bytes"
                )
            files = manifest.get("files")
            if (
                not isinstance(files, list)
                or len(files) == 0
                or len(files) != len(entries) - 1
                or len(files) > MAX_SNAPSHOTS
                or len(files) != receipt.get("archive_snapshot_count")
                or manifest.get("rank_snapshot_count") != len(files)
                or any(manifest.get(k) != v for k, v in identity.items())
                or manifest.get("restored_from_run_id_claimed") != source_run_id
                or manifest.get("restored_from_run_attempt_claimed") != source_attempt
                or manifest.get("rank_state_digest")
                != receipt.get("rank_state_digest")
                or manifest.get("sealed_at_ms") != receipt.get("sealed_at_ms")
                or manifest.get("promotion_authority") is not False
                or manifest.get("execution_authority") is not False
            ):
                raise GithubShortRankArtifactError(
                    "inner rank manifest conflicts with worker seal"
                )
            snapshots: list[FirstSeenRankSnapshot] = []
            prev_observed, prev_captured = -1, -1
            for member, descriptor_raw in zip(
                entries[1:], files, strict=True,
            ):
                descriptor = _object(descriptor_raw, "rank file descriptor")
                name = descriptor.get("path")
                if (
                    not isinstance(name, str)
                    or len(name) != len("snapshots/0000000000000000.json")
                    or not name.startswith("snapshots/")
                    or not name.endswith(".json")
                    or not name[10:26].isascii()
                    or not name[10:26].isdigit()
                    or member.filename != name
                    or member.file_size > MAX_ARTIFACT_SIZE
                ):
                    raise GithubShortRankArtifactError(
                        "original rank archive has noncanonical record path"
                    )
                row = rank_zip.read(member)
                snapshot = FirstSeenRankSnapshot.from_dict(json.loads(row))
                if (
                    row != _canonical(snapshot.to_dict())
                    or name != f"snapshots/{snapshot.observed_at_ms:016d}.json"
                    or descriptor.get("sha256") != _sha256(row)
                    or descriptor.get("byte_size") != len(row)
                    or descriptor.get("snapshot_digest") != snapshot.snapshot_digest
                    or descriptor.get("observed_at_ms") != snapshot.observed_at_ms
                    or descriptor.get("captured_at_ms") != snapshot.captured_at_ms
                    or snapshot.observed_at_ms <= prev_observed
                    or snapshot.captured_at_ms < prev_captured
                    or snapshot.captured_at_ms > seal_ms
                ):
                    raise GithubShortRankArtifactError(
                        "original rank row bytes or chronology mismatch"
                    )
                snapshots.append(snapshot)
                prev_observed = snapshot.observed_at_ms
                prev_captured = snapshot.captured_at_ms
        state_digest = _sha256(_canonical(
            [s.snapshot_digest for s in snapshots]
        ).rstrip(b"\n"))
        if (
            state_digest != manifest.get("rank_state_digest")
            or state_digest != receipt.get("rank_state_digest")
            or manifest.get("first_observed_at_ms") != snapshots[0].observed_at_ms
            or manifest.get("last_observed_at_ms") != snapshots[-1].observed_at_ms
            or manifest.get("first_captured_at_ms") != snapshots[0].captured_at_ms
            or manifest.get("last_captured_at_ms") != snapshots[-1].captured_at_ms
        ):
            raise GithubShortRankArtifactError(
                "rank state digest or complete snapshot interval mismatch"
            )
    except (
        ValueError, OSError, KeyError, TypeError,
        zipfile.BadZipFile, ShortRankFirstSeenError,
    ) as exc:
        raise GithubShortRankArtifactError(
            "GitHub rank artifact contains unreadable or inconsistent source"
        ) from exc

    return VerifiedGithubShortRankEvidence(
        snapshots=tuple(snapshots),
        rank_state_digest=state_digest,
        archive_sha256=_sha256(artifact_zip),
        worker_run_id=expected.run_id,
        worker_head_sha=expected.head_sha,
        worker_run_attempt=expected.run_attempt,
        restored_from_run_id=source_run_id,
        restored_from_run_attempt=cast(int | None, source_attempt),
    )


def run_github_original_rank_bound_paired_replay(
    *,
    market_source_root: str | Path,
    market_manifest: ReplayManifest,
    expected_market_manifest_id: str,
    github_artifact_zip: bytes,
    github_binding: ExpectedGithubRankArtifact,
    freeze: ProspectiveShortBreakoutRankState,
    config: BaselineReplayConfig,
    selected_markets: Sequence[MarketId],
    account_root: str | Path,
    decision_engine_factory: Callable[[], DecisionEpochEngine] | None = None,
) -> dict[str, object]:
    """Run two paper accounts only after complete source and artifact checks.

    A locally pinned market manifest is NOT independently authenticated,
    and a supplied GitHub binding does not attest its own trusted API origin.
    """
    market = PinnedShortRankReplaySource(
        root=Path(market_source_root),
        manifest=market_manifest,
        expected_manifest_id=expected_market_manifest_id,
    )
    records = market.verified_records(
        forward_not_before_ms=freeze.started_at_ms
    )
    rank = verify_github_original_short_rank_artifact(
        github_artifact_zip, expected=github_binding,
    )
    if (
        rank.snapshots[0].observed_at_ms < market_manifest.start_ms
        or rank.snapshots[-1].captured_at_ms > market_manifest.end_ms
        or not any(
            snapshot.captured_at_ms >= freeze.started_at_ms
            for snapshot in rank.snapshots
        )
    ):
        raise GithubShortRankArtifactError(
            "authenticated rank interval does not match recorded market source"
        )
    root = Path(account_root).resolve()
    source_root = Path(market_source_root).resolve()
    if (
        root == source_root or source_root in root.parents
        or root in source_root.parents
    ):
        raise GithubShortRankArtifactError(
            "paper account root overlaps original market evidence"
        )
    provider = FrozenFirstSeenRankWitnesses(rank.snapshots)
    replay = ShortRankIndependentPairedPaperReplay(
        freeze=freeze,
        config=config,
        manifest=market_manifest,
        selected_markets=selected_markets,
        rank_witness_provider=provider.witness_for_decision,
        state_root=account_root,
        decision_engine_factory=decision_engine_factory,
    )
    try:
        for record in records:
            replay.on_record(record)
        summary = replay.summary()
        summary["local_market_source_receipt"] = market.verification_receipt(records)
        summary["original_worker_rank_archive_receipt"] = rank.receipt()
        summary["original_rank_artifact_digest_checked_before_accounts"] = True
        summary["full_account_trial"] = False
        summary["ready_for_review"] = False
        summary["execution_authority"] = False
        summary["promotion_authority"] = False
        return summary
    finally:
        replay.close()
