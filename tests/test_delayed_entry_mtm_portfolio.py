from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
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
from cocomelon.research.delayed_entry_mtm_portfolio import (
    delayed_entry_mtm_portfolio,
)

MARKET = MarketId("", "SOL")


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    closed_at_ms: int,
    funding: tuple[FundingAccrual, ...] = (),
) -> TradeJournalEntry:
    entry = Decimal("100")
    quantity = Decimal("1")
    funding_pnl = sum(
        (item.cash_delta for item in funding),
        Decimal("0"),
    )
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"fill-open-{suffix}", f"fill-exit-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=tuple(
            item.accrual_id for item in funding
        ),
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        initial_risk_amount=Decimal("10"),
        entry_price=entry,
        exit_price=entry,
        filled_quantity=quantity,
        gross_realized_pnl=Decimal("0"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=funding_pnl,
        net_pnl=funding_pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - opened_at_ms,
        mfe=None,
        mae=None,
        net_r=funding_pnl / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + funding_pnl,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _funding(
    *,
    boundary_ms: int,
    rate: str,
    direction: Direction = Direction.LONG,
) -> FundingAccrual:
    signed_quantity = (
        Decimal("1")
        if direction is Direction.LONG
        else Decimal("-1")
    )
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
        funding_received_at_ms=boundary_ms + 100,
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
            if item.market == market
            and item.boundary_ms >= start_ms
        )

    return load


def _path(
    trade: TradeJournalEntry,
    marks: tuple[tuple[int, str], ...],
    *,
    complete: bool = True,
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
                event_key=f"{trade.trade_id}-{timestamp_ms}",
                mark_px=Decimal(mark_px),
            )
            for timestamp_ms, mark_px in marks
        ),
        known_gap_intervals=(),
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    source: str,
    quantity: str,
    price: str | None,
) -> DelayedEntryOutcome:
    delayed_price = None if price is None else Decimal(price)
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=Decimal(quantity),
        delayed_average_fill_price=delayed_price,
        delayed_fee=Decimal("0"),
        observation_lag_ms=0,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
        attempt_reason=None,
        capacity_cause=None,
    )


def test_mtm_portfolio_exposes_intratrade_drawdown_difference(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    try:
        long_trade = _trade(
            suffix="long",
            direction=Direction.LONG,
            opened_at_ms=100_000,
            closed_at_ms=400_000,
        )
        short_trade = _trade(
            suffix="short",
            direction=Direction.SHORT,
            opened_at_ms=130_000,
            closed_at_ms=430_000,
        )
        for trade in (long_trade, short_trade):
            journal.record_trade(trade)

        paths.record(
            _path(
                long_trade,
                (
                    (160_000, "90"),
                    (300_000, "100"),
                ),
            )
        )
        paths.record(
            _path(
                short_trade,
                (
                    (190_000, "110"),
                    (330_000, "100"),
                ),
            )
        )

        result = delayed_entry_mtm_portfolio(
            journal,
            (
                _outcome(
                    long_trade,
                    source="full_visible_book_ioc",
                    quantity="1",
                    price="90",
                ),
                _outcome(
                    short_trade,
                    source="full_visible_book_ioc",
                    quantity="1",
                    price="110",
                ),
            ),
            paths,
            _funding_loader(),
        )
    finally:
        journal.close()

    actual = result["actual"]
    candidate = result["candidate"]
    assert isinstance(actual, dict)
    assert isinstance(candidate, dict)
    assert actual["max_concurrent_positions"] == 2
    assert candidate["max_concurrent_positions"] == 2
    assert actual["overlap_openings"] == 1
    assert candidate["overlap_openings"] == 1
    assert actual["max_observed_equity_drawdown"] == "20"
    assert candidate["max_observed_equity_drawdown"] == "0"
    assert actual["final_realized_contribution"] == "0"
    assert candidate["final_realized_contribution"] == "20"
    assert result["delta_final_realized_contribution"] == "20"
    assert result["delta_max_observed_equity_drawdown"] == "-20"
    assert result["candidate_filled_positions"] == 2
    assert result["candidate_no_fill_trades"] == 0
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False
    assert readiness["missing_actual_overlap_openings"] == 4


def test_mtm_portfolio_ignores_marks_before_delayed_open(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    try:
        trade = _trade(
            suffix="pre-delay-mark",
            direction=Direction.LONG,
            opened_at_ms=100_000,
            closed_at_ms=400_000,
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (120_000, "80"),
                    (160_000, "90"),
                    (300_000, "100"),
                ),
            )
        )

        result = delayed_entry_mtm_portfolio(
            journal,
            (
                _outcome(
                    trade,
                    source="full_visible_book_ioc",
                    quantity="1",
                    price="90",
                ),
            ),
            paths,
            _funding_loader(),
        )
    finally:
        journal.close()

    actual = result["actual"]
    candidate = result["candidate"]
    assert isinstance(actual, dict)
    assert isinstance(candidate, dict)
    assert actual["max_observed_equity_drawdown"] == "20"
    assert candidate["max_observed_equity_drawdown"] == "0"
    assert result["candidate_filled_positions"] == 1
    assert result["lineage_mismatches"] == 0


def test_mtm_portfolio_no_fill_has_no_candidate_exposure(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    try:
        trade = _trade(
            suffix="nofill",
            direction=Direction.LONG,
            opened_at_ms=100_000,
            closed_at_ms=400_000,
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                ((160_000, "90"),),
            )
        )
        result = delayed_entry_mtm_portfolio(
            journal,
            (
                _outcome(
                    trade,
                    source="no_fill",
                    quantity="0",
                    price=None,
                ),
            ),
            paths,
            _funding_loader(),
        )
    finally:
        journal.close()

    actual = result["actual"]
    candidate = result["candidate"]
    assert isinstance(actual, dict)
    assert isinstance(candidate, dict)
    assert actual["max_concurrent_positions"] == 1
    assert candidate["max_concurrent_positions"] == 0
    assert result["candidate_filled_positions"] == 0
    assert result["candidate_no_fill_trades"] == 1
    assert candidate["final_realized_contribution"] == "0"


def test_mtm_portfolio_incomplete_path_blocks_review(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    try:
        trade = _trade(
            suffix="incomplete",
            direction=Direction.LONG,
            opened_at_ms=100_000,
            closed_at_ms=400_000,
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                ((160_000, "90"),),
                complete=False,
            )
        )
        result = delayed_entry_mtm_portfolio(
            journal,
            (
                _outcome(
                    trade,
                    source="full_visible_book_ioc",
                    quantity="1",
                    price="90",
                ),
            ),
            paths,
            _funding_loader(),
        )
    finally:
        journal.close()

    assert result["incomplete_exact_paths"] == 1
    assert result["evaluated_complete_path_trades"] == 0
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False



def test_mtm_portfolio_replays_funding_at_crossed_boundaries(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    first = _funding(boundary_ms=3_600_000, rate="0.01")
    second = _funding(boundary_ms=7_200_000, rate="0.02")
    try:
        trade = _trade(
            suffix="funding-timing",
            direction=Direction.LONG,
            opened_at_ms=3_550_000,
            closed_at_ms=7_300_000,
            funding=(first, second),
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (4_000_000, "100"),
                    (7_250_000, "100"),
                ),
            )
        )

        result = delayed_entry_mtm_portfolio(
            journal,
            (
                _outcome(
                    trade,
                    source="full_visible_book_ioc",
                    quantity="1",
                    price="100",
                ),
            ),
            paths,
            _funding_loader(first, second),
        )
    finally:
        journal.close()

    actual = result["actual"]
    candidate = result["candidate"]
    assert isinstance(actual, dict)
    assert isinstance(candidate, dict)
    assert result["intratrade_funding_timing_modeled"] is True
    assert actual["funding_events"] == 2
    assert candidate["funding_events"] == 1
    assert Decimal(str(actual["funding_cash_pnl"])) == Decimal("-3")
    assert Decimal(str(candidate["funding_cash_pnl"])) == Decimal("-2")
    assert Decimal(
        str(actual["final_realized_contribution"])
    ) == Decimal("-3")
    assert Decimal(
        str(candidate["final_realized_contribution"])
    ) == Decimal("-2")
    assert Decimal(
        str(result["delta_final_realized_contribution"])
    ) == Decimal("1")


def test_mtm_portfolio_missing_funding_event_blocks_review(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    funding = _funding(boundary_ms=3_600_000, rate="0.01")
    try:
        trade = _trade(
            suffix="missing-funding",
            direction=Direction.LONG,
            opened_at_ms=3_500_000,
            closed_at_ms=4_000_000,
            funding=(funding,),
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                ((3_800_000, "100"),),
            )
        )

        result = delayed_entry_mtm_portfolio(
            journal,
            (
                _outcome(
                    trade,
                    source="full_visible_book_ioc",
                    quantity="1",
                    price="100",
                ),
            ),
            paths,
            _funding_loader(),
        )
    finally:
        journal.close()

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert result["missing_funding_events"] == 1
    assert result["evaluated_complete_path_trades"] == 0
    assert readiness["ready_for_review"] is False
