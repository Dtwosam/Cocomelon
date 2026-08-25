from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from cocomelon.domain.features import FeatureSnapshot, OpportunityRank
from cocomelon.domain.market import Candle, FundingRate, MarketId, PerpMarketSnapshot
from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.evidence.contracts import (
    EvidenceRecordingConfig,
    EvidenceRecordingSession,
    SelectedEvidenceMarket,
)
from cocomelon.evidence.redundant_stream import RedundantStreamMux
from cocomelon.features.assemble import assemble_feature_snapshot
from cocomelon.features.broad import calculate_broad_features
from cocomelon.hyperliquid.client import INTERVAL_MS
from cocomelon.hyperliquid.normalize import normalize_candles, normalize_funding_history
from cocomelon.hyperliquid.registry import MarketRegistry
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager
from cocomelon.hyperliquid.ws_supervisor import (
    ClockMs,
    ConnectionFactory,
    Sleep,
    UtcNow,
    WebSocketSupervisor,
)
from cocomelon.scanner.eligibility import (
    EligibilityConfig,
    derive_eligibility_thresholds,
    evaluate_eligibility,
)
from cocomelon.scanner.ranker import rank_opportunities
from cocomelon.util.time import utc_now_ms

if TYPE_CHECKING:
    from cocomelon.recorder import DurableRecorder

FUNDING_BOOTSTRAP_LOOKBACK_MS = 24 * 60 * 60 * 1_000
SCORE_SCALE = Decimal("100")
RECORDING_SESSION_FILENAME = "recording-session.json"
REST_SOURCE = "hyperliquid-mainnet-info"


class EvidenceInfoReader(Protocol):
    def perp_dexs(self) -> object: ...

    def meta_and_asset_ctxs(self, dex: str = "") -> object: ...

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object: ...

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class RecordingBootstrap:
    session: EvidenceRecordingSession
    snapshots: tuple[PerpMarketSnapshot, ...]
    candles: tuple[Candle, ...]
    funding_rates: tuple[FundingRate, ...]
    subscriptions: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class RecordingRunSummary:
    session_id: str
    selected_markets: tuple[str, ...]
    duration_seconds: int
    event_count: int
    gap_count: int
    reconnect_count: int
    duplicate_count: int
    anomaly_count: int
    root: str
    network_access: bool = True
    live_orders: bool = False


@dataclass(frozen=True, slots=True)
class RecordedPublicEvent:
    kind: str
    market: MarketId
    source: str
    exchange_time_ms: int | None
    receive_time: datetime
    schema_version: int
    event_key: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("kind must not be empty")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        if self.exchange_time_ms is not None and self.exchange_time_ms < 0:
            raise ValueError("exchange_time_ms must be non-negative")
        if self.receive_time.tzinfo is None or self.receive_time.utcoffset() is None:
            raise ValueError("receive_time must be timezone-aware")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if not self.event_key.strip():
            raise ValueError("event_key must not be empty")


def _received_at(received_at_ms: int) -> datetime:
    if received_at_ms < 0:
        raise ValueError("received_at_ms must be non-negative")
    return datetime.fromtimestamp(received_at_ms / 1000, tz=UTC)


def _canonical_value(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical mapping keys must be strings")
            normalized[key] = _canonical_value(item)
        return normalized
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def _payload_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _canonical_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _market_from_canonical(value: str) -> MarketId:
    if ":" not in value:
        return MarketId.from_wire_name("", value)
    dex = value.split(":", 1)[0]
    return MarketId.from_wire_name(dex, value)


def _session_payload(session: EvidenceRecordingSession) -> dict[str, object]:
    return {
        "schema_version": session.schema_version,
        "session_id": session.session_id,
        "started_at_ms": session.started_at_ms,
        "recorder_code_revision": session.recorder_code_revision,
        "selected": [
            {
                "market": item.market.canonical,
                "rank": item.rank,
                "feature_snapshot_id": item.feature_snapshot_id,
                "score": str(item.score),
            }
            for item in session.selected
        ],
        "recording_config_digest": session.recording_config_digest,
        "api_url": session.api_url,
        "ws_url": session.ws_url,
        "selection_policy_id": session.selection_policy_id,
    }


def write_recording_session(root: Path, session: EvidenceRecordingSession) -> None:
    root.mkdir(parents=True, exist_ok=True)
    existing = load_recording_session(root)
    if existing is not None:
        if existing != session:
            raise ValueError("recording session metadata conflicts with requested session")
        return
    if any(root.iterdir()):
        raise ValueError("recording session metadata missing for populated root")

    payload = _session_payload(session)
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    target = root / RECORDING_SESSION_FILENAME
    temporary = root / f"{RECORDING_SESSION_FILENAME}.tmp"
    with temporary.open("wb") as handle:
        written = handle.write(encoded)
        if written != len(encoded):
            raise OSError(f"short recording session write: {written} of {len(encoded)} bytes")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def load_recording_session(root: Path) -> EvidenceRecordingSession | None:
    path = root / RECORDING_SESSION_FILENAME
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("recording session metadata must be a file")
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("recording session metadata must contain valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("recording session metadata must be an object")
    selected_raw = raw.get("selected")
    if not isinstance(selected_raw, list) or not selected_raw:
        raise ValueError("recording session selected must be a non-empty array")
    selected: list[SelectedEvidenceMarket] = []
    try:
        for item in selected_raw:
            if not isinstance(item, dict):
                raise ValueError("recording session selected entry must be an object")
            selected.append(
                SelectedEvidenceMarket(
                    market=_market_from_canonical(str(item["market"])),
                    rank=int(item["rank"]),
                    feature_snapshot_id=str(item["feature_snapshot_id"]),
                    score=Decimal(str(item["score"])),
                )
            )
        session = EvidenceRecordingSession(
            started_at_ms=int(raw["started_at_ms"]),
            recorder_code_revision=str(raw["recorder_code_revision"]),
            selected=tuple(selected),
            recording_config_digest=str(raw["recording_config_digest"]),
            api_url=str(raw["api_url"]),
            ws_url=str(raw["ws_url"]),
            selection_policy_id=str(raw["selection_policy_id"]),
            schema_version=int(raw["schema_version"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("recording session metadata is invalid") from exc
    stored_id = raw.get("session_id")
    if not isinstance(stored_id, str) or stored_id != session.session_id:
        raise ValueError("recording session metadata session_id mismatch")
    return session


def verify_recording_resume(root: Path, requested: EvidenceRecordingSession) -> None:
    if not root.exists():
        return
    existing = load_recording_session(root)
    if existing is None:
        if any(root.iterdir()):
            raise ValueError("recording session metadata missing for populated root")
        return
    if existing != requested or existing.session_id != requested.session_id:
        raise ValueError("recording session does not match requested session")


def _startup_ranks(
    markets: Mapping[str, PerpMarketSnapshot],
    *,
    as_of_ms: int,
) -> tuple[dict[str, FeatureSnapshot], tuple[OpportunityRank, ...]]:
    current_by_market: dict[str, PerpMarketSnapshot] = {}
    features: list[FeatureSnapshot] = []
    for current in sorted(markets.values(), key=lambda item: item.meta.market.canonical):
        market = current.meta.market
        key = market.canonical
        if key in current_by_market:
            raise ValueError(f"duplicate current market snapshot: {key}")
        if current.context.market != market or current.received_at_ms > as_of_ms:
            continue
        current_by_market[key] = current
        broad = calculate_broad_features(current, None, as_of_ms=as_of_ms)
        features.append(
            assemble_feature_snapshot(
                market,
                broad,
                as_of_ms=as_of_ms,
                provenance=(current.source,),
            )
        )

    if not features:
        return {}, ()
    feature_tuple = tuple(features)
    eligibility_config = EligibilityConfig()
    thresholds = derive_eligibility_thresholds(feature_tuple, eligibility_config)
    decisions = tuple(
        evaluate_eligibility(
            current_by_market[feature.market.canonical],
            feature,
            thresholds,
            eligibility_config,
        )
        for feature in feature_tuple
    )
    ranks = rank_opportunities(feature_tuple, decisions, mode="coarse")
    return {item.market.canonical: item for item in feature_tuple}, ranks


def _warmup_candles(
    reader: EvidenceInfoReader,
    market: MarketId,
    config: EvidenceRecordingConfig,
    *,
    end_ms: int,
    now_ms: Callable[[], int],
) -> tuple[Candle, ...]:
    output: list[Candle] = []
    for interval, bar_count in (
        ("5m", config.warmup_5m_bars),
        ("15m", config.warmup_15m_bars),
    ):
        interval_ms = INTERVAL_MS[interval]
        start_ms = max(0, end_ms - interval_ms * (bar_count + 2))
        raw = reader.candles(
            market,
            interval,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        received_at_ms = now_ms()
        output.extend(
            normalize_candles(
                market,
                raw,
                received_at_ms=received_at_ms,
            )
        )
    return tuple(output)


def _recent_funding(
    reader: EvidenceInfoReader,
    market: MarketId,
    *,
    end_ms: int,
    now_ms: Callable[[], int],
) -> tuple[FundingRate, ...]:
    raw = reader.funding_history(
        market,
        start_ms=max(0, end_ms - FUNDING_BOOTSTRAP_LOOKBACK_MS),
        end_ms=end_ms,
    )
    received_at_ms = now_ms()
    return normalize_funding_history(
        market,
        raw,
        received_at_ms=received_at_ms,
    )


def build_recording_bootstrap(
    reader: EvidenceInfoReader,
    config: EvidenceRecordingConfig,
    *,
    now_ms: Callable[[], int],
    code_revision: str,
) -> RecordingBootstrap:
    started_at_ms = now_ms()
    registry = MarketRegistry(reader, now_ms=now_ms).refresh()
    feature_map, ranks = _startup_ranks(
        registry.markets,
        as_of_ms=registry.received_at_ms,
    )

    native_ranks = tuple(rank for rank in ranks if rank.market.dex == "")
    selected_ranks = native_ranks[: config.deep_limit]
    if not selected_ranks:
        raise ValueError("startup scan produced no rankable native markets")

    selected = tuple(
        SelectedEvidenceMarket(
            market=rank.market,
            rank=rank.ordinal,
            feature_snapshot_id=feature_map[rank.market.canonical].snapshot_id,
            score=rank.score * SCORE_SCALE,
        )
        for rank in selected_ranks
    )
    session = EvidenceRecordingSession(
        started_at_ms=started_at_ms,
        recorder_code_revision=code_revision,
        selected=selected,
        recording_config_digest=config.config_digest,
        api_url=config.api_url,
        ws_url=config.ws_url,
        selection_policy_id=config.selection_policy_id,
    )

    selected_markets = tuple(item.market for item in session.selected)
    selected_snapshots = tuple(
        registry.markets[market.canonical] for market in selected_markets
    )
    candles: list[Candle] = []
    funding_rates: list[FundingRate] = []
    for market in selected_markets:
        candles.extend(
            _warmup_candles(
                reader,
                market,
                config,
                end_ms=started_at_ms,
                now_ms=now_ms,
            )
        )
        funding_rates.extend(
            _recent_funding(
                reader,
                market,
                end_ms=started_at_ms,
                now_ms=now_ms,
            )
        )

    plan = DeepWatchlistManager(candle_intervals=config.candle_intervals).reconcile(
        selected_markets
    )
    return RecordingBootstrap(
        session=session,
        snapshots=selected_snapshots,
        candles=tuple(candles),
        funding_rates=tuple(funding_rates),
        subscriptions=plan.subscribe,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def run_bounded_recording(
    *,
    bootstrap: RecordingBootstrap,
    reader: EvidenceInfoReader,
    connection_factory: ConnectionFactory,
    recorder: DurableRecorder,
    config: EvidenceRecordingConfig,
    sleep: Sleep = asyncio.sleep,
    clock_ms: ClockMs = utc_now_ms,
    utcnow: UtcNow = _utcnow,
) -> RecordingRunSummary:
    if bootstrap.session.recording_config_digest != config.config_digest:
        raise ValueError("recording bootstrap config does not match requested config")
    verify_recording_resume(recorder.root, bootstrap.session)
    write_recording_session(recorder.root, bootstrap.session)

    event_count = 0
    gap_count = 0
    funding_seen: set[tuple[str, int]] = set()
    selected_markets = tuple(item.market for item in bootstrap.session.selected)

    for snapshot in bootstrap.snapshots:
        recorder.append_market_snapshot(snapshot)
        event_count += 1
    for candle in bootstrap.candles:
        recorder.append_candle(candle)
        event_count += 1
    for rate in bootstrap.funding_rates:
        key = (rate.market.canonical, rate.time_ms)
        if key in funding_seen:
            continue
        recorder.append_funding_rate(rate)
        funding_seen.add(key)
        event_count += 1

    async def event_sink(event: StreamEvent) -> None:
        nonlocal event_count
        recorder.append_event(event)
        event_count += 1

    async def gap_sink(gap: DataGap) -> None:
        nonlocal gap_count
        recorder.append_gap(gap)
        gap_count += 1

    mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)

    async def record_rest_gap(stream_id: str, reason: str) -> None:
        now = clock_ms()
        await gap_sink(
            DataGap(
                stream_id=stream_id,
                started_ms=now,
                ended_ms=now,
                reason=reason,
                source=REST_SOURCE,
            )
        )

    async def poll_context() -> None:
        nonlocal event_count
        while True:
            try:
                registry = MarketRegistry(reader, now_ms=clock_ms).refresh()
                for market in selected_markets:
                    snapshot = registry.markets.get(market.canonical)
                    if snapshot is None:
                        raise ValueError(
                            f"selected market missing from context poll: {market.canonical}"
                        )
                    recorder.append_market_snapshot(snapshot)
                    event_count += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await record_rest_gap(
                    "rest:market_snapshot",
                    f"poll_error:{type(exc).__name__}",
                )
            await sleep(float(config.context_poll_seconds))

    async def poll_funding() -> None:
        nonlocal event_count
        while True:
            for market in selected_markets:
                try:
                    end_ms = clock_ms()
                    raw = reader.funding_history(
                        market,
                        start_ms=max(0, end_ms - FUNDING_BOOTSTRAP_LOOKBACK_MS),
                        end_ms=end_ms,
                    )
                    received_at_ms = clock_ms()
                    rates = normalize_funding_history(
                        market,
                        raw,
                        received_at_ms=received_at_ms,
                    )
                    for rate in rates:
                        key = (rate.market.canonical, rate.time_ms)
                        if key in funding_seen:
                            continue
                        recorder.append_funding_rate(rate)
                        funding_seen.add(key)
                        event_count += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await record_rest_gap(
                        f"rest:funding_rate:{market.canonical}",
                        f"poll_error:{type(exc).__name__}",
                    )
            await sleep(float(config.funding_poll_seconds))

    supervisors: list[WebSocketSupervisor] = []
    for lane in range(2):
        async def lane_event_sink(event: StreamEvent, lane: int = lane) -> None:
            await mux.on_event(lane, event)

        async def lane_gap_sink(gap: DataGap, lane: int = lane) -> None:
            await mux.on_gap(lane, gap)

        supervisors.append(
            WebSocketSupervisor(
                connection_factory,
                bootstrap.subscriptions,
                event_sink=lane_event_sink,
                gap_sink=lane_gap_sink,
                clock_ms=clock_ms,
                utcnow=utcnow,
                sleep=sleep,
            )
        )

    tasks = tuple(
        asyncio.create_task(supervisor.run()) for supervisor in supervisors
    ) + (
        asyncio.create_task(poll_context()),
        asyncio.create_task(poll_funding()),
    )
    try:
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks),
                timeout=float(config.duration_seconds),
            )
        except TimeoutError:
            pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    health = tuple(supervisor.health for supervisor in supervisors)
    return RecordingRunSummary(
        session_id=bootstrap.session.session_id,
        selected_markets=tuple(item.market.canonical for item in bootstrap.session.selected),
        duration_seconds=config.duration_seconds,
        event_count=event_count,
        gap_count=gap_count,
        reconnect_count=sum(item.reconnect_count for item in health),
        duplicate_count=0,
        anomaly_count=0,
        root=str(recorder.root),
    )


def market_snapshot_record_event(snapshot: PerpMarketSnapshot) -> RecordedPublicEvent:
    market = snapshot.meta.market
    if snapshot.context.market != market:
        raise ValueError("market snapshot metadata and context market must match")
    payload: dict[str, object] = {
        "meta": {
            "wire_name": snapshot.meta.wire_name,
            "sz_decimals": snapshot.meta.sz_decimals,
            "max_leverage": snapshot.meta.max_leverage,
            "margin_table_id": snapshot.meta.margin_table_id,
            "only_isolated": snapshot.meta.only_isolated,
            "is_delisted": snapshot.meta.is_delisted,
            "margin_mode": snapshot.meta.margin_mode,
        },
        "context": {
            "mark_px": snapshot.context.mark_px,
            "mid_px": snapshot.context.mid_px,
            "oracle_px": snapshot.context.oracle_px,
            "funding": snapshot.context.funding,
            "open_interest": snapshot.context.open_interest,
            "day_ntl_vlm": snapshot.context.day_ntl_vlm,
            "premium": snapshot.context.premium,
            "prev_day_px": snapshot.context.prev_day_px,
        },
    }
    digest = _payload_digest(payload)
    return RecordedPublicEvent(
        kind="market_snapshot",
        market=market,
        source=snapshot.source,
        exchange_time_ms=None,
        receive_time=_received_at(snapshot.received_at_ms),
        schema_version=snapshot.schema_version,
        event_key=(
            f"rest:market_snapshot:{market.canonical}:{snapshot.received_at_ms}:{digest}"
        ),
        payload=payload,
    )


def funding_rate_record_event(rate: FundingRate) -> RecordedPublicEvent:
    payload: dict[str, object] = {
        "time_ms": rate.time_ms,
        "funding_rate": rate.funding_rate,
        "premium": rate.premium,
    }
    digest = _payload_digest(payload)
    return RecordedPublicEvent(
        kind="funding_rate",
        market=rate.market,
        source=rate.source,
        exchange_time_ms=rate.time_ms,
        receive_time=_received_at(rate.received_at_ms),
        schema_version=rate.schema_version,
        event_key=(
            f"rest:funding_rate:{rate.market.canonical}:{rate.time_ms}:"
            f"{rate.received_at_ms}:{digest}"
        ),
        payload=payload,
    )


def candle_record_event(candle: Candle) -> RecordedPublicEvent:
    payload: dict[str, object] = {
        "start_ms": candle.start_ms,
        "end_ms": candle.end_ms,
        "interval": candle.interval,
        "open_px": candle.open_px,
        "high_px": candle.high_px,
        "low_px": candle.low_px,
        "close_px": candle.close_px,
        "volume": candle.volume,
        "trade_count": candle.trade_count,
    }
    digest = _payload_digest(payload)
    return RecordedPublicEvent(
        kind="candle",
        market=candle.market,
        source=candle.source,
        exchange_time_ms=candle.start_ms,
        receive_time=_received_at(candle.received_at_ms),
        schema_version=candle.schema_version,
        event_key=(
            f"rest:candle:{candle.market.canonical}:{candle.interval}:{candle.start_ms}:"
            f"{candle.received_at_ms}:{digest}"
        ),
        payload=payload,
    )
