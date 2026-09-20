from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import (
    ExecutionResult,
    InstrumentExecutionSpec,
    PaperExecutionConfig,
    PositionActionType,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import RiskDecision
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.paper import PaperExecutionAdapter

MARKET = MarketId("", "SOL")


def approved_risk(*, direction: Direction = Direction.LONG) -> RiskDecision:
    return RiskDecision(
        strategy_decision_id=f"strategy-{direction.value}",
        market=MARKET,
        direction=direction,
        approved=True,
        reason_codes=("risk_approved",),
        target_risk_amount=Decimal("25"),
        approved_risk_amount=Decimal("20"),
        approved_notional=Decimal("200"),
        entry_reference_price=Decimal("100"),
        stop_price=Decimal("95") if direction is Direction.LONG else Decimal("105"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
        correlation_bucket="crypto_beta",
        binding_caps=(),
        timestamp_ms=1_000,
    )


def rejected_risk() -> RiskDecision:
    return RiskDecision(
        strategy_decision_id="strategy-rejected",
        market=MARKET,
        direction=Direction.LONG,
        approved=False,
        reason_codes=("daily_loss_limit",),
        target_risk_amount=Decimal("25"),
        approved_risk_amount=Decimal("0"),
        approved_notional=Decimal("0"),
        entry_reference_price=Decimal("100"),
        stop_price=Decimal("95"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
        correlation_bucket="crypto_beta",
        binding_caps=(),
        timestamp_ms=1_000,
    )


def instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="hyperliquid-mainnet-meta",
    )


def book(
    *,
    bid: str = "99.9",
    ask: str = "100",
    quantity: str = "10",
    exchange_ms: int = 1_250,
    receive_ms: int = 1_260,
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=exchange_ms,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"l2:{MARKET.canonical}:{exchange_ms}:{bid}:{ask}",
        payload={
            "bids": ({"px": Decimal(bid), "sz": Decimal(quantity), "n": 1},),
            "asks": ({"px": Decimal(ask), "sz": Decimal(quantity), "n": 1},),
        },
    )


def mark(mark_px: str, *, receive_ms: int = 2_000) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=None,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"ctx:{MARKET.canonical}:{receive_ms}:{mark_px}",
        payload={
            "mark_px": Decimal(mark_px),
            "mid_px": Decimal(mark_px),
            "oracle_px": Decimal(mark_px),
            "funding": Decimal("0"),
            "open_interest": Decimal("1000"),
        },
    )


def adapter(path: Path) -> PaperExecutionAdapter:
    return PaperExecutionAdapter(
        path,
        PaperExecutionConfig(),
        starting_cash=Decimal("10000"),
        startup_timestamp_ms=500,
    )


def test_approved_long_opens_from_post_latency_public_l2_and_persists(
    tmp_path: Path,
) -> None:
    engine = adapter(tmp_path / "paper.sqlite3")

    result = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )

    assert result.rejection is None
    assert result.plan is not None
    assert result.simulation is not None
    assert result.simulation.attempt.result is ExecutionResult.FULL
    assert len(result.account.positions) == 1
    assert result.account.positions[0].quantity == Decimal("2.00")
    assert result.account.positions[0].correlation_bucket == "crypto_beta"
    engine.close()

    restarted = adapter(tmp_path / "paper.sqlite3")
    assert restarted.health.healthy_for_new_exposure is True
    assert restarted.account.state_id == result.account.state_id
    restarted.close()


def test_duplicate_observation_cannot_create_duplicate_exposure(tmp_path: Path) -> None:
    engine = adapter(tmp_path / "paper.sqlite3")
    first = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    second = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )

    assert len(first.account.positions) == 1
    assert second.plan is None
    assert second.rejection is not None
    assert second.rejection.reason == "POSITION_ALREADY_OPEN"
    assert len(second.account.positions) == 1
    engine.close()


def test_rejected_risk_never_creates_order_or_exposure(tmp_path: Path) -> None:
    engine = adapter(tmp_path / "paper.sqlite3")

    result = engine.submit_opening(
        rejected_risk(),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )

    assert result.plan is None
    assert result.simulation is None
    assert result.rejection is not None
    assert result.rejection.reason == "RISK_NOT_APPROVED"
    assert result.account.positions == ()
    engine.close()


def test_no_fill_persists_attempt_without_inventing_position(tmp_path: Path) -> None:
    engine = adapter(tmp_path / "paper.sqlite3")

    result = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(ask="100.30"),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )

    assert result.simulation is not None
    assert result.simulation.attempt.result is ExecutionResult.NO_FILL
    assert result.account.positions == ()
    engine.close()

    restarted = adapter(tmp_path / "paper.sqlite3")
    assert restarted.account.positions == ()
    assert restarted.health.healthy_for_new_exposure is True
    restarted.close()


def test_stop_exit_uses_reduce_only_ioc_and_closes_without_flip(tmp_path: Path) -> None:
    engine = adapter(tmp_path / "paper.sqlite3")
    opened = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    assert len(opened.account.positions) == 1

    managed = engine.manage_position(
        MARKET,
        instrument(),
        mark("94", receive_ms=2_000),
        book(bid="94", ask="94.1", exchange_ms=2_100, receive_ms=2_110),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        reference_price=Decimal("94"),
        timestamp_ms=2_100,
        attempt_timestamp_ms=2_400,
    )

    assert managed.plan is not None
    assert managed.plan.reduce_only is True
    assert managed.simulation is not None
    assert managed.simulation.attempt.result is ExecutionResult.FULL
    assert managed.account.positions == ()
    assert managed.account.consecutive_losses == 1
    engine.close()


def test_tightened_stop_updates_account_and_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    engine = adapter(path)
    opened = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    assert opened.account.positions[0].stop_price == Decimal("95")

    strategy = StrategyDecision(
        market=MARKET,
        direction=Direction.LONG,
        score=Decimal("80"),
        timestamp_ms=2_000,
        feature_snapshot_id="features-tighten",
        lead_strategy="trend",
        invalidation_price=Decimal("97"),
        signal_ids=("signal-tighten",),
        reason_codes=("TEST_TIGHTEN",),
    )
    managed = engine.manage_position(
        MARKET,
        instrument(),
        mark("101", receive_ms=2_000),
        book(bid="100.9", ask="101", exchange_ms=2_100, receive_ms=2_110),
        strategy_decision=strategy,
        strategy_fresh=True,
        critical_health=False,
        explicit_reduction_quantity=None,
        reference_price=Decimal("101"),
        timestamp_ms=2_100,
        attempt_timestamp_ms=2_400,
    )

    assert managed.action.action_type is PositionActionType.TIGHTEN_STOP
    assert managed.action.new_stop_price == Decimal("97")
    assert managed.account.positions[0].stop_price == Decimal("97")
    engine.close()

    restarted = adapter(path)
    assert restarted.health.healthy_for_new_exposure is True
    assert restarted.account.positions[0].stop_price == Decimal("97")
    restarted.close()


def test_tightened_short_stop_updates_account_and_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    engine = adapter(path)
    opened = engine.submit_opening(
        approved_risk(direction=Direction.SHORT),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    assert opened.account.positions[0].stop_price == Decimal("105")

    strategy = StrategyDecision(
        market=MARKET,
        direction=Direction.SHORT,
        score=Decimal("80"),
        timestamp_ms=2_000,
        feature_snapshot_id="features-tighten-short",
        lead_strategy="trend",
        invalidation_price=Decimal("103"),
        signal_ids=("signal-tighten-short",),
        reason_codes=("TEST_TIGHTEN_SHORT",),
    )
    managed = engine.manage_position(
        MARKET,
        instrument(),
        mark("99", receive_ms=2_000),
        book(bid="99", ask="99.1", exchange_ms=2_100, receive_ms=2_110),
        strategy_decision=strategy,
        strategy_fresh=True,
        critical_health=False,
        explicit_reduction_quantity=None,
        reference_price=Decimal("99"),
        timestamp_ms=2_100,
        attempt_timestamp_ms=2_400,
    )

    assert managed.action.action_type is PositionActionType.TIGHTEN_STOP
    assert managed.action.new_stop_price == Decimal("103")
    assert managed.account.positions[0].stop_price == Decimal("103")
    engine.close()

    restarted = adapter(path)
    assert restarted.health.healthy_for_new_exposure is True
    assert restarted.account.positions[0].stop_price == Decimal("103")
    restarted.close()


def test_tightened_stop_persistence_failure_keeps_old_account_and_degrades_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "paper.sqlite3"
    engine = adapter(path)
    opened = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    assert opened.account.positions[0].stop_price == Decimal("95")

    strategy = StrategyDecision(
        market=MARKET,
        direction=Direction.LONG,
        score=Decimal("80"),
        timestamp_ms=2_000,
        feature_snapshot_id="features-tighten-failure",
        lead_strategy="trend",
        invalidation_price=Decimal("97"),
        signal_ids=("signal-tighten-failure",),
        reason_codes=("TEST_TIGHTEN_FAILURE",),
    )

    def fail_persist(_account: object) -> None:
        raise RuntimeError("simulated durable write failure")

    monkeypatch.setattr(engine.store, "persist_account", fail_persist)
    with pytest.raises(RuntimeError, match="simulated durable write failure"):
        engine.manage_position(
            MARKET,
            instrument(),
            mark("101", receive_ms=2_000),
            book(bid="100.9", ask="101", exchange_ms=2_100, receive_ms=2_110),
            strategy_decision=strategy,
            strategy_fresh=True,
            critical_health=False,
            explicit_reduction_quantity=None,
            reference_price=Decimal("101"),
            timestamp_ms=2_100,
            attempt_timestamp_ms=2_400,
        )

    assert engine.account.positions[0].stop_price == Decimal("95")
    assert engine.health.healthy_for_new_exposure is False
    assert engine.health.reason_codes == ("DURABLE_STOP_TIGHTEN_WRITE_FAILED",)
    engine.close()

    restarted = adapter(path)
    assert restarted.account.positions[0].stop_price == Decimal("95")
    assert restarted.health.healthy_for_new_exposure is True
    restarted.close()


def test_opening_plan_persistence_failure_degrades_execution_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "paper.sqlite3"
    engine = adapter(path)

    def fail_persist(_plan: object) -> None:
        raise RuntimeError("simulated plan write failure")

    monkeypatch.setattr(engine.store, "persist_plan", fail_persist)
    with pytest.raises(RuntimeError, match="simulated plan write failure"):
        engine.submit_opening(
            approved_risk(),
            instrument(),
            book(),
            reference_price=Decimal("100"),
            created_at_ms=1_000,
            attempt_timestamp_ms=1_300,
        )

    assert engine.account.positions == ()
    assert engine.health.healthy_for_new_exposure is False
    assert engine.health.reason_codes == ("DURABLE_PLAN_WRITE_FAILED",)

    blocked = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(exchange_ms=2_000, receive_ms=2_010),
        reference_price=Decimal("100"),
        created_at_ms=1_500,
        attempt_timestamp_ms=2_100,
    )
    assert blocked.plan is None
    assert blocked.rejection is not None
    assert blocked.rejection.reason == "EXECUTION_STATE_UNHEALTHY"
    engine.close()


def test_reduce_only_plan_persistence_failure_keeps_position_and_degrades_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "paper.sqlite3"
    engine = adapter(path)
    opened = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    original_state_id = opened.account.state_id
    original_position_id = opened.account.positions[0].position_id

    def fail_persist(_plan: object) -> None:
        raise RuntimeError("simulated reduce plan write failure")

    monkeypatch.setattr(engine.store, "persist_plan", fail_persist)
    with pytest.raises(RuntimeError, match="simulated reduce plan write failure"):
        engine.manage_position(
            MARKET,
            instrument(),
            mark("94", receive_ms=2_000),
            book(bid="94", ask="94.1", exchange_ms=2_100, receive_ms=2_110),
            strategy_decision=None,
            strategy_fresh=False,
            critical_health=False,
            explicit_reduction_quantity=None,
            reference_price=Decimal("94"),
            timestamp_ms=2_100,
            attempt_timestamp_ms=2_400,
        )

    assert engine.account.state_id == original_state_id
    assert len(engine.account.positions) == 1
    assert engine.account.positions[0].position_id == original_position_id
    assert engine.health.healthy_for_new_exposure is False
    assert engine.health.reason_codes == ("DURABLE_PLAN_WRITE_FAILED",)
    engine.close()


def test_missing_opening_plan_lineage_degrades_health_during_position_management(
    tmp_path: Path,
) -> None:
    path = tmp_path / "paper.sqlite3"
    engine = adapter(path)
    opened = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    opening_plan_id = opened.account.positions[0].opening_plan_id
    with engine.store.raw_connection() as conn:
        conn.execute(
            "DELETE FROM paper_order_plans WHERE plan_id = ?",
            (opening_plan_id,),
        )

    managed = engine.manage_position(
        MARKET,
        instrument(),
        mark("94", receive_ms=2_000),
        book(bid="94", ask="94.1", exchange_ms=2_100, receive_ms=2_110),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        reference_price=Decimal("94"),
        timestamp_ms=2_100,
        attempt_timestamp_ms=2_400,
    )

    assert managed.plan is None
    assert managed.rejection is not None
    assert managed.rejection.reason == "OPENING_PLAN_LINEAGE_MISSING"
    assert len(managed.account.positions) == 1
    assert engine.health.healthy_for_new_exposure is False
    assert engine.health.reason_codes == ("OPENING_PLAN_LINEAGE_MISSING",)
    engine.close()


def test_unreadable_opening_plan_lineage_degrades_health_during_position_management(
    tmp_path: Path,
) -> None:
    path = tmp_path / "paper.sqlite3"
    engine = adapter(path)
    opened = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    opening_plan_id = opened.account.positions[0].opening_plan_id
    with engine.store.raw_connection() as conn:
        conn.execute(
            "UPDATE paper_order_plans SET payload_json = ? WHERE plan_id = ?",
            ("{", opening_plan_id),
        )

    managed = engine.manage_position(
        MARKET,
        instrument(),
        mark("94", receive_ms=2_000),
        book(bid="94", ask="94.1", exchange_ms=2_100, receive_ms=2_110),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        reference_price=Decimal("94"),
        timestamp_ms=2_100,
        attempt_timestamp_ms=2_400,
    )

    assert managed.plan is None
    assert managed.rejection is not None
    assert managed.rejection.reason == "OPENING_PLAN_LINEAGE_UNREADABLE"
    assert len(managed.account.positions) == 1
    assert engine.health.healthy_for_new_exposure is False
    assert engine.health.reason_codes == ("OPENING_PLAN_LINEAGE_UNREADABLE",)
    engine.close()


def test_restart_inconsistency_blocks_new_exposure_but_is_visible_in_health(
    tmp_path: Path,
) -> None:
    path = tmp_path / "paper.sqlite3"
    engine = adapter(path)
    result = engine.submit_opening(
        approved_risk(),
        instrument(),
        book(),
        reference_price=Decimal("100"),
        created_at_ms=1_000,
        attempt_timestamp_ms=1_300,
    )
    assert len(result.account.positions) == 1
    with engine.store.raw_connection() as conn:
        conn.execute("UPDATE paper_positions SET payload_json='{}'")
    engine.close()

    restarted = adapter(path)
    assert restarted.health.healthy_for_new_exposure is False
    rejected = restarted.submit_opening(
        approved_risk(),
        instrument(),
        book(exchange_ms=3_000, receive_ms=3_010),
        reference_price=Decimal("100"),
        created_at_ms=2_500,
        attempt_timestamp_ms=3_100,
    )
    assert rejected.rejection is not None
    assert rejected.rejection.reason == "EXECUTION_STATE_UNHEALTHY"
    restarted.close()
