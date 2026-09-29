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
from cocomelon.execution.funding import (
    FundingAccrual,
    funding_cash_delta,
)
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
    quantity: str = "1",
    funding: tuple[FundingAccrual, ...] = (),
) -> TradeJournalEntry:
    filled_quantity = Decimal(quantity)
    risk_amount = Decimal("10") * filled_quantity
    funding_pnl = sum(
        (item.cash_delta for item in funding),
        Decimal("0"),
    )
    net_pnl = risk_amount + funding_pnl
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
        funding_event_ids=tuple(
            item.accrual_id for item in funding
        ),
        initial_stop=Decimal("90"),
        initial_risk_amount=risk_amount,
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        filled_quantity=filled_quantity,
        gross_realized_pnl=risk_amount,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=funding_pnl,
        net_pnl=net_pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=400_000 - opened_at_ms,
        mfe=None,
        mae=None,
        net_r=net_pnl / risk_amount,
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net_pnl,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _path(
    trade: TradeJournalEntry,
    marks: tuple[tuple[int, str], ...],
    *,
    complete: bool = True,
    gaps: tuple[tuple[int, int | None], ...] = (),
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
        excursion_complete=complete,
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
        known_gap_intervals=gaps,
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
        delayed_filled_quantity=trade.filled_quantity,
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
    sz_decimals: int = 1,
) -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=sz_decimals,
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
    plan_sz_decimals: int = 1,
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
        instrument=_instrument(
            sz_decimals=plan_sz_decimals
        ),
    )
    assert store.capture_execution_book(
        pending,
        _book(
            receive_ms=crossing_ms + 300,
            bid_size=bid_size,
        ),
        _instrument(
            metadata_ms=execution_metadata_ms,
            sz_decimals=plan_sz_decimals,
        ),
    ) is True
    return store


def _funding(
    *,
    boundary_ms: int,
    received_at_ms: int,
    rate: str = "0.001",
) -> FundingAccrual:
    signed_quantity = Decimal("1")
    oracle_price = Decimal("100")
    funding_rate = Decimal(rate)
    return FundingAccrual(
        market=MARKET,
        boundary_ms=boundary_ms,
        position_id=f"position-{boundary_ms}",
        signed_quantity=signed_quantity,
        oracle_price=oracle_price,
        funding_rate=funding_rate,
        cash_delta=funding_cash_delta(
            signed_quantity,
            oracle_price,
            funding_rate,
        ),
        oracle_event_key=f"oracle-{boundary_ms}",
        funding_source="fixture",
        funding_received_at_ms=received_at_ms,
    )


def _funding_loader(
    *accruals: FundingAccrual,
):
    def load(
        market: MarketId,
        start_ms: int,
    ) -> tuple[FundingAccrual, ...]:
        return tuple(
            item
            for item in accruals
            if (
                item.market == market
                and item.boundary_ms >= start_ms
            )
        )

    return load


EMPTY_FUNDING_LOADER = _funding_loader()


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
            EMPTY_FUNDING_LOADER,
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


def test_funding_available_at_execution_is_included_before_stop(
    tmp_path: Path,
) -> None:
    accrual = _funding(
        boundary_ms=170_300,
        received_at_ms=170_300,
    )
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    try:
        trade = _trade(
            suffix="funding-at-execution",
            funding=(accrual,),
        )
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
            _funding_loader(accrual),
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert Decimal(
        str(overall["exact_pnl_on_full_stop_exits"])
    ) == Decimal("-11.14005")
    assert overall["late_funding_boundaries_excluded"] == 0


def test_funding_received_after_stop_execution_is_excluded(
    tmp_path: Path,
) -> None:
    accrual = _funding(
        boundary_ms=170_200,
        received_at_ms=170_400,
    )
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    try:
        trade = _trade(
            suffix="late-funding",
            funding=(accrual,),
        )
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
            _funding_loader(accrual),
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert Decimal(
        str(overall["exact_pnl_on_full_stop_exits"])
    ) == Decimal("-11.04005")
    assert overall["late_funding_boundaries_excluded"] == 1


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
            EMPTY_FUNDING_LOADER,
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
            EMPTY_FUNDING_LOADER,
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
            EMPTY_FUNDING_LOADER,
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


def test_full_ioc_with_quantized_position_remainder_is_unresolved(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    try:
        trade = _trade(
            suffix="quantized-remainder",
            quantity="1.5",
        )
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
            bid_size="10",
            plan_sz_decimals=0,
        )
        result = delayed_entry_stop_l2_replay(
            journal,
            (_outcome(trade),),
            paths,
            books,
            EMPTY_FUNDING_LOADER,
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert (
        overall["full_ioc_position_remainders"]
        == 1
    )
    assert overall["full_stop_exits"] == 0
    assert overall["resolved_candidates"] == 0
    assert overall["unresolved_stop_actions"] == 1


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
            EMPTY_FUNDING_LOADER,
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
            EMPTY_FUNDING_LOADER,
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
            EMPTY_FUNDING_LOADER,
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
            EMPTY_FUNDING_LOADER,
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["observed_path_survivors"] == 1
    assert overall["mark_stop_crossings"] == 0
    assert overall["resolved_candidates"] == 1



def test_post_capture_non_evaluable_entry_is_excluded_not_integrity_failure(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    books = _stop_books(tmp_path / "stop-books")
    try:
        trade = _trade(suffix="expired")
        journal.record_trade(trade)
        outcome = DelayedEntryOutcome(
            trade_id=trade.trade_id,
            opening_plan_id=trade.opening_plan_id,
            market=trade.market.canonical,
            direction=trade.direction.value,
            source="expired",
            delayed_filled_quantity=Decimal("0"),
            delayed_average_fill_price=None,
            delayed_fee=Decimal("0"),
            observation_lag_ms=None,
            signed_price_improvement_bps=None,
            gross_r_improvement=None,
            attempt_reason="NO_FRESH_BOOK_WITHIN_WINDOW",
        )
        result = delayed_entry_stop_l2_replay(
            journal,
            (outcome,),
            paths,
            books,
            EMPTY_FUNDING_LOADER,
            _config(),
        )
    finally:
        journal.close()

    assert result["source_counts"] == {"expired": 1}
    assert result["non_evaluable_entry_outcomes"] == 1
    assert result["non_evaluable_source_counts"] == {
        "expired": 1,
    }
    assert result["unresolved_outcomes"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["integrity_clean"] is True
    assert readiness["complete_counterfactual_cohort"] is True


def test_pre_capture_non_evaluable_entry_is_legacy_not_current_cohort(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "paths"
    )
    books = _stop_books(tmp_path / "stop-books")
    try:
        trade = _trade(
            suffix="legacy-expired",
            opened_at_ms=CAPTURE_START_MS - 1,
        )
        journal.record_trade(trade)
        outcome = DelayedEntryOutcome(
            trade_id=trade.trade_id,
            opening_plan_id=trade.opening_plan_id,
            market=trade.market.canonical,
            direction=trade.direction.value,
            source="expired",
            delayed_filled_quantity=Decimal("0"),
            delayed_average_fill_price=None,
            delayed_fee=Decimal("0"),
            observation_lag_ms=None,
            signed_price_improvement_bps=None,
            gross_r_improvement=None,
            attempt_reason="NO_FRESH_BOOK_WITHIN_WINDOW",
        )
        result = delayed_entry_stop_l2_replay(
            journal,
            (outcome,),
            paths,
            books,
            EMPTY_FUNDING_LOADER,
            _config(),
        )
    finally:
        journal.close()

    assert result["source_counts"] == {"expired": 1}
    assert result["pre_capture_legacy_outcomes"] == 1
    assert result["non_evaluable_entry_outcomes"] == 0
    assert result["non_evaluable_source_counts"] == {}
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["integrity_clean"] is True



def test_stop_l2_ignores_noncausal_session_gaps(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "paths")
    try:
        trade = _trade(suffix="noncausal-gap")
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                ((170_000, "89"), (300_000, "100")),
                complete=False,
                gaps=(
                    (10_000, 50_000),
                    (120_000, 160_000),
                    (500_000, 600_000),
                ),
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
            EMPTY_FUNDING_LOADER,
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert result["incomplete_or_gapped_paths"] == 0
    assert result["lineage_mismatches"] == 0
    assert overall["evaluated_filled_candidates"] == 1
    assert overall["full_stop_exits"] == 1
