from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction

DECISION_FACT_STORE_SCHEMA_VERSION = 1


class ContinuousPaperDecisionFactError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContinuousPaperDecisionFactError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContinuousPaperDecisionFactError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContinuousPaperDecisionFactError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ContinuousPaperDecisionFactError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ContinuousPaperDecisionFactError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise ContinuousPaperDecisionFactError(f"{field} must be finite")
    return result


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ContinuousPaperDecisionFactError(f"{field} must be a string array")
    return tuple(value)


def _market_from_canonical(value: str) -> MarketId:
    if ":" not in value:
        return MarketId("", value)
    dex, coin = value.split(":", 1)
    if not dex or not coin or ":" in coin:
        raise ContinuousPaperDecisionFactError("decision fact market is invalid")
    return MarketId(dex, coin)


def decision_fact_payload(fact: DecisionEvaluationFact) -> dict[str, object]:
    return {
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


def _fact_from_payload(raw: dict[str, object]) -> DecisionEvaluationFact:
    try:
        return DecisionEvaluationFact(
            strategy_decision_id=_string(
                raw.get("strategy_decision_id"),
                "strategy_decision_id",
            ),
            feature_snapshot_id=_string(
                raw.get("feature_snapshot_id"),
                "feature_snapshot_id",
            ),
            replay_run_id=_string(raw.get("replay_run_id"), "replay_run_id"),
            market=_market_from_canonical(_string(raw.get("market"), "market")),
            direction=Direction(_string(raw.get("direction"), "direction")),
            timestamp_ms=_integer(raw.get("timestamp_ms"), "timestamp_ms"),
            score=_decimal(raw.get("score"), "score"),
            lead_strategy=_optional_string(
                raw.get("lead_strategy"),
                "lead_strategy",
            ),
            signal_ids=_strings(raw.get("signal_ids"), "signal_ids"),
            reason_codes=_strings(raw.get("reason_codes"), "reason_codes"),
            trend_regime=TrendRegime(
                _string(raw.get("trend_regime"), "trend_regime")
            ),
            volatility_regime=VolatilityRegime(
                _string(raw.get("volatility_regime"), "volatility_regime")
            ),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except ValueError as exc:
        raise ContinuousPaperDecisionFactError(
            "CONTINUOUS_PAPER_DECISION_FACT_INVALID"
        ) from exc


@dataclass(frozen=True, slots=True)
class VerifiedContinuousPaperDecisionFact:
    fact: DecisionEvaluationFact
    record_sha256: str

    def __post_init__(self) -> None:
        if len(self.record_sha256) != 64:
            raise ValueError("record_sha256 must be a SHA-256 identity")


class ContinuousPaperDecisionFactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.records_root = self.root / "records"
        self.records_root.mkdir(parents=True, exist_ok=True)

    def _path(self, fact_id: str) -> Path:
        if (
            len(fact_id) != 24
            or any(char not in "0123456789abcdef" for char in fact_id)
        ):
            raise ContinuousPaperDecisionFactError(
                "decision fact id must be lowercase 24-character hex"
            )
        return self.records_root / f"{fact_id}.json"

    @staticmethod
    def _record_payload(fact: DecisionEvaluationFact) -> dict[str, object]:
        return {
            "store_schema_version": DECISION_FACT_STORE_SCHEMA_VERSION,
            "fact_id": fact.fact_id,
            "fact": decision_fact_payload(fact),
        }

    def record(self, fact: DecisionEvaluationFact) -> bool:
        path = self._path(fact.fact_id)
        encoded = (_canonical_json(self._record_payload(fact)) + "\n").encode(
            "utf-8"
        )
        if path.exists():
            if path.read_bytes() != encoded:
                raise ContinuousPaperDecisionFactError(
                    f"conflicting decision fact: {fact.fact_id}"
                )
            return False
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != encoded:
                    raise ContinuousPaperDecisionFactError(
                        f"conflicting decision fact: {fact.fact_id}"
                    ) from None
                return False
        finally:
            if temporary.exists():
                temporary.unlink()
        return True

    def load(
        self,
        fact_id: str,
    ) -> VerifiedContinuousPaperDecisionFact | None:
        path = self._path(fact_id)
        if not path.exists():
            return None
        try:
            encoded = path.read_bytes()
            raw = _mapping(
                json.loads(encoded),
                "continuous paper decision fact record",
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ContinuousPaperDecisionFactError(
                "CONTINUOUS_PAPER_DECISION_FACT_RECORD_INVALID"
            ) from exc

        if (
            _integer(
                raw.get("store_schema_version"),
                "store_schema_version",
            )
            != DECISION_FACT_STORE_SCHEMA_VERSION
        ):
            raise ContinuousPaperDecisionFactError(
                "CONTINUOUS_PAPER_DECISION_FACT_SCHEMA_UNSUPPORTED"
            )
        fact = _fact_from_payload(_mapping(raw.get("fact"), "fact"))
        if raw.get("fact_id") != fact.fact_id:
            raise ContinuousPaperDecisionFactError(
                "CONTINUOUS_PAPER_DECISION_FACT_ID_MISMATCH"
            )
        expected = self._record_payload(fact)
        if _canonical_json(raw) != _canonical_json(expected):
            raise ContinuousPaperDecisionFactError(
                "CONTINUOUS_PAPER_DECISION_FACT_IDENTITY_MISMATCH"
            )
        canonical = (_canonical_json(expected) + "\n").encode("utf-8")
        if encoded != canonical:
            raise ContinuousPaperDecisionFactError(
                "CONTINUOUS_PAPER_DECISION_FACT_NON_CANONICAL"
            )
        return VerifiedContinuousPaperDecisionFact(
            fact=fact,
            record_sha256=_sha256_bytes(encoded),
        )

    def iter_verified(
        self,
    ) -> tuple[VerifiedContinuousPaperDecisionFact, ...]:
        records: list[VerifiedContinuousPaperDecisionFact] = []
        for path in sorted(self.records_root.glob("*.json")):
            verified = self.load(path.stem)
            if verified is None:
                raise ContinuousPaperDecisionFactError(
                    "decision fact disappeared during iteration"
                )
            records.append(verified)
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.fact.timestamp_ms,
                    item.fact.market.canonical,
                    item.fact.fact_id,
                ),
            )
        )

    @property
    def state_digest(self) -> str:
        payload = tuple(
            {
                "fact_id": item.fact.fact_id,
                "record_sha256": item.record_sha256,
            }
            for item in self.iter_verified()
        )
        return _sha256_bytes(_canonical_json(payload).encode("utf-8"))
