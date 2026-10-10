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
    if event == _event(title="Continuous Paper · 200"):
        with pytest.raises(publisher.V5WindowPublishError, match="predecessor"):
            _publish(event)
    else:
        assert _publish(event)[0] is None


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
    assert "schedule:" not in yml
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
