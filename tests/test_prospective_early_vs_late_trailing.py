from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research import prospective_early_vs_late_trailing as audit
from cocomelon.research.prospective_profit_target_one_r_comparison import (
    EARLY_RESERVED_TRAILING_RULE_ID,
    NET_RESERVED_TRAILING_RULE_ID,
)


def _trade(n: int, direction: Direction = Direction.LONG) -> SimpleNamespace:
    return SimpleNamespace(
        trade_id=f"t{n}",
        market=MarketId("", "SOL" if n % 2 else "BTC"),
        direction=direction,
        opening_plan_id=f"plan-{n}",
        opened_at_ms=1000 + n * 10,
        closed_at_ms=3000 + n * 10,
        net_pnl=Decimal("-1"),
        net_r=Decimal("-0.1"),
        filled_quantity=Decimal("2"),
    )


def _outcome(
    trade: SimpleNamespace,
    candidate_pnl: str,
    *,
    incomplete: bool = False,
) -> SimpleNamespace:
    value = Decimal(candidate_pnl)
    return SimpleNamespace(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        opening_plan_id=trade.opening_plan_id,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        candidate_net_pnl_estimate=value,
        candidate_net_r_estimate=value / Decimal("10"),
        triggered=True,
        candidate_source="visible_book_ioc",
        simulated_close_complete=not incomplete,
        simulated_filled_quantity=trade.filled_quantity,
        simulated_average_exit_price=Decimal("10"),
        attempt_count=1,
        trigger_timestamp_ms=trade.opened_at_ms + 50,
        completion_timestamp_ms=trade.opened_at_ms + 100,
    )


def _patch_evidence(
    monkeypatch: pytest.MonkeyPatch,
    early: dict[str, SimpleNamespace],
    late: dict[str, SimpleNamespace],
    *,
    cost_drift: bool = False,
) -> None:
    def verified(
        _: object,
        *,
        rule_id: str,
    ) -> tuple[int, dict[str, SimpleNamespace], dict[str, object]]:
        if rule_id == EARLY_RESERVED_TRAILING_RULE_ID:
            outcomes = early
            config = "same_config"
        elif rule_id == NET_RESERVED_TRAILING_RULE_ID:
            outcomes = late
            config = "different_config" if cost_drift else "same_config"
        else:
            raise AssertionError("unexpected rule id")
        return 1000, outcomes, {
            "execution_config": config,
            "lineage_mismatch_closed_trades": 0,
            "orphaned_restored_positions": 0,
        }

    monkeypatch.setattr(audit, "_verified_outcomes", verified)
    monkeypatch.setattr(audit, "_verify_trade_exit_cashflow", lambda *_: None)


def test_identical_future_sample_both_directions_and_net_pnl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trades = (_trade(1), _trade(2, Direction.SHORT))
    early = {t.trade_id: _outcome(t, "2") for t in trades}
    late = {t.trade_id: _outcome(t, "0.5") for t in trades}
    _patch_evidence(monkeypatch, early, late)
    result = audit.prospective_early_vs_late_trailing(trades, {}, {})
    assert result["matched_trade_count"] == 2
    assert result["integrity_clean"] is True
    assert result["by_direction"]["long"]["early_net_pnl"] == "2"
    assert result["by_direction"]["short"]["early_net_pnl"] == "2"
    assert result["overall"]["early_vs_late_net_pnl"] == "3.0"
    assert result["overall"]["original_losers_rescued"] == 2
    assert result["sample_complete"] is False
    assert result["economic_screen_passes"] is False
    assert result["ready_for_review"] is False
    assert result["promotion_authority"] is False
    assert result["independent_portfolio_trial"] is False


def test_incomplete_one_side_does_not_claim_profitable_matched_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trades = (_trade(1), _trade(2, Direction.SHORT))
    early = {t.trade_id: _outcome(t, "2") for t in trades}
    late = {t.trade_id: _outcome(t, "0.5") for t in trades}
    early["t2"] = _outcome(trades[1], "200", incomplete=True)
    _patch_evidence(monkeypatch, early, late)
    result = audit.prospective_early_vs_late_trailing(trades, {}, {})
    assert result["matched_trade_count"] == 1
    assert result["incomplete_ioc_trade_ids"] == ["t2"]
    assert result["integrity_clean"] is False
    assert result["by_direction"]["short"]["matched_trades"] == 0
    assert result["economic_screen_passes"] is False


def test_missing_outcomes_and_cost_config_drift_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade = _trade(1)
    _patch_evidence(monkeypatch, {}, {})
    empty = audit.prospective_early_vs_late_trailing((trade,), {}, {})
    assert empty["missing_early_trade_ids"] == ["t1"]
    assert empty["missing_late_trade_ids"] == ["t1"]
    assert empty["integrity_clean"] is False
    _patch_evidence(monkeypatch, {}, {}, cost_drift=True)
    with pytest.raises(audit.EarlyVsLateTrailingError, match="configuration drift"):
        audit.prospective_early_vs_late_trailing((trade,), {}, {})


def test_duplicate_trade_and_observer_identity_drift_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade = _trade(1)
    early = {"t1": _outcome(trade, "2")}
    late = {"t1": _outcome(trade, "0.5")}
    _patch_evidence(monkeypatch, early, late)
    with pytest.raises(audit.EarlyVsLateTrailingError, match="duplicate"):
        audit.prospective_early_vs_late_trailing((trade, trade), {}, {})
    early["t1"].opening_plan_id = "different-plan"
    with pytest.raises(audit.EarlyVsLateTrailingError, match="identity mismatch"):
        audit.prospective_early_vs_late_trailing((trade,), {}, {})


def test_exit_economics_preserve_tiny_after_cost_edge_across_large_positions() -> None:
    """A small positive forward edge must not round to zero before netting."""
    rows = []
    for original, early, late in (
        ("10000", "10000", "10000"),
        ("0.000000000000000000000001", "0.000000000000000000000002", "0.000000000000000000000001"),
        ("-10000", "-10000", "-10000"),
    ):
        trade = SimpleNamespace(net_pnl=Decimal(original), net_r=Decimal(original))
        first = SimpleNamespace(
            candidate_net_pnl_estimate=Decimal(early),
            candidate_net_r_estimate=Decimal(early),
        )
        second = SimpleNamespace(
            candidate_net_pnl_estimate=Decimal(late),
            candidate_net_r_estimate=Decimal(late),
        )
        rows.append((trade, first, second))
    report = audit._economics(tuple(rows))
    assert report["original_net_pnl"] == "1E-24"
    assert report["early_net_pnl"] == "2E-24"
    assert report["late_net_pnl"] == "1E-24"
    assert report["early_vs_original_net_pnl"] == "1E-24"
    assert report["early_beats_late_and_original"] is True
    assert report["early_is_profitable"] is True
