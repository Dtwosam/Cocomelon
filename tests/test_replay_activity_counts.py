from __future__ import annotations

from collections.abc import Iterator

from cocomelon.domain.journal import JournalObservation, ObservationKind
from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    ReplayRecord,
    SourceRecordKind,
    SourceSegment,
)
from cocomelon.journal.store import JournalStore
from cocomelon.replay.engine import ReplayActivity, ReplayEngine, ReplayPipeline


class MemoryReplaySource:
    def iter_records(self, manifest: ReplayManifest) -> Iterator[ReplayRecord]:
        del manifest
        yield ReplayRecord(
            record_kind=SourceRecordKind.NORMALIZED_EVENT,
            available_at_ms=100,
            source="fixture",
            schema_version=1,
            market="BTC",
            exchange_time_ms=99,
            event_key="l2Book:BTC:100",
            payload_json="{}",
            event_kind="l2_book",
        )


def manifest() -> ReplayManifest:
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=100,
        end_ms=200,
        segments=(
            SourceSegment(
                relative_path="events/fixture.jsonl",
                partition="events",
                sha256="a" * 64,
                byte_count=1,
                row_count=1,
                schema_version=1,
                first_available_at_ms=100,
                last_available_at_ms=100,
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


def test_replay_result_counts_open_activity_without_requiring_closed_trade(tmp_path) -> None:
    def on_record(_record: ReplayRecord, now_ms: int) -> tuple[JournalObservation, ...]:
        return (
            JournalObservation(
                kind=ObservationKind.ACCOUNT_STATE,
                timestamp_ms=now_ms,
                market=None,
                feature_snapshot_id=None,
                strategy_decision_id=None,
                risk_decision_id=None,
                plan_id=None,
                attempt_id=None,
                position_action_id=None,
                account_state_id="state-open-position",
                reason_codes=(),
                health_refs=(),
                replay_run_id=None,
            ),
        )

    pipeline = ReplayPipeline(
        on_record=on_record,
        finalize=lambda _end_ms: (),
        activity=lambda: ReplayActivity(fills=1, opened_positions=1, closed_positions=0),
    )
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        result = ReplayEngine(MemoryReplaySource(), journal, pipeline).run(manifest())
    finally:
        journal.close()

    assert result.closed_trade_ids == ()
    assert result.fills == 1
    assert result.opened_positions == 1
    assert result.closed_positions == 0
