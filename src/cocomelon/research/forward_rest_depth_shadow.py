"""Default-off, nonexecuting public REST full-depth PAPER observer.

This module NEVER submits books to strategy, journal, gap repair or execution.
An enabled experiment MUST reuse the PAPER InfoClient instance's request
budget, and must run on its same process/IP to make quota accounting relevant.
Other processes sharing an IP are NOT observed: no production certification.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO, cast

from cocomelon.config import ExecutionMode, Settings
from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.client import InfoClient, InfoHttpError
from cocomelon.hyperliquid.rate_limit import RollingRateBudget
from cocomelon.research.full_depth_cadence_probe import FullDepthCadenceProbe
from cocomelon.research.low_rate_rest_l2_control import COHORT

SCHEMA = "bounded-paper-public-rest-depth-shadow-v1"
SHADOW_WEIGHT_PER_MINUTE = 360
SOURCE_AGE_LIMITS_MS = (3_000, 5_000)
MAX_SECONDS = 3_600
MIN_SECONDS = 30


class ShadowInfoReader(Protocol):
    def try_shadow_l2_book(self, market: MarketId) -> tuple[bool, object | None]: ...


@dataclass(frozen=True)
class RestShadowConfig:
    enabled: bool = False
    markets: tuple[str, ...] = COHORT
    duration_seconds: int = 180
    poll_interval_ms: int = 1_000

    def __post_init__(self) -> None:
        if self.markets != COHORT:
            raise ValueError("REST shadow only permits the frozen 3-market cohort")
        if not MIN_SECONDS <= self.duration_seconds <= MAX_SECONDS:
            raise ValueError("REST shadow duration must be 30–3600 seconds")
        if self.poll_interval_ms < 1_000:
            raise ValueError("REST shadow must not poll more than once per second")


@dataclass
class _DepthClock:
    last_ns: int | None = None
    age_ms: int = 0
    is_full_depth: bool = False
    covered_3_ns: int = 0
    covered_5_ns: int = 0

    def segment(self, now_ns: int, threshold_ms: int) -> int:
        if self.last_ns is None or now_ns <= self.last_ns or not self.is_full_depth:
            return 0
        budget_ns = max(0, threshold_ms - self.age_ms) * 1_000_000
        return min(now_ns - self.last_ns, budget_ns)

    def advance(self, now_ns: int) -> None:
        self.covered_3_ns += self.segment(now_ns, SOURCE_AGE_LIMITS_MS[0])
        self.covered_5_ns += self.segment(now_ns, SOURCE_AGE_LIMITS_MS[1])
        self.last_ns = now_ns

    def update(self, *, now_ns: int, age_ms: int, full_depth: bool) -> None:
        self.advance(now_ns)
        self.age_ms = age_ms
        self.is_full_depth = full_depth and age_ms >= 0

    def revoke(self, now_ns: int) -> None:
        self.advance(now_ns)
        self.is_full_depth = False

    def read(self, *, now_ns: int, start_ns: int) -> dict[str, object]:
        total = max(1, now_ns - start_ns)
        return {
            "full_depth_source_fresh_3000_fraction": round(
                min(1.0, (self.covered_3_ns + self.segment(now_ns, 3_000)) / total),
                6,
            ),
            "full_depth_source_fresh_5000_fraction": round(
                min(1.0, (self.covered_5_ns + self.segment(now_ns, 5_000)) / total),
                6,
            ),
        }


class RestDepthShadow:
    """Independent in-memory research accounting, never paper source authority."""

    def __init__(
        self,
        reader: ShadowInfoReader,
        *,
        config: RestShadowConfig,
        start_ns: int,
        slice_budget: RollingRateBudget | None = None,
    ) -> None:
        if not config.enabled:
            raise ValueError("REST observer is disabled by default")
        self.reader = reader
        self.config = config
        self.start_ns = start_ns
        self.slice_budget = slice_budget or RollingRateBudget(
            limit=SHADOW_WEIGHT_PER_MINUTE
        )
        self.probe = FullDepthCadenceProbe(config.markets, start_ns=start_ns)
        self.clocks = {coin: _DepthClock() for coin in config.markets}
        self.attempts = 0
        self.http_requests = 0
        self.quota_skipped = 0
        self.shadow_slice_skipped = 0
        self.http_errors = 0
        self.protocol_failures = 0
        self.shallow = 0
        self.future_dated = 0
        self.out_of_order = 0
        self.duplicate = 0
        self.missed_poll_count = 0
        self.http_429_count = 0
        self.circuit_skipped_count = 0
        self.http_circuit_open = False

    def record(
        self,
        market: str,
        response: object | None,
        *,
        now_ns: int,
        utc_ms: int,
        result: str,
        http_ms: float = 0.0,
        is_rate_limit: bool = False,
    ) -> dict[str, object]:
        if market not in self.clocks or now_ns < self.start_ns:
            raise ValueError("invalid shadow market or clock")
        self.attempts += 1
        data: dict[str, object] = {
            "schema": SCHEMA,
            "market": market,
            "receipt_elapsed_ms": round((now_ns - self.start_ns) / 1_000_000, 2),
            "receive_utc_ms": utc_ms,
            "status": result,
            "http_latency_ms": round(http_ms, 2),
            "source_authority": False,
            "account_or_order_changed": False,
        }
        if result == "missed_poll":
            self.missed_poll_count += 1
        elif result == "rate_limit_circuit_open":
            self.circuit_skipped_count += 1
        elif result == "shadow_budget_skipped":
            self.shadow_slice_skipped += 1
        elif result == "shared_budget_skipped":
            self.quota_skipped += 1
        elif result == "http_error":
            # A shared-budget reservation has been consumed. Count an
            # attempted HTTP call even if its response never arrived.
            self.http_requests += 1
            self.http_errors += 1
            self.clocks[market].revoke(now_ns)
            if is_rate_limit:
                # Hard stop across ALL markets for the remaining observation
                # window. Concurrent requests already in-flight may finish.
                self.http_429_count += 1
                self.http_circuit_open = True
                data["http_429"] = True
        elif result == "ok":
            self.http_requests += 1
            if not isinstance(response, dict) or response.get("coin") != market:
                self.protocol_failures += 1
                self.clocks[market].revoke(now_ns)
                data["status"] = "invalid"
            else:
                normalized = self.probe.ingest(
                    {"channel": "l2Book", "data": response},
                    receive_utc_ms=utc_ms,
                    monotonic_ns=now_ns,
                )
                if normalized is None:
                    self.protocol_failures += 1
                    self.clocks[market].revoke(now_ns)
                    data["status"] = "invalid"
                else:
                    data.update({
                        "status": normalized["result"],
                        "exchange_ms": normalized["exchange_ms"],
                        "source_age_ms": normalized["source_age_ms"],
                        "bid_levels": normalized["bid_levels"],
                        "ask_levels": normalized["ask_levels"],
                        "raw_message_sha256": normalized["raw_message_sha256"],
                    })
                    kind = cast(str, normalized["result"])
                    if kind == "unique":
                        full = (
                            cast(int, normalized["bid_levels"]) >= 20
                            and cast(int, normalized["ask_levels"]) >= 20
                        )
                        age = cast(int, normalized["source_age_ms"])
                        self.shallow += int(not full)
                        self.future_dated += int(age < 0)
                        self.clocks[market].update(
                            now_ns=now_ns, age_ms=age, full_depth=full,
                        )
                    elif kind == "duplicate":
                        self.duplicate += 1
                        # No refresh of the source clock, even on a fresh
                        # HTTP response carrying a cached book.
                    else:
                        self.out_of_order += 1
                        self.clocks[market].revoke(now_ns)
        else:
            raise ValueError("unknown REST-shadow result")
        return data

    def summary(self, *, now_ns: int) -> dict[str, object]:
        if now_ns < self.start_ns:
            raise ValueError("negative shadow observation duration")
        markets = cast(dict[str, dict[str, object]], self.probe.summary(
            end_ns=now_ns
        )["markets"])
        report: dict[str, object] = {
            "schema": SCHEMA,
            "mode": "READ_ONLY_UNCERTIFIED_REST_PAPER_SHADOW",
            "enabled": True,
            "cohort": list(self.config.markets),
            "elapsed_ms": round((now_ns - self.start_ns) / 1_000_000, 2),
            "scheduled_attempts": self.attempts,
            "duration_seconds": self.config.duration_seconds,
            "poll_interval_ms": self.config.poll_interval_ms,
            "expected_poll_ticks": (
                self.config.duration_seconds * 1000
                + self.config.poll_interval_ms - 1
            ) // self.config.poll_interval_ms,
            "missed_poll_count": self.missed_poll_count,
            "http_429_count": self.http_429_count,
            "rate_limit_circuit_open": self.http_circuit_open,
            "rate_limit_circuit_skips": self.circuit_skipped_count,
            "actual_http_requests": self.http_requests,
            "shared_budget_skips": self.quota_skipped,
            "shadow_slice_budget_skips": self.shadow_slice_skipped,
            "http_errors": self.http_errors,
            "protocol_failures": self.protocol_failures,
            "shallow_books": self.shallow,
            "future_dated_books": self.future_dated,
            "out_of_order_books": self.out_of_order,
            "duplicate_books": self.duplicate,
            "shadow_weight_ceiling_per_rolling_minute": SHADOW_WEIGHT_PER_MINUTE,
            "assumed_same_ip_process_budget": False,
            "other_process_ip_weight_verified": False,
            "source_completeness_certified": False,
            "production_source_authorized": False,
            "signed_gap_history_changed": False,
            "paper_account_changed": False,
            "execution_authority": False,
            "profitability_verified": False,
            "markets": {
                market: {**markets[market], **clock.read(
                    now_ns=now_ns, start_ns=self.start_ns
                )}
                for market, clock in self.clocks.items()
            },
        }
        # This is the original PAPER InfoClient's in-process rate ledger,
        # not proof that a NAT egress IP is dedicated to this worker.
        if type(self.reader) is InfoClient:
            local = cast(InfoClient, self.reader).rest_budget_snapshot()
            if local is not None:
                report["same_reader_rest_budget_snapshot"] = local
        return report

    async def poll_one(self, market: str, *, now_ns: int) -> dict[str, object]:
        if market not in self.config.markets:
            raise ValueError("noncohort shadow request")
        if self.http_circuit_open:
            return self.record(
                market, None, now_ns=now_ns,
                utc_ms=time.time_ns() // 1_000_000,
                result="rate_limit_circuit_open",
            )
        if not self.slice_budget.try_acquire(2):
            return self.record(
                market, None, now_ns=now_ns,
                utc_ms=time.time_ns() // 1_000_000, result="shadow_budget_skipped",
            )
        began = time.monotonic_ns()
        try:
            allowed, response = await asyncio.to_thread(
                self.reader.try_shadow_l2_book,
                MarketId(dex="", coin=market),
            )
        except Exception as exc:
            # No retries and no error-body or credential leakage.
            is_429 = isinstance(exc, InfoHttpError) and exc.status == 429
            return self.record(
                market, None, now_ns=time.monotonic_ns(),
                utc_ms=time.time_ns() // 1_000_000, result="http_error",
                is_rate_limit=is_429,
            )
        ended = time.monotonic_ns()
        return self.record(
            market, response if allowed else None, now_ns=ended,
            utc_ms=time.time_ns() // 1_000_000,
            result="ok" if allowed else "shared_budget_skipped",
            http_ms=(ended - began) / 1_000_000,
        )


async def collect_shadow(
    shadow: RestDepthShadow,
    *,
    receipts: TextIO,
    stop_requested: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """No catch-up requests. Runs only after explicit enabled config."""
    start_ns = shadow.start_ns
    duration = shadow.config.duration_seconds
    interval_ns = shadow.config.poll_interval_ms * 1_000_000
    ticks = (duration * 1_000_000_000 + interval_ns - 1) // interval_ns
    deadline = start_ns + duration * 1_000_000_000
    for tick in range(ticks):
        if stop_requested is not None and stop_requested():
            break
        due = start_ns + tick * interval_ns
        now = time.monotonic_ns()
        if now >= deadline:
            break
        if due > now:
            await asyncio.sleep((due - now) / 1_000_000_000)
        if time.monotonic_ns() >= deadline or (
            stop_requested is not None and stop_requested()
        ):
            break
        # Record every missed poll as NOT-FRESH evidence: silently dropping
        # slots previously let a 180s run look "complete" with almost no
        # source coverage. Never make network catch-up calls.
        if time.monotonic_ns() - due >= interval_ns:
            for market in shadow.config.markets:
                missed = shadow.record(
                    market, None, now_ns=time.monotonic_ns(),
                    utc_ms=time.time_ns() // 1_000_000, result="missed_poll",
                )
                missed["slot_index"] = tick
                receipts.write(json.dumps(missed, sort_keys=True) + "\n")
            continue
        rows = await asyncio.gather(*(
            shadow.poll_one(market, now_ns=time.monotonic_ns())
            for market in shadow.config.markets
        ))
        for row in rows:
            row["slot_index"] = tick
            receipts.write(json.dumps(row, sort_keys=True) + "\n")
    remaining = deadline - time.monotonic_ns()
    if remaining > 0 and (stop_requested is None or not stop_requested()):
        await asyncio.sleep(remaining / 1_000_000_000)
    report = shadow.summary(now_ns=time.monotonic_ns())
    markets = cast(dict[str, dict[str, object]], report["markets"])
    report["observation_window_completed"] = (
        cast(float, report["elapsed_ms"]) >= duration * 1_000
        and shadow.attempts == ticks * len(shadow.config.markets)
        and shadow.missed_poll_count == 0
        and shadow.http_429_count == 0
        and shadow.circuit_skipped_count == 0
        and shadow.http_errors == 0
        and shadow.protocol_failures == 0
        and shadow.shallow == 0
        and shadow.future_dated == 0
        and shadow.out_of_order == 0
        and shadow.quota_skipped == 0
        and shadow.shadow_slice_skipped == 0
        and all(
            cast(int, markets[m]["unique"]) >= 2
            for m in shadow.config.markets
        )
    )
    return report


async def run_to_files(
    reader: ShadowInfoReader,
    config: RestShadowConfig,
    out_dir: Path,
    *,
    stop_requested: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Explicit opt-in research files, NEVER paper journals or checkpoints."""
    if not config.enabled:
        return {"schema": SCHEMA, "enabled": False, "network_calls": 0}
    out_dir.mkdir(parents=True, exist_ok=False)
    raw_path = out_dir / "shadow-attempts.jsonl"
    shadow = RestDepthShadow(
        reader, config=config, start_ns=time.monotonic_ns()
    )
    interrupted = False
    with raw_path.open("x", encoding="utf-8") as receipts:
        try:
            summary = await collect_shadow(
                shadow, receipts=receipts, stop_requested=stop_requested,
            )
        except asyncio.CancelledError:
            # A PAPER upgrade must never wait for REST shadow evidence. Save
            # only an incomplete research receipt; re-raise cancellation.
            interrupted = True
            summary = shadow.summary(now_ns=time.monotonic_ns())
            summary["observation_window_completed"] = False
    summary["interrupted"] = interrupted
    summary["receipt_sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    summary["ended_utc"] = time.time_ns() // 1_000_000
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if interrupted:
        raise asyncio.CancelledError
    return summary


# Both variables must be deliberately set by the operator. A flag is NOT
# proof of a dedicated public IP or a complete cross-process rate ledger.
ENABLED_ENV = "COCOMELON_PAPER_REST_SHADOW_ENABLED"
IP_QUOTA_ENV = "COCOMELON_PAPER_REST_SHADOW_SHARED_IP_ACCOUNTED"


def attached_shadow_allowed(
    reader: InfoClient,
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """No implicit activation on deploy or predecessor handoff."""
    flags = os.environ if environ is None else environ
    if flags.get(ENABLED_ENV) != "1":
        return False
    if flags.get(IP_QUOTA_ENV) != "1":
        return False
    if settings.execution_mode is not ExecutionMode.PAPER:
        return False
    # The PAPER worker must hand us its existing production InfoClient.
    # Its single shared budget guards both mandatory and optional reads.
    return type(reader) is InfoClient


def start_attached_paper_shadow(
    reader: InfoClient,
    settings: Settings,
    state_root: Path,
    *,
    session_started_ms: int,
    stop_requested: Callable[[], bool],
    environ: Mapping[str, str] | None = None,
) -> asyncio.Task[None] | None:
    """Schedule a research-only single window; zero side effects when off."""
    if not attached_shadow_allowed(reader, settings, environ=environ):
        return None
    if stop_requested():
        return None

    async def observe() -> None:
        try:
            result = await run_to_files(
                reader,
                RestShadowConfig(enabled=True),
                state_root / f"rest-depth-research-only-{session_started_ms}",
                stop_requested=stop_requested,
            )
            print(
                "PAPER_REST_DEPTH_SHADOW_RESEARCH "
                + json.dumps({
                    "completed": result.get("observation_window_completed") is True,
                    "source_authorized": False,
                    "execution_authority": False,
                }, sort_keys=True),
                flush=True,
            )
        except asyncio.CancelledError:
            # Upgrades and stop requests always take precedence. Incomplete
            # receipt files, if any, are explicitly not qualifying evidence.
            raise
        except Exception as exc:
            # Never let a research observer kill execution or leak HTTP bodies.
            print(
                "PAPER_REST_DEPTH_SHADOW_ERROR " + type(exc).__name__,
                flush=True,
            )

    return asyncio.create_task(observe(), name="research-only-rest-20depth")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--out-dir", type=Path, default=Path("rest-shadow-observation"))
    args = parser.parse_args(argv)
    config = RestShadowConfig(
        enabled=args.enable, duration_seconds=args.duration_seconds,
    )
    # Standalone cannot observe other processes using the same NAT/IP. It
    # produces *uncertified* diagnostics only, never worker-source authority.
    settings = Settings.from_env()
    if settings.execution_mode is not ExecutionMode.PAPER:
        parser.error("REST shadow refuses any non-PAPER execution mode")
    if not args.enable:
        print(json.dumps({"enabled": False, "network_calls": 0}))
        return 0
    reader = InfoClient(settings, timeout=4, max_attempts=1)
    result = asyncio.run(run_to_files(reader, config, args.out_dir))
    print(json.dumps({
        "enabled": result["enabled"],
        "observation_completed": result.get("observation_window_completed", False),
        "execution_authority": False,
    }))
    return 0 if not args.enable or result.get("observation_window_completed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
