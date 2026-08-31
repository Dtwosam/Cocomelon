from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
    intervals_overlap,
    normalize_intervals,
    validation_cutover_allowed,
)


class ResearchRegistryError(RuntimeError):
    pass


class ResearchContaminationError(ResearchRegistryError):
    pass


_TERMINAL_STATES = frozenset(
    {
        ResearchCandidateState.REJECTED_OPERATIONAL,
        ResearchCandidateState.REJECTED_CONTAMINATION,
        ResearchCandidateState.REJECTED_FUTILITY,
        ResearchCandidateState.VALIDATED_EDGE,
        ResearchCandidateState.NO_EDGE,
    }
)
_RESEARCH_TOUCHABLE_STATES = frozenset(
    {
        ResearchCandidateState.DRAFT,
        ResearchCandidateState.RESEARCHING,
        ResearchCandidateState.RESEARCH_PROMISING,
    }
)


class ResearchRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_candidates (
                candidate_id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL,
                parent_candidate_id TEXT,
                ancestor_candidate_ids_json TEXT NOT NULL,
                config_digest TEXT NOT NULL,
                code_revision TEXT NOT NULL,
                state TEXT NOT NULL,
                freeze_ms INTEGER,
                FOREIGN KEY(parent_candidate_id) REFERENCES research_candidates(candidate_id)
            );
            CREATE TABLE IF NOT EXISTS research_touched_intervals (
                candidate_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                PRIMARY KEY(candidate_id, source_id, start_ms, end_ms),
                FOREIGN KEY(candidate_id) REFERENCES research_candidates(candidate_id)
            );
            CREATE TABLE IF NOT EXISTS research_v4_intervals (
                run_id TEXT PRIMARY KEY,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                disposition TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_batches (
                batch_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                replay_run_id TEXT NOT NULL UNIQUE,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES research_candidates(candidate_id)
            );
            CREATE TABLE IF NOT EXISTS research_candidate_state_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT NOT NULL,
                state TEXT NOT NULL,
                reason TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES research_candidates(candidate_id)
            );
            """
        )
        self.connection.commit()

    @staticmethod
    def _ancestor_json(ancestors: tuple[str, ...]) -> str:
        return json.dumps(ancestors, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _decode_ancestors(value: str) -> tuple[str, ...]:
        decoded = json.loads(value)
        if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
            raise ResearchRegistryError("stored ancestor lineage is invalid")
        return tuple(decoded)

    def close(self) -> None:
        self.connection.close()

    def create_candidate(self, manifest: ResearchCandidateManifest) -> None:
        existing = self.connection.execute(
            "SELECT candidate_id FROM research_candidates WHERE candidate_id = ?",
            (manifest.candidate_id,),
        ).fetchone()
        if existing is not None:
            raise ResearchRegistryError(f"candidate already exists: {manifest.candidate_id}")

        if manifest.parent_candidate_id is not None:
            parent = self.load_candidate(manifest.parent_candidate_id)
            if parent.family_id != manifest.family_id:
                raise ResearchRegistryError("candidate parent must belong to the same family")
            expected_ancestors = parent.ancestor_candidate_ids + (parent.candidate_id,)
            if manifest.ancestor_candidate_ids != expected_ancestors:
                raise ResearchRegistryError(
                    "candidate ancestor lineage does not match parent chain"
                )

        self.connection.execute(
            """
            INSERT INTO research_candidates (
                candidate_id,
                family_id,
                parent_candidate_id,
                ancestor_candidate_ids_json,
                config_digest,
                code_revision,
                state,
                freeze_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                manifest.candidate_id,
                manifest.family_id,
                manifest.parent_candidate_id,
                self._ancestor_json(manifest.ancestor_candidate_ids),
                manifest.config_digest,
                manifest.code_revision,
                manifest.state.value,
            ),
        )
        self.connection.execute(
            """
            INSERT INTO research_candidate_state_events (candidate_id, state, reason)
            VALUES (?, ?, ?)
            """,
            (manifest.candidate_id, manifest.state.value, "candidate_created"),
        )
        self.connection.commit()

    def load_candidate(self, candidate_id: str) -> ResearchCandidateManifest:
        row = self.connection.execute(
            """
            SELECT candidate_id, family_id, parent_candidate_id,
                   ancestor_candidate_ids_json, config_digest, code_revision, state
            FROM research_candidates
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise ResearchRegistryError(f"candidate not found: {candidate_id}")
        try:
            state = ResearchCandidateState(str(row["state"]))
        except ValueError as exc:
            raise ResearchRegistryError("stored candidate state is invalid") from exc
        return ResearchCandidateManifest(
            candidate_id=str(row["candidate_id"]),
            family_id=str(row["family_id"]),
            parent_candidate_id=(
                None if row["parent_candidate_id"] is None else str(row["parent_candidate_id"])
            ),
            ancestor_candidate_ids=self._decode_ancestors(str(row["ancestor_candidate_ids_json"])),
            config_digest=str(row["config_digest"]),
            code_revision=str(row["code_revision"]),
            state=state,
        )

    def _assert_research_touchable(self, candidate_id: str) -> ResearchCandidateManifest:
        candidate = self.load_candidate(candidate_id)
        if candidate.state not in _RESEARCH_TOUCHABLE_STATES:
            raise ResearchRegistryError(
                f"candidate is terminal to research checkpoints: {candidate.state.value}"
            )
        return candidate

    def record_touched_interval(
        self,
        candidate_id: str,
        interval: TimeInterval,
        *,
        source_id: str,
    ) -> None:
        self._assert_research_touchable(candidate_id)
        if not source_id.strip():
            raise ResearchRegistryError("source_id must not be empty")
        self.connection.execute(
            """
            INSERT OR IGNORE INTO research_touched_intervals (
                candidate_id, source_id, start_ms, end_ms
            ) VALUES (?, ?, ?, ?)
            """,
            (candidate_id, source_id, interval.start_ms, interval.end_ms),
        )
        self.connection.commit()

    def record_batch(
        self,
        *,
        candidate_id: str,
        batch_id: str,
        source_id: str,
        replay_run_id: str,
        interval: TimeInterval,
    ) -> None:
        self._assert_research_touchable(candidate_id)
        for value, field in (
            (batch_id, "batch_id"),
            (source_id, "source_id"),
            (replay_run_id, "replay_run_id"),
        ):
            if not value.strip():
                raise ResearchRegistryError(f"{field} must not be empty")
        self.assert_batch_disjoint_from_v4(interval)

        existing = self.connection.execute(
            """
            SELECT candidate_id, source_id, replay_run_id, start_ms, end_ms
            FROM research_batches
            WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        incoming = (
            candidate_id,
            source_id,
            replay_run_id,
            interval.start_ms,
            interval.end_ms,
        )
        if existing is not None:
            stored = (
                str(existing["candidate_id"]),
                str(existing["source_id"]),
                str(existing["replay_run_id"]),
                int(existing["start_ms"]),
                int(existing["end_ms"]),
            )
            if stored != incoming:
                raise ResearchRegistryError(
                    f"research batch already exists with different data: {batch_id}"
                )
            return

        replay_existing = self.connection.execute(
            "SELECT batch_id FROM research_batches WHERE replay_run_id = ?",
            (replay_run_id,),
        ).fetchone()
        if replay_existing is not None:
            raise ResearchRegistryError(
                f"research replay run already belongs to batch {replay_existing['batch_id']}"
            )

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO research_batches (
                    batch_id, candidate_id, source_id, replay_run_id, start_ms, end_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    candidate_id,
                    source_id,
                    replay_run_id,
                    interval.start_ms,
                    interval.end_ms,
                ),
            )
            self.connection.execute(
                """
                INSERT OR IGNORE INTO research_touched_intervals (
                    candidate_id, source_id, start_ms, end_ms
                ) VALUES (?, ?, ?, ?)
                """,
                (candidate_id, source_id, interval.start_ms, interval.end_ms),
            )

    def effective_touched_intervals(self, candidate_id: str) -> tuple[TimeInterval, ...]:
        candidate = self.load_candidate(candidate_id)
        lineage = candidate.ancestor_candidate_ids + (candidate.candidate_id,)
        intervals: list[TimeInterval] = []
        for lineage_candidate_id in lineage:
            rows = self.connection.execute(
                """
                SELECT start_ms, end_ms
                FROM research_touched_intervals
                WHERE candidate_id = ?
                ORDER BY start_ms, end_ms
                """,
                (lineage_candidate_id,),
            ).fetchall()
            intervals.extend(
                TimeInterval(int(row["start_ms"]), int(row["end_ms"])) for row in rows
            )
        return normalize_intervals(intervals)

    def record_v4_interval(
        self,
        *,
        run_id: str,
        interval: TimeInterval,
        disposition: str,
    ) -> None:
        if not run_id.strip() or not disposition.strip():
            raise ResearchRegistryError("V4 run_id and disposition must not be empty")
        existing = self.connection.execute(
            "SELECT start_ms, end_ms, disposition FROM research_v4_intervals WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if existing is not None:
            stored = (
                int(existing["start_ms"]),
                int(existing["end_ms"]),
                str(existing["disposition"]),
            )
            incoming = (interval.start_ms, interval.end_ms, disposition)
            if stored != incoming:
                raise ResearchRegistryError(
                    f"V4 interval already exists with different data: {run_id}"
                )
            return
        self.connection.execute(
            """
            INSERT INTO research_v4_intervals (run_id, start_ms, end_ms, disposition)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, interval.start_ms, interval.end_ms, disposition),
        )
        self.connection.commit()

    def assert_batch_disjoint_from_v4(self, interval: TimeInterval) -> None:
        rows = self.connection.execute(
            "SELECT run_id, start_ms, end_ms FROM research_v4_intervals ORDER BY start_ms, end_ms"
        ).fetchall()
        for row in rows:
            v4_interval = TimeInterval(int(row["start_ms"]), int(row["end_ms"]))
            if intervals_overlap(interval, v4_interval):
                raise ResearchContaminationError(
                    f"research source overlaps V4 acquisition interval for run {row['run_id']}"
                )

    def transition_candidate(
        self,
        candidate_id: str,
        state: ResearchCandidateState,
        *,
        reason: str,
    ) -> None:
        if not reason.strip():
            raise ResearchRegistryError("state transition reason must not be empty")
        current = self.load_candidate(candidate_id)
        if current.state in _TERMINAL_STATES and state != current.state:
            raise ResearchRegistryError(f"candidate is terminal: {current.state.value}")
        if current.state is ResearchCandidateState.FROZEN_CHALLENGER and state not in {
            ResearchCandidateState.FROZEN_CHALLENGER,
            ResearchCandidateState.VALIDATING,
        }:
            raise ResearchRegistryError(
                "candidate is terminal to research checkpoints: frozen_challenger"
            )
        if current.state is ResearchCandidateState.VALIDATING and state not in {
            ResearchCandidateState.VALIDATING,
            ResearchCandidateState.VALIDATED_EDGE,
            ResearchCandidateState.NO_EDGE,
            ResearchCandidateState.REJECTED_OPERATIONAL,
            ResearchCandidateState.REJECTED_CONTAMINATION,
        }:
            raise ResearchRegistryError("validating candidate cannot return to research")
        self.connection.execute(
            "UPDATE research_candidates SET state = ? WHERE candidate_id = ?",
            (state.value, candidate_id),
        )
        self.connection.execute(
            """
            INSERT INTO research_candidate_state_events (candidate_id, state, reason)
            VALUES (?, ?, ?)
            """,
            (candidate_id, state.value, reason),
        )
        self.connection.commit()

    def freeze_candidate(self, candidate_id: str, *, freeze_ms: int) -> None:
        if freeze_ms < 0:
            raise ResearchRegistryError("freeze_ms must be non-negative")
        current = self.load_candidate(candidate_id)
        if current.state is not ResearchCandidateState.RESEARCH_PROMISING:
            raise ResearchRegistryError("only a research-promising candidate can be frozen")
        self.connection.execute(
            """
            UPDATE research_candidates
            SET state = ?, freeze_ms = ?
            WHERE candidate_id = ?
            """,
            (ResearchCandidateState.FROZEN_CHALLENGER.value, freeze_ms, candidate_id),
        )
        self.connection.execute(
            """
            INSERT INTO research_candidate_state_events (candidate_id, state, reason)
            VALUES (?, ?, ?)
            """,
            (candidate_id, ResearchCandidateState.FROZEN_CHALLENGER.value, "candidate_frozen"),
        )
        self.connection.commit()

    def assert_validation_cutover(self, candidate_id: str, *, validation_start_ms: int) -> None:
        current = self.load_candidate(candidate_id)
        if current.state is not ResearchCandidateState.FROZEN_CHALLENGER:
            raise ResearchRegistryError("candidate must be frozen before validation cutover")
        row = self.connection.execute(
            "SELECT freeze_ms FROM research_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None or row["freeze_ms"] is None:
            raise ResearchRegistryError("candidate freeze timestamp is missing")
        if not validation_cutover_allowed(
            validation_start_ms=validation_start_ms,
            freeze_ms=int(row["freeze_ms"]),
            effective_touched_intervals=self.effective_touched_intervals(candidate_id),
        ):
            raise ResearchRegistryError(
                "validation cutover violates freeze or touched-data embargo"
            )
