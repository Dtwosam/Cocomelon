from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePath,
    ContinuousPaperTradePathMark,
    ContinuousPaperTradePathStore,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_stop_l2_replay import (
    delayed_entry_stop_l2_replay,
)
from cocomelon.research.original_stop_book_evidence import (
    OriginalStopBookEvidenceStore,
    OriginalStopCrossing,
)

MARKET = MarketId("", "SOL")
CAPTURE_START_MS = 90_000


def _trade(
    *,
    suffix: str,
    opened_at_ms: int = 100_000,
) -> TradeJournalEntry:
    return TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        closed_at_ms=400_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(
            f"fill-open-{suffix}",
            f"fill-exit-{suffix}",
        ),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=Decimal("10"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("10"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=400_000 - opened_at_ms,
        mfe=None,
        mae=None,
        net_r=Decimal("1"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10010"),
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _path(
    trade: TradeJournalEntry,
    marks: tuple[tuple[int, str], ...],
) -> ContinuousPaperTradePath:
    return ContinuousPaperTradePath(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        opened_at_ms=trade.opened_at_ms,
        closed_at_ms=trade.closed_at_ms,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        initial_stop=trade.initial_stop,
        initial_risk_amount=trade.initial_risk_amount,
        filled_quantity=trade.filled_quantity,
        excursion_complete=True,
        health_refs=trade.health_refs,
        marks=tuple(
            ContinuousPaperTradePathMark(
                available_at_ms=timestamp_ms,
                exchange_time_ms=timestamp_ms,
                event_key=(
                    f"{trade.trade_id}-{timestamp_ms}"
                ),
                mark_px=Decimal(mark_px),
            )
            for timestamp_ms, mark_px in marks
        ),
        known_gap_intervals=(),
    )


def _outcome(
    trade: TradeJournalEntry,
) -> DelayedEntryOutcome:
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source="full_visible_book_ioc",
        delayed_filled_quantity=Decimal("1"),
        delayed_average_fill_price=Decimal("100"),
        delayed_fee=Decimal("0"),
        observation_lag_ms=0,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
        attempt_reason=None,
        capacity_cause=None,
    )


def _instrument(
    *,
    metadata_ms: int = 90_000,
) -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=1,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=metadata_ms,
        metadata_source=f"meta-{metadata_ms}",
    )


def _book(
    *,
    receive_ms: int,
    bid_size: str,
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=receive_ms - 1,
        receive_time=datetime.fromtimestamp(
            receive_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"book:{receive_ms}",
        payload={
            "bids": (
                {
                    "px": Decimal("89"),
                    "sz": Decimal(bid_size),
                    "n": 1,
                },
            ),
            "asks": (
                {
                    "px": Decimal("89.1"),
                    "sz": Decimal("10"),
                    "n": 1,
                },
            ),
        },
    )


def _stop_books(
    root: Path,
    *,
    started_at_ms: int = CAPTURE_START_MS,
) -> OriginalStopBookEvidenceStore:
    return OriginalStopBookEvidenceStore(
        root,
        started_at_ms=started_at_ms,
    )


def _capture_stop_book(
    root: Path,
    trade: TradeJournalEntry,
    *,
    crossing_ms: int = 170_000,
    bid_size: str = "2",
    execution_metadata_ms: int = 90_000,
) -> OriginalStopBookEvidenceStore:
    store = _stop_books(root)
    crossing = OriginalStopCrossing(
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        opened_at_ms=trade.opened_at_ms,
        original_stop=trade.initial_stop,
        crossing_mark_event_key=(
            f"{trade.trade_id}-{crossing_ms}"
        ),
        crossing_mark_price=Decimal("89"),
        crossing_mark_received_ms=crossing_ms,
        crossing_mark_exchange_ms=crossing_ms,
    )
    assert store.stage(crossing) is True
    pending = store.pending_for(trade.opening_plan_id)
    assert pending is not None
    pending = store.stage_plan(
        pending,
        _book(
            receive_ms=crossing_ms + 100,
            bid_size="2",
        ),
        reference_price=Decimal("89.05"),
        instrument=_instrument(),
    )
    assert store.capture_execution_book(
        pending,
        _book(
            receive_ms=crossing_ms + 300,
            bid_size=bid_size,
        ),
        _instrument(
            metadata_ms=execution_metadata_ms
        ),
    ) is True
    return store


def _funding_loader(
    _market: MarketId,
    _start_ms: int,
):
    return ()


def _config() -> PaperExecutionConfig:
    return PaperExecutionConfig(
        latency_ms=250,
        max_ioc_slippage_bps=Decimal("25"),
        taker_fee_rate=Decimal("0.00045"),
    )


def test_exact_l2_replay_uses_manager_triggered_full_stop_fill(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    try:
        trade = _trade(suffix="full")
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                ((170_000, "89"), (300_000, "100")),
            )
        )
        books = _capture_stop_book(
            tmp_path / "stop-books",
            trade,
        )

        result = delayed_entry_stop_l2_replay(
            journal,
            (_outcome(trade),),
            paths,
            books,
            _funding_loader,
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["captured_stop_plans"] == 1
    assert overall["full_stop_exits"] == 1
    assert overall["unresolved_stop_actions"] == 0
    assert Decimal(
        str(overall["exact_pnl_on_full_stop_exits"])
    ) == Decimal("-11.04005")
    assert Decimal(
        str(
            overall[
                "same_exit_minus_exact_on_full_stop_exits"
            ]
        )
    ) == Decimal("21.04005")


def test_transient_mark_crossing_without_plan_keeps_same_exit(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    books = _stop_books(tmp_path / "stop-books")
    try:
        trade = _trade(suffix="transient")
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (170_000, "89"),
                    (175_000, "95"),
                    (300_000, "100"),
                ),
            )
        )
        result = delayed_entry_stop_l2_replay(
            journal,
            (_outcome(trade),),
            paths,
            books,
            _funding_loader,
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert (
        overall[
            "transient_mark_crossings_without_stop_plan"
        ]
        == 1
    )
    assert overall["resolved_candidates"] == 1
    assert overall["resolved_candidate_net_pnl"] == "10"


def test_later_manager_trigger_can_follow_earlier_transient_crossing(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    try:
        trade = _trade(suffix="later")
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (170_000, "89"),
                    (175_000, "95"),
                    (180_000, "89"),
                    (300_000, "100"),
                ),
            )
        )
        books = _capture_stop_book(
            tmp_path / "stop-books",
            trade,
            crossing_ms=180_000,
        )
        result = delayed_entry_stop_l2_replay(
            journal,
            (_outcome(trade),),
            paths,
            books,
            _funding_loader,
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["mark_stop_crossings"] == 1
    assert overall["captured_stop_plans"] == 1
    assert overall["full_stop_exits"] == 1
    assert result["lineage_mismatches"] == 0


def test_partial_stop_ioc_does_not_invent_remainder_exit(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    try:
        trade = _trade(suffix="partial")
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                ((170_000, "89"), (300_000, "100")),
            )
        )
        books = _capture_stop_book(
            tmp_path / "stop-books",
            trade,
            bid_size="0.4",
        )
        result = delayed_entry_stop_l2_replay(
            journal,
            (_outcome(trade),),
            paths,
            books,
            _funding_loader,
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["partial_stop_exits"] == 1
    assert overall["resolved_candidates"] == 0
    assert overall["unresolved_stop_actions"] == 1
    assert overall["exact_pnl_on_full_stop_exits"] == "0"


def test_instrument_version_drift_is_execution_rejection(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    try:
        trade = _trade(suffix="drift")
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                ((170_000, "89"), (300_000, "100")),
            )
        )
        books = _capture_stop_book(
            tmp_path / "stop-books",
            trade,
            execution_metadata_ms=90_001,
        )
        result = delayed_entry_stop_l2_replay(
            journal,
            (_outcome(trade),),
            paths,
            books,
            _funding_loader,
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert (
        overall["planning_or_execution_rejections"]
        == 1
    )
    assert overall["resolved_candidates"] == 0


def test_pre_capture_trade_is_excluded_not_called_missing(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    books = _stop_books(
        tmp_path / "stop-books",
        started_at_ms=110_000,
    )
    try:
        trade = _trade(
            suffix="legacy",
            opened_at_ms=100_000,
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                ((170_000, "89"), (300_000, "100")),
            )
        )
        result = delayed_entry_stop_l2_replay(
            journal,
            (_outcome(trade),),
            paths,
            books,
            _funding_loader,
            _config(),
        )
    finally:
        journal.close()

    assert result["pre_capture_legacy_outcomes"] == 1
    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["evaluated_filled_candidates"] == 0


def test_capture_error_makes_missing_stop_plan_unresolved(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    books = _stop_books(tmp_path / "stop-books")
    try:
        trade = _trade(suffix="capture-error")
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                ((170_000, "89"), (300_000, "100")),
            )
        )
        result = delayed_entry_stop_l2_replay(
            journal,
            (_outcome(trade),),
            paths,
            books,
            _funding_loader,
            _config(),
            capture_error="fixture capture failure",
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["stop_capture_unreliable"] == 1
    assert overall["unresolved_stop_actions"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["integrity_clean"] is False


def test_no_mark_crossing_is_observed_path_survivor(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    books = _stop_books(tmp_path / "stop-books")
    try:
        trade = _trade(suffix="survivor")
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                ((170_000, "95"), (300_000, "100")),
            )
        )
        result = delayed_entry_stop_l2_replay(
            journal,
            (_outcome(trade),),
            paths,
            books,
            _funding_loader,
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["observed_path_survivors"] == 1
    assert overall["mark_stop_crossings"] == 0
    assert overall["resolved_candidates"] == 1
