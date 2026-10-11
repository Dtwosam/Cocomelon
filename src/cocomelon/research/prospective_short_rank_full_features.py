"""Durable first-seen exact ranking INPUT feature payloads, not sampled decisions.

One canonical append-only batch per prospective original coarse ranking refresh.
The source's earlier ID-only rank ledger stays unchanged. The feature store is
research-only: failure must not affect trader orders, positions or risk.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.features import FeatureSnapshot
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotError,
    _snapshot_from_payload,
    feature_snapshot_payload,
)
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
)

BATCH_SCHEMA_VERSION: Final = 1


class OriginalRankInputBatchError(RuntimeError):
    pass


def _bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ) + "\n"
    ).encode("utf-8")


def _obj(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(
        not isinstance(k, str) for k in value
    ):
        raise OriginalRankInputBatchError("original rank feature batch is malformed")
    return cast(dict[str, object], value)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class OriginalRankFeatureInputBatch:
    observed_at_ms: int
    captured_at_ms: int
    rank_snapshot_digest: str
    features: tuple[FeatureSnapshot, ...]

    def __post_init__(self) -> None:
        if (
            type(self.observed_at_ms) is not int or self.observed_at_ms < 0
            or type(self.captured_at_ms) is not int
            or self.captured_at_ms < self.observed_at_ms
            or len(self.rank_snapshot_digest) != 64
            or any(c not in "0123456789abcdef" for c in self.rank_snapshot_digest)
        ):
            raise OriginalRankInputBatchError(
                "rank input observation or parent digest invalid"
            )
        markets = [feature.market.canonical for feature in self.features]
        if markets != sorted(set(markets)):
            raise OriginalRankInputBatchError("rank input markets noncanonical")
        for feature in self.features:
            if (
                feature.as_of_ms > self.observed_at_ms
                or feature.source_received_at_ms > self.observed_at_ms
            ):
                raise OriginalRankInputBatchError(
                    "ranking feature was not known at observation start"
                )

    def bind_to(self, rank: FirstSeenRankSnapshot) -> None:
        if (
            self.observed_at_ms != rank.observed_at_ms
            or self.captured_at_ms != rank.captured_at_ms
            or self.rank_snapshot_digest != rank.snapshot_digest
            or tuple(
                (
                    feat.market.canonical,
                    feat.snapshot_id,
                    feat.source_received_at_ms,
                )
                for feat in self.features
            ) != rank.features
        ):
            raise OriginalRankInputBatchError(
                "original full feature inputs disagree with rank snapshot"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": BATCH_SCHEMA_VERSION,
            "observed_at_ms": self.observed_at_ms,
            "captured_at_ms": self.captured_at_ms,
            "rank_snapshot_digest": self.rank_snapshot_digest,
            "features": [
                {
                    "market": feat.market.canonical,
                    "snapshot_id": feat.snapshot_id,
                    "source_received_at_ms": feat.source_received_at_ms,
                    "feature": feature_snapshot_payload(feat),
                }
                for feat in self.features
            ],
        }

    @property
    def batch_sha256(self) -> str:
        return _digest(_bytes(self.identity_payload()))

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "batch_sha256": self.batch_sha256,
        }

    @classmethod
    def from_dict(cls, raw: object) -> OriginalRankFeatureInputBatch:
        value = _obj(raw)
        if (
            set(value) != {
                "schema_version", "observed_at_ms", "captured_at_ms",
                "rank_snapshot_digest", "features", "batch_sha256",
            }
            or value["schema_version"] != BATCH_SCHEMA_VERSION
            or not isinstance(value["features"], list)
        ):
            raise OriginalRankInputBatchError(
                "original ranking input schema changed or is incomplete"
            )
        parsed: list[FeatureSnapshot] = []
        for item in value["features"]:
            row = _obj(item)
            if set(row) != {
                "market", "snapshot_id", "source_received_at_ms", "feature",
            }:
                raise OriginalRankInputBatchError("rank input feature schema drift")
            try:
                feature = _snapshot_from_payload(_obj(row["feature"]))
            except (ValueError, TypeError, LearningFeatureSnapshotError) as exc:
                raise OriginalRankInputBatchError(
                    "original rank source feature cannot be reconstructed"
                ) from exc
            if (
                row["market"] != feature.market.canonical
                or row["snapshot_id"] != feature.snapshot_id
                or row["source_received_at_ms"] != feature.source_received_at_ms
            ):
                raise OriginalRankInputBatchError(
                    "original rank source feature content ID mismatch"
                )
            parsed.append(feature)
        observed = value["observed_at_ms"]
        captured = value["captured_at_ms"]
        parent = value["rank_snapshot_digest"]
        if (
            type(observed) is not int or type(captured) is not int
            or not isinstance(parent, str)
        ):
            raise OriginalRankInputBatchError("original input header malformed")
        result = cls(
            observed_at_ms=observed, captured_at_ms=captured,
            rank_snapshot_digest=parent, features=tuple(parsed),
        )
        if result.to_dict() != value:
            raise OriginalRankInputBatchError(
                "original rank batch digest or content changed"
            )
        return result

    @classmethod
    def from_original_rank(
        cls, rank: FirstSeenRankSnapshot,
        features: dict[str, FeatureSnapshot],
    ) -> OriginalRankFeatureInputBatch:
        if any(
            key != feat.market.canonical for key, feat in features.items()
        ):
            raise OriginalRankInputBatchError(
                "source feature dictionary has inconsistent market keys"
            )
        batch = cls(
            observed_at_ms=rank.observed_at_ms,
            captured_at_ms=rank.captured_at_ms,
            rank_snapshot_digest=rank.snapshot_digest,
            features=tuple(features[key] for key in sorted(features)),
        )
        batch.bind_to(rank)
        return batch


class OriginalRankFeatureInputBatchStore:
    """Append one durable source batch per rank refresh, without old backfill."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.records = self.root / "batches"
        if self.root.is_symlink() or self.records.is_symlink():
            raise OriginalRankInputBatchError(
                "original rank feature archive is a symlink"
            )
        self.records.mkdir(parents=True, exist_ok=True)
        previous = self.iter_verified()
        self._last = previous[-1] if previous else None

    def iter_verified(self) -> tuple[OriginalRankFeatureInputBatch, ...]:
        if self.records.is_symlink():
            raise OriginalRankInputBatchError(
                "rank input batch archive is a symlink"
            )
        batches: list[OriginalRankFeatureInputBatch] = []
        previous_observed = -1
        previous_capture = -1
        for path in sorted(self.records.iterdir()):
            if (
                path.is_symlink() or not path.is_file()
                or len(path.name) != 21
                or path.name[16:] != ".json"
                or not path.name[:16].isascii()
                or not path.name[:16].isdigit()
            ):
                raise OriginalRankInputBatchError(
                    "rank input archive contains an unexpected file"
                )
            try:
                raw = path.read_bytes()
                batch = OriginalRankFeatureInputBatch.from_dict(json.loads(raw))
            except (OSError, ValueError, TypeError) as exc:
                raise OriginalRankInputBatchError(
                    "rank feature input batch is unreadable or changed"
                ) from exc
            if (
                path.name != f"{batch.observed_at_ms:016d}.json"
                or raw != _bytes(batch.to_dict())
                or batch.observed_at_ms <= previous_observed
                or batch.captured_at_ms < previous_capture
            ):
                raise OriginalRankInputBatchError(
                    "rank feature batch source ordering/byte drift"
                )
            batches.append(batch)
            previous_observed = batch.observed_at_ms
            previous_capture = batch.captured_at_ms
        return tuple(batches)

    def append(self, batch: OriginalRankFeatureInputBatch) -> bool:
        path = self.records / f"{batch.observed_at_ms:016d}.json"
        payload = _bytes(batch.to_dict())
        if path.is_symlink():
            raise OriginalRankInputBatchError(
                "rank input target file is a symlink"
            )
        if path.exists():
            if path.read_bytes() != payload:
                raise OriginalRankInputBatchError(
                    "historical rank input batch conflicts with original source"
                )
            return False
        if self._last is not None and (
            batch.observed_at_ms <= self._last.observed_at_ms
            or batch.captured_at_ms < self._last.captured_at_ms
        ):
            raise OriginalRankInputBatchError(
                "rank input archive backdated across original paper worker"
            )
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            with temporary.open("xb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != payload:
                    raise OriginalRankInputBatchError(
                        "concurrent rank source archive mismatch"
                    ) from None
                return False
        finally:
            if temporary.exists():
                temporary.unlink()
        self._last = batch
        return True

    @property
    def source_digest(self) -> str:
        return _digest(_bytes([
            {
                "observed_at_ms": item.observed_at_ms,
                "rank_snapshot_digest": item.rank_snapshot_digest,
                "batch_sha256": item.batch_sha256,
            }
            for item in self.iter_verified()
        ]))
