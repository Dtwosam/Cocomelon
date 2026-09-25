from __future__ import annotations

import json
from pathlib import Path

from cocomelon.learning_clean_campaign_sequence_cli import main
from tests.test_learning_clean_campaign_sequence import (
    REPO,
    _bootstrap,
    _history,
    _run,
)


def test_clean_campaign_sequence_cli_reports_next_missing_campaign(
    tmp_path: Path,
    capsys,
) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _history(
        history,
        [
            _run(run_id=20, created_at="1970-01-01T00:00:02Z"),
            _run(run_id=30, created_at="1970-01-01T00:00:03Z"),
        ],
    )

    code = main(
        [
            "--state-root",
            str(state),
            "--campaign-history",
            str(history),
            "--repository",
            REPO,
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "missing_campaign"
    assert payload["next_required_run_id"] == 20
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False


def test_clean_campaign_sequence_cli_reports_gap_for_newer_current_campaign(
    tmp_path: Path,
    capsys,
) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _history(
        history,
        [
            _run(run_id=20, created_at="1970-01-01T00:00:02Z"),
            _run(run_id=30, created_at="1970-01-01T00:00:03Z"),
        ],
    )

    code = main(
        [
            "--state-root",
            str(state),
            "--campaign-history",
            str(history),
            "--repository",
            REPO,
            "--current-run-id",
            "30",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "gap"
    assert payload["next_required_run_id"] == 20
