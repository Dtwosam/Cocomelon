"""Exact signed-v5 window automation must not skip missing source evidence."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

import scripts.publish_signed_v5_market_windows as publisher

REPO = "Dtwosam/Cocomelon"


def _report(count: int, *, base: str, candidate: str) -> dict[str, object]:
    def lane(value: str, lane_id: str) -> dict[str, object]:
        return {
            "account_state_id": f"{lane_id}-{count}",
            "signed_total_account_pnl": value,
            "signed_equity": str(Decimal("10000") + Decimal(value)),
            "fill_fees": str(Decimal(count) / Decimal("100")),
            "funding": "0",
            "markets": {"PONS": value},
        }

    return {
        "schema_version": 1,
        "kind": "signed-v5-paired-market-accounting-reconciliation",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "causal_block_credit": False,
        "economic_scope": "cumulative_through_last_signed_checkpoint_not_forward_verdict",
        "source_candidate_id": "frozen-v5",
        "source_state_digest": f"{count:x}".zfill(64),
        "source_latest_review_row_digest": f"{count + 100:x}".zfill(64),
        "source_record_count": count,
        "baseline": lane(base, "baseline"),
        "candidate": lane(candidate, "candidate"),
        "candidate_minus_baseline_total_account_pnl": str(
            Decimal(candidate) - Decimal(base)
        ),
        "by_market": {
            "PONS": {
                "baseline_account_pnl": base,
                "candidate_account_pnl": candidate,
                "candidate_minus_baseline": str(
                    Decimal(candidate) - Decimal(base)
                ),
            },
        },
    }


def _zip(
    report: dict[str, object],
    name: str = "signed-v5-market-economics.json",
) -> bytes:
    import io
    import json
    import zipfile

    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(name, json.dumps(report))
    return target.getvalue()


def _event(
    *, title: str = "Continuous Paper · 100",
    branch: str = "main", status: str = "completed",
) -> dict[str, object]:
    return {
        "action": "completed",
        "workflow_run": {
            "id": 200,
            "run_attempt": 1,
            "head_branch": branch,
            "status": status,
            "conclusion": "failure",
            "display_title": title,
        },
    }


def _services(
    *,
    previous_name: str = "continuous-paper-v5-market-economics-100-2",
    new_name: str = "continuous-paper-v5-market-economics-200-1",
) -> tuple[dict[str, object], dict[str, bytes]]:
    jsons: dict[str, object] = {
        f"repos/{REPO}/actions/runs/100": {
            "id": 100,
            "status": "completed",
            "conclusion": "failure",
            "head_branch": "main",
            "run_attempt": 2,
        },
        f"repos/{REPO}/actions/runs/100/artifacts?per_page=100": {
            "total_count": 1,
            "artifacts": [{
                "id": 14,
                "name": previous_name,
                "expired": False,
            }],
        },
        f"repos/{REPO}/actions/runs/200/artifacts?per_page=100": {
            "total_count": 1,
            "artifacts": [{
                "id": 15,
                "name": new_name,
                "expired": False,
            }],
        },
    }
    archives = {
        f"repos/{REPO}/actions/artifacts/14/zip": _zip(
            _report(100, base="-15", candidate="-25")
        ),
        f"repos/{REPO}/actions/artifacts/15/zip": _zip(
            _report(200, base="-4", candidate="-23")
        ),
    }
    return jsons, archives


def _publish(
    event: object | None = None,
    *,
    jsons: dict[str, object] | None = None,
    archives: dict[str, bytes] | None = None,
) -> tuple[dict[str, object] | None, str]:
    originals, original_zips = _services()
    source = originals if jsons is None else jsons
    zipped = original_zips if archives is None else archives
    return publisher.publish(
        _event() if event is None else event,
        REPO, source.__getitem__, zipped.__getitem__,
    )


def test_failing_predecessor_with_signed_ledger_is_usable() -> None:
    report, reason = _publish()
    assert report is not None
    assert "validated" in reason
    assert report["candidate_minus_baseline_window_pnl"] == "-9"
    assert report["baseline"]["marked_account_pnl_change"] == "11"
    assert report["candidate"]["marked_account_pnl_change"] == "2"
    assert report["artifact_lineage"] == {
        "current_run_id": 200,
        "current_attempt": 1,
        "current_artifact_id": 15,
        "predecessor_run_id": 100,
        "predecessor_attempt": 2,
        "predecessor_artifact_id": 14,
        "verified_exact_predecessor_run": True,
        "verified_review_ledger_contiguity": False,
    }
    assert report["promotion_authority"] is False
    assert report["execution_authority"] is False


@pytest.mark.parametrize(
    "event",
    (
        _event(branch="experimental"),
        _event(status="in_progress"),
        _event(title="Continuous Paper · 200"),
        {"action": "requested", "workflow_run": _event()["workflow_run"]},
    ),
)
def test_no_unverified_completed_predecessor_may_publish(
    event: object,
) -> None:
    report, reason = _publish(event)
    assert report is None
    assert "not an exact completed" in reason


def test_future_run_cannot_be_named_an_already_completed_predecessor() -> None:
    with pytest.raises(publisher.V5WindowPublishError, match="predecessor"):
        _publish(_event(title="Continuous Paper · 201"))


def test_actual_github_push_guard_completion_is_clean_no_evidence() -> None:
    event = _event(title="Continuous Paper · 200")
    event["workflow_run"]["conclusion"] = "success"
    report, reason = _publish(event)
    assert report is None
    assert "not an exact completed" in reason


def test_current_or_predecessor_missing_compact_artifact_skips_truthfully() -> None:
    for name, expected in (
        ("current", "current worker"),
        ("predecessor", "exact predecessor"),
    ):
        jsons, archives = _services()
        run = 200 if name == "current" else 100
        endpoint = f"repos/{REPO}/actions/runs/{run}/artifacts?per_page=100"
        jsons[endpoint]["artifacts"] = []
        jsons[endpoint]["total_count"] = 0
        assert _publish(jsons=jsons, archives=archives)[0] is None
        assert expected in _publish(jsons=jsons, archives=archives)[1]


def test_never_skip_predecessor_to_use_an_older_favorable_report() -> None:
    jsons, archives = _services(previous_name="wrong-name")
    report, reason = _publish(jsons=jsons, archives=archives)
    assert report is None
    assert "predecessor" in reason


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("id", 99, "predecessor run"),
        ("head_branch", "feature", "predecessor run"),
        ("status", "in_progress", "predecessor run"),
        ("run_attempt", 0, "predecessor run attempt"),
    ),
)
def test_predecessor_run_metadata_must_match(
    field: str, value: object, error: str,
) -> None:
    jsons, archives = _services()
    jsons[f"repos/{REPO}/actions/runs/100"][field] = value
    with pytest.raises(publisher.V5WindowPublishError, match=error):
        _publish(jsons=jsons, archives=archives)


def test_reject_incomplete_duplicate_or_expired_artifacts() -> None:
    for action in ("incomplete", "duplicate", "expired"):
        jsons, archives = _services()
        item = jsons[f"repos/{REPO}/actions/runs/200/artifacts?per_page=100"]
        if action == "incomplete":
            item["total_count"] = 101
        elif action == "duplicate":
            item["artifacts"].append(dict(item["artifacts"][0]))
            item["total_count"] = 2
        else:
            item["artifacts"][0]["expired"] = True
        with pytest.raises(publisher.V5WindowPublishError):
            _publish(jsons=jsons, archives=archives)


def test_reject_tampered_zip_and_source_candidate() -> None:
    jsons, archives = _services()
    archives[f"repos/{REPO}/actions/artifacts/15/zip"] = _zip(
        _report(200, base="-4", candidate="-23"), "wrong.json"
    )
    with pytest.raises(publisher.V5WindowPublishError, match="one bounded"):
        _publish(jsons=jsons, archives=archives)
    jsons, archives = _services()
    altered = _report(200, base="-4", candidate="-23")
    altered["source_candidate_id"] = "refrozen"
    archives[f"repos/{REPO}/actions/artifacts/15/zip"] = _zip(altered)
    with pytest.raises(ValueError, match="frozen candidate changed"):
        _publish(jsons=jsons, archives=archives)


def test_no_runtime_modification_or_paper_trigger_in_read_only_workflow() -> None:
    yml = Path(
        ".github/workflows/signed-v5-incremental-market-economics.yml"
    ).read_text(encoding="utf-8")
    assert "Continuous Mainnet Paper Trader" in yml
    assert "workflow_run:" in yml
    assert "contents: read" in yml
    assert "actions: read" in yml
    assert "persist-credentials: false" in yml
    assert "scripts.publish_signed_v5_market_windows" in yml
    assert "workflow_dispatch:" not in yml
    assert 'cron: "11 * * * *"' in yml
    assert "github.event_name == 'schedule'" in yml
    assert "steps.compare.outputs.artifact_name" in yml
    assert "group: signed-v5-window-singleflight" in yml
    assert "cancel-in-progress: false" in yml
    assert "github.event.workflow_run.id || 'scheduled-catchup'" not in yml
    assert "actions: write" not in yml
    assert "issue" not in yml.lower()
    assert "live_orders" not in yml
    paper = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    assert (
        '"scripts/publish_signed_v5_market_windows.py"'
        not in paper.split("workflow_dispatch:", 1)[0]
    )


def _scheduled_sources(
    *,
    existing: bool = False,
    missing_prior: bool = False,
) -> tuple[dict[str, object], dict[str, bytes]]:
    jsons, archives = _services()
    jsons[f"repos/{REPO}/actions/workflows/"
          "continuous-paper.yml/runs?per_page=100"] = {
        "total_count": 3,
        "workflow_runs": [
            {
                "id": 300,
                "run_attempt": 1,
                "status": "in_progress",
                "head_branch": "main",
                "path": ".github/workflows/continuous-paper.yml",
                "display_title": "Continuous Paper · 200",
            },
            {
                "id": 201,
                "run_attempt": 1,
                "status": "completed",
                "head_branch": "main",
                "path": ".github/workflows/continuous-paper.yml",
                "display_title": "Continuous Paper · 201",
            },
            {
                "id": 200,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "failure",
                "head_branch": "main",
                "path": ".github/workflows/continuous-paper.yml",
                "display_title": "Continuous Paper · 100",
            },
        ],
    }
    jsons[f"repos/{REPO}/actions/artifacts?"
          "name=signed-v5-incremental-market-window-200-1&per_page=100"] = {
        "total_count": int(existing),
        "artifacts": [{
            "id": 77,
            "name": "signed-v5-incremental-market-window-200-1",
            "expired": False,
        }] if existing else [],
    }
    if missing_prior:
        jsons[f"repos/{REPO}/actions/runs/100/artifacts?per_page=100"] = {
            "total_count": 0,
            "artifacts": [],
        }
    return jsons, archives


def test_scheduled_independent_catchup_recovers_true_failed_worker() -> None:
    jsons, archives = _scheduled_sources()
    result, reason = publisher.scheduled_catchup(
        REPO, jsons.__getitem__, archives.__getitem__,
    )
    assert result is not None
    assert result["candidate_minus_baseline_window_pnl"] == "-9"
    assert "catch-up validated exact" in reason
    assert result["artifact_lineage"]["current_run_id"] == 200
    assert result["artifact_lineage"]["predecessor_run_id"] == 100
    assert result["scheduled_catchup"] == {
        "discovery_limit_recent_paper_runs": 100,
        "source_run_id": 200,
        "source_run_attempt": 1,
        "not_review_authority": True,
    }
    assert result["promotion_authority"] is False


def test_schedule_skips_only_existing_unique_retained_interval_artifact() -> None:
    jsons, archives = _scheduled_sources(existing=True)
    result, reason = publisher.scheduled_catchup(
        REPO, jsons.__getitem__, archives.__getitem__,
    )
    assert result is None
    assert "no unpublished authentic" in reason


def test_schedule_never_skips_missing_exact_predecessor_to_use_older_worker() -> None:
    jsons, archives = _scheduled_sources(missing_prior=True)
    result, reason = publisher.scheduled_catchup(
        REPO, jsons.__getitem__, archives.__getitem__,
    )
    assert result is None
    assert "no unpublished authentic" in reason


@pytest.mark.parametrize(
    ("corruption", "reason"),
    (
        ("wrong_path", "non-paper workflow"),
        ("duplicate_worker", "duplicate exact completed paper run"),
        ("incomplete_artifacts", "incomplete published interval artifact"),
        ("duplicate_artifact", "duplicate existing signed interval"),
        ("future_predecessor", "predecessor"),
        ("wrong_candidate", "frozen candidate changed"),
    ),
)
def test_scheduled_source_integrity_fails_closed(
    corruption: str, reason: str,
) -> None:
    jsons, archives = _scheduled_sources()
    key = f"repos/{REPO}/actions/workflows/continuous-paper.yml/runs?per_page=100"
    artifact_key = (
        f"repos/{REPO}/actions/artifacts?"
        "name=signed-v5-incremental-market-window-200-1&per_page=100"
    )
    if corruption == "wrong_path":
        jsons[key]["workflow_runs"][2]["path"] = "other.yml"
    elif corruption == "duplicate_worker":
        jsons[key]["workflow_runs"].append(jsons[key]["workflow_runs"][2].copy())
        jsons[key]["total_count"] = 4
    elif corruption == "incomplete_artifacts":
        jsons[artifact_key]["total_count"] = 101
    elif corruption == "duplicate_artifact":
        jsons[artifact_key]["total_count"] = 2
        jsons[artifact_key]["artifacts"] = [
            {"id": 14, "name": "signed-v5-incremental-market-window-200-1",
             "expired": False},
            {"id": 15, "name": "signed-v5-incremental-market-window-200-1",
             "expired": False},
        ]
    elif corruption == "future_predecessor":
        jsons[key]["workflow_runs"][2]["display_title"] = (
            "Continuous Paper · 301"
        )
    else:
        alter = _report(200, base="-4", candidate="-23")
        alter["source_candidate_id"] = "another-trial"
        archives[f"repos/{REPO}/actions/artifacts/15/zip"] = _zip(alter)
    with pytest.raises(ValueError, match=reason):
        publisher.scheduled_catchup(
            REPO, jsons.__getitem__, archives.__getitem__,
        )


def test_scheduled_main_writes_stable_exact_interval_artifact_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    jsons, archives = _scheduled_sources()
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"schedule": "11 * * * *"}), encoding="utf-8")
    output = tmp_path / "window.json"
    github_output = tmp_path / "github_output.txt"
    summary = tmp_path / "summary.txt"
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("V5_WINDOW_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(publisher, "_gh_json", jsons.__getitem__)
    monkeypatch.setattr(publisher, "_gh_zip", archives.__getitem__)
    assert publisher.main() == 0
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["artifact_lineage"]["current_run_id"] == 200
    assert saved["candidate_minus_baseline_window_pnl"] == "-9"
    assert github_output.read_text(encoding="utf-8") == (
        "artifact_name=signed-v5-incremental-market-window-200-1\\n"
    ).replace("\\n", "\n")
    assert "Research only" in summary.read_text(encoding="utf-8")
