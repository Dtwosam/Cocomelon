"""Conservative source-chain preflight for the frozen v3 PAPER experiment.

This is *not* an independent GitHub API, venue, L2 or account signature
checker. Call only with separately pinned per-worker ZIP+manifest receipts.
Even internally consistent declarations cannot certify a 72h economic edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from cocomelon.domain.replay import ReplayManifest

MAX_HANDOFF_SOURCE_SILENCE_MS: Final = 5 * 60 * 1000


class OriginalV3SourceChainError(ValueError):
    """Source workers cannot be joined without an original provenance gap."""


@dataclass(frozen=True)
class OriginalV3WorkerSourceWitness:
    github_source: dict[str, object]
    manifest: ReplayManifest


def _positive_int(raw: object, name: str) -> int:
    if type(raw) is not int or raw < 1:
        raise OriginalV3SourceChainError(f"{name} missing or invalid")
    return raw


def _sha(raw: object, n: int, name: str) -> str:
    if (
        not isinstance(raw, str)
        or len(raw) != n
        or any(ch not in "0123456789abcdef" for ch in raw)
    ):
        raise OriginalV3SourceChainError(f"{name} unavailable or invalid")
    return raw


def _same_contract(manifest: ReplayManifest) -> tuple[str, ...]:
    return (
        manifest.config_digest,
        manifest.feature_version,
        manifest.strategy_version,
        manifest.risk_version,
        manifest.execution_config_version or "",
        manifest.fee_schedule_id or "",
        manifest.replay_engine_version,
    )


def audit_original_v3_worker_source_chain(
    witnesses: tuple[OriginalV3WorkerSourceWitness, ...],
) -> dict[str, object]:
    """Refuse broken contiguous *claims*, never certify venue or economics.

    Each source identity must have been checked against a separately fetched
    outer GitHub ZIP and worker metadata first. The caller can still forge
    supplied metadata; no signatures or venue receipts are inferred here.
    """
    if not witnesses:
        raise OriginalV3SourceChainError("no original worker source witnesses")

    previous_run: int | None = None
    previous_attempt: int | None = None
    previous_end: int | None = None
    expected_contract: tuple[str, ...] | None = None
    ids: set[int] = set()
    artifact_ids: set[int] = set()
    artifact_digests: set[str] = set()
    manifest_ids: set[str] = set()
    max_observed_handoff_silence = 0
    first_start: int | None = None
    total_original_manifest_rows = 0
    predecessor_at_chain_start: str | None = None

    for witness in witnesses:
        origin = witness.github_source
        manifest = witness.manifest
        run_id = _positive_int(origin.get("run_id"), "source GitHub run")
        attempt = _positive_int(origin.get("run_attempt"), "source attempt")
        artifact_id = _positive_int(
            origin.get("original_artifact_id"), "original artifact"
        )
        original_sha = _sha(
            origin.get("original_zip_sha256"), 64, "GitHub original ZIP SHA"
        )
        manifest_id = _sha(origin.get("manifest_id"), 24, "original manifest")
        head = _sha(origin.get("run_head_sha"), 40, "source worker head")
        if (
            manifest.manifest_id != manifest_id
            or manifest.code_revision != head
            or manifest.gap_refs
        ):
            raise OriginalV3SourceChainError(
                "original source manifest identity or zero-gap rule failed"
            )
        if (
            origin.get("original_zip_bytes_match_supplied_github_digest") is not True
            or origin.get("supplied_github_run_job_artifact_identity_crosschecked")
            is not True
            or origin.get("source_records_not_changed_by_audit") is not True
            or origin.get("original_worker_link_receipt_matches_run") is not True
            or origin.get("signed_cross_worker_handoff_proven") is not False
            or origin.get("net_after_cost_profitability_proven") is not False
            or origin.get("promotion_authority") is not False
            or origin.get("execution_authority") is not False
        ):
            raise OriginalV3SourceChainError(
                "source ZIP/worker receipt absent or claims unsupported authority"
            )
        if (
            run_id in ids or artifact_id in artifact_ids
            or original_sha in artifact_digests or manifest_id in manifest_ids
        ):
            raise OriginalV3SourceChainError(
                "original worker/artifact/manifest replayed or duplicated"
            )
        ids.add(run_id)
        artifact_ids.add(artifact_id)
        artifact_digests.add(original_sha)
        manifest_ids.add(manifest_id)

        predecessor = origin.get("declared_predecessor_run_id")
        pred_attempt = origin.get("declared_predecessor_run_attempt")
        if (predecessor is None) != (pred_attempt is None):
            raise OriginalV3SourceChainError(
                "original source predecessor half missing"
            )
        if predecessor is not None and (
            type(predecessor) is not str or not predecessor.isdecimal()
            or int(predecessor) <= 0 or int(predecessor) == run_id
            or type(pred_attempt) is not str
            or not pred_attempt.isdecimal() or int(pred_attempt) <= 0
        ):
            raise OriginalV3SourceChainError(
                "original source predecessor identity invalid"
            )
        if expected_contract is None:
            expected_contract = _same_contract(manifest)
            predecessor_at_chain_start = predecessor
            first_start = manifest.start_ms
        elif _same_contract(manifest) != expected_contract:
            raise OriginalV3SourceChainError(
                "source workers changed original frozen PAPER execution contract"
            )
        if previous_run is not None:
            if (
                predecessor != str(previous_run)
                or pred_attempt != str(previous_attempt)
            ):
                raise OriginalV3SourceChainError(
                    "source declared predecessor does not match prior worker"
                )
            assert previous_end is not None
            silence = manifest.start_ms - previous_end
            if silence < 0:
                raise OriginalV3SourceChainError(
                    "original source worker timestamps overlap"
                )
            if silence > MAX_HANDOFF_SOURCE_SILENCE_MS:
                raise OriginalV3SourceChainError(
                    "source handoff exceeds five-minute observation budget"
                )
            max_observed_handoff_silence = max(
                max_observed_handoff_silence, silence
            )

        total_original_manifest_rows += sum(
            segment.row_count for segment in manifest.segments
        )
        previous_run = run_id
        previous_attempt = attempt
        previous_end = manifest.end_ms

    assert first_start is not None and previous_end is not None
    return {
        "schema": "v3-original-multiworker-declared-source-chain-negative-preflight-v1",
        "source_worker_count": len(witnesses),
        "unique_original_artifact_count": len(artifact_ids),
        "original_manifest_record_rows": total_original_manifest_rows,
        "original_chain_first_manifest_timestamp_ms": first_start,
        "original_chain_last_manifest_timestamp_ms": previous_end,
        "original_manifest_nominal_span_ms": previous_end - first_start,
        "maximum_declared_handoff_source_silence_ms": max_observed_handoff_silence,
        "original_chain_first_unverified_predecessor_run_id": (
            predecessor_at_chain_start
        ),
        "declared_worker_chain_local_order_consistent": True,
        "independent_github_source_metadata_fetched_by_this_check": False,
        "independent_predecessor_restore_certified": False,
        "original_venue_event_completeness_certified": False,
        "unrecorded_source_gaps_excluded": False,
        "market_by_market_72h_l2_observation_certified": False,
        "signed_full_account_continuity_certified": False,
        "after_cost_absolute_positive_account_edge_verified": False,
        "profitability_certified": False,
        "research_only": True,
        "paper_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
