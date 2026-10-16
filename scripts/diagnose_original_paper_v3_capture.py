"""Read-only classification of an ORIGINAL PAPER v3 research capture failure.

Run after the genuine paper worker is stopped. Publish even if ZIP sealing
fails, to distinguish recorder initialization, queue/disk/receive-clock
failures from an absent capture. Diagnostics are NEVER tradable source.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cocomelon.research.original_paper_v3_capture import (
    ORIGINAL_GAP_REASON_BUCKETS,
    RECORD_FILE,
    STARTUP_FAILURE_FILE,
    TERMINAL_FILE,
)

DIAG_SCHEMA = "original-v3-paper-capture-failure-diagnostic-v1"


def _json_object(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def diagnose_original_paper_v3_capture(
    *, capture_root: Path, diagnostic_root: Path,
    run_id: str, run_attempt: str, head_sha: str,
) -> dict[str, object]:
    """Report observed original state, NEVER synthesize a missing receipt."""
    if (
        not run_id.isdecimal() or not run_attempt.isdecimal()
        or len(head_sha) != 40
        or any(c not in "0123456789abcdef" for c in head_sha)
    ):
        raise ValueError("original v3 diagnostic worker identity invalid")
    startup = _json_object(diagnostic_root / STARTUP_FAILURE_FILE)
    terminal = _json_object(capture_root / TERMINAL_FILE)
    journal = capture_root / RECORD_FILE
    has_journal = journal.is_file() and not journal.is_symlink()
    journal_size = journal.stat().st_size if has_journal else None
    startup_matches = bool(
        startup
        and startup.get("run_id") == run_id
        and startup.get("run_attempt") == run_attempt
        and startup.get("head_sha") == head_sha
    )
    terminal_matches = bool(
        terminal
        and terminal.get("run_id") == run_id
        and terminal.get("run_attempt") == run_attempt
        and terminal.get("head_sha") == head_sha
    )
    if startup is not None and not startup_matches:
        reason = "startup_failure_identity_mismatch"
    elif terminal is not None and not terminal_matches:
        reason = "terminal_identity_mismatch"
    elif startup_matches:
        reason = "recorder_initialization_failed"
    elif terminal is None:
        reason = (
            "capture_not_closed_or_terminal_missing"
            if capture_root.exists() else "capture_root_never_created"
        )
    elif terminal.get("complete") is not True:
        failure = terminal.get("failure")
        reason = (
            "capture_terminal_incomplete:"
            + (failure if isinstance(failure, str) and failure else "unknown")
        )
    elif not has_journal:
        reason = "complete_receipt_missing_original_journal"
    else:
        # Local writer completion only; a source ZIP must still pass ALL
        # separate seal, original ZIP SHA and economic/source gates.
        reason = "local_capture_terminal_complete_needs_external_audit"

    return {
        "schema": DIAG_SCHEMA,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "head_sha": head_sha,
        "diagnostic_reason": reason,
        "startup_failure_marker_observed": startup is not None,
        "startup_failure_marker_matches_worker": startup_matches,
        "startup_exception_class": (
            startup.get("exception_class")
            if startup_matches and isinstance(startup.get("exception_class"), str)
            else None
        ) if startup is not None else None,
        "original_capture_root_exists": capture_root.is_dir()
        and not capture_root.is_symlink(),
        "terminal_receipt_observed": terminal is not None,
        "terminal_receipt_matches_worker": terminal_matches,
        "original_journal_observed": has_journal,
        "original_journal_byte_count": journal_size,
        "original_offered_count": (
            terminal.get("offered_count") if terminal_matches else None
        ),
        "original_written_count": (
            terminal.get("written_count") if terminal_matches else None
        ),
        "original_dropped_count": (
            terminal.get("dropped_count") if terminal_matches else None
        ),
        "original_offered_not_written_or_dropped_count": (
            terminal.get("offered_not_written_or_dropped_count")
            if terminal_matches
            and type(terminal.get("offered_not_written_or_dropped_count")) is int
            else None
        ),
        "original_regressions_vs_prior_offered": (
            terminal.get("regressions_vs_prior_offered")
            if terminal_matches
            and type(terminal.get("regressions_vs_prior_offered")) is int
            else None
        ),
        "original_regressions_vs_paper_clock": (
            terminal.get("regressions_vs_paper_clock")
            if terminal_matches
            and type(terminal.get("regressions_vs_paper_clock")) is int
            else None
        ),
        "original_max_clock_backward_ms": (
            terminal.get("max_original_clock_backward_ms")
            if terminal_matches
            and type(terminal.get("max_original_clock_backward_ms")) is int
            else None
        ),
        "original_first_regression_cause": (
            terminal.get("first_regression_cause")
            if terminal_matches
            and terminal.get("first_regression_cause") in (
                "prior_input_clock", "paper_previous_clock",
                "both_prior_input_and_paper_clock",
            )
            else None
        ),
        "original_first_regression_event_kind": (
            terminal.get("first_regression_event_kind")
            if terminal_matches
            and terminal.get("first_regression_event_kind") in (
                "l2_book", "trades", "candle", "active_asset_ctx",
                "data_gap", "other",
            )
            else None
        ),
        "original_l2_within_stream_clock_regressions": (
            terminal.get("l2_within_stream_clock_regressions")
            if terminal_matches
            and type(terminal.get("l2_within_stream_clock_regressions")) is int
            else None
        ),
        "original_l2_cross_stream_only_clock_regressions": (
            terminal.get("l2_cross_stream_only_clock_regressions")
            if terminal_matches
            and type(terminal.get("l2_cross_stream_only_clock_regressions")) is int
            else None
        ),
        "original_l2_offer_age_over_15s_count": (
            terminal.get("l2_offer_age_over_15s_count")
            if terminal_matches
            and type(terminal.get("l2_offer_age_over_15s_count")) is int
            else None
        ),
        "original_l2_max_offer_age_ms": (
            terminal.get("l2_max_offer_age_ms")
            if terminal_matches
            and type(terminal.get("l2_max_offer_age_ms")) is int
            else None
        ),
        "original_l2_stream_clock_tracking_overflow": (
            terminal.get("l2_stream_clock_tracking_overflow")
            if terminal_matches
            and type(terminal.get("l2_stream_clock_tracking_overflow")) is int
            else None
        ),
        "original_source_offered_elapsed_ms": (
            terminal.get("source_offered_elapsed_ms")
            if terminal_matches and type(terminal.get("source_offered_elapsed_ms")) is int
            else None
        ),
        "original_l2_selected_market_offered_book_count": (
            terminal.get("l2_selected_market_offered_book_count")
            if terminal_matches
            and type(terminal.get("l2_selected_market_offered_book_count")) is int
            else None
        ),
        "original_l2_selected_market_zero_book_count": (
            terminal.get("l2_selected_market_zero_book_count")
            if terminal_matches and type(terminal.get("l2_selected_market_zero_book_count")) is int
            else None
        ),
        "original_l2_selected_market_min_offered_books": (
            terminal.get("l2_selected_market_min_offered_books")
            if terminal_matches
            and type(terminal.get("l2_selected_market_min_offered_books")) is int
            else None
        ),
        "original_l2_selected_market_max_observed_gap_ms": (
            terminal.get("l2_selected_market_max_observed_gap_ms")
            if terminal_matches
            and type(terminal.get("l2_selected_market_max_observed_gap_ms")) is int
            else None
        ),
        "original_l2_selected_market_over_5min_drought_count": (
            terminal.get("l2_selected_market_over_5min_drought_count")
            if terminal_matches
            and type(terminal.get("l2_selected_market_over_5min_drought_count")) is int
            else None
        ),
        "original_gap_reason_counts": (
            dict(terminal["gap_reason_counts"])
            if terminal_matches
            and isinstance(terminal.get("gap_reason_counts"), dict)
            and set(terminal["gap_reason_counts"]) == set(ORIGINAL_GAP_REASON_BUCKETS)
            and all(
                type(value) is int and value >= 0
                for value in terminal["gap_reason_counts"].values()
            )
            else None
        ),
        "original_gap_l2_stream_offered_count": (
            terminal.get("gap_l2_stream_offered_count")
            if terminal_matches
            and type(terminal.get("gap_l2_stream_offered_count")) is int
            else None
        ),
        "original_gap_non_l2_stream_offered_count": (
            terminal.get("gap_non_l2_stream_offered_count")
            if terminal_matches
            and type(terminal.get("gap_non_l2_stream_offered_count")) is int
            else None
        ),
        "original_gap_closed_valid_l2_duration_ms_total": (
            terminal.get("gap_closed_valid_l2_duration_ms_total")
            if terminal_matches
            and type(terminal.get("gap_closed_valid_l2_duration_ms_total")) is int
            and terminal.get("gap_closed_valid_l2_duration_ms_total") >= 0
            else None
        ),
        "original_gap_closed_valid_non_l2_duration_ms_total": (
            terminal.get("gap_closed_valid_non_l2_duration_ms_total")
            if terminal_matches
            and type(terminal.get("gap_closed_valid_non_l2_duration_ms_total")) is int
            and terminal.get("gap_closed_valid_non_l2_duration_ms_total") >= 0
            else None
        ),
        "original_gap_closed_l2_max_duration_ms": (
            terminal.get("gap_closed_l2_max_duration_ms")
            if terminal_matches and type(terminal.get("gap_closed_l2_max_duration_ms")) is int
            and terminal.get("gap_closed_l2_max_duration_ms") >= 0
            else None
        ),
        "original_gap_closed_non_l2_max_duration_ms": (
            terminal.get("gap_closed_non_l2_max_duration_ms")
            if terminal_matches and type(terminal.get("gap_closed_non_l2_max_duration_ms")) is int
            and terminal.get("gap_closed_non_l2_max_duration_ms") >= 0
            else None
        ),
        "original_gap_closed_l2_ge_5s_count": (
            terminal.get("gap_closed_l2_ge_5s_count")
            if terminal_matches and type(terminal.get("gap_closed_l2_ge_5s_count")) is int
            and terminal.get("gap_closed_l2_ge_5s_count") >= 0
            else None
        ),
        "original_gap_closed_non_l2_ge_5s_count": (
            terminal.get("gap_closed_non_l2_ge_5s_count")
            if terminal_matches and type(terminal.get("gap_closed_non_l2_ge_5s_count")) is int
            and terminal.get("gap_closed_non_l2_ge_5s_count") >= 0
            else None
        ),
        "original_gap_closed_invalid_bounds_count": (
            terminal.get("gap_closed_invalid_bounds_count")
            if terminal_matches and type(terminal.get("gap_closed_invalid_bounds_count")) is int
            and terminal.get("gap_closed_invalid_bounds_count") >= 0
            else None
        ),
        "original_gap_offered_count": (
            terminal.get("gap_offered_count")
            if terminal_matches and type(terminal.get("gap_offered_count")) is int
            else None
        ),
        "original_gap_open_offered_count": (
            terminal.get("gap_open_offered_count")
            if terminal_matches and type(terminal.get("gap_open_offered_count")) is int
            else None
        ),
        "original_gap_closed_offered_count": (
            terminal.get("gap_closed_offered_count")
            if terminal_matches and type(terminal.get("gap_closed_offered_count")) is int
            else None
        ),
        "original_gap_max_boundary_age_ms": (
            terminal.get("gap_max_boundary_age_ms")
            if terminal_matches and type(terminal.get("gap_max_boundary_age_ms")) is int
            else None
        ),
        "original_first_regression_gap_boundary_kind": (
            terminal.get("first_regression_gap_boundary_kind")
            if terminal_matches
            and terminal.get("first_regression_gap_boundary_kind") in ("open", "closed")
            else None
        ),
        "original_receive_clock_regressions": (
            terminal.get("original_received_clock_regressions")
            if terminal_matches else None
        ),
        "original_terminal_failure": (
            terminal.get("failure") if terminal_matches else None
        ),
        "capture_admissible_from_diagnostic": False,
        "source_integrity_certified": False,
        "independent_venue_feed_complete": False,
        "positive_after_cost_account_pnl_verified": False,
        "paper_only": True,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--diagnostic-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = diagnose_original_paper_v3_capture(
        capture_root=args.capture_root,
        diagnostic_root=args.diagnostic_root,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        head_sha=args.head_sha,
    )
    if args.output.exists():
        raise ValueError("original diagnostic receipt already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    # Always negative/nonqualifying: a diagnostic cannot grant trial admission.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
