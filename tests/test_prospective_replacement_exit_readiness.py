from __future__ import annotations

from cocomelon.research.prospective_replacement_exit_readiness import (
    MIN_EXACT_OPTIONS_FOR_REVIEW,
    ProspectiveReplacementExitReadinessError,
    prospective_replacement_exit_readiness,
)


def _robustness(
    *,
    exact_options: int = 30,
    total_pnl: str = "12",
    profit_factor: str | None = "1.8",
    gross_profit: str = "27",
    gross_loss_abs: str = "15",
    option_leave_one_positive: bool | None = True,
    market_leave_one_positive: bool | None = True,
    full_blocks: int = 4,
    all_blocks_positive: bool = True,
) -> dict[str, object]:
    return {
        "enabled": True,
        "candidate_id": "prospective-replacement-5m-real-l2-exit-v1",
        "started_at_ms": 1_000,
        "exit_horizon_ms": 300_000,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_candidate_rule": False,
        "prospective_options": exact_options,
        "exact_options": exact_options,
        "incomplete_options": 0,
        "sample_ready_for_review": (
            exact_options >= MIN_EXACT_OPTIONS_FOR_REVIEW
        ),
        "total_exact_realized_pnl": total_pnl,
        "gross_profit": gross_profit,
        "gross_loss_abs": gross_loss_abs,
        "profit_factor": profit_factor,
        "positive_after_any_single_option_removed": (
            option_leave_one_positive
        ),
        "positive_after_any_single_market_removed": (
            market_leave_one_positive
        ),
        "temporal": {
            "configured_blocks": 4,
            "full_blocks": full_blocks,
            "positive_full_blocks": (
                full_blocks if all_blocks_positive else max(0, full_blocks - 1)
            ),
            "all_full_blocks_positive": all_blocks_positive,
        },
    }


def test_replacement_exit_readiness_freezes_review_gate() -> None:
    result = prospective_replacement_exit_readiness(
        _robustness()
    )

    assert result["ready_for_review"] is True
    assert result["promotion_authority"] is False
    assert result["execution_authority"] is False
    assert result["changes_candidate_rule"] is False
    assert result["requirements"] == {
        "minimum_exact_options": 30,
        "requires_positive_total_exact_pnl": True,
        "requires_profit_factor_above_one": True,
        "requires_positive_after_any_single_option_removed": True,
        "requires_positive_after_any_single_market_removed": True,
        "requires_all_four_full_chronological_blocks_positive": True,
    }
    assert result["failed_requirements"] == []


def test_replacement_exit_readiness_reports_every_failed_requirement() -> None:
    result = prospective_replacement_exit_readiness(
        _robustness(
            exact_options=12,
            total_pnl="-1",
            profit_factor="0.8",
            gross_profit="4",
            gross_loss_abs="5",
            option_leave_one_positive=False,
            market_leave_one_positive=False,
            full_blocks=3,
            all_blocks_positive=False,
        )
    )

    assert result["ready_for_review"] is False
    assert result["failed_requirements"] == [
        "minimum_exact_options",
        "positive_total_exact_pnl",
        "profit_factor_above_one",
        "positive_after_any_single_option_removed",
        "positive_after_any_single_market_removed",
        "all_four_full_chronological_blocks_positive",
    ]
    assert result["missing_exact_options"] == 18


def test_replacement_exit_readiness_accepts_zero_loss_as_infinite_profit_factor() -> None:
    result = prospective_replacement_exit_readiness(
        _robustness(
            profit_factor=None,
            gross_profit="12",
            gross_loss_abs="0",
        )
    )

    assert result["ready_for_review"] is True
    assert result["profit_factor"] is None
    assert result["profit_factor_above_one"] is True


def test_replacement_exit_readiness_rejects_inconsistent_economics() -> None:
    try:
        prospective_replacement_exit_readiness(
            _robustness(
                total_pnl="12",
                profit_factor="2",
                gross_profit="20",
                gross_loss_abs="10",
            )
        )
    except ProspectiveReplacementExitReadinessError as exc:
        assert "does not reconcile" in str(exc)
    else:
        raise AssertionError("inconsistent robustness economics must fail closed")
