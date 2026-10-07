from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowCandidateError,
    build_loss_context_portfolio_shadow_freeze,
    verify_loss_context_portfolio_shadow_freeze,
    write_loss_context_portfolio_shadow_freeze,
)


def _composition() -> dict[str, object]:
    return {
        "candidate_id": "a" * 64,
        "dimensions": ["lead_strategy", "trend_regime"],
        "values": ["mean_reversion", "down"],
        "source_max_timestamp_ms": 20_000,
        "gate_open": True,
        "all_horizons_structurally_composable": True,
        "ready_for_chronological_portfolio_replay": True,
        "research_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
        "horizon_selection_performed": False,
        "cross_horizon_economics_aggregated": False,
        "chronological_account_state_replayed": False,
        "portfolio_counterfactual_complete": False,
        "strategy_level_realized_pnl_claimed": False,
        "horizons_ms": [300_000, 900_000],
        "horizon_summaries": {
            "300000": {
                "horizon_ms": 300_000,
                "structurally_composable": True,
                "chronological_account_state_replayed": False,
                "portfolio_counterfactual_complete": False,
                "strategy_level_realized_pnl_claimed": False,
            },
            "900000": {
                "horizon_ms": 900_000,
                "structurally_composable": True,
                "chronological_account_state_replayed": False,
                "portfolio_counterfactual_complete": False,
                "strategy_level_realized_pnl_claimed": False,
            },
        },
    }


def test_portfolio_shadow_freeze_preserves_all_horizons() -> None:
    freeze = build_loss_context_portfolio_shadow_freeze(
        _composition(),
        frozen_at_ms=25_000,
        source_paper_run_id=123,
        source_paper_run_attempt=1,
        source_paper_head_sha="b" * 40,
    )

    assert freeze.loss_context_candidate_id == "a" * 64
    assert freeze.horizons_ms == (300_000, 900_000)
    assert freeze.prospective_not_before_ms == (
        25_000 + MIN_PROSPECTIVE_EMBARGO_MS
    )
    assert freeze.horizon_selection_performed is False
    assert freeze.cross_horizon_economics_aggregated is False
    assert freeze.changes_strategy is False
    assert freeze.execution_authority is False


def test_portfolio_shadow_freeze_rejects_same_evidence_reuse() -> None:
    with pytest.raises(
        LossContextPortfolioShadowCandidateError,
        match="predates source evidence",
    ):
        build_loss_context_portfolio_shadow_freeze(
            _composition(),
            frozen_at_ms=19_999,
            source_paper_run_id=123,
            source_paper_run_attempt=1,
            source_paper_head_sha="b" * 40,
        )


def test_portfolio_shadow_freeze_rejects_horizon_selection() -> None:
    payload = _composition()
    payload["horizon_selection_performed"] = True
    with pytest.raises(
        LossContextPortfolioShadowCandidateError,
        match="authority or methodology drift",
    ):
        build_loss_context_portfolio_shadow_freeze(
            payload,
            frozen_at_ms=25_000,
            source_paper_run_id=123,
            source_paper_run_attempt=1,
            source_paper_head_sha="b" * 40,
        )


def test_portfolio_shadow_freeze_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "freeze.json"
    first, created = write_loss_context_portfolio_shadow_freeze(
        _composition(),
        output_path=path,
        frozen_at_ms=25_000,
        source_paper_run_id=123,
        source_paper_run_attempt=1,
        source_paper_head_sha="b" * 40,
    )
    assert created is True

    changed = _composition()
    changed["horizons_ms"] = [300_000]
    changed["horizon_summaries"] = {
        "300000": changed["horizon_summaries"]["300000"]
    }
    second, created_again = write_loss_context_portfolio_shadow_freeze(
        changed,
        output_path=path,
        frozen_at_ms=30_000,
        source_paper_run_id=999,
        source_paper_run_attempt=2,
        source_paper_head_sha="c" * 40,
    )

    assert created_again is False
    assert second == first
    assert verify_loss_context_portfolio_shadow_freeze(path) == first


def test_portfolio_shadow_freeze_detects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "freeze.json"
    freeze, _ = write_loss_context_portfolio_shadow_freeze(
        _composition(),
        output_path=path,
        frozen_at_ms=25_000,
        source_paper_run_id=123,
        source_paper_run_attempt=1,
        source_paper_head_sha="b" * 40,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["horizons_ms"] = [300_000]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        LossContextPortfolioShadowCandidateError,
        match="candidate id mismatch",
    ):
        verify_loss_context_portfolio_shadow_freeze(path)
    assert freeze.candidate_id != ""



def test_portfolio_shadow_freeze_workflow_follows_composition() -> None:
    source = Path(
        ".github/workflows/continuous-paper.yml"
    ).read_text(encoding="utf-8")
    composition_upload = source.index(
        "- name: Upload loss-context portfolio composition"
    )
    restore = source.index(
        "- name: Restore immutable loss-context portfolio shadow freeze"
    )
    freeze = source.index(
        "- name: Freeze loss-context portfolio shadow prospectively"
    )
    upload = source.index(
        "- name: Upload immutable loss-context portfolio shadow candidate"
    )
    cooldown = source.index(
        "- name: Rebuild deferred cooldown evidence after handoff"
    )
    assert composition_upload < restore < freeze < upload < cooldown
    assert "shadow freeze remains absent" in source
    assert "RESEARCH SHADOW ONLY / NO STRATEGY OR RISK CHANGE" in source
    assert "selected horizon: " in source
