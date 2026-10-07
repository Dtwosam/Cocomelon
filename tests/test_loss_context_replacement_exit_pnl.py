from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_candidate import (
    LossContextCandidateFreeze,
)
from cocomelon.research.loss_context_replacement_exit_pnl import (
    LossContextReplacementExitPnlError,
    loss_context_replacement_exit_pnl_summary,
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


def _entry(
    freeze: LossContextCandidateFreeze,
) -> dict[str, object]:
    return {
        "candidate_id": freeze.candidate_id,
        "enabled": True,
        "gate_open": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
        "replacement_entry_fills_modeled": True,
        "replacement_exits_modeled": False,
        "replacement_pnl_modeled": False,
        "fillable_options": 2,
    }


def test_exit_pnl_keeps_horizons_separate_and_requires_completeness(
    monkeypatch,
) -> None:
    freeze = _freeze()
    entry = _entry(freeze)
    horizons = (300_000, 900_000, 3_600_000)

    def fake_exit(
        fill,
        books,
        config,
        *,
        horizons_ms,
    ):
        assert fill is entry
        assert books == ()
        assert config == PaperExecutionConfig()
        assert horizons_ms == horizons
        return {
            "execution_authority": False,
            "promotion_authority": False,
            "replacement_entry_fills_modeled": True,
            "replacement_exit_fills_modeled": True,
            "cross_horizon_economics_aggregated": False,
            "horizons_ms": list(horizons),
            "option_exits": [],
        }

    def fake_realized(exit_fill, funding):
        assert exit_fill["replacement_exit_fills_modeled"] is True
        assert funding == ()
        return {
            "execution_authority": False,
            "promotion_authority": False,
            "exact_realized_pnl_available": True,
            "by_horizon": {
                "300000": {
                    "options": 2,
                    "exact_realized_pnl_options": 2,
                    "exact_realized_pnl": "3",
                    "incomplete_or_missing_exits": 0,
                    "funding_evidence_missing_closes": 0,
                },
                "900000": {
                    "options": 2,
                    "exact_realized_pnl_options": 2,
                    "exact_realized_pnl": "1",
                    "incomplete_or_missing_exits": 0,
                    "funding_evidence_missing_closes": 0,
                },
                "3600000": {
                    "options": 2,
                    "exact_realized_pnl_options": 2,
                    "exact_realized_pnl": "-1",
                    "incomplete_or_missing_exits": 0,
                    "funding_evidence_missing_closes": 0,
                },
            },
        }

    monkeypatch.setattr(
        "cocomelon.research.loss_context_replacement_exit_pnl."
        "prospective_capacity_reflow_exit_fill_summary",
        fake_exit,
    )
    monkeypatch.setattr(
        "cocomelon.research.loss_context_replacement_exit_pnl."
        "prospective_capacity_reflow_realized_pnl_summary",
        fake_realized,
    )

    result = loss_context_replacement_exit_pnl_summary(
        entry,
        (),
        (),
        freeze=freeze,
        config=PaperExecutionConfig(),
        horizons_ms=horizons,
    )

    assert result["all_horizons_complete"] is True
    assert result["all_horizons_positive"] is False
    assert result[
        "ready_for_portfolio_counterfactual_investigation"
    ] is True
    assert result["cross_horizon_economics_aggregated"] is False
    assert result["horizon_selection_performed"] is False
    assert result["selected_horizon_ms"] is None
    reviews = result["horizon_reviews"]
    assert isinstance(reviews, dict)
    assert reviews["300000"]["positive"] is True
    assert reviews["3600000"]["positive"] is False
    assert result["strategy_level_realized_pnl_claimed"] is False
    assert result["execution_authority"] is False


def test_exit_pnl_incomplete_horizon_stays_unready(
    monkeypatch,
) -> None:
    freeze = _freeze()
    entry = _entry(freeze)
    horizons = (300_000, 900_000)

    monkeypatch.setattr(
        "cocomelon.research.loss_context_replacement_exit_pnl."
        "prospective_capacity_reflow_exit_fill_summary",
        lambda *_args, **_kwargs: {
            "execution_authority": False,
            "promotion_authority": False,
            "replacement_entry_fills_modeled": True,
            "replacement_exit_fills_modeled": True,
            "cross_horizon_economics_aggregated": False,
        },
    )
    monkeypatch.setattr(
        "cocomelon.research.loss_context_replacement_exit_pnl."
        "prospective_capacity_reflow_realized_pnl_summary",
        lambda *_args, **_kwargs: {
            "execution_authority": False,
            "promotion_authority": False,
            "exact_realized_pnl_available": True,
            "by_horizon": {
                "300000": {
                    "options": 2,
                    "exact_realized_pnl_options": 2,
                    "exact_realized_pnl": "2",
                    "incomplete_or_missing_exits": 0,
                    "funding_evidence_missing_closes": 0,
                },
                "900000": {
                    "options": 2,
                    "exact_realized_pnl_options": 1,
                    "exact_realized_pnl": "1",
                    "incomplete_or_missing_exits": 1,
                    "funding_evidence_missing_closes": 0,
                },
            },
        },
    )

    result = loss_context_replacement_exit_pnl_summary(
        entry,
        (),
        (),
        freeze=freeze,
        config=PaperExecutionConfig(),
        horizons_ms=horizons,
    )

    assert result["all_horizons_complete"] is False
    assert result[
        "ready_for_portfolio_counterfactual_investigation"
    ] is False


def test_exit_pnl_rejects_entry_authority_drift() -> None:
    freeze = _freeze()
    entry = _entry(freeze)
    entry["changes_strategy"] = True

    with pytest.raises(
        LossContextReplacementExitPnlError,
        match="ENTRY_AUTHORITY_INVALID",
    ):
        loss_context_replacement_exit_pnl_summary(
            entry,
            (),
            (),
            freeze=freeze,
            config=PaperExecutionConfig(),
            horizons_ms=(300_000,),
        )


def test_replacement_exit_workflow_runs_after_entry_fill() -> None:
    source = Path(
        ".github/workflows/continuous-paper.yml"
    ).read_text(encoding="utf-8")
    entry_at = source.index(
        "- name: Rebuild loss-context replacement entry fill"
    )
    exit_at = source.index(
        "- name: Rebuild loss-context replacement exit pnl"
    )
    upload_at = source.index(
        "- name: Upload loss-context replacement exit pnl"
    )
    cooldown_at = source.index(
        "- name: Rebuild deferred cooldown evidence after handoff"
    )
    assert entry_at < exit_at < upload_at < cooldown_at
    assert (
        "rebuild_deferred_loss_context_replacement_exit_pnl.py"
        in source
    )
    assert "loss-context-replacement-exit-pnl-summary.json" in source
    assert "RESEARCH ONLY / NO POSITION OR RISK CHANGE" in source
