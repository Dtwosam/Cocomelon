import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.journal import JournalObservation, ObservationKind
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, SourceSegment
from cocomelon.journal.store import JournalConsistencyError, JournalStore

MARKET = MarketId("", "SOL")


def observation(*, reason_codes: tuple[str, ...] = ("trend",)) -> JournalObservation:
    return JournalObservation(
        kind=ObservationKind.STRATEGY_DECISION,
        timestamp_ms=1_000,
        market=MARKET,
        feature_snapshot_id="feature-1",
        strategy_decision_id="strategy-1",
        risk_decision_id=None,
        plan_id=None,
        attempt_id=None,
        position_action_id=None,
        account_state_id=None,
        reason_codes=reason_codes,
        health_refs=(),
        replay_run_id="run-1",
    )


def manifest() -> ReplayManifest:
    segment = SourceSegment(
        relative_path="events/a.jsonl",
        partition="events/2026-08-23/candle/SOL",
        sha256="a" * 64,
        byte_count=100,
        row_count=2,
        schema_version=1,
        first_available_at_ms=1_000,
        last_available_at_ms=2_000,
    )
    return ReplayManifest(
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
        start_ms=1_000,
        end_ms=2_000,
        segments=(segment,),
        gap_refs=(),
        code_revision="abc123",
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version=None,
        fee_schedule_id=None,
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def test_schema_contains_separate_journal_and_replay_tables(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    store.close()

    with sqlite3.connect(tmp_path / "journal.sqlite3") as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "journal_meta",
        "journal_observations",
        "journal_trades",
        "journal_trade_refs",
        "replay_manifests",
        "replay_runs",
        "compaction_manifests",
    } <= names


def test_identical_observation_retry_is_idempotent(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    item = observation()

    store.record_observation(item)
    store.record_observation(item)

    assert store.load_observation(item.observation_id) == item
    store.close()


def test_conflicting_duplicate_observation_id_fails_closed(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    item = observation()
    store.record_observation(item)

    changed_payload = store._canonical_observation(observation(reason_codes=("other",)))
    with store.connection:
        store.connection.execute(
            "UPDATE journal_observations SET payload_json = ? WHERE observation_id = ?",
            (changed_payload, item.observation_id),
        )

    with pytest.raises(JournalConsistencyError, match="conflicting"):
        store.record_observation(item)
    store.close()


def test_manifest_retry_is_idempotent_and_restart_safe(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    item = manifest()
    first = JournalStore(path)
    first.record_manifest(item)
    first.record_manifest(item)
    first.close()

    reopened = JournalStore(path)
    assert reopened.load_manifest(item.manifest_id) == item
    reopened.close()


def test_failed_multirow_write_rolls_back(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    item = observation()

    def fail_after_primary() -> None:
        raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        store._record_observation_transaction(item, after_primary=fail_after_primary)

    assert store.load_observation(item.observation_id) is None
    store.close()


def test_canonical_payload_preserves_decimal_strings_not_floats(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    payload = store._canonical_json({"risk": Decimal("0.002500")})

    assert payload == '{"risk":"0.002500"}'
    store.close()
