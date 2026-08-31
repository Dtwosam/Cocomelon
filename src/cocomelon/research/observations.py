from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from cocomelon.research.registry import ResearchRegistryError


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def ensure_observation_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_trade_observations (
            candidate_id TEXT NOT NULL,
            trade_id TEXT NOT NULL,
            closed_at_ms INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(candidate_id, trade_id),
            FOREIGN KEY(candidate_id) REFERENCES research_candidates(candidate_id)
        )
        """
    )
    connection.commit()


def record_trade_observations(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    observations: Iterable[dict[str, object]],
) -> None:
    ensure_observation_schema(connection)
    with connection:
        for observation in observations:
            trade_id = observation.get("trade_id")
            closed_at_ms = observation.get("closed_at_ms")
            if not isinstance(trade_id, str) or not trade_id.strip():
                raise ResearchRegistryError("research observation trade_id is invalid")
            if isinstance(closed_at_ms, bool) or not isinstance(closed_at_ms, int):
                raise ResearchRegistryError("research observation closed_at_ms is invalid")

            payload_json = _canonical_json(observation)
            existing = connection.execute(
                """
                SELECT payload_json
                FROM research_trade_observations
                WHERE candidate_id = ? AND trade_id = ?
                """,
                (candidate_id, trade_id),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ResearchRegistryError(
                        f"research observation already exists with different data: {trade_id}"
                    )
                continue

            connection.execute(
                """
                INSERT INTO research_trade_observations (
                    candidate_id, trade_id, closed_at_ms, payload_json
                ) VALUES (?, ?, ?, ?)
                """,
                (candidate_id, trade_id, closed_at_ms, payload_json),
            )


def load_trade_observations(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> tuple[dict[str, object], ...]:
    ensure_observation_schema(connection)
    rows = connection.execute(
        """
        SELECT payload_json
        FROM research_trade_observations
        WHERE candidate_id = ?
        ORDER BY closed_at_ms, trade_id
        """,
        (candidate_id,),
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            raise ResearchRegistryError("stored research observation is invalid")
        result.append(payload)
    return tuple(result)
