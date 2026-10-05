from __future__ import annotations

import json
from pathlib import Path

from cocomelon import context_conditioned_paper_cli


def test_cli_emits_research_only_empty_report(tmp_path: Path, capsys) -> None:
    learning = tmp_path / "ledger"
    features = tmp_path / "features"

    assert (
        context_conditioned_paper_cli.main(
            [
                "--learning-root",
                str(learning),
                "--feature-store-dir",
                str(features),
                "--as-of-ms",
                "1000",
                "--min-group-rows",
                "2",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "context-conditioned-paper"
    assert payload["resolved_records"] == 0
    assert payload["diagnostic_only"] is True
    assert payload["side_suppression_authority"] is False
    assert payload["execution_authority"] is False
