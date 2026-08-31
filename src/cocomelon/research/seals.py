from __future__ import annotations

import json
import sqlite3

from cocomelon.research.registry import ResearchRegistryError


def _canonical_trade_ids(trade_ids: tuple[str, ...]) -> tuple[str, ...]:
    if any(not trade_id.strip() for trade_id in trade_ids):
        raise ResearchRegistryError("sealed research trade ids must not be empty")
    normalized = tuple(sorted(trade_ids))
    if len(set(normalized)) != len(normalized):
        raise ResearchRegistryError("sealed research trade ids must be unique")
    return normalized


def _require_sha256(value: str) -> None:
    if (
        len(value) != 64
        or value != value.lower()
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ResearchRegistryError(
            "research batch sample digest must be a lowercase sha256 digest"
        )


def ensure_batch_seal_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_batch_seals (
            batch_id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            trade_ids_json TEXT NOT NULL,
            sample_digest TEXT NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES research_batches(batch_id),
            FOREIGN KEY(candidate_id) REFERENCES research_candidates(candidate_id)
        )
        """
    )
    connection.commit()


def seal_research_batch(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    batch_id: str,
    trade_ids: tuple[str, ...],
    sample_digest: str,
) -> None:
    normalized_ids = _canonical_trade_ids(trade_ids)
    _require_sha256(sample_digest)
    trade_ids_json = json.dumps(normalized_ids, separators=(",", ":"))

    ensure_batch_seal_schema(connection)
    if connection.in_transaction:
        raise ResearchRegistryError("research batch seal transaction is already active")
    connection.execute("BEGIN IMMEDIATE")
    try:
        batch = connection.execute(
            """
            SELECT candidate_id, status
            FROM research_batches
            WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        if batch is None:
            raise ResearchRegistryError(f"research batch not found for seal: {batch_id}")
        if str(batch["candidate_id"]) != candidate_id:
            raise ResearchRegistryError("research batch seal candidate does not match batch")
        if str(batch["status"]) != "admitted":
            raise ResearchRegistryError("contaminated research batch cannot be sealed")

        existing = connection.execute(
            """
            SELECT candidate_id, trade_ids_json, sample_digest
            FROM research_batch_seals
            WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        incoming = (candidate_id, trade_ids_json, sample_digest)
        if existing is not None:
            stored = (
                str(existing["candidate_id"]),
                str(existing["trade_ids_json"]),
                str(existing["sample_digest"]),
            )
            if stored != incoming:
                raise ResearchRegistryError(
                    f"research batch seal already exists with different data: {batch_id}"
                )
            connection.commit()
            return

        connection.execute(
            """
            INSERT INTO research_batch_seals (
                batch_id, candidate_id, trade_ids_json, sample_digest
            ) VALUES (?, ?, ?, ?)
            """,
            (batch_id, *incoming),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
