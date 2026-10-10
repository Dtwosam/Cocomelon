from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path("scripts/resolve_terminal_parity_schedule.py")
SPEC = importlib.util.spec_from_file_location("scheduled_terminal_parity", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
scheduled = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scheduled)
WORKFLOW = Path(
    ".github/workflows/immutable-terminal-source-parity-audit.yml"
).read_text(encoding="utf-8")


def _run(
    run: int,
    *,
    created: str = "2026-10-10T18:45:00Z",
    status: str = "completed",
    branch: str = "main",
) -> dict[str, object]:
    return {
        "id": run,
        "run_attempt": 1,
        "created_at": created,
        "status": status,
        "conclusion": "failure",
        "path": ".github/workflows/continuous-paper.yml",
        "head_branch": branch,
        "head_repository": {"full_name": "Dtwosam/Cocomelon"},
        "head_sha": "a" * 40,
    }


def _api_payload(*, reported: bool = False) -> dict[str, object]:
    return {
        "artifacts": (
            [{"name": "immutable-terminal-source-parity-20-1", "expired": False}]
            if reported else []
        ),
    }


def test_completed_source_candidates_are_chronological_and_post_causal() -> None:
    payload = {
        "workflow_runs": [
            _run(22, created="2026-10-10T19:15:00Z"),
            _run(21, status="in_progress"),
            _run(10, created="2026-10-10T17:00:00Z"),
            _run(20),
            _run(18, branch="research"),
        ]
    }
    assert scheduled.eligible_completed_runs(
        payload, repository="Dtwosam/Cocomelon"
    ) == ((20, 1), (22, 1))


def test_selection_skips_already_audited_and_missing_source_in_order() -> None:
    runs = {
        "workflow_runs": [
            _run(30, created="2026-10-10T19:30:00Z"),
            _run(20, created="2026-10-10T18:45:00Z"),
            _run(25, created="2026-10-10T19:00:00Z"),
        ]
    }
    fetched: list[str] = []

    def fetch(url: str) -> dict[str, object]:
        fetched.append(url)
        if "/runs/20/artifacts?" in url:
            return {"artifacts": [
                {
                    "id": 200,
                    "name": "continuous-paper-full-stack-forward-markout-20-1",
                    "digest": "sha256:" + "a" * 64,
                    "expired": False,
                }
            ]}
        if "name=immutable-terminal-source-parity-20-1" in url:
            return _api_payload(reported=True)
        if "/runs/25/artifacts?" in url:
            return {"artifacts": []}
        if "/runs/30/artifacts?" in url:
            return {"artifacts": [
                {
                    "id": 300,
                    "name": "continuous-paper-full-stack-forward-markout-30-1",
                    "digest": "sha256:" + "b" * 64,
                    "expired": False,
                }
            ]}
        if "name=immutable-terminal-source-parity-30-1" in url:
            return _api_payload()
        raise AssertionError(url)

    assert scheduled.select_oldest_unreported(
        runs,
        repository="Dtwosam/Cocomelon",
        fetch_json=fetch,
    ) == (30, 1)
    assert fetched.index(
        "repos/Dtwosam/Cocomelon/actions/runs/20/artifacts?per_page=100"
    ) < fetched.index(
        "repos/Dtwosam/Cocomelon/actions/runs/30/artifacts?per_page=100"
    )


def test_selector_fails_closed_on_duplicate_source_artifact() -> None:
    original = {
        "id": 123,
        "name": "continuous-paper-full-stack-forward-markout-20-1",
        "expired": False,
        "digest": "sha256:" + "c" * 64,
    }

    def fetch(_url: str) -> dict[str, object]:
        return {"artifacts": [original, original]}

    with pytest.raises(scheduled.ScheduledParitySourceError, match="duplicate"):
        scheduled.select_oldest_unreported(
            {"workflow_runs": [_run(20)]},
            repository="Dtwosam/Cocomelon",
            fetch_json=fetch,
        )


def test_selector_refuses_duplicate_completed_run_identity() -> None:
    with pytest.raises(scheduled.ScheduledParitySourceError, match="repeated"):
        scheduled.eligible_completed_runs(
            {"workflow_runs": [_run(20), _run(20)]},
            repository="Dtwosam/Cocomelon",
        )


def test_scheduled_catchup_is_read_only_and_independent_of_event_chain() -> None:
    assert 'cron: "17 */4 * * *"' in WORKFLOW
    assert 'elif [ "$EVENT_NAME" = "schedule" ]; then' in WORKFLOW
    assert "scripts/resolve_terminal_parity_schedule.py" in WORKFLOW
    assert "No unaudited authenticated completed paper source" in WORKFLOW
    assert "immutable-terminal-source-parity-${{ steps.source.outputs.run }}" in WORKFLOW
    assert WORKFLOW.count("      - name: Upload redacted parity diagnostic") == 1
    assert "  actions: read" in WORKFLOW
    assert "  contents: read" in WORKFLOW
    assert "  issues: write" not in WORKFLOW
    assert "  pull-requests: write" not in WORKFLOW
