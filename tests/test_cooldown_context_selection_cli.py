from __future__ import annotations

import json
from pathlib import Path

from cocomelon import cooldown_context_selection_cli


def test_cooldown_selection_cli_writes_authority_negative_record(
    tmp_path: Path,
    capsys,
) -> None:
    cooldown = tmp_path / "cooldown.json"
    stability = tmp_path / "stability.json"
    output = tmp_path / "selection.json"
    cooldown.write_text(
        json.dumps(
            {
                "candidate_id": (
                    "prospective-consecutive-loss-cooldown-relaxation-v1"
                ),
                "research_only": True,
                "descriptive_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "changes_risk_limits": False,
                "forward_markout_only": True,
                "realized_pnl_modeled": False,
                "relaxed_cooldown_windows_ms": [900000, 1800000, 2700000],
                "option_results": [],
            }
        ),
        encoding="utf-8",
    )
    stability.write_text(
        json.dumps(
            {
                "settled_1h_outcomes": 0,
                "candidates": [],
                "direction_only_candidates_allowed": False,
                "lead_strategy_context_required": True,
                "relaxation_window_context_required": True,
                "window_eligible_outcomes_only": True,
                "one_hour_fee_adjusted_execution_economics_required": True,
                "chronological_holdout_required": True,
                "leave_one_option_robustness_required": True,
                "leave_one_market_robustness_required": True,
                "validation_block_consistency_required": True,
                "research_only": True,
                "descriptive_only": True,
                "changes_strategy": False,
                "changes_risk_limits": False,
                "promotion_authority": False,
                "execution_authority": False,
                "schema_version": 2,
            }
        ),
        encoding="utf-8",
    )

    assert (
        cooldown_context_selection_cli.main(
            [
                "--cooldown",
                str(cooldown),
                "--stability",
                str(stability),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    status = json.loads(capsys.readouterr().out)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert status["stable_candidate_count"] == 0
    assert payload["selected_candidate"] is None
    assert payload["prospective_freeze_required_before_strategy_use"] is True
    assert payload["relaxation_window_context_required"] is True
    assert payload["window_eligible_outcomes_only"] is True
    assert payload["changes_risk_limits"] is False
    assert payload["execution_authority"] is False
