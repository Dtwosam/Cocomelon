from __future__ import annotations

import json
from pathlib import Path

from cocomelon import learning_dashboard_cli


def test_learning_dashboard_cli_renders_json(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        learning_dashboard_cli,
        "build_learning_operations_status",
        lambda *_args, **_kwargs: {
            "state": "waiting_for_authenticated_evidence",
            "research_only": True,
            "promotion_eligible": False,
            "execution_ready": False,
        },
    )

    code = learning_dashboard_cli.main(
        [
            "--state-root",
            str(tmp_path / "state"),
            "--format",
            "json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "waiting_for_authenticated_evidence"
    assert payload["execution_ready"] is False


def test_learning_dashboard_cli_renders_markdown(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        learning_dashboard_cli,
        "build_learning_operations_status",
        lambda *_args, **_kwargs: {
            "state": "waiting_for_capacity",
            "research_only": True,
            "promotion_eligible": False,
            "execution_ready": False,
        },
    )
    monkeypatch.setattr(
        learning_dashboard_cli,
        "render_learning_operations_markdown",
        lambda _payload: "## Continuous Learning Operations\n\nNO EXECUTION\n",
    )

    code = learning_dashboard_cli.main(
        [
            "--state-root",
            str(tmp_path / "state"),
            "--cycle-root",
            str(tmp_path / "cycle"),
            "--format",
            "markdown",
        ]
    )

    assert code == 0
    assert "Continuous Learning Operations" in capsys.readouterr().out
