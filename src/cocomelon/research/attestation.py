from __future__ import annotations

import json
import sqlite3

from cocomelon.research.artifact import VerifiedResearchBatch
from cocomelon.research.registry import ResearchRegistryError
from cocomelon.research.throughput import normalize_decision_throughput_payload


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def ensure_batch_attestation_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_batch_attestations (
            batch_id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            source_digest TEXT NOT NULL,
            manifest_id TEXT NOT NULL,
            result_digest TEXT NOT NULL,
            sample_digest TEXT NOT NULL,
            sample_identities_json TEXT NOT NULL,
            planned_risk_fractions_json TEXT NOT NULL,
            operational_failure INTEGER NOT NULL,
            hard_risk_failure INTEGER NOT NULL,
            health_reason_codes_json TEXT NOT NULL,
            decision_throughput_json TEXT,
            FOREIGN KEY(batch_id) REFERENCES research_batches(batch_id),
            FOREIGN KEY(candidate_id) REFERENCES research_candidates(candidate_id)
        )
        """
    )
    columns = {
        str(row["name"])
        for row in connection.execute(
            "PRAGMA table_info(research_batch_attestations)"
        ).fetchall()
    }
    if "decision_throughput_json" not in columns:
        connection.execute(
            "ALTER TABLE research_batch_attestations "
            "ADD COLUMN decision_throughput_json TEXT"
        )
    connection.commit()


def attest_verified_research_batch(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    verified: VerifiedResearchBatch,
) -> None:
    ensure_batch_attestation_schema(connection)
    if connection.in_transaction:
        raise ResearchRegistryError("research batch attestation transaction is already active")

    candidate = connection.execute(
        """
        SELECT code_revision, config_digest
        FROM research_candidates
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    ).fetchone()
    if candidate is None:
        raise ResearchRegistryError(f"candidate not found: {candidate_id}")
    if str(candidate["code_revision"]) != verified.code_revision:
        raise ResearchRegistryError(
            "authoritative research artifact code revision does not match candidate"
        )
    candidate_config_digest = (
        verified.candidate_config_digest
        if verified.candidate_config_digest is not None
        else verified.config_digest
    )
    if str(candidate["config_digest"]) != candidate_config_digest:
        raise ResearchRegistryError(
            "authoritative research artifact config digest does not match candidate"
        )

    identities = tuple(
        sorted((sample.trade_id, sample.sample_id) for sample in verified.samples)
    )
    planned = tuple(
        sorted(
            (trade_id, str(value))
            for trade_id, value in verified.planned_risk_fractions
        )
    )
    if verified.decision_throughput is None:
        throughput_json: str | None = None
    else:
        try:
            throughput_json = _canonical_json(
                normalize_decision_throughput_payload(
                    verified.decision_throughput
                )
            )
        except ValueError as exc:
            raise ResearchRegistryError(
                "authoritative research decision throughput is invalid"
            ) from exc
    incoming = (
        candidate_id,
        verified.source_digest,
        verified.manifest_id,
        verified.result_digest,
        verified.sample_digest,
        _canonical_json(identities),
        _canonical_json(planned),
        int(verified.operational_failure),
        int(verified.hard_risk_failure),
        _canonical_json(verified.health_reason_codes),
        throughput_json,
    )

    connection.execute("BEGIN IMMEDIATE")
    try:
        batch = connection.execute(
            """
            SELECT candidate_id, source_id, replay_run_id, start_ms, end_ms, status
            FROM research_batches
            WHERE batch_id = ?
            """,
            (verified.batch_id,),
        ).fetchone()
        if batch is None:
            raise ResearchRegistryError(
                f"research batch not found for authoritative attestation: {verified.batch_id}"
            )
        expected_batch = (
            candidate_id,
            verified.source_id,
            verified.replay_run_id,
            verified.interval.start_ms,
            verified.interval.end_ms,
            "admitted",
        )
        stored_batch = (
            str(batch["candidate_id"]),
            str(batch["source_id"]),
            str(batch["replay_run_id"]),
            int(batch["start_ms"]),
            int(batch["end_ms"]),
            str(batch["status"]),
        )
        if stored_batch != expected_batch:
            raise ResearchRegistryError(
                "authoritative research batch attestation does not match admitted batch"
            )

        existing = connection.execute(
            """
            SELECT candidate_id, source_digest, manifest_id, result_digest,
                   sample_digest, sample_identities_json, planned_risk_fractions_json,
                   operational_failure, hard_risk_failure, health_reason_codes_json,
                   decision_throughput_json
            FROM research_batch_attestations
            WHERE batch_id = ?
            """,
            (verified.batch_id,),
        ).fetchone()
        if existing is not None:
            stored = tuple(existing[index] for index in range(len(incoming)))
            normalized_stored = (
                str(stored[0]),
                str(stored[1]),
                str(stored[2]),
                str(stored[3]),
                str(stored[4]),
                str(stored[5]),
                str(stored[6]),
                int(stored[7]),
                int(stored[8]),
                str(stored[9]),
                None if stored[10] is None else str(stored[10]),
            )
            if normalized_stored != incoming:
                raise ResearchRegistryError(
                    "research batch already has a different authoritative attestation: "
                    f"{verified.batch_id}"
                )
            connection.commit()
            return

        connection.execute(
            """
            INSERT INTO research_batch_attestations (
                batch_id, candidate_id, source_digest, manifest_id, result_digest,
                sample_digest, sample_identities_json, planned_risk_fractions_json,
                operational_failure, hard_risk_failure, health_reason_codes_json,
                decision_throughput_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (verified.batch_id, *incoming),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def load_candidate_attested_health(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> tuple[bool, bool, tuple[str, ...]]:
    ensure_batch_attestation_schema(connection)
    rows = connection.execute(
        """
        SELECT a.operational_failure, a.hard_risk_failure, a.health_reason_codes_json
        FROM research_batch_attestations AS a
        JOIN research_batches AS b ON b.batch_id = a.batch_id
        WHERE a.candidate_id = ? AND b.status = 'admitted'
        ORDER BY a.batch_id
        """,
        (candidate_id,),
    ).fetchall()
    operational_failure = False
    hard_risk_failure = False
    reasons: set[str] = set()
    for row in rows:
        operational_failure = operational_failure or bool(int(row["operational_failure"]))
        hard_risk_failure = hard_risk_failure or bool(int(row["hard_risk_failure"]))
        decoded = json.loads(str(row["health_reason_codes_json"]))
        if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
            raise ResearchRegistryError("stored research batch health reasons are invalid")
        reasons.update(decoded)
    return operational_failure, hard_risk_failure, tuple(sorted(reasons))



def load_candidate_attested_decision_throughput(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> dict[str, dict[str, object] | None]:
    table = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'research_batch_attestations'
        """
    ).fetchone()
    if table is None:
        return {}

    columns = {
        str(row["name"])
        for row in connection.execute(
            "PRAGMA table_info(research_batch_attestations)"
        ).fetchall()
    }
    has_throughput = "decision_throughput_json" in columns
    if has_throughput:
        rows = connection.execute(
            """
            SELECT a.batch_id, a.decision_throughput_json
            FROM research_batch_attestations AS a
            JOIN research_batches AS b
              ON b.batch_id = a.batch_id AND b.candidate_id = a.candidate_id
            WHERE a.candidate_id = ? AND b.status = 'admitted'
            ORDER BY a.batch_id
            """,
            (candidate_id,),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT a.batch_id
            FROM research_batch_attestations AS a
            JOIN research_batches AS b
              ON b.batch_id = a.batch_id AND b.candidate_id = a.candidate_id
            WHERE a.candidate_id = ? AND b.status = 'admitted'
            ORDER BY a.batch_id
            """,
            (candidate_id,),
        ).fetchall()

    result: dict[str, dict[str, object] | None] = {}
    for row in rows:
        batch_id = str(row["batch_id"])
        if not has_throughput or row["decision_throughput_json"] is None:
            result[batch_id] = None
            continue
        try:
            decoded = json.loads(str(row["decision_throughput_json"]))
            normalized = normalize_decision_throughput_payload(decoded)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ResearchRegistryError(
                "stored research decision throughput is invalid"
            ) from exc
        result[batch_id] = normalized
    return result
