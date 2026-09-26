from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.continuous_paper import (
    RUN_ID,
    ContinuousPaperConfig,
    _load_checkpoint,
    _position_action_from_payload,
    _position_action_payload,
    _record_from_gap,
    _record_from_payload,
    _record_from_stream,
    _record_payload,
    _RecordPump,
    _SupervisorGroup,
    _wait_supervisor_group_ready,
)
from cocomelon.domain.execution import PositionAction, PositionActionType
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind


def test_continuous_config_requires_aligned_refresh_interval() -> None:
    with pytest.raises(ValueError, match="divisible"):
        ContinuousPaperConfig(
            duration_seconds=60,
            context_poll_seconds=60,
            selection_refresh_seconds=61,
        )


def test_gap_record_preserves_recovered_interval() -> None:
    gap = DataGap(
        stream_id="l2Book:BTC",
        started_ms=1_000,
        ended_ms=1_500,
        reason="recovered",
    )
    record = _record_from_gap(gap)
    assert record.record_kind is SourceRecordKind.DATA_GAP
    assert record.available_at_ms == 1_000
    assert record.payload == {
        "ended_ms": 1_500,
        "reason": "recovered",
        "started_ms": 1_000,
        "stream_id": "l2Book:BTC",
    }


def test_stream_record_round_trip_is_canonical() -> None:
    event = StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MarketId("", "BTC"),
        exchange_time_ms=2_000,
        receive_time=datetime.fromtimestamp(2, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key="ctx-1",
        payload={
            "mark_px": Decimal("100"),
            "mid_px": Decimal("100.1"),
            "oracle_px": Decimal("99.9"),
            "funding": Decimal("0.0001"),
            "open_interest": Decimal("50"),
        },
    )
    record = _record_from_stream(event)
    restored = _record_from_payload(_record_payload(record))
    assert restored == record
    assert RUN_ID == "continuous-paper-mainnet-v1"



def test_runtime_source_exposes_structured_live_heartbeat() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8")
    assert "COCOMELON_PAPER_HEARTBEAT " in source
    assert '"paper_only": True' in source
    assert '"live_orders": False' in source
    assert '"positions": positions' in source
    assert '"stop_price": str(position.stop_price)' in source
    assert '"session_decision_epochs"' in source
    assert '"session_decisions"' in source
    assert '"session_risk"' in source
    assert '"open_planned_risk"' in source
    assert '"open_planned_risk_fraction_of_equity"' in source


def test_record_pump_counts_each_closed_trade_once() -> None:
    trade = SimpleNamespace(trade_id="trade-1")

    class Pipeline:
        def on_record(self, _record: ReplayRecord, _now_ms: int) -> tuple[object, ...]:
            return ()

        def finalize(self, _end_ms: int) -> tuple[SimpleNamespace, ...]:
            return (trade,)

    class Journal:
        def __init__(self) -> None:
            self.recorded: list[str] = []

        def iter_trades(self) -> tuple[object, ...]:
            return ()

        def record_observation(self, _observation: object) -> None:
            raise AssertionError("no observations expected")

        def record_trade(self, item: SimpleNamespace) -> None:
            self.recorded.append(item.trade_id)

    journal = Journal()
    pump = _RecordPump(
        Pipeline(),  # type: ignore[arg-type]
        journal,  # type: ignore[arg-type]
        last_available_at_ms=0,
    )
    record = ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=1,
        source="fixture",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key="gap-1",
        payload_json='{"started_ms":1,"ended_ms":1,"reason":"fixture","stream_id":"x"}',
        event_kind=None,
    )
    second_record = ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=2,
        source="fixture",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key="gap-2",
        payload_json='{"started_ms":2,"ended_ms":2,"reason":"fixture","stream_id":"x"}',
        event_kind=None,
    )
    asyncio.run(pump.process(record))
    asyncio.run(pump.process(second_record))

    assert journal.recorded == ["trade-1"]
    assert pump.closed_trades == 1


def test_position_action_checkpoint_round_trip() -> None:
    action = PositionAction(
        action_type=PositionActionType.TIGHTEN_STOP,
        market=MarketId("", "BTC"),
        quantity=None,
        new_stop_price=Decimal("99.5"),
        reason_codes=("TRAILING_STOP",),
        timestamp_ms=1_700_000_000_000,
    )

    restored = _position_action_from_payload(_position_action_payload(action))

    assert restored == action


def test_legacy_checkpoint_without_position_actions_remains_loadable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": RUN_ID,
                "last_available_at_ms": 123,
                "selected_markets": ["BTC"],
                "open_lifecycles": [
                    {
                        "market": "BTC",
                        "opening_plan_id": "plan-1",
                        "feature_snapshot_id": "feature-1",
                        "equity_before": "10000",
                        "exit_plan_ids": [],
                        "mark_observations": [],
                    }
                ],
                "known_gap_intervals": [],
                "execution_mode": "paper",
                "live_orders": False,
            }
        ),
        encoding="utf-8",
    )

    checkpoints, gaps, last_available_at_ms = _load_checkpoint(path)

    assert last_available_at_ms == 123
    assert gaps == ()
    assert len(checkpoints) == 1
    assert checkpoints[0].position_actions == ()



def test_record_pump_drops_duplicate_event_keys() -> None:
    class Pipeline:
        def __init__(self) -> None:
            self.calls = 0

        def on_record(self, _record: ReplayRecord, _now_ms: int) -> tuple[object, ...]:
            self.calls += 1
            return ()

        def finalize(self, _end_ms: int) -> tuple[object, ...]:
            return ()

    class Journal:
        def iter_trades(self) -> tuple[object, ...]:
            return ()

        def record_observation(self, _observation: object) -> None:
            raise AssertionError("no observations expected")

        def record_trade(self, _trade: object) -> None:
            raise AssertionError("no trades expected")

    pipeline = Pipeline()
    pump = _RecordPump(
        pipeline,  # type: ignore[arg-type]
        Journal(),  # type: ignore[arg-type]
        last_available_at_ms=0,
    )
    record = ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=1,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="BTC",
        exchange_time_ms=1,
        event_key="duplicate-key",
        payload_json='{"mark_px":"100"}',
        event_kind="active_asset_ctx",
    )

    asyncio.run(pump.process(record))
    asyncio.run(pump.process(record))

    assert pipeline.calls == 1
    assert pump.processed_records == 1
    assert pump.duplicate_records_dropped == 1


def test_supervisor_group_readiness_requires_every_lane_event() -> None:
    async def scenario() -> bool:
        lane_a = asyncio.Event()
        lane_b = asyncio.Event()
        lane_a.set()
        lane_b.set()
        sleeper = asyncio.create_task(asyncio.sleep(60))
        group = _SupervisorGroup(
            supervisors=(),
            tasks=(sleeper,),
            forward_gaps=asyncio.Event(),
            ready_lanes=(lane_a, lane_b),
        )
        try:
            return await _wait_supervisor_group_ready(
                group,
                timeout_seconds=0.1,
                poll_seconds=0.01,
            )
        finally:
            sleeper.cancel()
            await asyncio.gather(sleeper, return_exceptions=True)

    assert asyncio.run(scenario()) is True


def test_rotation_source_promotes_replacement_before_retiring_previous() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8")
    start_index = source.index(
        "replacement_group = await start_supervisors("
    )
    readiness_index = source.index(
        "replacement_ready = await _wait_supervisor_group_ready(",
        start_index,
    )
    promote_index = source.index(
        "supervisor_group = replacement_group",
        readiness_index,
    )
    retire_index = source.index(
        "await _cancel_supervisor_group(previous_group)",
        promote_index,
    )

    assert start_index < readiness_index < promote_index < retire_index
    assert "forward_gaps=False" in source[start_index:readiness_index + 300]
    assert "ready_lanes[lane].set()" in source



def test_supervisor_group_readiness_rejects_completed_task() -> None:
    async def scenario() -> bool:
        lane_a = asyncio.Event()
        lane_b = asyncio.Event()
        lane_a.set()
        lane_b.set()
        completed = asyncio.create_task(asyncio.sleep(0))
        await completed
        group = _SupervisorGroup(
            supervisors=(),
            tasks=(completed,),
            forward_gaps=asyncio.Event(),
            ready_lanes=(lane_a, lane_b),
        )
        return await _wait_supervisor_group_ready(
            group,
            timeout_seconds=0.1,
            poll_seconds=0.01,
        )

    assert asyncio.run(scenario()) is False
