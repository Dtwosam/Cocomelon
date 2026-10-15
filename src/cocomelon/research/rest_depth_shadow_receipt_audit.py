"""Offline fail-closed auditor for nonexecuting PAPER REST shadow slot receipts.

This never connects to exchange, reads orders or changes execution. It checks
each scheduled poll slot and the source timing independently of the producer
summary, which is not a cryptographic venue attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from cocomelon.research.forward_rest_depth_shadow import SCHEMA, _DepthClock
from cocomelon.research.low_rate_rest_l2_control import COHORT

MAX_BYTES = 8_000_000
MAX_ROWS = 12_000
MAX_CLOCK_DRIFT_MS = 1_000
MAX_SUMMARY_END_SKEW_MS = 5_000
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
NON_SOURCE = frozenset({
    "missed_poll", "shadow_budget_skipped", "shared_budget_skipped",
    "http_error", "invalid", "rate_limit_circuit_open",
})
BOOK_STATUS = frozenset({"unique", "duplicate", "out_of_order"})


class ShadowAuditError(ValueError):
    """The diagnostic artifact is incomplete, contradictory or modified."""


def _obj(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ShadowAuditError(f"{name} is not a JSON object")
    return cast(dict[str, Any], value)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ShadowAuditError(f"{name} is not an integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ShadowAuditError(f"{name} is not numeric")
    x = float(value)
    if not math.isfinite(x):
        raise ShadowAuditError(f"{name} is not finite")
    return x


def audit_shadow_receipts(
    summary_path: Path,
    receipts_path: Path,
) -> dict[str, object]:
    """Strict original-byte completeness, clock and status audit.

    Return "provisional observation qualified" only for complete 3x20-level
    research windows. A pass NEVER admits the feed to PAPER/real execution.
    """
    if receipts_path.stat().st_size > MAX_BYTES:
        raise ShadowAuditError("receipt input exceeds size cap")
    summary = _obj(json.loads(summary_path.read_text(encoding="utf-8")), "summary")
    if summary.get("schema") != SCHEMA or summary.get("enabled") is not True:
        raise ShadowAuditError("unknown or disabled shadow receipt schema")
    if summary.get("cohort") != list(COHORT):
        raise ShadowAuditError("shadow cohort does not match frozen three markets")
    if summary.get("source_completeness_certified") is not False:
        raise ShadowAuditError("unsupported venue-source certification claimed")
    for flag in (
        "production_source_authorized", "signed_gap_history_changed",
        "paper_account_changed", "execution_authority", "profitability_verified",
        "other_process_ip_weight_verified",
    ):
        if summary.get(flag) is not False:
            raise ShadowAuditError(f"unsafe authority or IP-certification field: {flag}")
    duration_s = _integer(summary.get("duration_seconds"), "duration_seconds")
    interval_ms = _integer(summary.get("poll_interval_ms"), "poll_interval_ms")
    if not 30 <= duration_s <= 3600 or interval_ms < 1000:
        raise ShadowAuditError("unsupported observation duration or polling interval")
    ticks = (duration_s * 1000 + interval_ms - 1) // interval_ms
    if _integer(summary.get("expected_poll_ticks"), "ticks") != ticks:
        raise ShadowAuditError("expected slot total was changed")
    elapsed_ms = _number(summary.get("elapsed_ms"), "elapsed_ms")
    if elapsed_ms <= 0 or elapsed_ms > duration_s * 1000 + 10_000:
        raise ShadowAuditError("unbounded or invalid elapsed observation window")
    original = receipts_path.read_bytes()
    if hashlib.sha256(original).hexdigest() != summary.get("receipt_sha256"):
        raise ShadowAuditError("original JSONL SHA-256 mismatch")
    rows = original.splitlines()
    if len(rows) > MAX_ROWS:
        raise ShadowAuditError("too many receipt rows")
    expected = ticks * len(COHORT)
    if len(rows) != expected or _integer(
        summary.get("scheduled_attempts"), "scheduled_attempts"
    ) != expected:
        raise ShadowAuditError("missing scheduled REST poll slots")
    seen_slots: set[tuple[str, int]] = set()
    last_elapsed: dict[str, float] = {}
    last_unique_exchange: dict[str, int] = {}
    last_unique_hash: dict[str, str] = {}
    clocks = {m: _DepthClock() for m in COHORT}
    counts: dict[str, int] = defaultdict(int)
    counters = {
        "missed_poll_count": 0,
        "http_429_count": 0,
        "rate_limit_circuit_skips": 0,
        "shared_budget_skips": 0,
        "shadow_slice_budget_skips": 0,
        "http_errors": 0,
        "protocol_failures": 0,
        "shallow_books": 0,
        "future_dated_books": 0,
        "out_of_order_books": 0,
        "duplicate_books": 0,
        "actual_http_requests": 0,
    }
    start_utc_ms: float | None = None
    max_clock_drift = 0.0
    seen_rate_limit = False
    rate_limit_slot: int | None = None
    for line in rows:
        try:
            event = _obj(json.loads(line), "shadow receipt")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ShadowAuditError("invalid JSONL shadow receipt") from exc
        market = event.get("market")
        slot = _integer(event.get("slot_index"), "slot_index")
        if market not in COHORT or not 0 <= slot < ticks:
            raise ShadowAuditError("market or scheduled slot out of bounds")
        assert isinstance(market, str)
        key = (market, slot)
        if key in seen_slots:
            raise ShadowAuditError("repeated market and scheduled slot")
        seen_slots.add(key)
        if event.get("schema") != SCHEMA:
            raise ShadowAuditError("unexpected receipt schema")
        if event.get("source_authority") is not False or event.get(
            "account_or_order_changed"
        ) is not False:
            raise ShadowAuditError("unauthorized research receipt")
        elapsed = _number(event.get("receipt_elapsed_ms"), "receipt_elapsed_ms")
        utc_ms = _integer(event.get("receive_utc_ms"), "receive_utc_ms")
        if not 0 <= elapsed <= elapsed_ms + 150:
            raise ShadowAuditError("receipt elapsed time outside collection window")
        if elapsed < last_elapsed.get(market, -1):
            raise ShadowAuditError("per-market receipt time regressed")
        last_elapsed[market] = elapsed
        # Two locally collected clocks must represent the same observation
        # start. The checksum alone is NOT cryptographic venue attestation.
        inferred_start = utc_ms - elapsed
        if start_utc_ms is None:
            start_utc_ms = inferred_start
        drift = abs(inferred_start - start_utc_ms)
        max_clock_drift = max(max_clock_drift, drift)
        if drift > MAX_CLOCK_DRIFT_MS:
            raise ShadowAuditError("receipt wall/monotonic clocks disagree")
        latency = _number(event.get("http_latency_ms"), "http_latency_ms")
        if not 0 <= latency <= 10_000:
            raise ShadowAuditError("invalid REST HTTP diagnostic latency")
        status = event.get("status")
        now_ns = round(elapsed * 1_000_000)
        # JSONL rows are emitted in complete tick order. A 429 opens a
        # fail-closed circuit for subsequent slots; other same-tick
        # requests might already be in-flight.
        if (
            rate_limit_slot is not None
            and slot > rate_limit_slot
            and status != "rate_limit_circuit_open"
        ):
            raise ShadowAuditError("HTTP requests continued after rate-limit circuit opened")
        if status in NON_SOURCE:
            if any(key in event for key in (
                "exchange_ms", "source_age_ms", "bid_levels", "ask_levels",
                "raw_message_sha256",
            )):
                raise ShadowAuditError("nonsource poll pretended to hold a book")
            if status == "missed_poll":
                counters["missed_poll_count"] += 1
            elif status == "rate_limit_circuit_open":
                if rate_limit_slot is None or slot <= rate_limit_slot:
                    raise ShadowAuditError("rate-limit circuit skip without prior 429")
                counters["rate_limit_circuit_skips"] += 1
            elif status == "shared_budget_skipped":
                counters["shared_budget_skips"] += 1
            elif status == "shadow_budget_skipped":
                counters["shadow_slice_budget_skips"] += 1
            elif status == "http_error":
                counters["actual_http_requests"] += 1
                counters["http_errors"] += 1
                marker = event.get("http_429", False)
                if not isinstance(marker, bool):
                    raise ShadowAuditError("HTTP 429 marker is not boolean")
                if marker:
                    counters["http_429_count"] += 1
                    seen_rate_limit = True
                    if rate_limit_slot is None:
                        rate_limit_slot = slot
                clocks[market].revoke(now_ns)
            else:
                counters["actual_http_requests"] += 1
                counters["protocol_failures"] += 1
                clocks[market].revoke(now_ns)
        elif status in BOOK_STATUS:
            counters["actual_http_requests"] += 1
            source_ms = _integer(event.get("exchange_ms"), "exchange_ms")
            source_age = _integer(event.get("source_age_ms"), "source_age_ms")
            if utc_ms - source_ms != source_age:
                raise ShadowAuditError("receipt exchange source-age arithmetic mismatch")
            bids = _integer(event.get("bid_levels"), "bid_levels")
            asks = _integer(event.get("ask_levels"), "ask_levels")
            if not 0 <= bids <= 100 or not 0 <= asks <= 100:
                raise ShadowAuditError("invalid source level counts")
            sha = event.get("raw_message_sha256")
            if not isinstance(sha, str) or not SHA256_PATTERN.fullmatch(sha):
                raise ShadowAuditError("source book digest malformed")
            if status == "unique":
                if market in last_unique_exchange and (
                    source_ms <= last_unique_exchange[market]
                    or sha == last_unique_hash[market]
                ):
                    raise ShadowAuditError("book replay presented as a new source update")
                last_unique_exchange[market] = source_ms
                last_unique_hash[market] = sha
                counts[market] += 1
                counters["shallow_books"] += int(bids < 20 or asks < 20)
                counters["future_dated_books"] += int(source_age < 0)
                clocks[market].update(
                    now_ns=now_ns, age_ms=source_age,
                    full_depth=bids >= 20 and asks >= 20,
                )
            elif status == "duplicate":
                counters["duplicate_books"] += 1
                if (
                    market not in last_unique_exchange
                    or source_ms != last_unique_exchange[market]
                    or sha != last_unique_hash[market]
                ):
                    raise ShadowAuditError("duplicate receipt not equal to last source")
            else:
                counters["out_of_order_books"] += 1
                clocks[market].revoke(now_ns)
        else:
            raise ShadowAuditError("unknown poll receipt status")

    saved_markets = _obj(summary.get("markets"), "market summaries")
    for market in COHORT:
        item = _obj(saved_markets.get(market), "market summary")
        if _integer(item.get("unique"), f"{market} unique") != counts[market]:
            raise ShadowAuditError("per-market book count mismatch")
        actual = clocks[market].read(
            now_ns=round(elapsed_ms * 1_000_000),
            start_ns=0,
        )
        for threshold in ("3000", "5000"):
            field = f"full_depth_source_fresh_{threshold}_fraction"
            reported = _number(item.get(field), field)
            if abs(reported - cast(float, actual[field])) > 0.0006:
                raise ShadowAuditError("full-depth elapsed freshness differs from receipts")
    for counter_name, observed in counters.items():
        if _integer(summary.get(counter_name), counter_name) != observed:
            raise ShadowAuditError(f"counter mismatch: {counter_name}")
    if summary.get("rate_limit_circuit_open") is not seen_rate_limit:
        raise ShadowAuditError("rate-limit circuit flag conflicts with receipts")
    # Optional local in-process ledger is independently checked for
    # arithmetic consistency. It is NOT an external egress-IP rate audit.
    local_budget = summary.get("same_reader_rest_budget_snapshot")
    if local_budget is not None:
        local = _obj(local_budget, "same-reader quota snapshot")
        if (
            local.get("external_process_ip_weight_verified") is not False
            or local.get("source_or_execution_authority") is not False
        ):
            raise ShadowAuditError("local quota snapshot asserted external IP authority")
        keys = (
            "rolling_window_seconds", "rolling_weight_limit",
            "total_rolling_weight", "required_rolling_weight",
            "shadow_rolling_weight", "other_rolling_weight",
            "peak_total_rolling_weight", "peak_required_rolling_weight",
            "peak_shadow_rolling_weight", "shadow_admitted_lifetime",
            "shadow_denied_lifetime", "shadow_priority_reserve_weight",
        )
        metrics = {name: _integer(local.get(name), name) for name in keys}
        if any(value < 0 for value in metrics.values()):
            raise ShadowAuditError("negative quota-weight snapshot")
        if (
            metrics["rolling_window_seconds"] != 60
            or metrics["rolling_weight_limit"] <= 0
            or metrics["total_rolling_weight"] != (
                metrics["required_rolling_weight"]
                + metrics["shadow_rolling_weight"]
                + metrics["other_rolling_weight"]
            )
            or metrics["total_rolling_weight"] > metrics["rolling_weight_limit"]
            or metrics["peak_total_rolling_weight"] < metrics["total_rolling_weight"]
            or metrics["peak_total_rolling_weight"] > metrics["rolling_weight_limit"]
            or metrics["peak_required_rolling_weight"] < metrics["required_rolling_weight"]
            or metrics["peak_shadow_rolling_weight"] < metrics["shadow_rolling_weight"]
            or metrics["shadow_priority_reserve_weight"] > metrics["rolling_weight_limit"]
        ):
            raise ShadowAuditError("inconsistent same-reader rolling quota snapshot")
    if start_utc_ms is None:
        raise ShadowAuditError("empty source receipts")
    ended_utc_ms = _integer(summary.get("ended_utc"), "ended_utc")
    end_skew = abs(ended_utc_ms - (start_utc_ms + elapsed_ms))
    if end_skew > MAX_SUMMARY_END_SKEW_MS:
        raise ShadowAuditError("summary end UTC disagrees with receipt-derived clock")
    completed = (
        elapsed_ms >= duration_s * 1000
        and all(counts[m] >= 2 for m in COHORT)
        and all(counters[k] == 0 for k in (
            "missed_poll_count", "http_429_count", "rate_limit_circuit_skips",
            "shared_budget_skips",
            "shadow_slice_budget_skips", "http_errors", "protocol_failures",
            "shallow_books", "future_dated_books", "out_of_order_books",
        ))
    )
    if summary.get("observation_window_completed") is not completed:
        raise ShadowAuditError("completion flag contradicts original poll receipts")
    return {
        "schema": "independent-rest-shadow-slot-receipt-audit-v1",
        "receipt_sha256": hashlib.sha256(original).hexdigest(),
        "expected_slots": expected,
        "observed_slots": len(seen_slots),
        "unique_20depth_books_by_market": dict(counts),
        "receipt_max_clock_drift_ms": round(max_clock_drift, 2),
        "window_end_skew_ms": round(end_skew, 2),
        "observation_window_completed": completed,
        "clean_research_receipts": completed and counters["duplicate_books"] == 0,
        "in_process_rate_snapshot_consistent": local_budget is not None,
        "same_ip_external_processes_verified": False,
        "source_completeness_certified": False,
        "production_source_authorized": False,
        "signed_gap_history_changed": False,
        "paper_account_changed": False,
        "execution_authority": False,
        "profitability_verified": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = audit_shadow_receipts(args.summary, args.receipts)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ShadowAuditError) as exc:
        parser.exit(2, f"FAIL CLOSED: {type(exc).__name__}: {exc}\n")
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "receipt_slots_verified": result["observed_slots"],
        "research_window_complete": result["observation_window_completed"],
        "trading_authority": False,
    }))
    return 0 if result["observation_window_completed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
