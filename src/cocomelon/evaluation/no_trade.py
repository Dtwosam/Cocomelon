from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext

from cocomelon.domain.evaluation import DecisionEvaluationFact, EvaluationPolicy
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction
from cocomelon.journal.observations import should_sample_no_trade

AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
ACTIVE_ASSET_CTX = "active_asset_ctx"


@dataclass(frozen=True, slots=True)
class NoTradeHorizonOutcome:
    decision_fact_id: str
    horizon_ms: int
    start_mark: Decimal | None
    end_mark: Decimal | None
    end_return_fraction: Decimal | None
    max_up_fraction: Decimal | None
    max_down_fraction: Decimal | None
    complete: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.decision_fact_id.strip():
            raise ValueError("decision_fact_id must not be empty")
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        for field in ("start_mark", "end_mark"):
            value = getattr(self, field)
            if value is not None and (not value.is_finite() or value <= 0):
                raise ValueError(f"{field} must be finite and positive when present")
        for field in ("end_return_fraction", "max_up_fraction", "max_down_fraction"):
            value = getattr(self, field)
            if value is not None and not value.is_finite():
                raise ValueError(f"{field} must be finite when present")
        if self.start_mark is None and any(
            value is not None
            for value in (
                self.end_return_fraction,
                self.max_up_fraction,
                self.max_down_fraction,
            )
        ):
            raise ValueError("return fractions require a start mark")
        if self.end_mark is None and self.end_return_fraction is not None:
            raise ValueError("end_return_fraction requires an end mark")
        normalized = tuple(dict.fromkeys(self.reason_codes))
        if any(not value.strip() for value in normalized):
            raise ValueError("reason_codes values must not be empty")
        object.__setattr__(self, "reason_codes", normalized)


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, dict) else None


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result <= 0:
        return None
    return result


def _mark_price(record: ReplayRecord, market: str) -> Decimal | None:
    if (
        record.record_kind is not SourceRecordKind.NORMALIZED_EVENT
        or record.event_kind != ACTIVE_ASSET_CTX
        or record.market != market
    ):
        return None
    payload = _mapping(record.payload)
    if payload is None:
        return None
    return _decimal(payload.get("mark_px"))


def _gap_intersects(
    record: ReplayRecord,
    *,
    stream_id: str,
    start_ms: int,
    end_ms: int,
) -> bool:
    if record.record_kind is not SourceRecordKind.DATA_GAP:
        return False
    payload = _mapping(record.payload)
    if payload is None or payload.get("stream_id") != stream_id:
        return False
    gap_start = payload.get("started_ms")
    gap_end = payload.get("ended_ms")
    if isinstance(gap_start, bool) or not isinstance(gap_start, int):
        return False
    if gap_end is not None and (isinstance(gap_end, bool) or not isinstance(gap_end, int)):
        return False
    return gap_start <= end_ms and (gap_end is None or gap_end > start_ms)


def _outcome(
    decision: DecisionEvaluationFact,
    records: tuple[ReplayRecord, ...],
    *,
    horizon_ms: int,
) -> NoTradeHorizonOutcome:
    decision_ms = decision.timestamp_ms
    horizon_end_ms = decision_ms + horizon_ms
    market = decision.market.canonical

    start_candidates: list[tuple[int, str, Decimal]] = []
    future_candidates: list[tuple[int, str, Decimal]] = []
    for record in records:
        price = _mark_price(record, market)
        if price is None:
            continue
        key = record.event_key or record.payload_json
        if record.available_at_ms <= decision_ms:
            start_candidates.append((record.available_at_ms, key, price))
        elif record.available_at_ms <= horizon_end_ms:
            future_candidates.append((record.available_at_ms, key, price))

    start_mark = max(start_candidates, default=None, key=lambda item: (item[0], item[1]))
    ordered_future = tuple(sorted(future_candidates, key=lambda item: (item[0], item[1])))
    end_mark = ordered_future[-1][2] if ordered_future else None

    reasons: list[str] = []
    if start_mark is None:
        reasons.append("MISSING_START_MARK")
    if end_mark is None:
        reasons.append("MISSING_FUTURE_MARK")

    stream_id = f"activeAssetCtx:{decision.market.wire_name}"
    if any(
        _gap_intersects(
            record,
            stream_id=stream_id,
            start_ms=decision_ms,
            end_ms=horizon_end_ms,
        )
        for record in records
    ):
        reasons.append("DATA_GAP_INTERSECTS_HORIZON")

    start_price = None if start_mark is None else start_mark[2]
    if start_price is None:
        end_return = None
        max_up = None
        max_down = None
    else:
        with localcontext(AUTHORITATIVE_CONTEXT):
            end_return = None if end_mark is None else (end_mark - start_price) / start_price
            path_prices = (start_price, *(item[2] for item in ordered_future))
            max_up = (max(path_prices) - start_price) / start_price
            max_down = (min(path_prices) - start_price) / start_price

    return NoTradeHorizonOutcome(
        decision_fact_id=decision.fact_id,
        horizon_ms=horizon_ms,
        start_mark=start_price,
        end_mark=end_mark,
        end_return_fraction=end_return,
        max_up_fraction=max_up,
        max_down_fraction=max_down,
        complete=not reasons,
        reason_codes=tuple(reasons),
    )


def evaluate_no_trade_outcomes(
    decisions: Sequence[DecisionEvaluationFact],
    records: Sequence[ReplayRecord],
    *,
    policy: EvaluationPolicy,
    sample_numerator: int,
    sample_denominator: int,
) -> tuple[NoTradeHorizonOutcome, ...]:
    ordered_records = tuple(sorted(records, key=lambda item: item.sort_key))
    selected = tuple(
        sorted(
            (
                decision
                for decision in decisions
                if decision.direction is Direction.NO_TRADE
                and should_sample_no_trade(
                    decision.strategy_decision_id,
                    numerator=sample_numerator,
                    denominator=sample_denominator,
                )
            ),
            key=lambda item: (item.timestamp_ms, item.fact_id),
        )
    )

    return tuple(
        _outcome(decision, ordered_records, horizon_ms=horizon_ms)
        for decision in selected
        for horizon_ms in policy.no_trade_horizons_ms
    )
