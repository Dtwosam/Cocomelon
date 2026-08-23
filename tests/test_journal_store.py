import sqlite3
from pathlib import Path

import pytest
from cocomelon.journal.store import JournalStore

from cocomelon.domain.replay import JournalRecord, JournalRecordType


def record(
    record_type: JournalRecordType = JournalRecordType.STRATEGY_DECISION,
    *,
    occurred_at_ms: int = 1_000,
    recorded_at_ms: int = 1_010,
    market: str | None = "BTC",
    replay_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> JournalRecord:
    return JournalRecord(
        record_type=record_type,
        occurred_at_ms=occurred_at_ms,
        recorded_at_ms=recorded_at_ms,
        code_version="abc123",
        config_version="phase8-test",
        payload=payload or {"direction": "NO_TRADE", "reason_codes": ["NO_EDGE"]},
        market=market,
        decision_id="decision-1" if record_type is JournalRecordType.STRATEGY_DECISION else None,
        fill_id="fill-1" if record_type is JournalRecordType.FILL else None,
        replay_id=replay_id,
    )


def test_store_creates_only_phase8_journal_tables(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    store = JournalStore(path)
    store.close()

    with sqlite3.connect(path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    assert tables == {"journal_meta", "journal_records"}


def test_duplicate_logical_record_is_idempotent_and_keeps_first_recorded_time(
    tmp_path: Path,
) -> None:
    path = tmp_path / "journal.sqlite3"
    first = record(recorded_at_ms=1_010)
    duplicate = record(recorded_at_ms=9_999)
    assert first.journal_id == duplicate.journal_id

    store = JournalStore(path)
    store.append(first)
    store.append(duplicate)

    loaded = store.get(first.journal_id)
    assert loaded is not None
    assert loaded.recorded_at_ms == 1_010
    assert store.table_counts()["journal_records"] == 1
    store.close()


def test_tampered_same_id_payload_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    item = record()
    store = JournalStore(path)
    store.append(item)

    with store.raw_connection() as conn:
        conn.execute(
            "UPDATE journal_records SET logical_json = '{}' WHERE journal_id = ?",
            (item.journal_id,),
        )

    with pytest.raises(ValueError, match="immutable journal payload mismatch"):
        store.append(item)
    store.close()


def test_append_many_is_atomic_on_injected_second_record_failure(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    strategy = record()
    fill = record(
        JournalRecordType.FILL,
        occurred_at_ms=1_100,
        payload={"price": "100", "quantity": "1"},
    )
    store = JournalStore(path)

    with store.raw_connection() as conn:
        conn.execute(
            "CREATE TRIGGER reject_fill BEFORE INSERT ON journal_records "
            "WHEN NEW.record_type = 'fill' "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        store.append_many((strategy, fill))

    assert store.table_counts()["journal_records"] == 0
    store.close()


def test_restart_round_trip_and_deterministic_iteration_order(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    later = record(
        JournalRecordType.FILL,
        occurred_at_ms=2_000,
        payload={"price": "101", "quantity": "1"},
    )
    tie_b = record(
        JournalRecordType.ACCOUNT_SNAPSHOT,
        occurred_at_ms=1_000,
        market=None,
        payload={"equity": "10001"},
    )
    tie_a = record(
        JournalRecordType.RISK_DECISION,
        occurred_at_ms=1_000,
        payload={"approved": False, "reason_codes": ["DAILY_LOCKOUT"]},
    )

    store = JournalStore(path)
    store.append_many((later, tie_b, tie_a))
    store.close()

    reopened = JournalStore(path)
    loaded = reopened.iter_records()
    reopened.close()

    assert tuple((item.occurred_at_ms, item.journal_id) for item in loaded) == tuple(
        sorted((item.occurred_at_ms, item.journal_id) for item in (later, tie_b, tie_a))
    )
    assert {item.journal_id for item in loaded} == {
        later.journal_id,
        tie_b.journal_id,
        tie_a.journal_id,
    }


def test_replay_filter_returns_only_requested_namespace(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    original = record(replay_id=None)
    replay_a = record(
        JournalRecordType.RISK_DECISION,
        replay_id="replay-a",
        payload={"approved": True},
    )
    replay_b = record(
        JournalRecordType.RISK_DECISION,
        replay_id="replay-b",
        payload={"approved": False},
    )

    store = JournalStore(path)
    store.append_many((original, replay_b, replay_a))

    assert tuple(item.journal_id for item in store.iter_records(replay_id="replay-a")) == (
        replay_a.journal_id,
    )
    store.close()
