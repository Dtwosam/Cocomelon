"""Original public receipts for the one frozen volatility-budget PAPER experiment.

This adapter performs no network access and grants no entry authority. Its caller
must archive each complete receipt durably before it is released, account for all
outbound-IP consumers, and supervise protection/recovery. Historical warmup keeps
its actual receipt clock. Replaying an independently verified archive never
changes that clock or manufactures a previously available observation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from cocomelon.domain.execution import InstrumentExecutionSpec
from cocomelon.domain.features import EligibilityDecision
from cocomelon.domain.market import FundingRate, MarketId, PerpMarketSnapshot
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.funding import funding_boundary_for_record_time
from cocomelon.hyperliquid.normalize import (
    normalize_candles,
    normalize_funding_history,
    normalize_meta_and_asset_ctxs,
)
from cocomelon.hyperliquid.ws_protocol import normalize_ws_message
from cocomelon.research.volatility_budget import (
    DAY_MS,
    EIGHT_HOURS_MS,
    Native8hBar,
    VolatilityBudgetWindow,
)

MARKETS = tuple(MarketId("", coin) for coin in ("BTC", "ETH", "SOL", "BNB"))
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
Archive = Callable[[dict[str, object]], None]


def _clock(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("receipt clocks must be nonnegative integers")
    return value


def _market(market: MarketId) -> None:
    if market not in MARKETS:
        raise ValueError("unsupported market for frozen volatility experiment")


def _positive(value: Decimal | None) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value > 0


class VolatilitySource:
    """Parse archived native source; the archive callback must fail on custody loss.

    ``restore`` accepts only records already authenticated by the caller's
    independent custody verification. It is not itself an archive authenticator.
    A source gap remains recorded permanently even after fresh data resumes.
    """

    def __init__(self, archive: Archive) -> None:
        self._archive = archive
        self._last_received_ms = -1
        self._bars: dict[MarketId, dict[int, Native8hBar]] = {m: {} for m in MARKETS}
        self._books: dict[MarketId, StreamEvent] = {}
        self._marks: dict[MarketId, StreamEvent] = {}
        self._snapshots: dict[MarketId, PerpMarketSnapshot] = {}
        self._funding: dict[tuple[MarketId, int], FundingRate] = {}
        self._gaps: list[dict[str, object]] = []
        self._restoring = False
        self._rejections: list[dict[str, object]] = []

    @property
    def rejections(self) -> tuple[dict[str, object], ...]:
        """Original malformed rows recovered from custody; permanently unqualified."""
        return tuple(dict(row) for row in self._rejections)

    @property
    def books(self) -> dict[MarketId, StreamEvent]:
        return dict(self._books)

    @property
    def marks(self) -> dict[MarketId, StreamEvent]:
        return dict(self._marks)

    @property
    def snapshots(self) -> dict[MarketId, PerpMarketSnapshot]:
        return dict(self._snapshots)

    @property
    def funding_rates(self) -> dict[tuple[MarketId, int], FundingRate]:
        return dict(self._funding)

    @property
    def gaps(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(gap) for gap in self._gaps)

    def _receipt(
        self,
        kind: str,
        raw: object,
        received_at_ms: int,
        market: MarketId | None = None,
        request_started_ms: int | None = None,
    ) -> None:
        now = received_at_ms
        record: dict[str, object] = {
            "kind": kind,
            "source": "hyperliquid-mainnet-ws" if kind == "ws" else "hyperliquid-mainnet-info",
            "schema_version": 1,
            "received_at_ms": now,
            "request_started_ms": request_started_ms,
            "market": None if market is None else market.canonical,
            "raw": raw,
        }
        # Validate serializability without silently stringifying malformed values.
        json.dumps(record, allow_nan=False)
        if not self._restoring:
            self._archive(record)
        # Bad real clocks are original adverse evidence, so archive them before
        # rejecting release. Custody restore rejects their chronological defect.
        _clock(now)
        if now < self._last_received_ms:
            raise ValueError("receive clock regression")
        if request_started_ms is not None and _clock(request_started_ms) > now:
            raise ValueError("request starts after receipt")
        if market is not None:
            _market(market)
        self._last_received_ms = now

    def ingest_candles(
        self,
        market: MarketId,
        raw: object,
        *,
        received_at_ms: int,
        request_started_ms: int | None = None,
    ) -> tuple[Native8hBar, ...]:
        self._receipt("candles", raw, received_at_ms, market, request_started_ms)
        rows: list[Native8hBar] = []
        for c in normalize_candles(market, raw, received_at_ms=received_at_ms):
            if (
                c.interval != "8h"
                or c.start_ms % EIGHT_HOURS_MS
                or c.end_ms != c.start_ms + EIGHT_HOURS_MS - 1
            ):
                raise ValueError("invalid native8h candle grid")
            # An unfinished native candle is an authentic observation but cannot
            # become a closed daily input, even when replayed after its close.
            if c.end_ms + 1 > received_at_ms:
                continue
            if (
                not all(
                    _positive(v) for v in (c.open_px, c.high_px, c.low_px, c.close_px, c.volume)
                )
                or c.trade_count <= 0
                or not c.low_px
                <= min(c.open_px, c.close_px)
                <= max(c.open_px, c.close_px)
                <= c.high_px
            ):
                raise ValueError("invalid native8h candle")
            bar = Native8hBar(
                market,
                c.start_ms,
                c.end_ms,
                c.open_px,
                c.high_px,
                c.low_px,
                c.close_px,
                c.volume,
                c.trade_count,
                received_at_ms,
            )
            old = self._bars[market].get(c.start_ms)
            if old is not None and replace(bar, received_at_ms=old.received_at_ms) != old:
                raise ValueError("conflicting closed candle")
            rows.append(old or bar)
        # Admit the page atomically after validation, preserving first receipts.
        self._bars[market].update((row.open_time_ms, row) for row in rows)
        return tuple(rows)

    def ingest_meta(
        self,
        raw: object,
        *,
        received_at_ms: int,
        request_started_ms: int | None = None,
    ) -> tuple[StreamEvent, ...]:
        self._receipt("meta", raw, received_at_ms, request_started_ms=request_started_ms)
        snapshots = normalize_meta_and_asset_ctxs("", raw, received_at_ms=received_at_ms)
        selected = {s.meta.market: s for s in snapshots if s.meta.market in MARKETS}
        if set(selected) != set(MARKETS):
            raise ValueError("frozen native markets missing from metadata")
        marks = []
        for market in MARKETS:
            snapshot = selected[market]
            c = snapshot.context
            if not _positive(c.mark_px) or not _positive(c.oracle_px):
                raise ValueError("invalid target market mark/oracle")
            payload = dict(
                mark_px=c.mark_px,
                oracle_px=c.oracle_px,
                mid_px=c.mid_px,
                funding=c.funding,
                open_interest=c.open_interest,
            )
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, default=str).encode()
            ).hexdigest()
            marks.append(
                StreamEvent(
                    StreamKind.ACTIVE_ASSET_CTX,
                    market,
                    None,
                    _EPOCH + timedelta(milliseconds=received_at_ms),
                    1,
                    "hyperliquid-mainnet-info",
                    f"volatility-info:{market.canonical}:{received_at_ms}:{digest}",
                    payload,
                )
            )
        self._snapshots = {s.meta.market: s for s in snapshots}
        self._marks.update((m.market, m) for m in marks)
        return tuple(marks)

    def ingest_ws(self, raw: object, *, received_at_ms: int) -> tuple[StreamEvent, ...]:
        self._receipt("ws", raw, received_at_ms)
        events = normalize_ws_message(
            raw, receive_time=_EPOCH + timedelta(milliseconds=received_at_ms)
        )
        for event in events:
            _market(event.market)
            if event.kind not in (StreamKind.L2_BOOK, StreamKind.ACTIVE_ASSET_CTX):
                raise ValueError("unsubscribed stream for frozen volatility experiment")
            if event.exchange_time_ms is not None and event.exchange_time_ms > received_at_ms:
                raise ValueError("exchange clock after receipt")
            if event.kind is StreamKind.ACTIVE_ASSET_CTX and not all(
                _positive(cast(Decimal | None, event.payload.get(key)))
                for key in ("mark_px", "oracle_px")
            ):
                raise ValueError("invalid target market mark/oracle")
        for event in events:
            target = self._books if event.kind is StreamKind.L2_BOOK else self._marks
            target[event.market] = event
        return tuple(events)

    def ingest_funding(
        self,
        market: MarketId,
        raw: object,
        *,
        received_at_ms: int,
        request_started_ms: int | None = None,
    ) -> tuple[FundingRate, ...]:
        self._receipt("funding", raw, received_at_ms, market, request_started_ms)
        results: list[FundingRate] = []
        seen: set[int] = set()
        for rate in normalize_funding_history(market, raw, received_at_ms=received_at_ms):
            boundary = funding_boundary_for_record_time(rate.time_ms)
            if (
                boundary is None
                or rate.time_ms > received_at_ms
                or not rate.funding_rate.is_finite()
                or not rate.premium.is_finite()
            ):
                raise ValueError("invalid settled funding boundary")
            if boundary in seen:
                raise ValueError("duplicate settled funding boundary")
            seen.add(boundary)
            old = self._funding.get((market, boundary))
            # Bounded exchange timestamp jitter is preserved in the rate, never
            # synthesized as a fresh sample. Repeated genuine records retain the
            # first observation clock, including after the position has closed.
            if old is not None and replace(rate, received_at_ms=old.received_at_ms) != old:
                raise ValueError("conflicting settled funding")
            results.append(old or rate)
        for rate in results:
            boundary = funding_boundary_for_record_time(rate.time_ms)
            assert boundary is not None
            self._funding[(market, boundary)] = rate
        return tuple(results)

    def gap(self, reason: str, *, now_ms: int) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("gap reason must not be empty")
        raw = {"reason": reason}
        self._receipt("gap", raw, now_ms)
        self._gaps.append({"received_at_ms": now_ms, "reason": reason})

    def instruments(self) -> dict[MarketId, InstrumentExecutionSpec]:
        return {
            market: InstrumentExecutionSpec(
                market,
                s.meta.sz_decimals,
                Decimal(s.meta.max_leverage),
                Decimal("10"),
                s.received_at_ms,
                s.source,
            )
            for market, s in self._snapshots.items()
            if market in MARKETS and s.meta.max_leverage > 0 and 0 <= s.meta.sz_decimals <= 18
        }

    def daily_windows(
        self,
        epoch_ms: int,
        *,
        eligibility: Mapping[MarketId, EligibilityDecision],
    ) -> tuple[VolatilityBudgetWindow, ...]:
        epoch = _clock(epoch_ms)
        if epoch % DAY_MS != 30_000:
            raise ValueError("daily epoch must be exactly 00:00:30 UTC")
        start = epoch - 30_000 - 30 * DAY_MS
        windows = []
        for market in MARKETS:
            bars = tuple(
                self._bars[market][key]
                for key in sorted(self._bars[market])
                if start <= key < epoch - 30_000 and self._bars[market][key].received_at_ms < epoch
            )
            snapshot = self._snapshots.get(market)
            if snapshot is not None and snapshot.received_at_ms > epoch:
                snapshot = None
            funding = (
                None
                if snapshot is None or snapshot.context.premium is None
                else FundingRate(
                    market,
                    snapshot.received_at_ms,
                    snapshot.context.funding,
                    snapshot.context.premium,
                    snapshot.source,
                    snapshot.received_at_ms,
                    snapshot.schema_version,
                )
            )
            book = self._books.get(market)
            if book is not None and book.receive_time > _EPOCH + timedelta(milliseconds=epoch):
                book = None
            windows.append(
                VolatilityBudgetWindow(
                    market,
                    epoch,
                    bars,
                    book,
                    eligibility.get(
                        market,
                        EligibilityDecision(
                            market, False, False, ("missing_ordinary_eligibility",)
                        ),
                    ),
                    funding,
                    snapshot,
                )
            )
        return tuple(windows)

    def restore(
        self, records: Iterable[Mapping[str, Any]], *, allow_adverse_clocks: bool = False
    ) -> None:
        if self._last_received_ms >= 0:
            raise ValueError("restore requires a fresh source adapter")
        self._restoring = True
        try:
            for record in records:
                if (
                    type(record.get("schema_version")) is not int
                    or record.get("schema_version") != 1
                ):
                    raise ValueError("unsupported source receipt schema")
                kind = record["kind"]
                expected = "hyperliquid-mainnet-ws" if kind == "ws" else "hyperliquid-mainnet-info"
                if record.get("source") != expected:
                    raise ValueError("source receipt provenance mismatch")
                now = record["received_at_ms"]
                raw = record["raw"]
                started = record.get("request_started_ms")
                _clock(now)
                clock_fault = None
                if now < self._last_received_ms:
                    clock_fault = "receive clock regression"
                if started is not None and _clock(started) > now:
                    clock_fault = "request starts after receipt"
                if clock_fault is not None:
                    if not allow_adverse_clocks:
                        raise ValueError(clock_fault)
                    # Caller must already authenticate journal order independently.
                    # Preserve the original bad clock as permanent adverse evidence;
                    # it is never substituted as a fresh observation for protection.
                    self._rejections.append(
                        {"received_at_ms": now, "kind": kind, "reason": clock_fault}
                    )
                    continue
                if kind not in ("meta", "ws", "gap", "candles", "funding"):
                    raise ValueError("unsupported source receipt kind")
                if kind in ("candles", "funding") and not any(
                    m.canonical == record.get("market") for m in MARKETS
                ):
                    raise ValueError("unsupported market in source receipt")
                try:
                    if kind == "meta":
                        self.ingest_meta(raw, received_at_ms=now, request_started_ms=started)
                    elif kind == "ws":
                        self.ingest_ws(raw, received_at_ms=now)
                    elif kind == "gap":
                        self.gap(raw["reason"], now_ms=now)
                    elif kind in ("candles", "funding"):
                        market = next((m for m in MARKETS if m.canonical == record["market"]), None)
                        if market is None:
                            raise ValueError("unsupported market in source receipt")
                        if kind == "candles":
                            self.ingest_candles(
                                market, raw, received_at_ms=now, request_started_ms=started
                            )
                        else:
                            self.ingest_funding(
                                market, raw, received_at_ms=now, request_started_ms=started
                            )
                    else:
                        raise ValueError("unsupported source receipt kind")
                except ValueError as exc:
                    # Authenticated raw source may be malformed. It must remain
                    # adverse evidence without preventing fresh protective books
                    # from being recovered after an open-position interruption.
                    self._rejections.append(
                        {"received_at_ms": now, "kind": kind, "reason": str(exc)}
                    )
        finally:
            self._restoring = False
