"""Prospective, original decision-time context for coarse-rank eligibility.

The old rank/full-feature history has no independently replayable market meta,
prices, or context age. Capture a new, immutable, source-linked suffix only.
These are original producer observations, NOT authenticated exchange data,
and never grant trading or promotion authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, cast

from cocomelon.domain.market import (
    MarketId, PerpMarketContext, PerpMarketMeta, PerpMarketSnapshot,
)
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
)
from cocomelon.research.prospective_short_rank_full_features import (
    OriginalRankFeatureInputBatch,
)
from cocomelon.scanner.eligibility import (
    EligibilityConfig, derive_eligibility_thresholds, evaluate_eligibility,
)


class OriginalRankEligibilityContextError(RuntimeError):
    """The exact recorded original eligibility inputs are missing or changed."""


def _canonical(data: object) -> bytes:
    return (json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ) + "\n").encode("utf-8")


def _hash(data: object) -> str:
    return hashlib.sha256(_canonical(data)).hexdigest()


def _obj(data: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(data, dict) or set(data) != fields:
        raise OriginalRankEligibilityContextError("original rank context schema drift")
    return cast(dict[str, object], data)


def _decimal(value: object, *, nullable: bool = False) -> Decimal | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise OriginalRankEligibilityContextError("rank context decimal not text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise OriginalRankEligibilityContextError("rank context decimal invalid") from exc
    if not parsed.is_finite():
        raise OriginalRankEligibilityContextError("rank context decimal nonfinite")
    return parsed


def _snapshot_payload(snapshot: PerpMarketSnapshot) -> dict[str, object]:
    meta, ctx = snapshot.meta, snapshot.context
    return {
        "market": meta.market.canonical,
        "source": snapshot.source,
        "received_at_ms": snapshot.received_at_ms,
        "schema_version": snapshot.schema_version,
        "meta": {
            "wire_name": meta.wire_name,
            "sz_decimals": meta.sz_decimals,
            "max_leverage": meta.max_leverage,
            "margin_table_id": meta.margin_table_id,
            "only_isolated": meta.only_isolated,
            "is_delisted": meta.is_delisted,
            "margin_mode": meta.margin_mode,
        },
        "context": {
            "mark_px": None if ctx.mark_px is None else str(ctx.mark_px),
            "mid_px": None if ctx.mid_px is None else str(ctx.mid_px),
            "oracle_px": None if ctx.oracle_px is None else str(ctx.oracle_px),
            "funding": str(ctx.funding),
            "open_interest": str(ctx.open_interest),
            "day_ntl_vlm": str(ctx.day_ntl_vlm),
            "premium": None if ctx.premium is None else str(ctx.premium),
            "prev_day_px": str(ctx.prev_day_px),
        },
    }


def _snapshot_from_payload(raw: object) -> PerpMarketSnapshot:
    row = _obj(raw, {
        "market", "source", "received_at_ms", "schema_version",
        "meta", "context",
    })
    meta = _obj(row["meta"], {
        "wire_name", "sz_decimals", "max_leverage", "margin_table_id",
        "only_isolated", "is_delisted", "margin_mode",
    })
    ctx = _obj(row["context"], {
        "mark_px", "mid_px", "oracle_px", "funding", "open_interest",
        "day_ntl_vlm", "premium", "prev_day_px",
    })
    name = row["market"]
    if not isinstance(name, str) or not name or name.count(":") > 1:
        raise OriginalRankEligibilityContextError("rank context market invalid")
    dex = name.partition(":")[0] if ":" in name else ""
    market = MarketId.from_wire_name(dex, name)
    for key in ("sz_decimals", "max_leverage"):
        if type(meta[key]) is not int:
            raise OriginalRankEligibilityContextError("rank market metadata integer invalid")
    if (
        type(row["received_at_ms"]) is not int
        or type(row["schema_version"]) is not int
        or type(meta["only_isolated"]) is not bool
        or type(meta["is_delisted"]) is not bool
        or (
            meta["margin_table_id"] is not None
            and type(meta["margin_table_id"]) is not int
        )
        or not isinstance(meta["wire_name"], str)
        or (
            meta["margin_mode"] is not None
            and not isinstance(meta["margin_mode"], str)
        )
        or not isinstance(row["source"], str)
    ):
        raise OriginalRankEligibilityContextError("rank context metadata malformed")
    snapshot = PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market,
            wire_name=cast(str, meta["wire_name"]),
            sz_decimals=cast(int, meta["sz_decimals"]),
            max_leverage=cast(int, meta["max_leverage"]),
            margin_table_id=cast(int | None, meta["margin_table_id"]),
            only_isolated=cast(bool, meta["only_isolated"]),
            is_delisted=cast(bool, meta["is_delisted"]),
            margin_mode=cast(str | None, meta["margin_mode"]),
        ),
        context=PerpMarketContext(
            market=market,
            mark_px=_decimal(ctx["mark_px"], nullable=True),
            mid_px=_decimal(ctx["mid_px"], nullable=True),
            oracle_px=_decimal(ctx["oracle_px"], nullable=True),
            funding=cast(Decimal, _decimal(ctx["funding"])),
            open_interest=cast(Decimal, _decimal(ctx["open_interest"])),
            day_ntl_vlm=cast(Decimal, _decimal(ctx["day_ntl_vlm"])),
            premium=_decimal(ctx["premium"], nullable=True),
            prev_day_px=cast(Decimal, _decimal(ctx["prev_day_px"])),
        ),
        source=cast(str, row["source"]),
        received_at_ms=cast(int, row["received_at_ms"]),
        schema_version=cast(int, row["schema_version"]),
    )
    if _snapshot_payload(snapshot) != row:
        raise OriginalRankEligibilityContextError("rank context payload not canonical")
    return snapshot


@dataclass(frozen=True, slots=True)
class OriginalRankEligibilityContextBatch:
    observed_at_ms: int
    captured_at_ms: int
    rank_snapshot_digest: str
    snapshots: tuple[PerpMarketSnapshot, ...]

    def __post_init__(self) -> None:
        if (
            type(self.observed_at_ms) is not int or self.observed_at_ms < 0
            or type(self.captured_at_ms) is not int
            or self.captured_at_ms < self.observed_at_ms
            or not isinstance(self.rank_snapshot_digest, str)
            or len(self.rank_snapshot_digest) != 64
            or any(c not in "0123456789abcdef" for c in self.rank_snapshot_digest)
        ):
            raise OriginalRankEligibilityContextError("rank context identity invalid")
        markets = [s.meta.market.canonical for s in self.snapshots]
        if not markets or markets != sorted(set(markets)):
            raise OriginalRankEligibilityContextError(
                "rank context population empty, unsorted or duplicated"
            )
        for snap in self.snapshots:
            if (
                snap.context.market != snap.meta.market
                or type(snap.received_at_ms) is not int
                or not 0 <= snap.received_at_ms <= self.observed_at_ms
                or type(snap.schema_version) is not int
                or snap.schema_version <= 0
                or not isinstance(snap.source, str) or not snap.source.strip()
            ):
                raise OriginalRankEligibilityContextError(
                    "rank context market identity, receive clock or source invalid"
                )

    def bind_to(self, rank: FirstSeenRankSnapshot) -> None:
        if (
            self.observed_at_ms != rank.observed_at_ms
            or self.captured_at_ms != rank.captured_at_ms
            or self.rank_snapshot_digest != rank.snapshot_digest
            or tuple(
                (s.meta.market.canonical, s.received_at_ms)
                for s in self.snapshots
            ) != tuple((market, received) for market, _, received in rank.features)
        ):
            raise OriginalRankEligibilityContextError(
                "rank context input population or parent snapshot disagrees"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "observed_at_ms": self.observed_at_ms,
            "captured_at_ms": self.captured_at_ms,
            "rank_snapshot_digest": self.rank_snapshot_digest,
            "snapshots": [_snapshot_payload(s) for s in self.snapshots],
        }

    @property
    def batch_sha256(self) -> str:
        return _hash(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "batch_sha256": self.batch_sha256}

    @classmethod
    def from_dict(cls, raw: object) -> OriginalRankEligibilityContextBatch:
        data = _obj(raw, {
            "schema_version", "observed_at_ms", "captured_at_ms",
            "rank_snapshot_digest", "snapshots", "batch_sha256",
        })
        if data["schema_version"] != 1 or not isinstance(data["snapshots"], list):
            raise OriginalRankEligibilityContextError("rank context batch schema invalid")
        batch = cls(
            observed_at_ms=cast(int, data["observed_at_ms"]),
            captured_at_ms=cast(int, data["captured_at_ms"]),
            rank_snapshot_digest=cast(str, data["rank_snapshot_digest"]),
            snapshots=tuple(
                _snapshot_from_payload(row) for row in data["snapshots"]
            ),
        )
        if batch.to_dict() != data:
            raise OriginalRankEligibilityContextError(
                "rank context source hash or bytes changed"
            )
        return batch

    @classmethod
    def from_original_rank(
        cls,
        rank: FirstSeenRankSnapshot,
        markets: Mapping[str, PerpMarketSnapshot],
    ) -> OriginalRankEligibilityContextBatch:
        if any(key != item.meta.market.canonical for key, item in markets.items()):
            raise OriginalRankEligibilityContextError("rank context market map mislabeled")
        try:
            snapshots = tuple(
                markets[key] for key, _, _ in rank.features
            )
        except KeyError as exc:
            raise OriginalRankEligibilityContextError(
                "rank source missing original market context"
            ) from exc
        batch = cls(
            observed_at_ms=rank.observed_at_ms,
            captured_at_ms=rank.captured_at_ms,
            rank_snapshot_digest=rank.snapshot_digest,
            snapshots=snapshots,
        )
        batch.bind_to(rank)
        return batch


class OriginalRankEligibilityContextStore:
    """Append-only original context suffix; never fabricate old rank contexts."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.records = self.root / "batches"
        if self.root.is_symlink() or self.records.is_symlink():
            raise OriginalRankEligibilityContextError("rank context path is symlinked")
        self.records.mkdir(parents=True, exist_ok=True)
        prior = self.iter_verified()
        self._last = prior[-1] if prior else None

    def iter_verified(self) -> tuple[OriginalRankEligibilityContextBatch, ...]:
        if self.records.is_symlink():
            raise OriginalRankEligibilityContextError("rank context directory symlinked")
        rows: list[OriginalRankEligibilityContextBatch] = []
        prev_observed = -1
        prev_captured = -1
        for path in sorted(self.records.iterdir()):
            if (
                path.is_symlink() or not path.is_file()
                or len(path.name) != 21
                or not path.name[:16].isascii()
                or not path.name[:16].isdigit()
                or path.name[16:] != ".json"
            ):
                raise OriginalRankEligibilityContextError(
                    "unexpected original market context source file"
                )
            try:
                raw = path.read_bytes()
                item = OriginalRankEligibilityContextBatch.from_dict(json.loads(raw))
            except (OSError, ValueError, TypeError) as exc:
                raise OriginalRankEligibilityContextError(
                    "original rank market context source unreadable"
                ) from exc
            if (
                raw != _canonical(item.to_dict())
                or path.name != f"{item.observed_at_ms:016d}.json"
                or item.observed_at_ms <= prev_observed
                or item.captured_at_ms < prev_captured
            ):
                raise OriginalRankEligibilityContextError(
                    "original rank market context file or chronology altered"
                )
            rows.append(item)
            prev_observed = item.observed_at_ms
            prev_captured = item.captured_at_ms
        return tuple(rows)

    def append(self, batch: OriginalRankEligibilityContextBatch) -> bool:
        path = self.records / f"{batch.observed_at_ms:016d}.json"
        raw = _canonical(batch.to_dict())
        if path.is_symlink():
            raise OriginalRankEligibilityContextError("rank context target symlinked")
        if path.exists():
            if path.read_bytes() != raw:
                raise OriginalRankEligibilityContextError(
                    "original rank market context history conflicts"
                )
            return False
        if self._last is not None and (
            batch.observed_at_ms <= self._last.observed_at_ms
            or batch.captured_at_ms < self._last.captured_at_ms
        ):
            raise OriginalRankEligibilityContextError(
                "rank market context capture backdated across original source"
            )
        pending = path.with_name(f".{path.name}.pending")
        try:
            with pending.open("xb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(pending, path)
            except FileExistsError:
                if path.read_bytes() != raw:
                    raise OriginalRankEligibilityContextError(
                        "rank context concurrent source differs"
                    ) from None
                return False
        finally:
            if pending.exists():
                pending.unlink()
        self._last = batch
        return True

    @property
    def source_digest(self) -> str:
        return _hash([
            {
                "observed_at_ms": row.observed_at_ms,
                "rank_snapshot_digest": row.rank_snapshot_digest,
                "batch_sha256": row.batch_sha256,
            }
            for row in self.iter_verified()
        ])


def replay_recorded_rank_eligibility(
    *,
    rank: FirstSeenRankSnapshot,
    feature_inputs: OriginalRankFeatureInputBatch,
    context: OriginalRankEligibilityContextBatch,
) -> dict[str, object]:
    """Reconstruct ALL coarse eligibility from witnessed context; no feed proof."""
    context.bind_to(rank)
    feature_inputs.bind_to(rank)
    if (
        context.observed_at_ms != feature_inputs.observed_at_ms
        or context.rank_snapshot_digest != feature_inputs.rank_snapshot_digest
    ):
        raise OriginalRankEligibilityContextError(
            "independent original rank source cohorts are not identical"
        )
    features = feature_inputs.features
    observations = context.snapshots
    config = EligibilityConfig()
    thresholds = derive_eligibility_thresholds(features, config)
    decisions = tuple(
        evaluate_eligibility(snapshot, feature, thresholds, config)
        for feature, snapshot in zip(features, observations, strict=True)
    )
    actual = {row.market.canonical for row in decisions if row.rankable}
    claimed = {market for market, _, _, _ in rank.ranks}
    if actual != claimed:
        raise OriginalRankEligibilityContextError(
            "original claimed rankable universe contradicts recorded market context"
        )
    return {
        "schema_version": 1,
        "original_rank_snapshot_digest": rank.snapshot_digest,
        "original_context_batch_sha256": context.batch_sha256,
        "original_full_feature_batch_sha256": feature_inputs.batch_sha256,
        "recorded_context_markets_examined": len(observations),
        "rankable_markets_from_recorded_context": len(actual),
        "original_rank_membership_from_recorded_context_recomputed": True,
        "original_market_context_independently_authenticated": False,
        "mainnet_market_stream_authenticated": False,
        "profitable_risk_matched_account_certified": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
