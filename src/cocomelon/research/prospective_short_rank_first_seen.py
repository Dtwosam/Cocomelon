from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.features import FeatureSnapshot, OpportunityRank
from cocomelon.domain.market import MarketId
from cocomelon.research.prospective_short_breakout_paired_entry import (
    ObservedRankWitness,
)

SCHEMA_VERSION: Final = 1


class ShortRankFirstSeenError(RuntimeError):
    pass


def _canonical_json(data: object) -> str:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )


def _digest(data: object) -> str:
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


def _integer(data: object, label: str) -> int:
    if type(data) is not int or data < 0:
        raise ShortRankFirstSeenError(f"{label} must be a nonnegative integer")
    return data


def _text(data: object, label: str) -> str:
    if not isinstance(data, str) or not data.strip():
        raise ShortRankFirstSeenError(f"{label} must be nonempty text")
    return data


def _mapping(data: object, label: str) -> dict[str, object]:
    if not isinstance(data, dict) or not all(isinstance(k, str) for k in data):
        raise ShortRankFirstSeenError(f"{label} must be an object")
    return cast(dict[str, object], data)


def _rows(data: object, label: str) -> tuple[dict[str, object], ...]:
    if not isinstance(data, list):
        raise ShortRankFirstSeenError(f"{label} must be an array")
    return tuple(_mapping(value, label) for value in data)


@dataclass(frozen=True, slots=True)
class FirstSeenRankSnapshot:
    """Immutable source-feature identity and rank list with actual capture time."""

    observed_at_ms: int
    captured_at_ms: int
    features: tuple[tuple[str, str, int], ...]
    ranks: tuple[tuple[str, int, str, tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        _integer(self.observed_at_ms, "rank observed_at_ms")
        _integer(self.captured_at_ms, "rank captured_at_ms")
        if self.captured_at_ms < self.observed_at_ms:
            raise ShortRankFirstSeenError("rank captured before its calculation")
        markets = tuple(market for market, _, _ in self.features)
        if markets != tuple(sorted(set(markets))):
            raise ShortRankFirstSeenError("feature market identity is noncanonical")
        for market, snapshot_id, received_ms in self.features:
            _text(market, "feature market")
            _text(snapshot_id, "feature snapshot")
            if _integer(received_ms, "feature received_ms") > self.observed_at_ms:
                raise ShortRankFirstSeenError(
                    "ranking used a feature received after observation start"
                )
        rank_markets = [row[0] for row in self.ranks]
        if len(set(rank_markets)) != len(rank_markets):
            raise ShortRankFirstSeenError("rank snapshot contains duplicate markets")
        if [row[1] for row in self.ranks] != list(range(1, len(self.ranks) + 1)):
            raise ShortRankFirstSeenError("rank ordinals are not contiguous")
        for market, ordinal, score, reasons in self.ranks:
            if market not in markets or type(ordinal) is not int:
                raise ShortRankFirstSeenError("rank lacks verified feature identity")
            if not isinstance(score, str):
                raise ShortRankFirstSeenError("rank score must be decimal text")
            try:
                number = Decimal(score)
            except InvalidOperation as exc:
                raise ShortRankFirstSeenError("rank score is invalid") from exc
            if not number.is_finite() or not Decimal("0") <= number <= Decimal("1"):
                raise ShortRankFirstSeenError("rank score is out of range")
            if not isinstance(reasons, tuple) or not all(
                isinstance(reason, str) and bool(reason.strip())
                for reason in reasons
            ) or tuple(dict.fromkeys(reasons)) != reasons:
                raise ShortRankFirstSeenError("rank reasons are noncanonical")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "observed_at_ms": self.observed_at_ms,
            "captured_at_ms": self.captured_at_ms,
            "features": [
                {"market": market, "snapshot_id": snapshot_id, "received_at_ms": received}
                for market, snapshot_id, received in self.features
            ],
            "ranks": [
                {
                    "market": market,
                    "ordinal": ordinal,
                    "score": score,
                    "reason_codes": list(reasons),
                }
                for market, ordinal, score, reasons in self.ranks
            ],
        }

    @property
    def snapshot_digest(self) -> str:
        return _digest(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "snapshot_digest": self.snapshot_digest}

    @classmethod
    def from_dict(cls, data: object) -> FirstSeenRankSnapshot:
        row = _mapping(data, "rank snapshot")
        if set(row) != {
            "schema_version", "observed_at_ms", "captured_at_ms",
            "features", "ranks", "snapshot_digest",
        } or row["schema_version"] != SCHEMA_VERSION:
            raise ShortRankFirstSeenError("rank snapshot schema drift")
        features = _rows(row["features"], "features")
        ranks = _rows(row["ranks"], "ranks")
        for feature in features:
            if set(feature) != {"market", "snapshot_id", "received_at_ms"}:
                raise ShortRankFirstSeenError("ranking feature schema drift")
        for rank in ranks:
            if set(rank) != {"market", "ordinal", "score", "reason_codes"}:
                raise ShortRankFirstSeenError("ranking row schema drift")
        parsed_ranks: list[tuple[str, int, str, tuple[str, ...]]] = []
        for rank in ranks:
            reasons = rank["reason_codes"]
            if not isinstance(reasons, list) or not all(
                isinstance(reason, str) for reason in reasons
            ):
                raise ShortRankFirstSeenError("rank reason fields are invalid")
            parsed_ranks.append((
                _text(rank["market"], "rank market"),
                _integer(rank["ordinal"], "rank ordinal"),
                _text(rank["score"], "rank score"),
                tuple(reasons),
            ))
        result = cls(
            observed_at_ms=_integer(row["observed_at_ms"], "observed_at_ms"),
            captured_at_ms=_integer(row["captured_at_ms"], "captured_at_ms"),
            features=tuple(
                (
                    _text(feature["market"], "feature market"),
                    _text(feature["snapshot_id"], "feature id"),
                    _integer(feature["received_at_ms"], "feature received_ms"),
                )
                for feature in features
            ),
            ranks=tuple(parsed_ranks),
        )
        if row["snapshot_digest"] != result.snapshot_digest:
            raise ShortRankFirstSeenError("rank snapshot digest mismatch")
        return result

    @classmethod
    def from_observation(
        cls,
        *,
        observed_at_ms: int,
        captured_at_ms: int,
        features: Mapping[str, FeatureSnapshot],
        ranks: Sequence[OpportunityRank],
    ) -> FirstSeenRankSnapshot:
        source = tuple(
            (
                key,
                value.snapshot_id,
                value.source_received_at_ms,
            )
            for key, value in sorted(features.items())
        )
        if any(key != feat.market.canonical for key, feat in features.items()):
            raise ShortRankFirstSeenError(
                "rank source feature keys do not match market"
            )
        if any(feat.as_of_ms > observed_at_ms for feat in features.values()):
            raise ShortRankFirstSeenError(
                "rank source feature as-of is future dated"
            )
        return cls(
            observed_at_ms=observed_at_ms,
            captured_at_ms=captured_at_ms,
            features=source,
            ranks=tuple(
                (
                    rank.market.canonical,
                    rank.ordinal,
                    str(rank.score),
                    rank.reason_codes,
                ) for rank in ranks
            ),
        )


class FirstSeenRankSnapshotStore:
    """Append-only prospective snapshots, including empty rank universes.

    The actual persistence completion time, NOT the earlier start of ranking
    computation, is the first usable evidence timestamp. Old sealed files
    must never be rewritten to manufacture a pre-decision winning filter.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.records = self.root / "snapshots"
        self.records.mkdir(parents=True, exist_ok=True)

    def iter_records(self) -> tuple[FirstSeenRankSnapshot, ...]:
        result: list[FirstSeenRankSnapshot] = []
        previous_ms = -1
        previous_capture = -1
        for path in sorted(self.records.glob("*.json")):
            try:
                raw = path.read_bytes()
                parsed = FirstSeenRankSnapshot.from_dict(json.loads(raw))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ShortRankFirstSeenError(
                    "first-seen rank snapshot is unreadable or invalid"
                ) from exc
            if (
                path.name != f"{parsed.observed_at_ms:016d}.json"
                or raw != (_canonical_json(parsed.to_dict()) + "\n").encode("utf-8")
                or parsed.observed_at_ms <= previous_ms
                or parsed.captured_at_ms < previous_capture
            ):
                raise ShortRankFirstSeenError(
                    "first-seen rank archive ordering or canonical file drift"
                )
            result.append(parsed)
            previous_ms = parsed.observed_at_ms
            previous_capture = parsed.captured_at_ms
        return tuple(result)

    def append(self, snapshot: FirstSeenRankSnapshot) -> bool:
        existing = self.iter_records()
        path = self.records / f"{snapshot.observed_at_ms:016d}.json"
        encoded = (_canonical_json(snapshot.to_dict()) + "\n").encode("utf-8")
        if path.exists():
            if path.read_bytes() != encoded:
                raise ShortRankFirstSeenError(
                    "FIRST_SEEN_RANK_SNAPSHOT_CONFLICT"
                )
            return False
        if existing and (
            snapshot.observed_at_ms <= existing[-1].observed_at_ms
            or snapshot.captured_at_ms < existing[-1].captured_at_ms
        ):
            raise ShortRankFirstSeenError(
                "first-seen rank snapshot backdated across handoff"
            )
        temp = path.with_name(f".{path.name}.tmp")
        try:
            with temp.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temp, path)
            except FileExistsError:
                if path.read_bytes() != encoded:
                    raise ShortRankFirstSeenError(
                        "FIRST_SEEN_RANK_SNAPSHOT_CONFLICT"
                    ) from None
                return False
        finally:
            if temp.exists():
                temp.unlink()
        return True

    def witness_for_decision(
        self, market: MarketId, decision_ms: int,
    ) -> ObservedRankWitness | None:
        _integer(decision_ms, "rank decision timestamp")
        for snapshot in reversed(self.iter_records()):
            if snapshot.captured_at_ms < decision_ms:
                for key, ordinal, _score, _reasons in snapshot.ranks:
                    if key == market.canonical:
                        return ObservedRankWitness(
                            ordinal=ordinal,
                            observed_at_ms=snapshot.captured_at_ms,
                        )
                return None
        return None

    @property
    def state_digest(self) -> str:
        return _digest([record.snapshot_digest for record in self.iter_records()])
