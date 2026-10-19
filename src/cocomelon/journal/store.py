from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from itertools import islice
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from cocomelon.domain.journal import (
    ExcursionMetric,
    JournalObservation,
    ObservationKind,
    TradeJournalEntry,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayResult, SourceSegment
from cocomelon.domain.strategy import Direction

SCHEMA_VERSION = 1
SLOW_TRADE_TRANSACTION_MS = 2_000
# Four bind parameters per ref: 200 rows = 800 variables, below SQLite's
# conservative 999-variable limit, even in older build configurations.
TRADE_REF_INSERT_ROWS_PER_STATEMENT = 200
logger = logging.getLogger(__name__)


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


def _payload_market(value: object) -> MarketId:
    if isinstance(value, str):
        market = _market(value)
        if market is None:
            raise JournalConsistencyError("trade market must not be empty")
        return market
    if isinstance(value, dict):
        dex = value.get("dex")
        coin = value.get("coin")
        if not isinstance(dex, str) or not isinstance(coin, str):
            raise JournalConsistencyError("trade market payload is invalid")
        return MarketId(dex=dex, coin=coin)
    raise JournalConsistencyError("trade market payload is invalid")


def _tuple_strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise JournalConsistencyError(f"{field} must be a string array")
    return tuple(value)


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise JournalConsistencyError(f"{field} must be a decimal string")
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise JournalConsistencyError(f"{field} must be a decimal string") from exc
    if not resolved.is_finite():
        raise JournalConsistencyError(f"{field} must be finite")
    return resolved


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise JournalConsistencyError(f"{field} must be a boolean")
    return value


def _excursion_metric(value: object, field: str) -> ExcursionMetric | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise JournalConsistencyError(f"{field} must be an object or null")
    complete = value.get("complete")
    timestamp_ms = value.get("timestamp_ms")
    if not isinstance(complete, bool):
        raise JournalConsistencyError(f"{field}.complete must be a boolean")
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
        raise JournalConsistencyError(f"{field}.timestamp_ms must be an integer")
    kind = value.get("kind")
    source_event_key = value.get("source_event_key")
    if not isinstance(kind, str) or not isinstance(source_event_key, str):
        raise JournalConsistencyError(f"{field} string fields are invalid")
    raw_r_multiple = value.get("r_multiple")
    r_multiple = None if raw_r_multiple is None else _decimal(raw_r_multiple, f"{field}.r_multiple")
    return ExcursionMetric(
        kind=kind,
        price=_decimal(value.get("price"), f"{field}.price"),
        per_unit=_decimal(value.get("per_unit"), f"{field}.per_unit"),
        fraction=_decimal(value.get("fraction"), f"{field}.fraction"),
        currency=_decimal(value.get("currency"), f"{field}.currency"),
        r_multiple=r_multiple,
        timestamp_ms=timestamp_ms,
        source_event_key=source_event_key,
        complete=complete,
    )


class JournalStore:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        if read_only:
            # Offline research must never open a missing source journal in
            # SQLite's implicit-create mode or touch its authoritative
            # account/close records.
            if not self.path.is_file():
                raise JournalConsistencyError("read-only journal file missing")
            self.connection = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True,
            )
            self.connection.execute("PRAGMA query_only = ON")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            self._initialize_schema(read_only=read_only)
        except Exception:
            self.connection.close()
            raise
        # Per-process diagnostics only; never stored in the signed trade journal.
        self.slow_trade_sql_count = 0
        self.slow_trade_sql_max_total_ms = 0
        self.last_slow_trade_sql: dict[str, int] | None = None

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(
            _json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def _initialize_schema(self, *, read_only: bool = False) -> None:
        known_tables = frozenset(
            {
                "journal_meta",
                "journal_observations",
                "journal_trades",
                "journal_trade_refs",
                "replay_manifests",
                "replay_runs",
                "compaction_manifests",
            }
        )
        existing_tables = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        existing_store = bool(existing_tables & known_tables)
        if read_only and not existing_store:
            raise JournalConsistencyError("read-only original journal schema missing")
        if existing_store:
            if "journal_meta" not in existing_tables:
                raise JournalConsistencyError("missing journal schema metadata")
            version_row = self.connection.execute(
                "SELECT value FROM journal_meta WHERE key = 'schema_version'"
            ).fetchone()
            if version_row is None:
                raise JournalConsistencyError("missing journal schema version")
            persisted_version = str(version_row[0])
            if persisted_version != str(SCHEMA_VERSION):
                raise JournalConsistencyError(
                    "unsupported journal schema version: "
                    f"{persisted_version}; supported={SCHEMA_VERSION}"
                )
            missing_tables = known_tables - existing_tables
            if missing_tables:
                raise JournalConsistencyError(
                    "incomplete journal schema: missing tables="
                    + ",".join(sorted(missing_tables))
                )
        if read_only:
            # No CREATE TABLE, metadata insert or COMMIT even when every
            # schema and canonical trade checksum validates. Source stays
            # fully immutable under this connection.
            return

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
        if not existing_store:
            self.connection.execute(
                "INSERT INTO journal_meta(key, value) VALUES('schema_version', ?)",
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

    def iter_observations(self) -> Iterator[JournalObservation]:
        rows = self.connection.execute(
            """
            SELECT observation_id
            FROM journal_observations
            ORDER BY timestamp_ms, observation_id
            """
        ).fetchall()
        for row in rows:
            observation = self.load_observation(str(row[0]))
            if observation is None:
                raise JournalConsistencyError("journal observation disappeared during iteration")
            yield observation

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

    @staticmethod
    def _record_trade_transaction(
        connection: sqlite3.Connection,
        trade: TradeJournalEntry,
        payload: str,
    ) -> dict[str, int] | None:
        refs = (
            ("exit_plan", trade.exit_plan_ids),
            ("exit_attempt", trade.exit_attempt_ids),
            ("fill", trade.fill_ids),
            ("position_action", trade.position_action_ids),
            ("funding", trade.funding_event_ids),
            ("health", trade.health_refs),
        )
        # This remains one BEGIN IMMEDIATE -> COMMIT transaction. A long
        # awaited write holds the paper record-pump ordering lock even when
        # sqlite I/O runs in a thread. Distinguish lock wait, ref insertion,
        # and commit latency without logging account identifiers or payloads.
        started = perf_counter()
        try:
            connection.execute("BEGIN IMMEDIATE")
            acquired = perf_counter()
            existing = connection.execute(
                "SELECT payload_json FROM journal_trades WHERE trade_id = ?",
                (trade.trade_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise JournalConsistencyError(
                        f"conflicting journal trade: {trade.trade_id}"
                    )
                connection.commit()
                return None
            connection.execute(
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
            refs_started = perf_counter()
            # Keep the exact same six ref-kind groups, original ordinals,
            # row uniqueness and single transaction. The paper worker has
            # observed 4,893 refs taking 3,335ms even after 200-row batching.
            # SQLite JSON1 expands each kind's exact string array in ONE
            # VM statement, instead of 25+ separate multi-VALUES INSERTs.
            # Legacy SQLite without json_each retains the bounded method.
            JournalStore._insert_trade_ref_rows(
                connection, trade.trade_id, refs
            )
            refs_done = perf_counter()
            connection.commit()
            committed = perf_counter()
            JournalStore._log_slow_trade_transaction(
                begin_wait_ms=max(0, int((acquired - started) * 1000)),
                trade_row_ms=max(0, int((refs_started - acquired) * 1000)),
                ref_insert_ms=max(0, int((refs_done - refs_started) * 1000)),
                commit_ms=max(0, int((committed - refs_done) * 1000)),
                total_ms=max(0, int((committed - started) * 1000)),
                ref_rows=sum(len(values) for _, values in refs),
            )
            # Return only anonymous stage timings to the awaiting coroutine.
            # The worker heartbeat can then expose them while Actions logs
            # for the actively running paper job are still unavailable.
            total_ms = max(0, int((committed - started) * 1000))
            if total_ms >= SLOW_TRADE_TRANSACTION_MS:
                return {
                    "total_ms": total_ms,
                    "begin_wait_ms": max(0, int((acquired - started) * 1000)),
                    "trade_row_ms": max(0, int((refs_started - acquired) * 1000)),
                    "ref_insert_ms": max(0, int((refs_done - refs_started) * 1000)),
                    "commit_ms": max(0, int((committed - refs_done) * 1000)),
                    "ref_rows": sum(len(values) for _, values in refs),
                }
            return None
        except Exception:
            connection.rollback()
            raise

    @staticmethod
    def _sqlite_json_each_available(connection: sqlite3.Connection) -> bool:
        try:
            connection.execute("SELECT 1 FROM json_each('[]') LIMIT 1")
        except sqlite3.OperationalError as exc:
            # Older SQLite builds can omit JSON1. Do not turn any unrelated
            # SQLite error into a silent fallback or weaken the write.
            if "no such table: json_each" in str(exc).lower():
                return False
            raise
        return True

    @staticmethod
    def _insert_trade_ref_rows(
        connection: sqlite3.Connection,
        trade_id: str,
        refs: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> None:
        if JournalStore._sqlite_json_each_available(connection):
            for ref_kind, values in refs:
                if not values:
                    continue
                connection.execute(
                    "INSERT INTO journal_trade_refs("
                    "trade_id, ref_kind, ordinal, ref_id) "
                    "SELECT ?, ?, CAST(j.key AS INTEGER), j.value "
                    "FROM json_each(?) AS j ORDER BY CAST(j.key AS INTEGER)",
                    (
                        trade_id,
                        ref_kind,
                        json.dumps(
                            values, ensure_ascii=False, separators=(",", ":")
                        ),
                    ),
                )
            return

        # Four bind parameters per ref, <=200 rows/statement and <=800
        # variables for SQLite builds limited to 999 variables. This is
        # also the exact previous production write path.
        rows = (
            (trade_id, ref_kind, ordinal, ref_id)
            for ref_kind, values in refs
            for ordinal, ref_id in enumerate(values)
        )
        while batch := list(
            islice(rows, TRADE_REF_INSERT_ROWS_PER_STATEMENT)
        ):
            placeholders = ",".join("(?, ?, ?, ?)" for _ in batch)
            connection.execute(
                "INSERT INTO journal_trade_refs("
                "trade_id, ref_kind, ordinal, ref_id) VALUES "
                + placeholders,
                tuple(value for row in batch for value in row),
            )

    @staticmethod
    def _log_slow_trade_transaction(
        *, begin_wait_ms: int, trade_row_ms: int, ref_insert_ms: int,
        commit_ms: int, total_ms: int, ref_rows: int,
    ) -> None:
        if total_ms < SLOW_TRADE_TRANSACTION_MS:
            return
        logger.warning(
            "SLOW_PAPER_JOURNAL_TRADE_SQL "
            "total_ms=%d begin_wait_ms=%d trade_row_ms=%d "
            "ref_insert_ms=%d commit_ms=%d ref_rows=%d",
            total_ms, begin_wait_ms, trade_row_ms,
            ref_insert_ms, commit_ms, ref_rows,
        )

    def record_trade(self, trade: TradeJournalEntry) -> None:
        self._record_trade_transaction(
            self.connection,
            trade,
            self._canonical_json(trade),
        )

    @staticmethod
    def _record_trade_at_path(
        path: Path,
        trade: TradeJournalEntry,
        payload: str,
    ) -> dict[str, int] | None:
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            return JournalStore._record_trade_transaction(
                connection,
                trade,
                payload,
            )
        finally:
            connection.close()

    async def record_trade_async(
        self,
        trade: TradeJournalEntry,
    ) -> None:
        payload = self._canonical_json(trade)
        stages = await asyncio.to_thread(
            self._record_trade_at_path,
            self.path,
            trade,
            payload,
        )
        if stages is not None:
            self.slow_trade_sql_count += 1
            self.slow_trade_sql_max_total_ms = max(
                self.slow_trade_sql_max_total_ms, stages["total_ms"]
            )
            self.last_slow_trade_sql = stages

    def load_trade(self, trade_id: str) -> TradeJournalEntry | None:
        row = self.connection.execute(
            "SELECT payload_json FROM journal_trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            raw = json.loads(str(row[0]))
        except json.JSONDecodeError as exc:
            raise JournalConsistencyError("journal trade payload must be valid JSON") from exc
        if not isinstance(raw, dict):
            raise JournalConsistencyError("journal trade payload must be an object")
        try:
            direction = Direction(str(raw["direction"]))
            evidence_class = EvidenceClass(str(raw["evidence_class"]))
            result = TradeJournalEntry(
                market=_payload_market(raw.get("market")),
                direction=direction,
                opened_at_ms=int(raw["opened_at_ms"]),
                closed_at_ms=int(raw["closed_at_ms"]),
                feature_snapshot_id=str(raw["feature_snapshot_id"]),
                strategy_decision_id=str(raw["strategy_decision_id"]),
                risk_decision_id=str(raw["risk_decision_id"]),
                opening_plan_id=str(raw["opening_plan_id"]),
                opening_attempt_id=str(raw["opening_attempt_id"]),
                exit_plan_ids=_tuple_strings(raw.get("exit_plan_ids"), "exit_plan_ids"),
                exit_attempt_ids=_tuple_strings(
                    raw.get("exit_attempt_ids"), "exit_attempt_ids"
                ),
                fill_ids=_tuple_strings(raw.get("fill_ids"), "fill_ids"),
                position_action_ids=_tuple_strings(
                    raw.get("position_action_ids"), "position_action_ids"
                ),
                funding_event_ids=_tuple_strings(
                    raw.get("funding_event_ids"), "funding_event_ids"
                ),
                initial_stop=_decimal(raw.get("initial_stop"), "initial_stop"),
                initial_risk_amount=_decimal(
                    raw.get("initial_risk_amount"), "initial_risk_amount"
                ),
                entry_price=_decimal(raw.get("entry_price"), "entry_price"),
                exit_price=_decimal(raw.get("exit_price"), "exit_price"),
                filled_quantity=_decimal(raw.get("filled_quantity"), "filled_quantity"),
                gross_realized_pnl=_decimal(
                    raw.get("gross_realized_pnl"), "gross_realized_pnl"
                ),
                entry_fees=_decimal(raw.get("entry_fees"), "entry_fees"),
                exit_fees=_decimal(raw.get("exit_fees"), "exit_fees"),
                funding_cash_pnl=_decimal(
                    raw.get("funding_cash_pnl"), "funding_cash_pnl"
                ),
                net_pnl=_decimal(raw.get("net_pnl"), "net_pnl"),
                entry_slippage_amount=_decimal(
                    raw.get("entry_slippage_amount"), "entry_slippage_amount"
                ),
                exit_slippage_amount=_decimal(
                    raw.get("exit_slippage_amount"), "exit_slippage_amount"
                ),
                entry_slippage_fraction=_decimal(
                    raw.get("entry_slippage_fraction"), "entry_slippage_fraction"
                ),
                exit_slippage_fraction=_decimal(
                    raw.get("exit_slippage_fraction"), "exit_slippage_fraction"
                ),
                holding_duration_ms=int(raw["holding_duration_ms"]),
                mfe=_excursion_metric(raw.get("mfe"), "mfe"),
                mae=_excursion_metric(raw.get("mae"), "mae"),
                net_r=_decimal(raw.get("net_r"), "net_r"),
                equity_before=_decimal(raw.get("equity_before"), "equity_before"),
                equity_after=_decimal(raw.get("equity_after"), "equity_after"),
                exit_reason=str(raw["exit_reason"]),
                health_refs=_tuple_strings(raw.get("health_refs"), "health_refs"),
                evidence_class=evidence_class,
                replay_run_id=_optional_string(raw.get("replay_run_id")),
                schema_version=int(raw["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, JournalConsistencyError):
                raise
            raise JournalConsistencyError("journal trade payload is invalid") from exc
        if result.trade_id != trade_id:
            raise JournalConsistencyError("stored trade id does not match canonical payload")
        return result

    def iter_trades(self) -> Iterator[TradeJournalEntry]:
        rows = self.connection.execute(
            """
            SELECT trade_id
            FROM journal_trades
            ORDER BY opened_at_ms, closed_at_ms, trade_id
            """
        ).fetchall()
        for row in rows:
            trade = self.load_trade(str(row[0]))
            if trade is None:
                raise JournalConsistencyError("journal trade disappeared during iteration")
            yield trade

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

    def load_replay_result(self, run_id: str) -> ReplayResult | None:
        row = self.connection.execute(
            "SELECT manifest_id, status, result_json FROM replay_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None or row[1] != "finished" or row[2] is None:
            return None
        try:
            raw = json.loads(str(row[2]))
        except json.JSONDecodeError as exc:
            raise JournalConsistencyError("replay result payload must be valid JSON") from exc
        if not isinstance(raw, dict):
            raise JournalConsistencyError("replay result payload must be an object")
        try:
            result = ReplayResult(
                manifest_id=str(raw["manifest_id"]),
                run_id=str(raw["run_id"]),
                evidence_class=EvidenceClass(str(raw["evidence_class"])),
                start_ms=int(raw["start_ms"]),
                end_ms=int(raw["end_ms"]),
                processed_events=int(raw["processed_events"]),
                processed_gaps=int(raw["processed_gaps"]),
                strategy_decisions=int(raw["strategy_decisions"]),
                risk_approvals=int(raw["risk_approvals"]),
                risk_rejections=int(raw["risk_rejections"]),
                execution_attempts=int(raw["execution_attempts"]),
                fills=int(raw["fills"]),
                opened_positions=int(raw["opened_positions"]),
                closed_positions=int(raw["closed_positions"]),
                journal_observations=int(raw["journal_observations"]),
                closed_trade_ids=_tuple_strings(raw.get("closed_trade_ids"), "closed_trade_ids"),
                final_account_state_id=str(raw["final_account_state_id"]),
                data_complete=_boolean(raw.get("data_complete"), "data_complete"),
                schema_version=int(raw["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, JournalConsistencyError):
                raise
            raise JournalConsistencyError("replay result payload is invalid") from exc
        if result.run_id != run_id:
            raise JournalConsistencyError("stored replay run id does not match payload")
        if result.manifest_id != str(row[0]):
            raise JournalConsistencyError("stored replay manifest id does not match payload")
        return result

    def iter_replay_results(self) -> Iterator[ReplayResult]:
        rows = self.connection.execute(
            """
            SELECT run_id
            FROM replay_runs
            WHERE status = 'finished' AND result_json IS NOT NULL
            ORDER BY run_id
            """
        ).fetchall()
        for row in rows:
            result = self.load_replay_result(str(row[0]))
            if result is None:
                raise JournalConsistencyError("replay result disappeared during iteration")
            yield result

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
