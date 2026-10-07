from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_candidate import (
    LossContextCandidateFreeze,
)
from cocomelon.research.loss_context_portfolio_composition import (
    loss_context_portfolio_composition_summary,
)


def _freeze() -> LossContextCandidateFreeze:
    frozen_at_ms = 10_000
    return LossContextCandidateFreeze(
        source_audit_digest="a" * 64,
        source_max_timestamp_ms=9_000,
        source_paper_run_id=123,
        source_paper_run_attempt=1,
        source_paper_head_sha="b" * 40,
        dimensions=("lead_strategy", "trend_regime"),
        values=("mean_reversion", "down"),
        discovery_rows=20,
        discovery_markets=5,
        discovery_loss_share=Decimal("0.70"),
        discovery_filter_delta_pnl=Decimal("30"),
        validation_rows=12,
        validation_markets=4,
        validation_loss_share=Decimal("0.75"),
        validation_filter_delta_pnl=Decimal("20"),
        validation_leave_one_trade_min_delta_pnl=Decimal("15"),
        validation_leave_one_market_min_delta_pnl=Decimal("10"),
        frozen_at_ms=frozen_at_ms,
        prospective_not_before_ms=(
            frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ),
    )


def _account(freeze: LossContextCandidateFreeze) -> dict[str, object]:
    return {
        "candidate_id": freeze.candidate_id,
        "fixed_schedule_economics_ready": True,
        "research_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "promotion_authority": False,
        "execution_authority": False,
        "fixed_schedule_economics": {
            "actual_net_pnl": "-10",
            "candidate_net_pnl": "6",
            "delta_net_pnl": "16",
        },
    }


def _entry(
    freeze: LossContextCandidateFreeze,
    *,
    duplicate_opportunity: bool = False,
    reused_holder: bool = False,
) -> dict[str, object]:
    second_opportunity = "opp-1" if duplicate_opportunity else "opp-2"
    second_holder = "holder-1" if reused_holder else "holder-2"
    rows = [
        {
            "option_id": "opt-1",
            "opportunity_id": "opp-1",
            "release_opening_plan_id": "holder-1",
            "execution_result": "full",
        },
        {
            "option_id": "opt-2",
            "opportunity_id": second_opportunity,
            "release_opening_plan_id": second_holder,
            "execution_result": "full",
        },
    ]
    return {
        "candidate_id": freeze.candidate_id,
        "ready_for_replacement_exit_investigation": True,
        "research_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
        "fillable_option_ids": ["opt-1", "opt-2"],
        "option_results": rows,
    }


def _exit(
    freeze: LossContextCandidateFreeze,
    *,
    overlap: bool = False,
) -> dict[str, object]:
    second_entry = 1_400 if overlap else 2_000
    return {
        "candidate_id": freeze.candidate_id,
        "ready_for_portfolio_counterfactual_investigation": True,
        "all_horizons_complete": True,
        "cross_horizon_economics_aggregated": False,
        "horizon_selection_performed": False,
        "research_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
        "horizons_ms": [300_000, 900_000],
        "realized_pnl": {
            "option_results": [
                {
                    "option_id": "opt-1",
                    "opportunity_id": "opp-1",
                    "entry_attempt_timestamp_ms": 1_000,
                    "exits": {
                        "300000": {
                            "exact_realized_pnl": "3",
                            "closed_at_ms": 1_500,
                        },
                        "900000": {
                            "exact_realized_pnl": "2",
                            "closed_at_ms": 1_800,
                        },
                    },
                },
                {
                    "option_id": "opt-2",
                    "opportunity_id": "opp-2",
                    "entry_attempt_timestamp_ms": second_entry,
                    "exits": {
                        "300000": {
                            "exact_realized_pnl": "4",
                            "closed_at_ms": 2_500,
                        },
                        "900000": {
                            "exact_realized_pnl": "1",
                            "closed_at_ms": 2_900,
                        },
                    },
                },
            ]
        },
    }


def test_portfolio_composition_advances_only_clean_independent_paths() -> None:
    freeze = _freeze()
    result = loss_context_portfolio_composition_summary(
        _account(freeze),
        _entry(freeze),
        _exit(freeze),
        freeze=freeze,
    )

    assert result["all_horizons_structurally_composable"] is True
    assert result["ready_for_chronological_portfolio_replay"] is True
    assert result["portfolio_counterfactual_complete"] is False
    assert result["horizon_selection_performed"] is False
    assert result["cross_horizon_economics_aggregated"] is False

    horizons = result["horizon_summaries"]
    assert isinstance(horizons, dict)
    five = horizons["300000"]
    assert five["structurally_composable"] is True
    assert five["ambiguous_opportunity_count"] == 0
    assert five["reused_release_holder_count"] == 0
    assert five["overlapping_replacement_pairs"] == 0
    assert five["independent_path_exact_replacement_pnl"] == "7"
    assert five["first_order_combined_pnl"] == "13"
    assert five["first_order_delta_vs_actual_pnl"] == "23"
    assert five["portfolio_counterfactual_complete"] is False


def test_portfolio_composition_rejects_duplicate_opportunity_credit() -> None:
    freeze = _freeze()
    entry = _entry(freeze, duplicate_opportunity=True)
    exit_pnl = _exit(freeze)
    realized = exit_pnl["realized_pnl"]
    assert isinstance(realized, dict)
    options = realized["option_results"]
    assert isinstance(options, list)
    options[1]["opportunity_id"] = "opp-1"

    result = loss_context_portfolio_composition_summary(
        _account(freeze),
        entry,
        exit_pnl,
        freeze=freeze,
    )

    assert result["all_horizons_structurally_composable"] is False
    assert result["ready_for_chronological_portfolio_replay"] is False
    horizons = result["horizon_summaries"]
    assert isinstance(horizons, dict)
    assert horizons["300000"]["ambiguous_opportunity_count"] == 1


def test_portfolio_composition_rejects_reused_holder_and_overlap() -> None:
    freeze = _freeze()
    result = loss_context_portfolio_composition_summary(
        _account(freeze),
        _entry(freeze, reused_holder=True),
        _exit(freeze, overlap=True),
        freeze=freeze,
    )

    assert result["all_horizons_structurally_composable"] is False
    horizons = result["horizon_summaries"]
    assert isinstance(horizons, dict)
    assert horizons["300000"]["reused_release_holder_count"] == 1
    assert horizons["300000"]["overlapping_replacement_pairs"] == 1
    assert result["ready_for_chronological_portfolio_replay"] is False


def test_portfolio_composition_workflow_follows_exact_exit_pnl() -> None:
    source = Path(
        ".github/workflows/continuous-paper.yml"
    ).read_text(encoding="utf-8")
    exit_at = source.index(
        "- name: Rebuild loss-context replacement exit pnl"
    )
    composition_at = source.index(
        "- name: Rebuild loss-context portfolio composition"
    )
    upload_at = source.index(
        "- name: Upload loss-context portfolio composition"
    )
    cooldown_at = source.index(
        "- name: Rebuild deferred cooldown evidence after handoff"
    )
    assert exit_at < composition_at < upload_at < cooldown_at
    assert (
        "rebuild_deferred_loss_context_portfolio_composition.py"
        in source
    )
    assert "NO PORTFOLIO PNL CLAIM" in source
