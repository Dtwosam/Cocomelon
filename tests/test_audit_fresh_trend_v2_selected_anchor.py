"""V2 signed selected-anchor continuity is not venue or profit certification."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    FROZEN_AT_MS_V2,
    FORWARD_NOT_BEFORE_MS_V2,
    TRIAL_ID_V2,
    both_side_trend_matched_shadow_v2_freeze,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_genesis import (
    _digest,
)
from scripts import audit_fresh_trend_v2_selected_anchor as audit

REPO = "Dtwosam/Cocomelon"
SOURCE_ARGS = {
    "repository": REPO,
    "anchor_run_id": 40001,
    "anchor_attempt": 1,
    "current_run_id": 40002,
    "current_attempt": 1,
    "anchor_run": {"head_sha": "a" * 40},
    "anchor_jobs": {},
    "anchor_artifacts": {},
    "current_run": {},
    "current_jobs": {},
    "current_artifacts": {},
}


def _state() -> dict[str, object]:
    return {
        "baseline": {
            "known_gap_intervals_by_stream": {},
            "known_global_gap_intervals_by_stream": {},
            "legacy_unscoped_gap_intervals": [],
        },
        "candidate": {
            "known_gap_intervals_by_stream": {},
            "known_global_gap_intervals_by_stream": {},
            "legacy_unscoped_gap_intervals": [],
        },
    }


def _genesis() -> dict[str, object]:
    freeze = both_side_trend_matched_shadow_v2_freeze()
    value: dict[str, object] = {
        "schema_version": 1,
        "trial_id": TRIAL_ID_V2,
        "frozen_candidate_id": freeze.candidate_id,
        "source_composition_digest": freeze.source_composition_digest,
        "frozen_at_ms": FROZEN_AT_MS_V2,
        "forward_not_before_ms": FORWARD_NOT_BEFORE_MS_V2,
        "genesis_startup_ms": FROZEN_AT_MS_V2 + 100,
        "selected_markets": ["BTC"],
        "replay_config_digest": "a" * 64,
        "initial_cash_each_lane": "10000",
        "initial_record_count": 0,
        "initial_signed_review_rows": 0,
        "source_github_run_id": SOURCE_ARGS["anchor_run_id"],
        "source_github_attempt": SOURCE_ARGS["anchor_attempt"],
        "source_github_head_sha": "a" * 40,
        "original_v1_account_reuse": False,
        "research_only": True,
        "paper_only": True,
        "shadow_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
    value["genesis_digest"] = _digest(value)
    return value


def _archive(
    path: Path,
    *,
    rows: list[dict[str, object]],
) -> Path:
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr(
            "both-side-trend-paired-shadow-v2/v2-genesis.json",
            json.dumps(_genesis()),
        )
        zipped.writestr(
            audit.V2_LEDGER_MEMBER,
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        )
        zipped.writestr(audit.V2_STATE_MEMBER, json.dumps(_state()))
    return path


def _row(
    digest: str, prior: str | None, *, end: int, count: int,
) -> dict[str, object]:
    return {
        "row_digest": digest,
        "previous_row_digest": prior,
        "end_ms": end,
        "record_count": count,
    }


def _audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    *,
    successor: list[dict[str, object]],
    anchor: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    monkeypatch.setattr(
        audit, "_strict_source",
        lambda **kw: {
            "v2_genesis_original_worker_authenticated": True,
            "status": "archive_checkpoint_lineage_verified",
            "source_v2_terminal_receipt_verified": True,
            "archived_execution_economics_reconciled": True,
        },
    )
    anchor_rows = anchor or [_row("anchor", None, end=100, count=10)]
    source_zip = _archive(tmp_path / "source.zip", rows=successor)
    anchor_zip = _archive(tmp_path / "anchor.zip", rows=anchor_rows)
    return audit.audit_v2_selected_anchor_lineage(
        **SOURCE_ARGS, anchor_archive=anchor_zip, current_archive=source_zip,
    )


def test_valid_selected_v2_anchor_prefix_and_genuine_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _audit(
        tmp_path, monkeypatch,
        successor=[
            _row("anchor", None, end=100, count=10),
            _row("fresh", "anchor", end=200, count=20),
        ],
    )
    assert receipt["status"] == "v2_selected_anchor_worker_append_verified"
    assert receipt["anchored_prefix_row_count"] == 1
    assert receipt["new_signed_checkpoint_count"] == 1
    assert receipt["signed_selected_anchor_prefix_preserved"] is True
    assert receipt["new_signed_checkpoint_append_verified"] is True
    assert receipt["source_gap_lifecycle_state_only"] is not None
    assert receipt["v2_campaign_genesis_proven"] is False
    assert receipt["first_archived_v2_worker_proven"] is True
    assert receipt["identical_write_once_genesis_across_workers"] is True
    assert receipt["independent_market_feed_authenticated"] is False
    assert receipt["72h_positive_after_cost_edge_verified"] is False
    assert receipt["execution_authority"] is False
    assert receipt["promotion_authority"] is False


def test_old_signed_checkpoint_repeated_without_append_is_not_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _audit(
        tmp_path, monkeypatch,
        successor=[_row("anchor", None, end=100, count=10)],
    )
    assert receipt["status"] == "v2_no_new_signed_checkpoint"
    assert receipt["new_signed_checkpoint_append_verified"] is False


@pytest.mark.parametrize(
    "successor",
    [
        [_row("forged", None, end=100, count=10)],
        [
            _row("anchor", None, end=100, count=10),
            _row("fresh", "wrong-prior", end=200, count=20),
        ],
        [
            _row("anchor", None, end=100, count=10),
            _row("fresh", "anchor", end=100, count=20),
        ],
        [
            _row("anchor", None, end=100, count=10),
            _row("fresh", "anchor", end=200, count=10),
        ],
    ],
)
def test_tampered_prefix_link_or_unchanged_source_progress_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    successor: list[dict[str, object]],
) -> None:
    receipt = _audit(tmp_path, monkeypatch, successor=successor)
    assert receipt["status"] == "unverified"
    assert receipt["new_signed_checkpoint_append_verified"] is False
    assert receipt["72h_positive_after_cost_edge_verified"] is False


def test_unpinned_anchor_is_not_silently_replaced_with_latest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "_strict_source", lambda **kw: {})
    current = _archive(
        tmp_path / "current.zip",
        rows=[_row("a", None, end=100, count=10)],
    )
    args = dict(SOURCE_ARGS)
    args.update(
        anchor_run=None, anchor_jobs=None, anchor_artifacts=None,
    )
    result = audit.audit_v2_selected_anchor_lineage(
        **args, anchor_archive=None, current_archive=current,
    )
    assert result["status"] == "unverified"
    assert result["v2_campaign_genesis_proven"] is False
    assert result["new_signed_checkpoint_append_verified"] is False


def test_selected_anchor_is_not_a_forward_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit, "_strict_source",
        lambda **kw: {"v2_genesis_original_worker_authenticated": True},
    )
    anchor = _archive(
        tmp_path / "anchor.zip",
        rows=[_row("a", None, end=100, count=10)],
    )
    args = dict(SOURCE_ARGS)
    args["current_run_id"] = args["anchor_run_id"]
    result = audit.audit_v2_selected_anchor_lineage(
        **args, anchor_archive=anchor, current_archive=anchor,
    )
    assert result["status"] == "v2_selected_anchor_only"
    assert result["new_signed_checkpoint_append_verified"] is False
    assert result["v2_campaign_genesis_proven"] is False


def test_excluded_source_metadata_and_unsafe_authority_never_promote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_source(**kwargs: object) -> dict[str, object]:
        raise audit.TrendPairHandoffAuditError(
            "independent v2 terminal account mismatch"
        )

    monkeypatch.setattr(audit, "_strict_source", invalid_source)
    source = _archive(
        tmp_path / "source.zip",
        rows=[_row("a", None, end=100, count=10)],
    )
    result = audit.audit_v2_selected_anchor_lineage(
        **SOURCE_ARGS, anchor_archive=source, current_archive=source,
    )
    assert result["status"] == "unverified"
    assert "account mismatch" in str(result["reasons"])
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
