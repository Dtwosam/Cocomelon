from __future__ import annotations

import json
from pathlib import Path

from cocomelon import cooldown_context_stability_cli


def test_cooldown_context_stability_cli_writes_authority_negative_report(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "cooldown.json"
    output = tmp_path / "stability.json"
    source.write_text(
        json.dumps(
            {
                "candidate_id": (
                    "prospective-consecutive-loss-cooldown-relaxation-v1"
                ),
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "changes_risk_limits": False,
                "forward_markout_only": True,
                "realized_pnl_modeled": False,
                "option_results": [],
            }
        ),
        encoding="utf-8",
    )

    assert (
        cooldown_context_stability_cli.main(
            [
                "--input",
                str(source),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    status = json.loads(capsys.readouterr().out)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert status["stable_candidate_count"] == 0
    assert payload["direction_only_candidates_allowed"] is False
    assert payload["changes_strategy"] is False
    assert payload["changes_risk_limits"] is False
    assert payload["execution_authority"] is False
