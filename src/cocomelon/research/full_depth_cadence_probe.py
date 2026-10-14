"""Independent read-only full-depth L2 timing probe.

This deliberately does NOT interact with paper trading, signed source history,
account state, strategy eligibility, order creation, or position management.
Receipts are diagnostic digests, NOT authenticated venue-completeness evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from cocomelon.config import MAINNET_WS_URL
from cocomelon.domain.stream import StreamKind
from cocomelon.hyperliquid.ws_client import JsonWsConnection
from cocomelon.hyperliquid.ws_protocol import (
    WsProtocolError,
    normalize_ws_message,
    subscribe_message,
)

# Exact public 20-market cohort shown in authenticated PAPER issue #469 on
# 2026-10-14. Do not silently swap its membership inside a single comparison.
DEFAULT_MARKETS = (
    "BLUR", "BOME", "CASHCAT", "CC", "CHIP", "ENA", "FET",
    "GRASS", "LIT", "NIL", "ONDO", "OP", "PONS", "PUMP",
    "RSR", "STRK", "SYRUP", "W", "WLD", "ZK",
)
FRESHNESS_MS = (3_000, 5_000)


@dataclass
class _MarketTiming:
    last_unique_ns: int | None = None
    last_age_ms: int | None = None
    last_exchange_ms: int | None = None
    recent_keys: set[str] = field(default_factory=set)
    key_order: deque[str] = field(default_factory=deque)
    messages: int = 0
    unique: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    negative_age: int = 0
    late_3000: int = 0
    late_5000: int = 0
    both_sides_20_levels: int = 0
    interval_samples: int = 0
    interval_ge_3000: int = 0
    interval_ge_5000: int = 0
    interval_ge_8000: int = 0
    interval_max_ms: float = 0.0
    age_max_ms: int = 0
    eligible_3_ns: int = 0
    eligible_5_ns: int = 0

    def _fresh_segment(self, end_ns: int, freshness_ms: int) -> int:
        anchor = self.last_unique_ns
        age = self.last_age_ms
        if anchor is None or age is None or age < 0 or end_ns <= anchor:
            return 0
        budget_ns = max(0, freshness_ms - age) * 1_000_000
        return max(0, min(end_ns - anchor, budget_ns))

    def advance(self, end_ns: int) -> None:
        anchor = self.last_unique_ns
        if anchor is None:
            return
        self.eligible_3_ns += self._fresh_segment(end_ns, 3_000)
        self.eligible_5_ns += self._fresh_segment(end_ns, 5_000)
        # The new receive becomes the clock anchor only after integration.
        self.last_unique_ns = end_ns

    def record(
        self,
        *,
        monotonic_ns: int,
        exchange_ms: int,
        age_ms: int,
        key: str,
        bid_levels: int,
        ask_levels: int,
    ) -> tuple[str, float | None]:
        self.messages += 1
        if key in self.recent_keys:
            self.duplicates += 1
            return "duplicate", None
        if (
            self.last_exchange_ms is not None
            and exchange_ms < self.last_exchange_ms
        ) or (
            self.last_unique_ns is not None
            and monotonic_ns < self.last_unique_ns
        ):
            self.out_of_order += 1
            return "out_of_order", None

        self.recent_keys.add(key)
        self.key_order.append(key)
        if len(self.key_order) > 512:
            self.recent_keys.discard(self.key_order.popleft())
        previous = self.last_unique_ns
        interval_ms: float | None = None
        if previous is not None:
            interval_ms = (monotonic_ns - previous) / 1_000_000
            self.interval_samples += 1
            self.interval_ge_3000 += int(interval_ms >= 3_000)
            self.interval_ge_5000 += int(interval_ms >= 5_000)
            self.interval_ge_8000 += int(interval_ms >= 8_000)
            self.interval_max_ms = max(self.interval_max_ms, interval_ms)
            self.advance(monotonic_ns)
        self.unique += 1
        self.last_unique_ns = monotonic_ns
        self.last_exchange_ms = exchange_ms
        self.last_age_ms = age_ms
        self.negative_age += int(age_ms < 0)
        self.late_3000 += int(age_ms >= 3_000)
        self.late_5000 += int(age_ms >= 5_000)
        self.age_max_ms = max(self.age_max_ms, age_ms)
        self.both_sides_20_levels += int(bid_levels >= 20 and ask_levels >= 20)
        return "unique", interval_ms

    def summary(self, end_ns: int, total_ns: int) -> dict[str, object]:
        extra_3_ns = self._fresh_segment(end_ns, 3_000)
        extra_5_ns = self._fresh_segment(end_ns, 5_000)
        return {
            "messages": self.messages,
            "unique": self.unique,
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "source_future_dated": self.negative_age,
            "source_age_ge_3000": self.late_3000,
            "source_age_ge_5000": self.late_5000,
            "source_age_max_ms": self.age_max_ms,
            "both_sides_20_levels": self.both_sides_20_levels,
            "interval_samples": self.interval_samples,
            "interval_ge_3000": self.interval_ge_3000,
            "interval_ge_5000": self.interval_ge_5000,
            "interval_ge_8000": self.interval_ge_8000,
            "interval_max_ms": round(self.interval_max_ms, 2),
            "fresh_3s_time_fraction": round(
                min(1.0, (self.eligible_3_ns + extra_3_ns) / max(1, total_ns)), 6
            ),
            "fresh_5s_time_fraction": round(
                min(1.0, (self.eligible_5_ns + extra_5_ns) / max(1, total_ns)), 6
            ),
        }


class FullDepthCadenceProbe:
    """Per-market exchange-time age and monotonic elapsed-time observations."""

    def __init__(self, markets: Sequence[str], *, start_ns: int) -> None:
        names = tuple(markets)
        if not names or len(names) > 20 or len(set(names)) != len(names):
            raise ValueError("require 1–20 distinct public markets")
        if any(not name or not name.isascii() for name in names):
            raise ValueError("invalid market")
        self.markets = names
        self.start_ns = start_ns
        self._timings = {name: _MarketTiming() for name in names}
        self.protocol_errors = 0
        self.untracked = 0
        self.connections = 0
        self.connection_errors = 0

    def ingest(
        self,
        raw: Mapping[str, object],
        *,
        receive_utc_ms: int,
        monotonic_ns: int,
    ) -> dict[str, object] | None:
        if monotonic_ns < self.start_ns:
            raise ValueError("monotonic timestamp predates probe")
        if raw.get("channel") != "l2Book":
            return None
        try:
            events = normalize_ws_message(
                dict(raw),
                receive_time=datetime.fromtimestamp(
                    receive_utc_ms / 1_000, tz=UTC
                ),
            )
        except (WsProtocolError, ValueError, OverflowError):
            self.protocol_errors += 1
            return None
        if len(events) != 1 or events[0].kind is not StreamKind.L2_BOOK:
            self.protocol_errors += 1
            return None
        event = events[0]
        market = event.market.wire_name
        timing = self._timings.get(market)
        if timing is None:
            self.untracked += 1
            return None
        if event.exchange_time_ms is None:
            self.protocol_errors += 1
            return None

        bids = event.payload.get("bids")
        asks = event.payload.get("asks")
        bid_levels = len(bids) if isinstance(bids, tuple) else 0
        ask_levels = len(asks) if isinstance(asks, tuple) else 0
        digest = hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        age_ms = receive_utc_ms - event.exchange_time_ms
        kind, interval_ms = timing.record(
            monotonic_ns=monotonic_ns,
            exchange_ms=event.exchange_time_ms,
            age_ms=age_ms,
            key=event.event_key,
            bid_levels=bid_levels,
            ask_levels=ask_levels,
        )
        return {
            "schema": "passive-l2-cadence-v1",
            "market": market,
            "receipt_elapsed_ms": round(
                (monotonic_ns - self.start_ns) / 1_000_000, 2
            ),
            "receive_utc_ms": receive_utc_ms,
            "exchange_ms": event.exchange_time_ms,
            "source_age_ms": age_ms,
            "interval_ms": None if interval_ms is None else round(interval_ms, 2),
            "bid_levels": bid_levels,
            "ask_levels": ask_levels,
            "result": kind,
            "raw_message_sha256": digest,
        }

    def summary(self, *, end_ns: int) -> dict[str, object]:
        if end_ns < self.start_ns:
            raise ValueError("negative observation duration")
        total_ns = end_ns - self.start_ns
        markets = {
            name: timing.summary(end_ns, total_ns)
            for name, timing in self._timings.items()
        }
        unique = sum(t.unique for t in self._timings.values())
        return {
            "schema": "passive-l2-cadence-v1",
            "mode": "independent_public_read_only",
            "mainnet_ws_url": MAINNET_WS_URL,
            "duration_ms": round(total_ns / 1_000_000, 2),
            "market_cohort": list(self.markets),
            "connections": self.connections,
            "connection_errors": self.connection_errors,
            "protocol_errors": self.protocol_errors,
            "untracked_messages": self.untracked,
            "unique_books": unique,
            "markets_with_two_or_more_books": sum(
                t.unique >= 2 for t in self._timings.values()
            ),
            "markets": markets,
            "freshness_thresholds_ms": list(FRESHNESS_MS),
            "source_completeness_certified": False,
            "trading_authority": False,
            "after_cost_profit_verified": False,
            "caution": (
                "Clocked public-feed observations only. Missing events cannot be "
                "reconstructed; receive/exchange clock offsets affect source age. "
                "Never promote these receipts to signed trading-market evidence."
            ),
        }


async def collect(
    probe: FullDepthCadenceProbe,
    *,
    duration_seconds: int,
    receipts: TextIO,
) -> tuple[dict[str, object], bool]:
    """Subscribe to public default full-depth L2 only; no order/account API."""
    from websockets.asyncio.client import connect

    deadline_ns = probe.start_ns + duration_seconds * 1_000_000_000
    errors: list[str] = []
    while time.monotonic_ns() < deadline_ns and probe.connections < 4:
        probe.connections += 1
        try:
            # No fast:true / five-level subscription; the venue default
            # full-depth public L2 feed is compared to the PAPER source.
            async with connect(
                MAINNET_WS_URL, ping_interval=15, ping_timeout=15,
                max_size=2**22,
            ) as socket:
                conn = JsonWsConnection(socket)
                for market in probe.markets:
                    await conn.send_json(subscribe_message(
                        {"type": "l2Book", "coin": market}
                    ))
                timeouts = 0
                while (remaining_ns := deadline_ns - time.monotonic_ns()) > 0:
                    try:
                        message = await asyncio.wait_for(
                            conn.recv_json(),
                            timeout=min(15.0, remaining_ns / 1_000_000_000),
                        )
                    except TimeoutError:
                        if time.monotonic_ns() >= deadline_ns:
                            break
                        timeouts += 1
                        if timeouts >= 3:
                            raise TimeoutError("no public socket messages") from None
                        await conn.send_json({"method": "ping"})
                        continue
                    timeouts = 0
                    # Sample the receipt clock immediately after JSON receive,
                    # before independent parsing or writing receipts.
                    received_ns = time.monotonic_ns()
                    received_utc_ms = time.time_ns() // 1_000_000
                    receipt = probe.ingest(
                        message, receive_utc_ms=received_utc_ms,
                        monotonic_ns=received_ns,
                    )
                    if receipt is not None:
                        receipts.write(json.dumps(receipt, sort_keys=True) + "\n")
                if time.monotonic_ns() >= deadline_ns:
                    break
        except (Exception, asyncio.CancelledError) as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            probe.connection_errors += 1
            errors.append(type(exc).__name__)
            if time.monotonic_ns() < deadline_ns:
                await asyncio.sleep(min(2**min(probe.connections, 2), 4))
    result = probe.summary(end_ns=time.monotonic_ns())
    result["connection_error_types"] = errors
    complete = time.monotonic_ns() >= deadline_ns and result["unique_books"] != 0
    result["observation_window_completed"] = complete
    return result, complete


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--markets", default=",".join(DEFAULT_MARKETS))
    parser.add_argument("--out-dir", type=Path, default=Path("l2-cadence-probe"))
    args = parser.parse_args(argv)
    if not 30 <= args.duration_seconds <= 900:
        parser.error("duration-seconds must be between 30 and 900")
    markets = tuple(m.strip() for m in args.markets.split(","))
    try:
        probe = FullDepthCadenceProbe(markets, start_ns=time.monotonic_ns())
    except ValueError as exc:
        parser.error(str(exc))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    receipts_path = args.out_dir / "source-receipts.jsonl"
    with receipts_path.open("x", encoding="utf-8") as receipts:
        result, complete = asyncio.run(
            collect(probe, duration_seconds=args.duration_seconds, receipts=receipts)
        )
    receipt_digest = hashlib.sha256(receipts_path.read_bytes()).hexdigest()
    result["receipts_sha256"] = receipt_digest
    result["wall_clock_ended_utc"] = datetime.now(UTC).isoformat()
    (args.out_dir / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "unique_books": result["unique_books"],
        "observation_window_completed": complete,
        "receipts_sha256": receipt_digest,
        "summary": str(args.out_dir / "summary.json"),
    }))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
