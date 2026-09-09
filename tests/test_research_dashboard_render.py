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
                "zero_trade_checkpoint_streak": 0,
                "last_trade_checkpoint_index": 2,
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
                        "long_count": 1,
                        "short_count": 0,
                        "new_batch_count": 1,
                        "new_closed_trade_count": 1,
                        "new_closed_trade_days": 1,
                        "net_pnl_delta": "6.250000",
                        "new_long_count": 1,
                        "new_short_count": 0,
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
                        "long_count": 1,
                        "short_count": 1,
                        "new_batch_count": 1,
                        "new_closed_trade_count": 1,
                        "new_closed_trade_days": 1,
                        "net_pnl_delta": "-2.500000",
                        "new_long_count": 0,
                        "new_short_count": 1,
                    },
                ],
            }
        ],
    }


def test_markdown_is_explicitly_non_promotional_and_research_only() -> None:
    rendered = render_research_status_markdown(_snapshot())

    assert rendered.startswith("# Research Status\n\n**TOUCHED / NON-PROMOTIONAL**")
    assert "Research results are not promotion or verified-edge evidence." in rendered
    assert (
        "| candidate-a | researching | 2 | 2 | 1 | 1 | 2 | 0 | "
        "3.750000 | 0.075 | — |"
    ) in rendered
    assert "## candidate-a checkpoint history" in rendered
    assert (
        "| # | Source end ms | Checkpoint | New batches | New trades | New L | New S | "
        "Trades | New days | Days | Δ Net PnL | Net PnL | Mean R | Posterior |"
    ) in rendered
    assert (
        "| 1 | 200000 | insufficient_trades | 1 | 1 | 1 | 0 | 1 | 1 | 1 | "
        "6.250000 | 6.250000 | 0.25 | — |"
    ) in rendered
    assert (
        "| 2 | 400000 | insufficient_trades | 1 | 1 | 0 | 1 | 2 | 1 | 2 | "
        "-2.500000 | 3.750000 | 0.075 | — |"
    ) in rendered
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


def test_checkpoint_history_makes_zero_trade_cohort_explicit() -> None:
    snapshot = _snapshot()
    candidate = snapshot["candidates"][0]
    assert isinstance(candidate, dict)
    checkpoints = candidate["checkpoints"]
    assert isinstance(checkpoints, list)
    second = checkpoints[1]
    assert isinstance(second, dict)
    second["closed_trade_count"] = 1
    second["closed_trade_days"] = 1
    second["net_pnl"] = "6.250000"
    second["mean_net_r"] = "0.25"
    second["long_count"] = 1
    second["short_count"] = 0
    second["new_closed_trade_count"] = 0
    second["new_closed_trade_days"] = 0
    second["net_pnl_delta"] = "0"
    second["new_long_count"] = 0
    second["new_short_count"] = 0
    candidate["zero_trade_checkpoint_streak"] = 1
    candidate["last_trade_checkpoint_index"] = 1

    rendered = render_research_status_markdown(snapshot)

    assert (
        "| candidate-a | researching | 2 | 1 | 1 | 0 | 1 | 1 | "
        "6.250000 | 0.25 | — |"
    ) in rendered
    assert (
        "| 2 | 400000 | insufficient_trades | 1 | 0 | 0 | 0 | 1 | 0 | 1 | "
        "0 | 6.250000 | 0.25 | — |"
    ) in rendered



def test_markdown_renders_separate_read_only_throughput_history() -> None:
    snapshot = _snapshot()
    candidate = snapshot["candidates"][0]
    assert isinstance(candidate, dict)
    checkpoints = candidate["checkpoints"]
    assert isinstance(checkpoints, list)
    first = checkpoints[0]
    second = checkpoints[1]
    assert isinstance(first, dict)
    assert isinstance(second, dict)

    first.update(
        {
            "throughput_state": "unavailable",
            "new_decision_count": None,
            "new_signal_count": None,
            "new_long_signal_count": None,
            "new_short_signal_count": None,
            "new_entry_eligible_signal_count": None,
            "new_post_cutoff_signal_count": None,
            "new_no_trade_decision_count": None,
            "new_entry_eligible_reason_counts": None,
            "new_post_cutoff_reason_counts": None,
        }
    )
    second.update(
        {
            "throughput_state": "verified",
            "new_decision_count": 10,
            "new_signal_count": 1,
            "new_long_signal_count": 1,
            "new_short_signal_count": 0,
            "new_entry_eligible_signal_count": 0,
            "new_post_cutoff_signal_count": 1,
            "new_no_trade_decision_count": 9,
            "new_entry_eligible_reason_counts": {"not_deep_ready": 5},
            "new_post_cutoff_reason_counts": {
                "decision_threshold_met": 1,
                "not_deep_ready": 4,
            },
        }
    )

    rendered = render_research_status_markdown(snapshot)

    assert "### Decision throughput diagnostics" in rendered
    assert "read-only diagnostic provenance and is not checkpoint economics" in rendered
    assert (
        "| # | Diagnostics | Decisions | Signals | LONG | SHORT | "
        "Entry-eligible signals | Post-cutoff signals | NO_TRADE |"
    ) in rendered
    assert "| 1 | unavailable | — | — | — | — | — | — | — |" in rendered
    assert "| 2 | verified | 10 | 1 | 1 | 0 | 0 | 1 | 9 |" in rendered



def test_markdown_renders_attempt_audit_history_without_counting_failures() -> None:
    snapshot = _snapshot()
    candidate = snapshot["candidates"][0]
    assert isinstance(candidate, dict)
    candidate["attempt_count"] = 3
    candidate["attempts"] = [
        {
            "attempt_index": 3,
            "attempt_id": "attempt-workflow-failure",
            "status": "failed",
            "counted": False,
            "batch_id": "batch-workflow-failure",
            "start_ms": None,
            "end_ms": None,
            "report_id": None,
            "error_type": "WorkflowFailure",
            "error_message": (
                "research campaign failed before authenticated checkpoint; "
                "failed_jobs=prepare-control=failure,refresh-authority=cancelled"
            ),
        },
        {
            "attempt_index": 2,
            "attempt_id": "attempt-failure",
            "status": "failed",
            "counted": False,
            "batch_id": "batch-failure",
            "start_ms": 200_000,
            "end_ms": 300_000,
            "report_id": None,
            "error_type": "RuntimeError",
            "error_message": "synthetic audit failure",
        },
        {
            "attempt_index": 1,
            "attempt_id": "attempt-success",
            "status": "succeeded",
            "counted": True,
            "batch_id": "batch-first",
            "start_ms": 1_000,
            "end_ms": 200_000,
            "report_id": "r1",
            "error_type": None,
            "error_message": None,
        },
    ]

    rendered = render_research_status_markdown(snapshot)

    assert "### Research attempt audit history" in rendered
    assert "Failed, contaminated, running, and evaluating attempts are NOT COUNTED" in rendered
    assert (
        "| Attempt | Status | Checkpoint accounting | Batch | Start ms | End ms | "
        "Failure stage | Error |"
    ) in rendered
    assert (
        "| attempt-workflow-failure | failed | NOT COUNTED | batch-workflow-failure | — | — | "
        "prepare-control=failure, refresh-authority=cancelled | "
        "WorkflowFailure: research campaign failed before authenticated checkpoint; "
        "failed_jobs=prepare-control=failure,refresh-authority=cancelled |"
    ) in rendered
    assert (
        "| attempt-failure | failed | NOT COUNTED | batch-failure | 200000 | 300000 | — | "
        "RuntimeError: synthetic audit failure |"
    ) in rendered
    assert (
        "| attempt-success | succeeded | COUNTED | batch-first | 1000 | 200000 | — | — |"
    ) in rendered
