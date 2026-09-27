from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.opening_fill_liquidity import (
    OpeningFillLiquidityError,
    OpeningFillLiquidityEvidence,
    OpeningFillLiquidityStore,
    opening_fill_liquidity_attribution,
)

MARKET = MarketId("", "SOL")
ZERO = Decimal("0")


def _evidence(
    *,
    plan_id: str,
    direction: Direction,
    opened_at_ms: int,
    spread_bps: str,
    slippage_bps: str,
    imbalance: str,
) -> OpeningFillLiquidityEvidence:
    return OpeningFillLiquidityEvidence(
        opening_plan_id=plan_id,
        strategy_decision_id=f"strategy-{plan_id}",
        feature_snapshot_id=f"feature-{plan_id}",
        market=MARKET.canonical,
        direction=direction.value,
        opened_at_ms=opened_at_ms,
        attempt_timestamp_ms=opened_at_ms,
        book_event_key=f"book-{plan_id}",
        book_exchange_ms=opened_at_ms,
        book_received_ms=opened_at_ms,
        book_exchange_age_ms=0,
        book_receive_age_ms=0,
        spread_bps=Decimal(spread_bps),
        bid_depth_25bps=Decimal("90000"),
        ask_depth_25bps=Decimal("110000"),
        book_imbalance=Decimal(imbalance),
        mid_px=Decimal("100"),
        entry_side_depth_25bps=(
            Decimal("110000")
            if direction is Direction.LONG
            else Decimal("90000")
        ),
        exit_side_depth_25bps=(
            Decimal("90000")
            if direction is Direction.LONG
            else Decimal("110000")
        ),
        requested_quantity=Decimal("1"),
        filled_quantity=Decimal("1"),
        gross_fill_notional=Decimal("100"),
        average_fill_price=(
            Decimal("100.1")
            if direction is Direction.LONG
            else Decimal("99.9")
        ),
        fill_slippage_bps=Decimal(slippage_bps),
        entry_depth_usage_fraction=Decimal("0.001"),
        decision_spread_bps=Decimal("2"),
        decision_book_age_ms=10,
    )


def _trade(
    evidence: OpeningFillLiquidityEvidence,
    *,
    pnl: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    quantity = evidence.filled_quantity
    if evidence.direction == Direction.LONG.value:
        direction = Direction.LONG
        exit_price = evidence.average_fill_price + net / quantity
        stop = evidence.average_fill_price - Decimal("5")
    else:
        direction = Direction.SHORT
        exit_price = evidence.average_fill_price - net / quantity
        stop = evidence.average_fill_price + Decimal("5")
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=evidence.opened_at_ms,
        closed_at_ms=evidence.opened_at_ms + 60_000,
        feature_snapshot_id=evidence.feature_snapshot_id,
        strategy_decision_id=evidence.strategy_decision_id,
        risk_decision_id=f"risk-{evidence.opening_plan_id}",
        opening_plan_id=evidence.opening_plan_id,
        opening_attempt_id=f"attempt-{evidence.opening_plan_id}",
        exit_plan_ids=(f"exit-plan-{evidence.opening_plan_id}",),
        exit_attempt_ids=(f"exit-attempt-{evidence.opening_plan_id}",),
        fill_ids=(
            f"open-fill-{evidence.opening_plan_id}",
            f"close-fill-{evidence.opening_plan_id}",
        ),
        position_action_ids=(f"action-{evidence.opening_plan_id}",),
        funding_event_ids=(),
        initial_stop=stop,
        initial_risk_amount=Decimal("10"),
        entry_price=evidence.average_fill_price,
        exit_price=exit_price,
        filled_quantity=quantity,
        gross_realized_pnl=net,
        entry_fees=ZERO,
        exit_fees=ZERO,
        funding_cash_pnl=ZERO,
        net_pnl=net,
        entry_slippage_amount=ZERO,
        exit_slippage_amount=ZERO,
        entry_slippage_fraction=ZERO,
        exit_slippage_fraction=ZERO,
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def test_store_is_idempotent_and_conflict_detecting(
    tmp_path: Path,
) -> None:
    store = OpeningFillLiquidityStore(tmp_path / "liquidity")
    evidence = _evidence(
        plan_id="plan-1",
        direction=Direction.LONG,
        opened_at_ms=1_000,
        spread_bps="2",
        slippage_bps="1",
        imbalance="0.2",
    )

    assert store.record(evidence) is True
    assert store.record(evidence) is False
    assert store.load("plan-1") == evidence
    assert store.record_count == 1
    assert len(store.state_digest) == 64

    with pytest.raises(
        OpeningFillLiquidityError,
        match="OPENING_FILL_LIQUIDITY_CONFLICT",
    ):
        store.record(
            replace(
                evidence,
                spread_bps=Decimal("3"),
            )
        )


def test_attribution_compares_winners_losers_and_directional_imbalance(
    tmp_path: Path,
) -> None:
    store = OpeningFillLiquidityStore(tmp_path / "liquidity")
    winner_evidence = _evidence(
        plan_id="winner",
        direction=Direction.LONG,
        opened_at_ms=1_000,
        spread_bps="1",
        slippage_bps="0.5",
        imbalance="0.4",
    )
    loser_evidence = _evidence(
        plan_id="loser",
        direction=Direction.SHORT,
        opened_at_ms=2_000,
        spread_bps="5",
        slippage_bps="2",
        imbalance="0.6",
    )
    store.record(winner_evidence)
    store.record(loser_evidence)

    payload = opening_fill_liquidity_attribution(
        (
            _trade(winner_evidence, pnl="5"),
            _trade(loser_evidence, pnl="-4"),
        ),
        store,
    )

    assert payload["evidence_source"] == "exact_opening_ioc_l2_book"
    assert payload["evidence_records"] == 2
    assert payload["attributed_closed_trades"] == 2
    assert payload["closed_trades_without_fill_liquidity_evidence"] == 0
    assert payload["unmatched_open_or_pending_records"] == 0
    assert payload["ready_for_review"] is False
    assert payload["still_needed_closed_trades"] == 28

    winners = payload["winners"]
    losers = payload["losers"]
    sides = payload["by_side"]
    assert isinstance(winners, dict)
    assert isinstance(losers, dict)
    assert isinstance(sides, dict)
    assert winners["mean_spread_bps"] == "1"
    assert losers["mean_spread_bps"] == "5"
    assert winners["mean_fill_slippage_bps"] == "0.5"
    assert losers["mean_fill_slippage_bps"] == "2"
    assert winners["mean_directional_book_imbalance"] == "0.4"
    assert losers["mean_directional_book_imbalance"] == "-0.6"
    assert sides["long"]["net_pnl"] == "5"
    assert sides["short"]["net_pnl"] == "-4"


def test_attribution_keeps_historical_trades_explicitly_unmatched(
    tmp_path: Path,
) -> None:
    store = OpeningFillLiquidityStore(tmp_path / "liquidity")
    evidence = _evidence(
        plan_id="prospective",
        direction=Direction.LONG,
        opened_at_ms=2_000,
        spread_bps="2",
        slippage_bps="1",
        imbalance="0",
    )
    store.record(evidence)

    historical = replace(
        _trade(evidence, pnl="1"),
        opening_plan_id="historical-plan",
        strategy_decision_id="historical-strategy",
        feature_snapshot_id="historical-feature",
    )
    payload = opening_fill_liquidity_attribution(
        (historical,),
        store,
    )

    assert payload["attributed_closed_trades"] == 0
    assert payload["closed_trades_without_fill_liquidity_evidence"] == 1
    assert payload["unmatched_open_or_pending_records"] == 1
