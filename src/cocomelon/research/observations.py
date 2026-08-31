from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import cast

from cocomelon.research.attestation import ensure_batch_attestation_schema
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
            batch_id TEXT,
            trade_id TEXT NOT NULL,
            sample_id TEXT,
            closed_at_ms INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(candidate_id, trade_id),
            FOREIGN KEY(candidate_id) REFERENCES research_candidates(candidate_id),
            FOREIGN KEY(batch_id) REFERENCES research_batches(batch_id)
        )
        """
    )
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(research_trade_observations)").fetchall()
    }
    if "batch_id" not in columns:
        connection.execute("ALTER TABLE research_trade_observations ADD COLUMN batch_id TEXT")
    if "sample_id" not in columns:
        connection.execute("ALTER TABLE research_trade_observations ADD COLUMN sample_id TEXT")
    connection.commit()


def _string(observation: dict[str, object], field: str) -> str:
    value = observation.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ResearchRegistryError(f"research observation {field} is invalid")
    return value


def _attestation_for_observation(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    batch_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT b.source_id, b.replay_run_id, b.status,
               a.sample_identities_json, a.planned_risk_fractions_json
        FROM research_batches AS b
        JOIN research_batch_attestations AS a ON a.batch_id = b.batch_id
        WHERE b.batch_id = ? AND b.candidate_id = ? AND a.candidate_id = ?
        """,
        (batch_id, candidate_id, candidate_id),
    ).fetchone()
    if row is None:
        raise ResearchRegistryError(
            f"research observation batch is not authoritatively attested: {batch_id}"
        )
    typed_row = cast(sqlite3.Row, row)
    if str(typed_row["status"]) != "admitted":
        raise ResearchRegistryError("research observation batch is contaminated")
    return typed_row


def _planned_fraction(value: object) -> str:
    if not isinstance(value, str):
        raise ResearchRegistryError("research observation planned_risk_fraction is invalid")
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise ResearchRegistryError(
            "research observation planned_risk_fraction is invalid"
        ) from exc
    if not decimal.is_finite() or decimal <= 0:
        raise ResearchRegistryError("research observation planned_risk_fraction is invalid")
    return str(decimal)


def _expected_attested_sample_identities(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> set[tuple[str, str, str]]:
    rows = connection.execute(
        """
        SELECT a.batch_id, a.sample_identities_json
        FROM research_batch_attestations AS a
        JOIN research_batches AS b
          ON b.batch_id = a.batch_id AND b.candidate_id = a.candidate_id
        WHERE a.candidate_id = ? AND b.status = 'admitted'
        ORDER BY a.batch_id
        """,
        (candidate_id,),
    ).fetchall()
    expected: set[tuple[str, str, str]] = set()
    for row in rows:
        batch_id = str(row["batch_id"])
        decoded = json.loads(str(row["sample_identities_json"]))
        if not isinstance(decoded, list):
            raise ResearchRegistryError("stored research batch sample identities are invalid")
        for identity in decoded:
            if (
                not isinstance(identity, list)
                or len(identity) != 2
                or not all(isinstance(item, str) and item for item in identity)
            ):
                raise ResearchRegistryError(
                    "stored research batch sample identities are invalid"
                )
            item = (batch_id, identity[0], identity[1])
            if item in expected:
                raise ResearchRegistryError(
                    "stored research batch sample identities are not unique"
                )
            expected.add(item)
    return expected


def record_trade_observations(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    observations: Iterable[dict[str, object]],
) -> None:
    ensure_batch_attestation_schema(connection)
    ensure_observation_schema(connection)
    with connection:
        for observation in observations:
            trade_id = _string(observation, "trade_id")
            batch_id = _string(observation, "batch_id")
            attestation = _attestation_for_observation(
                connection,
                candidate_id=candidate_id,
                batch_id=batch_id,
            )
            sample_id = _string(observation, "sample_id")
            source_id = _string(observation, "source_id")
            replay_run_id = _string(observation, "replay_run_id")
            planned_risk_fraction = _planned_fraction(
                observation.get("planned_risk_fraction")
            )
            closed_at_ms = observation.get("closed_at_ms")
            if isinstance(closed_at_ms, bool) or not isinstance(closed_at_ms, int):
                raise ResearchRegistryError("research observation closed_at_ms is invalid")

            if str(attestation["source_id"]) != source_id:
                raise ResearchRegistryError("research observation source does not match batch")
            if str(attestation["replay_run_id"]) != replay_run_id:
                raise ResearchRegistryError("research observation replay run does not match batch")

            identities = json.loads(str(attestation["sample_identities_json"]))
            expected_identity = [trade_id, sample_id]
            if not isinstance(identities, list) or expected_identity not in identities:
                raise ResearchRegistryError(
                    "research observation is not covered by the authoritative batch seal"
                )
            planned = json.loads(str(attestation["planned_risk_fractions_json"]))
            expected_planned = [trade_id, planned_risk_fraction]
            if not isinstance(planned, list) or expected_planned not in planned:
                raise ResearchRegistryError(
                    "research observation planned risk is not authoritatively attested"
                )

            normalized = dict(observation)
            normalized["planned_risk_fraction"] = planned_risk_fraction
            payload_json = _canonical_json(normalized)
            existing = connection.execute(
                """
                SELECT batch_id, sample_id, payload_json
                FROM research_trade_observations
                WHERE candidate_id = ? AND trade_id = ?
                """,
                (candidate_id, trade_id),
            ).fetchone()
            if existing is not None:
                stored = (
                    str(existing["batch_id"]),
                    str(existing["sample_id"]),
                    str(existing["payload_json"]),
                )
                if stored != (batch_id, sample_id, payload_json):
                    raise ResearchRegistryError(
                        f"research observation already exists with different data: {trade_id}"
                    )
                continue

            connection.execute(
                """
                INSERT INTO research_trade_observations (
                    candidate_id, batch_id, trade_id, sample_id, closed_at_ms, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (candidate_id, batch_id, trade_id, sample_id, closed_at_ms, payload_json),
            )


def load_trade_observations(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> tuple[dict[str, object], ...]:
    ensure_batch_attestation_schema(connection)
    ensure_observation_schema(connection)
    total = connection.execute(
        "SELECT COUNT(*) FROM research_trade_observations WHERE candidate_id = ?",
        (candidate_id,),
    ).fetchone()
    rows = connection.execute(
        """
        SELECT o.batch_id, o.trade_id, o.sample_id, o.payload_json
        FROM research_trade_observations AS o
        JOIN research_batches AS b
          ON b.batch_id = o.batch_id AND b.candidate_id = o.candidate_id
        JOIN research_batch_attestations AS a
          ON a.batch_id = o.batch_id AND a.candidate_id = o.candidate_id
        WHERE o.candidate_id = ? AND b.status = 'admitted'
        ORDER BY o.closed_at_ms, o.trade_id
        """,
        (candidate_id,),
    ).fetchall()
    if total is None or int(total[0]) != len(rows):
        raise ResearchRegistryError(
            "research observations are not fully backed by admitted authoritative batches"
        )

    actual: set[tuple[str, str, str]] = set()
    for row in rows:
        batch_id = row["batch_id"]
        trade_id = row["trade_id"]
        sample_id = row["sample_id"]
        if not all(isinstance(item, str) and item for item in (batch_id, trade_id, sample_id)):
            raise ResearchRegistryError("stored research observation identity is invalid")
        actual.add((str(batch_id), str(trade_id), str(sample_id)))
    expected = _expected_attested_sample_identities(
        connection,
        candidate_id=candidate_id,
    )
    if actual != expected:
        raise ResearchRegistryError(
            "research observations do not match the complete attested sample set"
        )

    result: list[dict[str, object]] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            raise ResearchRegistryError("stored research observation is invalid")
        result.append(payload)
    return tuple(result)