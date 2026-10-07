from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_candidate import (
    LossContextCandidateFreeze,
)
from cocomelon.research.loss_context_replacement_entry_fill import (
    LossContextReplacementEntryFillError,
    loss_context_replacement_entry_fill_summary,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    CandidateCausedCapacityRelease,
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


def _release(
    freeze: LossContextCandidateFreeze,
    *,
    opportunity_id: str,
    timestamp_ms: int,
) -> CandidateCausedCapacityRelease:
    return CandidateCausedCapacityRelease(
        opportunity_id=opportunity_id,
        opportunity_timestamp_ms=timestamp_ms,
        opportunity_market="SOL",
        release_market="BTC",
        release_correlation_bucket="majors",
        release_opening_plan_id="holder-plan-btc",
        release_block_reason="frozen_loss_context",
    )


def _holder_report(
    freeze: LossContextCandidateFreeze,
    options: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "candidate_id": freeze.candidate_id,
        "enabled": True,
        "gate_open": True,
        "ready_for_replacement_entry_investigation": bool(options),
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
        "replacement_entry_fills_modeled": False,
        "replacement_pnl_modeled": False,
        "exact_full_close_release_options": len(options),
        "full_close_release_options": options,
    }


def _holder_option(
    release: CandidateCausedCapacityRelease,
    terminal: str,
) -> dict[str, object]:
    return {
        "release_option_id": (
            f"{release.opportunity_id}:"
            f"{release.release_opening_plan_id}"
        ),
        "opportunity_id": release.opportunity_id,
        "opportunity_timestamp_ms": release.opportunity_timestamp_ms,
        "opportunity_market": release.opportunity_market,
        "release_market": release.release_market,
        "release_correlation_bucket": (
            release.release_correlation_bucket
        ),
        "release_opening_plan_id": release.release_opening_plan_id,
        "full_close_terminal_contribution": terminal,
        "execution_result": "full",
    }


def test_replacement_entry_replays_same_holder_per_opportunity(
    monkeypatch,
) -> None:
    freeze = _freeze()
    first = _release(
        freeze,
        opportunity_id="opportunity-1",
        timestamp_ms=freeze.prospective_not_before_ms + 1_000,
    )
    second = _release(
        freeze,
        opportunity_id="opportunity-2",
        timestamp_ms=freeze.prospective_not_before_ms + 2_000,
    )
    opportunities = (
        SimpleNamespace(
            opportunity_id=first.opportunity_id,
            opportunity_timestamp_ms=first.opportunity_timestamp_ms,
            market=first.opportunity_market,
        ),
        SimpleNamespace(
            opportunity_id=second.opportunity_id,
            opportunity_timestamp_ms=second.opportunity_timestamp_ms,
            market=second.opportunity_market,
        ),
    )
    holder = _holder_report(
        freeze,
        [
            _holder_option(first, "1.25"),
            _holder_option(second, "-0.75"),
        ],
    )
    seen_terminal_maps: list[dict[str, Decimal]] = []

    def fake_replay(
        replay_opportunities,
        replay_releases,
        _config,
        *,
        position_history_loader,
        released_position_terminal_contribution_by_plan,
    ):
        del position_history_loader
        assert len(replay_opportunities) == 1
        assert len(replay_releases) == 1
        terminal_map = dict(
            released_position_terminal_contribution_by_plan
        )
        seen_terminal_maps.append(terminal_map)
        release = replay_releases[0]
        option_id = (
            f"{release.opportunity_id}:"
            f"{release.release_opening_plan_id}"
        )
        terminal = terminal_map[release.release_opening_plan_id]
        return {
            "option_results": [
                {
                    "option_id": option_id,
                    "risk_approved": True,
                    "risk_reason_codes": ["risk_approved"],
                    "planning_approved": True,
                    "planning_rejection": None,
                    "execution_result": "full",
                    "counterfactual_equity_delta": str(terminal),
                }
            ],
            "conservative_risk_approvals": 1,
            "planning_approvals": 1,
            "fillable_options": 1,
            "full_fill_options": 1,
            "partial_fill_options": 0,
            "no_fill_options": 0,
            "execution_rejected_options": 0,
            "gross_fill_notional": "100",
            "taker_fees": "0.05",
        }

    monkeypatch.setattr(
        "cocomelon.research.loss_context_replacement_entry_fill."
        "prospective_capacity_reflow_fill_feasibility_summary",
        fake_replay,
    )

    result = loss_context_replacement_entry_fill_summary(
        opportunities,  # type: ignore[arg-type]
        (first, second),
        holder,
        freeze=freeze,
        config=PaperExecutionConfig(),
        position_history_loader=lambda _plan, _through: (),
    )

    assert seen_terminal_maps == [
        {"holder-plan-btc": Decimal("1.25")},
        {"holder-plan-btc": Decimal("-0.75")},
    ]
    assert result["holder_full_close_release_options"] == 2
    assert result["entry_replayed_options"] == 2
    assert result["conservative_risk_approvals"] == 2
    assert result["planning_approvals"] == 2
    assert result["fillable_options"] == 2
    assert result["full_fill_options"] == 2
    assert result["partial_fill_options"] == 0
    assert result["gross_fill_notional"] == "200"
    assert result["taker_fees"] == "0.10"
    assert result["ready_for_replacement_exit_investigation"] is True
    assert result[
        "holder_release_terminal_contribution_applied_per_option"
    ] is True
    assert result["replacement_exits_modeled"] is False
    assert result["replacement_pnl_modeled"] is False
    assert result["changes_strategy"] is False
    assert result["execution_authority"] is False


def test_replacement_entry_rejects_holder_authority_drift() -> None:
    freeze = _freeze()
    holder = _holder_report(freeze, [])
    holder["changes_positions"] = True

    with pytest.raises(
        LossContextReplacementEntryFillError,
        match="HOLDER_AUTHORITY_INVALID",
    ):
        loss_context_replacement_entry_fill_summary(
            (),
            (),
            holder,
            freeze=freeze,
            config=PaperExecutionConfig(),
            position_history_loader=lambda _plan, _through: (),
        )


def test_replacement_entry_requires_exact_opportunity_lineage() -> None:
    freeze = _freeze()
    release = _release(
        freeze,
        opportunity_id="missing-opportunity",
        timestamp_ms=freeze.prospective_not_before_ms + 1_000,
    )
    holder = _holder_report(
        freeze,
        [_holder_option(release, "1")],
    )

    with pytest.raises(
        LossContextReplacementEntryFillError,
        match="opportunity evidence is missing",
    ):
        loss_context_replacement_entry_fill_summary(
            (),
            (release,),
            holder,
            freeze=freeze,
            config=PaperExecutionConfig(),
            position_history_loader=lambda _plan, _through: (),
        )


def test_replacement_entry_workflow_runs_after_holder_release() -> None:
    source = Path(
        ".github/workflows/continuous-paper.yml"
    ).read_text(encoding="utf-8")
    holder_at = source.index(
        "- name: Rebuild loss-context holder release execution"
    )
    entry_at = source.index(
        "- name: Rebuild loss-context replacement entry fill"
    )
    upload_at = source.index(
        "- name: Upload loss-context replacement entry fill"
    )
    cooldown_at = source.index(
        "- name: Rebuild deferred cooldown evidence after handoff"
    )
    assert holder_at < entry_at < upload_at < cooldown_at
    assert (
        "rebuild_deferred_loss_context_replacement_entry_fill.py"
        in source
    )
    assert "loss-context-replacement-entry-fill-summary.json" in source
    assert "RESEARCH ONLY / NO POSITION OR RISK CHANGE" in source
