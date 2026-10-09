from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from cocomelon.research.profit_lock_counterfactual import (
    DEFAULT_PROFIT_LOCK_RULES,
)
from cocomelon.research.profit_lock_execution_shadow import (
    EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
)
from cocomelon.research.prospective_early_reserved_trailing import (
    prospective_early_reserved_trailing_comparison,
)
from cocomelon.research.prospective_profit_target_one_r_comparison import (
    EARLY_RESERVED_TRAILING_RULE_ID,
    ProspectiveProfitTargetComparisonError,
    _verified_outcomes,
)


def _state(*, early: bool, start: int = 2000) -> dict[str, object]:
    if early:
        rules = [{
            "rule_id": EARLY_RESERVED_TRAILING_RULE_ID,
            "activate_at_r": "0.5",
            "lock_at_r": "0.1",
            "trail_by_r": "0.4",
            "minimum_estimated_net_lock_r": "0.05",
        }]
    else:
        rules = [
            {
                "rule_id": rule.rule_id,
                "activate_at_r": str(rule.activate_at_r),
                "lock_at_r": str(rule.lock_at_r),
            }
            for rule in DEFAULT_PROFIT_LOCK_RULES
        ]
    return {
        "schema_version": EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
        "started_at_ms": start,
        "rules": rules,
        "outcomes": [],
        "lineage_mismatch_closed_trades": 0,
        "orphaned_restored_positions": 0,
        "execution_config": {"same_real_execution_cost_configuration": True},
    }


def test_early_net_reserved_trailing_identity_and_future_empty_sample() -> None:
    state = _state(early=True)
    start, outcomes, integrity = _verified_outcomes(
        state, rule_id=EARLY_RESERVED_TRAILING_RULE_ID
    )
    assert start == 2000
    assert outcomes == {}
    assert integrity["lineage_mismatch_closed_trades"] == 0
    result = prospective_early_reserved_trailing_comparison(
        (), state, _state(early=False, start=1000)
    )
    assert result["candidate_id"] == EARLY_RESERVED_TRAILING_RULE_ID
    assert result["frozen_start_ms"] == 2000
    assert result["matched_trades"] == 0
    assert result["economic_screen_passes"] is False
    assert result["ready_for_review"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
    assert result["not_an_independent_portfolio_trial"] is True


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("activate_at_r", "1"),
        ("lock_at_r", "0"),
        ("trail_by_r", "0.5"),
        ("minimum_estimated_net_lock_r", "0"),
        ("rule_id", "another_rule"),
    ),
)
def test_rule_hyperparameters_are_frozen(
    name: str,
    value: str,
) -> None:
    state = deepcopy(_state(early=True))
    rules = state["rules"]
    assert isinstance(rules, list)
    rules[0][name] = value
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="frozen exit rule identity drift",
    ):
        _verified_outcomes(state, rule_id=EARLY_RESERVED_TRAILING_RULE_ID)


def test_missing_shadow_fills_are_not_counted_as_profitable() -> None:
    trade = SimpleNamespace(
        trade_id="prospective-trade",
        opened_at_ms=2500,
        closed_at_ms=3000,
    )
    report = prospective_early_reserved_trailing_comparison(
        (trade,), _state(early=True), _state(early=False)
    )
    assert report["prospective_closed_trades"] == 1
    assert report["matched_trades"] == 0
    assert report["missing_target_trade_ids"] == ["prospective-trade"]
    assert report["missing_breakeven_trade_ids"] == ["prospective-trade"]
    assert report["integrity_clean"] is False
    assert report["economic_screen_passes"] is False
    assert report["overall"]["target_net_pnl"] == "0"


def test_missing_or_drifting_execution_configuration_fails_closed() -> None:
    state = _state(early=True)
    baseline = _state(early=False)
    baseline["execution_config"] = {"different_cost_model": True}
    with pytest.raises(
        ProspectiveProfitTargetComparisonError,
        match="execution cost/config drift",
    ):
        prospective_early_reserved_trailing_comparison(
            (), state, baseline
        )
