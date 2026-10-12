"""Independent GitHub SHA-bound original SHORT rank market eligibility proof.

The GitHub API provenance must be fetched independently by the caller.
Three separate original worker artifact ZIPs and a completed worker are
required; no self-declared source bytes establish an exchange feed signature.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from typing import Final, cast

from cocomelon.research.prospective_short_rank_full_feature_artifact import (
    VerifiedGithubOriginalRankInputs,
)
from cocomelon.research.prospective_short_rank_full_features import (
    OriginalRankInputBatchError,
)
from cocomelon.research.prospective_short_rank_market_context import (
    OriginalRankEligibilityContextBatch,
    OriginalRankEligibilityContextError,
    replay_recorded_rank_eligibility,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    VerifiedGithubShortRankEvidence,
)
from scripts.seal_paper_short_rank_market_context import (
    BUNDLE_FILE,
    MAX_CONTEXT_BATCH_BYTES,
    MAX_CONTEXT_BATCHES,
    RECEIPT_FILE,
)

MAX_GITHUB_ARTIFACT_SIZE: Final = 256 * 1024 * 1024
MAX_INNER_TOTAL_UNCOMPRESSED: Final = 512 * 1024 * 1024
MAX_MANIFEST_BYTES: Final = 16 * 1024 * 1024
MAX_RECEIPT_BYTES: Final = 1024 * 1024
HEX: Final = frozenset("0123456789abcdef")


class OriginalRankContextArtifactError(RuntimeError):
    pass


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(data: object) -> bytes:
    return (json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ) + "\n").encode("utf-8")


def _json(raw: bytes) -> dict[str, object]:
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != _canonical(value):
        raise OriginalRankContextArtifactError(
            "rank context original seal or manifest bytes noncanonical"
        )
    return cast(dict[str, object], value)


@dataclass(frozen=True, slots=True)
class ExpectedGithubRankContextArtifact:
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
            or not isinstance(self.head_sha, str)
            or len(self.head_sha) != 40
            or any(c not in HEX for c in self.head_sha)
            or self.artifact_head_sha != self.head_sha
            or self.artifact_name != (
                "continuous-paper-first-seen-short-rank-market-context-"
                f"{self.run_id}-{self.run_attempt}"
            )
            or not isinstance(self.artifact_digest, str)
            or len(self.artifact_digest) != 71
            or not self.artifact_digest.startswith("sha256:")
            or any(c not in HEX for c in self.artifact_digest[7:])
            or type(self.artifact_size_bytes) is not int
            or not 0 < self.artifact_size_bytes <= MAX_GITHUB_ARTIFACT_SIZE
        ):
            raise OriginalRankContextArtifactError(
                "GitHub original rank context artifact metadata invalid"
            )


@dataclass(frozen=True, slots=True)
class VerifiedGithubOriginalRankContexts:
    batches: tuple[OriginalRankEligibilityContextBatch, ...]
    source_digest: str
    worker_run_id: int
    worker_run_attempt: int
    worker_head_sha: str
    historical_rank_snapshots_without_context: int
    total_market_eligibilities_replayed: int

    def receipt(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "original_worker_run_id": self.worker_run_id,
            "original_worker_run_attempt": self.worker_run_attempt,
            "original_worker_head_sha": self.worker_head_sha,
            "verified_rank_context_batches": len(self.batches),
            "original_rank_snapshots_without_market_context": (
                self.historical_rank_snapshots_without_context
            ),
            "original_rank_market_context_source_digest": self.source_digest,
            "original_eligibility_markets_replayed": (
                self.total_market_eligibilities_replayed
            ),
            "rankable_membership_reconstructed_from_github_bound_producer_context": True,
            "market_context_source_independently_authenticated_from_exchange": False,
            "original_full_account_after_cost_profitability_certified": False,
            "research_only": True,
            "ready_for_review": False,
            "execution_authority": False,
            "promotion_authority": False,
        }


def verify_github_original_rank_market_context_artifact(
    artifact_zip: bytes,
    *,
    expected: ExpectedGithubRankContextArtifact,
    original_rank: VerifiedGithubShortRankEvidence,
    original_features: VerifiedGithubOriginalRankInputs,
) -> VerifiedGithubOriginalRankContexts:
    """Verify every context record and replay its original rankable universe."""
    if (
        not isinstance(artifact_zip, bytes)
        or len(artifact_zip) != expected.artifact_size_bytes
        or f"sha256:{_hash(artifact_zip)}" != expected.artifact_digest
    ):
        raise OriginalRankContextArtifactError(
            "GitHub market context artifact outer bytes/digest mismatch"
        )
    if (
        expected.run_id != original_rank.worker_run_id
        or expected.run_id != original_features.worker_run_id
        or expected.run_attempt != original_rank.worker_run_attempt
        or expected.run_attempt != original_features.worker_attempt
        or expected.head_sha != original_rank.worker_head_sha
        or expected.head_sha != original_features.worker_head_sha
    ):
        raise OriginalRankContextArtifactError(
            "original market context, rank and full feature worker identities differ"
        )
    identity: dict[str, object] = {
        "worker_run_id_claimed": expected.run_id,
        "worker_run_attempt_claimed": expected.run_attempt,
        "worker_head_sha_claimed": expected.head_sha,
    }
    try:
        with zipfile.ZipFile(io.BytesIO(artifact_zip)) as outer:
            members = outer.infolist()
            if (
                len(members) != 2
                or {row.filename for row in members} != {
                    BUNDLE_FILE, RECEIPT_FILE,
                }
                or any(
                    row.is_dir()
                    or (row.external_attr >> 16) & 0o170000 == 0o120000
                    or row.file_size > (
                        MAX_RECEIPT_BYTES
                        if row.filename == RECEIPT_FILE
                        else MAX_GITHUB_ARTIFACT_SIZE
                    )
                    for row in members
                )
            ):
                raise OriginalRankContextArtifactError(
                    "GitHub original context artifact has extra or unsafe members"
                )
            receipt = _json(outer.read(RECEIPT_FILE))
            original_zip = outer.read(BUNDLE_FILE)
        count = receipt.get("verified_market_context_batches")
        historical = receipt.get("rank_snapshots_without_context")
        seal_time = receipt.get("sealed_at_ms")
        ranks = original_rank.snapshots
        full = original_features.batches
        if (
            receipt.get("schema_version") != 1
            or any(receipt.get(k) != v for k, v in identity.items())
            or receipt.get("original_rank_market_context_status")
            != "locally_sealed_prospective_suffix"
            or receipt.get("local_original_eligibility_membership_replayed")
            is not True
            or receipt.get("ready_for_review") is not False
            or receipt.get("execution_authority") is not False
            or receipt.get("promotion_authority") is not False
            or receipt.get("independent_mainnet_market_stream_authenticated")
            is not False
            or receipt.get("zip_sha256") != _hash(original_zip)
            or receipt.get("zip_size_bytes") != len(original_zip)
            or receipt.get("original_rank_state_digest")
            != original_rank.rank_state_digest
            or receipt.get("original_feature_source_digest")
            != original_features.source_digest
            or type(count) is not int or not 0 < count <= MAX_CONTEXT_BATCHES
            or type(historical) is not int or historical < 0
            or historical + count != len(ranks)
            or count > len(full)
            or type(seal_time) is not int or seal_time < 0
        ):
            raise OriginalRankContextArtifactError(
                "original market context receipt disagrees with two source cohorts"
            )
        full_offset = len(full) - count
        rank_digest = original_rank.rank_state_digest
        feature_digest = original_features.source_digest
        with zipfile.ZipFile(io.BytesIO(original_zip)) as inner:
            records = inner.infolist()
            if (
                len(records) != count + 1
                or records[0].filename != "manifest.json"
                or sum(item.file_size for item in records)
                > MAX_INNER_TOTAL_UNCOMPRESSED
                or any(
                    item.is_dir()
                    or (item.external_attr >> 16) & 0o170000 == 0o120000
                    or item.file_size > (
                        MAX_MANIFEST_BYTES
                        if item.filename == "manifest.json"
                        else MAX_CONTEXT_BATCH_BYTES
                    )
                    for item in records
                )
            ):
                raise OriginalRankContextArtifactError(
                    "original inner market context archive unsafe or incomplete"
                )
            manifest = _json(inner.read("manifest.json"))
            files = manifest.get("files")
            if (
                manifest.get("schema_version") != 1
                or any(manifest.get(k) != v for k, v in identity.items())
                or manifest.get("sealed_at_ms") != seal_time
                or manifest.get("original_rank_state_digest") != rank_digest
                or manifest.get("original_feature_source_digest") != feature_digest
                or manifest.get("original_context_source_digest")
                != receipt.get("original_context_source_digest")
                or manifest.get("verified_market_context_batches") != count
                or manifest.get("rank_snapshot_count") != len(ranks)
                or manifest.get("rank_snapshots_without_context") != historical
                or manifest.get("ready_for_review") is not False
                or manifest.get("execution_authority") is not False
                or manifest.get("promotion_authority") is not False
                or manifest.get("independent_mainnet_market_stream_authenticated")
                is not False
                or not isinstance(files, list)
                or len(files) != count
            ):
                raise OriginalRankContextArtifactError(
                    "original context manifest disagrees with GitHub bound sources"
                )
            batches: list[OriginalRankEligibilityContextBatch] = []
            total_markets = 0
            for index, (row, file_info) in enumerate(
                zip(records[1:], files, strict=True)
            ):
                if not isinstance(file_info, dict):
                    raise OriginalRankContextArtifactError(
                        "original context manifest descriptor invalid"
                    )
                parent = ranks[historical + index]
                full_feature = full[full_offset + index]
                expected_path = f"batches/{parent.observed_at_ms:016d}.json"
                if (
                    row.filename != expected_path
                    or file_info.get("path") != expected_path
                    or row.file_size != file_info.get("byte_size")
                ):
                    raise OriginalRankContextArtifactError(
                        "original market context manifest file population altered"
                    )
                raw = inner.read(row)
                batch = OriginalRankEligibilityContextBatch.from_dict(
                    json.loads(raw)
                )
                if (
                    raw != _canonical(batch.to_dict())
                    or file_info.get("sha256") != _hash(raw)
                    or file_info.get("observed_at_ms") != batch.observed_at_ms
                    or file_info.get("rank_snapshot_digest")
                    != batch.rank_snapshot_digest
                    or file_info.get("batch_sha256") != batch.batch_sha256
                    or file_info.get("market_count") != len(batch.snapshots)
                    or batch.captured_at_ms > seal_time
                ):
                    raise OriginalRankContextArtifactError(
                        "original context batch byte digest or parent changed"
                    )
                replay_recorded_rank_eligibility(
                    rank=parent, feature_inputs=full_feature, context=batch,
                )
                total_markets += len(batch.snapshots)
                batches.append(batch)
            source_digest = _hash(_canonical([
                {
                    "observed_at_ms": batch.observed_at_ms,
                    "rank_snapshot_digest": batch.rank_snapshot_digest,
                    "batch_sha256": batch.batch_sha256,
                }
                for batch in batches
            ]))
            if (
                source_digest != receipt.get("original_context_source_digest")
                or source_digest != manifest.get("original_context_source_digest")
                or manifest.get("first_context_observed_at_ms")
                != batches[0].observed_at_ms
                or manifest.get("last_context_observed_at_ms")
                != batches[-1].observed_at_ms
                or manifest.get("source_context_markets_replayed")
                != total_markets
            ):
                raise OriginalRankContextArtifactError(
                    "original complete market context population digest changed"
                )
    except (
        OSError, ValueError, TypeError, zipfile.BadZipFile,
        OriginalRankEligibilityContextError, OriginalRankInputBatchError,
    ) as exc:
        raise OriginalRankContextArtifactError(
            "GitHub original context artifact unreadable, altered or incomplete"
        ) from exc
    return VerifiedGithubOriginalRankContexts(
        batches=tuple(batches), source_digest=source_digest,
        worker_run_id=expected.run_id,
        worker_run_attempt=expected.run_attempt,
        worker_head_sha=expected.head_sha,
        historical_rank_snapshots_without_context=historical,
        total_market_eligibilities_replayed=total_markets,
    )
