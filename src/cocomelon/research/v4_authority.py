from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

from cocomelon.research.contracts import TimeInterval
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError

_REQUIRED_AUTHORITY_TABLES = frozenset(
    {
        "research_v4_intervals",
        "research_v4_registry_state",
    }
)


def _open_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ResearchRegistryError(f"V4 authority snapshot not found: {path}")
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _load_authority_snapshot(
    path: Path,
) -> tuple[tuple[tuple[str, int, int, str], ...], int, str]:
    connection = _open_read_only(path)
    try:
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        table_names = {str(row["name"]) for row in table_rows}
        missing = _REQUIRED_AUTHORITY_TABLES - table_names
        if missing:
            raise ResearchRegistryError(
                "V4 authority snapshot is missing required tables: "
                + ", ".join(sorted(missing))
            )

        state_rows = connection.execute(
            """
            SELECT singleton, complete_through_ms, source_id
            FROM research_v4_registry_state
            """
        ).fetchall()
        if len(state_rows) != 1 or int(state_rows[0]["singleton"]) != 1:
            raise ResearchRegistryError("V4 authority snapshot has invalid completeness state")
        through_ms = int(state_rows[0]["complete_through_ms"])
        source_id = str(state_rows[0]["source_id"])
        if through_ms < 0 or not source_id.strip():
            raise ResearchRegistryError("V4 authority snapshot has invalid completeness state")

        rows = connection.execute(
            """
            SELECT run_id, start_ms, end_ms, disposition
            FROM research_v4_intervals
            ORDER BY run_id
            """
        ).fetchall()
        intervals: list[tuple[str, int, int, str]] = []
        seen_run_ids: set[str] = set()
        for row in rows:
            run_id = str(row["run_id"])
            start_ms = int(row["start_ms"])
            end_ms = int(row["end_ms"])
            disposition = str(row["disposition"])
            if (
                not run_id.strip()
                or run_id in seen_run_ids
                or start_ms < 0
                or end_ms <= start_ms
                or not disposition.strip()
            ):
                raise ResearchRegistryError("V4 authority snapshot contains invalid interval data")
            seen_run_ids.add(run_id)
            intervals.append((run_id, start_ms, end_ms, disposition))
        return tuple(intervals), through_ms, source_id
    except sqlite3.Error as exc:
        raise ResearchRegistryError(f"V4 authority snapshot is unreadable: {exc}") from exc
    finally:
        connection.close()


def _merge_interval_uncommitted(
    registry: ResearchRegistry,
    *,
    run_id: str,
    start_ms: int,
    end_ms: int,
    disposition: str,
) -> None:
    existing = registry.connection.execute(
        """
        SELECT start_ms, end_ms, disposition
        FROM research_v4_intervals
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    incoming = (start_ms, end_ms, disposition)
    if existing is not None:
        stored = (
            int(existing["start_ms"]),
            int(existing["end_ms"]),
            str(existing["disposition"]),
        )
        if stored != incoming:
            raise ResearchRegistryError(
                f"V4 interval already exists with different data: {run_id}"
            )
        return

    interval = TimeInterval(start_ms, end_ms)
    overlapping_batches = registry.connection.execute(
        """
        SELECT batch_id, candidate_id
        FROM research_batches
        WHERE start_ms < ? AND ? < end_ms
        """,
        (interval.end_ms, interval.start_ms),
    ).fetchall()
    directly_contaminated = {str(row["candidate_id"]) for row in overlapping_batches}
    contaminated_candidates = registry._candidate_ids_contaminated_by_roots(
        directly_contaminated
    )
    registry.connection.execute(
        """
        INSERT INTO research_v4_intervals (run_id, start_ms, end_ms, disposition)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, start_ms, end_ms, disposition),
    )
    for row in overlapping_batches:
        registry.connection.execute(
            """
            UPDATE research_batches
            SET status = 'rejected_contamination', contamination_v4_run_id = ?
            WHERE batch_id = ?
            """,
            (run_id, str(row["batch_id"])),
        )
    for candidate_id in contaminated_candidates:
        registry._force_candidate_contamination(
            candidate_id,
            reason=f"late_v4_source_interval_overlap:{run_id}",
        )


def merge_v4_authority_snapshot(
    registry: ResearchRegistry,
    authority_path: str | Path,
) -> None:
    intervals, through_ms, source_id = _load_authority_snapshot(Path(authority_path))
    incoming_by_run_id = {
        run_id: (start_ms, end_ms, disposition)
        for run_id, start_ms, end_ms, disposition in intervals
    }

    registry._begin_immediate()
    try:
        local_intervals = registry.connection.execute(
            """
            SELECT run_id, start_ms, end_ms, disposition
            FROM research_v4_intervals
            ORDER BY run_id
            """
        ).fetchall()
        for row in local_intervals:
            run_id = str(row["run_id"])
            stored = (
                int(row["start_ms"]),
                int(row["end_ms"]),
                str(row["disposition"]),
            )
            if incoming_by_run_id.get(run_id) != stored:
                raise ResearchRegistryError(
                    f"V4 authority snapshot omitted or rewrote existing interval: {run_id}"
                )

        state = registry.connection.execute(
            """
            SELECT complete_through_ms, source_id
            FROM research_v4_registry_state
            WHERE singleton = 1
            """
        ).fetchone()
        if state is not None:
            stored_through = int(state["complete_through_ms"])
            stored_source = str(state["source_id"])
            if stored_source != source_id:
                raise ResearchRegistryError("V4 registry completeness source cannot change")
            if through_ms < stored_through:
                raise ResearchRegistryError("V4 registry completeness cannot move backwards")

        for run_id, start_ms, end_ms, disposition in intervals:
            _merge_interval_uncommitted(
                registry,
                run_id=run_id,
                start_ms=start_ms,
                end_ms=end_ms,
                disposition=disposition,
            )

        if state is None:
            registry.connection.execute(
                """
                INSERT INTO research_v4_registry_state (
                    singleton, complete_through_ms, source_id
                ) VALUES (1, ?, ?)
                """,
                (through_ms, source_id),
            )
        elif through_ms > int(state["complete_through_ms"]):
            registry.connection.execute(
                """
                UPDATE research_v4_registry_state
                SET complete_through_ms = ?
                WHERE singleton = 1
                """,
                (through_ms,),
            )
        registry.connection.commit()
    except (ResearchRegistryError, sqlite3.Error):
        registry.connection.rollback()
        raise
    except Exception:
        registry.connection.rollback()
        raise
