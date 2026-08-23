from __future__ import annotations

from collections.abc import Iterator

import pytest
from cocomelon.replay.adapters import EvidenceClassError, ReplayRequirements
from cocomelon.replay.engine import ReplayEngine, ReplayPipeline

from cocomelon.domain.journal import JournalObservation, ObservationKind
from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    ReplayRecord,
    SourceRecordKind,
    SourceSegment,
)
from cocomelon.journal.store import JournalStore


class MemoryReplaySource:
    def __init__(self, records: tuple[ReplayRecord, ...]) -> None:
        self.records = records

    def iter_records(self, manifest: ReplayManifest) -> Iterator[ReplayRecord]:
        del manifest
        yield from self.records


def record(
    *,
    available_at_ms: int,
    kind: str,
    payload_json: str = "{}",
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=available_at_ms,
        source="fixture",
        schema_version=1,
        market="SOL",
        exchange_time_ms=available_at_ms - 1,
        event_key=f"{kind}:{available_at_ms}",
        payload_json=payload_json,
        event_kind=kind,
    )


def gap(*, available_at_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=available_at_ms,
        source="fixture",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key=f"gap:{available_at_ms}",
        payload_json=(
            '{"ended_ms":null,"reason":"disconnect",'
            f'"started_ms":{available_at_ms},"stream_id":"l2Book:SOL"}}'
        ),
        event_kind=None,
    )


def manifest(evidence_class: EvidenceClass) -> ReplayManifest:
    return ReplayManifest(
        evidence_class=evidence_class,
        start_ms=100,
        end_ms=400,
        segments=(
            SourceSegment(
                relative_path="events/fixture.jsonl",
                partition="events",
                sha256="a" * 64,
                byte_count=1,
                row_count=1,
                schema_version=1,
                first_available_at_ms=100,
                last_available_at_ms=400,
            ),
        ),
        gap_refs=(),
        code_revision="test-revision",
        config_digest="b" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="fees-v1",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def observation(
    kind: ObservationKind,
    timestamp_ms: int,
    *,
    strategy_decision_id: str | None = None,
    account_state_id: str | None = None,
) -> JournalObservation:
    return JournalObservation(
        kind=kind,
        timestamp_ms=timestamp_ms,
        market=None,
        feature_snapshot_id=("feature-1" if strategy_decision_id is not None else None),
        strategy_decision_id=strategy_decision_id,
        risk_decision_id=None,
        plan_id=None,
        attempt_id=None,
        position_action_id=None,
        account_state_id=account_state_id,
        reason_codes=(),
        health_refs=(),
        replay_run_id=None,
    )


def pipeline(order: list[int]) -> ReplayPipeline:
    def on_record(item: ReplayRecord, now_ms: int) -> tuple[JournalObservation, ...]:
        order.append(now_ms)
        if item.record_kind is SourceRecordKind.DATA_GAP:
            return ()
        if item.event_kind == "candle":
            return (
                observation(
                    ObservationKind.STRATEGY_DECISION,
                    now_ms,
                    strategy_decision_id=f"strategy-{now_ms}",
                ),
            )
        if item.event_kind == "active_asset_ctx":
            return (
                observation(
                    ObservationKind.ACCOUNT_STATE,
                    now_ms,
                    account_state_id=f"state-{now_ms}",
                ),
            )
        return ()

    return ReplayPipeline(on_record=on_record, finalize=lambda _: ())


def test_replay_orders_shuffled_records_and_is_idempotent(tmp_path) -> None:
    source = MemoryReplaySource(
        (
            record(available_at_ms=300, kind="active_asset_ctx"),
            gap(available_at_ms=200),
            record(available_at_ms=100, kind="candle"),
        )
    )
    journal = JournalStore(tmp_path / "journal.sqlite")
    first_order: list[int] = []
    first = ReplayEngine(source, journal, pipeline(first_order)).run(
        manifest(EvidenceClass.CANDLE_CONTEXT)
    )

    second_order: list[int] = []
    second = ReplayEngine(source, journal, pipeline(second_order)).run(
        manifest(EvidenceClass.CANDLE_CONTEXT)
    )

    assert first_order == [100, 200, 300]
    assert second_order == first_order
    assert first == second
    assert first.result_digest == second.result_digest
    assert first.processed_events == 2
    assert first.processed_gaps == 1
    assert first.strategy_decisions == 1
    assert first.journal_observations == 2
    assert first.final_account_state_id == "state-300"
    assert first.data_complete is False
    journal.close()


def test_candle_context_rejects_recorded_microstructure(tmp_path) -> None:
    source = MemoryReplaySource((record(available_at_ms=100, kind="l2_book"),))
    journal = JournalStore(tmp_path / "journal.sqlite")

    with pytest.raises(EvidenceClassError, match="CANDLE_CONTEXT"):
        ReplayEngine(source, journal, pipeline([])).run(manifest(EvidenceClass.CANDLE_CONTEXT))
    journal.close()


def test_required_l2_fails_closed_when_microstructure_recording_has_no_book(tmp_path) -> None:
    source = MemoryReplaySource((record(available_at_ms=100, kind="trade"),))
    journal = JournalStore(tmp_path / "journal.sqlite")
    strict = ReplayPipeline(
        on_record=lambda _record, _now_ms: (),
        finalize=lambda _: (),
        requirements=ReplayRequirements(requires_l2=True),
    )

    with pytest.raises(EvidenceClassError, match="l2"):
        ReplayEngine(source, journal, strict).run(manifest(EvidenceClass.MICROSTRUCTURE))
    journal.close()
