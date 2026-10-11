"""Verify immutable SHORT-rank source continuity across actual original-paper workers.

No successor is allowed to erase, rewrite, reorder, or backdate a predecessor's
first-seen rank cohort. Independently verified GitHub ZIPs and workflow-dispatch
inputs are both necessary. This remains offline research, not economic approval.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, cast

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayManifest
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import DecisionEpochEngine
from cocomelon.research.prospective_short_breakout_rank import (
    ProspectiveShortBreakoutRankState,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    ExpectedGithubRankArtifact,
    VerifiedGithubShortRankEvidence,
    run_github_original_rank_bound_paired_replay,
    verify_github_original_short_rank_artifact,
)

WORKFLOW_PATH: Final = ".github/workflows/continuous-paper.yml"


class ShortRankHandoffError(RuntimeError):
    """A failed source transition prevents pairing, never permits backfill."""


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ShortRankHandoffError(
            "original workflow handoff API response is not an object"
        )
    return cast(dict[str, Any], value)


def _source_run_identity(
    payload: dict[str, Any],
    evidence: VerifiedGithubShortRankEvidence,
    repository: str,
) -> None:
    if (
        payload.get("id") != evidence.worker_run_id
        or payload.get("run_attempt") != evidence.worker_run_attempt
        or payload.get("head_sha") != evidence.worker_head_sha
        or payload.get("head_branch") != "main"
        or payload.get("path") != WORKFLOW_PATH
        or _object(payload.get("repository")).get("full_name") != repository
        or _object(payload.get("head_repository")).get("full_name") != repository
    ):
        raise ShortRankHandoffError(
            "original GitHub worker run/head/attempt/repository mismatch"
        )


def verify_exact_original_rank_handoff(
    *,
    predecessor: VerifiedGithubShortRankEvidence,
    successor: VerifiedGithubShortRankEvidence,
    predecessor_run_json: object,
    successor_run_json: object,
    expected_repository: str,
) -> dict[str, object]:
    """Require a genuine workflow-dispatch link and every old rank row unchanged.

    The passed run JSON must be fetched through authenticated GitHub API. The
    pure function cannot independently prove the caller's API provenance.
    """
    if (
        not expected_repository
        or expected_repository.count("/") != 1
        or expected_repository.startswith("/")
        or expected_repository.endswith("/")
    ):
        raise ShortRankHandoffError("invalid original repository constraint")
    previous = _object(predecessor_run_json)
    newer = _object(successor_run_json)
    _source_run_identity(previous, predecessor, expected_repository)
    _source_run_identity(newer, successor, expected_repository)
    if previous.get("status") != "completed":
        raise ShortRankHandoffError(
            "predecessor original worker is not complete and sealed"
        )
    if (
        newer.get("event") != "workflow_dispatch"
        or successor.worker_run_id <= predecessor.worker_run_id
        or newer.get("created_at") is None
        or previous.get("created_at") is None
        or not isinstance(newer.get("created_at"), str)
        or not isinstance(previous.get("created_at"), str)
        or newer["created_at"] < previous["created_at"]
    ):
        raise ShortRankHandoffError(
            "successor is not a later exact workflow dispatch"
        )
    # GitHub's REST workflow-run endpoint exposes display_title but does NOT
    # expose workflow_dispatch.inputs. A completed original-worker source
    # archive must therefore carry its actual dispatch predecessor run/attempt
    # (sealed after state restore), and the GitHub-computed run title must
    # separately confirm the predecessor run ID.
    if (
        successor.restored_from_run_id != predecessor.worker_run_id
        or successor.restored_from_run_attempt
        != predecessor.worker_run_attempt
        or newer.get("display_title") != (
            f"Continuous Paper · {predecessor.worker_run_id}"
        )
    ):
        raise ShortRankHandoffError(
            "successor GitHub title and sealed restore identity mismatch"
        )
    inputs = newer.get("inputs")
    if inputs is not None:
        actual_inputs = _object(inputs)
        if (
            actual_inputs.get("source_run_id")
            != str(predecessor.worker_run_id)
            or actual_inputs.get("source_run_attempt")
            != str(predecessor.worker_run_attempt)
        ):
            raise ShortRankHandoffError(
                "successor workflow inputs conflict with rank seal identity"
            )
    if not predecessor.snapshots or not successor.snapshots:
        raise ShortRankHandoffError("rank archive population missing")
    before = predecessor.snapshots
    after = successor.snapshots
    if len(after) < len(before):
        raise ShortRankHandoffError(
            "original rank history truncated across worker handoff"
        )
    for old, new in zip(before, after, strict=False):
        if old.to_dict() != new.to_dict():
            raise ShortRankHandoffError(
                "original rank snapshot rewritten, omitted, or reordered"
            )
    prefix_digest = hashlib.sha256(
        json.dumps(
            [row.snapshot_digest for row in after[:len(before)]],
            sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    if prefix_digest != predecessor.rank_state_digest:
        raise ShortRankHandoffError(
            "unchanged successor prefix does not match sealed predecessor state"
        )
    if len(after) == len(before):
        raise ShortRankHandoffError(
            "no new rank observation after predecessor source handoff"
        )
    newer_rows = after[len(before):]
    if (
        newer_rows[0].observed_at_ms <= before[-1].observed_at_ms
        or newer_rows[0].captured_at_ms < before[-1].captured_at_ms
    ):
        raise ShortRankHandoffError(
            "new rank observations backdated across original worker handoff"
        )
    return {
        "schema_version": 1,
        "original_predecessor_run_id": predecessor.worker_run_id,
        "original_predecessor_attempt": predecessor.worker_run_attempt,
        "original_predecessor_head": predecessor.worker_head_sha,
        "original_successor_run_id": successor.worker_run_id,
        "original_successor_attempt": successor.worker_run_attempt,
        "original_successor_head": successor.worker_head_sha,
        "predecessor_sealed_rank_state_digest": predecessor.rank_state_digest,
        "successor_sealed_rank_state_digest": successor.rank_state_digest,
        "exact_predecessor_rank_prefix_digest": prefix_digest,
        "original_predecessor_snapshot_count": len(before),
        "original_successor_snapshot_count": len(after),
        "new_complete_rank_snapshots": len(newer_rows),
        "original_rank_history_exact_prefix_reconciled": True,
        "successor_github_title_and_sealed_restore_identity_matched": True,
        "successor_workflow_dispatch_inputs_independently_exposed": (
            inputs is not None
        ),
        "github_run_metadata_authenticated_by_caller": False,
        "original_market_stream_and_gaps_authenticated": False,
        "forward_account_maturity_certified": False,
        "full_account_trial": False,
        "ready_for_review": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run_handoff_verified_original_rank_paired_replay(
    *,
    market_source_root: str | Path,
    market_manifest: ReplayManifest,
    expected_market_manifest_id: str,
    predecessor_artifact_zip: bytes,
    predecessor_binding: ExpectedGithubRankArtifact,
    successor_artifact_zip: bytes,
    successor_binding: ExpectedGithubRankArtifact,
    predecessor_run_json: object,
    successor_run_json: object,
    expected_repository: str,
    freeze: ProspectiveShortBreakoutRankState,
    config: BaselineReplayConfig,
    selected_markets: Sequence[MarketId],
    account_root: str | Path,
    decision_engine_factory: (
        Callable[[], DecisionEpochEngine] | None
    ) = None,
) -> dict[str, object]:
    """Verify both original-worker sources and handoff BEFORE any paired account.

    Still fails to certify market source and maturity, even on success.
    """
    prev = verify_github_original_short_rank_artifact(
        predecessor_artifact_zip, expected=predecessor_binding
    )
    next_source = verify_github_original_short_rank_artifact(
        successor_artifact_zip, expected=successor_binding
    )
    continuity = verify_exact_original_rank_handoff(
        predecessor=prev,
        successor=next_source,
        predecessor_run_json=predecessor_run_json,
        successor_run_json=successor_run_json,
        expected_repository=expected_repository,
    )
    result = run_github_original_rank_bound_paired_replay(
        market_source_root=market_source_root,
        market_manifest=market_manifest,
        expected_market_manifest_id=expected_market_manifest_id,
        github_artifact_zip=successor_artifact_zip,
        github_binding=successor_binding,
        freeze=freeze,
        config=config,
        selected_markets=selected_markets,
        account_root=account_root,
        decision_engine_factory=decision_engine_factory,
    )
    result["original_rank_worker_handoff_receipt"] = continuity
    result["source_manifest_independently_authenticated"] = False
    result["rank_witness_source_independently_authenticated"] = False
    result["full_account_trial"] = False
    result["ready_for_review"] = False
    result["execution_authority"] = False
    result["promotion_authority"] = False
    return result
