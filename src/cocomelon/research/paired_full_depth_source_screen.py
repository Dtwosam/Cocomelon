"""Conservative, never-trading comparison of independent L2 source receipts.

Consumes files from the public full-depth probe and optional hosted gRPC
candidate. A PASS means only that both *independent diagnostic windows* meet
a preliminary paired-source research screen. It never authorizes execution,
fills source gaps, certifies venue completeness, or proves profitability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from cocomelon.research.full_depth_cadence_probe import DEFAULT_MARKETS

BASELINE = "passive-l2-cadence-v1"
CANDIDATE = "candidate-grpc-l2-diagnostic-v1"
MAX_RECEIPT_BYTES = 30_000_000
MIN_WINDOW_MS = 180_000
MIN_PAIRED_OVERLAP_MS = 120_000
# The collector samples UTC and monotonic clocks together. On the genuine
# 2026-10-14 public receipts their inferred UTC start differs by <2ms; allow
# bounded runner clock/sampling drift, but never infer an overlap from a
# summary end-time field that the receipt bytes cannot substantiate.
MAX_RECEIPT_CLOCK_DRIFT_MS = 1_000
MAX_SUMMARY_END_SKEW_MS = 5_000
MIN_DISTINCT_PER_MARKET = 20
PRELIMINARY_CANDIDATE_MIN_FRESH_BPS = 9_500
PRELIMINARY_CANDIDATE_MIN_IMPROVEMENT_BPS = 2_000
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class ReceiptAuditError(ValueError):
    """Input fails the independent, fail-closed evidence requirements."""


def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReceiptAuditError(f"{field} must be integer")
    return value


def _as_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ReceiptAuditError(f"{field} must be finite numeric")
    result = float(value)
    if not -1e18 < result < 1e18:
        raise ReceiptAuditError(f"{field} out of range")
    return result


def _dict(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReceiptAuditError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _finish_ms(value: object) -> int:
    if not isinstance(value, str):
        raise ReceiptAuditError("end time must be ISO-8601 string")
    try:
        when = datetime.fromisoformat(value)
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("missing timezone")
        return round(when.timestamp() * 1000)
    except (OverflowError, ValueError) as exc:
        raise ReceiptAuditError("invalid time-aware end timestamp") from exc


def _integrate(
    unique: Sequence[tuple[float, int, bool]],
    duration_ms: float,
    threshold_ms: int,
) -> int:
    """Source-age freshness weighted by monitored elapsed time, basis points."""
    if duration_ms <= 0:
        return 0
    fresh_ms = 0.0
    for i, (arrival_ms, source_age_ms, depth_ok) in enumerate(unique):
        end_ms = unique[i + 1][0] if i + 1 < len(unique) else duration_ms
        if source_age_ms >= 0 and depth_ok and end_ms > arrival_ms:
            fresh_ms += min(end_ms - arrival_ms, max(0, threshold_ms - source_age_ms))
    return min(10_000, int(10_000 * fresh_ms / duration_ms))


def inspect_source(summary_path: Path, receipts_path: Path, *, schema: str) -> dict[str, Any]:
    """Validate original bytes, cohort, source time and report consistency."""
    if schema not in {BASELINE, CANDIDATE}:
        raise ReceiptAuditError("unknown receipt schema")
    if receipts_path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ReceiptAuditError("receipt file exceeds diagnostic size cap")
    summary = _dict(json.loads(summary_path.read_text(encoding="utf-8")), "summary")
    if (summary.get("schema") != schema or summary.get("observation_window_completed") is not True):
        raise ReceiptAuditError("schema mismatch or incomplete observation window")
    public = schema == BASELINE
    cohort = summary.get("market_cohort" if public else "cohort")
    if cohort != list(DEFAULT_MARKETS):
        raise ReceiptAuditError("market cohort differs from frozen 20-market baseline")
    duration = _as_float(
        summary.get("duration_ms" if public else "elapsed_ms"), "duration_ms"
    )
    if duration < MIN_WINDOW_MS or duration > 920_000:
        raise ReceiptAuditError("observation window is outside supported range")
    if public:
        if (
            _as_int(summary.get("connections"), "connections") != 1
            or _as_int(summary.get("connection_errors"), "connection_errors") != 0
            or _as_int(summary.get("protocol_errors"), "protocol_errors") != 0
        ):
            raise ReceiptAuditError("public source disconnected or had errors")
    elif (
        _as_int(summary.get("stream_errors"), "stream_errors") != 0
        or _as_int(summary.get("parse_errors"), "parse_errors") != 0
        or _as_int(summary.get("n_levels_requested"), "n_levels_requested") != 20
    ):
        raise ReceiptAuditError("candidate stream failed or requested wrong depth")

    raw = receipts_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != summary.get("receipts_sha256"):
        raise ReceiptAuditError("raw receipt SHA-256 differs from summary")
    observations: dict[str, list[tuple[float, int, bool]]] = defaultdict(list)
    last_arrival: dict[str, float] = {}
    last_height: dict[str, int] = {}
    unique_count = 0
    observed_start_utc_ms: float | None = None
    max_receipt_clock_drift_ms = 0.0
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if lineno > 150_000:
            raise ReceiptAuditError("too many source receipts")
        try:
            row = _dict(json.loads(line), "receipt")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ReceiptAuditError("invalid receipt JSONL line") from exc
        market = row.get("market")
        if market not in DEFAULT_MARKETS or row.get("schema") != schema:
            raise ReceiptAuditError("unexpected market or receipt schema")
        assert isinstance(market, str)
        receive_ms = _as_int(row.get("receive_utc_ms"), "receive_utc_ms")
        exchange_ms = _as_int(
            row.get("exchange_ms" if public else "exchange_time_ms"), "exchange_ms"
        )
        age_ms = _as_int(row.get("source_age_ms"), "source_age_ms")
        if age_ms != receive_ms - exchange_ms:
            raise ReceiptAuditError("receipt source-age arithmetic mismatch")
        elapsed = _as_float(row.get("receipt_elapsed_ms"), "receipt_elapsed_ms")
        if not 0 <= elapsed <= duration + 150:
            raise ReceiptAuditError("receipt elapsed time outside window")
        if elapsed < last_arrival.get(market, -1.0):
            raise ReceiptAuditError("per-market monotonic receipt clock regressed")
        # The receipt contains two independently sampled clocks. Its UTC
        # start (receive_utc - monotonic_elapsed) must be consistent across
        # *all* source messages. A changed summary end timestamp alone can
        # no longer masquerade as a contemporaneous experiment.
        inferred_start_ms = receive_ms - elapsed
        if observed_start_utc_ms is None:
            observed_start_utc_ms = inferred_start_ms
        drift_ms = abs(inferred_start_ms - observed_start_utc_ms)
        max_receipt_clock_drift_ms = max(max_receipt_clock_drift_ms, drift_ms)
        if drift_ms > MAX_RECEIPT_CLOCK_DRIFT_MS:
            raise ReceiptAuditError("receipt UTC and elapsed clocks disagree")
        last_arrival[market] = elapsed
        d = row.get("raw_message_sha256" if public else "wire_sha256")
        if not isinstance(d, str) or DIGEST.fullmatch(d) is None:
            raise ReceiptAuditError("source message hash malformed")
        bids = _as_int(row.get("bid_levels"), "bid_levels")
        asks = _as_int(row.get("ask_levels"), "ask_levels")
        if not 0 < bids <= 100 or not 0 < asks <= 100:
            raise ReceiptAuditError("invalid book depth")
        if row.get("result") != "unique":
            # A candidate may record replays or failed integrity results, but
            # they make the preliminary comparison fail until separately audited.
            raise ReceiptAuditError("duplicate, conflicting or regressing source record")
        if not public:
            height = _as_int(row.get("block_number"), "block_number")
            if height <= last_height.get(market, 0):
                raise ReceiptAuditError("candidate block height did not advance")
            last_height[market] = height
        unique_count += 1
        depth_ok = bids >= 20 and asks >= 20
        if public and not depth_ok:
            raise ReceiptAuditError("public reference source has insufficient depth")
        observations[market].append((elapsed, age_ms, depth_ok))
    if unique_count != _as_int(
        summary.get("unique_books" if public else "unique_blocks"), "unique_count"
    ):
        raise ReceiptAuditError("receipt count disagrees with published summary")
    saved = _dict(summary.get("markets"), "per-market source summary")
    detail: dict[str, dict[str, int]] = {}
    for market in DEFAULT_MARKETS:
        events = observations[market]
        if len(events) < MIN_DISTINCT_PER_MARKET:
            raise ReceiptAuditError("too few unique books in at least one market")
        reported = _dict(saved.get(market), "per-market source summary")
        expected_count = _as_int(
            reported.get("unique" if public else "unique_blocks"), "per-market count"
        )
        if expected_count != len(events):
            raise ReceiptAuditError("per-market summary/source receipt count mismatch")
        if not public and any(
            _as_int(reported.get(field), field) != 0
            for field in (
                "height_regressions", "time_regressions", "conflicting_blocks",
                "books_under_20_levels_per_side", "future_dated_books",
            )
        ):
            raise ReceiptAuditError("candidate integrity or depth anomaly")
        fresh3 = _integrate(events, duration, 3_000)
        fresh5 = _integrate(events, duration, 5_000)
        reported3 = _as_float(
            reported.get("fresh_3s_time_fraction" if public
                         else "full_depth_fresh3_time_fraction"), "reported fresh3"
        )
        reported5 = _as_float(
            reported.get("fresh_5s_time_fraction" if public
                         else "full_depth_fresh5_time_fraction"), "reported fresh5"
        )
        # Independent recomputation checks the published source summaries;
        # allow 1bp of JSON/clock rounding, never inflate by trusting either.
        if abs(fresh3 - int(reported3 * 10_000)) > 5 or abs(
            fresh5 - int(reported5 * 10_000)
        ) > 5:
            raise ReceiptAuditError("time-integrated freshness differs from raw receipts")
        detail[market] = {
            "unique": len(events),
            "fresh3_basis_points": min(fresh3, int(reported3 * 10_000)),
            "fresh5_basis_points": min(fresh5, int(reported5 * 10_000)),
        }
    finished = _finish_ms(summary.get("wall_clock_ended_utc" if public else "ended_utc"))
    if observed_start_utc_ms is None:
        raise ReceiptAuditError("no receipt clocks observed")
    receipt_end_ms = observed_start_utc_ms + duration
    end_skew_ms = abs(finished - receipt_end_ms)
    if end_skew_ms > MAX_SUMMARY_END_SKEW_MS:
        raise ReceiptAuditError("summary window end disagrees with receipt clocks")
    # Derive overlap from the paired receipt clocks themselves, not from
    # user-editable/unbound per-run summary timestamps.
    return {
        "schema": schema,
        "receipt_digest": hashlib.sha256(raw).hexdigest(),
        "window_end_utc_ms": round(receipt_end_ms),
        "window_start_utc_ms": round(observed_start_utc_ms),
        "summary_end_disagreement_ms": round(end_skew_ms, 2),
        "receipt_clock_max_drift_ms": round(max_receipt_clock_drift_ms, 2),
        "duration_ms": duration,
        "cohort": list(DEFAULT_MARKETS),
        "markets": detail,
        "minimum_fresh3_basis_points": min(
            v["fresh3_basis_points"] for v in detail.values()
        ),
        "count": unique_count,
    }


def compare_sources(
    baseline_summary: Path, baseline_receipts: Path,
    candidate_summary: Path, candidate_receipts: Path,
) -> dict[str, Any]:
    """Paired, comparable diagnostic screen, never trading/source authorization."""
    baseline = inspect_source(baseline_summary, baseline_receipts, schema=BASELINE)
    candidate = inspect_source(candidate_summary, candidate_receipts, schema=CANDIDATE)
    overlap = max(
        0,
        min(baseline["window_end_utc_ms"], candidate["window_end_utc_ms"])
        - max(baseline["window_start_utc_ms"], candidate["window_start_utc_ms"]),
    )
    gain = min(
        candidate["markets"][m]["fresh3_basis_points"]
        - baseline["markets"][m]["fresh3_basis_points"]
        for m in DEFAULT_MARKETS
    )
    paired = overlap >= MIN_PAIRED_OVERLAP_MS
    provisional = (
        paired
        and candidate["minimum_fresh3_basis_points"]
        >= PRELIMINARY_CANDIDATE_MIN_FRESH_BPS
        and gain >= PRELIMINARY_CANDIDATE_MIN_IMPROVEMENT_BPS
    )
    return {
        "schema": "paired-full-depth-l2-read-only-screen-v1",
        "baseline": baseline,
        "candidate": candidate,
        "paired_overlap_ms": overlap,
        "paired_windows": paired,
        "candidate_minimum_fresh3_basis_points": candidate[
            "minimum_fresh3_basis_points"
        ],
        "minimum_candidate_lift_basis_points": gain,
        "preliminary_source_diagnostic_screen_passed": provisional,
        "source_completeness_certified": False,
        "signed_paper_evidence_reconciled": False,
        "account_or_order_state_changed": False,
        "production_source_switch_authorized": False,
        "live_trading_authorized": False,
        "profitability_verified": False,
        "caution": (
            "A diagnostic source screen is not block completeness, source "
            "attestation, exchange clock synchronization, book/position "
            "eligibility or after-cost profit. Full prospective PAPER shadow "
            "and independent economic gates are required."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-summary", type=Path, required=True)
    parser.add_argument("--public-receipts", type=Path, required=True)
    parser.add_argument("--candidate-summary", type=Path, required=True)
    parser.add_argument("--candidate-receipts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = compare_sources(
            args.public_summary, args.public_receipts,
            args.candidate_summary, args.candidate_receipts,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ReceiptAuditError) as exc:
        parser.exit(2, f"FAIL CLOSED: {type(exc).__name__}: {exc}\n")
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "paired_windows": result["paired_windows"],
        "candidate_3s_floor_bps": result["candidate_minimum_fresh3_basis_points"],
        "preliminary_screen": result["preliminary_source_diagnostic_screen_passed"],
        "production_authorized": False,
    }))
    return 0 if result["preliminary_source_diagnostic_screen_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
