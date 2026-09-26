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
    _position_protection_metrics,
    _record_from_gap,
    _record_from_payload,
    _record_from_stream,
    _record_payload,
    _RecordPump,
    _restore_cadence_shadow,
)
from cocomelon.domain.execution import PositionAction, PositionActionType
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.contracts import BaselineReplayConfig


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
    assert '"recent_closed_trades"' in source
    assert '"session_closed_trades"' in source
    assert '"net_pnl": str(trade.net_pnl)' in source
    assert '"net_r": str(trade.net_r)' in source
    assert '"exit_reason": trade.exit_reason' in source
    assert 'CADENCE_SHADOW_STATE_FILENAME = "cadence-shadow-state.json"' in source
    assert "pump.cadence_shadow.state_payload()" in source
    assert 'ContinuousPaperTradePathStore(root / "trade-paths")' in source
    assert "closed_lifecycle_sink=trade_path_sink" in source
    assert '"trade_path_count": self.trade_path_count' in source
    assert '"trade_path_state_digest": self.trade_path_state_digest' in source
    assert '"trade_path_capture_error": self.trade_path_capture_error' in source


def test_position_protection_metrics_handle_long_and_short_stops() -> None:
    long = _position_protection_metrics(
        side="long",
        quantity=Decimal("2"),
        entry_price=Decimal("100"),
        stop_price=Decimal("102"),
        latest_mark=Decimal("104"),
        planned_risk=Decimal("10"),
    )
    short = _position_protection_metrics(
        side="short",
        quantity=Decimal("2"),
        entry_price=Decimal("100"),
        stop_price=Decimal("98"),
        latest_mark=Decimal("96"),
        planned_risk=Decimal("10"),
    )

    assert long["unrealized_gross_pnl"] == "8"
    assert long["current_gross_r"] == "0.8"
    assert long["stop_trigger_gross_pnl"] == "4"
    assert long["stop_trigger_gross_r"] == "0.4"
    assert long["stop_protects_profit"] is True

    assert short["unrealized_gross_pnl"] == "8"
    assert short["current_gross_r"] == "0.8"
    assert short["stop_trigger_gross_pnl"] == "4"
    assert short["stop_trigger_gross_r"] == "0.4"
    assert short["stop_protects_profit"] is True


def test_position_protection_metrics_allow_legacy_zero_planned_risk() -> None:
    metrics = _position_protection_metrics(
        side="long",
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        stop_price=Decimal("99"),
        latest_mark=Decimal("101"),
        planned_risk=Decimal("0"),
    )

    assert metrics["unrealized_gross_pnl"] == "1"
    assert metrics["current_gross_r"] is None
    assert metrics["stop_trigger_gross_pnl"] == "-1"
    assert metrics["stop_trigger_gross_r"] is None
    assert metrics["stop_protects_profit"] is False


def test_position_protection_metrics_keep_unprotected_stop_negative() -> None:
    metrics = _position_protection_metrics(
        side="short",
        quantity=Decimal("5"),
        entry_price=Decimal("100"),
        stop_price=Decimal("102"),
        latest_mark=None,
        planned_risk=Decimal("10"),
    )

    assert metrics["unrealized_gross_pnl"] is None
    assert metrics["current_gross_r"] is None
    assert metrics["stop_trigger_gross_pnl"] == "-10"
    assert metrics["stop_trigger_gross_r"] == "-1"
    assert metrics["stop_protects_profit"] is False


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
    asyncio.run(pump.process(record))
    asyncio.run(pump.process(record))

    assert journal.recorded == ["trade-1"]
    assert pump.closed_trades == 1
    assert pump.session_closed_trades == 1


def test_record_pump_disables_failing_cadence_shadow() -> None:
    class Pipeline:
        def on_record(
            self,
            _record: ReplayRecord,
            _now_ms: int,
        ) -> tuple[object, ...]:
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

    class FailingShadow:
        def observe(self, _record: ReplayRecord, _now_ms: int) -> None:
            raise RuntimeError("diagnostic boom")

    pump = _RecordPump(
        Pipeline(),  # type: ignore[arg-type]
        Journal(),  # type: ignore[arg-type]
        last_available_at_ms=0,
        cadence_shadow=FailingShadow(),  # type: ignore[arg-type]
    )
    record = ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=1,
        source="fixture",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key="gap-shadow",
        payload_json=(
            '{"started_ms":1,"ended_ms":1,"reason":"fixture","stream_id":"x"}'
        ),
        event_kind=None,
    )

    asyncio.run(pump.process(record))

    assert pump.cadence_shadow is None
    payload = pump.cadence_shadow_payload()
    assert payload["enabled"] is False
    assert payload["execution_authority"] is False
    assert payload["error"] == "RuntimeError: diagnostic boom"


def test_cadence_shadow_restore_failure_is_fail_open(tmp_path: Path) -> None:
    path = tmp_path / "cadence-shadow-state.json"
    path.write_text("{not-json", encoding="utf-8")

    shadow = _restore_cadence_shadow(
        path,
        (MarketId("", "BTC"),),
        replay_config=BaselineReplayConfig(),
    )

    payload = shadow.summary_payload()
    assert payload["state_restored"] is False
    assert payload["durable_state"] is True
    assert "JSONDecodeError" in str(payload["state_restore_error"])


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



def test_continuous_runtime_honors_upgrade_stop_file_contract() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8")
    cli = Path("src/cocomelon/continuous_paper_cli.py").read_text(encoding="utf-8")
    assert 'stop_file: str | Path | None = None' in source
    assert 'exit_reason = "upgrade_requested"' in source
    assert '"exit_reason": self.exit_reason' in source
    assert 'parser.add_argument("--stop-file", type=Path)' in cli
    assert "stop_file=args.stop_file" in cli


def test_runtime_persists_authenticated_learning_features() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8")
    assert "LearningFeatureSnapshotStore(root / \"learning-features\")" in source
    assert "feature_snapshot_sink=feature_store" in source
    assert '"feature_snapshot_count": self.feature_snapshot_count' in source
    assert (
        '"feature_snapshot_state_digest": self.feature_snapshot_state_digest'
        in source
    )


def test_runtime_persists_opening_runtime_lineage() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8")
    assert "ContinuousPaperOpeningLineageStore(" in source
    assert 'root / "opening-lineage"' in source
    assert "_ContinuousOpeningLineageSink" in source
    assert "opening_lifecycle_sink=" in source
    assert '"opening_lineage_count": self.opening_lineage_count' in source
    assert '"opening_lineage_state_digest": self.opening_lineage_state_digest' in source
