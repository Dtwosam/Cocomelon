from __future__ import annotations

import json

from cocomelon.learning_shadow_campaign_sequence_cli import main
from tests.test_learning_shadow_campaign_sequence import REPO, _bootstrap, _history, _run


def test_shadow_sequence_cli_reports_required_post_review_campaign(
    tmp_path,
    capsys,
) -> None:
    state = tmp_path / "state"
    history = tmp_path / "history.json"
    _bootstrap(state, as_of_ms=1_500)
    _history(
        history,
        [
            _run(
                run_id=20,
                created_at="1970-01-01T00:00:01Z",
                updated_at="1970-01-01T00:00:02Z",
            )
        ],
    )

    status = main(
        [
            "--state-root",
            str(state),
            "--campaign-history",
            str(history),
            "--repository",
            REPO,
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "missing_campaign"
    assert payload["next_required_run_id"] == 20
    assert payload["next_required_completed_at_ms"] == 2_000
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert payload["live_promotion_authorized"] is False
