from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind

SOURCE = "hyperliquid-mainnet-ws"
SCHEMA_VERSION = 1
PUBLIC_TYPES = frozenset({"allMids", "l2Book", "trades", "candle"})


class WsProtocolError(ValueError):
    pass


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise WsProtocolError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WsProtocolError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        raise WsProtocolError(f"{field} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise WsProtocolError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise WsProtocolError(f"{field} must be finite")
    return result


def _market(wire: object) -> MarketId:
    name = _string(wire, "coin")
    if ":" in name:
        dex = name.split(":", 1)[0]
        return MarketId.from_wire_name(dex, name)
    return MarketId.from_wire_name("", name)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise WsProtocolError(f"{field} must be an object")
    return value


def _validated_subscription(subscription: Mapping[str, object]) -> str:
    kind = subscription.get("type")
    if not isinstance(kind, str) or kind not in PUBLIC_TYPES:
        raise WsProtocolError("Phase 3 accepts only a public subscription")
    if kind == "allMids":
        extra = set(subscription) - {"type", "dex"}
        if extra:
            raise WsProtocolError("allMids has unsupported fields")
        dex = subscription.get("dex")
        if dex is not None and (not isinstance(dex, str) or not dex):
            raise WsProtocolError("allMids dex must be a non-empty string")
        return kind if dex is None else f"{kind}:{dex}"
    coin = _string(subscription.get("coin"), "coin")
    if kind == "candle":
        interval = _string(subscription.get("interval"), "interval")
        if set(subscription) != {"type", "coin", "interval"}:
            raise WsProtocolError("candle has unsupported fields")
        return f"candle:{coin}:{interval}"
    if set(subscription) != {"type", "coin"}:
        raise WsProtocolError(f"{kind} has unsupported fields")
    return f"{kind}:{coin}"


def subscription_id(subscription: Mapping[str, object]) -> str:
    return _validated_subscription(subscription)


def subscribe_message(subscription: Mapping[str, object]) -> dict[str, object]:
    _validated_subscription(subscription)
    return {"method": "subscribe", "subscription": dict(subscription)}


def unsubscribe_message(subscription: Mapping[str, object]) -> dict[str, object]:
    _validated_subscription(subscription)
    return {"method": "unsubscribe", "subscription": dict(subscription)}


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def normalize_ws_message(raw: object, *, receive_time: datetime) -> list[StreamEvent]:
    message = _mapping(raw, "message")
    channel = _string(message.get("channel"), "channel")
    if channel in {"pong", "subscriptionResponse"}:
        return []
    if channel == "allMids":
        mid_data = _mapping(message.get("data"), "data")
        mids = _mapping(mid_data.get("mids"), "mids")
        mid_events: list[StreamEvent] = []
        for wire, value in mids.items():
            market = _market(wire)
            mid = _decimal(value, "mid")
            mid_events.append(
                StreamEvent(
                    StreamKind.ALL_MIDS,
                    market,
                    None,
                    receive_time,
                    SCHEMA_VERSION,
                    SOURCE,
                    f"allMids:{market.canonical}:{mid}",
                    {"mid_px": mid},
                )
            )
        return mid_events
    if channel == "l2Book":
        book_data = _mapping(message.get("data"), "data")
        market = _market(book_data.get("coin"))
        time_ms = _integer(book_data.get("time"), "time")
        levels = book_data.get("levels")
        if (
            not isinstance(levels, list)
            or len(levels) != 2
            or not all(isinstance(side, list) for side in levels)
        ):
            raise WsProtocolError("levels must contain bid and ask arrays")
        normalized: list[tuple[dict[str, object], ...]] = []
        for side in levels:
            side_rows: list[dict[str, object]] = []
            for raw_level in side:
                level = _mapping(raw_level, "level")
                side_rows.append(
                    {
                        "px": _decimal(level.get("px"), "px"),
                        "sz": _decimal(level.get("sz"), "sz"),
                        "n": _integer(level.get("n"), "n"),
                    }
                )
            normalized.append(tuple(side_rows))
        payload: dict[str, object] = {"bids": normalized[0], "asks": normalized[1]}
        return [
            StreamEvent(
                StreamKind.L2_BOOK,
                market,
                time_ms,
                receive_time,
                SCHEMA_VERSION,
                SOURCE,
                f"l2Book:{market.canonical}:{time_ms}:{_digest(payload)}",
                payload,
            )
        ]
    if channel == "trades":
        trade_rows = message.get("data")
        if not isinstance(trade_rows, list):
            raise WsProtocolError("trades data must be an array")
        trade_events: list[StreamEvent] = []
        for raw_trade in trade_rows:
            trade = _mapping(raw_trade, "trade")
            market = _market(trade.get("coin"))
            time_ms = _integer(trade.get("time"), "time")
            tid = _integer(trade.get("tid"), "tid")
            users_raw = trade.get("users")
            valid_users = isinstance(users_raw, list) and all(
                isinstance(item, str) for item in users_raw
            )
            if not valid_users:
                raise WsProtocolError("users must be a string array")
            payload = {
                "side": _string(trade.get("side"), "side"),
                "price": _decimal(trade.get("px"), "px"),
                "size": _decimal(trade.get("sz"), "sz"),
                "hash": _string(trade.get("hash"), "hash"),
                "tid": tid,
                "users": tuple(users_raw),
            }
            trade_events.append(
                StreamEvent(
                    StreamKind.TRADE,
                    market,
                    time_ms,
                    receive_time,
                    SCHEMA_VERSION,
                    SOURCE,
                    f"trades:{market.canonical}:{time_ms}:{tid}",
                    payload,
                )
            )
        return trade_events
    if channel == "candle":
        candle_data = _mapping(message.get("data"), "data")
        market = _market(candle_data.get("s"))
        start = _integer(candle_data.get("t"), "t")
        payload = {
            "start_ms": start,
            "end_ms": _integer(candle_data.get("T"), "T"),
            "interval": _string(candle_data.get("i"), "i"),
            "open_px": _decimal(candle_data.get("o"), "o"),
            "close_px": _decimal(candle_data.get("c"), "c"),
            "high_px": _decimal(candle_data.get("h"), "h"),
            "low_px": _decimal(candle_data.get("l"), "l"),
            "volume": _decimal(candle_data.get("v"), "v"),
            "trade_count": _integer(candle_data.get("n"), "n"),
        }
        return [
            StreamEvent(
                StreamKind.CANDLE,
                market,
                start,
                receive_time,
                SCHEMA_VERSION,
                SOURCE,
                f"candle:{market.canonical}:{payload['interval']}:{start}:{_digest(payload)}",
                payload,
            )
        ]
    raise WsProtocolError(f"unsupported channel: {channel}")
