from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import cast

from cocomelon.domain.market import (
    Candle,
    FundingRate,
    MarketId,
    PerpDex,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)

SOURCE = "hyperliquid-mainnet-info"
SCHEMA_VERSION = 1


def _as_dict(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _as_list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return cast(list[object], value)


def _required_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_str(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value


def _required_int(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _optional_int(data: dict[str, object], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer or null")
    return value


def _bool(data: dict[str, object], key: str, default: bool = False) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _decimal(data: dict[str, object], key: str, *, optional: bool = False) -> Decimal | None:
    value = data.get(key)
    if value is None:
        if optional:
            return None
        raise ValueError(f"{key} must not be null")
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError(f"{key} must be numeric")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{key} must be numeric") from exc


def normalize_perp_dexs(raw: object) -> tuple[PerpDex, ...]:
    values = _as_list(raw, "perpDexs")
    dexes: list[PerpDex] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        if value is None:
            if index != 0:
                raise ValueError("only perpDexs[0] may be null")
            continue
        data = _as_dict(value, f"perpDexs[{index}]")
        name = _required_str(data, "name")
        if name in seen:
            raise ValueError(f"duplicate perp dex name: {name}")
        seen.add(name)
        dexes.append(
            PerpDex(
                name=name,
                full_name=_required_str(data, "fullName"),
                deployer=_required_str(data, "deployer"),
                oracle_updater=_optional_str(data, "oracleUpdater"),
                fee_recipient=_optional_str(data, "feeRecipient"),
            )
        )
    return tuple(dexes)


def normalize_meta_and_asset_ctxs(
    dex: str,
    raw: object,
    *,
    received_at_ms: int,
) -> tuple[PerpMarketSnapshot, ...]:
    response = _as_list(raw, "metaAndAssetCtxs")
    if len(response) != 2:
        raise ValueError("metaAndAssetCtxs response must contain metadata and contexts")
    meta = _as_dict(response[0], "metaAndAssetCtxs[0]")
    universe = _as_list(meta.get("universe"), "universe")
    contexts = _as_list(response[1], "asset contexts")
    if len(universe) != len(contexts):
        raise ValueError("universe and asset context length must match")

    snapshots: list[PerpMarketSnapshot] = []
    seen: set[str] = set()
    for index, (meta_value, context_value) in enumerate(zip(universe, contexts, strict=True)):
        meta_item = _as_dict(meta_value, f"universe[{index}]")
        context_item = _as_dict(context_value, f"assetContexts[{index}]")
        wire_name = _required_str(meta_item, "name")
        market = MarketId.from_wire_name(dex, wire_name)
        if market.canonical in seen:
            raise ValueError(f"duplicate canonical market: {market.canonical}")
        seen.add(market.canonical)

        market_meta = PerpMarketMeta(
            market=market,
            wire_name=wire_name,
            sz_decimals=_required_int(meta_item, "szDecimals"),
            max_leverage=_required_int(meta_item, "maxLeverage"),
            margin_table_id=_optional_int(meta_item, "marginTableId"),
            only_isolated=_bool(meta_item, "onlyIsolated"),
            is_delisted=_bool(meta_item, "isDelisted"),
            margin_mode=_optional_str(meta_item, "marginMode"),
        )
        market_context = PerpMarketContext(
            market=market,
            mark_px=_decimal(context_item, "markPx", optional=True),
            mid_px=_decimal(context_item, "midPx", optional=True),
            oracle_px=_decimal(context_item, "oraclePx", optional=True),
            funding=cast(Decimal, _decimal(context_item, "funding")),
            open_interest=cast(Decimal, _decimal(context_item, "openInterest")),
            day_ntl_vlm=cast(Decimal, _decimal(context_item, "dayNtlVlm")),
            premium=_decimal(context_item, "premium", optional=True),
            prev_day_px=cast(Decimal, _decimal(context_item, "prevDayPx")),
        )
        snapshots.append(
            PerpMarketSnapshot(
                meta=market_meta,
                context=market_context,
                source=SOURCE,
                received_at_ms=received_at_ms,
                schema_version=SCHEMA_VERSION,
            )
        )
    return tuple(snapshots)


def normalize_candles(
    market: MarketId,
    raw: object,
    *,
    received_at_ms: int,
) -> tuple[Candle, ...]:
    values = _as_list(raw, "candleSnapshot")
    candles: list[Candle] = []
    previous_start: int | None = None
    for index, value in enumerate(values):
        item = _as_dict(value, f"candleSnapshot[{index}]")
        wire_name = _required_str(item, "s")
        if wire_name != market.wire_name:
            raise ValueError(
                f"candle coin {wire_name!r} does not match requested market {market.wire_name!r}"
            )
        start_ms = _required_int(item, "t")
        end_ms = _required_int(item, "T")
        if end_ms < start_ms:
            raise ValueError("candle end timestamp must be >= start timestamp")
        if previous_start is not None and start_ms <= previous_start:
            raise ValueError("candle timestamps must be strictly increasing")
        previous_start = start_ms
        candles.append(
            Candle(
                market=market,
                interval=_required_str(item, "i"),
                start_ms=start_ms,
                end_ms=end_ms,
                open_px=cast(Decimal, _decimal(item, "o")),
                high_px=cast(Decimal, _decimal(item, "h")),
                low_px=cast(Decimal, _decimal(item, "l")),
                close_px=cast(Decimal, _decimal(item, "c")),
                volume=cast(Decimal, _decimal(item, "v")),
                trade_count=_required_int(item, "n"),
                source=SOURCE,
                received_at_ms=received_at_ms,
                schema_version=SCHEMA_VERSION,
            )
        )
    return tuple(candles)


def normalize_funding_history(
    market: MarketId,
    raw: object,
    *,
    received_at_ms: int,
) -> tuple[FundingRate, ...]:
    values = _as_list(raw, "fundingHistory")
    rates: list[FundingRate] = []
    previous_time: int | None = None
    for index, value in enumerate(values):
        item = _as_dict(value, f"fundingHistory[{index}]")
        wire_name = _required_str(item, "coin")
        if wire_name != market.wire_name:
            raise ValueError(
                f"funding coin {wire_name!r} does not match requested market {market.wire_name!r}"
            )
        time_ms = _required_int(item, "time")
        if previous_time is not None and time_ms <= previous_time:
            raise ValueError("funding timestamps must be strictly increasing")
        previous_time = time_ms
        rates.append(
            FundingRate(
                market=market,
                time_ms=time_ms,
                funding_rate=cast(Decimal, _decimal(item, "fundingRate")),
                premium=cast(Decimal, _decimal(item, "premium")),
                source=SOURCE,
                received_at_ms=received_at_ms,
                schema_version=SCHEMA_VERSION,
            )
        )
    return tuple(rates)
