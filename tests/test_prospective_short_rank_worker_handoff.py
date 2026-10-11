from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.prospective_short_breakout_rank import (
    ProspectiveShortBreakoutRankState,
)
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    ExpectedGithubRankArtifact,
    GithubShortRankArtifactError,
    VerifiedGithubShortRankEvidence,
)
from cocomelon.research.prospective_short_rank_worker_handoff import (
    ShortRankHandoffError,
    run_handoff_verified_original_rank_paired_replay,
    verify_exact_original_rank_handoff,
)

REPO = "Dtwosam/Cocomelon"
PRIOR_ID = 38162541394
NEW_ID = 38173471234
PRIOR_HEAD = "a" * 40
NEW_HEAD = "b" * 40
OBS = 1_790_000_000_000


def _snapshot(at: int, market: str, ordinal: int = 1) -> FirstSeenRankSnapshot:
    return FirstSeenRankSnapshot(
        observed_at_ms=at,
        captured_at_ms=at + 50,
        features=((market, f"feature-{market}-{at}", at - 100),),
        ranks=((market, ordinal, "0.7", ("immutable-test",)),),
    )


def _state_digest(rows: tuple[FirstSeenRankSnapshot, ...]) -> str:
    return hashlib.sha256(
        json.dumps(
            [r.snapshot_digest for r in rows],
            sort_keys=True, separators=(",", ":"),
        ).encode(),
    ).hexdigest()


def _verified(
    *,
    rows: tuple[FirstSeenRankSnapshot, ...],
    run_id: int,
    head: str,
    attempt: int = 1,
) -> VerifiedGithubShortRankEvidence:
    return VerifiedGithubShortRankEvidence(
        snapshots=rows,
        rank_state_digest=_state_digest(rows),
        archive_sha256="f" * 64,
        worker_run_id=run_id,
        worker_head_sha=head,
        worker_run_attempt=attempt,
    )


def _run(
    run_id: int, head: str, *,
    attempt: int = 1,
    source_id: str | None = None,
    source_attempt: str | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "run_attempt": attempt,
        "head_sha": head,
        "head_branch": "main",
        "path": ".github/workflows/continuous-paper.yml",
        "status": status,
        "event": "workflow_dispatch",
        "created_at": (
            "2026-10-11T18:30:00Z"
            if run_id == PRIOR_ID else "2026-10-11T18:45:00Z"
        ),
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
        "inputs": {
            "source_run_id": source_id or str(PRIOR_ID),
            "source_run_attempt": source_attempt or "1",
        },
    }


def _valid() -> tuple[
    VerifiedGithubShortRankEvidence, VerifiedGithubShortRankEvidence,
    dict[str, Any], dict[str, Any],
]:
    history = (_snapshot(OBS, "BTC"), _snapshot(OBS + 5_000, "ETH"))
    prior = _verified(rows=history, run_id=PRIOR_ID, head=PRIOR_HEAD)
    current = _verified(
        rows=history + (_snapshot(OBS + 10_000, "SOL"),),
        run_id=NEW_ID,
        head=NEW_HEAD,
    )
    return (
        prior, current,
        _run(PRIOR_ID, PRIOR_HEAD),
        _run(NEW_ID, NEW_HEAD),
    )


def _verify(
    prev: VerifiedGithubShortRankEvidence,
    curr: VerifiedGithubShortRankEvidence,
    previous_run: dict[str, Any],
    current_run: dict[str, Any],
) -> dict[str, object]:
    return verify_exact_original_rank_handoff(
        predecessor=prev,
        successor=curr,
        predecessor_run_json=previous_run,
        successor_run_json=current_run,
        expected_repository=REPO,
    )


def test_complete_original_rank_history_is_exact_prefix_after_real_dispatch() -> None:
    before, after, previous_run, next_run = _valid()
    result = _verify(before, after, previous_run, next_run)
    assert result["original_rank_history_exact_prefix_reconciled"] is True
    assert result["successor_workflow_dispatch_inputs_matched"] is True
    assert result["original_predecessor_snapshot_count"] == 2
    assert result["original_successor_snapshot_count"] == 3
    assert result["new_complete_rank_snapshots"] == 1
    assert result["exact_predecessor_rank_prefix_digest"] == before.rank_state_digest
    assert result["predecessor_sealed_rank_state_digest"] == before.rank_state_digest
    assert result["github_run_metadata_authenticated_by_caller"] is False
    assert result["original_market_stream_and_gaps_authenticated"] is False
    assert result["full_account_trial"] is False
    assert result["ready_for_review"] is False
    assert result["promotion_authority"] is False
    assert result["execution_authority"] is False


def test_missing_or_rewritten_predecessor_rank_snapshot_is_fatal() -> None:
    previous, successor, p_run, s_run = _valid()
    with pytest.raises(ShortRankHandoffError, match="truncated"):
        _verify(
            previous,
            replace(successor, snapshots=successor.snapshots[:1]),
            p_run, s_run,
        )
    edited = replace(
        previous.snapshots[0],
        ranks=(("BTC", 1, "0.8", ("immutable-test",)),),
    )
    with pytest.raises(ShortRankHandoffError, match="rewritten"):
        _verify(
            previous,
            replace(
                successor,
                snapshots=(edited,) + successor.snapshots[1:],
            ),
            p_run, s_run,
        )
    with pytest.raises(ShortRankHandoffError, match="rewritten"):
        _verify(
            previous,
            replace(
                successor,
                snapshots=(
                    successor.snapshots[1], successor.snapshots[0],
                    successor.snapshots[2],
                ),
            ),
            p_run, s_run,
        )
    with pytest.raises(ShortRankHandoffError, match="rewritten"):
        _verify(
            previous,
            replace(
                successor,
                snapshots=(
                    successor.snapshots[0], successor.snapshots[2],
                    successor.snapshots[2],
                ),
            ),
            p_run, s_run,
        )


def test_same_archive_without_new_forward_rank_is_not_a_mature_handoff() -> None:
    previous, successor, p_run, s_run = _valid()
    with pytest.raises(ShortRankHandoffError, match="no new"):
        _verify(
            previous,
            replace(successor, snapshots=previous.snapshots),
            p_run, s_run,
        )


def test_successor_cannot_backdate_first_new_capture() -> None:
    previous, successor, p_run, s_run = _valid()
    suspicious = _snapshot(OBS + 1_000, "SOL")
    with pytest.raises(ShortRankHandoffError, match="backdated"):
        _verify(
            previous,
            replace(
                successor,
                snapshots=previous.snapshots + (suspicious,),
            ),
            p_run, s_run,
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("source_run_id", "38162541395", "inputs"),
        ("source_run_attempt", "2", "inputs"),
    ],
)
def test_successor_dispatch_must_name_exact_original_predecessor(
    field: str, value: str, error: str,
) -> None:
    previous, successor, p_run, s_run = _valid()
    s_run["inputs"][field] = value
    with pytest.raises(ShortRankHandoffError, match=error):
        _verify(previous, successor, p_run, s_run)


def test_wrong_run_head_attempt_repository_and_unfinished_source_fail() -> None:
    previous, successor, p_run, s_run = _valid()
    for field, wrong in (
        ("run_attempt", 2),
        ("head_sha", "c" * 40),
        ("head_branch", "evil-branch"),
        ("id", PRIOR_ID),
    ):
        altered = dict(s_run, **{field: wrong})
        with pytest.raises(ShortRankHandoffError):
            _verify(previous, successor, p_run, altered)
    with pytest.raises(ShortRankHandoffError, match="not complete"):
        _verify(previous, successor, dict(p_run, status="in_progress"), s_run)
    with pytest.raises(ShortRankHandoffError, match="run/head"):
        _verify(
            previous, successor,
            dict(p_run, repository={"full_name": "attacker/repo"}),
            s_run,
        )
    with pytest.raises(ShortRankHandoffError, match="dispatch"):
        _verify(previous, successor, p_run, dict(s_run, event="push"))


def test_bad_unpinned_artifact_fails_before_creating_either_account(
    tmp_path: Path,
) -> None:
    prev, _, prior_run, next_run = _valid()
    head = ExpectedGithubRankArtifact(
        run_id=PRIOR_ID, run_attempt=1, head_sha=PRIOR_HEAD,
        artifact_run_id=PRIOR_ID, artifact_head_sha=PRIOR_HEAD,
        artifact_name=f"continuous-paper-first-seen-short-rank-{PRIOR_ID}-1",
        artifact_digest="sha256:" + "a" * 64,
        artifact_size_bytes=1,
    )
    second = replace(
        head,
        run_id=NEW_ID,
        artifact_run_id=NEW_ID,
        head_sha=NEW_HEAD,
        artifact_head_sha=NEW_HEAD,
        artifact_name=f"continuous-paper-first-seen-short-rank-{NEW_ID}-1",
    )
    accounts = tmp_path / "accounts"
    with pytest.raises(GithubShortRankArtifactError, match="bytes"):
        run_handoff_verified_original_rank_paired_replay(
            market_source_root=tmp_path / "source",
            market_manifest=ReplayManifest(
                evidence_class=EvidenceClass.MICROSTRUCTURE,
                start_ms=OBS, end_ms=OBS + 11_000,
                segments=(), gap_refs=(),
                code_revision="fixture", config_digest="a" * 64,
                feature_version="fixture",
                strategy_version="fixture",
                risk_version="fixture",
                execution_config_version="fixture",
                fee_schedule_id="fixture",
                replay_engine_version="fixture",
                dataset_manifest_id=None,
            ),
            expected_market_manifest_id="0" * 24,
            predecessor_artifact_zip=b"bad",
            predecessor_binding=head,
            successor_artifact_zip=b"bad",
            successor_binding=second,
            predecessor_run_json=prior_run,
            successor_run_json=next_run,
            expected_repository=REPO,
            freeze=ProspectiveShortBreakoutRankState(frozen_at_ms=1_000),
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(MarketId("", "TEST"),),
            account_root=accounts,
        )
    assert prev.worker_run_id == PRIOR_ID
    assert not accounts.exists()
