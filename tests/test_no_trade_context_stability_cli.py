from __future__ import annotations

import json
from pathlib import Path

from cocomelon import no_trade_context_stability_cli


def test_no_trade_context_stability_cli_emits_research_report(
    tmp_path: Path,
    capsys,
) -> None:
    outcomes = []
    for index in range(20):
        value = "0.02" if index % 4 != 3 else "-0.02"
        outcomes.append(
            {
                "decision_fact_id": f"fact-{index}",
                "strategy_decision_id": f"decision-{index}",
                "market": "HYPE",
                "decision_timestamp_ms": index + 1,
                "feature_snapshot_id": f"feature-{index}",
                "feature_as_of_ms": index + 1,
                "horizon_ms": 900_000,
                "target_as_of_ms": index + 900_001,
                "forward_mark_return": value,
                "favored_direction": "long" if value[0] != "-" else "short",
                "reason_codes": ["no_primary_thesis"],
                "decision_stage": "strategy_abstained",
                "trend_regime": "up",
                "volatility_regime": "high",
                "return_15m_sign": "positive",
                "return_1h_sign": "positive",
                "funding_sign": "positive",
                "book_imbalance_sign": "negative",
            }
        )
    path = tmp_path / "forward.json"
    path.write_text(
        json.dumps(
            {
                "decision_state_digest": "a" * 64,
                "feature_state_digest": "b" * 64,
                "diagnostic_only": True,
                "hypothetical_pnl": False,
                "execution_authority": False,
                "outcomes": outcomes,
            }
        ),
        encoding="utf-8",
    )

    assert (
        no_trade_context_stability_cli.main(
            [
                "--input",
                str(path),
                "--split-fraction",
                "0.5",
                "--threshold-bps",
                "100",
                "--min-discovery-rows",
                "4",
                "--min-validation-rows",
                "4",
                "--min-discovery-direction-share",
                "0.6",
                "--min-validation-direction-share",
                "0.51",
                "--min-validation-lift",
                "0",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "no-trade-context-stability"
    assert payload["chronological_holdout_required"] is True
    assert payload["directional_candidate_source"] == "strategy_abstained_only"
    assert payload["market_aware"] is True
    assert payload["validation_block_consistency_required"] is True
    assert payload["validation_block_count"] == 3
    assert payload["strategy_abstained_outcomes"] == 20
    assert payload["exploratory_only"] is True
    assert payload["execution_authority"] is False
