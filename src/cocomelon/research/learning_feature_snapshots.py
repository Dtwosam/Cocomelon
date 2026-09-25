from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId

FEATURE_SNAPSHOT_STORE_SCHEMA_VERSION = 1


class LearningFeatureSnapshotError(RuntimeError):
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
        raise LearningFeatureSnapshotError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningFeatureSnapshotError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningFeatureSnapshotError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LearningFeatureSnapshotError(f"{field} must be a decimal string")
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise LearningFeatureSnapshotError(f"{field} must be a decimal string") from exc
    if not resolved.is_finite():
        raise LearningFeatureSnapshotError(f"{field} must be finite")
    return resolved


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field)


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LearningFeatureSnapshotError(f"{field} must be a string array")
    return tuple(value)


def _market_from_canonical(value: str) -> MarketId:
    if ":" not in value:
        return MarketId("", value)
    dex, coin = value.split(":", 1)
    if not dex or not coin or ":" in coin:
        raise LearningFeatureSnapshotError("feature snapshot market is invalid")
    return MarketId(dex, coin)


def feature_snapshot_payload(snapshot: FeatureSnapshot) -> dict[str, object]:
    return {
        "market": snapshot.market.canonical,
        "as_of_ms": snapshot.as_of_ms,
        "source_received_at_ms": snapshot.source_received_at_ms,
        "schema_version": snapshot.schema_version,
        "day_return": None if snapshot.day_return is None else str(snapshot.day_return),
        "funding": str(snapshot.funding),
        "open_interest": str(snapshot.open_interest),
        "day_notional_volume": str(snapshot.day_notional_volume),
        "oi_change_fraction": (
            None
            if snapshot.oi_change_fraction is None
            else str(snapshot.oi_change_fraction)
        ),
        "funding_change": (
            None if snapshot.funding_change is None else str(snapshot.funding_change)
        ),
        "mark_oracle_dislocation_bps": (
            None
            if snapshot.mark_oracle_dislocation_bps is None
            else str(snapshot.mark_oracle_dislocation_bps)
        ),
        "return_5m": None if snapshot.return_5m is None else str(snapshot.return_5m),
        "return_15m": None if snapshot.return_15m is None else str(snapshot.return_15m),
        "return_1h": None if snapshot.return_1h is None else str(snapshot.return_1h),
        "return_4h": None if snapshot.return_4h is None else str(snapshot.return_4h),
        "realized_vol_15m": (
            None
            if snapshot.realized_vol_15m is None
            else str(snapshot.realized_vol_15m)
        ),
        "range_expansion_15m": (
            None
            if snapshot.range_expansion_15m is None
            else str(snapshot.range_expansion_15m)
        ),
        "relative_volume_15m": (
            None
            if snapshot.relative_volume_15m is None
            else str(snapshot.relative_volume_15m)
        ),
        "spread_bps": None if snapshot.spread_bps is None else str(snapshot.spread_bps),
        "bid_depth_25bps": (
            None if snapshot.bid_depth_25bps is None else str(snapshot.bid_depth_25bps)
        ),
        "ask_depth_25bps": (
            None if snapshot.ask_depth_25bps is None else str(snapshot.ask_depth_25bps)
        ),
        "book_imbalance": (
            None if snapshot.book_imbalance is None else str(snapshot.book_imbalance)
        ),
        "book_age_ms": snapshot.book_age_ms,
        "trend_regime": snapshot.trend_regime.value,
        "volatility_regime": snapshot.volatility_regime.value,
        "provenance": snapshot.provenance,
    }


def _snapshot_from_payload(raw: dict[str, object]) -> FeatureSnapshot:
    try:
        return FeatureSnapshot(
            market=_market_from_canonical(_string(raw.get("market"), "market")),
            as_of_ms=_integer(raw.get("as_of_ms"), "as_of_ms"),
            source_received_at_ms=_integer(
                raw.get("source_received_at_ms"),
                "source_received_at_ms",
            ),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
            day_return=_optional_decimal(raw.get("day_return"), "day_return"),
            funding=_decimal(raw.get("funding"), "funding"),
            open_interest=_decimal(raw.get("open_interest"), "open_interest"),
            day_notional_volume=_decimal(
                raw.get("day_notional_volume"),
                "day_notional_volume",
            ),
            oi_change_fraction=_optional_decimal(
                raw.get("oi_change_fraction"),
                "oi_change_fraction",
            ),
            funding_change=_optional_decimal(
                raw.get("funding_change"),
                "funding_change",
            ),
            mark_oracle_dislocation_bps=_optional_decimal(
                raw.get("mark_oracle_dislocation_bps"),
                "mark_oracle_dislocation_bps",
            ),
            return_5m=_optional_decimal(raw.get("return_5m"), "return_5m"),
            return_15m=_optional_decimal(raw.get("return_15m"), "return_15m"),
            return_1h=_optional_decimal(raw.get("return_1h"), "return_1h"),
            return_4h=_optional_decimal(raw.get("return_4h"), "return_4h"),
            realized_vol_15m=_optional_decimal(
                raw.get("realized_vol_15m"),
                "realized_vol_15m",
            ),
            range_expansion_15m=_optional_decimal(
                raw.get("range_expansion_15m"),
                "range_expansion_15m",
            ),
            relative_volume_15m=_optional_decimal(
                raw.get("relative_volume_15m"),
                "relative_volume_15m",
            ),
            spread_bps=_optional_decimal(raw.get("spread_bps"), "spread_bps"),
            bid_depth_25bps=_optional_decimal(
                raw.get("bid_depth_25bps"),
                "bid_depth_25bps",
            ),
            ask_depth_25bps=_optional_decimal(
                raw.get("ask_depth_25bps"),
                "ask_depth_25bps",
            ),
            book_imbalance=_optional_decimal(
                raw.get("book_imbalance"),
                "book_imbalance",
            ),
            book_age_ms=_optional_integer(raw.get("book_age_ms"), "book_age_ms"),
            trend_regime=TrendRegime(
                _string(raw.get("trend_regime"), "trend_regime")
            ),
            volatility_regime=VolatilityRegime(
                _string(raw.get("volatility_regime"), "volatility_regime")
            ),
            provenance=_strings(raw.get("provenance"), "provenance"),
        )
    except ValueError as exc:
        raise LearningFeatureSnapshotError(
            "LEARNING_FEATURE_SNAPSHOT_INVALID"
        ) from exc


@dataclass(frozen=True, slots=True)
class VerifiedLearningFeatureSnapshot:
    snapshot: FeatureSnapshot
    record_sha256: str

    def __post_init__(self) -> None:
        if len(self.record_sha256) != 64:
            raise ValueError("record_sha256 must be a SHA-256 identity")


class LearningFeatureSnapshotStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.records_root = self.root / "records"
        self.records_root.mkdir(parents=True, exist_ok=True)

    def _path(self, snapshot_id: str) -> Path:
        if (
            len(snapshot_id) != 24
            or any(char not in "0123456789abcdef" for char in snapshot_id)
        ):
            raise LearningFeatureSnapshotError(
                "feature snapshot id must be lowercase 24-character hex"
            )
        return self.records_root / f"{snapshot_id}.json"

    @staticmethod
    def _record_payload(snapshot: FeatureSnapshot) -> dict[str, object]:
        return {
            "store_schema_version": FEATURE_SNAPSHOT_STORE_SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "feature": feature_snapshot_payload(snapshot),
        }

    def record(self, snapshot: FeatureSnapshot) -> bool:
        path = self._path(snapshot.snapshot_id)
        encoded = (
            _canonical_json(self._record_payload(snapshot)) + "\n"
        ).encode("utf-8")
        if path.exists():
            if path.read_bytes() != encoded:
                raise LearningFeatureSnapshotError(
                    f"conflicting feature snapshot: {snapshot.snapshot_id}"
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
                    raise LearningFeatureSnapshotError(
                        f"conflicting feature snapshot: {snapshot.snapshot_id}"
                    ) from None
                return False
        finally:
            if temporary.exists():
                temporary.unlink()
        return True

    def load(self, snapshot_id: str) -> VerifiedLearningFeatureSnapshot | None:
        path = self._path(snapshot_id)
        if not path.exists():
            return None
        try:
            encoded = path.read_bytes()
            raw = _mapping(
                json.loads(encoded),
                "learning feature snapshot record",
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise LearningFeatureSnapshotError(
                "LEARNING_FEATURE_SNAPSHOT_RECORD_INVALID"
            ) from exc

        if (
            _integer(
                raw.get("store_schema_version"),
                "store_schema_version",
            )
            != FEATURE_SNAPSHOT_STORE_SCHEMA_VERSION
        ):
            raise LearningFeatureSnapshotError(
                "LEARNING_FEATURE_SNAPSHOT_SCHEMA_UNSUPPORTED"
            )
        feature = _mapping(raw.get("feature"), "feature")
        snapshot = _snapshot_from_payload(feature)
        if raw.get("snapshot_id") != snapshot.snapshot_id:
            raise LearningFeatureSnapshotError(
                "LEARNING_FEATURE_SNAPSHOT_ID_MISMATCH"
            )
        expected = self._record_payload(snapshot)
        if _canonical_json(raw) != _canonical_json(expected):
            raise LearningFeatureSnapshotError(
                "LEARNING_FEATURE_SNAPSHOT_RECORD_IDENTITY_MISMATCH"
            )
        canonical = (_canonical_json(expected) + "\n").encode("utf-8")
        if encoded != canonical:
            raise LearningFeatureSnapshotError(
                "LEARNING_FEATURE_SNAPSHOT_RECORD_NON_CANONICAL"
            )
        return VerifiedLearningFeatureSnapshot(
            snapshot=snapshot,
            record_sha256=_sha256_bytes(encoded),
        )

    def iter_verified(self) -> tuple[VerifiedLearningFeatureSnapshot, ...]:
        records: list[VerifiedLearningFeatureSnapshot] = []
        for path in sorted(self.records_root.glob("*.json")):
            verified = self.load(path.stem)
            if verified is None:
                raise LearningFeatureSnapshotError(
                    "feature snapshot disappeared during iteration"
                )
            records.append(verified)
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.snapshot.as_of_ms,
                    item.snapshot.market.canonical,
                    item.snapshot.snapshot_id,
                ),
            )
        )

    @property
    def state_digest(self) -> str:
        payload = tuple(
            {
                "snapshot_id": item.snapshot.snapshot_id,
                "record_sha256": item.record_sha256,
            }
            for item in self.iter_verified()
        )
        return _sha256_bytes(_canonical_json(payload).encode("utf-8"))
