from __future__ import annotations

import json
from pathlib import Path

from cocomelon import no_trade_forward_opportunity_cli
from cocomelon import continuous_paper_decision_export_cli
from cocomelon.evaluation.store import EvaluationFactStore


def test_decision_export_cli_emits_empty_research_report(
    tmp_path: Path,
    capsys,
) -> None:
    facts_path = tmp_path / "facts.sqlite3"
    EvaluationFactStore(facts_path).close()

    assert (
        continuous_paper_decision_export_cli.main(
            [
                "--facts",
                str(facts_path),
                "--output-dir",
                str(tmp_path / "decisions"),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_facts"] == 0
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False


def test_no_trade_forward_cli_emits_empty_research_report(
    tmp_path: Path,
    capsys,
) -> None:
    assert (
        no_trade_forward_opportunity_cli.main(
            [
                "--decision-store-dir",
                str(tmp_path / "decisions"),
                "--feature-store-dir",
                str(tmp_path / "features"),
                "--as-of-ms",
                "1000",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["no_trade_decisions"] == 0
    assert payload["diagnostic_only"] is True
    assert payload["hypothetical_pnl"] is False
    assert payload["execution_authority"] is False
