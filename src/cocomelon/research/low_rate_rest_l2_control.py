"""Read-only low-rate public REST full-depth L2 versus public WS control.

Test whether POST /info type=l2Book produces *distinct*, sufficiently deep
20x20 snapshots more often than the default public websocket without using a
paid feed. This is a bounded three-coin diagnostic (<=360 REST weight/minute),
not an approved order feed, gap repair, or method for bypassing freshness gates.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO, cast

from cocomelon.research.full_depth_cadence_probe import (
    DEFAULT_MARKETS,
    FullDepthCadenceProbe,
)
from cocomelon.research.full_depth_cadence_probe import (
    collect as collect_public_ws,
)

SCHEMA = "low-rate-rest-full-depth-control-v1"
URL = "https://api.hyperliquid.xyz/info"
# Exactly 3 of the existing 20 PAPER-cohort symbols; do not poll 20 at 1Hz.
COHORT = ("BLUR", "BOME", "CASHCAT")
POLL_INTERVAL_MS = 1_000
REQUEST_WEIGHT = 2
MAX_REQUESTS_PER_MINUTE = 180
WEIGHT_BUDGET_PER_MINUTE = MAX_REQUESTS_PER_MINUTE * REQUEST_WEIGHT
MAX_BODY_BYTES = 256_000
HTTP_TIMEOUT_SECONDS = 4


def public_l2_request(market: str) -> urllib.request.Request:
    if market not in COHORT or market not in DEFAULT_MARKETS:
        raise ValueError("REST probe limited to three frozen markets")
    body = json.dumps(
        {"type": "l2Book", "coin": market}, separators=(",", ":")
    ).encode("utf-8")
    return urllib.request.Request(
        URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def get_public_rest_l2(market: str) -> dict[str, object]:
    """Only read /info with bounded response and timeout. Never authenticate."""
    request = public_l2_request(market)
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as res:
        if res.status != 200:
            raise ValueError("public REST HTTP response unsuccessful")
        data = res.read(MAX_BODY_BYTES + 1)
    if len(data) > MAX_BODY_BYTES:
        raise ValueError("public REST book exceeds diagnostic byte cap")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("public REST L2 was not an object")
    return cast(dict[str, object], value)


class RestFullDepthControl:
    """Use identical source-age parser/dedup rules on REST snapshots."""

    def __init__(self, *, start_ns: int) -> None:
        self.probe = FullDepthCadenceProbe(COHORT, start_ns=start_ns)
        self.request_count = 0
        self.http_error_count = 0
        self.invalid_response_count = 0
        self.http_max_latency_ms = 0.0
        self.http_total_latency_ms = 0.0
        self.http_429_count = 0

    def observe(
        self,
        market: str,
        book: Mapping[str, object],
        *,
        monotonic_ns: int,
        receive_utc_ms: int,
        request_latency_ms: float,
    ) -> dict[str, object] | None:
        if market not in COHORT:
            raise ValueError("unexpected REST market")
        if book.get("coin") != market:
            self.invalid_response_count += 1
            return None
        receipt = self.probe.ingest(
            {"channel": "l2Book", "data": dict(book)},
            monotonic_ns=monotonic_ns,
            receive_utc_ms=receive_utc_ms,
        )
        if receipt is None:
            self.invalid_response_count += 1
            return None
        return {
            **receipt,
            "schema": SCHEMA,
            "http_request_latency_ms": round(request_latency_ms, 2),
            "full_depth_20x20_observed": (
                cast(int, receipt["bid_levels"]) >= 20
                and cast(int, receipt["ask_levels"]) >= 20
            ),
            "production_trading_authorized": False,
        }

    def summary(self, *, end_ns: int) -> dict[str, object]:
        base = self.probe.summary(end_ns=end_ns)
        return {
            **base,
            "schema": SCHEMA,
            "mode": "independent_low_rate_PUBLIC_REST_read_only",
            "rest_url": URL,
            "request_weight": REQUEST_WEIGHT,
            "rate_ceiling_per_minute_weight": WEIGHT_BUDGET_PER_MINUTE,
            "poll_interval_ms": POLL_INTERVAL_MS,
            "http_requests": self.request_count,
            "http_errors": self.http_error_count,
            "http_429_count": self.http_429_count,
            "invalid_responses": self.invalid_response_count,
            "http_max_latency_ms": round(self.http_max_latency_ms, 2),
            "http_mean_latency_ms": round(
                self.http_total_latency_ms / max(1, self.request_count), 2
            ),
            "source_completeness_certified": False,
            "production_trading_authorized": False,
            "five_level_books_substituted": False,
            "live_execution_authorized": False,
            "profitability_verified": False,
            "warning": (
                "Rate-limited public REST full-depth candidate is a DIAGNOSTIC. "
                "Fresh book time does not establish continuous signed source "
                "evidence, quota headroom for 20 markets, latency or profitability."
            ),
        }


async def collect_rest(
    probe: RestFullDepthControl,
    *,
    duration_seconds: int,
    receipts: TextIO,
) -> tuple[dict[str, object], bool]:
    """At most one public REST call per second per coin; no catch-up bursts."""
    deadline_ns = probe.probe.start_ns + duration_seconds * 1_000_000_000

    async def one(market: str) -> None:
        began_ns = time.monotonic_ns()
        probe.request_count += 1
        try:
            book = await asyncio.to_thread(get_public_rest_l2, market)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            probe.http_error_count += 1
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                probe.http_429_count += 1
            return
        arrived_ns = time.monotonic_ns()
        arrived_utc_ms = time.time_ns() // 1_000_000
        latency_ms = (arrived_ns - began_ns) / 1_000_000
        probe.http_total_latency_ms += latency_ms
        probe.http_max_latency_ms = max(probe.http_max_latency_ms, latency_ms)
        if arrived_ns > deadline_ns:
            return
        receipt = probe.observe(
            market,
            book,
            monotonic_ns=arrived_ns,
            receive_utc_ms=arrived_utc_ms,
            request_latency_ms=latency_ms,
        )
        if receipt is not None:
            receipts.write(json.dumps(receipt, sort_keys=True) + "\n")

    tick = 0
    while tick < duration_seconds:
        due_ns = probe.probe.start_ns + tick * 1_000_000_000
        remaining_ns = deadline_ns - time.monotonic_ns()
        if remaining_ns <= 0:
            break
        await asyncio.sleep(max(0.0, (due_ns - time.monotonic_ns()) / 1_000_000_000))
        if time.monotonic_ns() >= deadline_ns:
            break
        await asyncio.gather(*(one(market) for market in COHORT))
        # Drop missed time slots rather than burst against IP rate limits.
        tick = max(
            tick + 1,
            (time.monotonic_ns() - probe.probe.start_ns) // 1_000_000_000 + 1,
        )
    # There may be no call due at the exact end. Preserve a real 180s
    # observation interval rather than falsely declaring an early exit.
    remaining_ns = deadline_ns - time.monotonic_ns()
    if remaining_ns > 0:
        await asyncio.sleep(remaining_ns / 1_000_000_000)
    result = probe.summary(end_ns=time.monotonic_ns())
    result["observation_window_completed"] = (
        cast(float, result["duration_ms"]) >= duration_seconds * 1_000
        and result["http_errors"] == 0
        and result["invalid_responses"] == 0
        and result["unique_books"] != 0
    )
    return result, bool(result["observation_window_completed"])


def compare_rest_vs_ws(
    rest: Mapping[str, Any], ws: Mapping[str, Any]
) -> dict[str, object]:
    if (
        rest.get("market_cohort") != list(COHORT)
        or ws.get("market_cohort") != list(COHORT)
    ):
        raise ValueError("market cohort mismatch")
    rest_markets = cast(dict[str, dict[str, Any]], rest["markets"])
    ws_markets = cast(dict[str, dict[str, Any]], ws["markets"])
    valid = (
        rest.get("observation_window_completed") is True
        and ws.get("observation_window_completed") is True
        and rest.get("http_errors") == 0
        and rest.get("invalid_responses") == 0
        and rest.get("http_429_count") == 0
        and rest.get("rate_ceiling_per_minute_weight") == WEIGHT_BUDGET_PER_MINUTE
        and rest.get("http_requests", 0) <= duration_request_limit(
            int(float(rest.get("duration_ms", 0)))
        )
        and ws.get("connections") == 1
        and ws.get("connection_errors") == 0
        and ws.get("protocol_errors") == 0
    )
    details: dict[str, dict[str, object]] = {}
    for market in COHORT:
        a = rest_markets[market]
        b = ws_markets[market]
        valid = valid and all(
            (
                value["unique"] >= 20
                and value["both_sides_20_levels"] == value["unique"]
                and value["source_future_dated"] == 0
                and value["out_of_order"] == 0
            )
            for value in (a, b)
        )
        details[market] = {
            "rest_distinct_20x20_books": a["unique"],
            "ws_distinct_20x20_books": b["unique"],
            "rest_3s_fresh_time": a["fresh_3s_time_fraction"],
            "ws_3s_fresh_time": b["fresh_3s_time_fraction"],
            "rest_full_depth_observed": a["both_sides_20_levels"] == a["unique"],
            "ws_full_depth_observed": b["both_sides_20_levels"] == b["unique"],
            "rest_source_production_ready": False,
        }
    return {
        "schema": SCHEMA + "-paired-v1",
        "valid_diagnostic": valid,
        "markets": details,
        "rest_requests": rest["http_requests"],
        "rest_rate_weight_cap_per_minute": WEIGHT_BUDGET_PER_MINUTE,
        "production_source_switch_authorized": False,
        "gap_history_repaired": False,
        "paper_order_or_account_changed": False,
        "live_execution_authorized": False,
        "after_cost_profit_verified": False,
        "caution": (
            "Three-coin REST poll diagnostics cannot prove sustainable "
            "20-market rate-limit headroom, signed source continuity, or "
            "a tradable/after-cost profitable market data stream."
        ),
    }


def duration_request_limit(duration_ms: int) -> int:
    """No more than one request/coin/second, incl. bounded poll slack."""
    return len(COHORT) * (duration_ms // POLL_INTERVAL_MS + 1)


async def run_probe(out_dir: Path, *, duration_seconds: int) -> tuple[dict[str, object], bool]:
    if not 180 <= duration_seconds <= 900:
        raise ValueError("diagnostic duration must be 180-900 seconds")
    out_dir.mkdir(parents=True, exist_ok=True)
    start_ns = time.monotonic_ns()
    rest_probe = RestFullDepthControl(start_ns=start_ns)
    ws_probe = FullDepthCadenceProbe(COHORT, start_ns=start_ns)
    rest_path = out_dir / "rest-full-depth-receipts.jsonl"
    ws_path = out_dir / "ws-full-depth-receipts.jsonl"
    with rest_path.open("x", encoding="utf-8") as rest_out, ws_path.open(
        "x", encoding="utf-8"
    ) as ws_out:
        (rest, rest_ok), (ws, ws_ok) = await asyncio.gather(
            collect_rest(
                rest_probe, duration_seconds=duration_seconds, receipts=rest_out
            ),
            collect_public_ws(
                ws_probe, duration_seconds=duration_seconds, receipts=ws_out
            ),
        )
    finish_utc = datetime.now(UTC).isoformat()
    for result, path, summary_path in (
        (rest, rest_path, "rest-full-depth-summary.json"),
        (ws, ws_path, "ws-full-depth-summary.json"),
    ):
        result["receipts_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        result["wall_clock_ended_utc"] = finish_utc
        (out_dir / summary_path).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    comparison = compare_rest_vs_ws(rest, ws)
    (out_dir / "comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return comparison, bool(rest_ok and ws_ok and comparison["valid_diagnostic"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--out-dir", type=Path, default=Path("public-rest-full-depth"))
    args = parser.parse_args(argv)
    if not 180 <= args.duration_seconds <= 900:
        parser.error("duration-seconds must be between 180 and 900")
    result, valid = asyncio.run(
        run_probe(args.out_dir, duration_seconds=args.duration_seconds)
    )
    print(json.dumps({
        "valid_diagnostic": result["valid_diagnostic"],
        "production_source_switch_authorized": False,
        "live_execution_authorized": False,
    }))
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
