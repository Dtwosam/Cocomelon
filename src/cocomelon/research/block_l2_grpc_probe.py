"""Optional read-only per-block, full-depth HyperCore gRPC diagnostic.

No execution, paper-account access, signed evidence mutation, or fast 5-level
substitution. A hosted gRPC endpoint is optional and must be supplied explicitly.
This module only measures candidate-source viability; it NEVER promotes books.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TextIO, cast

from cocomelon.research.full_depth_cadence_probe import DEFAULT_MARKETS

SCHEMA = "candidate-grpc-l2-diagnostic-v1"
METHOD = "/hyperliquid.OrderBookStreaming/StreamL2Book"
REQUIRED_DEPTH = 20


@dataclass(frozen=True)
class Level:
    px: Decimal
    sz: Decimal
    n: int


@dataclass(frozen=True)
class BlockL2Snapshot:
    coin: str
    time_ms: int
    height: int
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    wire_sha256: str


def _level(value: object) -> Level:
    try:
        raw = cast(Any, value)
        px = Decimal(str(raw.px))
        sz = Decimal(str(raw.sz))
        n = raw.n
    except (AttributeError, InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid aggregated level") from exc
    if (
        not px.is_finite()
        or not sz.is_finite()
        or px <= 0
        or sz <= 0
        or isinstance(n, bool)
        or not isinstance(n, int)
        or n <= 0
    ):
        raise ValueError("nonpositive or nonfinite aggregated level")
    return Level(px=px, sz=sz, n=n)


def parse_block_l2(value: object, wire: bytes) -> BlockL2Snapshot:
    """Strict, vendor-wire-schema L2 conversion without trading-side effects."""
    try:
        raw = cast(Any, value)
        coin = raw.coin
        stamp = raw.time
        height = raw.block_number
        raw_bids = raw.bids
        raw_asks = raw.asks
    except AttributeError as exc:
        raise ValueError("missing StreamL2Book fields") from exc
    if (
        not isinstance(coin, str)
        or not coin
        or isinstance(stamp, bool)
        or not isinstance(stamp, int)
        or stamp <= 0
        or isinstance(height, bool)
        or not isinstance(height, int)
        or height <= 0
    ):
        raise ValueError("invalid StreamL2Book identity, time, or height")
    try:
        bids = tuple(_level(item) for item in raw_bids)
        asks = tuple(_level(item) for item in raw_asks)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid book levels") from exc
    if not bids or not asks:
        raise ValueError("book has an empty side")
    if any(a.px <= b.px for a, b in zip(bids, bids[1:], strict=False)):
        raise ValueError("bid prices must descend")
    if any(a.px >= b.px for a, b in zip(asks, asks[1:], strict=False)):
        raise ValueError("ask prices must ascend")
    if bids[0].px >= asks[0].px:
        raise ValueError("crossed or locked book")
    if len(bids) > 100 or len(asks) > 100:
        raise ValueError("out of supported depth range")
    return BlockL2Snapshot(
        coin=coin,
        time_ms=stamp,
        height=height,
        bids=bids,
        asks=asks,
        wire_sha256=hashlib.sha256(wire).hexdigest(),
    )


@dataclass
class _Market:
    last_ns: int | None = None
    last_age_ms: int | None = None
    last_height: int | None = None
    last_time_ms: int | None = None
    last_digest: str | None = None
    last_depth_ok: bool = False
    messages: int = 0
    unique: int = 0
    duplicate_blocks: int = 0
    conflicting_blocks: int = 0
    height_regressions: int = 0
    time_regressions: int = 0
    height_jump_count: int = 0
    shallow_books: int = 0
    future_books: int = 0
    stale_on_arrival_3s: int = 0
    stale_on_arrival_5s: int = 0
    interval_samples: int = 0
    interval_ge_3s: int = 0
    interval_ge_5s: int = 0
    max_interval_ms: float = 0.0
    time_fresh3_ns: int = 0
    time_fresh5_ns: int = 0

    def _fresh_ns(self, end_ns: int, threshold_ms: int) -> int:
        if (
            self.last_ns is None
            or self.last_age_ms is None
            or not self.last_depth_ok
            or self.last_age_ms < 0
        ):
            return 0
        budget = max(0, threshold_ms - self.last_age_ms) * 1_000_000
        return max(0, min(end_ns - self.last_ns, budget))

    def integrate(self, end_ns: int) -> None:
        self.time_fresh3_ns += self._fresh_ns(end_ns, 3_000)
        self.time_fresh5_ns += self._fresh_ns(end_ns, 5_000)

    def record(
        self, snapshot: BlockL2Snapshot, *, age_ms: int, monotonic_ns: int
    ) -> tuple[str, float | None]:
        self.messages += 1
        if self.last_ns is not None and monotonic_ns < self.last_ns:
            raise ValueError("receipt monotonic time moved backwards")
        if self.last_height is not None and snapshot.height < self.last_height:
            self.height_regressions += 1
            self.integrate(monotonic_ns)
            self.last_ns, self.last_age_ms, self.last_depth_ok = monotonic_ns, None, False
            return "height_regression", None
        if self.last_height == snapshot.height:
            if self.last_digest == snapshot.wire_sha256:
                self.duplicate_blocks += 1
                return "duplicate_block", None
            self.conflicting_blocks += 1
            self.integrate(monotonic_ns)
            self.last_ns, self.last_age_ms, self.last_depth_ok = monotonic_ns, None, False
            return "conflicting_block", None
        if self.last_time_ms is not None and snapshot.time_ms < self.last_time_ms:
            self.time_regressions += 1
            self.integrate(monotonic_ns)
            self.last_ns, self.last_age_ms, self.last_depth_ok = monotonic_ns, None, False
            return "time_regression", None
        if self.last_height is not None and snapshot.height > self.last_height + 1:
            self.height_jump_count += 1

        interval_ms: float | None = None
        if self.last_ns is not None:
            interval_ms = (monotonic_ns - self.last_ns) / 1_000_000
            self.interval_samples += 1
            self.interval_ge_3s += int(interval_ms >= 3_000)
            self.interval_ge_5s += int(interval_ms >= 5_000)
            self.max_interval_ms = max(self.max_interval_ms, interval_ms)
            self.integrate(monotonic_ns)

        depth_ok = len(snapshot.bids) >= REQUIRED_DEPTH and len(snapshot.asks) >= REQUIRED_DEPTH
        self.shallow_books += int(not depth_ok)
        self.future_books += int(age_ms < 0)
        self.stale_on_arrival_3s += int(age_ms >= 3_000)
        self.stale_on_arrival_5s += int(age_ms >= 5_000)
        self.unique += 1
        self.last_ns = monotonic_ns
        self.last_age_ms = age_ms
        self.last_depth_ok = depth_ok and age_ms >= 0
        self.last_height = snapshot.height
        self.last_time_ms = snapshot.time_ms
        self.last_digest = snapshot.wire_sha256
        return "unique", interval_ms

    def summary(self, *, end_ns: int, total_ns: int) -> dict[str, object]:
        return {
            "received_messages": self.messages,
            "unique_blocks": self.unique,
            "duplicate_blocks": self.duplicate_blocks,
            "conflicting_blocks": self.conflicting_blocks,
            "height_regressions": self.height_regressions,
            "time_regressions": self.time_regressions,
            "height_jump_count_not_completeness_proof": self.height_jump_count,
            "books_under_20_levels_per_side": self.shallow_books,
            "future_dated_books": self.future_books,
            "stale_on_arrival_3s": self.stale_on_arrival_3s,
            "stale_on_arrival_5s": self.stale_on_arrival_5s,
            "interval_samples": self.interval_samples,
            "interval_ge_3s": self.interval_ge_3s,
            "interval_ge_5s": self.interval_ge_5s,
            "interval_max_ms": round(self.max_interval_ms, 2),
            "full_depth_fresh3_time_fraction": round(
                min(1.0, (self.time_fresh3_ns + self._fresh_ns(end_ns, 3_000))
                    / max(1, total_ns)), 6
            ),
            "full_depth_fresh5_time_fraction": round(
                min(1.0, (self.time_fresh5_ns + self._fresh_ns(end_ns, 5_000))
                    / max(1, total_ns)), 6
            ),
        }


class BlockL2Probe:
    def __init__(self, markets: Sequence[str], *, start_ns: int) -> None:
        cohort = tuple(markets)
        if (
            not cohort
            or len(cohort) > 20
            or len(set(cohort)) != len(cohort)
            or any(market not in DEFAULT_MARKETS for market in cohort)
        ):
            raise ValueError("require distinct subset of frozen 20-market public cohort")
        self.cohort = cohort
        self.start_ns = start_ns
        self.states = {name: _Market() for name in cohort}
        self.parse_errors = 0
        self.untracked = 0
        self.stream_errors = 0

    def observe(
        self, value: object, wire: bytes, *, utc_ms: int, monotonic_ns: int
    ) -> dict[str, object] | None:
        if monotonic_ns < self.start_ns:
            raise ValueError("monotonic receipt predates experiment")
        try:
            snapshot = parse_block_l2(value, wire)
        except ValueError:
            self.parse_errors += 1
            return None
        state = self.states.get(snapshot.coin)
        if state is None:
            self.untracked += 1
            return None
        age_ms = utc_ms - snapshot.time_ms
        status, interval = state.record(
            snapshot, age_ms=age_ms, monotonic_ns=monotonic_ns
        )
        return {
            "schema": SCHEMA,
            "market": snapshot.coin,
            "block_number": snapshot.height,
            "exchange_time_ms": snapshot.time_ms,
            "receive_utc_ms": utc_ms,
            "receipt_elapsed_ms": round((monotonic_ns - self.start_ns) / 1_000_000, 2),
            "source_age_ms": age_ms,
            "bid_levels": len(snapshot.bids),
            "ask_levels": len(snapshot.asks),
            "has_at_least_20x20_levels": (
                len(snapshot.bids) >= REQUIRED_DEPTH
                and len(snapshot.asks) >= REQUIRED_DEPTH
            ),
            "interval_ms": None if interval is None else round(interval, 2),
            "result": status,
            "wire_sha256": snapshot.wire_sha256,
        }

    def summary(self, *, end_ns: int) -> dict[str, object]:
        if end_ns < self.start_ns:
            raise ValueError("negative elapsed observation window")
        total_ns = end_ns - self.start_ns
        per_market = {
            market: state.summary(end_ns=end_ns, total_ns=total_ns)
            for market, state in self.states.items()
        }
        return {
            "schema": SCHEMA,
            "mode": "optional_hosted_grpc_read_only_diagnostic",
            "method": METHOD,
            "n_levels_requested": REQUIRED_DEPTH,
            "cohort": list(self.cohort),
            "elapsed_ms": round(total_ns / 1_000_000, 2),
            "unique_blocks": sum(state.unique for state in self.states.values()),
            "parse_errors": self.parse_errors,
            "stream_errors": self.stream_errors,
            "untracked_messages": self.untracked,
            "markets": per_market,
            "venue_completeness_certified": False,
            "trading_authority": False,
            "after_cost_profit_verified": False,
            "warning": (
                "Experimental provider stream, not signed market source or trading-ready "
                "order book. Clock skew affects timestamp ages; missing blocks cannot "
                "be reconstructed. 20-level depth and existing 3s/5s gates stay mandatory."
            ),
        }


def _proto_messages() -> tuple[type[Any], type[Any]]:
    """Build only the three vendor-documented protobuf wire messages at runtime.

    Field numbers/types match QuickNode's public orderbook.proto for StreamL2Book.
    No checked-in generated clients, customer credentials, or external schema
    downloads are needed. Requires optional google.protobuf installation.
    """
    descriptor_pb2 = importlib.import_module("google.protobuf.descriptor_pb2")
    descriptor_pool = importlib.import_module("google.protobuf.descriptor_pool")
    message_factory = importlib.import_module("google.protobuf.message_factory")
    file = descriptor_pb2.FileDescriptorProto()
    file.name = "read_only_l2_probe.proto"
    file.package = "hyperliquid"
    file.syntax = "proto3"
    optional = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    repeated = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED

    def message(name: str) -> Any:
        obj = file.message_type.add()
        obj.name = name
        return obj

    def field(
        msg: Any, name: str, number: int, kind: int, *,
        label: int = optional, type_name: str = "",
    ) -> None:
        obj = msg.field.add()
        obj.name, obj.number, obj.type, obj.label = name, number, kind, label
        if type_name:
            obj.type_name = type_name

    S = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    UINT32 = descriptor_pb2.FieldDescriptorProto.TYPE_UINT32
    L = descriptor_pb2.FieldDescriptorProto.TYPE_UINT64
    M = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    req = message("L2BookRequest")
    field(req, "coin", 1, S)
    field(req, "n_levels", 2, UINT32)
    level = message("L2Level")
    field(level, "px", 1, S)
    field(level, "sz", 2, S)
    field(level, "n", 3, UINT32)
    resp = message("L2BookUpdate")
    field(resp, "coin", 1, S)
    field(resp, "time", 2, L)
    field(resp, "block_number", 3, L)
    field(resp, "bids", 4, M, label=repeated, type_name=".hyperliquid.L2Level")
    field(resp, "asks", 5, M, label=repeated, type_name=".hyperliquid.L2Level")
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return (
        message_factory.GetMessageClass(
            pool.FindMessageTypeByName("hyperliquid.L2BookRequest")
        ),
        message_factory.GetMessageClass(
            pool.FindMessageTypeByName("hyperliquid.L2BookUpdate")
        ),
    )


def validate_endpoint(endpoint: str) -> str:
    """Disallow insecure/unknown destinations and credential-in-URL leakage."""
    if (
        any(token in endpoint for token in ("/", "://", "@", "?", "#", "\\", "\n", " "))
        or not endpoint.endswith(".hype-mainnet.quiknode.pro:10000")
    ):
        raise ValueError(
            "GRPC_ENDPOINT must be a bare mainnet QuickNode HyperCore host:10000"
        )
    return endpoint


async def collect_candidate(
    probe: BlockL2Probe, *, duration_seconds: int, receipts: TextIO,
    endpoint: str, token: str,
) -> tuple[dict[str, object], bool]:
    """TLS gRPC receive-only; never touches the worker or its runtime data."""
    if not token or "\n" in token:
        raise ValueError("AUTH_TOKEN must be present and valid")
    host = validate_endpoint(endpoint)
    grpc = importlib.import_module("grpc")
    request_cls, response_cls = _proto_messages()
    deadline_ns = probe.start_ns + duration_seconds * 1_000_000_000

    async with grpc.aio.secure_channel(
        host, grpc.ssl_channel_credentials(),
        options=(("grpc.max_receive_message_length", 8 * 1024 * 1024),),
    ) as channel:
        stream_method = channel.unary_stream(
            METHOD,
            request_serializer=lambda request: request.SerializeToString(),
            response_deserializer=response_cls.FromString,
        )

        async def one_market(coin: str) -> None:
            request = request_cls(coin=coin, n_levels=REQUIRED_DEPTH)
            stream = stream_method(
                request, metadata=(("x-token", token),),
                timeout=duration_seconds + 10,
            )
            try:
                async for update in stream:
                    now_ns = time.monotonic_ns()
                    utc_ms = time.time_ns() // 1_000_000
                    if now_ns >= deadline_ns:
                        break
                    raw = update.SerializeToString()
                    receipt = probe.observe(
                        update, raw, utc_ms=utc_ms, monotonic_ns=now_ns
                    )
                    if receipt is not None:
                        receipts.write(json.dumps(receipt, sort_keys=True) + "\n")
            except asyncio.CancelledError:
                raise
            except Exception:
                # Fail closed; error details may embed customer endpoint or
                # auth metadata and therefore must never reach GH output.
                probe.stream_errors += 1
            finally:
                stream.cancel()

        tasks = [asyncio.create_task(one_market(coin)) for coin in probe.cohort]
        _done, pending = await asyncio.wait(tasks, timeout=duration_seconds)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    result = probe.summary(end_ns=time.monotonic_ns())
    complete = (
        time.monotonic_ns() >= deadline_ns
        and all(state.unique >= 2 for state in probe.states.values())
        and probe.stream_errors == 0
        and probe.parse_errors == 0
    )
    result["observation_window_completed"] = complete
    return result, complete


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--markets", default=",".join(DEFAULT_MARKETS))
    parser.add_argument("--out-dir", type=Path, default=Path("grpc-l2-diagnostic"))
    args = parser.parse_args(argv)
    if not 30 <= args.duration_seconds <= 900:
        parser.error("duration must be between 30 and 900 seconds")
    markets = tuple(m.strip() for m in args.markets.split(","))
    try:
        probe = BlockL2Probe(markets, start_ns=time.monotonic_ns())
        endpoint = validate_endpoint(os.environ.get("GRPC_ENDPOINT", ""))
        token = os.environ.get("AUTH_TOKEN", "")
        if not token:
            raise ValueError("AUTH_TOKEN is required for hosted gRPC diagnostics")
    except ValueError as exc:
        parser.error(str(exc))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "receipts.jsonl").open("x", encoding="utf-8") as out:
        result, complete = asyncio.run(
            collect_candidate(
                probe, duration_seconds=args.duration_seconds,
                receipts=out, endpoint=endpoint, token=token,
            )
        )
    result["receipts_sha256"] = hashlib.sha256(
        (args.out_dir / "receipts.jsonl").read_bytes()
    ).hexdigest()
    result["ended_utc"] = datetime.now(UTC).isoformat()
    (args.out_dir / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "unique_blocks": result["unique_blocks"],
        "observation_window_completed": complete,
        "receipts_sha256": result["receipts_sha256"],
    }))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
