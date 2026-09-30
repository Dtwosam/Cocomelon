from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.research.profit_lock_counterfactual import (
    DEFAULT_PROFIT_LOCK_RULES,
    ProfitLockTradeOutcome,
)
from cocomelon.research.prospective_allowed_residual import AllowedResidualItem

ZERO: Final = Decimal("0")


class ProspectiveResidualProfitLockError(RuntimeError):
    pass


def _mfe_r(item: AllowedResidualItem) -> Decimal | None:
    mfe = item.trade.mfe
    if (
        mfe is None
        or not mfe.complete
        or mfe.r_multiple is None
    ):
        return None
    return mfe.r_multiple


def _leave_one_out_robustness(
    values: tuple[Decimal, ...],
) -> dict[str, object]:
    total = sum(values, ZERO)
    leave_one_out = tuple(total - value for value in values)
    minimum = min(leave_one_out, default=ZERO)
    return {
        "total_delta": str(total),
        "leave_one_loss_out_min_delta": str(minimum),
        "positive_after_removing_any_one_loss": (
            len(values) >= 2 and minimum > ZERO
        ),
    }


def prospective_residual_profit_lock_summary(
    items: Sequence[AllowedResidualItem],
    outcomes: Sequence[ProfitLockTradeOutcome],
) -> dict[str, object]:
    values = tuple(items)
    residual_losses = tuple(
        item for item in values if item.trade.net_pnl < ZERO
    )
    loss_by_id = {
        item.trade.trade_id: item
        for item in residual_losses
    }
    if len(loss_by_id) != len(residual_losses):
        raise ProspectiveResidualProfitLockError(
            "allowed residual losses contain duplicate trade ids"
        )

    outcome_values = tuple(outcomes)
    outcome_keys = tuple(
        (outcome.rule_id, outcome.trade_id)
        for outcome in outcome_values
    )
    if len(set(outcome_keys)) != len(outcome_keys):
        raise ProspectiveResidualProfitLockError(
            "profit-lock outcomes contain duplicate rule/trade ids"
        )

    rule_ids = tuple(
        rule.rule_id for rule in DEFAULT_PROFIT_LOCK_RULES
    )
    unexpected_rule_ids = sorted(
        {
            outcome.rule_id
            for outcome in outcome_values
            if outcome.rule_id not in rule_ids
        }
    )
    if unexpected_rule_ids:
        raise ProspectiveResidualProfitLockError(
            "profit-lock outcomes contain unsupported rules"
        )

    complete_mfe_losses = tuple(
        item for item in residual_losses if _mfe_r(item) is not None
    )
    giveback_losses = tuple(
        item
        for item in complete_mfe_losses
        if (_mfe_r(item) or ZERO) >= Decimal("0.5")
    )
    deep_giveback_losses = tuple(
        item
        for item in complete_mfe_losses
        if (_mfe_r(item) or ZERO) >= Decimal("1")
    )

    by_rule: dict[str, dict[str, object]] = {}
    for rule_id in rule_ids:
        matched = tuple(
            outcome
            for outcome in outcome_values
            if outcome.rule_id == rule_id
            and outcome.trade_id in loss_by_id
        )
        for outcome in matched:
            trade = loss_by_id[outcome.trade_id].trade
            if (
                outcome.market != trade.market.canonical
                or outcome.direction != trade.direction.value
                or outcome.actual_net_pnl != trade.net_pnl
                or outcome.actual_net_r != trade.net_r
            ):
                raise ProspectiveResidualProfitLockError(
                    "profit-lock outcome does not match residual trade"
                )

        matched_by_id = {
            outcome.trade_id: outcome for outcome in matched
        }
        giveback_matched = tuple(
            matched_by_id[item.trade.trade_id]
            for item in giveback_losses
            if item.trade.trade_id in matched_by_id
        )
        deep_matched = tuple(
            matched_by_id[item.trade.trade_id]
            for item in deep_giveback_losses
            if item.trade.trade_id in matched_by_id
        )

        actual_pnl = sum(
            (outcome.actual_net_pnl for outcome in matched),
            ZERO,
        )
        candidate_pnl = sum(
            (
                outcome.candidate_net_pnl_estimate
                for outcome in matched
            ),
            ZERO,
        )
        actual_r = sum(
            (outcome.actual_net_r for outcome in matched),
            ZERO,
        )
        candidate_r = sum(
            (
                outcome.candidate_net_r_estimate
                for outcome in matched
            ),
            ZERO,
        )
        pnl_deltas = tuple(
            outcome.delta_net_pnl_estimate
            for outcome in matched
        )
        r_deltas = tuple(
            outcome.delta_net_r_estimate
            for outcome in matched
        )

        by_rule[rule_id] = {
            "residual_loss_trades": len(residual_losses),
            "matched_exact_path_losses": len(matched),
            "missing_exact_path_losses": (
                len(residual_losses) - len(matched)
            ),
            "exact_path_coverage_complete": (
                len(matched) == len(residual_losses)
            ),
            "activated_losses": sum(
                1 for outcome in matched if outcome.activated
            ),
            "triggered_losses": sum(
                1 for outcome in matched if outcome.triggered
            ),
            "rescued_to_nonnegative": sum(
                1
                for outcome in matched
                if outcome.candidate_net_pnl_estimate >= ZERO
            ),
            "worsened_losses": sum(
                1
                for outcome in matched
                if outcome.candidate_net_pnl_estimate
                < outcome.actual_net_pnl
            ),
            "actual_net_pnl": str(actual_pnl),
            "candidate_net_pnl_estimate": str(candidate_pnl),
            "delta_net_pnl_estimate": str(
                candidate_pnl - actual_pnl
            ),
            "actual_net_r_sum": str(actual_r),
            "candidate_net_r_estimate_sum": str(candidate_r),
            "delta_net_r_estimate_sum": str(
                candidate_r - actual_r
            ),
            "pnl_robustness": _leave_one_out_robustness(
                pnl_deltas
            ),
            "net_r_robustness": _leave_one_out_robustness(
                r_deltas
            ),
            "giveback_losses": len(giveback_losses),
            "giveback_matched_exact_paths": len(giveback_matched),
            "giveback_triggered_losses": sum(
                1 for outcome in giveback_matched
                if outcome.triggered
            ),
            "giveback_delta_net_pnl_estimate": str(
                sum(
                    (
                        outcome.delta_net_pnl_estimate
                        for outcome in giveback_matched
                    ),
                    ZERO,
                )
            ),
            "giveback_delta_net_r_estimate": str(
                sum(
                    (
                        outcome.delta_net_r_estimate
                        for outcome in giveback_matched
                    ),
                    ZERO,
                )
            ),
            "deep_giveback_losses": len(deep_giveback_losses),
            "deep_giveback_matched_exact_paths": len(deep_matched),
            "deep_giveback_triggered_losses": sum(
                1 for outcome in deep_matched
                if outcome.triggered
            ),
            "deep_giveback_delta_net_pnl_estimate": str(
                sum(
                    (
                        outcome.delta_net_pnl_estimate
                        for outcome in deep_matched
                    ),
                    ZERO,
                )
            ),
        }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "allowed_trades": len(values),
        "residual_loss_trades": len(residual_losses),
        "complete_mfe_residual_losses": len(complete_mfe_losses),
        "giveback_residual_losses": len(giveback_losses),
        "deep_giveback_residual_losses": len(deep_giveback_losses),
        "by_rule": by_rule,
    }
