from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
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
_EVIDENCE_DERIVED_STATES = frozenset(
    {
        ResearchCandidateState.RESEARCH_PROMISING,
        ResearchCandidateState.REJECTED_FUTILITY,
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
                execution_config_json TEXT NOT NULL,
                risk_config_json TEXT NOT NULL,
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
                status TEXT NOT NULL DEFAULT 'admitted',
                contamination_v4_run_id TEXT,
                FOREIGN KEY(candidate_id) REFERENCES research_candidates(candidate_id)
            );
            CREATE TABLE IF NOT EXISTS research_performance_reports (
                report_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
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
        self._ensure_research_candidate_columns()
        self._ensure_research_batch_columns()
        self.connection.commit()

    def _ensure_research_candidate_columns(self) -> None:
        rows = self.connection.execute("PRAGMA table_info(research_candidates)").fetchall()
        columns = {str(row["name"]) for row in rows}
        if "execution_config_json" not in columns:
            self.connection.execute(
                "ALTER TABLE research_candidates "
                "ADD COLUMN execution_config_json TEXT NOT NULL "
                "DEFAULT '{\"legacy\":true}'"
            )
        if "risk_config_json" not in columns:
            self.connection.execute(
                "ALTER TABLE research_candidates "
                "ADD COLUMN risk_config_json TEXT NOT NULL "
                "DEFAULT '{\"legacy\":true}'"
            )

    def _ensure_research_batch_columns(self) -> None:
        rows = self.connection.execute("PRAGMA table_info(research_batches)").fetchall()
        columns = {str(row["name"]) for row in rows}
        if "status" not in columns:
            self.connection.execute(
                "ALTER TABLE research_batches ADD COLUMN status TEXT NOT NULL DEFAULT 'admitted'"
            )
        if "contamination_v4_run_id" not in columns:
            self.connection.execute(
                "ALTER TABLE research_batches ADD COLUMN contamination_v4_run_id TEXT"
            )

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @staticmethod
    def _ancestor_json(ancestors: tuple[str, ...]) -> str:
        return json.dumps(ancestors, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _decode_ancestors(value: str) -> tuple[str, ...]:
        decoded = json.loads(value)
        if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
            raise ResearchRegistryError("stored ancestor lineage is invalid")
        return tuple(decoded)

    @staticmethod
    def _report_decimal(payload: dict[str, object], field: str) -> Decimal | None:
        value = payload.get(field)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ResearchRegistryError(f"checkpoint report {field} is invalid")
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ResearchRegistryError(f"checkpoint report {field} is invalid") from exc
        if not result.is_finite():
            raise ResearchRegistryError(f"checkpoint report {field} is invalid")
        return result

    @staticmethod
    def _report_int(payload: dict[str, object], field: str) -> int:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ResearchRegistryError(f"checkpoint report {field} is invalid")
        return value

    def close(self) -> None:
        self.connection.close()

    def _local_touched_intervals(self, candidate_id: str) -> tuple[TimeInterval, ...]:
        rows = self.connection.execute(
            """
            SELECT start_ms, end_ms
            FROM research_touched_intervals
            WHERE candidate_id = ?
            ORDER BY start_ms, end_ms
            """,
            (candidate_id,),
        ).fetchall()
        return normalize_intervals(
            TimeInterval(int(row["start_ms"]), int(row["end_ms"])) for row in rows
        )

    def _source_provenance_ids(self, candidate_id: str) -> tuple[str, ...]:
        rows = self.connection.execute(
            """
            SELECT DISTINCT source_id
            FROM research_touched_intervals
            WHERE candidate_id = ?
            ORDER BY source_id
            """,
            (candidate_id,),
        ).fetchall()
        return tuple(str(row["source_id"]) for row in rows)

    def _performance_report_ids(self, candidate_id: str) -> tuple[str, ...]:
        rows = self.connection.execute(
            """
            SELECT report_id
            FROM research_performance_reports
            WHERE candidate_id = ?
            ORDER BY report_id
            """,
            (candidate_id,),
        ).fetchall()
        return tuple(str(row["report_id"]) for row in rows)

    def _effective_touched_for_lineage(
        self,
        lineage_candidate_ids: tuple[str, ...],
    ) -> tuple[TimeInterval, ...]:
        intervals: list[TimeInterval] = []
        for lineage_candidate_id in lineage_candidate_ids:
            intervals.extend(self._local_touched_intervals(lineage_candidate_id))
        return normalize_intervals(intervals)

    def create_candidate(self, manifest: ResearchCandidateManifest) -> None:
        existing = self.connection.execute(
            "SELECT candidate_id FROM research_candidates WHERE candidate_id = ?",
            (manifest.candidate_id,),
        ).fetchone()
        if existing is not None:
            raise ResearchRegistryError(f"candidate already exists: {manifest.candidate_id}")
        if manifest.state is not ResearchCandidateState.DRAFT:
            raise ResearchRegistryError("candidate must enter the registry in draft state")
        if (
            manifest.first_observation_ms is not None
            or manifest.last_observation_ms is not None
            or manifest.source_provenance_ids
            or manifest.local_touched_intervals
            or manifest.effective_touched_intervals
            or manifest.performance_report_ids
        ):
            raise ResearchRegistryError(
                "candidate dynamic provenance must be empty at registry creation"
            )

        inherited_contamination = False
        if manifest.parent_candidate_id is not None:
            parent = self.load_candidate(manifest.parent_candidate_id)
            if parent.family_id != manifest.family_id:
                raise ResearchRegistryError("candidate parent must belong to the same family")
            expected_ancestors = parent.ancestor_candidate_ids + (parent.candidate_id,)
            if manifest.ancestor_candidate_ids != expected_ancestors:
                raise ResearchRegistryError(
                    "candidate ancestor lineage does not match parent chain"
                )
            inherited_contamination = (
                parent.state is ResearchCandidateState.REJECTED_CONTAMINATION
            )

        stored_state = (
            ResearchCandidateState.REJECTED_CONTAMINATION
            if inherited_contamination
            else ResearchCandidateState.DRAFT
        )
        initial_reason = (
            "inherited_contamination" if inherited_contamination else "candidate_created"
        )
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO research_candidates (
                    candidate_id,
                    family_id,
                    parent_candidate_id,
                    ancestor_candidate_ids_json,
                    config_digest,
                    code_revision,
                    execution_config_json,
                    risk_config_json,
                    state,
                    freeze_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    manifest.candidate_id,
                    manifest.family_id,
                    manifest.parent_candidate_id,
                    self._ancestor_json(manifest.ancestor_candidate_ids),
                    manifest.config_digest,
                    manifest.code_revision,
                    manifest.execution_config_json,
                    manifest.risk_config_json,
                    stored_state.value,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO research_candidate_state_events (candidate_id, state, reason)
                VALUES (?, ?, ?)
                """,
                (manifest.candidate_id, stored_state.value, initial_reason),
            )

    def load_candidate(self, candidate_id: str) -> ResearchCandidateManifest:
        row = self.connection.execute(
            """
            SELECT candidate_id, family_id, parent_candidate_id,
                   ancestor_candidate_ids_json, config_digest, code_revision,
                   execution_config_json, risk_config_json, state
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

        ancestors = self._decode_ancestors(str(row["ancestor_candidate_ids_json"]))
        local_touched = self._local_touched_intervals(candidate_id)
        effective_touched = self._effective_touched_for_lineage(
            ancestors + (candidate_id,)
        )
        return ResearchCandidateManifest(
            candidate_id=str(row["candidate_id"]),
            family_id=str(row["family_id"]),
            parent_candidate_id=(
                None if row["parent_candidate_id"] is None else str(row["parent_candidate_id"])
            ),
            ancestor_candidate_ids=ancestors,
            config_digest=str(row["config_digest"]),
            code_revision=str(row["code_revision"]),
            execution_config_json=str(row["execution_config_json"]),
            risk_config_json=str(row["risk_config_json"]),
            state=state,
            first_observation_ms=(None if not local_touched else local_touched[0].start_ms),
            last_observation_ms=(None if not local_touched else local_touched[-1].end_ms),
            source_provenance_ids=self._source_provenance_ids(candidate_id),
            local_touched_intervals=local_touched,
            effective_touched_intervals=effective_touched,
            performance_report_ids=self._performance_report_ids(candidate_id),
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
                    batch_id,
                    candidate_id,
                    source_id,
                    replay_run_id,
                    start_ms,
                    end_ms,
                    status,
                    contamination_v4_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, 'admitted', NULL)
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

    def record_performance_report(
        self,
        *,
        candidate_id: str,
        report_id: str,
        payload: dict[str, object],
    ) -> None:
        self.load_candidate(candidate_id)
        if not report_id.strip():
            raise ResearchRegistryError("report_id must not be empty")
        payload_json = self._canonical_json(payload)
        existing = self.connection.execute(
            """
            SELECT candidate_id, payload_json
            FROM research_performance_reports
            WHERE report_id = ?
            """,
            (report_id,),
        ).fetchone()
        if existing is not None:
            stored = (str(existing["candidate_id"]), str(existing["payload_json"]))
            incoming = (candidate_id, payload_json)
            if stored != incoming:
                raise ResearchRegistryError(
                    f"performance report already exists with different data: {report_id}"
                )
            return
        self.connection.execute(
            """
            INSERT INTO research_performance_reports (report_id, candidate_id, payload_json)
            VALUES (?, ?, ?)
            """,
            (report_id, candidate_id, payload_json),
        )
        self.connection.commit()

    def _checkpoint_report_payload(
        self,
        candidate_id: str,
        report_id: str,
    ) -> dict[str, object]:
        row = self.connection.execute(
            """
            SELECT candidate_id, payload_json
            FROM research_performance_reports
            WHERE report_id = ?
            """,
            (report_id,),
        ).fetchone()
        if row is None:
            raise ResearchRegistryError(f"checkpoint report not found: {report_id}")
        if str(row["candidate_id"]) != candidate_id:
            raise ResearchRegistryError("checkpoint report belongs to a different candidate")
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            raise ResearchRegistryError("checkpoint report payload is invalid")
        return payload

    def _validate_checkpoint_report_for_state(
        self,
        payload: dict[str, object],
        state: ResearchCandidateState,
    ) -> None:
        if payload.get("candidate_state") != state.value:
            raise ResearchRegistryError("checkpoint report state does not match transition")
        closed_trade_count = self._report_int(payload, "closed_trade_count")
        closed_trade_days = self._report_int(payload, "closed_trade_days")
        posterior = self._report_decimal(payload, "posterior_probability_positive")
        checkpoint_state = payload.get("checkpoint_state")

        if state is ResearchCandidateState.RESEARCH_PROMISING:
            if (
                checkpoint_state != "research_promising"
                or closed_trade_count < 40
                or closed_trade_days < 7
                or posterior is None
                or posterior < Decimal("0.80")
            ):
                raise ResearchRegistryError(
                    "checkpoint report does not satisfy research-promising threshold"
                )
            return
        if state is ResearchCandidateState.REJECTED_FUTILITY:
            if (
                checkpoint_state != "reject_futility"
                or closed_trade_count < 20
                or posterior is None
                or posterior >= Decimal("0.05")
            ):
                raise ResearchRegistryError(
                    "checkpoint report does not satisfy futility threshold"
                )
            return
        if state is ResearchCandidateState.RESEARCHING:
            if checkpoint_state not in {"insufficient_trades", "continue"}:
                raise ResearchRegistryError("checkpoint report is not a researching state")
            return
        if state is ResearchCandidateState.REJECTED_OPERATIONAL:
            reason_codes = payload.get("reason_codes")
            if not isinstance(reason_codes, list) or not any(
                reason in {"operational_failure", "hard_risk_failure"}
                for reason in reason_codes
            ):
                raise ResearchRegistryError(
                    "checkpoint report lacks operational rejection evidence"
                )
            return
        raise ResearchRegistryError(f"checkpoint report cannot transition to {state.value}")

    def apply_checkpoint_state(
        self,
        candidate_id: str,
        state: ResearchCandidateState,
        *,
        report_id: str,
    ) -> None:
        current = self.load_candidate(candidate_id)
        if current.state in _TERMINAL_STATES and state != current.state:
            raise ResearchRegistryError(f"candidate is terminal: {current.state.value}")
        if current.state is ResearchCandidateState.FROZEN_CHALLENGER:
            raise ResearchRegistryError(
                "candidate is terminal to research checkpoints: frozen_challenger"
            )
        if state not in {
            ResearchCandidateState.RESEARCHING,
            ResearchCandidateState.RESEARCH_PROMISING,
            ResearchCandidateState.REJECTED_FUTILITY,
            ResearchCandidateState.REJECTED_OPERATIONAL,
        }:
            raise ResearchRegistryError(f"checkpoint cannot enter {state.value}")
        if current.state is ResearchCandidateState.RESEARCH_PROMISING and state is (
            ResearchCandidateState.RESEARCHING
        ):
            raise ResearchRegistryError("research-promising candidate cannot return to researching")

        payload = self._checkpoint_report_payload(candidate_id, report_id)
        self._validate_checkpoint_report_for_state(payload, state)
        if current.state is state:
            return
        with self.connection:
            self.connection.execute(
                "UPDATE research_candidates SET state = ? WHERE candidate_id = ?",
                (state.value, candidate_id),
            )
            self.connection.execute(
                """
                INSERT INTO research_candidate_state_events (candidate_id, state, reason)
                VALUES (?, ?, ?)
                """,
                (candidate_id, state.value, f"checkpoint_report:{report_id}"),
            )

    def effective_touched_intervals(self, candidate_id: str) -> tuple[TimeInterval, ...]:
        row = self.connection.execute(
            "SELECT ancestor_candidate_ids_json FROM research_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise ResearchRegistryError(f"candidate not found: {candidate_id}")
        ancestors = self._decode_ancestors(str(row["ancestor_candidate_ids_json"]))
        return self._effective_touched_for_lineage(ancestors + (candidate_id,))

    def _candidate_ids_contaminated_by_roots(
        self,
        root_candidate_ids: set[str],
    ) -> tuple[str, ...]:
        if not root_candidate_ids:
            return ()
        contaminated = set(root_candidate_ids)
        rows = self.connection.execute(
            "SELECT candidate_id, ancestor_candidate_ids_json FROM research_candidates"
        ).fetchall()
        for row in rows:
            ancestors = self._decode_ancestors(str(row["ancestor_candidate_ids_json"]))
            if any(ancestor in root_candidate_ids for ancestor in ancestors):
                contaminated.add(str(row["candidate_id"]))
        return tuple(sorted(contaminated))

    def _force_candidate_contamination(self, candidate_id: str, *, reason: str) -> None:
        row = self.connection.execute(
            "SELECT state FROM research_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise ResearchRegistryError(f"candidate not found: {candidate_id}")
        if str(row["state"]) == ResearchCandidateState.REJECTED_CONTAMINATION.value:
            return
        self.connection.execute(
            "UPDATE research_candidates SET state = ? WHERE candidate_id = ?",
            (ResearchCandidateState.REJECTED_CONTAMINATION.value, candidate_id),
        )
        self.connection.execute(
            """
            INSERT INTO research_candidate_state_events (candidate_id, state, reason)
            VALUES (?, ?, ?)
            """,
            (candidate_id, ResearchCandidateState.REJECTED_CONTAMINATION.value, reason),
        )

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

        overlapping_batches = self.connection.execute(
            """
            SELECT batch_id, candidate_id
            FROM research_batches
            WHERE start_ms < ? AND ? < end_ms
            """,
            (interval.end_ms, interval.start_ms),
        ).fetchall()
        directly_contaminated = {str(row["candidate_id"]) for row in overlapping_batches}
        contaminated_candidates = self._candidate_ids_contaminated_by_roots(
            directly_contaminated
        )

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO research_v4_intervals (run_id, start_ms, end_ms, disposition)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, interval.start_ms, interval.end_ms, disposition),
            )
            for row in overlapping_batches:
                self.connection.execute(
                    """
                    UPDATE research_batches
                    SET status = 'rejected_contamination', contamination_v4_run_id = ?
                    WHERE batch_id = ?
                    """,
                    (run_id, str(row["batch_id"])),
                )
            for candidate_id in contaminated_candidates:
                self._force_candidate_contamination(
                    candidate_id,
                    reason=f"late_v4_source_interval_overlap:{run_id}",
                )

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
        if state in _EVIDENCE_DERIVED_STATES or state in {
            ResearchCandidateState.FROZEN_CHALLENGER,
            ResearchCandidateState.VALIDATING,
            ResearchCandidateState.VALIDATED_EDGE,
            ResearchCandidateState.NO_EDGE,
        }:
            raise ResearchRegistryError(
                f"research state transition cannot enter {state.value}"
            )
        if current.state in _TERMINAL_STATES and state != current.state:
            raise ResearchRegistryError(f"candidate is terminal: {current.state.value}")
        if current.state is ResearchCandidateState.FROZEN_CHALLENGER:
            raise ResearchRegistryError(
                "candidate is terminal to research checkpoints: frozen_challenger"
            )
        if state is current.state:
            return

        allowed = False
        if current.state is ResearchCandidateState.DRAFT:
            allowed = state in {
                ResearchCandidateState.RESEARCHING,
                ResearchCandidateState.REJECTED_OPERATIONAL,
                ResearchCandidateState.REJECTED_CONTAMINATION,
            }
        elif current.state in {
            ResearchCandidateState.RESEARCHING,
            ResearchCandidateState.RESEARCH_PROMISING,
        }:
            allowed = state in {
                ResearchCandidateState.REJECTED_OPERATIONAL,
                ResearchCandidateState.REJECTED_CONTAMINATION,
            }
        if not allowed:
            raise ResearchRegistryError(
                f"invalid research state transition: {current.state.value} -> {state.value}"
            )

        with self.connection:
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

    def freeze_candidate(self, candidate_id: str, *, freeze_ms: int) -> None:
        if freeze_ms < 0:
            raise ResearchRegistryError("freeze_ms must be non-negative")
        current = self.load_candidate(candidate_id)
        if current.state is not ResearchCandidateState.RESEARCH_PROMISING:
            raise ResearchRegistryError("only a research-promising candidate can be frozen")
        with self.connection:
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
                (
                    candidate_id,
                    ResearchCandidateState.FROZEN_CHALLENGER.value,
                    "candidate_frozen",
                ),
            )

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
