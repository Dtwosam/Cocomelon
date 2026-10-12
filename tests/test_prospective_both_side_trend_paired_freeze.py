"""A paired shadow plan never rewrites the original trend trial or trades."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    verify_loss_context_portfolio_shadow_freeze,
)
from cocomelon.research.paper_profitability_scoreboard import (
    BOTH_SIDE_TREND_DISCOVERY_ARTIFACT_ID,
    BOTH_SIDE_TREND_DISCOVERY_GITHUB_ARTIFACT_SHA256,
    BOTH_SIDE_TREND_DISCOVERY_RUN_ID,
    BOTH_SIDE_TREND_FORWARD_MS,
    BOTH_SIDE_TREND_FREEZE_MS,
)
from cocomelon.research.prospective_both_side_trend_paired_freeze import (
    DISCOVERY_HEAD_SHA,
    DISCOVERY_WORKER_UPDATED_UPPER_BOUND_MS,
    TRIAL_ID,
    both_side_trend_matched_shadow_freeze,
)


def test_trend_paired_identity_bound_to_real_210_close_discovery() -> None:
    freeze = both_side_trend_matched_shadow_freeze()
    assert freeze.dimensions == ("lead_strategy",)
    assert freeze.values == ("trend",)
    assert freeze.frozen_at_ms == BOTH_SIDE_TREND_FREEZE_MS
    assert freeze.prospective_not_before_ms == BOTH_SIDE_TREND_FORWARD_MS
    assert freeze.source_paper_run_id == BOTH_SIDE_TREND_DISCOVERY_RUN_ID
    assert freeze.source_paper_run_attempt == 1
    assert freeze.source_paper_head_sha == DISCOVERY_HEAD_SHA
    assert freeze.source_max_timestamp_ms == DISCOVERY_WORKER_UPDATED_UPPER_BOUND_MS
    assert freeze.source_max_timestamp_ms < freeze.frozen_at_ms
    assert BOTH_SIDE_TREND_DISCOVERY_ARTIFACT_ID == 11739794720
    assert len(BOTH_SIDE_TREND_DISCOVERY_GITHUB_ARTIFACT_SHA256) == 64
    assert TRIAL_ID.endswith("capital-matched-shadow-v1")
    assert freeze.candidate_id == both_side_trend_matched_shadow_freeze().candidate_id
    assert freeze.loss_context_candidate_id != freeze.source_composition_digest


def test_paired_freeze_is_verifiable_but_never_execution_authority(
    tmp_path: Path,
) -> None:
    freeze = both_side_trend_matched_shadow_freeze()
    path = tmp_path / "paired-freeze.json"
    path.write_text(json.dumps(freeze.to_dict()), encoding="utf-8")
    assert verify_loss_context_portfolio_shadow_freeze(path) == freeze
    assert freeze.paper_only is True
    assert freeze.shadow_only is True
    assert freeze.prospective_only is True
    assert freeze.research_only is True
    assert freeze.horizon_selection_performed is False
    assert freeze.cross_horizon_economics_aggregated is False
    assert freeze.execution_authority is False
    assert freeze.promotion_authority is False
    assert freeze.changes_strategy is False
    assert freeze.changes_positions is False
    assert freeze.changes_risk_limits is False

    tampered = freeze.to_dict()
    tampered["prospective_not_before_ms"] = BOTH_SIDE_TREND_FREEZE_MS
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_loss_context_portfolio_shadow_freeze(path)


def test_new_paired_trial_has_no_live_runtime_wiring() -> None:
    """A freezer alone is not a launched paired-account experiment."""
    paper = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8")
    assert "prospective_both_side_trend_paired_freeze" not in paper
    assert "both_side_trend_matched_shadow_freeze" not in paper
