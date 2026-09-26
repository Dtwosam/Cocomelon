from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathError,
    ContinuousPaperTradePathStore,
    continuous_paper_trade_path,
)

MARKET = MarketId("", "SOL")


def _trade() -> TradeJournalEntry:
    return TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        feature_snapshot_id="feature-1",
        strategy_decision_id="strategy-1",
        risk_decision_id="risk-1",
        opening_plan_id="plan-open",
        opening_attempt_id="attempt-open",
        exit_plan_ids=("plan-close",),
        exit_attempt_ids=("attempt-close",),
        fill_ids=("fill-open", "fill-close"),
        position_action_ids=("action-close",),
        funding_event_ids=(),
        initial_stop=Decimal("95"),
        initial_risk_amount=Decimal("25"),
        entry_price=Decimal("100"),
        exit_price=Decimal("102"),
        filled_quantity=Decimal("10"),
        gross_realized_pnl=Decimal("20"),
        entry_fees=Decimal("0.45"),
        exit_fees=Decimal("0.459"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("19.091"),
        entry_slippage_amount=Decimal("1"),
        exit_slippage_amount=Decimal("2"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.002"),
        holding_duration_ms=1_000,
        mfe=None,
        mae=None,
        net_r=Decimal("0.76364"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10019.091"),
        exit_reason="exit_thesis",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _mark(
    available_at_ms: int,
    mark_px: str,
    event_key: str,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=available_at_ms,
        source="hyperliquid-mainnet",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=available_at_ms - 1,
        event_key=event_key,
        payload_json=f'{{"mark_px":"{mark_px}"}}',
        event_kind="activeAssetCtx",
    )


def test_trade_path_preserves_ordered_mark_sequence() -> None:
    path = continuous_paper_trade_path(
        _trade(),
        (
            _mark(1_500, "103", "mark-2"),
            _mark(1_200, "101", "mark-1"),
        ),
        ((1_700, 1_750),),
    )

    assert path.trade_id == _trade().trade_id
    assert tuple(mark.event_key for mark in path.marks) == (
        "mark-1",
        "mark-2",
    )
    assert tuple(mark.mark_px for mark in path.marks) == (
        Decimal("101"),
        Decimal("103"),
    )
    assert path.known_gap_intervals == ((1_700, 1_750),)
    assert path.excursion_complete is False
    assert path.path_complete is False


def test_trade_path_store_is_idempotent_and_conflict_detecting(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    path = continuous_paper_trade_path(
        _trade(),
        (_mark(1_200, "101", "mark-1"),),
        (),
    )

    assert store.record(path) is True
    assert store.record(path) is False
    assert store.record_count == 1
    assert len(store.state_digest) == 64

    conflict = replace(
        path,
        marks=(
            replace(
                path.marks[0],
                mark_px=Decimal("101.5"),
            ),
        ),
    )
    with pytest.raises(
        ContinuousPaperTradePathError,
        match="CONTINUOUS_PAPER_TRADE_PATH_CONFLICT",
    ):
        store.record(conflict)


def test_trade_path_rejects_mark_outside_lifecycle() -> None:
    with pytest.raises(ValueError, match="outside lifecycle"):
        continuous_paper_trade_path(
            _trade(),
            (_mark(2_001, "101", "mark-late"),),
            (),
        )
