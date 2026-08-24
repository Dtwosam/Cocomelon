from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cocomelon.domain.evaluation import (
    AccountEquityFact,
    DecisionEvaluationFact,
    EquityFactKind,
    EvaluationDatasetManifest,
    EvaluationResult,
    ReplayEvaluationSource,
)
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.result_codec import (
    EvaluationResultCodecError,
    evaluation_result_from_payload,
    evaluation_result_payload,
)


class EvaluationConsistencyError(RuntimeError):
    pass


def _market(value: object) -> MarketId:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationConsistencyError("evaluation market must be a non-empty string")
    if ":" in value:
        dex = value.split(":", 1)[0]
        return MarketId.from_wire_name(dex, value)
    return MarketId.from_wire_name("", value)


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise EvaluationConsistencyError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise EvaluationConsistencyError(f"{field} must be a decimal string") from exc
    if not result.is_finite():
        raise EvaluationConsistencyError(f"{field} must be finite")
    return result


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationConsistencyError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EvaluationConsistencyError(f"{field} must be a string array")
    return tuple(value)


def _int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvaluationConsistencyError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationConsistencyError(f"{field} must be a boolean")
    return value


def _replay_evaluation_source(value: object) -> ReplayEvaluationSource:
    if not isinstance(value, dict):
        raise EvaluationConsistencyError("evaluation replay source must be an object")
    try:
        return ReplayEvaluationSource(
            run_id=_string(value.get("run_id"), "run_id"),
            manifest_id=_string(value.get("manifest_id"), "manifest_id"),
            result_digest=_string(value.get("result_digest"), "result_digest"),
            evidence_class=EvidenceClass(
                _string(value.get("evidence_class"), "evidence_class")
            ),
            start_ms=_int(value.get("start_ms"), "start_ms"),
            end_ms=_int(value.get("end_ms"), "end_ms"),
            data_complete=_boolean(value.get("data_complete"), "data_complete"),
        )
    except ValueError as exc:
        raise EvaluationConsistencyError("evaluation replay source is invalid") from exc


class EvaluationFactStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self._initialize_schema()

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def _initialize_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS evaluation_decision_facts (
                fact_id TEXT PRIMARY KEY,
                strategy_decision_id TEXT NOT NULL,
                replay_run_id TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE(strategy_decision_id, replay_run_id)
            );
            CREATE TABLE IF NOT EXISTS evaluation_equity_facts (
                fact_id TEXT PRIMARY KEY,
                replay_run_id TEXT NOT NULL,
                account_state_id TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE(replay_run_id, account_state_id)
            );
            CREATE TABLE IF NOT EXISTS evaluation_dataset_manifests (
                manifest_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evaluation_split_manifests (
                split_manifest_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evaluation_candidate_sets (
                candidate_set_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evaluation_oos_consumptions (
                test_partition_digest TEXT PRIMARY KEY,
                candidate_set_id TEXT NOT NULL,
                policy_id TEXT NOT NULL,
                consumed_by_evaluation_id TEXT
            );
            CREATE TABLE IF NOT EXISTS evaluation_results (
                evaluation_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def _canonical_decision_fact(self, fact: DecisionEvaluationFact) -> str:
        return self._canonical_json(
            {
                "strategy_decision_id": fact.strategy_decision_id,
                "feature_snapshot_id": fact.feature_snapshot_id,
                "replay_run_id": fact.replay_run_id,
                "market": fact.market.canonical,
                "direction": fact.direction.value,
                "timestamp_ms": fact.timestamp_ms,
                "score": str(fact.score),
                "lead_strategy": fact.lead_strategy,
                "signal_ids": fact.signal_ids,
                "reason_codes": fact.reason_codes,
                "trend_regime": fact.trend_regime.value,
                "volatility_regime": fact.volatility_regime.value,
                "schema_version": fact.schema_version,
            }
        )

    def _canonical_equity_fact(self, fact: AccountEquityFact) -> str:
        return self._canonical_json(
            {
                "replay_run_id": fact.replay_run_id,
                "account_state_id": fact.account_state_id,
                "timestamp_ms": fact.timestamp_ms,
                "kind": fact.kind.value,
                "equity": str(fact.equity),
                "cash": str(fact.cash),
                "unrealized_pnl": str(fact.unrealized_pnl),
                "realized_gross_pnl": str(fact.realized_gross_pnl),
                "cumulative_fees": str(fact.cumulative_fees),
                "cumulative_funding": str(fact.cumulative_funding),
                "gross_open_notional": str(fact.gross_open_notional),
                "open_position_count": fact.open_position_count,
                "schema_version": fact.schema_version,
            }
        )

    def _canonical_dataset_manifest(self, manifest: EvaluationDatasetManifest) -> str:
        return self._canonical_json(
            {
                "sources": tuple(source.canonical_payload() for source in manifest.sources),
                "trade_ids": manifest.trade_ids,
                "decision_fact_ids": manifest.decision_fact_ids,
                "equity_fact_ids": manifest.equity_fact_ids,
                "start_ms": manifest.start_ms,
                "end_ms": manifest.end_ms,
                "code_revision": manifest.code_revision,
                "data_complete": manifest.data_complete,
                "gap_refs": manifest.gap_refs,
                "mixed_evidence_diagnostic": manifest.mixed_evidence_diagnostic,
                "schema_version": manifest.schema_version,
            }
        )

    def record_decision_fact(self, fact: DecisionEvaluationFact) -> None:
        self._record_decision_fact_transaction(fact)

    def _record_decision_fact_transaction(
        self,
        fact: DecisionEvaluationFact,
        *,
        after_primary: Callable[[], None] | None = None,
    ) -> None:
        payload = self._canonical_decision_fact(fact)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT payload_json FROM evaluation_decision_facts WHERE fact_id = ?",
                (fact.fact_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise EvaluationConsistencyError(
                        f"conflicting evaluation decision fact: {fact.fact_id}"
                    )
                self.connection.commit()
                return
            by_decision = self.connection.execute(
                """
                SELECT fact_id, payload_json
                FROM evaluation_decision_facts
                WHERE strategy_decision_id = ? AND replay_run_id = ?
                """,
                (fact.strategy_decision_id, fact.replay_run_id),
            ).fetchone()
            if by_decision is not None:
                raise EvaluationConsistencyError(
                    "conflicting evaluation decision fact for strategy decision"
                )
            self.connection.execute(
                """
                INSERT INTO evaluation_decision_facts(
                    fact_id, strategy_decision_id, replay_run_id, timestamp_ms, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    fact.fact_id,
                    fact.strategy_decision_id,
                    fact.replay_run_id,
                    fact.timestamp_ms,
                    payload,
                ),
            )
            if after_primary is not None:
                after_primary()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def record_equity_fact(self, fact: AccountEquityFact) -> None:
        payload = self._canonical_equity_fact(fact)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT payload_json FROM evaluation_equity_facts WHERE fact_id = ?",
                (fact.fact_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise EvaluationConsistencyError(
                        f"conflicting evaluation equity fact: {fact.fact_id}"
                    )
                self.connection.commit()
                return
            by_state = self.connection.execute(
                """
                SELECT fact_id
                FROM evaluation_equity_facts
                WHERE replay_run_id = ? AND account_state_id = ?
                """,
                (fact.replay_run_id, fact.account_state_id),
            ).fetchone()
            if by_state is not None:
                raise EvaluationConsistencyError(
                    "conflicting evaluation equity fact for account state"
                )
            self.connection.execute(
                """
                INSERT INTO evaluation_equity_facts(
                    fact_id, replay_run_id, account_state_id, timestamp_ms, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    fact.fact_id,
                    fact.replay_run_id,
                    fact.account_state_id,
                    fact.timestamp_ms,
                    payload,
                ),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def load_decision_fact(self, fact_id: str) -> DecisionEvaluationFact | None:
        row = self.connection.execute(
            "SELECT payload_json FROM evaluation_decision_facts WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            raw = json.loads(str(row[0]))
        except json.JSONDecodeError as exc:
            raise EvaluationConsistencyError("decision fact payload must be valid JSON") from exc
        if not isinstance(raw, dict):
            raise EvaluationConsistencyError("decision fact payload must be an object")
        try:
            result = DecisionEvaluationFact(
                strategy_decision_id=_string(
                    raw.get("strategy_decision_id"), "strategy_decision_id"
                ),
                feature_snapshot_id=_string(raw.get("feature_snapshot_id"), "feature_snapshot_id"),
                replay_run_id=_string(raw.get("replay_run_id"), "replay_run_id"),
                market=_market(raw.get("market")),
                direction=Direction(_string(raw.get("direction"), "direction")),
                timestamp_ms=_int(raw.get("timestamp_ms"), "timestamp_ms"),
                score=_decimal(raw.get("score"), "score"),
                lead_strategy=_optional_string(raw.get("lead_strategy"), "lead_strategy"),
                signal_ids=_string_tuple(raw.get("signal_ids"), "signal_ids"),
                reason_codes=_string_tuple(raw.get("reason_codes"), "reason_codes"),
                trend_regime=TrendRegime(
                    _string(raw.get("trend_regime"), "trend_regime")
                ),
                volatility_regime=VolatilityRegime(
                    _string(raw.get("volatility_regime"), "volatility_regime")
                ),
                schema_version=_int(raw.get("schema_version"), "schema_version"),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, EvaluationConsistencyError):
                raise
            raise EvaluationConsistencyError("decision fact payload is invalid") from exc
        if result.fact_id != fact_id:
            raise EvaluationConsistencyError("stored decision fact id does not match payload")
        return result

    def load_decision_by_strategy_id(
        self,
        strategy_decision_id: str,
        replay_run_id: str,
    ) -> DecisionEvaluationFact | None:
        row = self.connection.execute(
            """
            SELECT fact_id
            FROM evaluation_decision_facts
            WHERE strategy_decision_id = ? AND replay_run_id = ?
            """,
            (strategy_decision_id, replay_run_id),
        ).fetchone()
        if row is None:
            return None
        return self.load_decision_fact(str(row[0]))

    def iter_decision_facts(self) -> Iterator[DecisionEvaluationFact]:
        rows = self.connection.execute(
            """
            SELECT fact_id
            FROM evaluation_decision_facts
            ORDER BY timestamp_ms, fact_id
            """
        ).fetchall()
        for row in rows:
            fact = self.load_decision_fact(str(row[0]))
            if fact is None:
                raise EvaluationConsistencyError("decision fact disappeared during iteration")
            yield fact

    def load_equity_fact(self, fact_id: str) -> AccountEquityFact | None:
        row = self.connection.execute(
            "SELECT payload_json FROM evaluation_equity_facts WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            raw = json.loads(str(row[0]))
        except json.JSONDecodeError as exc:
            raise EvaluationConsistencyError("equity fact payload must be valid JSON") from exc
        if not isinstance(raw, dict):
            raise EvaluationConsistencyError("equity fact payload must be an object")
        try:
            result = AccountEquityFact(
                replay_run_id=_string(raw.get("replay_run_id"), "replay_run_id"),
                account_state_id=_string(raw.get("account_state_id"), "account_state_id"),
                timestamp_ms=_int(raw.get("timestamp_ms"), "timestamp_ms"),
                kind=EquityFactKind(_string(raw.get("kind"), "kind")),
                equity=_decimal(raw.get("equity"), "equity"),
                cash=_decimal(raw.get("cash"), "cash"),
                unrealized_pnl=_decimal(raw.get("unrealized_pnl"), "unrealized_pnl"),
                realized_gross_pnl=_decimal(
                    raw.get("realized_gross_pnl"), "realized_gross_pnl"
                ),
                cumulative_fees=_decimal(raw.get("cumulative_fees"), "cumulative_fees"),
                cumulative_funding=_decimal(
                    raw.get("cumulative_funding"), "cumulative_funding"
                ),
                gross_open_notional=_decimal(
                    raw.get("gross_open_notional"), "gross_open_notional"
                ),
                open_position_count=_int(
                    raw.get("open_position_count"), "open_position_count"
                ),
                schema_version=_int(raw.get("schema_version"), "schema_version"),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, EvaluationConsistencyError):
                raise
            raise EvaluationConsistencyError("equity fact payload is invalid") from exc
        if result.fact_id != fact_id:
            raise EvaluationConsistencyError("stored equity fact id does not match payload")
        return result

    def iter_equity_facts(
        self,
        replay_run_id: str | None = None,
    ) -> Iterator[AccountEquityFact]:
        if replay_run_id is None:
            rows = self.connection.execute(
                """
                SELECT fact_id
                FROM evaluation_equity_facts
                ORDER BY timestamp_ms, fact_id
                """
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT fact_id
                FROM evaluation_equity_facts
                WHERE replay_run_id = ?
                ORDER BY timestamp_ms, fact_id
                """,
                (replay_run_id,),
            ).fetchall()
        for row in rows:
            fact = self.load_equity_fact(str(row[0]))
            if fact is None:
                raise EvaluationConsistencyError("equity fact disappeared during iteration")
            yield fact

    def record_dataset_manifest(self, manifest: EvaluationDatasetManifest) -> None:
        payload = self._canonical_dataset_manifest(manifest)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                """
                SELECT payload_json
                FROM evaluation_dataset_manifests
                WHERE manifest_id = ?
                """,
                (manifest.manifest_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise EvaluationConsistencyError(
                        f"conflicting evaluation dataset manifest: {manifest.manifest_id}"
                    )
                self.connection.commit()
                return
            self.connection.execute(
                """
                INSERT INTO evaluation_dataset_manifests(manifest_id, payload_json)
                VALUES (?, ?)
                """,
                (manifest.manifest_id, payload),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def load_dataset_manifest(
        self,
        manifest_id: str,
    ) -> EvaluationDatasetManifest | None:
        row = self.connection.execute(
            """
            SELECT payload_json
            FROM evaluation_dataset_manifests
            WHERE manifest_id = ?
            """,
            (manifest_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            raw = json.loads(str(row[0]))
        except json.JSONDecodeError as exc:
            raise EvaluationConsistencyError(
                "evaluation dataset manifest payload must be valid JSON"
            ) from exc
        if not isinstance(raw, dict):
            raise EvaluationConsistencyError(
                "evaluation dataset manifest payload must be an object"
            )
        raw_sources = raw.get("sources")
        if not isinstance(raw_sources, list):
            raise EvaluationConsistencyError("evaluation dataset sources must be an array")
        try:
            result = EvaluationDatasetManifest(
                sources=tuple(_replay_evaluation_source(value) for value in raw_sources),
                trade_ids=_string_tuple(raw.get("trade_ids"), "trade_ids"),
                decision_fact_ids=_string_tuple(
                    raw.get("decision_fact_ids"), "decision_fact_ids"
                ),
                equity_fact_ids=_string_tuple(raw.get("equity_fact_ids"), "equity_fact_ids"),
                start_ms=_int(raw.get("start_ms"), "start_ms"),
                end_ms=_int(raw.get("end_ms"), "end_ms"),
                code_revision=_string(raw.get("code_revision"), "code_revision"),
                data_complete=_boolean(raw.get("data_complete"), "data_complete"),
                gap_refs=_string_tuple(raw.get("gap_refs"), "gap_refs"),
                mixed_evidence_diagnostic=_boolean(
                    raw.get("mixed_evidence_diagnostic"),
                    "mixed_evidence_diagnostic",
                ),
                schema_version=_int(raw.get("schema_version"), "schema_version"),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, EvaluationConsistencyError):
                raise
            raise EvaluationConsistencyError(
                "evaluation dataset manifest payload is invalid"
            ) from exc
        if result.manifest_id != manifest_id:
            raise EvaluationConsistencyError(
                "stored evaluation dataset manifest id does not match payload"
            )
        return result

    def record_evaluation_result(self, result: EvaluationResult) -> None:
        payload = self._canonical_json(evaluation_result_payload(result))
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT payload_json FROM evaluation_results WHERE evaluation_id = ?",
                (result.evaluation_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise EvaluationConsistencyError(
                        f"conflicting evaluation result: {result.evaluation_id}"
                    )
                self.connection.commit()
                return
            self.connection.execute(
                "INSERT INTO evaluation_results(evaluation_id, payload_json) VALUES (?, ?)",
                (result.evaluation_id, payload),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def load_evaluation_result(self, evaluation_id: str) -> EvaluationResult | None:
        row = self.connection.execute(
            "SELECT payload_json FROM evaluation_results WHERE evaluation_id = ?",
            (evaluation_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            raw = json.loads(str(row[0]))
            result = evaluation_result_from_payload(raw)
        except (json.JSONDecodeError, EvaluationResultCodecError, TypeError, ValueError) as exc:
            raise EvaluationConsistencyError("evaluation result payload is invalid") from exc
        if result.evaluation_id != evaluation_id:
            raise EvaluationConsistencyError(
                "stored evaluation result id does not match canonical payload"
            )
        return result

    def bind_oos_consumption(
        self,
        *,
        test_partition_digest: str,
        candidate_set_id: str,
        policy_id: str,
        evaluation_id: str,
    ) -> None:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                """
                SELECT candidate_set_id, policy_id, consumed_by_evaluation_id
                FROM evaluation_oos_consumptions
                WHERE test_partition_digest = ?
                """,
                (test_partition_digest,),
            ).fetchone()
            if row is None:
                raise EvaluationConsistencyError(
                    "cannot bind evaluation to missing OOS consumption"
                )
            if row[0] != candidate_set_id or row[1] != policy_id:
                raise EvaluationConsistencyError(
                    "cannot bind evaluation to conflicting OOS consumption"
                )
            existing_evaluation_id = row[2]
            if existing_evaluation_id is not None and existing_evaluation_id != evaluation_id:
                raise EvaluationConsistencyError(
                    "OOS consumption is already bound to a different evaluation"
                )
            if existing_evaluation_id is None:
                self.connection.execute(
                    """
                    UPDATE evaluation_oos_consumptions
                    SET consumed_by_evaluation_id = ?
                    WHERE test_partition_digest = ?
                    """,
                    (evaluation_id, test_partition_digest),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def close(self) -> None:
        self.connection.close()
