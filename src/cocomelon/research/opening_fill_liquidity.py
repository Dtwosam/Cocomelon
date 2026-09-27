from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.evidence.openings import BaselineOpeningTrace
from cocomelon.features.microstructure import calculate_microstructure_features

OPENING_FILL_LIQUIDITY_SCHEMA_VERSION: Final = 1
MIN_MATCHED_CLOSED_TRADES: Final = 30
BPS: Final = Decimal("10000")
ZERO: Final = Decimal("0")


class OpeningFillLiquidityError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OpeningFillLiquidityError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise OpeningFillLiquidityError(
            f"{field} must be finite"
        )
    return resolved


@dataclass(frozen=True, slots=True)
class OpeningFillLiquidityEvidence:
    opening_plan_id: str
    strategy_decision_id: str
    feature_snapshot_id: str
    market: str
    direction: str
    opened_at_ms: int
    attempt_timestamp_ms: int
    book_event_key: str
    book_exchange_ms: int
    book_received_ms: int
    book_exchange_age_ms: int
    book_receive_age_ms: int
    spread_bps: Decimal
    bid_depth_25bps: Decimal
    ask_depth_25bps: Decimal
    book_imbalance: Decimal | None
    mid_px: Decimal
    entry_side_depth_25bps: Decimal
    exit_side_depth_25bps: Decimal
    requested_quantity: Decimal
    filled_quantity: Decimal
    gross_fill_notional: Decimal
    average_fill_price: Decimal
    fill_slippage_bps: Decimal
    entry_depth_usage_fraction: Decimal
    decision_spread_bps: Decimal | None
    decision_book_age_ms: int | None
    schema_version: int = OPENING_FILL_LIQUIDITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, field in (
            (self.opening_plan_id, "opening_plan_id"),
            (self.strategy_decision_id, "strategy_decision_id"),
            (self.feature_snapshot_id, "feature_snapshot_id"),
            (self.market, "market"),
            (self.direction, "direction"),
            (self.book_event_key, "book_event_key"),
        ):
            if not value.strip():
                raise ValueError(f"{field} must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        for value, field in (
            (self.opened_at_ms, "opened_at_ms"),
            (self.attempt_timestamp_ms, "attempt_timestamp_ms"),
            (self.book_exchange_ms, "book_exchange_ms"),
            (self.book_received_ms, "book_received_ms"),
            (self.book_exchange_age_ms, "book_exchange_age_ms"),
            (self.book_receive_age_ms, "book_receive_age_ms"),
        ):
            if value < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.attempt_timestamp_ms < self.opened_at_ms:
            raise ValueError(
                "attempt_timestamp_ms must not precede opening"
            )
        if (
            self.book_exchange_age_ms
            != self.attempt_timestamp_ms - self.book_exchange_ms
        ):
            raise ValueError("book exchange age must reconcile")
        if (
            self.book_receive_age_ms
            != self.attempt_timestamp_ms - self.book_received_ms
        ):
            raise ValueError("book receive age must reconcile")
        positive = (
            "spread_bps",
            "bid_depth_25bps",
            "ask_depth_25bps",
            "mid_px",
            "entry_side_depth_25bps",
            "exit_side_depth_25bps",
            "requested_quantity",
            "filled_quantity",
            "gross_fill_notional",
            "average_fill_price",
        )
        for field in positive:
            value = getattr(self, field)
            if not value.is_finite() or value <= ZERO:
                raise ValueError(
                    f"{field} must be positive and finite"
                )
        if self.filled_quantity > self.requested_quantity:
            raise ValueError(
                "filled_quantity must not exceed requested_quantity"
            )
        if (
            not self.fill_slippage_bps.is_finite()
            or self.fill_slippage_bps < ZERO
        ):
            raise ValueError(
                "fill_slippage_bps must be non-negative and finite"
            )
        if (
            not self.entry_depth_usage_fraction.is_finite()
            or self.entry_depth_usage_fraction < ZERO
        ):
            raise ValueError(
                "entry_depth_usage_fraction must be non-negative"
            )
        if self.book_imbalance is not None and (
            not self.book_imbalance.is_finite()
            or self.book_imbalance < Decimal("-1")
            or self.book_imbalance > Decimal("1")
        ):
            raise ValueError(
                "book_imbalance must be finite in [-1, 1]"
            )
        if self.decision_spread_bps is not None and (
            not self.decision_spread_bps.is_finite()
            or self.decision_spread_bps < ZERO
        ):
            raise ValueError(
                "decision_spread_bps must be non-negative"
            )
        if (
            self.decision_book_age_ms is not None
            and self.decision_book_age_ms < 0
        ):
            raise ValueError(
                "decision_book_age_ms must be non-negative"
            )
        if self.schema_version != OPENING_FILL_LIQUIDITY_SCHEMA_VERSION:
            raise ValueError(
                "unsupported opening fill-liquidity schema"
            )

    @property
    def directional_book_imbalance(self) -> Decimal | None:
        if self.book_imbalance is None:
            return None
        if self.direction == "long":
            return self.book_imbalance
        return -self.book_imbalance

    def identity_payload(self) -> dict[str, object]:
        return {
            "opening_plan_id": self.opening_plan_id,
            "strategy_decision_id": self.strategy_decision_id,
            "feature_snapshot_id": self.feature_snapshot_id,
            "market": self.market,
            "direction": self.direction,
            "opened_at_ms": self.opened_at_ms,
            "attempt_timestamp_ms": self.attempt_timestamp_ms,
            "book_event_key": self.book_event_key,
            "book_exchange_ms": self.book_exchange_ms,
            "book_received_ms": self.book_received_ms,
            "book_exchange_age_ms": self.book_exchange_age_ms,
            "book_receive_age_ms": self.book_receive_age_ms,
            "spread_bps": str(self.spread_bps),
            "bid_depth_25bps": str(self.bid_depth_25bps),
            "ask_depth_25bps": str(self.ask_depth_25bps),
            "book_imbalance": (
                None
                if self.book_imbalance is None
                else str(self.book_imbalance)
            ),
            "mid_px": str(self.mid_px),
            "entry_side_depth_25bps": str(
                self.entry_side_depth_25bps
            ),
            "exit_side_depth_25bps": str(
                self.exit_side_depth_25bps
            ),
            "requested_quantity": str(self.requested_quantity),
            "filled_quantity": str(self.filled_quantity),
            "gross_fill_notional": str(self.gross_fill_notional),
            "average_fill_price": str(self.average_fill_price),
            "fill_slippage_bps": str(self.fill_slippage_bps),
            "entry_depth_usage_fraction": str(
                self.entry_depth_usage_fraction
            ),
            "decision_spread_bps": (
                None
                if self.decision_spread_bps is None
                else str(self.decision_spread_bps)
            ),
            "decision_book_age_ms": self.decision_book_age_ms,
            "schema_version": self.schema_version,
        }

    @property
    def evidence_id(self) -> str:
        return _digest(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "evidence_id": self.evidence_id,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> OpeningFillLiquidityEvidence:
        if not isinstance(raw, dict):
            raise OpeningFillLiquidityError(
                "fill-liquidity record must be an object"
            )
        expected = {
            "opening_plan_id",
            "strategy_decision_id",
            "feature_snapshot_id",
            "market",
            "direction",
            "opened_at_ms",
            "attempt_timestamp_ms",
            "book_event_key",
            "book_exchange_ms",
            "book_received_ms",
            "book_exchange_age_ms",
            "book_receive_age_ms",
            "spread_bps",
            "bid_depth_25bps",
            "ask_depth_25bps",
            "book_imbalance",
            "mid_px",
            "entry_side_depth_25bps",
            "exit_side_depth_25bps",
            "requested_quantity",
            "filled_quantity",
            "gross_fill_notional",
            "average_fill_price",
            "fill_slippage_bps",
            "entry_depth_usage_fraction",
            "decision_spread_bps",
            "decision_book_age_ms",
            "schema_version",
            "evidence_id",
        }
        if set(raw) != expected:
            raise OpeningFillLiquidityError(
                "fill-liquidity record fields are invalid"
            )
        try:
            evidence = cls(
                opening_plan_id=str(raw["opening_plan_id"]),
                strategy_decision_id=str(
                    raw["strategy_decision_id"]
                ),
                feature_snapshot_id=str(raw["feature_snapshot_id"]),
                market=str(raw["market"]),
                direction=str(raw["direction"]),
                opened_at_ms=int(raw["opened_at_ms"]),
                attempt_timestamp_ms=int(
                    raw["attempt_timestamp_ms"]
                ),
                book_event_key=str(raw["book_event_key"]),
                book_exchange_ms=int(raw["book_exchange_ms"]),
                book_received_ms=int(raw["book_received_ms"]),
                book_exchange_age_ms=int(
                    raw["book_exchange_age_ms"]
                ),
                book_receive_age_ms=int(
                    raw["book_receive_age_ms"]
                ),
                spread_bps=_decimal(
                    raw["spread_bps"],
                    "spread_bps",
                ),
                bid_depth_25bps=_decimal(
                    raw["bid_depth_25bps"],
                    "bid_depth_25bps",
                ),
                ask_depth_25bps=_decimal(
                    raw["ask_depth_25bps"],
                    "ask_depth_25bps",
                ),
                book_imbalance=(
                    None
                    if raw["book_imbalance"] is None
                    else _decimal(
                        raw["book_imbalance"],
                        "book_imbalance",
                    )
                ),
                mid_px=_decimal(raw["mid_px"], "mid_px"),
                entry_side_depth_25bps=_decimal(
                    raw["entry_side_depth_25bps"],
                    "entry_side_depth_25bps",
                ),
                exit_side_depth_25bps=_decimal(
                    raw["exit_side_depth_25bps"],
                    "exit_side_depth_25bps",
                ),
                requested_quantity=_decimal(
                    raw["requested_quantity"],
                    "requested_quantity",
                ),
                filled_quantity=_decimal(
                    raw["filled_quantity"],
                    "filled_quantity",
                ),
                gross_fill_notional=_decimal(
                    raw["gross_fill_notional"],
                    "gross_fill_notional",
                ),
                average_fill_price=_decimal(
                    raw["average_fill_price"],
                    "average_fill_price",
                ),
                fill_slippage_bps=_decimal(
                    raw["fill_slippage_bps"],
                    "fill_slippage_bps",
                ),
                entry_depth_usage_fraction=_decimal(
                    raw["entry_depth_usage_fraction"],
                    "entry_depth_usage_fraction",
                ),
                decision_spread_bps=(
                    None
                    if raw["decision_spread_bps"] is None
                    else _decimal(
                        raw["decision_spread_bps"],
                        "decision_spread_bps",
                    )
                ),
                decision_book_age_ms=(
                    None
                    if raw["decision_book_age_ms"] is None
                    else int(raw["decision_book_age_ms"])
                ),
                schema_version=int(raw["schema_version"]),
            )
        except (TypeError, ValueError) as exc:
            raise OpeningFillLiquidityError(
                "fill-liquidity record is invalid"
            ) from exc
        if raw["evidence_id"] != evidence.evidence_id:
            raise OpeningFillLiquidityError(
                "fill-liquidity evidence id mismatch"
            )
        return evidence


def evidence_from_opening_trace(
    trace: BaselineOpeningTrace,
) -> OpeningFillLiquidityEvidence | None:
    submission = trace.submission
    simulation = submission.simulation
    plan = submission.plan
    if plan is None or simulation is None or not simulation.fills:
        return None
    attempt = simulation.attempt
    if attempt.average_fill_price is None:
        raise OpeningFillLiquidityError(
            "filled opening attempt is missing average_fill_price"
        )
    book = trace.book_event
    if book.exchange_time_ms is None:
        raise OpeningFillLiquidityError(
            "opening L2 book is missing exchange time"
        )
    micro = calculate_microstructure_features(
        book,
        as_of_ms=attempt.attempt_timestamp_ms,
    )
    direction = trace.evaluation.decision.direction
    if direction is Direction.LONG:
        entry_depth = micro.ask_depth_25bps
        exit_depth = micro.bid_depth_25bps
        slippage = (
            attempt.average_fill_price - micro.mid_px
        ) / micro.mid_px * BPS
    elif direction is Direction.SHORT:
        entry_depth = micro.bid_depth_25bps
        exit_depth = micro.ask_depth_25bps
        slippage = (
            micro.mid_px - attempt.average_fill_price
        ) / micro.mid_px * BPS
    else:
        raise OpeningFillLiquidityError(
            "filled opening trace must be directional"
        )
    if entry_depth <= ZERO:
        raise OpeningFillLiquidityError(
            "entry-side 25bps depth must be positive"
        )
    opened_at_ms = min(
        fill.timestamp_ms for fill in simulation.fills
    )
    return OpeningFillLiquidityEvidence(
        opening_plan_id=plan.plan_id,
        strategy_decision_id=plan.strategy_decision_id,
        feature_snapshot_id=trace.evaluation.feature.snapshot_id,
        market=plan.market.canonical,
        direction=direction.value,
        opened_at_ms=opened_at_ms,
        attempt_timestamp_ms=attempt.attempt_timestamp_ms,
        book_event_key=book.event_key,
        book_exchange_ms=book.exchange_time_ms,
        book_received_ms=micro.source_received_at_ms,
        book_exchange_age_ms=micro.book_age_ms,
        book_receive_age_ms=(
            attempt.attempt_timestamp_ms
            - micro.source_received_at_ms
        ),
        spread_bps=micro.spread_bps,
        bid_depth_25bps=micro.bid_depth_25bps,
        ask_depth_25bps=micro.ask_depth_25bps,
        book_imbalance=micro.book_imbalance,
        mid_px=micro.mid_px,
        entry_side_depth_25bps=entry_depth,
        exit_side_depth_25bps=exit_depth,
        requested_quantity=attempt.requested_quantity,
        filled_quantity=attempt.filled_quantity,
        gross_fill_notional=attempt.gross_fill_notional,
        average_fill_price=attempt.average_fill_price,
        fill_slippage_bps=max(ZERO, slippage),
        entry_depth_usage_fraction=(
            attempt.gross_fill_notional / entry_depth
        ),
        decision_spread_bps=trace.evaluation.feature.spread_bps,
        decision_book_age_ms=trace.evaluation.feature.book_age_ms,
    )


class OpeningFillLiquidityStore:
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
        return self.records_root / self._record_name(
            opening_plan_id
        )

    def record(
        self,
        evidence: OpeningFillLiquidityEvidence,
    ) -> bool:
        path = self._path(evidence.opening_plan_id)
        encoded = (
            _canonical_json(evidence.to_dict()) + "\n"
        ).encode("utf-8")
        if path.exists():
            if path.read_bytes() != encoded:
                raise OpeningFillLiquidityError(
                    "OPENING_FILL_LIQUIDITY_CONFLICT"
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
                    raise OpeningFillLiquidityError(
                        "OPENING_FILL_LIQUIDITY_CONFLICT"
                    ) from None
                return False
        finally:
            if temporary.exists():
                temporary.unlink()
        return True

    def load(
        self,
        opening_plan_id: str,
    ) -> OpeningFillLiquidityEvidence | None:
        path = self._path(opening_plan_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpeningFillLiquidityError(
                "OPENING_FILL_LIQUIDITY_UNREADABLE"
            ) from exc
        record = OpeningFillLiquidityEvidence.from_dict(raw)
        if record.opening_plan_id != opening_plan_id:
            raise OpeningFillLiquidityError(
                "fill-liquidity plan id mismatch"
            )
        canonical = (
            _canonical_json(record.to_dict()) + "\n"
        ).encode("utf-8")
        if path.read_bytes() != canonical:
            raise OpeningFillLiquidityError(
                "fill-liquidity record is non-canonical"
            )
        return record

    def iter_records(
        self,
    ) -> tuple[OpeningFillLiquidityEvidence, ...]:
        records: list[OpeningFillLiquidityEvidence] = []
        for path in sorted(self.records_root.glob("*.json")):
            record = self.load_by_path(path)
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

    def load_by_path(
        self,
        path: Path,
    ) -> OpeningFillLiquidityEvidence:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpeningFillLiquidityError(
                "OPENING_FILL_LIQUIDITY_UNREADABLE"
            ) from exc
        record = OpeningFillLiquidityEvidence.from_dict(raw)
        if path.name != self._record_name(
            record.opening_plan_id
        ):
            raise OpeningFillLiquidityError(
                "fill-liquidity filename mismatch"
            )
        canonical = (
            _canonical_json(record.to_dict()) + "\n"
        ).encode("utf-8")
        if path.read_bytes() != canonical:
            raise OpeningFillLiquidityError(
                "fill-liquidity record is non-canonical"
            )
        return record

    @property
    def record_count(self) -> int:
        return len(self.iter_records())

    @property
    def state_digest(self) -> str:
        return _digest(
            tuple(
                record.to_dict()
                for record in self.iter_records()
            )
        )


def _mean(
    values: Sequence[Decimal],
) -> str | None:
    resolved = tuple(values)
    if not resolved:
        return None
    return str(sum(resolved, ZERO) / Decimal(len(resolved)))


def _summarize(
    pairs: Sequence[
        tuple[
            TradeJournalEntry,
            OpeningFillLiquidityEvidence,
        ]
    ],
) -> dict[str, object]:
    resolved = tuple(pairs)
    directional_imbalance = tuple(
        record.directional_book_imbalance
        for _, record in resolved
        if record.directional_book_imbalance is not None
    )
    return {
        "trades": len(resolved),
        "wins": sum(
            1 for trade, _ in resolved if trade.net_pnl > ZERO
        ),
        "losses": sum(
            1 for trade, _ in resolved if trade.net_pnl < ZERO
        ),
        "net_pnl": str(
            sum(
                (trade.net_pnl for trade, _ in resolved),
                ZERO,
            )
        ),
        "mean_net_r": _mean(
            tuple(trade.net_r for trade, _ in resolved)
        ),
        "mean_spread_bps": _mean(
            tuple(record.spread_bps for _, record in resolved)
        ),
        "mean_fill_slippage_bps": _mean(
            tuple(
                record.fill_slippage_bps
                for _, record in resolved
            )
        ),
        "mean_entry_depth_25bps": _mean(
            tuple(
                record.entry_side_depth_25bps
                for _, record in resolved
            )
        ),
        "mean_exit_depth_25bps": _mean(
            tuple(
                record.exit_side_depth_25bps
                for _, record in resolved
            )
        ),
        "mean_entry_depth_usage_fraction": _mean(
            tuple(
                record.entry_depth_usage_fraction
                for _, record in resolved
            )
        ),
        "mean_directional_book_imbalance": _mean(
            directional_imbalance
        ),
        "mean_book_receive_age_ms": (
            None
            if not resolved
            else sum(
                record.book_receive_age_ms
                for _, record in resolved
            )
            // len(resolved)
        ),
    }


def opening_fill_liquidity_attribution(
    trades: Sequence[TradeJournalEntry],
    store: OpeningFillLiquidityStore,
) -> dict[str, object]:
    matched: list[
        tuple[
            TradeJournalEntry,
            OpeningFillLiquidityEvidence,
        ]
    ] = []
    without_evidence = 0
    for trade in trades:
        evidence = store.load(trade.opening_plan_id)
        if evidence is None:
            without_evidence += 1
            continue
        if (
            evidence.market != trade.market.canonical
            or evidence.direction != trade.direction.value
            or evidence.opened_at_ms != trade.opened_at_ms
            or evidence.strategy_decision_id
            != trade.strategy_decision_id
            or evidence.feature_snapshot_id
            != trade.feature_snapshot_id
        ):
            raise OpeningFillLiquidityError(
                "fill-liquidity evidence does not match trade"
            )
        matched.append((trade, evidence))

    winners = tuple(
        pair
        for pair in matched
        if pair[0].net_pnl > ZERO
    )
    losers = tuple(
        pair
        for pair in matched
        if pair[0].net_pnl < ZERO
    )
    longs = tuple(
        pair
        for pair in matched
        if pair[0].direction is Direction.LONG
    )
    shorts = tuple(
        pair
        for pair in matched
        if pair[0].direction is Direction.SHORT
    )
    matched_count = len(matched)
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "evidence_source": "exact_opening_ioc_l2_book",
        "evidence_records": store.record_count,
        "attributed_closed_trades": matched_count,
        "closed_trades_without_fill_liquidity_evidence": (
            without_evidence
        ),
        "unmatched_open_or_pending_records": max(
            0,
            store.record_count - matched_count,
        ),
        "review_gate_closed_trades": MIN_MATCHED_CLOSED_TRADES,
        "still_needed_closed_trades": max(
            0,
            MIN_MATCHED_CLOSED_TRADES - matched_count,
        ),
        "ready_for_review": (
            matched_count >= MIN_MATCHED_CLOSED_TRADES
        ),
        "overall": _summarize(matched),
        "winners": _summarize(winners),
        "losers": _summarize(losers),
        "by_side": {
            "long": _summarize(longs),
            "short": _summarize(shorts),
        },
    }
