from __future__ import annotations

import json
from pathlib import Path

from cocomelon import (
    cooldown_context_candidate_cli,
    cooldown_context_prospective_cli,
)
from cocomelon.research.cooldown_context_selection import (
    build_cooldown_context_selection_record,
)


def _selection() -> dict[str, object]:
    cooldown = {
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
        "relaxed_cooldown_windows_ms": [900_000],
        "option_results": [{"timestamp_ms": 1_000}],
    }
    candidate = {
        "dimensions": ("relaxation_window_ms", "lead_strategy"),
        "values": ("900000", "trend"),
        "discovery_rows": 8,
        "discovery_markets": 4,
        "discovery_positive_share": "0.75",
        "discovery_total_pnl": "8",
        "discovery_mean_return": "0.002",
        "validation_rows": 6,
        "validation_markets": 3,
        "validation_positive_share": "0.6666666666666666666666666667",
        "validation_total_pnl": "5",
        "validation_mean_return": "0.001",
        "validation_leave_one_option_min_pnl": "2",
        "validation_leave_one_market_min_pnl": "1",
        "validation_block_rows": (3, 3),
        "validation_block_positive_shares": (
            "0.6666666666666666666666666667",
            "0.6666666666666666666666666667",
        ),
        "validation_block_pnl": ("2", "3"),
        "validation_blocks_consistent": 2,
        "stable_on_validation": True,
        "strategy_authority": False,
        "risk_authority": False,
        "execution_authority": False,
    }
    stability = {
        "source_option_count": 14,
        "settled_1h_outcomes": 14,
        "split_timestamp_ms": 500,
        "discovery_rows": 8,
        "validation_rows": 6,
        "candidate_count": 1,
        "stable_candidate_count": 1,
        "candidates": [candidate],
        "candidate_dimension_sets": (
            ("relaxation_window_ms", "lead_strategy"),
        ),
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
    return build_cooldown_context_selection_record(
        cooldown,
        stability,
    ).to_dict()


def test_freeze_and_prospective_clis_are_authority_negative(
    tmp_path: Path,
    capsys,
) -> None:
    selection_path = tmp_path / "selection.json"
    freeze_path = tmp_path / "freeze.json"
    cooldown_path = tmp_path / "cooldown.json"
    report_path = tmp_path / "prospective.json"
    selection_path.write_text(
        json.dumps(_selection()),
        encoding="utf-8",
    )

    assert (
        cooldown_context_candidate_cli.main(
            [
                "--selection",
                str(selection_path),
                "--output",
                str(freeze_path),
                "--frozen-at-ms",
                "1000",
                "--source-paper-run-id",
                "123",
                "--source-paper-run-attempt",
                "1",
                "--source-paper-head-sha",
                "a" * 40,
            ]
        )
        == 0
    )
    freeze_payload = json.loads(capsys.readouterr().out)
    assert freeze_payload["created"] is True
    assert freeze_payload["changes_risk_limits"] is False
    assert freeze_payload["execution_authority"] is False

    cooldown_path.write_text(
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
                "relaxed_cooldown_windows_ms": [900_000],
                "option_results": [],
            }
        ),
        encoding="utf-8",
    )

    assert (
        cooldown_context_prospective_cli.main(
            [
                "--cooldown",
                str(cooldown_path),
                "--freeze",
                str(freeze_path),
                "--output",
                str(report_path),
            ]
        )
        == 0
    )
    report_payload = json.loads(capsys.readouterr().out)
    assert report_payload["matching_outcomes"] == 0
    assert report_payload["ready_for_review"] is False
    assert report_payload["changes_risk_limits"] is False
    assert report_payload["execution_authority"] is False
    assert json.loads(report_path.read_text(encoding="utf-8")) == report_payload
