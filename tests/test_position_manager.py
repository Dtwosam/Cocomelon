from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    OrderSide,
    PaperExecutionConfig,
    PositionActionType,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.execution.manager import evaluate_position
from cocomelon.execution.planner import PlanningRejection, plan_reduce_only_order

MARKET = MarketId(dex="", coin="SOL")
FOUR_HOURS_MS = 14_400_000


def position(*, side: PositionSide = PositionSide.LONG) -> PaperPosition:
    return PaperPosition(
        market=MARKET,
        side=side,
        quantity=Decimal("5"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("95") if side is PositionSide.LONG else Decimal("105"),
        opening_plan_id="open-1",
        opened_at_ms=1_000,
        updated_at_ms=1_000,
    )


def ctx(mark: str, *, received_ms: int = 2_000) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=None,
        receive_time=datetime.fromtimestamp(received_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"ctx:{MARKET.canonical}:{received_ms}:{mark}",
        payload={
            "mark_px": Decimal(mark),
            "mid_px": Decimal(mark),
            "oracle_px": Decimal(mark),
            "funding": Decimal("0"),
            "open_interest": Decimal("1000"),
        },
    )


def decision(direction: Direction, invalidation: str | None, *, timestamp_ms: int = 2_000):
    return StrategyDecision(
        market=MARKET,
        direction=direction,
        score=Decimal("80"),
        timestamp_ms=timestamp_ms,
        feature_snapshot_id="features-1",
        lead_strategy=None if direction is Direction.NO_TRADE else "trend",
        invalidation_price=None if invalidation is None else Decimal(invalidation),
        signal_ids=("signal-1",),
        reason_codes=("TEST",),
    )


def instrument(*, sz_decimals: int = 2) -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=sz_decimals,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=1_500,
        metadata_source="meta",
    )


def test_position_age_limit_defaults_to_disabled() -> None:
    assert PaperExecutionConfig().max_position_age_ms is None


def test_position_age_limit_must_be_positive_when_set() -> None:
    with pytest.raises(ValueError, match="max_position_age_ms"):
        PaperExecutionConfig(max_position_age_ms=0)


def test_expired_position_exits_thesis_after_four_hours() -> None:
    timestamp_ms = 1_000 + FOUR_HOURS_MS
    action = evaluate_position(
        position(),
        mark_event=ctx("101", received_ms=timestamp_ms),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(max_position_age_ms=FOUR_HOURS_MS),
        timestamp_ms=timestamp_ms,
    )

    assert action.action_type is PositionActionType.EXIT_THESIS
    assert action.quantity == Decimal("5")
    assert action.reason_codes == ("MAX_HOLD_EXPIRED",)


def test_position_does_not_expire_before_four_hours() -> None:
    timestamp_ms = 1_000 + FOUR_HOURS_MS - 1
    action = evaluate_position(
        position(),
        mark_event=ctx("101", received_ms=timestamp_ms),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(max_position_age_ms=FOUR_HOURS_MS),
        timestamp_ms=timestamp_ms,
    )

    assert action.action_type is PositionActionType.HOLD


def test_stop_has_precedence_over_position_age_expiry() -> None:
    timestamp_ms = 1_000 + FOUR_HOURS_MS
    action = evaluate_position(
        position(),
        mark_event=ctx("95", received_ms=timestamp_ms),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(max_position_age_ms=FOUR_HOURS_MS),
        timestamp_ms=timestamp_ms,
    )

    assert action.action_type is PositionActionType.EXIT_STOP
    assert action.reason_codes == ("MARK_STOP_TRIGGERED",)


def test_fresh_opposite_thesis_has_precedence_over_position_age_expiry() -> None:
    timestamp_ms = 1_000 + FOUR_HOURS_MS
    action = evaluate_position(
        position(),
        mark_event=ctx("101", received_ms=timestamp_ms),
        strategy_decision=decision(Direction.SHORT, "104", timestamp_ms=timestamp_ms),
        strategy_fresh=True,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(max_position_age_ms=FOUR_HOURS_MS),
        timestamp_ms=timestamp_ms,
    )

    assert action.action_type is PositionActionType.EXIT_THESIS
    assert action.reason_codes == ("OPPOSITE_FRESH_THESIS",)


def test_emergency_exit_has_precedence_over_stop_and_thesis() -> None:
    action = evaluate_position(
        position(),
        mark_event=ctx("94"),
        strategy_decision=decision(Direction.SHORT, "101"),
        strategy_fresh=True,
        critical_health=True,
        explicit_reduction_quantity=Decimal("1"),
        config=PaperExecutionConfig(),
        timestamp_ms=2_100,
    )

    assert action.action_type is PositionActionType.EXIT_EMERGENCY
    assert action.quantity == Decimal("5")


def test_mark_stop_has_precedence_over_opposite_thesis() -> None:
    action = evaluate_position(
        position(),
        mark_event=ctx("95"),
        strategy_decision=decision(Direction.SHORT, "101"),
        strategy_fresh=True,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(),
        timestamp_ms=2_100,
    )

    assert action.action_type is PositionActionType.EXIT_STOP
    assert action.quantity == Decimal("5")


def test_opposite_fresh_thesis_exits_but_no_trade_holds() -> None:
    opposite = evaluate_position(
        position(),
        mark_event=ctx("101"),
        strategy_decision=decision(Direction.SHORT, "104"),
        strategy_fresh=True,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(),
        timestamp_ms=2_100,
    )
    no_trade = evaluate_position(
        position(),
        mark_event=ctx("101"),
        strategy_decision=decision(Direction.NO_TRADE, None),
        strategy_fresh=True,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(),
        timestamp_ms=2_100,
    )

    assert opposite.action_type is PositionActionType.EXIT_THESIS
    assert no_trade.action_type is PositionActionType.HOLD


def test_same_direction_invalidation_only_tightens_stop() -> None:
    tighter_long = evaluate_position(
        position(),
        mark_event=ctx("101"),
        strategy_decision=decision(Direction.LONG, "97"),
        strategy_fresh=True,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(),
        timestamp_ms=2_100,
    )
    looser_long = evaluate_position(
        position(),
        mark_event=ctx("101"),
        strategy_decision=decision(Direction.LONG, "94"),
        strategy_fresh=True,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(),
        timestamp_ms=2_100,
    )
    tighter_short = evaluate_position(
        position(side=PositionSide.SHORT),
        mark_event=ctx("100"),
        strategy_decision=decision(Direction.SHORT, "103"),
        strategy_fresh=True,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(),
        timestamp_ms=2_100,
    )

    assert tighter_long.action_type is PositionActionType.TIGHTEN_STOP
    assert tighter_long.new_stop_price == Decimal("97")
    assert looser_long.action_type is PositionActionType.HOLD
    assert tighter_short.action_type is PositionActionType.TIGHTEN_STOP
    assert tighter_short.new_stop_price == Decimal("103")


def test_explicit_reduction_is_capped_to_current_position() -> None:
    action = evaluate_position(
        position(),
        mark_event=ctx("101"),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=Decimal("99"),
        config=PaperExecutionConfig(),
        timestamp_ms=2_100,
    )

    assert action.action_type is PositionActionType.REDUCE
    assert action.quantity == Decimal("5")


def test_stale_or_wrong_context_cannot_trigger_mark_stop() -> None:
    stale = evaluate_position(
        position(),
        mark_event=ctx("90", received_ms=1_000),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(max_asset_ctx_age_ms=500),
        timestamp_ms=2_100,
    )

    assert stale.action_type is PositionActionType.HOLD
    assert "MARK_CONTEXT_UNUSABLE" in stale.reason_codes


def test_reduce_only_plan_rounds_down_and_never_flips() -> None:
    action = evaluate_position(
        position(),
        mark_event=ctx("101"),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=Decimal("1.239"),
        config=PaperExecutionConfig(),
        timestamp_ms=2_100,
    )
    planned = plan_reduce_only_order(
        position(),
        action,
        instrument(sz_decimals=2),
        PaperExecutionConfig(),
        reference_price=Decimal("101"),
        created_at_ms=2_100,
    )

    assert not isinstance(planned, PlanningRejection)
    assert planned.reduce_only is True
    assert planned.side is OrderSide.SELL
    assert planned.requested_quantity == Decimal("1.23")
    assert planned.requested_quantity <= position().quantity
    assert planned.earliest_execution_ms == 2_350


def test_short_exit_plan_uses_buy_and_full_exit_never_exceeds_position() -> None:
    short = position(side=PositionSide.SHORT)
    action = evaluate_position(
        short,
        mark_event=ctx("106"),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(),
        timestamp_ms=2_100,
    )
    planned = plan_reduce_only_order(
        short,
        action,
        instrument(),
        PaperExecutionConfig(),
        reference_price=Decimal("106"),
        created_at_ms=2_100,
    )

    assert not isinstance(planned, PlanningRejection)
    assert action.action_type is PositionActionType.EXIT_STOP
    assert planned.side is OrderSide.BUY
    assert planned.requested_quantity == Decimal("5.00")


def test_hold_or_tighten_action_cannot_produce_order() -> None:
    hold = evaluate_position(
        position(),
        mark_event=ctx("101"),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=PaperExecutionConfig(),
        timestamp_ms=2_100,
    )

    rejection = plan_reduce_only_order(
        position(),
        hold,
        instrument(),
        PaperExecutionConfig(),
        reference_price=Decimal("101"),
        created_at_ms=2_100,
    )

    assert isinstance(rejection, PlanningRejection)
    assert rejection.reason == "ACTION_NOT_EXECUTABLE"
