from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

from cocomelon.domain.features import OpportunityRank
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId

OPENING_RANK_SCHEMA_VERSION: Final = 1
ZERO: Final = Decimal("0")


class ContinuousPaperOpeningRankError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ContinuousPaperOpeningRankEvidence:
    opening_plan_id: str
    market: str
    opened_at_ms: int
    rank_observed_at_ms: int
    rank_age_ms: int
    ordinal: int
    score: Decimal
    rank_pool_size: int
    reason_codes: tuple[str, ...]
    schema_version: int = OPENING_RANK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.opening_plan_id, "opening_plan_id"),
            (self.market, "market"),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.opened_at_ms < 0 or self.rank_observed_at_ms < 0:
            raise ValueError("rank evidence timestamps must be non-negative")
        if self.rank_observed_at_ms > self.opened_at_ms:
            raise ValueError("rank observation cannot be after opening")
        if self.rank_age_ms != (
            self.opened_at_ms - self.rank_observed_at_ms
        ):
            raise ValueError("rank_age_ms must reconcile")
        if self.ordinal <= 0:
            raise ValueError("ordinal must be positive")
        if not self.score.is_finite() or not ZERO <= self.score <= Decimal("1"):
            raise ValueError("score must be finite in [0, 1]")
        if self.rank_pool_size < self.ordinal:
            raise ValueError("rank_pool_size must include ordinal")
        normalized = tuple(dict.fromkeys(self.reason_codes))
        if any(not reason.strip() for reason in normalized):
            raise ValueError("reason_codes must not contain empty values")
        if normalized != self.reason_codes:
            raise ValueError("reason_codes must be canonical")
        if self.schema_version != OPENING_RANK_SCHEMA_VERSION:
            raise ValueError("unsupported opening-rank schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "opening_plan_id": self.opening_plan_id,
            "market": self.market,
            "opened_at_ms": self.opened_at_ms,
            "rank_observed_at_ms": self.rank_observed_at_ms,
            "rank_age_ms": self.rank_age_ms,
            "ordinal": self.ordinal,
            "score": str(self.score),
            "rank_pool_size": self.rank_pool_size,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
        }

    @property
    def evidence_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "evidence_id": self.evidence_id,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> ContinuousPaperOpeningRankEvidence:
        if not isinstance(raw, dict):
            raise ContinuousPaperOpeningRankError(
                "opening-rank record must be an object"
            )
        expected = {
            "opening_plan_id",
            "market",
            "opened_at_ms",
            "rank_observed_at_ms",
            "rank_age_ms",
            "ordinal",
            "score",
            "rank_pool_size",
            "reason_codes",
            "schema_version",
            "evidence_id",
        }
        if set(raw) != expected:
            raise ContinuousPaperOpeningRankError(
                "opening-rank record fields are invalid"
            )
        reasons = raw["reason_codes"]
        if not isinstance(reasons, list) or not all(
            isinstance(value, str) for value in reasons
        ):
            raise ContinuousPaperOpeningRankError(
                "opening-rank reason_codes must be a string array"
            )
        try:
            evidence = cls(
                opening_plan_id=str(raw["opening_plan_id"]),
                market=str(raw["market"]),
                opened_at_ms=int(raw["opened_at_ms"]),
                rank_observed_at_ms=int(raw["rank_observed_at_ms"]),
                rank_age_ms=int(raw["rank_age_ms"]),
                ordinal=int(raw["ordinal"]),
                score=Decimal(str(raw["score"])),
                rank_pool_size=int(raw["rank_pool_size"]),
                reason_codes=tuple(reasons),
                schema_version=int(raw["schema_version"]),
            )
        except (TypeError, ValueError) as exc:
            raise ContinuousPaperOpeningRankError(
                "opening-rank record is invalid"
            ) from exc
        if raw["evidence_id"] != evidence.evidence_id:
            raise ContinuousPaperOpeningRankError(
                "opening-rank evidence id mismatch"
            )
        return evidence


class ContinuousPaperOpeningRankStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.records_root = self.root / "records"
        self.records_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _record_name(opening_plan_id: str) -> str:
        if not opening_plan_id.strip():
            raise ValueError("opening_plan_id must not be empty")
        return (
            hashlib.sha256(
                opening_plan_id.encode("utf-8")
            ).hexdigest()
            + ".json"
        )

    def _path(self, opening_plan_id: str) -> Path:
        return self.records_root / self._record_name(opening_plan_id)

    def record(
        self,
        evidence: ContinuousPaperOpeningRankEvidence,
    ) -> bool:
        path = self._path(evidence.opening_plan_id)
        encoded = (
            _canonical_json(evidence.to_dict()) + "\n"
        ).encode("utf-8")
        if path.exists():
            if path.read_bytes() != encoded:
                raise ContinuousPaperOpeningRankError(
                    "OPENING_RANK_EVIDENCE_CONFLICT"
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
                    raise ContinuousPaperOpeningRankError(
                        "OPENING_RANK_EVIDENCE_CONFLICT"
                    ) from None
                return False
        finally:
            if temporary.exists():
                temporary.unlink()
        return True

    def load(
        self,
        opening_plan_id: str,
    ) -> ContinuousPaperOpeningRankEvidence | None:
        path = self._path(opening_plan_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContinuousPaperOpeningRankError(
                "OPENING_RANK_EVIDENCE_UNREADABLE"
            ) from exc
        evidence = ContinuousPaperOpeningRankEvidence.from_dict(raw)
        if evidence.opening_plan_id != opening_plan_id:
            raise ContinuousPaperOpeningRankError(
                "opening-rank plan id mismatch"
            )
        canonical = (
            _canonical_json(evidence.to_dict()) + "\n"
        ).encode("utf-8")
        if path.read_bytes() != canonical:
            raise ContinuousPaperOpeningRankError(
                "opening-rank record is non-canonical"
            )
        return evidence

    def iter_records(
        self,
    ) -> tuple[ContinuousPaperOpeningRankEvidence, ...]:
        records: list[ContinuousPaperOpeningRankEvidence] = []
        for path in sorted(self.records_root.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ContinuousPaperOpeningRankError(
                    "OPENING_RANK_EVIDENCE_UNREADABLE"
                ) from exc
            record = ContinuousPaperOpeningRankEvidence.from_dict(raw)
            if path.name != self._record_name(record.opening_plan_id):
                raise ContinuousPaperOpeningRankError(
                    "opening-rank filename mismatch"
                )
            records.append(record)
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.opened_at_ms,
                    item.market,
                    item.opening_plan_id,
                ),
            )
        )

    @property
    def record_count(self) -> int:
        return len(self.iter_records())

    @property
    def state_digest(self) -> str:
        return _sha256_json(
            tuple(record.to_dict() for record in self.iter_records())
        )


class LatestCoarseRankTracker:
    def __init__(self) -> None:
        self._observed_at_ms: int | None = None
        self._ranks: dict[str, OpportunityRank] = {}
        self._pool_size = 0

    def update(
        self,
        ranks: Sequence[OpportunityRank],
        *,
        observed_at_ms: int,
    ) -> None:
        if observed_at_ms < 0:
            raise ValueError("observed_at_ms must be non-negative")
        resolved = tuple(ranks)
        keys = [rank.market.canonical for rank in resolved]
        if len(keys) != len(set(keys)):
            raise ValueError("coarse rank snapshot contains duplicate markets")
        if any(rank.ordinal != index for index, rank in enumerate(resolved, 1)):
            raise ValueError("coarse rank snapshot ordinals must be contiguous")
        self._observed_at_ms = observed_at_ms
        self._ranks = {
            rank.market.canonical: rank
            for rank in resolved
        }
        self._pool_size = len(resolved)

    def evidence_for_opening(
        self,
        *,
        opening_plan_id: str,
        market: MarketId,
        opened_at_ms: int,
    ) -> ContinuousPaperOpeningRankEvidence | None:
        observed_at_ms = self._observed_at_ms
        if observed_at_ms is None or observed_at_ms > opened_at_ms:
            return None
        rank = self._ranks.get(market.canonical)
        if rank is None:
            return None
        return ContinuousPaperOpeningRankEvidence(
            opening_plan_id=opening_plan_id,
            market=market.canonical,
            opened_at_ms=opened_at_ms,
            rank_observed_at_ms=observed_at_ms,
            rank_age_ms=opened_at_ms - observed_at_ms,
            ordinal=rank.ordinal,
            score=rank.score,
            rank_pool_size=self._pool_size,
            reason_codes=tuple(rank.reason_codes),
        )


def _bucket(ordinal: int) -> str:
    if ordinal <= 5:
        return "1-5"
    if ordinal <= 10:
        return "6-10"
    if ordinal <= 20:
        return "11-20"
    return "21+"


def opening_rank_attribution(
    trades: Sequence[TradeJournalEntry],
    store: ContinuousPaperOpeningRankStore,
) -> dict[str, object]:
    grouped: dict[str, list[TradeJournalEntry]] = {}
    ages: list[int] = []
    attributed = 0
    misses = 0

    for trade in trades:
        evidence = store.load(trade.opening_plan_id)
        if evidence is None:
            misses += 1
            continue
        if (
            evidence.market != trade.market.canonical
            or evidence.opened_at_ms != trade.opened_at_ms
        ):
            raise ContinuousPaperOpeningRankError(
                "opening-rank evidence does not match trade"
            )
        attributed += 1
        ages.append(evidence.rank_age_ms)
        grouped.setdefault(
            _bucket(evidence.ordinal),
            [],
        ).append(trade)

    def summarize(
        items: Sequence[TradeJournalEntry],
    ) -> dict[str, object]:
        resolved = tuple(items)
        count = len(resolved)
        net_pnl = sum(
            (trade.net_pnl for trade in resolved),
            ZERO,
        )
        net_r = sum(
            (trade.net_r for trade in resolved),
            ZERO,
        )
        return {
            "trades": count,
            "wins": sum(
                1 for trade in resolved if trade.net_pnl > ZERO
            ),
            "losses": sum(
                1 for trade in resolved if trade.net_pnl < ZERO
            ),
            "breakeven": sum(
                1 for trade in resolved if trade.net_pnl == ZERO
            ),
            "net_pnl": str(net_pnl),
            "mean_net_r": (
                None
                if count == 0
                else str(net_r / Decimal(count))
            ),
        }

    return {
        "research_only": True,
        "execution_authority": False,
        "rank_definition": "latest_coarse_rank_before_open",
        "prospective_only": True,
        "evidence_records": store.record_count,
        "attributed_closed_trades": attributed,
        "attribution_misses": misses,
        "mean_rank_age_ms": (
            None
            if not ages
            else sum(ages) // len(ages)
        ),
        "max_rank_age_ms": (
            None
            if not ages
            else max(ages)
        ),
        "by_rank_bucket": {
            bucket: summarize(items)
            for bucket, items in sorted(grouped.items())
        },
    }
