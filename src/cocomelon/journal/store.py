from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cocomelon.domain.replay import (
    JournalRecord,
    JournalRecordType,
    canonical_json_bytes,
)

SCHEMA_VERSION = 1


def _canonical_text(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _payload_from_json(value: str) -> dict[str, object]:
    parsed: Any = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("journal payload must be a JSON object")
    return parsed


class JournalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS journal_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS journal_records (
                    journal_id TEXT PRIMARY KEY,
                    record_type TEXT NOT NULL,
                    occurred_at_ms INTEGER NOT NULL,
                    recorded_at_ms INTEGER NOT NULL,
                    market TEXT,
                    decision_id TEXT,
                    risk_decision_id TEXT,
                    plan_id TEXT,
                    attempt_id TEXT,
                    fill_id TEXT,
                    position_id TEXT,
                    funding_record_id TEXT,
                    replay_id TEXT,
                    schema_version INTEGER NOT NULL,
                    code_version TEXT NOT NULL,
                    config_version TEXT NOT NULL,
                    logical_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS journal_records_order_idx
                    ON journal_records(occurred_at_ms, journal_id);
                CREATE INDEX IF NOT EXISTS journal_records_replay_idx
                    ON journal_records(replay_id, occurred_at_ms, journal_id);
                """
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO journal_meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def close(self) -> None:
        self._conn.close()

    def raw_connection(self) -> sqlite3.Connection:
        return self._conn

    def _append_in_transaction(self, record: JournalRecord) -> None:
        logical_json = _canonical_text(record.logical_content())
        payload_json = _canonical_text(record.payload)
        existing = self._conn.execute(
            "SELECT logical_json FROM journal_records WHERE journal_id = ?",
            (record.journal_id,),
        ).fetchone()
        if existing is not None:
            if existing[0] != logical_json:
                raise ValueError(
                    f"immutable journal payload mismatch for {record.journal_id}"
                )
            return

        self._conn.execute(
            """
            INSERT INTO journal_records(
                journal_id,
                record_type,
                occurred_at_ms,
                recorded_at_ms,
                market,
                decision_id,
                risk_decision_id,
                plan_id,
                attempt_id,
                fill_id,
                position_id,
                funding_record_id,
                replay_id,
                schema_version,
                code_version,
                config_version,
                logical_json,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.journal_id,
                record.record_type.value,
                record.occurred_at_ms,
                record.recorded_at_ms,
                record.market,
                record.decision_id,
                record.risk_decision_id,
                record.plan_id,
                record.attempt_id,
                record.fill_id,
                record.position_id,
                record.funding_record_id,
                record.replay_id,
                record.schema_version,
                record.code_version,
                record.config_version,
                logical_json,
                payload_json,
            ),
        )

    def append(self, record: JournalRecord) -> None:
        with self._conn:
            self._append_in_transaction(record)

    def append_many(self, records: Sequence[JournalRecord]) -> None:
        with self._conn:
            for record in records:
                self._append_in_transaction(record)

    def _row_to_record(self, row: sqlite3.Row | tuple[object, ...]) -> JournalRecord:
        return JournalRecord(
            record_type=JournalRecordType(str(row[1])),
            occurred_at_ms=int(row[2]),
            recorded_at_ms=int(row[3]),
            market=None if row[4] is None else str(row[4]),
            decision_id=None if row[5] is None else str(row[5]),
            risk_decision_id=None if row[6] is None else str(row[6]),
            plan_id=None if row[7] is None else str(row[7]),
            attempt_id=None if row[8] is None else str(row[8]),
            fill_id=None if row[9] is None else str(row[9]),
            position_id=None if row[10] is None else str(row[10]),
            funding_record_id=None if row[11] is None else str(row[11]),
            replay_id=None if row[12] is None else str(row[12]),
            schema_version=int(row[13]),
            code_version=str(row[14]),
            config_version=str(row[15]),
            payload=_payload_from_json(str(row[16])),
        )

    def get(self, journal_id: str) -> JournalRecord | None:
        row = self._conn.execute(
            """
            SELECT
                journal_id,
                record_type,
                occurred_at_ms,
                recorded_at_ms,
                market,
                decision_id,
                risk_decision_id,
                plan_id,
                attempt_id,
                fill_id,
                position_id,
                funding_record_id,
                replay_id,
                schema_version,
                code_version,
                config_version,
                payload_json
            FROM journal_records
            WHERE journal_id = ?
            """,
            (journal_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def iter_records(self, *, replay_id: str | None = None) -> tuple[JournalRecord, ...]:
        columns = """
            journal_id,
            record_type,
            occurred_at_ms,
            recorded_at_ms,
            market,
            decision_id,
            risk_decision_id,
            plan_id,
            attempt_id,
            fill_id,
            position_id,
            funding_record_id,
            replay_id,
            schema_version,
            code_version,
            config_version,
            payload_json
        """
        if replay_id is None:
            rows = self._conn.execute(
                f"SELECT {columns} FROM journal_records "
                "ORDER BY occurred_at_ms, journal_id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {columns} FROM journal_records WHERE replay_id = ? "
                "ORDER BY occurred_at_ms, journal_id",
                (replay_id,),
            ).fetchall()
        return tuple(self._row_to_record(row) for row in rows)

    def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in ("journal_meta", "journal_records"):
            row = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            if row is None:
                raise RuntimeError(f"missing count result for {table}")
            counts[table] = int(row[0])
        return counts
