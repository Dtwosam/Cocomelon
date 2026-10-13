"""Fail-closed independent v2 forward-account diagnostics, never promotion.

Recompute a predeclared paired AFTER-COST account window from signed source
ledger, plus matched closed-trade expectancy from independently replayed
source SQLite accounts. Authenticated paper accounting is NOT an authenticated
mainnet market feed. Even an economically positive row has no trade authority.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from cocomelon.research.loss_context_paired_shadow_review import (
    build_paired_shadow_review,
    verify_review_ledger,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    FORWARD_NOT_BEFORE_MS_V2,
    PRECOMMITMENT_V2,
    both_side_trend_matched_shadow_v2_freeze,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
    FILE_NAME as V2_GAP_WITNESS_FILE,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
    read_source_gap_witness,
)
from scripts.audit_both_side_trend_ledger_anchor import _sha256_file
from scripts.audit_both_side_trend_paired_handoff import (
    TrendPairHandoffAuditError,
    _json_file,
    _mapping,
    _member,
    _write_json_atomic,
)

V2_ROOT = "both-side-trend-paired-shadow-v2"
REVIEW_MEMBER = f"{V2_ROOT}/review-ledger.jsonl"
STATE_MEMBER = f"{V2_ROOT}/paired-shadow-state.json"
ALLOWED_LANES = ("baseline", "candidate")
GAP_SCOPES = (
    "known_gap_intervals_by_stream", "known_global_gap_intervals_by_stream",
)
MINIMUM_FORWARD_MS = int(PRECOMMITMENT_V2["minimum_forward_duration_ms"])


def _number(raw: object, name: str) -> Decimal:
    if not isinstance(raw, str):
        raise TrendPairHandoffAuditError(f"{name} missing exact decimal")
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise TrendPairHandoffAuditError(f"{name} invalid decimal") from exc
    if not number.is_finite():
        raise TrendPairHandoffAuditError(f"{name} non-finite decimal")
    return number


def _lane_metric(row: dict[str, object], lane: str, key: str) -> Decimal:
    return _number(_mapping(row.get(lane), lane).get(key), lane + "." + key)


def _strict_gap_history(
    signed_state: dict[str, object], *,
    start_ms: int, end_ms: int,
) -> dict[str, object]:
    if signed_state.get("historical_gap_scope_tainted") is not False:
        raise TrendPairHandoffAuditError(
            "v2 original source gap history is missing or tainted"
        )
    raw: list[dict[str, object]] = []
    for lane in ALLOWED_LANES:
        account = _mapping(signed_state.get(lane), f"{lane} durable state")
        if account.get("legacy_unscoped_gap_intervals") != []:
            raise TrendPairHandoffAuditError(
                f"{lane} unattributed market gaps cannot certify v2"
            )
        raw.append(account)
    if any(raw[0].get(field) != raw[1].get(field) for field in GAP_SCOPES):
        raise TrendPairHandoffAuditError(
            "v2 market and global source gaps diverged between account lanes"
        )
    unresolved = 0
    overlaps: list[dict[str, object]] = []
    total_intervals = 0
    for field in GAP_SCOPES:
        mapping = _mapping(raw[0].get(field), field)
        for stream, intervals in mapping.items():
            if not stream or not isinstance(intervals, list):
                raise TrendPairHandoffAuditError(
                    "v2 source-scoped market interval is invalid"
                )
            previous_end: int | None = -1
            for interval in intervals:
                if (
                    not isinstance(interval, list) or len(interval) != 2
                    or type(interval[0]) is not int or interval[0] < 0
                    or (
                        interval[1] is not None and (
                            type(interval[1]) is not int
                            or interval[1] < interval[0]
                        )
                    )
                    or previous_end is None
                    or interval[0] <= previous_end
                ):
                    raise TrendPairHandoffAuditError(
                        "v2 source interval chronology invalid"
                    )
                start, end = interval
                previous_end = end
                total_intervals += 1
                if end is None:
                    unresolved += 1
                if start <= end_ms and (end is None or end >= start_ms):
                    overlaps.append({
                        "scope": field, "stream": stream,
                        "start_ms": start, "end_ms": end,
                    })
    return {
        "signed_lane_source_gap_histories_agree": True,
        "total_preserved_gap_intervals": total_intervals,
        "unresolved_named_source_gap_intervals": unresolved,
        "gap_intervals_intersecting_prospective_window": overlaps,
        "no_recorded_forward_gaps": not overlaps and unresolved == 0,
        "original_exchange_source_completeness_verified": False,
    }


def _closed_cohort(
    source: dict[str, object], lane: str, anchor_ms: int,
    review: dict[str, object],
) -> dict[str, object]:
    reconciled = _mapping(source.get("reconciled_lanes"), "reconciled lanes")
    account = _mapping(reconciled.get(lane), f"{lane} archived SQLite economics")
    cohort = _mapping(
        account.get("forward_closed_trade_cohort"),
        f"{lane} forward closed-trade cohort",
    )
    if (
        cohort.get("anchor_end_ms") != anchor_ms
        or cohort.get("window")
        != "exits_strictly_after_first_eligible_signed_checkpoint"
    ):
        raise TrendPairHandoffAuditError(
            f"{lane} closed trade cohort does not match signed review anchor"
        )
    evidence = _mapping(
        _mapping(
            review.get("forward_closed_trade_economics_by_direction"),
            "review directional trades",
        ).get(lane),
        f"{lane} signed direction evidence",
    )
    for side in ("long", "short"):
        count = evidence.get(f"{side}_closed_trades")
        if (
            type(count) is not int
            or _mapping(cohort.get(side), f"{lane} {side} trades")
            .get("closed_trades") != count
        ):
            raise TrendPairHandoffAuditError(
                f"{lane} signed directional closed-trade cohort differs from fills"
            )
    all_trades = _mapping(cohort.get("all"), f"{lane} cohort all trades")
    count = evidence.get("total_forward_closed_trades")
    if (
        type(count) is not int
        or all_trades.get("closed_trades") != count
    ):
        raise TrendPairHandoffAuditError(
            f"{lane} total cohort counts do not reconcile with signed review"
        )
    if all_trades.get("closed_trades") != sum(
        _mapping(cohort[side], side)["closed_trades"]
        for side in ("long", "short")
    ):
        raise TrendPairHandoffAuditError(
            f"{lane} inconsistent LONG/SHORT fill cohorts"
        )
    profit = _number(all_trades.get("gross_positive_net_pnl"), "gross profit")
    loss = _number(
        all_trades.get("absolute_gross_negative_net_pnl"), "absolute gross loss",
    )
    if profit < 0 or loss < 0:
        raise TrendPairHandoffAuditError("net trade gross components negative")
    net_closed = _number(all_trades.get("net_pnl_after_costs"), "cohort net cash")
    expectancy = all_trades.get("net_expectancy_per_closed_trade")
    if net_closed != profit - loss:
        raise TrendPairHandoffAuditError("closed cohort net versus gains/losses mismatch")
    wins = all_trades.get("wins_after_costs")
    losses = all_trades.get("losses_after_costs")
    if (
        type(wins) is not int or type(losses) is not int
        or wins < 0 or losses < 0 or wins + losses > count
    ):
        raise TrendPairHandoffAuditError("closed cohort wins/loss counts invalid")
    if count:
        if _number(expectancy, "closed cohort expectancy") != net_closed / count:
            raise TrendPairHandoffAuditError("closed cohort expectancy mismatch")
    elif expectancy is not None or net_closed != 0:
        raise TrendPairHandoffAuditError("no-trade cohort cannot report expectancy")
    if all_trades.get("profit_factor") is not None:
        reported_pf = _number(all_trades["profit_factor"], "profit factor")
        if loss <= 0 or reported_pf != profit / loss:
            raise TrendPairHandoffAuditError("profit factor arithmetic mismatch")
    elif loss > 0:
        raise TrendPairHandoffAuditError("missing finite profit factor")
    return {
        "closed_trades": count,
        "after_cost_profit_factor": all_trades.get("profit_factor"),
        "after_cost_net_expectancy_per_closed_trade": all_trades.get(
            "net_expectancy_per_closed_trade"
        ),
        "after_cost_net_of_closed_trades": all_trades.get("net_pnl_after_costs"),
        "closed_long_trades": evidence.get("long_closed_trades"),
        "closed_short_trades": evidence.get("short_closed_trades"),
        "trade_close_cohort_not_same_as_marked_account_window": True,
    }


def _economics(
    *,
    source: dict[str, object], lineage: dict[str, object],
    review: dict[str, object], signed_state: dict[str, object],
    rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    min_ms = MINIMUM_FORWARD_MS
    window = tuple(
        row for row in rows
        if type(row.get("end_ms")) is int
        and row["end_ms"] >= FORWARD_NOT_BEFORE_MS_V2
    )
    forward_anchor = window[0] if window else None
    latest = window[-1] if window else None
    snapshot: dict[str, object] = {
        "trial_id": PRECOMMITMENT_V2["trial_id"],
        "prospective_boundary_ms": FORWARD_NOT_BEFORE_MS_V2,
        "required_duration_ms": min_ms,
        "eligible_signed_checkpoints": len(window),
        "signed_72h_window_complete": False,
        "review_gate_passed": False,
        "positive_signed_source_account_screen": False,
        "original_exchange_event_source_authenticated": False,
        "venue_mark_prices_authenticated": False,
        "live_execution_authority": False,
        "promotion_authority": False,
        "research_only": True,
        "paper_only": True,
        "status": "unverified",
        "reasons": [],
    }
    reasons: list[str] = []
    if (
        source.get("status") != "archive_checkpoint_lineage_verified"
        or source.get("v2_write_once_genesis_verified") is not True
        or source.get("source_v2_terminal_receipt_verified") is not True
        or source.get("archived_execution_economics_reconciled") is not True
        or source.get("source_worker_completed") is not True
        or source.get("source_class") not in (
            "completed_successful_worker",
            "completed_expected_upgrade_handoff_worker",
        )
        or lineage.get("status") != "v2_selected_anchor_worker_append_verified"
        or lineage.get("first_archived_v2_worker_proven") is not True
        or lineage.get("identical_write_once_genesis_across_workers") is not True
        or lineage.get("v2_actor_gap_witness_prefix_verified") is not True
        or lineage.get("new_signed_checkpoint_append_verified") is not True
        or lineage.get("current_run_id") != source.get("source_run_id")
        or lineage.get("current_attempt") != source.get("source_run_attempt")
        or not rows
        or lineage.get("successor_last_row_digest")
        != rows[-1].get("row_digest")
        or lineage.get("successor_row_count") != len(rows)
        or lineage.get("successor_end_ms") != rows[-1].get("end_ms")
        or lineage.get("successor_record_count")
        != rows[-1].get("record_count")
    ):
        reasons.append("original_worker_and_forward_source_lineage_not_authenticated")
    if forward_anchor is None or latest is None or len(window) < 2:
        reasons.append("no_authentic_post_embargo_signed_comparison")
        snapshot["reasons"] = reasons
        return snapshot
    start = int(forward_anchor["end_ms"])
    end = int(latest["end_ms"])
    span = end - start
    if span < 0:
        raise TrendPairHandoffAuditError("signed forward duration negative")
    snapshot["anchor_end_ms"] = start
    snapshot["latest_end_ms"] = end
    snapshot["signed_forward_duration_ms"] = span
    snapshot["signed_72h_window_complete"] = span >= min_ms
    if span < min_ms:
        reasons.append("insufficient_72h_forward_signed_duration")
    if len(window) < 9:
        reasons.append("insufficient_independent_signed_samples")
    gap_receipt_count = source.get("witnessed_forward_gap_event_count")
    snapshot["witnessed_forward_gap_event_count"] = gap_receipt_count
    if (
        source.get("v2_actor_received_gap_record_chain_verified") is not True
        or type(gap_receipt_count) is not int
        or gap_receipt_count < 0
    ):
        reasons.append("original_actor_gap_event_witness_not_authenticated")
    elif gap_receipt_count:
        reasons.append("original_actor_received_forward_market_gap_event")
    # A 72h wall-clock span with NO new market records is not an honest
    # 72h prospective evaluation. The original venue still needs its own
    # independent provenance; this is a conservative signed progress gate.
    signed_progress = True
    previous_count: int | None = None
    previous_available_ms: int | None = None
    for checkpoint in window:
        count = checkpoint.get("record_count")
        observed_ms = checkpoint.get("last_record_available_at_ms")
        checkpoint_end = checkpoint.get("end_ms")
        if (
            type(count) is not int
            or type(observed_ms) is not int
            or type(checkpoint_end) is not int
            or observed_ms < FORWARD_NOT_BEFORE_MS_V2
            or observed_ms > checkpoint_end
            or (previous_count is not None and count <= previous_count)
            or (
                previous_available_ms is not None
                and observed_ms <= previous_available_ms
            )
        ):
            signed_progress = False
            break
        previous_count, previous_available_ms = count, observed_ms
    snapshot["signed_new_records_at_every_eligible_checkpoint"] = signed_progress
    snapshot["signed_record_count_delta_in_window"] = (
        int(latest["record_count"]) - int(forward_anchor["record_count"])
        if signed_progress else None
    )
    if not signed_progress:
        reasons.append("signed_market_record_progress_stalled_or_unverifiable")
    gap_status = _strict_gap_history(
        signed_state, start_ms=FORWARD_NOT_BEFORE_MS_V2, end_ms=end,
    )
    snapshot["named_market_source_gap_history"] = gap_status
    if not gap_status["no_recorded_forward_gaps"]:
        reasons.append("recorded_market_feed_gaps_or_unresolved_sources")
    report_count = review.get("eligible_checkpoint_count")
    if report_count != len(window) or review.get("review_anchor_end_ms") != start:
        raise TrendPairHandoffAuditError("signed economic window review mismatch")
    if review.get("future_duration_ms") != span:
        raise TrendPairHandoffAuditError("signed review span mismatch")
    for lane in ALLOWED_LANES:
        delta = _lane_metric(latest, lane, "total_account_pnl") - _lane_metric(
            forward_anchor, lane, "total_account_pnl",
        )
        snapshot[f"{lane}_after_cost_marked_pnl"] = str(delta)
        snapshot[f"{lane}_latest_max_drawdown_fraction"] = str(
            _lane_metric(latest, lane, "max_drawdown_fraction")
        )
    advantage = _number(
        cast(str, snapshot["candidate_after_cost_marked_pnl"]),
        "candidate forward PnL",
    ) - _number(
        cast(str, snapshot["baseline_after_cost_marked_pnl"]),
        "baseline forward PnL",
    )
    snapshot["primary_candidate_minus_baseline_after_cost_marked_pnl"] = str(
        advantage
    )
    if (
        _number(
            review.get("candidate_minus_baseline_total_account_pnl"),
            "review primary advantage",
        ) != advantage
        or _number(
            review.get("candidate_total_account_pnl"),
            "review candidate net PnL",
        ) != _number(
            cast(str, snapshot["candidate_after_cost_marked_pnl"]),
            "candidate forward PnL",
        )
    ):
        raise TrendPairHandoffAuditError(
            "independent marked account window differs from review"
        )
    for lane in ALLOWED_LANES:
        snapshot[f"{lane}_fill_matched_trades"] = _closed_cohort(
            source, lane, start, review,
        )
    failures = review.get("readiness_failures")
    if not isinstance(failures, (list, tuple)) or not all(
        isinstance(item, str) for item in failures
    ):
        raise TrendPairHandoffAuditError("signed review readiness reasons missing")
    snapshot["signed_economic_review_failures"] = failures
    review_passed = review.get("ready_for_review") is True and not failures
    snapshot["review_gate_passed"] = review_passed
    if not review_passed:
        reasons.append("existing_predeclared_forward_economic_gates_failed")
    if _number(
        cast(str, snapshot["candidate_after_cost_marked_pnl"]),
        "candidate forward PnL",
    ) <= 0 or advantage <= 0:
        reasons.append("candidate_not_positive_and_ahead_after_costs")
    snapshot["positive_signed_source_account_screen"] = (
        not reasons
    )
    # Even a perfect signed paper-account result remains original-venue
    # unauthenticated and unpromotable, by construction.
    snapshot["status"] = (
        "signed_paper_account_positive_screen_not_venue_certified"
        if not reasons
        else "signed_paper_account_review_incomplete_or_unfavorable"
    )
    reasons.append("independent_mainnet_tick_and_mark_source_not_authenticated")
    snapshot["reasons"] = reasons
    return snapshot


def audit_v2_forward_economic_diagnostic(
    *,
    source: dict[str, object], lineage: dict[str, object],
    archive: Path,
) -> dict[str, object]:
    blank: dict[str, object] = {
        "status": "unverified",
        "reasons": [],
        "positive_signed_source_account_screen": False,
        "original_exchange_event_source_authenticated": False,
        "signed_72h_window_complete": False,
        "live_execution_authority": False,
        "promotion_authority": False,
        "research_only": True,
        "paper_only": True,
    }
    try:
        if (
            source.get("archive_sha256") != _sha256_file(archive)
            or source.get("trial_id") != PRECOMMITMENT_V2["trial_id"]
            or source.get("expected_candidate_id")
            != both_side_trend_matched_shadow_v2_freeze().candidate_id
        ):
            raise TrendPairHandoffAuditError(
                "v2 source archive hash or precommitment identity mismatch"
            )
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "v2-review-ledger.jsonl"
            with zipfile.ZipFile(archive) as package:
                ledger_path.write_bytes(_member(package, REVIEW_MEMBER))
                signed_state = _mapping(
                    json.loads(_member(package, STATE_MEMBER)),
                    "v2 signed source state",
                )
                raw_received_gap_events = _member(
                    package, f"{V2_ROOT}/{V2_GAP_WITNESS_FILE}",
                )
            gap_path = Path(tmp) / V2_GAP_WITNESS_FILE
            gap_path.write_bytes(raw_received_gap_events)
            received = read_source_gap_witness(
                gap_path,
                total_processed_records=signed_state["record_count"],
            )
            if (
                signed_state.get("v2_source_gap_event_witness") != received
                or source.get("v2_actor_received_gap_record_chain_verified")
                is not True
                or source.get("v2_actor_received_gap_count")
                != received["received_gap_record_count"]
            ):
                raise TrendPairHandoffAuditError(
                    "v2 source-recorded gap events differ from signed state"
                )
            signed_forward_gaps = 0
            for raw_line in raw_received_gap_events.splitlines():
                item = _mapping(json.loads(raw_line), "v2 original received gap")
                envelope = _mapping(item.get("record"), "v2 received gap")
                if (
                    envelope["available_at_ms"] >= FORWARD_NOT_BEFORE_MS_V2
                    and envelope["available_at_ms"]
                    <= signed_state.get("last_record_available_at_ms", -1)
                ):
                    signed_forward_gaps += 1
            freeze = both_side_trend_matched_shadow_v2_freeze()
            review = build_paired_shadow_review(freeze, ledger_path)
            if json.dumps(
                review, sort_keys=True, separators=(",", ":"),
            ) != json.dumps(
                source.get("review_report"), sort_keys=True,
                separators=(",", ":"),
            ):
                raise TrendPairHandoffAuditError(
                    "independently recomputed v2 review differs from source receipt"
                )
            rows = verify_review_ledger(ledger_path, candidate_id=freeze.candidate_id)
            witnessed_source = dict(source)
            witnessed_source["witnessed_forward_gap_event_count"] = (
                signed_forward_gaps
            )
            result = _economics(
                source=witnessed_source, lineage=lineage, review=review,
                signed_state=signed_state, rows=rows,
            )
            result["original_source_sha256"] = source["archive_sha256"]
            result["original_source_run_id"] = source.get("source_run_id")
            result["original_source_attempt"] = source.get("source_run_attempt")
            return result
    except (
        OSError, ValueError, RuntimeError, TypeError, KeyError, ArithmeticError,
        zipfile.BadZipFile, UnicodeDecodeError,
    ) as exc:
        blank["reasons"] = [f"{type(exc).__name__}: {exc}"]
        return blank


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--lineage-receipt", type=Path, required=True)
    parser.add_argument("--source-artifact-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit_v2_forward_economic_diagnostic(
        source=_json_file(args.source_receipt),
        lineage=_json_file(args.lineage_receipt),
        archive=args.source_artifact_zip,
    )
    _write_json_atomic(args.output, result)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
