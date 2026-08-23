from __future__ import annotations

import json
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
from cocomelon.replay.engine import ReplayEngine, ReplayPipeline


class MemoryReplaySource:
    def __init__(self, records: tuple[ReplayRecord, ...]) -> None:
        self.records = records

    def iter_records(self, manifest: ReplayManifest) -> Iterator[ReplayRecord]:
        del manifest
        yield from self.records


def record(available_at_ms: int, kind: str, payload: dict[str, object]) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=available_at_ms,
        source="fixture",
        schema_version=1,
        market="SOL",
        exchange_time_ms=available_at_ms - 1,
        event_key=f"{kind}:{available_at_ms}",
        payload_json=json.dumps(payload),
        event_kind=kind,
    )


def manifest() -> ReplayManifest:
    return ReplayManifest(
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
        start_ms=100,
        end_ms=300,
        segments=(
            SourceSegment(
                relative_path="events/lookahead.jsonl",
                partition="events",
                sha256="c" * 64,
                byte_count=1,
                row_count=3,
                schema_version=1,
                first_available_at_ms=100,
                last_available_at_ms=300,
            ),
        ),
        gap_refs=(),
        code_revision="test-revision",
        config_digest="d" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="fees-v1",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def make_pipeline(captured: list[JournalObservation]) -> ReplayPipeline:
    latest_mark: str | None = None

    def on_record(item: ReplayRecord, now_ms: int) -> tuple[JournalObservation, ...]:
        nonlocal latest_mark
        if item.event_kind == "active_asset_ctx":
            raw_mark = item.payload.get("mark_px")
            latest_mark = str(raw_mark)
            observation = JournalObservation(
                kind=ObservationKind.ACCOUNT_STATE,
                timestamp_ms=now_ms,
                market=None,
                feature_snapshot_id=None,
                strategy_decision_id=None,
                risk_decision_id=None,
                plan_id=None,
                attempt_id=None,
                position_action_id=None,
                account_state_id=f"state-{now_ms}-{latest_mark}",
                reason_codes=(),
                health_refs=(f"mark:{latest_mark}",),
                replay_run_id=None,
            )
            captured.append(observation)
            return (observation,)
        if item.event_kind == "candle":
            observation = JournalObservation(
                kind=ObservationKind.STRATEGY_DECISION,
                timestamp_ms=now_ms,
                market=None,
                feature_snapshot_id="feature-200",
                strategy_decision_id=f"decision-200-mark-{latest_mark}",
                risk_decision_id=None,
                plan_id=None,
                attempt_id=None,
                position_action_id=None,
                account_state_id=None,
                reason_codes=("FIXTURE_DECISION",),
                health_refs=(f"mark:{latest_mark}",),
                replay_run_id=None,
            )
            captured.append(observation)
            return (observation,)
        return ()

    return ReplayPipeline(on_record=on_record, finalize=lambda _: ())


def run_fixture(tmp_path, future_mark: str) -> tuple[JournalObservation, ...]:
    source = MemoryReplaySource(
        (
            record(300, "active_asset_ctx", {"mark_px": future_mark}),
            record(200, "candle", {"close_px": "100"}),
            record(100, "active_asset_ctx", {"mark_px": "100"}),
        )
    )
    captured: list[JournalObservation] = []
    journal = JournalStore(tmp_path / f"journal-{future_mark}.sqlite")
    ReplayEngine(source, journal, make_pipeline(captured)).run(manifest())
    journal.close()
    return tuple(captured)


def test_future_values_do_not_change_pre_availability_observations(tmp_path) -> None:
    high_future = run_fixture(tmp_path, "1000")
    low_future = run_fixture(tmp_path, "1")

    high_pre = tuple(item for item in high_future if item.timestamp_ms < 300)
    low_pre = tuple(item for item in low_future if item.timestamp_ms < 300)
    assert tuple(item.observation_id for item in high_pre) == tuple(
        item.observation_id for item in low_pre
    )
    assert high_pre[1].strategy_decision_id == "decision-200-mark-100"
    assert low_pre[1].strategy_decision_id == "decision-200-mark-100"

    high_future_observation = tuple(item for item in high_future if item.timestamp_ms == 300)
    low_future_observation = tuple(item for item in low_future if item.timestamp_ms == 300)
    assert high_future_observation[0].observation_id != low_future_observation[0].observation_id
