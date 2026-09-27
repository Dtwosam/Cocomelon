from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fill_capacity import (
    delayed_entry_fill_capacity_summary,
)

MARKET = MarketId("", "SOL")


def _trade(
    trade_id: str,
    *,
    direction: Direction,
    quantity: str = "2",
) -> SimpleNamespace:
    return SimpleNamespace(
        trade_id=trade_id,
        opening_plan_id=f"plan-{trade_id}",
        market=MARKET,
        direction=direction,
        filled_quantity=Decimal(quantity),
    )


def _outcome(
    trade_id: str,
    *,
    direction: str,
    source: str,
    filled: str,
    reason: str | None,
) -> DelayedEntryOutcome:
    return DelayedEntryOutcome(
        trade_id=trade_id,
        opening_plan_id=f"plan-{trade_id}",
        market=MARKET.canonical,
        direction=direction,
        source=source,
        delayed_filled_quantity=Decimal(filled),
        delayed_average_fill_price=(
            None if Decimal(filled) == 0 else Decimal("99")
        ),
        delayed_fee=Decimal("0"),
        observation_lag_ms=300,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
        attempt_reason=reason,
    )


def test_fill_capacity_attributes_partial_causes_and_side() -> None:
    trades = (
        _trade("long-depth", direction=Direction.LONG),
        _trade("long-risk", direction=Direction.LONG),
        _trade("short-full", direction=Direction.SHORT),
    )
    journal = SimpleNamespace(iter_trades=lambda: iter(trades))
    outcomes = (
        _outcome(
            "long-depth",
            direction="long",
            source="partial_visible_book_ioc",
            filled="1",
            reason="IOC_REMAINDER_CANCELLED",
        ),
        _outcome(
            "long-risk",
            direction="long",
            source="partial_visible_book_ioc",
            filled="0.5",
            reason="IOC_REMAINDER_CANCELLED,RISK_CEILING_REACHED",
        ),
        _outcome(
            "short-full",
            direction="short",
            source="full_visible_book_ioc",
            filled="2",
            reason="FILLED_VISIBLE_DEPTH",
        ),
    )

    result = delayed_entry_fill_capacity_summary(
        journal,  # type: ignore[arg-type]
        outcomes,
    )

    assert result["evaluated_attempts"] == 3
    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["full"] == 1
    assert overall["partial"] == 2
    assert overall["mean_fill_fraction"] == "0.5833333333333333333333333333"
    causes = result["by_cause"]
    assert isinstance(causes, dict)
    assert causes["visible_depth_or_slippage_boundary"]["attempts"] == 1
    assert causes["risk_ceiling_clip"]["attempts"] == 1
    assert causes["full_fill"]["attempts"] == 1
    by_side = result["by_side"]
    assert isinstance(by_side, dict)
    assert by_side["long"]["mean_fill_fraction"] == "0.375"
    assert by_side["short"]["mean_fill_fraction"] == "1"
    assert result["cause_known_partial_fills"] == 2
    assert result["legacy_unknown_partial_fills"] == 0


def test_fill_capacity_marks_old_partials_unknown_without_guessing() -> None:
    trade = _trade("legacy", direction=Direction.LONG)
    journal = SimpleNamespace(iter_trades=lambda: iter((trade,)))
    outcome = _outcome(
        "legacy",
        direction="long",
        source="partial_visible_book_ioc",
        filled="1",
        reason=None,
    )

    result = delayed_entry_fill_capacity_summary(
        journal,  # type: ignore[arg-type]
        (outcome,),
    )

    assert result["cause_known_partial_fills"] == 0
    assert result["legacy_unknown_partial_fills"] == 1
    causes = result["by_cause"]
    assert isinstance(causes, dict)
    assert causes["legacy_unknown_partial"]["attempts"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False
