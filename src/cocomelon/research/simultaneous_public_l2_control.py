"""Simultaneous independent public Hyperliquid L2 cadence control experiment.

Two separate unprivileged sockets subscribe to an identical, frozen 20-market
cohort, for the SAME monotonic time window:
  (a) default full-depth public l2Book (20 levels)
  (b) opt-in public fast:true l2Book (at most 5 levels)

Five-level snapshots are NEVER depth eligible and NEVER promoted to signed
market data or the PAPER trader. The experiment cannot execute orders.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO, cast

from cocomelon.config import MAINNET_WS_URL
from cocomelon.hyperliquid.ws_client import JsonWsConnection
from cocomelon.research.full_depth_cadence_probe import (
    DEFAULT_MARKETS,
    FullDepthCadenceProbe,
)
from cocomelon.research.full_depth_cadence_probe import (
    collect as collect_full_depth,
)

SCHEMA = "simultaneous-public-l2-control-v1"
FAST_SCHEMA = "public-five-level-control-v1"
MIN_UNIQUE_PER_MARKET = 20


def fast_control_subscription(market: str) -> dict[str, object]:
    """Separate diagnostic-only subscription; DO NOT weaken trader protocol."""
    if market not in DEFAULT_MARKETS:
        raise ValueError("fast control requires the frozen PAPER market cohort")
    return {
        "method": "subscribe",
        "subscription": {"type": "l2Book", "coin": market, "fast": True},
    }


class FastL2Control:
    """Wrap the existing parser, but permanently deny deep-book eligibility."""

    def __init__(self, markets: Sequence[str], *, start_ns: int) -> None:
        cohort = tuple(markets)
        if cohort != DEFAULT_MARKETS:
            raise ValueError("control requires the exact frozen 20-market cohort")
        self.probe = FullDepthCadenceProbe(cohort, start_ns=start_ns)
        self.max_bid_depth = {market: 0 for market in cohort}
        self.max_ask_depth = {market: 0 for market in cohort}
        self.unique_depth_counts = {market: 0 for market in cohort}
        self.unexpected_depth_count = 0
        self.zero_depth_count = 0
        self.acks_received = 0

    def ingest(
        self,
        raw: Mapping[str, object],
        *,
        receive_utc_ms: int,
        monotonic_ns: int,
    ) -> dict[str, object] | None:
        if raw.get("channel") == "subscriptionResponse":
            # Only an observation, not a claim of venue source completeness.
            self.acks_received += 1
            return None
        receipt = self.probe.ingest(
            raw,
            receive_utc_ms=receive_utc_ms,
            monotonic_ns=monotonic_ns,
        )
        if receipt is None:
            return None
        market = cast(str, receipt["market"])
        bids = cast(int, receipt["bid_levels"])
        asks = cast(int, receipt["ask_levels"])
        if receipt["result"] == "unique":
            self.unique_depth_counts[market] += 1
            self.max_bid_depth[market] = max(self.max_bid_depth[market], bids)
            self.max_ask_depth[market] = max(self.max_ask_depth[market], asks)
            self.unexpected_depth_count += int(bids > 5 or asks > 5)
            self.zero_depth_count += int(bids == 0 or asks == 0)
        # Separate schema and never allow 5-level results to impersonate
        # a legitimate 20-level public or candidate gRPC receipt.
        return {
            **receipt,
            "schema": FAST_SCHEMA,
            "feed": "fast_true_5_level_control",
            "full_depth_20x20_eligible": False,
            "trading_authority": False,
        }

    def summary(self, *, end_ns: int) -> dict[str, object]:
        base = self.probe.summary(end_ns=end_ns)
        markets = cast(dict[str, dict[str, Any]], base["markets"])
        detail: dict[str, dict[str, object]] = {}
        for market in DEFAULT_MARKETS:
            item = markets[market]
            detail[market] = {
                "unique": item["unique"],
                "duplicates": item["duplicates"],
                "out_of_order": item["out_of_order"],
                "interval_samples": item["interval_samples"],
                "interval_ge_3000": item["interval_ge_3000"],
                "interval_ge_5000": item["interval_ge_5000"],
                "interval_max_ms": item["interval_max_ms"],
                "source_age_ge_3000": item["source_age_ge_3000"],
                "source_age_ge_5000": item["source_age_ge_5000"],
                "source_future_dated": item["source_future_dated"],
                "source_age_max_ms": item["source_age_max_ms"],
                # These are TIMING-ONLY observations, not deep-book readiness.
                "control_source_age_under_3s_fraction": item["fresh_3s_time_fraction"],
                "control_source_age_under_5s_fraction": item["fresh_5s_time_fraction"],
                "max_bid_levels": self.max_bid_depth[market],
                "max_ask_levels": self.max_ask_depth[market],
                "full_depth_20x20_eligible": False,
            }
        return {
            "schema": FAST_SCHEMA,
            "mode": "independent_public_fast_true_5_level_CONTROL_ONLY",
            "market_cohort": list(DEFAULT_MARKETS),
            "duration_ms": base["duration_ms"],
            "unique_books": base["unique_books"],
            "connections": base["connections"],
            "connection_errors": base["connection_errors"],
            "protocol_errors": base["protocol_errors"],
            "untracked_messages": base["untracked_messages"],
            "subscription_response_count": self.acks_received,
            "unexpected_more_than_5_levels_count": self.unexpected_depth_count,
            "zero_sided_depth_count": self.zero_depth_count,
            "markets": detail,
            "full_depth_20x20_eligible": False,
            "source_completeness_certified": False,
            "trading_authority": False,
            "after_cost_profit_verified": False,
            "warning": (
                "The 5-level fast:true feed is an isolated timing CONTROL, "
                "NOT equivalent to 20-level liquidity, strategy readiness, "
                "source-gap completeness or order execution authority."
            ),
        }


async def collect_fast_control(
    control: FastL2Control,
    *,
    duration_seconds: int,
    receipts: TextIO,
) -> tuple[dict[str, object], bool]:
    from websockets.asyncio.client import connect

    deadline_ns = control.probe.start_ns + duration_seconds * 1_000_000_000
    errors: list[str] = []
    while time.monotonic_ns() < deadline_ns and control.probe.connections < 4:
        control.probe.connections += 1
        try:
            async with connect(
                MAINNET_WS_URL,
                ping_interval=15,
                ping_timeout=15,
                max_size=2**22,
            ) as socket:
                conn = JsonWsConnection(socket)
                for market in DEFAULT_MARKETS:
                    await conn.send_json(fast_control_subscription(market))
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
                            raise TimeoutError("no fast public socket messages") from None
                        await conn.send_json({"method": "ping"})
                        continue
                    timeouts = 0
                    now_ns = time.monotonic_ns()
                    now_utc_ms = time.time_ns() // 1_000_000
                    receipt = control.ingest(
                        message,
                        receive_utc_ms=now_utc_ms,
                        monotonic_ns=now_ns,
                    )
                    if receipt is not None:
                        receipts.write(json.dumps(receipt, sort_keys=True) + "\n")
                if time.monotonic_ns() >= deadline_ns:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Only error *types* appear in artifacts, not provider content.
            control.probe.connection_errors += 1
            errors.append(type(exc).__name__)
            if time.monotonic_ns() < deadline_ns:
                await asyncio.sleep(min(2**min(control.probe.connections, 2), 4))
    result = control.summary(end_ns=time.monotonic_ns())
    result["connection_error_types"] = errors
    complete = time.monotonic_ns() >= deadline_ns and result["unique_books"] != 0
    result["observation_window_completed"] = complete
    return result, complete


def compare_control(
    full: Mapping[str, Any], fast: Mapping[str, Any],
) -> dict[str, object]:
    """Strict read-only comparison; no production source switch is possible."""
    if (
        full.get("market_cohort") != list(DEFAULT_MARKETS)
        or fast.get("market_cohort") != list(DEFAULT_MARKETS)
    ):
        raise ValueError("mismatched or incomplete public market cohort")
    full_markets = cast(dict[str, dict[str, Any]], full["markets"])
    fast_markets = cast(dict[str, dict[str, Any]], fast["markets"])
    comparable = (
        full.get("observation_window_completed") is True
        and fast.get("observation_window_completed") is True
        and full.get("connections") == 1
        and fast.get("connections") == 1
        and full.get("connection_errors") == 0
        and fast.get("connection_errors") == 0
        and full.get("protocol_errors") == 0
        and fast.get("protocol_errors") == 0
        and fast.get("unexpected_more_than_5_levels_count") == 0
        and fast.get("zero_sided_depth_count") == 0
        and full.get("duration_ms", 0) >= 180_000
        and fast.get("duration_ms", 0) >= 180_000
    )
    market_rows: dict[str, dict[str, object]] = {}
    for market in DEFAULT_MARKETS:
        deep = full_markets[market]
        shallow = fast_markets[market]
        valid = (
            deep["unique"] >= MIN_UNIQUE_PER_MARKET
            and deep["both_sides_20_levels"] == deep["unique"]
            and deep["out_of_order"] == 0
            and deep["source_future_dated"] == 0
            and shallow["unique"] >= MIN_UNIQUE_PER_MARKET
            and shallow["max_bid_levels"] <= 5
            and shallow["max_ask_levels"] <= 5
            and shallow["max_bid_levels"] > 0
            and shallow["max_ask_levels"] > 0
            and shallow["out_of_order"] == 0
            and shallow["source_future_dated"] == 0
        )
        comparable = comparable and valid
        deep3 = float(deep["fresh_3s_time_fraction"])
        control3 = float(shallow["control_source_age_under_3s_fraction"])
        market_rows[market] = {
            "default_20x20_unique_books": deep["unique"],
            "fast_control_unique_books": shallow["unique"],
            "default_full_depth_source_age_under_3s": deep3,
            "fast_5_level_control_source_age_under_3s": control3,
            "control_minus_full_age_fraction": round(control3 - deep3, 6),
            "default_20x20_depth_observed": deep["both_sides_20_levels"] == deep["unique"],
            "fast_control_max_levels_each_side": [
                shallow["max_bid_levels"], shallow["max_ask_levels"]
            ],
            "fast_control_20x20_eligible": False,
        }
    return {
        "schema": SCHEMA,
        "mode": "two_simultaneous_public_sockets_READ_ONLY",
        "market_cohort": list(DEFAULT_MARKETS),
        "full_public_duration_ms": full["duration_ms"],
        "fast_control_duration_ms": fast["duration_ms"],
        "diagnostic_comparison_valid": comparable,
        "markets": market_rows,
        "full_depth_source_swap_authorized": False,
        "five_level_execution_authorized": False,
        "signed_market_evidence_changed": False,
        "live_trading_authorized": False,
        "profitability_verified": False,
        "warning": (
            "Fast:true is a five-level timing CONTROL ONLY. Faster five-level "
            "data cannot satisfy strategy's full-depth eligibility, signed "
            "source continuity or after-cost trading proof."
        ),
    }


async def simultaneous_collect(
    output: Path, *, duration_seconds: int,
) -> tuple[dict[str, object], bool]:
    """Launch both independent websocket subscribers over one shared interval."""
    if not 180 <= duration_seconds <= 900:
        raise ValueError("require 180-900 seconds for paired public observations")
    output.mkdir(parents=True, exist_ok=True)
    start_ns = time.monotonic_ns()
    full_probe = FullDepthCadenceProbe(DEFAULT_MARKETS, start_ns=start_ns)
    control = FastL2Control(DEFAULT_MARKETS, start_ns=start_ns)
    full_path = output / "full-20x20-receipts.jsonl"
    fast_path = output / "fast-5level-control-receipts.jsonl"
    with full_path.open("x", encoding="utf-8") as full_out, fast_path.open(
        "x", encoding="utf-8"
    ) as fast_out:
        (deep, deep_ok), (fast, fast_ok) = await asyncio.gather(
            collect_full_depth(
                full_probe, duration_seconds=duration_seconds, receipts=full_out,
            ),
            collect_fast_control(
                control, duration_seconds=duration_seconds, receipts=fast_out,
            ),
        )
    completed_utc = datetime.now(UTC).isoformat()
    for result, path, name in (
        (deep, full_path, "full-20x20-summary.json"),
        (fast, fast_path, "fast-5level-control-summary.json"),
    ):
        result["receipts_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        result["wall_clock_ended_utc"] = completed_utc
        (output / name).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    comparison = compare_control(deep, fast)
    (output / "comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return comparison, bool(deep_ok and fast_ok and comparison["diagnostic_comparison_valid"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("public-depth-control")
    )
    args = parser.parse_args(argv)
    if not 180 <= args.duration_seconds <= 900:
        parser.error("duration-seconds must be between 180 and 900")
    comparison, completed = asyncio.run(
        simultaneous_collect(args.out_dir, duration_seconds=args.duration_seconds)
    )
    print(json.dumps({
        "diagnostic_comparison_valid": comparison["diagnostic_comparison_valid"],
        "both_windows_completed": completed,
        "five_level_execution_authorized": False,
        "full_depth_source_swap_authorized": False,
    }))
    return 0 if completed else 2


if __name__ == "__main__":
    raise SystemExit(main())
