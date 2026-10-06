from __future__ import annotations

import json
from pathlib import Path

from cocomelon import no_trade_context_prospective_cli

SOURCE = Path(
    "research/no_trade_context_candidates/"
    "mon-normal-short-1h-v1-source.json"
)
FREEZE = Path(
    "research/no_trade_context_candidates/"
    "mon-normal-short-1h-v1.json"
)


def test_prospective_cli_emits_authority_negative_report(
    tmp_path: Path,
    capsys,
) -> None:
    forward = tmp_path / "forward.json"
    forward.write_text(
        json.dumps(
            {
                "as_of_ms": 1791291300000,
                "decision_state_digest": "e" * 64,
                "feature_state_digest": "f" * 64,
                "diagnostic_only": True,
                "hypothetical_pnl": False,
                "execution_authority": False,
                "schema_version": 2,
                "outcomes": [],
            }
        ),
        encoding="utf-8",
    )

    assert (
        no_trade_context_prospective_cli.main(
            [
                "--input",
                str(forward),
                "--freeze",
                str(FREEZE),
                "--selection-record",
                str(SOURCE),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "no-trade-context-prospective"
    assert payload["candidate_id"] == (
        "2f72dd8fcb0b8cef3a4eb991d472a0e9c50f550954d1b3d8a0ddd3d6fe1cfd23"
    )
    assert payload["matching_outcomes"] == 0
    assert payload["schema_version"] == 2
    assert payload["ready_for_review"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
