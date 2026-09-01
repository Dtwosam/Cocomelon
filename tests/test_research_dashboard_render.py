from __future__ import annotations

from cocomelon.research.dashboard import (
    RESEARCH_STATUS_LABEL,
    render_research_status_markdown,
)


def _snapshot() -> dict[str, object]:
    return {
        "label": RESEARCH_STATUS_LABEL,
        "candidate_count": 1,
        "state_counts": {"researching": 1},
        "candidates": [
            {
                "candidate_id": "candidate-a",
                "family_id": "family-a",
                "parent_candidate_id": None,
                "ancestor_candidate_ids": [],
                "config_digest": "a" * 64,
                "code_revision": "1" * 40,
                "execution_config_json": '{"mode":"paper"}',
                "risk_config_json": '{"risk_per_trade":"0.0025"}',
                "state": "researching",
                "first_observation_ms": 1_000,
                "last_observation_ms": 400_000,
                "source_provenance_ids": ["source-first", "source-second"],
                "local_touched_intervals": [
                    {"start_ms": 1_000, "end_ms": 400_000},
                ],
                "effective_touched_intervals": [
                    {"start_ms": 1_000, "end_ms": 400_000},
                ],
                "checkpoint_count": 2,
                "economics_visible": True,
                "checkpoints": [
                    {
                        "report_id": "r1",
                        "commit_index": 1,
                        "source_end_ms": 200_000,
                        "batch_ids": ["batch-first"],
                        "source_ids": ["source-first"],
                        "closed_trade_count": 1,
                        "closed_trade_days": 1,
                        "net_pnl": "6.250000",
                        "mean_net_r": "0.25",
                        "posterior_probability_positive": None,
                        "checkpoint_state": "insufficient_trades",
                        "candidate_state": "researching",
                    },
                    {
                        "report_id": "r2",
                        "commit_index": 2,
                        "source_end_ms": 400_000,
                        "batch_ids": ["batch-first", "batch-second"],
                        "source_ids": ["source-first", "source-second"],
                        "closed_trade_count": 2,
                        "closed_trade_days": 2,
                        "net_pnl": "3.750000",
                        "mean_net_r": "0.075",
                        "posterior_probability_positive": None,
                        "checkpoint_state": "insufficient_trades",
                        "candidate_state": "researching",
                    },
                ],
            }
        ],
    }


def test_markdown_is_explicitly_non_promotional_and_research_only() -> None:
    rendered = render_research_status_markdown(_snapshot())

    assert rendered.startswith("# Research Status\n\n**TOUCHED / NON-PROMOTIONAL**")
    assert "Research results are not promotion or verified-edge evidence." in rendered
    assert "| candidate-a | researching | 2 | 2 | 2 | 3.750000 | 0.075 | — |" in rendered
    assert "## candidate-a checkpoint history" in rendered
    assert "| 1 | 200000 | insufficient_trades | 1 | 1 | 6.250000 | 0.25 | — |" in rendered
    assert "| 2 | 400000 | insufficient_trades | 2 | 2 | 3.750000 | 0.075 | — |" in rendered
    assert "V4 validation" not in rendered
    assert "CANDIDATE_EDGE" not in rendered


def test_markdown_handles_empty_status_without_inventing_economics() -> None:
    rendered = render_research_status_markdown(
        {
            "label": RESEARCH_STATUS_LABEL,
            "candidate_count": 0,
            "state_counts": {},
            "candidates": [],
        }
    )

    assert "No research candidates." in rendered
    assert "Net PnL" not in rendered
