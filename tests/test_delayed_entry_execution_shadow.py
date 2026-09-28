from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import (
    PaperPosition,
    PositionSide,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DELAY_MS,
    DelayedEntryExecutionShadow,
    DelayedEntryShadowError,
)

MARKET = MarketId("", "SOL")


def _config() -> PaperExecutionConfig:
    return PaperExecutionConfig()


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="hyperliquid-mainnet-meta",
    )


def _position(
    *,
    side: PositionSide = PositionSide.LONG,
    opened_at_ms: int = 1_000,
    quantity: str = "1",
) -> PaperPosition:
    return PaperPosition(
        market=MARKET,
        side=side,
        quantity=Decimal(quantity),
        average_entry_price=Decimal("100"),
        stop_price=(
            Decimal("90")
            if side is PositionSide.LONG
            else Decimal("110")
        ),
        opening_plan_id=(
            f"opening-{side.value}-{opened_at_ms}"
        ),
        opened_at_ms=opened_at_ms,
        updated_at_ms=opened_at_ms,
        initial_risk_decision_id="risk-1",
        correlation_bucket="crypto_beta",
        cost_buffer_fraction=Decimal("0"),
        planned_risk=Decimal("10") * Decimal(quantity),
        venue_max_leverage=Decimal("20"),
        latest_mark=Decimal("100"),
    )


def _mark(
    receive_ms: int,
    *,
    px: str = "100",
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=receive_ms - 1,
        receive_time=datetime.fromtimestamp(
            receive_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"mark:{receive_ms}:{px}",
        payload={
            "mark_px": Decimal(px),
            "mid_px": Decimal(px),
            "oracle_px": Decimal(px),
            "funding": Decimal("0"),
            "open_interest": Decimal("1000"),
        },
    )


def _book(
    receive_ms: int,
    *,
    bid: str,
    ask: str,
    bid_size: str = "10",
    ask_size: str = "10",
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
        event_key=(
            f"book:{receive_ms}:{bid}:{ask}:"
            f"{bid_size}:{ask_size}"
        ),
        payload={
            "bids": (
                {
                    "px": Decimal(bid),
                    "sz": Decimal(bid_size),
                    "n": 1,
                },
            ),
            "asks": (
                {
                    "px": Decimal(ask),
                    "sz": Decimal(ask_size),
                    "n": 1,
                },
            ),
        },
    )


def _book_levels(
    receive_ms: int,
    *,
    bids: tuple[tuple[str, str], ...],
    asks: tuple[tuple[str, str], ...],
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
        event_key=f"book-levels:{receive_ms}:{bids}:{asks}",
        payload={
            "bids": tuple(
                {
                    "px": Decimal(px),
                    "sz": Decimal(sz),
                    "n": 1,
                }
                for px, sz in bids
            ),
            "asks": tuple(
                {
                    "px": Decimal(px),
                    "sz": Decimal(sz),
                    "n": 1,
                }
                for px, sz in asks
            ),
        },
    )


def _trade(
    position: PaperPosition,
    *,
    closed_at_ms: int = 180_000,
) -> TradeJournalEntry:
    direction = (
        Direction.LONG
        if position.side is PositionSide.LONG
        else Direction.SHORT
    )
    return TradeJournalEntry(
        market=position.market,
        direction=direction,
        opened_at_ms=position.opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id="feature-1",
        strategy_decision_id="strategy-1",
        risk_decision_id=position.initial_risk_decision_id,
        opening_plan_id=position.opening_plan_id,
        opening_attempt_id="opening-attempt-1",
        exit_plan_ids=("exit-plan-1",),
        exit_attempt_ids=("exit-attempt-1",),
        fill_ids=("fill-open", "fill-close"),
        position_action_ids=("action-close",),
        funding_event_ids=(),
        initial_stop=position.stop_price,
        initial_risk_amount=position.planned_risk,
        entry_price=position.average_entry_price,
        exit_price=position.average_entry_price,
        filled_quantity=position.quantity,
        gross_realized_pnl=Decimal("0"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("0"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=(
            closed_at_ms - position.opened_at_ms
        ),
        mfe=None,
        mae=None,
        net_r=Decimal("0"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000"),
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def test_delayed_long_full_fill_reports_better_price() -> None:
    position = _position()
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )
    attempt_ms = position.opened_at_ms + DELAY_MS + 300
    shadow.observe_book(
        (position,),
        _instrument(),
        _book(
            attempt_ms,
            bid="98.9",
            ask="99.1",
        ),
        reference_price=Decimal("99"),
        now_ms=attempt_ms,
    )
    shadow.record_closed_trade(_trade(position))

    summary = shadow.summary_payload()
    assert summary["closed_eligible_trades"] == 1
    assert summary["full_delayed_fills"] == 1
    assert summary["better_price_full_fills"] == 1
    assert summary["worse_price_full_fills"] == 0
    assert Decimal(
        str(summary["mean_signed_price_improvement_bps"])
    ) == Decimal("90.000")
    outcome = shadow.outcomes[0]
    assert outcome.delayed_entry_side_depth_25bps == Decimal("1009.0")
    assert outcome.delayed_exit_side_depth_25bps == Decimal("1011.0")
    assert Decimal(
        str(summary["mean_gross_r_improvement"])
    ) == Decimal("0.09")
    outcome = shadow.outcomes[0]
    assert outcome.delayed_entry_side_depth_25bps == Decimal("991.0")
    assert outcome.delayed_exit_side_depth_25bps == Decimal("989.0")
    assert summary["delayed_depth_evidence_outcomes"] == 1


def test_delayed_short_full_fill_is_direction_symmetric() -> None:
    position = _position(side=PositionSide.SHORT)
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )
    attempt_ms = position.opened_at_ms + DELAY_MS + 300
    shadow.observe_book(
        (position,),
        _instrument(),
        _book(
            attempt_ms,
            bid="100.9",
            ask="101.1",
        ),
        reference_price=Decimal("101"),
        now_ms=attempt_ms,
    )
    shadow.record_closed_trade(_trade(position))

    summary = shadow.summary_payload()
    assert summary["full_delayed_fills"] == 1
    assert summary["better_price_full_fills"] == 1
    assert Decimal(
        str(summary["mean_signed_price_improvement_bps"])
    ) == Decimal("90.000")


def test_delayed_entry_partial_fill_is_not_scored_as_full() -> None:
    position = _position(quantity="2")
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )
    attempt_ms = position.opened_at_ms + DELAY_MS + 300
    shadow.observe_book(
        (position,),
        _instrument(),
        _book(
            attempt_ms,
            bid="98.9",
            ask="99.1",
            ask_size="1",
        ),
        reference_price=Decimal("99"),
        now_ms=attempt_ms,
    )
    shadow.record_closed_trade(_trade(position))

    summary = shadow.summary_payload()
    assert summary["full_delayed_fills"] == 0
    assert summary["partial_delayed_fills"] == 1
    assert summary["mean_signed_price_improvement_bps"] is None
    assert summary["mean_gross_r_improvement"] is None


def test_delayed_partial_distinguishes_slippage_boundary() -> None:
    position = _position(quantity="2")
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )
    attempt_ms = position.opened_at_ms + DELAY_MS + 300
    shadow.observe_book(
        (position,),
        _instrument(),
        _book_levels(
            attempt_ms,
            bids=(("99.7", "10"),),
            asks=(("99.9", "1"), ("100.5", "10")),
        ),
        reference_price=Decimal("100"),
        now_ms=attempt_ms,
    )
    shadow.record_closed_trade(_trade(position))

    outcome = shadow.outcomes[0]
    assert outcome.source == "partial_visible_book_ioc"
    assert outcome.delayed_filled_quantity == Decimal("1")
    assert outcome.capacity_cause == "slippage_boundary_reached"


def test_delayed_partial_distinguishes_visible_depth_exhaustion() -> None:
    position = _position(quantity="2")
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )
    attempt_ms = position.opened_at_ms + DELAY_MS + 300
    shadow.observe_book(
        (position,),
        _instrument(),
        _book_levels(
            attempt_ms,
            bids=(("99.7", "10"),),
            asks=(("99.9", "1"),),
        ),
        reference_price=Decimal("100"),
        now_ms=attempt_ms,
    )
    shadow.record_closed_trade(_trade(position))

    outcome = shadow.outcomes[0]
    assert outcome.source == "partial_visible_book_ioc"
    assert outcome.delayed_filled_quantity == Decimal("1")
    assert outcome.capacity_cause == "visible_depth_exhausted"


def test_open_attempt_capacity_payload_exposes_partial_cause() -> None:
    position = _position(quantity="2")
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )
    attempt_ms = position.opened_at_ms + DELAY_MS + 300
    shadow.observe_book(
        (position,),
        _instrument(),
        _book_levels(
            attempt_ms,
            bids=(("99.7", "10"),),
            asks=(("99.9", "1"), ("100.5", "10")),
        ),
        reference_price=Decimal("100"),
        now_ms=attempt_ms,
    )

    payload = shadow.open_attempt_capacity_payload()
    assert payload["attempted_open_positions"] == 1
    rows = payload["rows"]
    assert isinstance(rows, list)
    assert rows == [
        {
            "opening_plan_id": position.opening_plan_id,
            "market": MARKET.canonical,
            "side": "long",
            "attempted_at_ms": attempt_ms,
            "result": "partial",
            "attempt_reason": "IOC_REMAINDER_CANCELLED",
            "capacity_cause": "slippage_boundary_reached",
            "requested_quantity": "2",
            "filled_quantity": "1.00",
            "fill_fraction": "0.50",
            "observation_lag_ms": 300,
            "delayed_entry_side_depth_25bps": "99.9",
            "delayed_exit_side_depth_25bps": "997.0",
        }
    ]


def test_delayed_capacity_cause_survives_restart_before_close() -> None:
    position = _position(quantity="2")
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )
    attempt_ms = position.opened_at_ms + DELAY_MS + 300
    shadow.observe_book(
        (position,),
        _instrument(),
        _book_levels(
            attempt_ms,
            bids=(("99.7", "10"),),
            asks=(("99.9", "1"), ("100.5", "10")),
        ),
        reference_price=Decimal("100"),
        now_ms=attempt_ms,
    )

    restored = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=999_999,
    )
    restored.restore_state(shadow.state_payload())
    restored.record_closed_trade(_trade(position))

    outcome = restored.outcomes[0]
    assert outcome.capacity_cause == "slippage_boundary_reached"
    assert outcome.delayed_entry_side_depth_25bps == Decimal("99.9")
    assert outcome.delayed_exit_side_depth_25bps == Decimal("997.0")


def test_delayed_entry_v2_state_migrates_without_inventing_depth() -> None:
    position = _position()
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )
    attempt_ms = position.opened_at_ms + DELAY_MS + 300
    shadow.observe_book(
        (position,),
        _instrument(),
        _book(
            attempt_ms,
            bid="98.9",
            ask="99.1",
        ),
        reference_price=Decimal("99"),
        now_ms=attempt_ms,
    )
    shadow.record_closed_trade(_trade(position))

    payload = shadow.state_payload()
    payload["schema_version"] = 2
    outcomes = payload["outcomes"]
    assert isinstance(outcomes, list)
    for raw in outcomes:
        assert isinstance(raw, dict)
        raw.pop("delayed_entry_side_depth_25bps")
        raw.pop("delayed_exit_side_depth_25bps")

    restored = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=999_999,
    )
    restored.restore_state(payload)

    assert restored.summary_payload()["state_restored"] is True
    outcome = restored.outcomes[0]
    assert outcome.delayed_entry_side_depth_25bps is None
    assert outcome.delayed_exit_side_depth_25bps is None
    assert restored.state_payload()["schema_version"] == 3


def test_delayed_entry_state_survives_restart_before_target() -> None:
    position = _position()
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )

    restored = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=999_999,
    )
    restored.restore_state(shadow.state_payload())
    assert restored.summary_payload()["state_restored"] is True

    attempt_ms = position.opened_at_ms + DELAY_MS + 300
    restored.observe_book(
        (position,),
        _instrument(),
        _book(
            attempt_ms,
            bid="98.9",
            ask="99.1",
        ),
        reference_price=Decimal("99"),
        now_ms=attempt_ms,
    )
    restored.record_closed_trade(_trade(position))
    assert restored.summary_payload()["full_delayed_fills"] == 1


def test_delayed_entry_expires_when_first_book_is_too_late() -> None:
    position = _position()
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )
    attempt_ms = (
        position.opened_at_ms
        + DELAY_MS
        + 60_001
    )
    shadow.observe_book(
        (position,),
        _instrument(),
        _book(
            attempt_ms,
            bid="98.9",
            ask="99.1",
        ),
        reference_price=Decimal("99"),
        now_ms=attempt_ms,
    )
    shadow.record_closed_trade(_trade(position))

    summary = shadow.summary_payload()
    assert summary["expired"] == 1
    assert summary["full_delayed_fills"] == 0


def test_delayed_entry_excludes_position_open_before_observer() -> None:
    position = _position(opened_at_ms=1_000)
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=2_000,
    )
    shadow.observe_mark(
        (position,),
        _mark(2_100),
        now_ms=2_100,
    )
    shadow.record_closed_trade(_trade(position))

    summary = shadow.summary_payload()
    assert summary["closed_eligible_trades"] == 0
    assert summary["excluded_closed_trades"] == 1


def test_delayed_entry_reconciles_orphaned_restored_position() -> None:
    position = _position()
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )

    restored = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=999_999,
    )
    restored.restore_state(shadow.state_payload())
    restored.reconcile_open_positions(())

    summary = restored.summary_payload()
    assert summary["open_tracked_positions"] == 0
    assert summary["orphaned_restored_positions"] == 1
    assert summary["readiness"]["ready_for_review"] is False


def test_custom_120s_delay_is_durable_and_independent() -> None:
    position = _position()
    delay_ms = 120_000
    shadow = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
        delay_ms=delay_ms,
        max_observation_lag_ms=60_000,
    )
    shadow.observe_mark(
        (position,),
        _mark(1_100),
        now_ms=1_100,
    )
    attempt_ms = position.opened_at_ms + delay_ms + 300
    shadow.observe_book(
        (position,),
        _instrument(),
        _book(
            attempt_ms,
            bid="97.9",
            ask="98.1",
        ),
        reference_price=Decimal("98"),
        now_ms=attempt_ms,
    )

    payload = shadow.state_payload()
    assert payload["delay_ms"] == delay_ms
    assert payload["max_observation_lag_ms"] == 60_000

    restored = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=999_999,
        delay_ms=delay_ms,
        max_observation_lag_ms=60_000,
    )
    restored.restore_state(payload)
    restored.record_closed_trade(
        _trade(position, closed_at_ms=240_000)
    )
    summary = restored.summary_payload()
    assert summary["delay_ms"] == delay_ms
    assert summary["full_delayed_fills"] == 1
    assert Decimal(
        str(summary["mean_gross_r_improvement"])
    ) == Decimal("0.19")

    incompatible = DelayedEntryExecutionShadow(
        _config(),
        started_at_ms=500,
    )
    with pytest.raises(
        DelayedEntryShadowError,
        match="delay mismatch",
    ):
        incompatible.restore_state(payload)
