from __future__ import annotations

import sqlite3


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def load_sealed_admitted_batch_provenance(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not _table_exists(connection, "research_batch_seals"):
        return (), ()
    if not _table_exists(connection, "research_batch_attestations"):
        return (), ()

    rows = connection.execute(
        """
        SELECT b.batch_id, b.source_id
        FROM research_batches AS b
        INNER JOIN research_batch_seals AS s
          ON s.batch_id = b.batch_id AND s.candidate_id = b.candidate_id
        INNER JOIN research_batch_attestations AS a
          ON a.batch_id = b.batch_id AND a.candidate_id = b.candidate_id
        WHERE b.candidate_id = ?
          AND b.status = 'admitted'
        ORDER BY b.batch_id, b.source_id
        """,
        (candidate_id,),
    ).fetchall()
    batch_ids = tuple(str(row["batch_id"]) for row in rows)
    source_ids = tuple(sorted({str(row["source_id"]) for row in rows}))
    return batch_ids, source_ids
