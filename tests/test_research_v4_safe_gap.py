from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/research_v4_active_acquisition.sh")
CAMPAIGN = Path(".github/workflows/research-campaign-scheduled.yml")
DISPATCHER = Path(".github/workflows/research-daily-gap-dispatcher.yml")


def _fake_gh(
    tmp_path: Path,
    *,
    workflow_status: str = "in_progress",
    acquire_status: str = "completed",
    acquire_conclusion: str | None = "success",
    include_acquire_job: bool = True,
    fail_jobs_query: bool = False,
) -> Path:
    run_payload = {
        "workflow_runs": [
            {
                "id": 12345,
                "run_attempt": 1,
                "head_branch": "main",
                "event": "schedule",
                "status": workflow_status,
                "created_at": "2026-09-03T12:00:00Z",
            }
        ]
    }
    jobs: list[dict[str, object]] = []
    if include_acquire_job:
        jobs.append(
            {
                "name": "acquire-evidence",
                "status": acquire_status,
                "conclusion": acquire_conclusion,
            }
        )
    jobs_payload = {"jobs": jobs}
    path = tmp_path / "fake-gh.py"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"RUN_PAYLOAD = {run_payload!r}\n"
        f"JOBS_PAYLOAD = {jobs_payload!r}\n"
        f"FAIL_JOBS = {fail_jobs_query!r}\n"
        "endpoint = next((arg for arg in sys.argv if arg.startswith('/repos/')), '')\n"
        "if '/attempts/' in endpoint and endpoint.endswith('/jobs?per_page=100'):\n"
        "    if FAIL_JOBS:\n"
        "        raise SystemExit(9)\n"
        "    print(json.dumps(JOBS_PAYLOAD))\n"
        "elif '/workflows/evidence-campaign-v4-scheduled.yml/runs?per_page=100' in endpoint:\n"
        "    print(json.dumps(RUN_PAYLOAD))\n"
        "else:\n"
        "    raise SystemExit(f'unexpected endpoint: {endpoint}')\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _run_guard(fake_gh: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GH_BIN"] = str(fake_gh)
    env["GITHUB_REPOSITORY"] = "Dtwosam/Cocomelon"
    return subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_verification_only_v4_workflow_is_not_an_active_acquisition(tmp_path: Path) -> None:
    result = _run_guard(_fake_gh(tmp_path, acquire_status="completed"))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_in_progress_v4_acquisition_is_reported_active(tmp_path: Path) -> None:
    result = _run_guard(
        _fake_gh(
            tmp_path,
            acquire_status="in_progress",
            acquire_conclusion=None,
        )
    )

    assert result.returncode == 0, result.stderr
    assert "12345" in result.stdout
    assert "in_progress" in result.stdout


def test_ambiguous_or_unavailable_job_metadata_fails_closed(tmp_path: Path) -> None:
    ambiguous = _run_guard(_fake_gh(tmp_path, include_acquire_job=False))
    unavailable = _run_guard(_fake_gh(tmp_path, fail_jobs_query=True))

    assert ambiguous.returncode == 0, ambiguous.stderr
    assert "12345" in ambiguous.stdout
    assert unavailable.returncode != 0


def test_campaign_and_dispatcher_use_acquisition_aware_guard() -> None:
    campaign = CAMPAIGN.read_text(encoding="utf-8")
    dispatcher = DISPATCHER.read_text(encoding="utf-8")

    assert 'cron: "*/15 * * * *"' in dispatcher
    assert "scripts/research_v4_active_acquisition.sh" in dispatcher
    assert campaign.count("scripts/research_v4_active_acquisition.sh") >= 3

    refresh = campaign.split("\n  refresh-authority:\n", 1)[1].split(
        "\n  evaluate-research:\n",
        1,
    )[0]
    assert "timeout-minutes: 120" in refresh
    assert "retrying non-economic V4 authority synchronization" in refresh
    assert "fresh V4 authority does not cover bound research interval" in refresh

    insufficient = refresh.split(
        'if [ "$THROUGH_MS" -lt "$BOUND_END_MS" ]; then',
        1,
    )[1].split("continue", 1)[0]
    assert "rm -rf research-campaign/state/refreshed-v4-authority" in insufficient
    assert "rm -f research-campaign/state/refreshed-v4-authority.zip" in insufficient
