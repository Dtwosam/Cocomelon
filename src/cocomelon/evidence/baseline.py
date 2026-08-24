from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from cocomelon.domain.market import (
    Candle,
    FundingRate,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.stream import StreamEvent, StreamKind


@dataclass(slots=True)
class RecordedMarketState:
    market: MarketId
    latest_snapshot: PerpMarketSnapshot | None = None
    previous_snapshot: PerpMarketSnapshot | None = None
    candles_5m: dict[int, Candle] = field(default_factory=dict)
    candles_15m: dict[int, Candle] = field(default_factory=dict)
    latest_book: StreamEvent | None = None
    micro_events: deque[StreamEvent] = field(default_factory=deque)
    latest_asset_ctx: StreamEvent | None = None
    funding_by_boundary: dict[int, FundingRate] = field(default_factory=dict)
    _snapshot_available_at_ms: int | None = field(default=None, repr=False)
    _candle_5m_available_at: dict[int, int] = field(default_factory=dict, repr=False)
    _candle_15m_available_at: dict[int, int] = field(default_factory=dict, repr=False)
    _book_available_at_ms: int | None = field(default=None, repr=False)
    _asset_ctx_available_at_ms: int | None = field(default=None, repr=False)
    _funding_available_at: dict[int, int] = field(default_factory=dict, repr=False)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _optional_integer(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field_name)


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{field_name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field_name)


def _market(value: str) -> MarketId:
    if ":" not in value:
        return MarketId.from_wire_name("", value)
    dex = value.split(":", 1)[0]
    return MarketId.from_wire_name(dex, value)


def _receive_time(record: ReplayRecord) -> datetime:
    return datetime.fromtimestamp(record.available_at_ms / 1000, tz=UTC)


def _normalized_event(record: ReplayRecord, expected_kind: str | None = None) -> MarketId:
    if record.record_kind is not SourceRecordKind.NORMALIZED_EVENT:
        raise ValueError("replay record must be a normalized event")
    if record.market is None:
        raise ValueError("normalized replay event is missing market")
    if record.event_kind is None:
        raise ValueError("normalized replay event is missing event kind")
    if expected_kind is not None and record.event_kind != expected_kind:
        raise ValueError(f"expected {expected_kind} replay event")
    if record.event_key is None:
        raise ValueError("normalized replay event is missing event key")
    return _market(record.market)


def replay_record_market_snapshot(record: ReplayRecord) -> PerpMarketSnapshot:
    market = _normalized_event(record, "market_snapshot")
    payload = _mapping(record.payload, "market snapshot payload")
    raw_meta = _mapping(payload.get("meta"), "market snapshot meta")
    raw_context = _mapping(payload.get("context"), "market snapshot context")
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market,
            wire_name=_string(raw_meta.get("wire_name"), "wire_name"),
            sz_decimals=_integer(raw_meta.get("sz_decimals"), "sz_decimals"),
            max_leverage=_integer(raw_meta.get("max_leverage"), "max_leverage"),
            margin_table_id=_optional_integer(
                raw_meta.get("margin_table_id"),
                "margin_table_id",
            ),
            only_isolated=bool(raw_meta.get("only_isolated")),
            is_delisted=bool(raw_meta.get("is_delisted")),
            margin_mode=(
                None
                if raw_meta.get("margin_mode") is None
                else _string(raw_meta.get("margin_mode"), "margin_mode")
            ),
        ),
        context=PerpMarketContext(
            market=market,
            mark_px=_optional_decimal(raw_context.get("mark_px"), "mark_px"),
            mid_px=_optional_decimal(raw_context.get("mid_px"), "mid_px"),
            oracle_px=_optional_decimal(raw_context.get("oracle_px"), "oracle_px"),
            funding=_decimal(raw_context.get("funding"), "funding"),
            open_interest=_decimal(raw_context.get("open_interest"), "open_interest"),
            day_ntl_vlm=_decimal(raw_context.get("day_ntl_vlm"), "day_ntl_vlm"),
            premium=_optional_decimal(raw_context.get("premium"), "premium"),
            prev_day_px=_decimal(raw_context.get("prev_day_px"), "prev_day_px"),
        ),
        source=record.source,
        received_at_ms=record.available_at_ms,
        schema_version=record.schema_version,
    )


def replay_record_candle(record: ReplayRecord) -> Candle:
    market = _normalized_event(record, "candle")
    payload = _mapping(record.payload, "candle payload")
    return Candle(
        market=market,
        interval=_string(payload.get("interval"), "interval"),
        start_ms=_integer(payload.get("start_ms"), "start_ms"),
        end_ms=_integer(payload.get("end_ms"), "end_ms"),
        open_px=_decimal(payload.get("open_px"), "open_px"),
        high_px=_decimal(payload.get("high_px"), "high_px"),
        low_px=_decimal(payload.get("low_px"), "low_px"),
        close_px=_decimal(payload.get("close_px"), "close_px"),
        volume=_decimal(payload.get("volume"), "volume"),
        trade_count=_integer(payload.get("trade_count"), "trade_count"),
        source=record.source,
        received_at_ms=record.available_at_ms,
        schema_version=record.schema_version,
    )


def replay_record_funding_rate(record: ReplayRecord) -> FundingRate:
    market = _normalized_event(record, "funding_rate")
    payload = _mapping(record.payload, "funding rate payload")
    return FundingRate(
        market=market,
        time_ms=_integer(payload.get("time_ms"), "time_ms"),
        funding_rate=_decimal(payload.get("funding_rate"), "funding_rate"),
        premium=_decimal(payload.get("premium"), "premium"),
        source=record.source,
        received_at_ms=record.available_at_ms,
        schema_version=record.schema_version,
    )


def _level_tuple(value: object, field_name: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    output: list[dict[str, object]] = []
    for raw in value:
        level = _mapping(raw, "book level")
        output.append(
            {
                "px": _decimal(level.get("px"), "px"),
                "sz": _decimal(level.get("sz"), "sz"),
                "n": _integer(level.get("n"), "n"),
            }
        )
    return tuple(output)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    return tuple(_string(item, field_name) for item in value)


def replay_record_stream_event(record: ReplayRecord) -> StreamEvent:
    market = _normalized_event(record)
    event_kind = record.event_kind
    if event_kind is None:
        raise ValueError("normalized replay event is missing event kind")
    if event_kind in {"market_snapshot", "funding_rate"}:
        raise ValueError("REST evidence must be decoded by its typed decoder")
    try:
        kind = StreamKind(event_kind)
    except ValueError as exc:
        raise ValueError(f"unsupported stream event kind: {event_kind}") from exc
    payload = _mapping(record.payload, "stream event payload")
    normalized: dict[str, object]
    if kind is StreamKind.ALL_MIDS:
        normalized = {"mid_px": _decimal(payload.get("mid_px"), "mid_px")}
    elif kind is StreamKind.ACTIVE_ASSET_CTX:
        normalized = {
            "mark_px": _decimal(payload.get("mark_px"), "mark_px"),
            "mid_px": _optional_decimal(payload.get("mid_px"), "mid_px"),
            "oracle_px": _decimal(payload.get("oracle_px"), "oracle_px"),
            "funding": _decimal(payload.get("funding"), "funding"),
            "open_interest": _decimal(payload.get("open_interest"), "open_interest"),
        }
    elif kind is StreamKind.L2_BOOK:
        normalized = {
            "bids": _level_tuple(payload.get("bids"), "bids"),
            "asks": _level_tuple(payload.get("asks"), "asks"),
        }
    elif kind is StreamKind.TRADE:
        normalized = {
            "side": _string(payload.get("side"), "side"),
            "price": _decimal(payload.get("price"), "price"),
            "size": _decimal(payload.get("size"), "size"),
            "hash": _string(payload.get("hash"), "hash"),
            "tid": _integer(payload.get("tid"), "tid"),
            "users": _string_tuple(payload.get("users"), "users"),
        }
    else:
        normalized = {
            "start_ms": _integer(payload.get("start_ms"), "start_ms"),
            "end_ms": _integer(payload.get("end_ms"), "end_ms"),
            "interval": _string(payload.get("interval"), "interval"),
            "open_px": _decimal(payload.get("open_px"), "open_px"),
            "high_px": _decimal(payload.get("high_px"), "high_px"),
            "low_px": _decimal(payload.get("low_px"), "low_px"),
            "close_px": _decimal(payload.get("close_px"), "close_px"),
            "volume": _decimal(payload.get("volume"), "volume"),
            "trade_count": _integer(payload.get("trade_count"), "trade_count"),
        }
    return StreamEvent(
        kind=kind,
        market=market,
        exchange_time_ms=record.exchange_time_ms,
        receive_time=_receive_time(record),
        schema_version=record.schema_version,
        source=record.source,
        event_key=_string(record.event_key, "event_key"),
        payload=normalized,
    )


class RecordedStateBook:
    def __init__(self, *, microstructure_window_ms: int) -> None:
        if microstructure_window_ms <= 0:
            raise ValueError("microstructure_window_ms must be positive")
        self.microstructure_window_ms = microstructure_window_ms
        self._states: dict[str, RecordedMarketState] = {}

    def state(self, market: MarketId) -> RecordedMarketState:
        key = market.canonical
        state = self._states.get(key)
        if state is None:
            state = RecordedMarketState(market=market)
            self._states[key] = state
        return state

    def _prune_micro_events(self, state: RecordedMarketState, now_ms: int) -> None:
        cutoff_ms = max(0, now_ms - self.microstructure_window_ms)
        retained = sorted(
            (
                event
                for event in state.micro_events
                if int(event.receive_time.timestamp() * 1000) >= cutoff_ms
            ),
            key=lambda event: (
                event.receive_time,
                event.kind.value,
                event.event_key,
            ),
        )
        state.micro_events = deque(retained)

    def _apply_candle(self, state: RecordedMarketState, record: ReplayRecord) -> None:
        candle = replay_record_candle(record)
        if candle.interval == "5m":
            candles = state.candles_5m
            availability = state._candle_5m_available_at
        elif candle.interval == "15m":
            candles = state.candles_15m
            availability = state._candle_15m_available_at
        else:
            return
        previous_available = availability.get(candle.start_ms)
        if previous_available is None or record.available_at_ms >= previous_available:
            candles[candle.start_ms] = candle
            availability[candle.start_ms] = record.available_at_ms

    def apply(self, record: ReplayRecord, now_ms: int) -> None:
        if now_ms < record.available_at_ms:
            raise ValueError("future evidence cannot be applied before its availability time")
        if record.record_kind is SourceRecordKind.DATA_GAP:
            return
        if record.market is None or record.event_kind is None:
            raise ValueError("normalized replay event must include market and event kind")
        market = _market(record.market)
        state = self.state(market)

        if record.event_kind == "market_snapshot":
            snapshot = replay_record_market_snapshot(record)
            if (
                state._snapshot_available_at_ms is None
                or record.available_at_ms >= state._snapshot_available_at_ms
            ):
                if state.latest_snapshot is not None:
                    state.previous_snapshot = state.latest_snapshot
                state.latest_snapshot = snapshot
                state._snapshot_available_at_ms = record.available_at_ms
        elif record.event_kind == "funding_rate":
            rate = replay_record_funding_rate(record)
            previous_available = state._funding_available_at.get(rate.time_ms)
            if previous_available is None or record.available_at_ms >= previous_available:
                state.funding_by_boundary[rate.time_ms] = rate
                state._funding_available_at[rate.time_ms] = record.available_at_ms
        elif record.event_kind == StreamKind.CANDLE.value:
            self._apply_candle(state, record)
        else:
            event = replay_record_stream_event(record)
            if event.kind is StreamKind.ACTIVE_ASSET_CTX:
                if (
                    state._asset_ctx_available_at_ms is None
                    or record.available_at_ms >= state._asset_ctx_available_at_ms
                ):
                    state.latest_asset_ctx = event
                    state._asset_ctx_available_at_ms = record.available_at_ms
            elif event.kind is StreamKind.L2_BOOK:
                if (
                    state._book_available_at_ms is None
                    or record.available_at_ms >= state._book_available_at_ms
                ):
                    state.latest_book = event
                    state._book_available_at_ms = record.available_at_ms
                state.micro_events.append(event)
            elif event.kind is StreamKind.TRADE:
                state.micro_events.append(event)

        self._prune_micro_events(state, now_ms)
