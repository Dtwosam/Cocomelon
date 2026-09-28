from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import PaperExecutionConfig
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
from cocomelon.research.delayed_entry_stop_exit_proxy import (
    delayed_entry_stop_exit_proxy_range,
)

MARKET = MarketId("", "SOL")


def _funding(
    *,
    boundary_ms: int,
    rate: str,
    direction: Direction = Direction.LONG,
) -> FundingAccrual:
    quantity = Decimal("1")
    signed_quantity = (
        quantity
        if direction is Direction.LONG
        else -quantity
    )
    oracle = Decimal("100")
    funding_rate = Decimal(rate)
    return FundingAccrual(
        market=MARKET,
        boundary_ms=boundary_ms,
        position_id=f"position-{boundary_ms}",
        signed_quantity=signed_quantity,
        oracle_price=oracle,
        funding_rate=funding_rate,
        cash_delta=funding_cash_delta(
            signed_quantity,
            oracle,
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


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    closed_at_ms: int,
    funding: tuple[FundingAccrual, ...] = (),
) -> TradeJournalEntry:
    funding_pnl = sum(
        (item.cash_delta for item in funding),
        Decimal("0"),
    )
    entry = Decimal("100")
    exit_px = (
        Decimal("110")
        if direction is Direction.LONG
        else Decimal("90")
    )
    stop = (
        Decimal("90")
        if direction is Direction.LONG
        else Decimal("110")
    )
    gross = Decimal("10")
    net = gross + funding_pnl
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
        fill_ids=(
            f"fill-open-{suffix}",
            f"fill-exit-{suffix}",
        ),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=tuple(
            item.accrual_id for item in funding
        ),
        initial_stop=stop,
        initial_risk_amount=Decimal("10"),
        entry_price=entry,
        exit_price=exit_px,
        filled_quantity=Decimal("1"),
        gross_realized_pnl=gross,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=funding_pnl,
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - opened_at_ms,
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


def _path(
    trade: TradeJournalEntry,
    marks: tuple[tuple[int, str], ...],
    *,
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
        excursion_complete=True,
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
        known_gap_intervals=gaps,
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    source: str = "full_visible_book_ioc",
    quantity: str = "1",
    price: str | None = "100",
) -> DelayedEntryOutcome:
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=Decimal(quantity),
        delayed_average_fill_price=(
            None if price is None else Decimal(price)
        ),
        delayed_fee=Decimal("0"),
        observation_lag_ms=0,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
        attempt_reason=None,
        capacity_cause=None,
    )


def _config() -> PaperExecutionConfig:
    return PaperExecutionConfig(
        max_ioc_slippage_bps=Decimal("100"),
        taker_fee_rate=Decimal("0.001"),
    )


def test_stop_exit_proxy_replaces_crossed_same_exit_pnl(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "paths")
    try:
        crossed = _trade(
            suffix="crossed",
            direction=Direction.LONG,
            opened_at_ms=100_000,
            closed_at_ms=400_000,
        )
        survived = _trade(
            suffix="survived",
            direction=Direction.LONG,
            opened_at_ms=500_000,
            closed_at_ms=800_000,
        )
        for trade in (crossed, survived):
            journal.record_trade(trade)
        paths.record(
            _path(
                crossed,
                (
                    (170_000, "89"),
                    (300_000, "100"),
                ),
            )
        )
        paths.record(
            _path(
                survived,
                (
                    (570_000, "95"),
                    (700_000, "105"),
                ),
            )
        )

        result = delayed_entry_stop_exit_proxy_range(
            journal,
            (_outcome(crossed), _outcome(survived)),
            paths,
            _funding_loader(),
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["definite_original_stop_crossings"] == 1
    assert overall["survived_observed_path_to_actual_close"] == 1
    assert Decimal(
        str(overall["same_exit_candidate_net_pnl"])
    ) == Decimal("20")
    assert Decimal(
        str(
            overall[
                "same_exit_candidate_pnl_on_stop_crossings"
            ]
        )
    ) == Decimal("10")
    assert Decimal(
        str(overall["stop_price_proxy_pnl_on_stop_crossings"])
    ) == Decimal("-10.090")
    assert Decimal(
        str(
            overall[
                "crossing_mark_proxy_pnl_on_stop_crossings"
            ]
        )
    ) == Decimal("-11.089")
    assert Decimal(
        str(
            overall[
                "ioc_boundary_proxy_pnl_on_stop_crossings"
            ]
        )
    ) == Decimal("-11.978110")
    assert Decimal(
        str(overall["stop_price_proxy_cohort_net_pnl"])
    ) == Decimal("-0.090")
    assert Decimal(
        str(overall["crossing_mark_proxy_cohort_net_pnl"])
    ) == Decimal("-1.089")
    assert Decimal(
        str(overall["ioc_boundary_proxy_cohort_net_pnl"])
    ) == Decimal("-1.978110")
    assert (
        overall[
            "positive_same_exit_crossings_to_nonpositive_boundary"
        ]
        == 1
    )


def test_short_stop_exit_boundary_worsens_price_and_pnl(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "paths")
    try:
        trade = _trade(
            suffix="short-crossed",
            direction=Direction.SHORT,
            opened_at_ms=100_000,
            closed_at_ms=400_000,
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (170_000, "111"),
                    (300_000, "100"),
                ),
            )
        )
        result = delayed_entry_stop_exit_proxy_range(
            journal,
            (_outcome(trade),),
            paths,
            _funding_loader(),
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert Decimal(
        str(overall["stop_price_proxy_cohort_net_pnl"])
    ) == Decimal("-10.110")
    assert Decimal(
        str(overall["crossing_mark_proxy_cohort_net_pnl"])
    ) == Decimal("-11.111")
    assert Decimal(
        str(overall["ioc_boundary_proxy_cohort_net_pnl"])
    ) == Decimal("-12.222110")


def test_stop_exit_proxy_funding_stops_before_trigger(
    tmp_path: Path,
) -> None:
    before_open = _funding(
        boundary_ms=150_000,
        rate="0.01",
    )
    before_stop = _funding(
        boundary_ms=165_000,
        rate="0.02",
    )
    after_stop = _funding(
        boundary_ms=200_000,
        rate="0.03",
    )
    trade = _trade(
        suffix="funding-cutoff",
        direction=Direction.LONG,
        opened_at_ms=100_000,
        closed_at_ms=400_000,
        funding=(before_open, before_stop, after_stop),
    )
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "paths")
    try:
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (170_000, "89"),
                    (300_000, "100"),
                ),
            )
        )
        result = delayed_entry_stop_exit_proxy_range(
            journal,
            (_outcome(trade),),
            paths,
            _funding_loader(
                before_open,
                before_stop,
                after_stop,
            ),
            _config(),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert Decimal(
        str(overall["stop_price_proxy_cohort_net_pnl"])
    ) == Decimal("-12.090")
    assert Decimal(
        str(overall["same_exit_candidate_net_pnl"])
    ) == Decimal("5")


def test_stop_exit_proxy_excludes_same_timestamp_funding(
    tmp_path: Path,
) -> None:
    funding = _funding(
        boundary_ms=170_000,
        rate="0.01",
    )
    trade = _trade(
        suffix="ambiguous-funding",
        direction=Direction.LONG,
        opened_at_ms=100_000,
        closed_at_ms=400_000,
        funding=(funding,),
    )
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "paths")
    try:
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (170_000, "89"),
                    (300_000, "100"),
                ),
            )
        )
        result = delayed_entry_stop_exit_proxy_range(
            journal,
            (_outcome(trade),),
            paths,
            _funding_loader(funding),
            _config(),
        )
    finally:
        journal.close()

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert result["ambiguous_stop_funding_timing"] == 1
    assert result["evaluated_filled_candidates"] == 0
    assert readiness["ready_for_review"] is False


def test_stop_exit_proxy_no_fill_needs_no_path_or_funding(
    tmp_path: Path,
) -> None:
    trade = _trade(
        suffix="no-fill",
        direction=Direction.LONG,
        opened_at_ms=100_000,
        closed_at_ms=400_000,
    )
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "paths")
    try:
        journal.record_trade(trade)
        result = delayed_entry_stop_exit_proxy_range(
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
            _config(),
        )
    finally:
        journal.close()

    assert result["candidate_no_fill_trades"] == 1
    assert result["evaluated_filled_candidates"] == 0
    assert result["missing_exact_paths"] == 0
    assert result["missing_funding_events"] == 0


def test_stop_exit_proxy_gapped_path_blocks_review(
    tmp_path: Path,
) -> None:
    trade = _trade(
        suffix="gap",
        direction=Direction.LONG,
        opened_at_ms=100_000,
        closed_at_ms=400_000,
    )
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "paths")
    try:
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (170_000, "95"),
                    (300_000, "103"),
                ),
                gaps=((200_000, 250_000),),
            )
        )
        result = delayed_entry_stop_exit_proxy_range(
            journal,
            (_outcome(trade),),
            paths,
            _funding_loader(),
            _config(),
        )
    finally:
        journal.close()

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert result["incomplete_or_gapped_paths"] == 1
    assert result["evaluated_filled_candidates"] == 0
    assert readiness["ready_for_review"] is False
