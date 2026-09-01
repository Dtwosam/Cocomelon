from __future__ import annotations

import sqlite3
from pathlib import Path

from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError

_REQUIRED_TABLES = frozenset(
    {
        "research_candidates",
        "research_touched_intervals",
        "research_v4_intervals",
        "research_v4_registry_state",
        "research_batches",
        "research_performance_reports",
        "research_candidate_state_events",
    }
)


class ReadOnlyResearchRegistry(ResearchRegistry):
    """Research registry view that never initializes or mutates SQLite schema."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        try:
            self.connection = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            raise ResearchRegistryError(f"cannot open research registry read-only: {exc}") from exc
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA query_only = ON")
            self._validate_read_schema()
        except Exception:
            self.connection.close()
            raise

    def _validate_read_schema(self) -> None:
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        tables = {str(row["name"]) for row in rows}
        missing = sorted(_REQUIRED_TABLES - tables)
        if missing:
            raise ResearchRegistryError(
                "research registry schema is missing required tables: " + ", ".join(missing)
            )
