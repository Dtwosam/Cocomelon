"""Authenticate original SHORT rank-input payload artifacts against ranked source.

Requires separately authenticated GitHub Actions original worker + artifact
metadata and an already SHA-verified full original first-seen rank cohort.
Matching self-declared JSON is NOT an authenticated market-data feature source.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from typing import Final, cast

from cocomelon.research.prospective_short_rank_full_features import (
    OriginalRankFeatureInputBatch,
    OriginalRankInputBatchError,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    VerifiedGithubShortRankEvidence,
)
from scripts.seal_paper_short_rank_full_features import (
    BUNDLE_FILE,
    MAX_BATCH_SIZE,
    MAX_BATCHES,
    RECEIPT_FILE,
)

MAX_GITHUB_ZIP_BYTES: Final = 256 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES: Final = 512 * 1024 * 1024
HEX: Final = frozenset("0123456789abcdef")


class OriginalRankFeatureArtifactError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(data: object) -> bytes:
    return (
        json.dumps(
            data, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ) + "\n"
    ).encode("utf-8")


def _object(data: object, name: str) -> dict[str, object]:
    if not isinstance(data, dict) or any(
        not isinstance(key, str) for key in data
    ):
        raise OriginalRankFeatureArtifactError(f"{name} must be an object")
    return cast(dict[str, object], data)


def _json(data: bytes, name: str) -> dict[str, object]:
    value = _object(json.loads(data), name)
    if data != _canonical(value):
        raise OriginalRankFeatureArtifactError(
            f"{name} is not canonical original bytes"
        )
    return value


@dataclass(frozen=True, slots=True)
class ExpectedGithubRankInputArtifact:
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
            or any(ch not in HEX for ch in self.head_sha)
            or self.artifact_head_sha != self.head_sha
            or self.artifact_name != (
                "continuous-paper-first-seen-short-rank-full-inputs-"
                f"{self.run_id}-{self.run_attempt}"
            )
            or not isinstance(self.artifact_digest, str)
            or not self.artifact_digest.startswith("sha256:")
            or len(self.artifact_digest) != 71
            or any(ch not in HEX for ch in self.artifact_digest[7:])
            or type(self.artifact_size_bytes) is not int
            or not 0 < self.artifact_size_bytes <= MAX_GITHUB_ZIP_BYTES
        ):
            raise OriginalRankFeatureArtifactError(
                "original GitHub full-rank input artifact identity invalid"
            )


@dataclass(frozen=True, slots=True)
class VerifiedGithubOriginalRankInputs:
    batches: tuple[OriginalRankFeatureInputBatch, ...]
    historical_rank_snapshots_without_inputs: int
    source_digest: str
    archive_sha256: str
    original_rank_state_digest: str
    worker_run_id: int
    worker_head_sha: str
    worker_attempt: int

    def receipt(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "original_worker_run_id": self.worker_run_id,
            "original_worker_attempt": self.worker_attempt,
            "original_worker_head_sha": self.worker_head_sha,
            "original_rank_state_digest": self.original_rank_state_digest,
            "original_feature_batch_source_digest": self.source_digest,
            "verified_full_input_batches": len(self.batches),
            "historical_rank_snapshots_without_full_inputs": (
                self.historical_rank_snapshots_without_inputs
            ),
            "original_full_input_suffix_first_observed_ms": (
                self.batches[0].observed_at_ms
            ),
            "original_full_input_suffix_last_observed_ms": (
                self.batches[-1].observed_at_ms
            ),
            "rank_feature_payload_identity_closed_for_verified_suffix": True,
            "entire_rank_history_full_inputs_present": (
                self.historical_rank_snapshots_without_inputs == 0
            ),
            "github_artifact_sha256_and_inner_zip_verified": True,
            "github_original_run_metadata_origin_attested_by_caller": False,
            "full_hyperliquid_market_stream_attested": False,
            "all_market_data_gaps_resolved": False,
            "feature_values_independently_reconstructed_from_market": False,
            "full_account_trial": False,
            "ready_for_review": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }


def verify_github_original_rank_full_input_artifact(
    artifact_zip: bytes,
    *,
    expected: ExpectedGithubRankInputArtifact,
    original_rank: VerifiedGithubShortRankEvidence,
) -> VerifiedGithubOriginalRankInputs:
    """Require entire original rank-input suffix to match pinned rank source."""
    if (
        not isinstance(artifact_zip, bytes)
        or len(artifact_zip) != expected.artifact_size_bytes
        or f"sha256:{_sha256(artifact_zip)}" != expected.artifact_digest
    ):
        raise OriginalRankFeatureArtifactError(
            "GitHub full-feature artifact bytes, SHA256 or size mismatch"
        )
    if (
        expected.run_id != original_rank.worker_run_id
        or expected.run_attempt != original_rank.worker_run_attempt
        or expected.head_sha != original_rank.worker_head_sha
    ):
        raise OriginalRankFeatureArtifactError(
            "original ranking and full feature source worker identities differ"
        )
    identity: dict[str, object] = {
        "worker_run_id_claimed": expected.run_id,
        "worker_run_attempt_claimed": expected.run_attempt,
        "worker_head_sha_claimed": expected.head_sha,
    }
    try:
        with zipfile.ZipFile(io.BytesIO(artifact_zip)) as external:
            members = external.infolist()
            if (
                len(members) != 2
                or {member.filename for member in members}
                != {BUNDLE_FILE, RECEIPT_FILE}
                or any(
                    member.is_dir()
                    or member.file_size > MAX_GITHUB_ZIP_BYTES
                    or (member.external_attr >> 16) & 0o170000 == 0o120000
                    for member in members
                )
            ):
                raise OriginalRankFeatureArtifactError(
                    "GitHub original full rank artifact has extra or unsafe members"
                )
            receipt_data = external.read(RECEIPT_FILE)
            original_zip = external.read(BUNDLE_FILE)
        receipt = _json(receipt_data, "original full rank input seal")
        historical = receipt.get("historical_rank_snapshots_without_full_inputs")
        count = receipt.get("verified_full_input_batch_count")
        seal_time = receipt.get("sealed_at_ms")
        if (
            type(seal_time) is not int or seal_time < 0
            or receipt.get("schema_version") != 1
        ):
            raise OriginalRankFeatureArtifactError(
                "original full rank seal timestamp or schema invalid"
            )
        if (
            any(receipt.get(key) != value for key, value in identity.items())
            or receipt.get("full_rank_feature_status")
            != "locally_sealed_prospective_suffix"
            or receipt.get("execution_authority") is not False
            or receipt.get("promotion_authority") is not False
            or receipt.get("ready_for_review") is not False
            or receipt.get("zip_sha256") != _sha256(original_zip)
            or receipt.get("zip_size_bytes") != len(original_zip)
            or receipt.get("rank_state_digest")
            != original_rank.rank_state_digest
            or receipt.get("rank_snapshot_count") != len(original_rank.snapshots)
            or type(historical) is not int
            or historical < 0
            or type(count) is not int or not 0 < count <= MAX_BATCHES
            or historical + count != len(original_rank.snapshots)
            or receipt.get("entire_rank_history_full_feature_inputs_complete")
            is not (historical == 0)
        ):
            raise OriginalRankFeatureArtifactError(
                "original full input seal disagrees with verified rank population"
            )
        with zipfile.ZipFile(io.BytesIO(original_zip)) as bundle:
            entries = bundle.infolist()
            if (
                len(entries) != count + 1
                or entries[0].filename != "manifest.json"
                or sum(entry.file_size for entry in entries)
                > MAX_TOTAL_UNCOMPRESSED_BYTES
                or any(
                    entry.is_dir() or entry.file_size > MAX_BATCH_SIZE
                    if entry.filename != "manifest.json" else
                    entry.file_size > MAX_GITHUB_ZIP_BYTES
                    for entry in entries
                )
            ):
                raise OriginalRankFeatureArtifactError(
                    "original rank input ZIP population or byte size invalid"
                )
            manifest = _json(
                bundle.read("manifest.json"), "original feature input manifest",
            )
            descriptions = manifest.get("files")
            if (
                manifest.get("schema_version") != 1
                or not isinstance(descriptions, list)
                or len(descriptions) != count
                or any(manifest.get(key) != value for key, value in identity.items())
                or manifest.get("rank_state_digest")
                != original_rank.rank_state_digest
                or manifest.get("feature_input_source_digest")
                != receipt.get("feature_input_source_digest")
                or manifest.get("rank_snapshot_count")
                != len(original_rank.snapshots)
                or manifest.get("verified_full_input_batch_count") != count
                or manifest.get("historical_rank_snapshots_without_full_inputs")
                != historical
                or manifest.get("sealed_at_ms") != receipt.get("sealed_at_ms")
                or manifest.get("ready_for_review") is not False
                or manifest.get("promotion_authority") is not False
            ):
                raise OriginalRankFeatureArtifactError(
                    "rank feature source manifest disagrees with original seal"
                )
            result: list[OriginalRankFeatureInputBatch] = []
            for offset, (entry, source_row) in enumerate(
                zip(entries[1:], descriptions, strict=True),
            ):
                descriptor = _object(source_row, "feature input file descriptor")
                parent = original_rank.snapshots[historical + offset]
                path = f"batches/{parent.observed_at_ms:016d}.json"
                if (
                    entry.filename != path
                    or descriptor.get("path") != path
                    or entry.file_size != descriptor.get("byte_size")
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise OriginalRankFeatureArtifactError(
                        "feature input batch path, length or type changed"
                    )
                raw = bundle.read(entry)
                batch = OriginalRankFeatureInputBatch.from_dict(json.loads(raw))
                if (
                    raw != _canonical(batch.to_dict())
                    or descriptor.get("sha256") != _sha256(raw)
                    or descriptor.get("batch_sha256") != batch.batch_sha256
                    or descriptor.get("rank_snapshot_digest")
                    != batch.rank_snapshot_digest
                    or descriptor.get("feature_market_count") != len(batch.features)
                    or descriptor.get("observed_at_ms") != batch.observed_at_ms
                    or descriptor.get("captured_at_ms") != batch.captured_at_ms
                    or batch.captured_at_ms > seal_time
                ):
                    raise OriginalRankFeatureArtifactError(
                        "exact original rank input file/source digest mismatch"
                    )
                batch.bind_to(parent)
                result.append(batch)
        rebuilt_digest = _sha256(_canonical([
            {
                "observed_at_ms": batch.observed_at_ms,
                "rank_snapshot_digest": batch.rank_snapshot_digest,
                "batch_sha256": batch.batch_sha256,
            }
            for batch in result
        ]))
        if (
            rebuilt_digest != receipt.get("feature_input_source_digest")
            or rebuilt_digest != manifest.get("feature_input_source_digest")
            or result[0].observed_at_ms
            != manifest.get("first_complete_rank_input_observed_ms")
            or result[-1].observed_at_ms
            != manifest.get("last_complete_rank_input_observed_ms")
        ):
            raise OriginalRankFeatureArtifactError(
                "full source rank feature ID batch population digest mismatch"
            )
    except (
        OSError, ValueError, TypeError, zipfile.BadZipFile,
        OriginalRankInputBatchError,
    ) as exc:
        raise OriginalRankFeatureArtifactError(
            "full ranking input artifact is unreadable, altered or inconsistent"
        ) from exc
    return VerifiedGithubOriginalRankInputs(
        batches=tuple(result),
        historical_rank_snapshots_without_inputs=historical,
        source_digest=rebuilt_digest,
        archive_sha256=_sha256(artifact_zip),
        original_rank_state_digest=original_rank.rank_state_digest,
        worker_run_id=expected.run_id,
        worker_head_sha=expected.head_sha,
        worker_attempt=expected.run_attempt,
    )
