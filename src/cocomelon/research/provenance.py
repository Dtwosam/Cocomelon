from __future__ import annotations

import sqlite3


def load_sealed_admitted_batch_provenance(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    seal_table = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'research_batch_seals'
        """
    ).fetchone()
    if seal_table is None:
        return (), ()

    rows = connection.execute(
        """
        SELECT b.batch_id, b.source_id
        FROM research_batches AS b
        INNER JOIN research_batch_seals AS s ON s.batch_id = b.batch_id
        WHERE b.candidate_id = ?
          AND s.candidate_id = ?
          AND b.status = 'admitted'
        ORDER BY b.batch_id, b.source_id
        """,
        (candidate_id, candidate_id),
    ).fetchall()
    batch_ids = tuple(str(row["batch_id"]) for row in rows)
    source_ids = tuple(sorted({str(row["source_id"]) for row in rows}))
    return batch_ids, source_ids
