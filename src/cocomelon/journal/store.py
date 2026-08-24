from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, cast

from cocomelon.domain.journal import JournalObservation, ObservationKind, TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayResult, SourceSegment

SCHEMA_VERSION = 1


class JournalConsistencyError(RuntimeError):
    pass


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, MarketId):
        return value.canonical
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON mapping keys must be strings")
            normalized[key] = _json_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__dataclass_fields__"):
        return _json_value(asdict(cast(Any, value)))
    raise TypeError(f"unsupported journal value type: {type(value).__name__}")


def _market(value: str | None) -> MarketId | None:
    if value is None:
        return None
    if ":" in value:
        dex = value.split(":", 1)[0]
        return MarketId.from_wire_name(dex, value)
    return MarketId.from_wire_name("", value)


def _tuple_strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise JournalConsistencyError(f"{field} must be a string array")
    return tuple(value)


class JournalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(
            _json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def _initialize_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS journal_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS journal_observations (
                observation_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                market TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS journal_trades (
                trade_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                direction TEXT NOT NULL,
                opened_at_ms INTEGER NOT NULL,
                closed_at_ms INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS journal_trade_refs (
                trade_id TEXT NOT NULL,
                ref_kind TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                ref_id TEXT NOT NULL,
                PRIMARY KEY (trade_id, ref_kind, ordinal),
                FOREIGN KEY (trade_id) REFERENCES journal_trades(trade_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS replay_manifests (
                manifest_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS replay_runs (
                run_id TEXT PRIMARY KEY,
                manifest_id TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT,
                FOREIGN KEY (manifest_id) REFERENCES replay_manifests(manifest_id)
            );
            CREATE TABLE IF NOT EXISTS compaction_manifests (
                manifest_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            """
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO journal_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.connection.commit()

    def _canonical_observation(self, observation: JournalObservation) -> str:
        return self._canonical_json(
            {
                "kind": observation.kind.value,
                "timestamp_ms": observation.timestamp_ms,
                "market": None if observation.market is None else observation.market.canonical,
                "feature_snapshot_id": observation.feature_snapshot_id,
                "strategy_decision_id": observation.strategy_decision_id,
                "risk_decision_id": observation.risk_decision_id,
                "plan_id": observation.plan_id,
                "attempt_id": observation.attempt_id,
                "position_action_id": observation.position_action_id,
                "account_state_id": observation.account_state_id,
                "funding_event_id": observation.funding_event_id,
                "reason_codes": observation.reason_codes,
                "health_refs": observation.health_refs,
                "replay_run_id": observation.replay_run_id,
                "schema_version": observation.schema_version,
            }
        )

    def record_observation(self, observation: JournalObservation) -> None:
        self._record_observation_transaction(observation)

    def _record_observation_transaction(
        self,
        observation: JournalObservation,
        *,
        after_primary: Callable[[], None] | None = None,
    ) -> None:
        payload = self._canonical_observation(observation)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT payload_json FROM journal_observations WHERE observation_id = ?",
                (observation.observation_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise JournalConsistencyError(
                        f"conflicting journal observation: {observation.observation_id}"
                    )
                self.connection.commit()
                return
            self.connection.execute(
                """
                INSERT INTO journal_observations(
                    observation_id, kind, timestamp_ms, market, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    observation.observation_id,
                    observation.kind.value,
                    observation.timestamp_ms,
                    None if observation.market is None else observation.market.canonical,
                    payload,
                ),
            )
            if after_primary is not None:
                after_primary()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def load_observation(self, observation_id: str) -> JournalObservation | None:
        row = self.connection.execute(
            "SELECT payload_json FROM journal_observations WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()
        if row is None:
            return None
        raw = json.loads(row[0])
        if not isinstance(raw, dict):
            raise JournalConsistencyError("journal observation payload must be an object")
        result = JournalObservation(
            kind=ObservationKind(str(raw["kind"])),
            timestamp_ms=int(raw["timestamp_ms"]),
            market=_market(raw.get("market") if isinstance(raw.get("market"), str) else None),
            feature_snapshot_id=_optional_string(raw.get("feature_snapshot_id")),
            strategy_decision_id=_optional_string(raw.get("strategy_decision_id")),
            risk_decision_id=_optional_string(raw.get("risk_decision_id")),
            plan_id=_optional_string(raw.get("plan_id")),
            attempt_id=_optional_string(raw.get("attempt_id")),
            position_action_id=_optional_string(raw.get("position_action_id")),
            account_state_id=_optional_string(raw.get("account_state_id")),
            reason_codes=_tuple_strings(raw.get("reason_codes"), "reason_codes"),
            health_refs=_tuple_strings(raw.get("health_refs"), "health_refs"),
            replay_run_id=_optional_string(raw.get("replay_run_id")),
            funding_event_id=_optional_string(raw.get("funding_event_id")),
            schema_version=int(raw["schema_version"]),
        )
        if result.observation_id != observation_id:
            raise JournalConsistencyError("stored observation id does not match canonical payload")
        return result

    def record_manifest(self, manifest: ReplayManifest) -> None:
        payload = self._canonical_manifest(manifest)
        self._insert_consistent("replay_manifests", "manifest_id", manifest.manifest_id, payload)

    def _canonical_manifest(self, manifest: ReplayManifest) -> str:
        return self._canonical_json(
            {
                "evidence_class": manifest.evidence_class.value,
                "start_ms": manifest.start_ms,
                "end_ms": manifest.end_ms,
                "segments": tuple(item.canonical_payload() for item in manifest.segments),
                "gap_refs": manifest.gap_refs,
                "code_revision": manifest.code_revision,
                "config_digest": manifest.config_digest,
                "feature_version": manifest.feature_version,
                "strategy_version": manifest.strategy_version,
                "risk_version": manifest.risk_version,
                "execution_config_version": manifest.execution_config_version,
                "fee_schedule_id": manifest.fee_schedule_id,
                "replay_engine_version": manifest.replay_engine_version,
                "dataset_manifest_id": manifest.dataset_manifest_id,
                "schema_version": manifest.schema_version,
            }
        )

    def load_manifest(self, manifest_id: str) -> ReplayManifest | None:
        row = self.connection.execute(
            "SELECT payload_json FROM replay_manifests WHERE manifest_id = ?",
            (manifest_id,),
        ).fetchone()
        if row is None:
            return None
        raw = json.loads(row[0])
        if not isinstance(raw, dict):
            raise JournalConsistencyError("manifest payload must be an object")
        raw_segments = raw.get("segments")
        if not isinstance(raw_segments, list):
            raise JournalConsistencyError("manifest segments must be an array")
        segments = tuple(_source_segment(item) for item in raw_segments)
        result = ReplayManifest(
            evidence_class=EvidenceClass(str(raw["evidence_class"])),
            start_ms=int(raw["start_ms"]),
            end_ms=int(raw["end_ms"]),
            segments=segments,
            gap_refs=_tuple_strings(raw.get("gap_refs"), "gap_refs"),
            code_revision=str(raw["code_revision"]),
            config_digest=str(raw["config_digest"]),
            feature_version=str(raw["feature_version"]),
            strategy_version=str(raw["strategy_version"]),
            risk_version=str(raw["risk_version"]),
            execution_config_version=_optional_string(raw.get("execution_config_version")),
            fee_schedule_id=_optional_string(raw.get("fee_schedule_id")),
            replay_engine_version=str(raw["replay_engine_version"]),
            dataset_manifest_id=_optional_string(raw.get("dataset_manifest_id")),
            schema_version=int(raw["schema_version"]),
        )
        if result.manifest_id != manifest_id:
            raise JournalConsistencyError("stored manifest id does not match canonical payload")
        return result

    def _insert_consistent(self, table: str, key_field: str, key: str, payload: str) -> None:
        existing = self.connection.execute(
            f"SELECT payload_json FROM {table} WHERE {key_field} = ?",  # noqa: S608
            (key,),
        ).fetchone()
        if existing is not None:
            if existing[0] != payload:
                raise JournalConsistencyError(f"conflicting {table} record: {key}")
            return
        self.connection.execute(
            f"INSERT INTO {table}({key_field}, payload_json) VALUES (?, ?)",  # noqa: S608
            (key, payload),
        )
        self.connection.commit()

    def record_trade(self, trade: TradeJournalEntry) -> None:
        payload = self._canonical_json(trade)
        refs = (
            ("exit_plan", trade.exit_plan_ids),
            ("exit_attempt", trade.exit_attempt_ids),
            ("fill", trade.fill_ids),
            ("position_action", trade.position_action_ids),
            ("funding", trade.funding_event_ids),
            ("health", trade.health_refs),
        )
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT payload_json FROM journal_trades WHERE trade_id = ?",
                (trade.trade_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise JournalConsistencyError(f"conflicting journal trade: {trade.trade_id}")
                self.connection.commit()
                return
            self.connection.execute(
                """
                INSERT INTO journal_trades(
                    trade_id, market, direction, opened_at_ms, closed_at_ms, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.trade_id,
                    trade.market.canonical,
                    trade.direction.value,
                    trade.opened_at_ms,
                    trade.closed_at_ms,
                    payload,
                ),
            )
            for ref_kind, values in refs:
                for ordinal, ref_id in enumerate(values):
                    self.connection.execute(
                        """
                        INSERT INTO journal_trade_refs(trade_id, ref_kind, ordinal, ref_id)
                        VALUES (?, ?, ?, ?)
                        """,
                        (trade.trade_id, ref_kind, ordinal, ref_id),
                    )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def begin_run(self, manifest_id: str, run_id: str) -> None:
        existing = self.connection.execute(
            "SELECT manifest_id, status, result_json FROM replay_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if existing is not None:
            if existing != (manifest_id, "running", None):
                raise JournalConsistencyError(f"conflicting replay run: {run_id}")
            return
        self.connection.execute(
            "INSERT INTO replay_runs(run_id, manifest_id, status) VALUES (?, ?, 'running')",
            (run_id, manifest_id),
        )
        self.connection.commit()

    def finish_run(self, result: ReplayResult) -> None:
        payload = self._canonical_json(result)
        existing = self.connection.execute(
            "SELECT manifest_id, status, result_json FROM replay_runs WHERE run_id = ?",
            (result.run_id,),
        ).fetchone()
        if existing is None:
            raise JournalConsistencyError(f"unknown replay run: {result.run_id}")
        expected = (result.manifest_id, "finished", payload)
        if existing[1] == "finished":
            if existing != expected:
                raise JournalConsistencyError(f"conflicting replay result: {result.run_id}")
            return
        if existing[0] != result.manifest_id or existing[1] != "running":
            raise JournalConsistencyError(f"invalid replay run state: {result.run_id}")
        self.connection.execute(
            "UPDATE replay_runs SET status = 'finished', result_json = ? WHERE run_id = ?",
            (payload, result.run_id),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise JournalConsistencyError("expected optional string")
    return value


def _source_segment(value: object) -> SourceSegment:
    if not isinstance(value, dict):
        raise JournalConsistencyError("source segment must be an object")
    return SourceSegment(
        relative_path=str(value["relative_path"]),
        partition=str(value["partition"]),
        sha256=str(value["sha256"]),
        byte_count=int(value["byte_count"]),
        row_count=int(value["row_count"]),
        schema_version=int(value["schema_version"]),
        first_available_at_ms=int(value["first_available_at_ms"]),
        last_available_at_ms=int(value["last_available_at_ms"]),
    )
