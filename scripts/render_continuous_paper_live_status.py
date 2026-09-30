from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

MAX_ISSUE_BODY_CHARS = 240_000


def _bounded_issue_body(body: str) -> str:
    if len(body) <= MAX_ISSUE_BODY_CHARS:
        return body
    footer = (
        "\n\n> Live-status body was compacted to stay within the GitHub "
        "issue limit. Durable artifacts remain the audit authority.\n"
    )
    budget = MAX_ISSUE_BODY_CHARS - len(footer)
    clipped = body[:budget]
    boundary = clipped.rfind("\n")
    if boundary > 0:
        clipped = clipped[:boundary]
    return clipped + footer


def _reason_summary(raw: object) -> str:
    if not isinstance(raw, dict) or not raw:
        return "none"
    counts = sorted(
        ((str(reason), int(count)) for reason, count in raw.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return ", ".join(f"{reason}={count}" for reason, count in counts[:8])

def _cadence_shadow_lines(raw: object) -> list[str]:
    if not isinstance(raw, dict):
        return [
            "### 5m cadence shadow diagnostic",
            "",
            "_No cadence-shadow telemetry in this heartbeat._",
        ]

    enabled = bool(raw.get("enabled"))
    error = raw.get("error")
    lines = [
        "### 5m cadence shadow diagnostic",
        "",
        (
            "- authority: `RESEARCH ONLY / NO EXECUTION` · "
            f"enabled: `{str(enabled).lower()}`"
        ),
        (
            "- durable across workers: "
            f"`{str(bool(raw.get('durable_state'))).lower()}` · "
            f"restored this worker: "
            f"`{str(bool(raw.get('state_restored'))).lower()}`"
        ),
    ]
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(f"- state restore warning: `{restore_error}`")
    if error:
        lines.append(f"- diagnostic error: `{error}`")
        return lines

    cadences = raw.get("cadences", {})
    if not isinstance(cadences, dict):
        cadences = {}
    five = cadences.get("300000", {})
    fifteen = cadences.get("900000", {})
    if not isinstance(five, dict):
        five = {}
    if not isinstance(fifteen, dict):
        fifteen = {}

    def counts(value: dict[str, object]) -> str:
        decisions = value.get("decision_counts", {})
        if not isinstance(decisions, dict):
            decisions = {}
        return (
            f"{decisions.get('long', 0)} / "
            f"{decisions.get('short', 0)} / "
            f"{decisions.get('no_trade', 0)}"
        )

    lines.extend(
        [
            f"- 5m LONG / SHORT / NO_TRADE: `{counts(five)}`",
            f"- 15m LONG / SHORT / NO_TRADE: `{counts(fifteen)}`",
            (
                "- pending exact forward outcomes: "
                f"`{raw.get('pending_outcome_count', 0)}`"
            ),
            (
                "- censored after shortlist unsubscribe: "
                f"`{raw.get('censored_due_to_unsubscribe', 0)}`"
            ),
        ]
    )

    off_cycle = five.get(
        "off_primary_boundary_outcomes_by_horizon_ms",
        {},
    )
    if not isinstance(off_cycle, dict):
        off_cycle = {}
    for horizon_ms, label in (
        ("900000", "15m"),
        ("3600000", "1h"),
    ):
        outcome = off_cycle.get(horizon_ms, {})
        if not isinstance(outcome, dict):
            outcome = {}
        lines.append(
            f"- off-cycle 5m signals → {label}: "
            f"settled=`{outcome.get('settled_count', 0)}`, "
            f"mean net=`{outcome.get('mean_net_return')}`, "
            f"positive=`{outcome.get('positive_net_count', 0)}`"
        )

    def grouped_quality_table(
        field: str,
        title: str,
        *,
        preferred_order: tuple[str, ...] = (),
    ) -> None:
        raw_by_horizon = fifteen.get(field, {})
        if not isinstance(raw_by_horizon, dict):
            return
        h15 = raw_by_horizon.get("900000", {})
        h1h = raw_by_horizon.get("3600000", {})
        if not isinstance(h15, dict):
            h15 = {}
        if not isinstance(h1h, dict):
            h1h = {}
        labels = set(str(label) for label in h15)
        labels.update(str(label) for label in h1h)
        if not labels:
            return
        ordered = [label for label in preferred_order if label in labels]
        ordered.extend(sorted(labels.difference(ordered)))
        lines.extend(
            [
                "",
                f"#### {title}",
                "",
                (
                    "| Bucket | 15m settled | 15m mean net | 15m positive | "
                    "1h settled | 1h mean net | 1h positive |"
                ),
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for label in ordered:
            short = h15.get(label, {})
            long = h1h.get(label, {})
            if not isinstance(short, dict):
                short = {}
            if not isinstance(long, dict):
                long = {}
            lines.append(
                (
                    "| {label} | {n15} | {mean15} | {pos15} | "
                    "{n1h} | {mean1h} | {pos1h} |"
                ).format(
                    label=label,
                    n15=short.get("settled_count", 0),
                    mean15=short.get("mean_net_return"),
                    pos15=short.get("positive_net_count", 0),
                    n1h=long.get("settled_count", 0),
                    mean1h=long.get("mean_net_return"),
                    pos1h=long.get("positive_net_count", 0),
                )
            )

    grouped_quality_table(
        "outcomes_by_lead_strategy_by_horizon_ms",
        "15m lead-strategy forward outcomes",
    )
    grouped_quality_table(
        "outcomes_by_score_band_by_horizon_ms",
        "15m decision-score forward outcomes",
        preferred_order=("<65", "65-<70", "70-<75", "75-<80", "80+"),
    )
    lines.extend(
        [
            (
                "- skipped directional signals missing lead strategy: "
                f"`{raw.get('skipped_missing_lead_strategy', 0)}`"
            ),
            "",
            (
                "_Forward-return diagnostic after frozen research costs; "
                "not paper fills and not promotion evidence._"
            ),
        ]
    )
    return lines


def _cadence_opportunity_learning_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Cadence opportunity learning",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No cadence opportunity-learning telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    lines.extend(
        [
            (
                "- settled directional outcomes: "
                f"`{raw.get('settled_outcomes', 0)}`"
            ),
            (
                "- model: "
                f"`{raw.get('model_family', 'unknown')}`"
            ),
            (
                "- primary surfaces ready / development-qualified: "
                f"`{str(bool(raw.get('primary_ready_for_review'))).lower()} / "
                f"{str(bool(raw.get('development_qualified'))).lower()}`"
            ),
        ]
    )

    surfaces = raw.get("surfaces", {})
    if not isinstance(surfaces, dict):
        surfaces = {}
    lines.extend(
        [
            "",
            "| Primary surface | Status | Train | Val | Purged | "
            "Admit/skip | Actual Σnet | Candidate Σnet | ΔΣnet | "
            "LONG admit | SHORT admit | Stable blocks |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: |",
        ]
    )
    for key, label in (
        ("900000:900000", "15m → 15m"),
        ("900000:3600000", "15m → 1h"),
    ):
        surface = surfaces.get(key, {})
        if not isinstance(surface, dict):
            surface = {}
        direction = surface.get("by_direction", {})
        if not isinstance(direction, dict):
            direction = {}
        long_row = direction.get("long", {})
        short_row = direction.get("short", {})
        if not isinstance(long_row, dict):
            long_row = {}
        if not isinstance(short_row, dict):
            short_row = {}
        blocks = surface.get("stability_blocks", ())
        if not isinstance(blocks, (list, tuple)):
            blocks = ()
        stable = sum(
            1
            for block in blocks
            if isinstance(block, dict) and block.get("passes") is True
        )
        lines.append(
            (
                "| {label} | {status} | {train} | {val} | {purged} | "
                "{admit}/{skip} | {actual} | {candidate} | {delta} | "
                "{long_admit} | {short_admit} | {stable}/{blocks} |"
            ).format(
                label=label,
                status=surface.get("status", "missing"),
                train=surface.get("training_rows", 0),
                val=surface.get("validation_rows", 0),
                purged=surface.get("purged_overlap_rows", 0),
                admit=surface.get("admitted_rows", 0),
                skip=surface.get("skipped_rows", 0),
                actual=surface.get("actual_net_return_sum", "0"),
                candidate=surface.get("candidate_net_return_sum", "0"),
                delta=surface.get("delta_net_return_sum", "0"),
                long_admit=long_row.get("admitted_rows", 0),
                short_admit=short_row.get("admitted_rows", 0),
                stable=stable,
                blocks=len(blocks),
            )
        )

    def cohort_table(
        field: str,
        title: str,
        *,
        limit_per_surface: int = 4,
    ) -> None:
        rows: list[tuple[str, dict[str, object]]] = []
        for key, label in (
            ("900000:900000", "15m→15m"),
            ("900000:3600000", "15m→1h"),
        ):
            surface = surfaces.get(key, {})
            if not isinstance(surface, dict):
                continue
            cohorts = surface.get(field, ())
            if not isinstance(cohorts, (list, tuple)):
                continue
            for cohort in cohorts[:limit_per_surface]:
                if isinstance(cohort, dict):
                    rows.append((label, cohort))
        if not rows:
            return
        lines.extend(
            [
                "",
                f"#### {title}",
                "",
                (
                    "| Surface | Side | Strategy | Score | Train estimate | "
                    "Train N | Estimator | Val N | Val mean | Val Σnet |"
                ),
                "| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: |",
            ]
        )
        for label, cohort in rows:
            lines.append(
                (
                    "| {surface} | {side} | {strategy} | {score} | "
                    "{estimate} | {train_n} | {specificity} | "
                    "{val_n} | {val_mean} | {val_sum} |"
                ).format(
                    surface=label,
                    side=cohort.get("direction", "unknown"),
                    strategy=cohort.get("lead_strategy", "unknown"),
                    score=cohort.get("score_band", "unknown"),
                    estimate=cohort.get(
                        "training_estimate_mean_net_return"
                    ),
                    train_n=cohort.get("training_estimate_rows", 0),
                    specificity=cohort.get(
                        "training_estimate_specificity",
                        "unknown",
                    ),
                    val_n=cohort.get("validation_rows", 0),
                    val_mean=cohort.get("validation_mean_net_return"),
                    val_sum=cohort.get("validation_net_return_sum"),
                )
            )

    cohort_table(
        "admitted_cohorts",
        "Top admitted validation cohorts",
    )
    cohort_table(
        "skipped_cohorts",
        "Most negative skipped validation cohorts",
    )

    lines.extend(
        [
            "",
            (
                "_Purged chronological holdout: training labels whose forward "
                "window overlaps validation start are removed. Predictions use "
                "direction + lead strategy + score-band grouped means with "
                "deterministic fallback, and must retain both LONG and SHORT "
                "validation admissions. This is not paper-fill or promotion evidence._"
            ),
        ]
    )
    return lines


def _profit_lock_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Fixed profit-lock counterfactual",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No profit-lock telemetry in this heartbeat._")
        return lines

    enabled = bool(raw.get("enabled"))
    lines.append(f"- enabled: `{str(enabled).lower()}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    lines.extend(
        [
            (
                "- complete paths evaluated: "
                f"`{raw.get('evaluated_trade_count', 0)} / "
                f"{raw.get('path_record_count', 0)}`"
            ),
            (
                "- incomplete paths skipped: "
                f"`{raw.get('skipped_incomplete_paths', 0)}`"
            ),
            f"- fill model: `{raw.get('fill_model', 'unknown')}`",
        ]
    )
    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    lines.extend(
        [
            (
                "- evidence gate (paths / armed / triggered): "
                f"`{readiness.get('min_complete_paths', 0)} / "
                f"{readiness.get('min_activated_trades_per_rule', 0)} / "
                f"{readiness.get('min_triggered_trades_per_rule', 0)}`"
            ),
            (
                "- all rules ready for review: "
                f"`{str(bool(readiness.get('all_rules_ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
        ]
    )
    rules = raw.get("rules", [])
    if not isinstance(rules, list):
        rules = []
    if rules:
        lines.extend(
            [
                "",
                (
                    "| Rule | Status | N | Armed | Triggered | Need P/A/T | "
                    "Actual + | Est + | Actual PnL | Est PnL | Δ PnL | "
                    "Actual mean R | Est mean R | Δ mean R |"
                ),
                (
                    "| --- | --- | ---: | ---: | ---: | --- | ---: | "
                    "---: | ---: | ---: | ---: | ---: | ---: | ---: |"
                ),
            ]
        )
        for rule in rules:
            if not isinstance(rule, dict):
                raise ValueError("profit-lock rule must be an object")
            lines.append(
                (
                    "| {rule_id} | {status} | {n} | {armed} | {triggered} | "
                    "{missing_paths}/{missing_armed}/{missing_triggered} | "
                    "{actual_pos} | {candidate_pos} | {actual_pnl} | "
                    "{candidate_pnl} | {delta_pnl} | {actual_r} | "
                    "{candidate_r} | {delta_r} |"
                ).format(
                    rule_id=rule.get("rule_id", "unknown"),
                    status=rule.get("readiness_status", "collecting"),
                    n=rule.get("evaluated_trades", 0),
                    missing_paths=rule.get("missing_complete_paths", 0),
                    missing_armed=rule.get("missing_activated_trades", 0),
                    missing_triggered=rule.get("missing_triggered_trades", 0),
                    armed=rule.get("activated_trades", 0),
                    triggered=rule.get("triggered_trades", 0),
                    actual_pos=rule.get("actual_positive_trades", 0),
                    candidate_pos=rule.get(
                        "candidate_positive_trades_estimate",
                        0,
                    ),
                    actual_pnl=rule.get("actual_net_pnl", "0"),
                    candidate_pnl=rule.get(
                        "candidate_net_pnl_estimate",
                        "0",
                    ),
                    delta_pnl=rule.get("delta_net_pnl_estimate", "0"),
                    actual_r=rule.get("actual_mean_net_r"),
                    candidate_r=rule.get(
                        "candidate_mean_net_r_estimate"
                    ),
                    delta_r=rule.get("delta_mean_net_r_estimate"),
                )
            )
    lines.extend(
        [
            "",
            (
                "_Mark-path estimate using first crossing mark plus frozen "
                "research costs; not an executable fill claim._"
            ),
        ]
    )
    return lines


def _profit_lock_execution_shadow_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Profit-lock execution shadow",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No execution-shadow telemetry in this heartbeat._")
        return lines

    enabled = bool(raw.get("enabled"))
    lines.append(f"- enabled: `{str(enabled).lower()}`")
    lines.append(
        "- durable across workers: "
        f"`{str(bool(raw.get('durable_state'))).lower()}` · "
        "restored this worker: "
        f"`{str(bool(raw.get('state_restored'))).lower()}`"
    )
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(f"- state restore warning: `{restore_error}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    lines.extend(
        [
            f"- fill model: `{raw.get('fill_model', 'unknown')}`",
            (
                "- eligible / excluded open positions: "
                f"`{raw.get('eligible_open_positions', 0)} / "
                f"{raw.get('excluded_open_positions', 0)}`"
            ),
            (
                "- closed shadow outcomes / excluded closes: "
                f"`{raw.get('closed_outcome_count', 0)} / "
                f"{raw.get('excluded_closed_trades', 0)}`"
            ),
            (
                "- lineage-mismatch closes / orphaned restored positions: "
                f"`{raw.get('lineage_mismatch_closed_trades', 0)} / "
                f"{raw.get('orphaned_restored_positions', 0)}`"
            ),
        ]
    )
    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    lines.extend(
        [
            (
                "- evidence gate (economic / armed / triggered / IOC full): "
                f"`{readiness.get('min_economically_evaluated_trades_per_rule', 0)} / "
                f"{readiness.get('min_activated_trades_per_rule', 0)} / "
                f"{readiness.get('min_triggered_trades_per_rule', 0)} / "
                f"{readiness.get('min_simulated_full_closes_per_rule', 0)}`"
            ),
            (
                "- all rules ready for review: "
                f"`{str(bool(readiness.get('all_rules_ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
        ]
    )
    rules = raw.get("rules", [])
    if not isinstance(rules, list):
        rules = []
    if rules:
        lines.extend(
            [
                "",
                (
                    "| Rule | Status | Closed eligible | Econ N | Armed | Triggered | "
                    "IOC full | Triggered incomplete | Need E/A/T/F | Actual + | Est + | "
                    "Actual PnL | IOC-est PnL | Δ PnL | Actual mean R | "
                    "IOC-est mean R | Δ mean R |"
                ),
                (
                    "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | "
                    "---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
                ),
            ]
        )
        for rule in rules:
            if not isinstance(rule, dict):
                raise ValueError("execution-shadow rule must be an object")
            lines.append(
                (
                    "| {rule_id} | {status} | {closed} | {evaluated} | {armed} | "
                    "{triggered} | {full} | {incomplete} | {missing} | {actual_pos} | "
                    "{candidate_pos} | {actual_pnl} | {candidate_pnl} | "
                    "{delta_pnl} | {actual_r} | {candidate_r} | {delta_r} |"
                ).format(
                    rule_id=rule.get("rule_id", "unknown"),
                    status=rule.get("readiness_status", "collecting"),
                    closed=rule.get("closed_eligible_trades", 0),
                    evaluated=rule.get("economically_evaluated_trades", 0),
                    armed=rule.get("activated_trades", 0),
                    triggered=rule.get("triggered_trades", 0),
                    full=rule.get("simulated_full_closes", 0),
                    incomplete=rule.get("triggered_incomplete", 0),
                    missing=(
                        f"{rule.get('missing_evaluated_trades', 0)}/"
                        f"{rule.get('missing_activated_trades', 0)}/"
                        f"{rule.get('missing_triggered_trades', 0)}/"
                        f"{rule.get('missing_simulated_full_closes', 0)}"
                    ),
                    actual_pos=rule.get("actual_positive_trades", 0),
                    candidate_pos=rule.get(
                        "candidate_positive_trades_estimate",
                        0,
                    ),
                    actual_pnl=rule.get("actual_net_pnl", "0"),
                    candidate_pnl=rule.get(
                        "candidate_net_pnl_estimate",
                        "0",
                    ),
                    delta_pnl=rule.get("delta_net_pnl_estimate", "0"),
                    actual_r=rule.get("actual_mean_net_r"),
                    candidate_r=rule.get(
                        "candidate_mean_net_r_estimate"
                    ),
                    delta_r=rule.get("delta_mean_net_r_estimate"),
                )
            )
    lines.extend(
        [
            "",
            (
                "_Visible-book IOC research shadow using the same paper "
                "latency/slippage/fee model; it never mutates the paper "
                "position or submits an order._"
            ),
        ]
    )
    return lines


def _delayed_entry_execution_shadow_lines(
    raw: object,
    *,
    title: str = "60s delayed-entry execution shadow",
) -> list[str]:
    lines = [
        "",
        f"### {title}",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No delayed-entry execution telemetry in this heartbeat._"
        )
        return lines

    enabled = bool(raw.get("enabled"))
    lines.append(f"- enabled: `{str(enabled).lower()}`")
    lines.append(
        "- durable across workers: "
        f"`{str(bool(raw.get('durable_state'))).lower()}` · "
        "restored this worker: "
        f"`{str(bool(raw.get('state_restored'))).lower()}`"
    )
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(f"- state restore warning: `{restore_error}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    lines.extend(
        [
            (
                "- prospective start / state schema: "
                f"`{raw.get('started_at_ms')}` / "
                f"`v{raw.get('state_schema_version')}`"
            ),
            (
                "- frozen delay / max observation lag: "
                f"`{raw.get('delay_ms', 0)}ms / "
                f"{raw.get('max_observation_lag_ms', 0)}ms`"
            ),
            (
                "- stop source: "
                f"`{raw.get('stop_source', 'unknown')}`"
            ),
            (
                "- eligible / excluded open positions: "
                f"`{raw.get('eligible_open_positions', 0)} / "
                f"{raw.get('excluded_open_positions', 0)}`"
            ),
            (
                "- closed eligible / excluded closes: "
                f"`{raw.get('closed_eligible_trades', 0)} / "
                f"{raw.get('excluded_closed_trades', 0)}`"
            ),
            (
                "- full / partial / no-fill / rejected / expired: "
                f"`{raw.get('full_delayed_fills', 0)} / "
                f"{raw.get('partial_delayed_fills', 0)} / "
                f"{raw.get('no_fills', 0)} / "
                f"{raw.get('rejections', 0)} / "
                f"{raw.get('expired', 0)}`"
            ),
            (
                "- censored-before-delay / missing delayed book: "
                f"`{raw.get('censored_before_delay', 0)} / "
                f"{raw.get('missing_delayed_book', 0)}`"
            ),
            (
                "- better / worse price among full delayed fills: "
                f"`{raw.get('better_price_full_fills', 0)} / "
                f"{raw.get('worse_price_full_fills', 0)}`"
            ),
            (
                "- mean signed price improvement / gross-R improvement: "
                f"`{raw.get('mean_signed_price_improvement_bps')}` bps / "
                f"`{raw.get('mean_gross_r_improvement')}` R"
            ),
            (
                "- lineage-mismatch closes / orphaned restored positions: "
                f"`{raw.get('lineage_mismatch_closed_trades', 0)} / "
                f"{raw.get('orphaned_restored_positions', 0)}`"
            ),
            (
                "- evidence gate (closed eligible / full delayed fills): "
                f"`{readiness.get('min_closed_eligible_trades', 0)} / "
                f"{readiness.get('min_full_delayed_fills', 0)}`"
            ),
            (
                "- still needed closed / full: "
                f"`{readiness.get('missing_closed_eligible_trades', 0)} / "
                f"{readiness.get('missing_full_delayed_fills', 0)}`"
            ),
            (
                "- positive PnL survives remove top positive market: "
                f"`{str(bool(raw.get(
                    'positive_pnl_survives_remove_top_positive_market'
                ))).lower()}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_One fixed +60s visible-book IOC shadow using the original "
                "paper size, stop, and risk ceiling. Full fills compare entry "
                "price only; it does not claim portfolio PnL or alter the "
                "actual paper entry._"
            ),
        ]
    )
    return lines


def _delayed_entry_pair_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Paired 60s vs 120s delayed-entry study",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No paired delayed-entry telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    if not isinstance(overall, dict):
        overall = {}
    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    by_side = raw.get("by_side", {})
    if not isinstance(by_side, dict):
        by_side = {}

    lines.extend(
        [
            f"- scope: `{raw.get('claim_scope', 'unknown')}`",
            (
                "- prospective start / delays: "
                f"`{raw.get('started_at_ms')}` / "
                f"`{raw.get('base_delay_ms')}ms → "
                f"{raw.get('challenger_delay_ms')}ms`"
            ),
            (
                "- prospective closed / paired full fills: "
                f"`{raw.get('prospective_closed_trades', 0)} / "
                f"{raw.get('paired_full_fills', 0)}`"
            ),
            (
                "- missing 60s / 120s outcomes: "
                f"`{raw.get('missing_base_outcome', 0)} / "
                f"{raw.get('missing_challenger_outcome', 0)}`"
            ),
            (
                "- non-full 60s / 120s: "
                f"`{raw.get('non_full_base', 0)} / "
                f"{raw.get('non_full_challenger', 0)}`"
            ),
            (
                "- lineage mismatches: "
                f"`{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- 120s better / 60s better / equal: "
                f"`{overall.get('challenger_better', 0)} / "
                f"{overall.get('base_better', 0)} / "
                f"{overall.get('equal', 0)}`"
            ),
            (
                "- 60s / 120s same-exit PnL / incremental: "
                f"`{overall.get('base_same_exit_net_pnl', '0')}` / "
                f"`{overall.get('challenger_same_exit_net_pnl', '0')}` / "
                f"`{overall.get('challenger_minus_base_pnl', '0')}`"
            ),
            (
                "- mean 120s−60s entry improvement: "
                f"`{overall.get('mean_challenger_minus_base_bps')}` bps / "
                f"`{overall.get('mean_challenger_minus_base_r')}` R"
            ),
            (
                "- evidence gate closed / paired / LONG / SHORT: "
                f"`{readiness.get('min_prospective_closed_trades', 0)} / "
                f"{readiness.get('min_paired_full_fills', 0)} / "
                f"{readiness.get('min_long_paired_full_fills', 0)} / "
                f"{readiness.get('min_short_paired_full_fills', 0)}`"
            ),
            (
                "- still needed C/P/L/S: "
                f"`{readiness.get('missing_prospective_closed_trades', 0)} / "
                f"{readiness.get('missing_paired_full_fills', 0)} / "
                f"{readiness.get('missing_long_paired_full_fills', 0)} / "
                f"{readiness.get('missing_short_paired_full_fills', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "| Side | Paired | 120s better | 60s better | "
                "Δ same-exit PnL | Mean ΔR | Mean Δbps |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for key, label in (("long", "LONG"), ("short", "SHORT")):
        item = by_side.get(key, {})
        if not isinstance(item, dict):
            item = {}
        lines.append(
            (
                "| {label} | {n} | {better120} | {better60} | "
                "{pnl} | {r} | {bps} |"
            ).format(
                label=label,
                n=item.get("trades", 0),
                better120=item.get("challenger_better", 0),
                better60=item.get("base_better", 0),
                pnl=item.get("challenger_minus_base_pnl", "0"),
                r=item.get("mean_challenger_minus_base_r"),
                bps=item.get("mean_challenger_minus_base_bps"),
            )
        )
    lines.extend(
        [
            "",
            (
                "_Prospective paired visible-book IOC comparison only. "
                "The same observed exit is held constant so the result "
                "isolates 120s versus 60s entry contribution; it does not "
                "model changed stops, capacity, missed trades, or replacements._"
            ),
        ]
    )
    return lines


def _delayed_entry_pair_fill_weighted_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Paired 60s vs 120s fill-weighted delay",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No paired fill-weighted delay telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    if not isinstance(overall, dict):
        overall = {}
    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    by_side = raw.get("by_side", {})
    if not isinstance(by_side, dict):
        by_side = {}
    source_pairs = raw.get("source_pairs", {})
    if not isinstance(source_pairs, dict):
        source_pairs = {}

    source_text = ", ".join(
        f"{name}={count}"
        for name, count in sorted(source_pairs.items())
    )
    if not source_text:
        source_text = "none"

    lines.extend(
        [
            f"- scope: `{raw.get('claim_scope', 'unknown')}`",
            (
                "- prospective start / delays: "
                f"`{raw.get('started_at_ms')}` / "
                f"`{raw.get('base_delay_ms')}ms → "
                f"{raw.get('challenger_delay_ms')}ms`"
            ),
            (
                "- prospective closed / paired evaluable: "
                f"`{raw.get('prospective_closed_trades', 0)} / "
                f"{raw.get('paired_evaluable_attempts', 0)}`"
            ),
            (
                "- missing 60s / 120s outcomes: "
                f"`{raw.get('missing_base_outcome', 0)} / "
                f"{raw.get('missing_challenger_outcome', 0)}`"
            ),
            (
                "- non-evaluable 60s / 120s: "
                f"`{raw.get('non_evaluable_base', 0)} / "
                f"{raw.get('non_evaluable_challenger', 0)}`"
            ),
            (
                "- lineage mismatches: "
                f"`{raw.get('lineage_mismatches', 0)}`"
            ),
            f"- source pairs: `{source_text}`",
            (
                "- 120s better / 60s better / equal contribution: "
                f"`{overall.get('challenger_better', 0)} / "
                f"{overall.get('base_better', 0)} / "
                f"{overall.get('equal', 0)}`"
            ),
            (
                "- 60s / 120s fill-weighted PnL / incremental: "
                f"`{overall.get('base_fill_weighted_net_pnl', '0')}` / "
                f"`{overall.get('challenger_fill_weighted_net_pnl', '0')}` / "
                f"`{overall.get('challenger_minus_base_pnl', '0')}`"
            ),
            (
                "- mean 60s / 120s fill fraction: "
                f"`{overall.get('mean_base_fill_fraction')} / "
                f"{overall.get('mean_challenger_fill_fraction')}`"
            ),
            (
                "- 120s loses / gains / matches fill fraction: "
                f"`{overall.get('challenger_loses_fill_fraction', 0)} / "
                f"{overall.get('challenger_gains_fill_fraction', 0)} / "
                f"{overall.get('equal_fill_fraction', 0)}`"
            ),
            (
                "- evidence gate closed / paired / LONG / SHORT: "
                f"`{readiness.get('min_prospective_closed_trades', 0)} / "
                f"{readiness.get('min_paired_evaluable_attempts', 0)} / "
                f"{readiness.get('min_long_paired_evaluable_attempts', 0)} / "
                f"{readiness.get('min_short_paired_evaluable_attempts', 0)}`"
            ),
            (
                "- still needed C/P/L/S: "
                f"`{readiness.get('missing_prospective_closed_trades', 0)} / "
                f"{readiness.get('missing_paired_evaluable_attempts', 0)} / "
                f"{readiness.get('missing_long_paired_evaluable_attempts', 0)} / "
                f"{readiness.get('missing_short_paired_evaluable_attempts', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "| Side | N | 120s better | 60s better | Equal | "
                "60s fill | 120s fill | 60s PnL | 120s PnL | Δ PnL | Mean ΔR |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | "
                "---: | ---: | ---: | ---: |"
            ),
        ]
    )

    for side in ("long", "short"):
        item = by_side.get(side, {})
        if not isinstance(item, dict):
            continue
        lines.append(
            (
                "| {side} | {n} | {challenger} | {base} | {equal} | "
                "{base_fill} | {challenger_fill} | {base_pnl} | "
                "{challenger_pnl} | {delta} | {delta_r} |"
            ).format(
                side=side.upper(),
                n=item.get("trades", 0),
                challenger=item.get("challenger_better", 0),
                base=item.get("base_better", 0),
                equal=item.get("equal", 0),
                base_fill=item.get("mean_base_fill_fraction"),
                challenger_fill=item.get(
                    "mean_challenger_fill_fraction"
                ),
                base_pnl=item.get(
                    "base_fill_weighted_net_pnl",
                    "0",
                ),
                challenger_pnl=item.get(
                    "challenger_fill_weighted_net_pnl",
                    "0",
                ),
                delta=item.get("challenger_minus_base_pnl", "0"),
                delta_r=item.get("mean_challenger_minus_base_r"),
            )
        )

    lines.extend(
        [
            "",
            (
                "_Prospective paired same-exit contribution comparison using "
                "full, partial, and genuine no-fill outcomes for both delays. "
                "Unresolved observations are excluded. This does not model "
                "replacement trades, changed exits, capacity, or stop timing._"
            ),
        ]
    )
    return lines


def _delayed_entry_fill_capacity_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry fill-capacity diagnostic",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No delayed-entry fill-capacity telemetry in this heartbeat._")
        return lines
    lines.append(f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    by_side = raw.get("by_side", {})
    by_cause = raw.get("by_cause", {})
    readiness = raw.get("readiness", {})
    open_attempts = raw.get("open_attempts", {})
    if not isinstance(overall, dict):
        overall = {}
    if not isinstance(by_side, dict):
        by_side = {}
    if not isinstance(by_cause, dict):
        by_cause = {}
    if not isinstance(readiness, dict):
        readiness = {}
    if not isinstance(open_attempts, dict):
        open_attempts = {}

    lines.extend(
        [
            (
                "- attempts / mean fill fraction: "
                f"`{raw.get('evaluated_attempts', 0)} / "
                f"{overall.get('mean_fill_fraction')}`"
            ),
            (
                "- full / partial / no-fill: "
                f"`{overall.get('full', 0)} / "
                f"{overall.get('partial', 0)} / "
                f"{overall.get('no_fill', 0)}`"
            ),
            (
                "- cause-known / legacy-unknown partials: "
                f"`{raw.get('cause_known_partial_fills', 0)} / "
                f"{raw.get('legacy_unknown_partial_fills', 0)}`"
            ),
            (
                "- missing journal / lineage mismatch: "
                f"`{raw.get('missing_journal_trades', 0)} / "
                f"{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- evidence gate attempts / cause-known partials: "
                f"`{readiness.get('min_evaluated_attempts', 0)} / "
                f"{readiness.get('min_cause_known_partial_fills', 0)}`"
            ),
            (
                "- still needed attempts / partials: "
                f"`{readiness.get('missing_evaluated_attempts', 0)} / "
                f"{readiness.get('missing_cause_known_partial_fills', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            "| Cohort | Attempts | Mean fill | Full | Partial | No fill |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for label, data in (("LONG", by_side.get("long")), ("SHORT", by_side.get("short"))):
        if not isinstance(data, dict):
            continue
        lines.append(
            f"| {label} | {data.get('attempts', 0)} | "
            f"{data.get('mean_fill_fraction')} | {data.get('full', 0)} | "
            f"{data.get('partial', 0)} | {data.get('no_fill', 0)} |"
        )
    if by_cause:
        lines.extend(["", "Partial/fill cause breakdown:"])
        for cause, data in sorted(by_cause.items()):
            if not isinstance(data, dict):
                continue
            lines.append(
                f"- {cause}: n={data.get('attempts', 0)}, "
                f"mean_fill={data.get('mean_fill_fraction')}"
            )

    open_rows = open_attempts.get("rows", [])
    if not isinstance(open_rows, list):
        open_rows = []
    lines.extend(
        [
            "",
            (
                "- current open positions with completed +60s attempt: "
                f"`{open_attempts.get('attempted_open_positions', 0)}`"
            ),
        ]
    )
    if open_rows:
        lines.extend(
            [
                "",
                (
                    "| Open market | Side | Result | Fill fraction | "
                    "Capacity cause | IOC reason | Lag |"
                ),
                (
                    "| --- | --- | --- | ---: | --- | --- | ---: |"
                ),
            ]
        )
        for item in open_rows:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {market} | {side} | {result} | {fill} | "
                "{cause} | {reason} | {lag}ms |".format(
                    market=item.get("market", "unknown"),
                    side=item.get("side", "unknown"),
                    result=item.get("result", "unknown"),
                    fill=item.get("fill_fraction"),
                    cause=item.get("capacity_cause") or "n/a",
                    reason=item.get("attempt_reason") or "n/a",
                    lag=item.get("observation_lag_ms"),
                )
            )
    lines.extend(
        [
            "",
            (
                "_This diagnoses why delayed IOC attempts lose size. "
                "It does not change delay, order size, slippage, risk, or execution._"
            ),
        ]
    )
    return lines


def _delayed_entry_fill_weighted_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry fill-weighted contribution",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No delayed-entry fill-weighted telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    if not isinstance(overall, dict):
        overall = {}
    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    by_side = raw.get("by_side", {})
    if not isinstance(by_side, dict):
        by_side = {}
    by_source = raw.get("by_source", {})
    if not isinstance(by_source, dict):
        by_source = {}
    source_counts = raw.get("source_counts", {})
    if not isinstance(source_counts, dict):
        source_counts = {}

    lines.extend(
        [
            f"- scope: `{raw.get('claim_scope', 'unknown')}`",
            (
                "- exit / funding assumptions: "
                f"`{raw.get('exit_assumption', 'unknown')}` / "
                f"`{raw.get('funding_assumption', 'unknown')}`"
            ),
            (
                "- unfilled assumption: "
                f"`{raw.get('unfilled_assumption', 'unknown')}`"
            ),
            (
                "- closed shadow / evaluated attempts: "
                f"`{raw.get('closed_shadow_outcomes', 0)} / "
                f"{raw.get('evaluated_delayed_attempts', 0)}`"
            ),
            (
                "- full / partial / no-fill: "
                f"`{source_counts.get('full_visible_book_ioc', 0)} / "
                f"{source_counts.get('partial_visible_book_ioc', 0)} / "
                f"{source_counts.get('no_fill', 0)}`"
            ),
            (
                "- unresolved censored / missing / rejected / expired: "
                f"`{source_counts.get('censored_before_delay', 0)} / "
                f"{source_counts.get('missing_delayed_book', 0)} / "
                f"{source_counts.get('rejected', 0)} / "
                f"{source_counts.get('expired', 0)}`"
            ),
            (
                "- missing journal / lineage mismatch: "
                f"`{raw.get('missing_journal_trades', 0)} / "
                f"{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- mean delayed fill fraction: "
                f"`{overall.get('mean_fill_fraction')}`"
            ),
            (
                "- actual / fill-weighted candidate PnL / delta: "
                f"`{overall.get('actual_net_pnl', '0')}` / "
                f"`{overall.get('candidate_fill_weighted_net_pnl', '0')}` / "
                f"`{overall.get('delta_net_pnl_estimate', '0')}`"
            ),
            (
                "- actual W/L → candidate +/−/0 contribution: "
                f"`{overall.get('actual_wins', 0)}/"
                f"{overall.get('actual_losses', 0)} → "
                f"{overall.get('candidate_positive_contributions', 0)}/"
                f"{overall.get('candidate_negative_contributions', 0)}/"
                f"{overall.get('candidate_zero_contributions', 0)}`"
            ),
            (
                "- candidate better / worse / equal to actual: "
                f"`{overall.get('candidate_better_than_actual', 0)} / "
                f"{overall.get('candidate_worse_than_actual', 0)} / "
                f"{overall.get('candidate_equal_to_actual', 0)}`"
            ),
            (
                "- actual winner→nonpositive / loss→nonnegative: "
                f"`{overall.get('actual_win_to_nonpositive_contribution', 0)} / "
                f"{overall.get('actual_loss_to_nonnegative_contribution', 0)}`"
            ),
            (
                "- evidence gate (closed / evaluated): "
                f"`{readiness.get('min_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('min_evaluated_delayed_attempts', 0)}`"
            ),
            (
                "- still needed closed / evaluated: "
                f"`{readiness.get('missing_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('missing_evaluated_delayed_attempts', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            "| Cohort | N | Fill fraction | Actual PnL | Candidate PnL | Δ PnL | Mean ΔR |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    def row(label: str, item: object) -> None:
        if not isinstance(item, dict):
            return
        lines.append(
            (
                "| {label} | {n} | {fill} | {actual} | {candidate} | "
                "{delta} | {delta_r} |"
            ).format(
                label=label,
                n=item.get("trades", 0),
                fill=item.get("mean_fill_fraction"),
                actual=item.get("actual_net_pnl", "0"),
                candidate=item.get(
                    "candidate_fill_weighted_net_pnl",
                    "0",
                ),
                delta=item.get("delta_net_pnl_estimate", "0"),
                delta_r=item.get("mean_delta_r_contribution"),
            )
        )

    row("Overall", overall)
    row("LONG", by_side.get("long"))
    row("SHORT", by_side.get("short"))
    row("Full fill", by_source.get("full_visible_book_ioc"))
    row("Partial fill", by_source.get("partial_visible_book_ioc"))
    row("No fill", by_source.get("no_fill"))

    lines.extend(
        [
            "",
            (
                "_Contribution estimate only. Partial fills keep only the "
                "simulated filled quantity; genuine no-fills contribute zero. "
                "Unresolved stale/missing/censored evidence is excluded, not "
                "treated as a missed trade. This does not model replacement "
                "trades, changed exits, capacity, or stop timing._"
            ),
        ]
    )
    return lines


def _delayed_entry_fill_weighted_funding_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry funding-corrected fill weighting",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No funding-corrected fill-weighted telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    readiness = raw.get("readiness", {})
    if not isinstance(overall, dict):
        overall = {}
    if not isinstance(readiness, dict):
        readiness = {}

    lines.extend(
        [
            f"- scope: `{raw.get('claim_scope', 'unknown')}`",
            (
                "- closed / evaluated attempts: "
                f"`{raw.get('closed_shadow_outcomes', 0)} / "
                f"{raw.get('evaluated_delayed_attempts', 0)}`"
            ),
            (
                "- legacy scaled / exact post-delay funding / correction: "
                f"`{overall.get('legacy_scaled_funding_pnl', '0')} / "
                f"{overall.get('exact_post_delay_funding_pnl', '0')} / "
                f"{overall.get('funding_timing_delta_pnl', '0')}`"
            ),
            (
                "- legacy / funding-corrected candidate PnL / correction: "
                f"`{overall.get('legacy_fill_weighted_candidate_net_pnl', '0')} / "
                f"{overall.get('funding_corrected_candidate_net_pnl', '0')} / "
                f"{overall.get('corrected_delta_vs_legacy_pnl', '0')}`"
            ),
            (
                "- corrected candidate delta vs actual: "
                f"`{overall.get('corrected_delta_vs_actual_pnl', '0')}`"
            ),
            (
                "- missing journal / funding / lineage: "
                f"`{raw.get('missing_journal_trades', 0)} / "
                f"{raw.get('missing_funding_events', 0)} / "
                f"{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- evidence gate closed / evaluated: "
                f"`{readiness.get('min_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('min_evaluated_delayed_attempts', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_Same actual exit is still assumed. This overlay changes only "
                "funding: filled candidates pay verified recorded boundaries "
                "strictly after their delayed open; genuine no-fills pay zero._"
            ),
        ]
    )
    return lines


def _delayed_entry_fixed_schedule_portfolio_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry fixed-schedule portfolio shadow",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No fixed-schedule portfolio telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    actual = raw.get("actual", {})
    candidate = raw.get("candidate", {})
    readiness = raw.get("readiness", {})
    if not isinstance(actual, dict):
        actual = {}
    if not isinstance(candidate, dict):
        candidate = {}
    if not isinstance(readiness, dict):
        readiness = {}
    lines.extend(
        [
            f"- scope: `{raw.get('claim_scope', 'unknown')}`",
            (
                "- closed shadow / evaluated / unresolved: "
                f"`{raw.get('closed_shadow_outcomes', 0)} / "
                f"{raw.get('evaluated_delayed_attempts', 0)} / "
                f"{raw.get('unresolved_outcomes', 0)}`"
            ),
            (
                "- missing journal / opening plan / lineage: "
                f"`{raw.get('missing_journal_trades', 0)} / "
                f"{raw.get('missing_opening_plans', 0)} / "
                f"{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- candidate no-fill trades / risk ceiling exceeded: "
                f"`{raw.get('candidate_no_fill_trades', 0)} / "
                f"{raw.get('candidate_risk_ceiling_exceeded', 0)}`"
            ),
            (
                "- actual / candidate realized contribution / delta: "
                f"`{actual.get('final_realized_contribution', '0')}` / "
                f"`{candidate.get('final_realized_contribution', '0')}` / "
                f"`{raw.get('delta_final_realized_contribution', '0')}`"
            ),
            (
                "- actual / candidate max realized drawdown / delta: "
                f"`{actual.get('max_realized_drawdown', '0')}` / "
                f"`{candidate.get('max_realized_drawdown', '0')}` / "
                f"`{raw.get('delta_max_realized_drawdown', '0')}`"
            ),
            (
                "- actual / candidate max concurrent positions: "
                f"`{actual.get('max_concurrent_positions', 0)} / "
                f"{candidate.get('max_concurrent_positions', 0)}`"
            ),
            (
                "- actual / candidate overlap openings: "
                f"`{actual.get('overlap_openings', 0)} / "
                f"{candidate.get('overlap_openings', 0)}`"
            ),
            (
                "- actual / candidate max gross notional / delta: "
                f"`{actual.get('max_gross_notional', '0')}` / "
                f"`{candidate.get('max_gross_notional', '0')}` / "
                f"`{raw.get('delta_max_gross_notional', '0')}`"
            ),
            (
                "- actual / candidate max planned risk / delta: "
                f"`{actual.get('max_planned_risk', '0')}` / "
                f"`{candidate.get('max_planned_risk', '0')}` / "
                f"`{raw.get('delta_max_planned_risk', '0')}`"
            ),
            (
                "- position exposure-hours actual / candidate: "
                f"`{actual.get('position_exposure_hours', '0')} / "
                f"{candidate.get('position_exposure_hours', '0')}`"
            ),
            (
                "- notional exposure-hours actual / candidate: "
                f"`{actual.get('notional_exposure_hours', '0')} / "
                f"{candidate.get('notional_exposure_hours', '0')}`"
            ),
            (
                "- risk exposure-hours actual / candidate: "
                f"`{actual.get('risk_exposure_hours', '0')} / "
                f"{candidate.get('risk_exposure_hours', '0')}`"
            ),
            (
                "- complete cohort required (unresolved must be zero): "
                f"`{raw.get('unresolved_outcomes', 0)} unresolved`"
            ),
            (
                "- evidence gate closed / evaluated / overlap: "
                f"`{readiness.get('min_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('min_evaluated_delayed_attempts', 0)} / "
                f"{readiness.get('min_actual_overlap_openings', 0)}`"
            ),
            (
                "- still needed C/E/O: "
                f"`{readiness.get('missing_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('missing_evaluated_delayed_attempts', 0)} / "
                f"{readiness.get('missing_actual_overlap_openings', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_Fixed observed schedule only: delayed fills change exposure "
                "timing/size, but observed close times stay fixed. No "
                "replacement trades, changed exits, or unrealized MTM equity "
                "are invented._"
            ),
        ]
    )
    return lines


def _delayed_entry_mtm_portfolio_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry mark-to-market portfolio shadow",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No delayed-entry MTM portfolio telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    actual = raw.get("actual", {})
    candidate = raw.get("candidate", {})
    readiness = raw.get("readiness", {})
    if not isinstance(actual, dict):
        actual = {}
    if not isinstance(candidate, dict):
        candidate = {}
    if not isinstance(readiness, dict):
        readiness = {}

    lines.extend(
        [
            f"- scope: `{raw.get('claim_scope', 'unknown')}`",
            f"- mark model: `{raw.get('mark_model', 'unknown')}`",
            (
                "- closed shadow / complete paths / unresolved: "
                f"`{raw.get('closed_shadow_outcomes', 0)} / "
                f"{raw.get('evaluated_complete_path_trades', 0)} / "
                f"{raw.get('unresolved_outcomes', 0)}`"
            ),
            (
                "- missing journal / exact path / incomplete / funding / lineage: "
                f"`{raw.get('missing_journal_trades', 0)} / "
                f"{raw.get('missing_exact_paths', 0)} / "
                f"{raw.get('incomplete_exact_paths', 0)} / "
                f"{raw.get('missing_funding_events', 0)} / "
                f"{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- candidate filled / no-fill positions: "
                f"`{raw.get('candidate_filled_positions', 0)} / "
                f"{raw.get('candidate_no_fill_trades', 0)}`"
            ),
            (
                "- actual / candidate realized contribution / delta: "
                f"`{actual.get('final_realized_contribution', '0')}` / "
                f"`{candidate.get('final_realized_contribution', '0')}` / "
                f"`{raw.get('delta_final_realized_contribution', '0')}`"
            ),
            (
                "- actual / candidate observed equity drawdown / delta: "
                f"`{actual.get('max_observed_equity_drawdown', '0')}` / "
                f"`{candidate.get('max_observed_equity_drawdown', '0')}` / "
                f"`{raw.get('delta_max_observed_equity_drawdown', '0')}`"
            ),
            (
                "- actual / candidate min observed equity contribution: "
                f"`{actual.get('min_observed_equity_contribution', '0')} / "
                f"{candidate.get('min_observed_equity_contribution', '0')}`"
            ),
            (
                "- actual / candidate funding events / cash: "
                f"`{actual.get('funding_events', 0)} / "
                f"{candidate.get('funding_events', 0)} / "
                f"{actual.get('funding_cash_pnl', '0')} / "
                f"{candidate.get('funding_cash_pnl', '0')}`"
            ),
            (
                "- actual / candidate max concurrent positions: "
                f"`{actual.get('max_concurrent_positions', 0)} / "
                f"{candidate.get('max_concurrent_positions', 0)}`"
            ),
            (
                "- actual / candidate overlap openings: "
                f"`{actual.get('overlap_openings', 0)} / "
                f"{candidate.get('overlap_openings', 0)}`"
            ),
            (
                "- actual / candidate max carried-mark age: "
                f"`{actual.get('max_mark_carry_age_ms', 0)}ms / "
                f"{candidate.get('max_mark_carry_age_ms', 0)}ms`"
            ),
            (
                "- evidence gate closed / complete-path / overlap: "
                f"`{readiness.get('min_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('min_evaluated_complete_path_trades', 0)} / "
                f"{readiness.get('min_actual_overlap_openings', 0)}`"
            ),
            (
                "- still needed C/P/O: "
                f"`{readiness.get('missing_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('missing_evaluated_complete_path_trades', 0)} / "
                f"{readiness.get('missing_actual_overlap_openings', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_Observed-mark contribution equity only; funding is applied "
                "at exact recorded hourly boundaries. No replacement trades or "
                "changed exits are modeled._"
            ),
        ]
    )
    return lines


def _delayed_entry_stop_survivability_lines(
    raw: object,
    validity_raw: object = None,
    proxy_raw: object = None,
) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry original-stop survivability",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No delayed-entry stop-survivability telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    readiness = raw.get("readiness", {})
    if not isinstance(overall, dict):
        overall = {}
    if not isinstance(readiness, dict):
        readiness = {}

    lines.extend(
        [
            f"- scope: `{raw.get('claim_scope', 'unknown')}`",
            (
                "- closed / evaluated fills / no-fills: "
                f"`{raw.get('closed_shadow_outcomes', 0)} / "
                f"{raw.get('evaluated_filled_candidates', 0)} / "
                f"{raw.get('candidate_no_fill_trades', 0)}`"
            ),
            (
                "- definite original-stop crossings / observed survivors: "
                f"`{overall.get('definite_original_stop_crossings', 0)} / "
                f"{overall.get('survived_observed_path_to_actual_close', 0)}`"
            ),
            (
                "- crossing fraction / mean / median / fastest time-to-stop: "
                f"`{overall.get('crossing_fraction')} / "
                f"{overall.get('mean_time_to_stop_ms')} / "
                f"{overall.get('median_time_to_stop_ms')} / "
                f"{overall.get('min_time_to_stop_ms')}`"
            ),
            (
                "- unresolved / missing journal / path / gapped / lineage / timing: "
                f"`{raw.get('unresolved_outcomes', 0)} / "
                f"{raw.get('missing_journal_trades', 0)} / "
                f"{raw.get('missing_exact_paths', 0)} / "
                f"{raw.get('incomplete_or_gapped_paths', 0)} / "
                f"{raw.get('lineage_mismatches', 0)} / "
                f"{raw.get('invalid_candidate_timing', 0)}`"
            ),
            (
                "- evidence gate closed / evaluated: "
                f"`{readiness.get('min_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('min_evaluated_filled_candidates', 0)}`"
            ),
            (
                "- still needed C/E: "
                f"`{readiness.get('missing_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('missing_evaluated_filled_candidates', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_A crossing means a complete gap-free observed mark path "
                "definitely touched the immutable original stop after the "
                "delayed fill existed; same-millisecond marks are excluded; "
                "stop fill price and the full exit policy are not modeled._"
            ),
        ]
    )

    if isinstance(validity_raw, dict):
        validity_error = validity_raw.get("error")
        validity_overall = validity_raw.get("overall", {})
        if validity_error:
            lines.append(
                f"- same-exit stop-validity research error: `{validity_error}`"
            )
        elif isinstance(validity_overall, dict):
            candidate_all = validity_overall.get(
                "same_exit_candidate_net_pnl",
                "0",
            )
            candidate_crossed = validity_overall.get(
                "same_exit_candidate_pnl_on_definite_stop_crossings",
                "0",
            )
            candidate_survived = validity_overall.get(
                "same_exit_candidate_pnl_on_observed_survivors",
                "0",
            )
            delta_all = validity_overall.get(
                "same_exit_delta_vs_actual",
                "0",
            )
            delta_crossed = validity_overall.get(
                "same_exit_delta_on_definite_stop_crossings",
                "0",
            )
            delta_survived = validity_overall.get(
                "same_exit_delta_on_observed_survivors",
                "0",
            )
            lines.extend(
                [
                    (
                        "- corrected same-exit candidate PnL all / stop-crossed / "
                        "survived: "
                        f"`{candidate_all} / {candidate_crossed} / "
                        f"{candidate_survived}`"
                    ),
                    (
                        "- same-exit Δ vs actual all / stop-crossed / survived: "
                        f"`{delta_all} / {delta_crossed} / "
                        f"{delta_survived}`"
                    ),
                    (
                        "- stop-validity candidate/actual Decimal residual: "
                        f"`{validity_overall.get(
                            'candidate_actual_decimal_rounding_residual_pnl',
                            '0',
                        )}`"
                    ),
                    (
                        "- absolute candidate PnL on definite stop crossings: "
                        f"`{validity_overall.get('absolute_candidate_pnl_on_stop_crossings_fraction')}`"
                    ),
                    (
                        "- stop-validity missing path / funding / lineage: "
                        f"`{validity_raw.get('missing_exact_paths', 0)} / "
                        f"{validity_raw.get('missing_funding_events', 0)} / "
                        f"{validity_raw.get('lineage_mismatches', 0)}`"
                    ),
                    (
                        "_Stop-crossed same-exit PnL is flagged as path-invalid, "
                        "not repriced into a synthetic stop-fill result._"
                    ),
                ]
            )

    if isinstance(proxy_raw, dict):
        proxy_error = proxy_raw.get("error")
        proxy_overall = proxy_raw.get("overall", {})
        if proxy_error:
            lines.append(
                f"- stop-exit proxy research error: `{proxy_error}`"
            )
        elif isinstance(proxy_overall, dict):
            lines.extend(
                [
                    (
                        "- stop-exit cohort PnL same-exit / stop / mark / IOC-boundary: "
                        f"`{proxy_overall.get('same_exit_candidate_net_pnl', '0')} / "
                        f"{proxy_overall.get('stop_price_proxy_cohort_net_pnl', '0')} / "
                        f"{proxy_overall.get('crossing_mark_proxy_cohort_net_pnl', '0')} / "
                        f"{proxy_overall.get('ioc_boundary_proxy_cohort_net_pnl', '0')}`"
                    ),
                    (
                        "- stop-exit Δ vs actual same-exit / stop / mark / IOC-boundary: "
                        f"`{proxy_overall.get('same_exit_delta_vs_actual', '0')} / "
                        f"{proxy_overall.get('stop_price_proxy_delta_vs_actual', '0')} / "
                        f"{proxy_overall.get('crossing_mark_proxy_delta_vs_actual', '0')} / "
                        f"{proxy_overall.get('ioc_boundary_proxy_delta_vs_actual', '0')}`"
                    ),
                    (
                        "- same-exit edge removed by IOC-boundary proxy / "
                        "positive→nonpositive crossings: "
                        f"`{proxy_overall.get('same_exit_minus_ioc_boundary_proxy_pnl', '0')} / "
                        f"{proxy_overall.get(
                            'positive_same_exit_crossings_to_nonpositive_boundary',
                            0,
                        )}`"
                    ),
                    (
                        "- stop proxy config taker fee / max slippage bps: "
                        f"`{proxy_raw.get('taker_fee_rate')} / "
                        f"{proxy_raw.get('max_ioc_slippage_bps')}`"
                    ),
                    (
                        "- stop proxy missing path / funding / ambiguous funding / lineage: "
                        f"`{proxy_raw.get('missing_exact_paths', 0)} / "
                        f"{proxy_raw.get('missing_funding_events', 0)} / "
                        f"{proxy_raw.get('ambiguous_stop_funding_timing', 0)} / "
                        f"{proxy_raw.get('lineage_mismatches', 0)}`"
                    ),
                    (
                        "_These are full-exit price proxies only: stop ideal, "
                        "first crossing mark, and the configured IOC slippage "
                        "boundary. Exit-side L2 depth and partial stop fills are "
                        "not reconstructed._"
                    ),
                ]
            )
    return lines


def _delayed_entry_portfolio_capacity_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry portfolio capacity overlay",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No delayed-entry capacity telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    actual = raw.get("actual", {})
    candidate = raw.get("candidate", {})
    actual_admission = raw.get("actual_admission", {})
    candidate_admission = raw.get("candidate_admission", {})
    limits = raw.get("limits", {})
    readiness = raw.get("readiness", {})
    if not isinstance(actual, dict):
        actual = {}
    if not isinstance(candidate, dict):
        candidate = {}
    if not isinstance(actual_admission, dict):
        actual_admission = {}
    if not isinstance(candidate_admission, dict):
        candidate_admission = {}
    if not isinstance(limits, dict):
        limits = {}
    if not isinstance(readiness, dict):
        readiness = {}
    admitted_bucket_utilization = candidate_admission.get(
        "max_admitted_correlation_bucket_risk_utilization",
        "0",
    )

    lines.extend(
        [
            f"- scope: `{raw.get('claim_scope', 'unknown')}`",
            (
                "- frozen limits open-risk / bucket-risk / gross leverage / "
                "margin fraction / visible-depth fraction / venue minimum / "
                "paper leverage / liquidation stop multiple: "
                f"`{limits.get('max_open_risk')} / "
                f"{limits.get('correlation_bucket_risk_limit')} / "
                f"{limits.get('max_gross_leverage')} / "
                f"{limits.get('max_available_margin_fraction')} / "
                f"{limits.get('max_visible_depth_fraction')} / "
                f"{limits.get('native_perp_min_notional')} / "
                f"{limits.get('paper_max_gross_leverage')} / "
                f"{limits.get('min_liquidation_stop_multiple')}`"
            ),
            (
                "- closed / candidate fills / no-fills / background: "
                f"`{raw.get('closed_shadow_outcomes', 0)} / "
                f"{raw.get('candidate_filled_positions', 0)} / "
                f"{raw.get('candidate_no_fill_trades', 0)} / "
                f"{raw.get('background_positions', 0)}`"
            ),
            (
                "- unresolved / missing journal-plan-leverage-openliq-"
                "delayliq-delayref-funding-path / incomplete / lineage: "
                f"`{raw.get('unresolved_outcomes', 0)} / "
                f"{raw.get('missing_journal_trades', 0)}-"
                f"{raw.get('missing_opening_plans', 0)}-"
                f"{raw.get('missing_venue_max_leverage', 0)}-"
                f"{raw.get('missing_opening_liquidity_evidence', 0)}-"
                f"{raw.get('missing_delayed_liquidity_evidence', 0)}-"
                f"{raw.get('missing_delayed_reference_price', 0)}-"
                f"{raw.get('missing_funding_events', 0)}-"
                f"{raw.get('missing_exact_paths', 0)} / "
                f"{raw.get('incomplete_exact_paths', 0)} / "
                f"{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- actual opening checks / capacity violations: "
                f"`{actual.get('opening_checks', 0)} / "
                f"{actual.get('capacity_violations', 0)}`"
            ),
            (
                "- candidate opening checks / capacity violations: "
                f"`{candidate.get('opening_checks', 0)} / "
                f"{candidate.get('capacity_violations', 0)}`"
            ),
            (
                "- candidate violations delayed / background: "
                f"`{candidate.get('delayed_opening_violations', 0)} / "
                f"{candidate.get('background_opening_violations', 0)}`"
            ),
            (
                "- candidate violations aggregate / bucket / leverage / margin / "
                "liquidity / min-notional / liquidation: "
                f"`{candidate.get('aggregate_risk_violations', 0)} / "
                f"{candidate.get('correlation_bucket_risk_violations', 0)} / "
                f"{candidate.get('gross_leverage_violations', 0)} / "
                f"{candidate.get('margin_capacity_violations', 0)} / "
                f"{candidate.get('liquidity_capacity_violations', 0)} / "
                f"{candidate.get('venue_min_notional_violations', 0)} / "
                f"{candidate.get('liquidation_buffer_violations', 0)}`"
            ),
            (
                "- candidate max utilization aggregate / bucket / leverage / margin / "
                "liquidity: "
                f"`{candidate.get('max_aggregate_risk_utilization', '0')} / "
                f"{candidate.get('max_correlation_bucket_risk_utilization', '0')} / "
                f"{candidate.get('max_gross_leverage', '0')} / "
                f"{candidate.get('max_margin_capacity_utilization', '0')} / "
                f"{candidate.get('max_liquidity_capacity_utilization', '0')}`"
            ),
            (
                "- candidate min headroom aggregate / bucket / gross / margin / "
                "liquidity / venue-min notional: "
                f"`{candidate.get('min_aggregate_risk_headroom', '0')} / "
                f"{candidate.get('min_correlation_bucket_risk_headroom', '0')} / "
                f"{candidate.get('min_gross_notional_headroom', '0')} / "
                f"{candidate.get('min_margin_notional_headroom', '0')} / "
                f"{candidate.get('min_liquidity_notional_headroom', '0')} / "
                f"{candidate.get('min_venue_notional_headroom', '0')}`"
            ),
            (
                "- candidate liquidation min multiple / headroom: "
                f"`{candidate.get('min_liquidation_stop_multiple', '0')} / "
                f"{candidate.get('min_liquidation_stop_headroom', '0')}`"
            ),
            (
                "- causal admissions modeled / replacement trades modeled: "
                f"`{str(bool(raw.get('changed_admissions_modeled'))).lower()} / "
                f"{str(bool(raw.get('replacement_trades_modeled'))).lower()}`"
            ),
            (
                "- actual admission admitted / rejected: "
                f"`{actual_admission.get('admitted_openings', 0)} / "
                f"{actual_admission.get('rejected_openings', 0)}`"
            ),
            (
                "- candidate admission admitted / rejected: "
                f"`{candidate_admission.get('admitted_openings', 0)} / "
                f"{candidate_admission.get('rejected_openings', 0)}`"
            ),
            (
                "- candidate delayed admitted / rejected: "
                f"`{candidate_admission.get('delayed_candidate_admitted', 0)} / "
                f"{candidate_admission.get('delayed_candidate_rejected', 0)}`"
            ),
            (
                "- candidate observed-schedule admitted / rejected: "
                f"`{candidate_admission.get('observed_schedule_admitted', 0)} / "
                f"{candidate_admission.get('observed_schedule_rejected', 0)}`"
            ),
            (
                "- candidate admission rejection causes aggregate / bucket / "
                "leverage / margin / liquidity / min-notional / liquidation / "
                "non-positive-equity: "
                f"`{candidate_admission.get('aggregate_risk_rejections', 0)} / "
                f"{candidate_admission.get('correlation_bucket_risk_rejections', 0)} / "
                f"{candidate_admission.get('gross_leverage_rejections', 0)} / "
                f"{candidate_admission.get('margin_capacity_rejections', 0)} / "
                f"{candidate_admission.get('liquidity_capacity_rejections', 0)} / "
                f"{candidate_admission.get('venue_min_notional_rejections', 0)} / "
                f"{candidate_admission.get('liquidation_buffer_rejections', 0)} / "
                f"{candidate_admission.get('non_positive_equity_rejections', 0)}`"
            ),
            (
                "- candidate admitted max utilization aggregate / bucket / leverage / "
                "margin / liquidity: "
                f"`{candidate_admission.get('max_admitted_aggregate_risk_utilization', '0')} / "
                f"{admitted_bucket_utilization} / "
                f"{candidate_admission.get('max_admitted_gross_leverage', '0')} / "
                f"{candidate_admission.get('max_admitted_margin_capacity_utilization', '0')} / "
                f"{candidate_admission.get('max_admitted_liquidity_capacity_utilization', '0')}`"
            ),
            (
                "- admitted candidate minimum liquidation stop multiple: "
                f"`{candidate_admission.get('min_admitted_liquidation_stop_multiple', '0')}`"
            ),
            (
                "- funding events/cash fixed A/C · admitted A/C: "
                f"`{actual.get('funding_events', 0)}/"
                f"{candidate.get('funding_events', 0)} "
                f"{actual.get('funding_cash_pnl', '0')}/"
                f"{candidate.get('funding_cash_pnl', '0')} · "
                f"{actual_admission.get('funding_events', 0)}/"
                f"{candidate_admission.get('funding_events', 0)} "
                f"{actual_admission.get('funding_cash_pnl', '0')}/"
                f"{candidate_admission.get('funding_cash_pnl', '0')}`"
            ),
            (
                "- fixed / admitted candidate realized contribution / admission Δ: "
                f"`{raw.get('fixed_candidate_final_realized_contribution', '0')} / "
                f"{raw.get('admitted_candidate_final_realized_contribution', '0')} / "
                f"{raw.get('admission_delta_vs_fixed_schedule', '0')}`"
            ),
            (
                "- evidence gate closed / candidate fills / candidate overlap: "
                f"`{readiness.get('min_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('min_candidate_filled_positions', 0)} / "
                f"{readiness.get('min_candidate_overlap_openings', 0)}`"
            ),
            (
                "- still needed C/F/O: "
                f"`{readiness.get('missing_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('missing_candidate_filled_positions', 0)} / "
                f"{readiness.get('missing_candidate_overlap_openings', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_The fixed overlay still reports every opening opportunity. "
                "The causal admission shadow separately skips any opening that "
                "would breach aggregate risk, the shared bucket, venue-aware gross "
                "leverage, available-margin capacity, visible-liquidity capacity, "
                "the venue minimum notional, or the paper liquidation buffer, then "
                "evaluates later openings against the surviving portfolio. Funding "
                "is applied at exact recorded boundaries. It does not invent resized "
                "or replacement trades or changed exits._"
            ),
        ]
    )
    return lines


def _delayed_entry_contribution_decomposition_lines(
    raw: object,
    funding_raw: object = None,
) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry contribution decomposition",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No delayed-entry decomposition telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    by_side = raw.get("by_side", {})
    by_source = raw.get("by_source", {})
    by_cause = raw.get("by_capacity_cause", {})
    readiness = raw.get("readiness", {})
    if not isinstance(overall, dict):
        overall = {}
    if not isinstance(by_side, dict):
        by_side = {}
    if not isinstance(by_source, dict):
        by_source = {}
    if not isinstance(by_cause, dict):
        by_cause = {}
    if not isinstance(readiness, dict):
        readiness = {}

    lines.extend(
        [
            f"- scope: `{raw.get('claim_scope', 'unknown')}`",
            f"- identity: `{raw.get('identity', 'unknown')}`",
            (
                "- closed shadow / evaluated attempts: "
                f"`{raw.get('closed_shadow_outcomes', 0)} / "
                f"{raw.get('evaluated_delayed_attempts', 0)}`"
            ),
            (
                "- missing journal / lineage mismatch: "
                f"`{raw.get('missing_journal_trades', 0)} / "
                f"{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- price / entry-fee / exposure / total Δ PnL: "
                f"`{overall.get('price_effect_pnl', '0')}` / "
                f"`{overall.get('entry_fee_effect_pnl', '0')}` / "
                f"`{overall.get('exposure_effect_pnl', '0')}` / "
                f"`{overall.get('total_delta_pnl', '0')}`"
            ),
            (
                "- aggregate Decimal rounding residual: "
                f"`{overall.get('decimal_rounding_residual_pnl', '0')}`"
            ),
            (
                "- mean price / fee / exposure / total ΔR: "
                f"`{overall.get('mean_price_effect_r')}` / "
                f"`{overall.get('mean_entry_fee_effect_r')}` / "
                f"`{overall.get('mean_exposure_effect_r')}` / "
                f"`{overall.get('mean_total_delta_r')}`"
            ),
            (
                "- price benefit +/− / exposure effect +/−: "
                f"`{overall.get('price_benefit_positive', 0)} / "
                f"{overall.get('price_benefit_negative', 0)} / "
                f"{overall.get('exposure_effect_positive', 0)} / "
                f"{overall.get('exposure_effect_negative', 0)}`"
            ),
            (
                "- evidence gate (closed / evaluated): "
                f"`{readiness.get('min_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('min_evaluated_delayed_attempts', 0)}`"
            ),
            (
                "- still needed closed / evaluated: "
                f"`{readiness.get('missing_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('missing_evaluated_delayed_attempts', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "| Cohort | N | Fill | Price Δ | Fee Δ | Exposure Δ | "
                "Total Δ | Mean total ΔR |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
            ),
        ]
    )

    def row(label: str, item: object) -> None:
        if not isinstance(item, dict):
            return
        lines.append(
            (
                "| {label} | {n} | {fill} | {price} | {fee} | "
                "{exposure} | {total} | {total_r} |"
            ).format(
                label=label,
                n=item.get("trades", 0),
                fill=item.get("mean_fill_fraction"),
                price=item.get("price_effect_pnl", "0"),
                fee=item.get("entry_fee_effect_pnl", "0"),
                exposure=item.get("exposure_effect_pnl", "0"),
                total=item.get("total_delta_pnl", "0"),
                total_r=item.get("mean_total_delta_r"),
            )
        )

    row("Overall", overall)
    row("LONG", by_side.get("long"))
    row("SHORT", by_side.get("short"))
    row("Full fill", by_source.get("full_visible_book_ioc"))
    row("Partial fill", by_source.get("partial_visible_book_ioc"))
    row("No fill", by_source.get("no_fill"))
    for cause, item in sorted(by_cause.items()):
        row(f"Cause: {cause}", item)

    lines.extend(
        [
            "",
            (
                "_Accounting decomposition of the existing fill-weighted "
                "same-exit estimate. Price and entry-fee effects apply only "
                "to filled quantity; exposure effect measures the observed "
                "trade contribution removed by unfilled quantity._"
            ),
        ]
    )

    if isinstance(funding_raw, dict):
        funding_error = funding_raw.get("error")
        funding_overall = funding_raw.get("overall", {})
        if funding_error:
            lines.append(
                f"- funding decomposition research error: `{funding_error}`"
            )
        elif isinstance(funding_overall, dict):
            lines.extend(
                [
                    (
                        "- funding timing / corrected total Δ PnL: "
                        f"`{funding_overall.get('funding_timing_effect_pnl', '0')} / "
                        f"{funding_overall.get('corrected_total_delta_pnl', '0')}`"
                    ),
                    (
                        "- legacy / corrected total Δ PnL: "
                        f"`{funding_overall.get('legacy_total_delta_pnl', '0')} / "
                        f"{funding_overall.get('corrected_total_delta_pnl', '0')}`"
                    ),
                    (
                        "- funding summary Decimal residuals "
                        "components / legacy bridge / candidate bridge: "
                        f"`{funding_overall.get(
                            'component_decimal_rounding_residual_pnl', '0'
                        )} / "
                        f"{funding_overall.get(
                            'legacy_bridge_decimal_rounding_residual_pnl', '0'
                        )} / "
                        f"{funding_overall.get(
                            'candidate_bridge_decimal_rounding_residual_pnl', '0'
                        )}`"
                    ),
                    (
                        "- funding-aware missing journal / funding / lineage: "
                        f"`{funding_raw.get('missing_journal_trades', 0)} / "
                        f"{funding_raw.get('missing_funding_events', 0)} / "
                        f"{funding_raw.get('lineage_mismatches', 0)}`"
                    ),
                    (
                        "_Funding timing is the explicit fourth effect; "
                        "any finite-precision Decimal bridge is reported separately "
                        "and reconciles the aggregate accounting exactly._"
                    ),
                ]
            )
    return lines


def _fill_aware_delay_selector_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Fill-aware 60s/120s delayed-entry selector",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No fill-aware delay telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(
            f"- state restore warning: `{restore_error}`"
        )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    by_side = raw.get("by_side", {})
    by_source = raw.get("by_60s_source", {})
    readiness = raw.get("readiness", {})
    if not isinstance(overall, dict):
        overall = {}
    if not isinstance(by_side, dict):
        by_side = {}
    if not isinstance(by_source, dict):
        by_source = {}
    if not isinstance(readiness, dict):
        readiness = {}

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- prospective start / rule: "
                f"`{raw.get('started_at_ms')}` / "
                f"`{raw.get('rule', 'unknown')}`"
            ),
            (
                "- prospective closed / causal evaluable: "
                f"`{raw.get('prospective_closed_trades', 0)} / "
                f"{raw.get('causal_evaluable_trades', 0)}`"
            ),
            (
                "- selected 60s / 120s: "
                f"`{overall.get('selected_60s', 0)} / "
                f"{overall.get('selected_120s', 0)}`"
            ),
            (
                "- actual / always-60 / always-120 / fill-aware PnL: "
                f"`{overall.get('actual_net_pnl', '0')}` / "
                f"`{overall.get('always_60s_net_pnl', '0')}` / "
                f"`{overall.get('always_120s_net_pnl', '0')}` / "
                f"`{overall.get('fill_aware_net_pnl', '0')}`"
            ),
            (
                "- fill-aware Δ vs actual / 60s / 120s: "
                f"`{overall.get('fill_aware_minus_actual_pnl', '0')}` / "
                f"`{overall.get('fill_aware_minus_60s_pnl', '0')}` / "
                f"`{overall.get('fill_aware_minus_120s_pnl', '0')}`"
            ),
            (
                "- mean selected fill / R contribution: "
                f"`{overall.get('mean_selected_fill_fraction')}` / "
                f"`{overall.get('mean_selected_r_contribution')}`"
            ),
            (
                "- missing 60s / 120s, non-evaluable 60s / 120s: "
                f"`{raw.get('missing_base_outcome', 0)} / "
                f"{raw.get('missing_challenger_outcome', 0)} / "
                f"{raw.get('non_evaluable_base', 0)} / "
                f"{raw.get('non_evaluable_challenger', 0)}`"
            ),
            (
                "- lineage mismatches: "
                f"`{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- evidence gate closed / causal / 60s / 120s: "
                f"`{readiness.get('min_prospective_closed_trades', 0)} / "
                f"{readiness.get('min_causal_evaluable_trades', 0)} / "
                f"{readiness.get('min_selected_60s_trades', 0)} / "
                f"{readiness.get('min_selected_120s_trades', 0)}`"
            ),
            (
                "- still needed C/E/60/120: "
                f"`{readiness.get('missing_prospective_closed_trades', 0)} / "
                f"{readiness.get('missing_causal_evaluable_trades', 0)} / "
                f"{readiness.get('missing_selected_60s_trades', 0)} / "
                f"{readiness.get('missing_selected_120s_trades', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "| Cohort | N | Select 60s | Select 120s | Fill-aware PnL | "
                "Δ vs 60s | Δ vs 120s | Mean fill |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
            ),
        ]
    )

    def row(label: str, item: object) -> None:
        if not isinstance(item, dict):
            return
        lines.append(
            (
                "| {label} | {n} | {s60} | {s120} | {pnl} | "
                "{d60} | {d120} | {fill} |"
            ).format(
                label=label,
                n=item.get("trades", 0),
                s60=item.get("selected_60s", 0),
                s120=item.get("selected_120s", 0),
                pnl=item.get("fill_aware_net_pnl", "0"),
                d60=item.get("fill_aware_minus_60s_pnl", "0"),
                d120=item.get("fill_aware_minus_120s_pnl", "0"),
                fill=item.get("mean_selected_fill_fraction"),
            )
        )

    row("LONG", by_side.get("long"))
    row("SHORT", by_side.get("short"))
    row("60s full fill", by_source.get("full_visible_book_ioc"))
    row("60s partial fill", by_source.get("partial_visible_book_ioc"))
    row("60s no fill", by_source.get("no_fill"))

    lines.extend(
        [
            "",
            (
                "_Prospective causal selector only. A full 60s visible-book IOC "
                "uses 60s; a partial or no-fill 60s attempt waits for the 120s "
                "shadow. Same observed exits are held constant, unfilled "
                "quantity contributes zero, and no replacement trades or "
                "changed stops are modeled._"
            ),
        ]
    )
    return lines


def _delay_selector_comparison_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Markout vs fill-aware delay selector",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No selector-comparison telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(
            f"- state restore warning: `{restore_error}`"
        )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    disagreements = raw.get("disagreements", {})
    readiness = raw.get("readiness", {})
    by_type = raw.get("by_disagreement_type", {})
    if not isinstance(overall, dict):
        overall = {}
    if not isinstance(disagreements, dict):
        disagreements = {}
    if not isinstance(readiness, dict):
        readiness = {}
    if not isinstance(by_type, dict):
        by_type = {}

    lines.extend(
        [
            f"- study: `{raw.get('candidate_id', 'unknown')}`",
            f"- prospective start: `{raw.get('started_at_ms')}`",
            (
                "- prospective closed / causal evaluable / disagreements: "
                f"`{raw.get('prospective_closed_trades', 0)} / "
                f"{raw.get('causal_evaluable_trades', 0)} / "
                f"{raw.get('disagreement_trades', 0)}`"
            ),
            (
                "- agreement / disagreement: "
                f"`{overall.get('agreements', 0)} / "
                f"{overall.get('disagreements', 0)}`"
            ),
            (
                "- both 60s / both 120s / markout60-fill120 / "
                "markout120-fill60: "
                f"`{overall.get('both_60s', 0)} / "
                f"{overall.get('both_120s', 0)} / "
                f"{overall.get('markout_60s_fill_120s', 0)} / "
                f"{overall.get('markout_120s_fill_60s', 0)}`"
            ),
            (
                "- disagreements: fill-aware better / markout better / equal: "
                f"`{disagreements.get('fill_aware_better', 0)} / "
                f"{disagreements.get('markout_better', 0)} / "
                f"{disagreements.get('equal_contribution', 0)}`"
            ),
            (
                "- disagreement PnL markout / fill-aware / delta: "
                f"`{disagreements.get('markout_selector_pnl', '0')}` / "
                f"`{disagreements.get('fill_aware_selector_pnl', '0')}` / "
                f"`{disagreements.get('fill_aware_minus_markout_pnl', '0')}`"
            ),
            (
                "- evidence gate closed / evaluable / disagreements: "
                f"`{readiness.get('min_prospective_closed_trades', 0)} / "
                f"{readiness.get('min_causal_evaluable_trades', 0)} / "
                f"{readiness.get('min_disagreement_trades', 0)}`"
            ),
            (
                "- still needed C/E/D: "
                f"`{readiness.get('missing_prospective_closed_trades', 0)} / "
                f"{readiness.get('missing_causal_evaluable_trades', 0)} / "
                f"{readiness.get('missing_disagreement_trades', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            "| Disagreement | N | Fill-aware better | Markout better | Δ PnL |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for key, label in (
        ("markout_60s_fill_120s", "Markout 60s / Fill-aware 120s"),
        ("markout_120s_fill_60s", "Markout 120s / Fill-aware 60s"),
    ):
        item = by_type.get(key, {})
        if not isinstance(item, dict):
            item = {}
        lines.append(
            "| {label} | {n} | {fill} | {markout} | {delta} |".format(
                label=label,
                n=item.get("trades", 0),
                fill=item.get("fill_aware_better", 0),
                markout=item.get("markout_better", 0),
                delta=item.get(
                    "fill_aware_minus_markout_pnl",
                    "0",
                ),
            )
        )
    lines.extend(
        [
            "",
            (
                "_Paired prospective comparison only. Agreements do not "
                "create selector edge; review readiness requires enough "
                "same-trade disagreements._"
            ),
        ]
    )
    return lines


def _adaptive_delay_selector_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Adaptive 60s/120s delayed-entry selector",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No adaptive-delay telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(
            f"- state restore warning: `{restore_error}`"
        )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    by_side = raw.get("by_side", {})
    robustness = raw.get("robustness", {})
    readiness = raw.get("readiness", {})
    if not isinstance(overall, dict):
        overall = {}
    if not isinstance(by_side, dict):
        by_side = {}
    if not isinstance(robustness, dict):
        robustness = {}
    if not isinstance(readiness, dict):
        readiness = {}
    robustness_60 = robustness.get(
        "adaptive_minus_60s",
        {},
    )
    robustness_120 = robustness.get(
        "adaptive_minus_120s",
        {},
    )
    temporal = robustness.get("temporal", {})
    if not isinstance(robustness_60, dict):
        robustness_60 = {}
    if not isinstance(robustness_120, dict):
        robustness_120 = {}
    if not isinstance(temporal, dict):
        temporal = {}

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- prospective start / rule: "
                f"`{raw.get('started_at_ms')}` / "
                f"`{raw.get('rule', 'unknown')}`"
            ),
            (
                "- causal guard: "
                f"`{raw.get('causality_rule', 'unknown')}`"
            ),
            (
                "- prospective closed / causal evaluable: "
                f"`{raw.get('prospective_closed_trades', 0)} / "
                f"{raw.get('causal_evaluable_trades', 0)}`"
            ),
            (
                "- selected 60s / 120s: "
                f"`{overall.get('selected_60s', 0)} / "
                f"{overall.get('selected_120s', 0)}`"
            ),
            (
                "- actual / always-60 / always-120 / adaptive PnL: "
                f"`{overall.get('actual_net_pnl', '0')}` / "
                f"`{overall.get('always_60s_net_pnl', '0')}` / "
                f"`{overall.get('always_120s_net_pnl', '0')}` / "
                f"`{overall.get('adaptive_net_pnl', '0')}`"
            ),
            (
                "- adaptive Δ vs actual / 60s / 120s: "
                f"`{overall.get('adaptive_minus_actual_pnl', '0')}` / "
                f"`{overall.get('adaptive_minus_60s_pnl', '0')}` / "
                f"`{overall.get('adaptive_minus_120s_pnl', '0')}`"
            ),
            (
                "- mean adaptive fill / R contribution: "
                f"`{overall.get('mean_adaptive_fill_fraction')}` / "
                f"`{overall.get('mean_adaptive_r_contribution')}`"
            ),
            (
                "- missing mid / non-fresh / late signal: "
                f"`{raw.get('missing_mid_outcome', 0)} / "
                f"{raw.get('non_fresh_mid_outcome', 0)} / "
                f"{raw.get('late_mid_signal', 0)}`"
            ),
            (
                "- missing 60s / 120s, non-evaluable 60s / 120s: "
                f"`{raw.get('missing_base_outcome', 0)} / "
                f"{raw.get('missing_challenger_outcome', 0)} / "
                f"{raw.get('non_evaluable_base', 0)} / "
                f"{raw.get('non_evaluable_challenger', 0)}`"
            ),
            (
                "- lineage mismatches: "
                f"`{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- robustness is descriptive only / changes gate: "
                f"`{str(bool(robustness.get('descriptive_only'))).lower()} / "
                f"{str(bool(robustness.get('changes_readiness_gate'))).lower()}`"
            ),
            (
                "- Δ vs 60s robustness total / LOTO trade / LOMO market: "
                f"`{robustness_60.get('total_delta_pnl')} / "
                f"{robustness_60.get('leave_one_trade_out_min_delta')} / "
                f"{robustness_60.get('leave_one_market_out_min_delta')}`"
            ),
            (
                "- Δ vs 60s survives any one trade / market removal: "
                f"`{robustness_60.get('positive_after_any_single_trade_removed')} / "
                f"{robustness_60.get('positive_after_any_single_market_removed')}`"
            ),
            (
                "- Δ vs 120s robustness total / LOTO trade / LOMO market: "
                f"`{robustness_120.get('total_delta_pnl')} / "
                f"{robustness_120.get('leave_one_trade_out_min_delta')} / "
                f"{robustness_120.get('leave_one_market_out_min_delta')}`"
            ),
            (
                "- Δ vs 120s survives any one trade / market removal: "
                f"`{robustness_120.get('positive_after_any_single_trade_removed')} / "
                f"{robustness_120.get('positive_after_any_single_market_removed')}`"
            ),
            (
                "- largest |Δ| market vs 60s / share: "
                f"`{robustness_60.get('largest_abs_market')} / "
                f"{robustness_60.get('largest_abs_market_share')}`"
            ),
            (
                "- largest |Δ| market vs 120s / share: "
                f"`{robustness_120.get('largest_abs_market')} / "
                f"{robustness_120.get('largest_abs_market_share')}`"
            ),
            (
                "- temporal full / positive vs 60s / positive vs 120s: "
                f"`{temporal.get('full_blocks', 0)} / "
                f"{temporal.get('positive_blocks_vs_60s', 0)} / "
                f"{temporal.get('positive_blocks_vs_120s', 0)}`"
            ),
            (
                "- all full temporal blocks positive vs 60s / 120s: "
                f"`{temporal.get('all_full_blocks_positive_vs_60s')} / "
                f"{temporal.get('all_full_blocks_positive_vs_120s')}`"
            ),
            (
                "- temporal block design: "
                f"`{temporal.get('configured_blocks', 0)} × "
                f"{temporal.get('min_trades_per_full_block', 0)} trades`"
            ),
            (
                "- evidence gate closed / causal / 60s / 120s: "
                f"`{readiness.get('min_prospective_closed_trades', 0)} / "
                f"{readiness.get('min_causal_evaluable_trades', 0)} / "
                f"{readiness.get('min_selected_60s_trades', 0)} / "
                f"{readiness.get('min_selected_120s_trades', 0)}`"
            ),
            (
                "- still needed C/E/60/120: "
                f"`{readiness.get('missing_prospective_closed_trades', 0)} / "
                f"{readiness.get('missing_causal_evaluable_trades', 0)} / "
                f"{readiness.get('missing_selected_60s_trades', 0)} / "
                f"{readiness.get('missing_selected_120s_trades', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "| Side | N | Select 60s | Select 120s | Adaptive PnL | "
                "Δ vs 60s | Δ vs 120s | Mean fill |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
            ),
        ]
    )
    for key, label in (("long", "LONG"), ("short", "SHORT")):
        item = by_side.get(key, {})
        if not isinstance(item, dict):
            item = {}
        lines.append(
            (
                "| {label} | {n} | {s60} | {s120} | {pnl} | "
                "{d60} | {d120} | {fill} |"
            ).format(
                label=label,
                n=item.get("trades", 0),
                s60=item.get("selected_60s", 0),
                s120=item.get("selected_120s", 0),
                pnl=item.get("adaptive_net_pnl", "0"),
                d60=item.get("adaptive_minus_60s_pnl", "0"),
                d120=item.get(
                    "adaptive_minus_120s_pnl",
                    "0",
                ),
                fill=item.get("mean_adaptive_fill_fraction"),
            )
        )

    temporal_blocks = temporal.get("chronological_blocks", [])
    if isinstance(temporal_blocks, list) and temporal_blocks:
        lines.extend(
            [
                "",
                "| Time block | N | 60s | 120s | Δ vs 60s | Δ vs 120s |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for block in temporal_blocks:
            if not isinstance(block, dict):
                continue
            lines.append(
                "| {block} | {n} | {s60} | {s120} | {d60} | {d120} |".format(
                    block=block.get("block"),
                    n=block.get("trades", 0),
                    s60=block.get("selected_60s", 0),
                    s120=block.get("selected_120s", 0),
                    d60=block.get("adaptive_minus_60s_pnl", "0"),
                    d120=block.get("adaptive_minus_120s_pnl", "0"),
                )
            )

    lines.extend(
        [
            "",
            (
                "_Prospective causal selector only. At the 60s decision point, "
                "a fresh adverse 1m mid-markout waits to 120s; otherwise the "
                "60s entry is used. Same observed exits are held constant, "
                "unfilled quantity contributes zero, and no replacement trades "
                "or changed stops are modeled. Leave-one-out and chronological "
                "robustness are descriptive only and do not change the frozen "
                "readiness gate._"
            ),
        ]
    )
    return lines


def _delayed_entry_same_exit_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry same-exit contribution",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No delayed-entry same-exit telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    if not isinstance(overall, dict):
        overall = {}
    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    by_side = raw.get("by_side", {})
    if not isinstance(by_side, dict):
        by_side = {}

    lines.extend(
        [
            (
                "- scope: "
                f"`{raw.get('claim_scope', 'unknown')}`"
            ),
            (
                "- funding / exit assumptions: "
                f"`{raw.get('funding_assumption', 'unknown')}` / "
                f"`{raw.get('exit_assumption', 'unknown')}`"
            ),
            (
                "- closed shadow / full fills / evaluated: "
                f"`{raw.get('closed_shadow_outcomes', 0)} / "
                f"{raw.get('full_delayed_fill_outcomes', 0)} / "
                f"{raw.get('evaluated_full_delayed_fills', 0)}`"
            ),
            (
                "- missing journal / lineage mismatch: "
                f"`{raw.get('missing_journal_trades', 0)} / "
                f"{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- actual W/L → estimated W/L: "
                f"`{overall.get('actual_wins', 0)}/"
                f"{overall.get('actual_losses', 0)} → "
                f"{overall.get('candidate_wins_estimate', 0)}/"
                f"{overall.get('candidate_losses_estimate', 0)}`"
            ),
            (
                "- estimated loss→win / win→loss flips: "
                f"`{overall.get('loss_to_win_flips_estimate', 0)} / "
                f"{overall.get('win_to_loss_flips_estimate', 0)}`"
            ),
            (
                "- actual / same-exit estimated PnL / delta: "
                f"`{overall.get('actual_net_pnl', '0')}` / "
                f"`{overall.get('candidate_net_pnl_estimate', '0')}` / "
                f"`{overall.get('delta_net_pnl_estimate', '0')}`"
            ),
            (
                "- actual / estimated mean R / mean delta R: "
                f"`{overall.get('actual_mean_net_r')}` / "
                f"`{overall.get('candidate_mean_net_r_estimate')}` / "
                f"`{overall.get('mean_delta_net_r_estimate')}`"
            ),
            (
                "- evidence gate (closed shadow / full fills): "
                f"`{readiness.get('min_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('min_full_delayed_fills', 0)}`"
            ),
            (
                "- still needed closed / full: "
                f"`{readiness.get('missing_closed_shadow_outcomes', 0)} / "
                f"{readiness.get('missing_full_delayed_fills', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
        ]
    )

    rows = (
        ("long", "LONG"),
        ("short", "SHORT"),
    )
    lines.extend(
        [
            "",
            (
                "| Side | N | Actual W/L | Est W/L | Loss→win | "
                "Actual PnL | Est PnL | Δ PnL | Mean ΔR |"
            ),
            (
                "| --- | ---: | --- | --- | ---: | ---: | ---: | "
                "---: | ---: |"
            ),
        ]
    )
    for key, label in rows:
        item = by_side.get(key, {})
        if not isinstance(item, dict):
            item = {}
        lines.append(
            (
                "| {label} | {n} | {aw}/{al} | {cw}/{cl} | {flip} | "
                "{actual} | {candidate} | {delta} | {delta_r} |"
            ).format(
                label=label,
                n=item.get("trades", 0),
                aw=item.get("actual_wins", 0),
                al=item.get("actual_losses", 0),
                cw=item.get("candidate_wins_estimate", 0),
                cl=item.get("candidate_losses_estimate", 0),
                flip=item.get("loss_to_win_flips_estimate", 0),
                actual=item.get("actual_net_pnl", "0"),
                candidate=item.get("candidate_net_pnl_estimate", "0"),
                delta=item.get("delta_net_pnl_estimate", "0"),
                delta_r=item.get("mean_delta_net_r_estimate"),
            )
        )

    lines.extend(
        [
            "",
            (
                "_Contribution estimate only: the delayed entry price/fee is "
                "substituted while the observed exit price, exit fee, and "
                "funding are held constant. It does not model changed stop "
                "timing, capacity, missed trades, or replacement trades._"
            ),
        ]
    )
    return lines


def _delayed_entry_risk_geometry_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry risk geometry",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No delayed-entry risk-geometry telemetry in this heartbeat._")
        return lines

    lines.append(f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    readiness = raw.get("readiness", {})
    overall = raw.get("overall", {})
    clipped = raw.get("risk_clipped", {})
    by_side = raw.get("by_side", {})
    by_cause = raw.get("by_cause", {})
    if not isinstance(readiness, dict):
        readiness = {}
    if not isinstance(overall, dict):
        overall = {}
    if not isinstance(clipped, dict):
        clipped = {}
    if not isinstance(by_side, dict):
        by_side = {}
    if not isinstance(by_cause, dict):
        by_cause = {}

    lines.extend(
        [
            f"- definition: `{raw.get('definition', 'unknown')}`",
            (
                "- filled attempts / no-fill outcomes: "
                f"`{raw.get('evaluated_filled_attempts', 0)} / "
                f"{raw.get('no_fill_outcomes', 0)}`"
            ),
            (
                "- missing journal / opening plan / lineage / fill price: "
                f"`{raw.get('missing_journal_trades', 0)} / "
                f"{raw.get('missing_opening_plans', 0)} / "
                f"{raw.get('lineage_mismatches', 0)} / "
                f"{raw.get('missing_delayed_fill_price', 0)}`"
            ),
            (
                "- evidence gate (filled / risk-clipped): "
                f"`{readiness.get('min_evaluated_filled_attempts', 0)} / "
                f"{readiness.get('min_risk_clipped_attempts', 0)}`"
            ),
            (
                "- still needed filled / risk-clipped: "
                f"`{readiness.get('missing_evaluated_filled_attempts', 0)} / "
                f"{readiness.get('missing_risk_clipped_attempts', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "| Cohort | N | Fill | Risk used / ceiling | "
                "Full-size risk / ceiling | Risk-capacity fraction | "
                "Unit-risk change | Risk clipped | Full-size > ceiling |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | "
                "---: | ---: |"
            ),
        ]
    )

    def row(label: str, item: object) -> None:
        if not isinstance(item, dict):
            return
        lines.append(
            (
                "| {label} | {n} | {fill} | {util} | {full} | "
                "{capacity} | {unit} | {clipped} | {over} |"
            ).format(
                label=label,
                n=item.get("attempts", 0),
                fill=item.get("mean_fill_fraction"),
                util=item.get("mean_risk_utilization"),
                full=item.get("mean_full_size_risk_ratio"),
                capacity=item.get("mean_risk_capacity_fraction"),
                unit=item.get("mean_unit_risk_change_fraction"),
                clipped=item.get("risk_clipped", 0),
                over=item.get("full_size_risk_above_ceiling", 0),
            )
        )

    row("Overall", overall)
    row("Risk-clipped", clipped)
    row("LONG", by_side.get("long"))
    row("SHORT", by_side.get("short"))
    for cause, item in sorted(by_cause.items()):
        row(f"Cause: {cause}", item)

    lines.extend(
        [
            "",
            (
                "_Risk used is delayed filled risk divided by the original "
                "paper trade risk ceiling. Full-size risk / ceiling above 1 "
                "means the original quantity could not fit the original risk "
                "budget at the observed delayed average fill. This diagnostic "
                "does not change size, stops, risk, delay, or execution._"
            ),
        ]
    )
    return lines


def _prospective_filter_fixed_schedule_lines(
    raw: object,
) -> list[str]:
    if not isinstance(raw, dict):
        return ["- fixed-schedule portfolio: `not available`"]
    actual = raw.get("actual", {})
    candidate = raw.get("candidate", {})
    if not isinstance(actual, dict):
        actual = {}
    if not isinstance(candidate, dict):
        candidate = {}
    return [
        (
            "- fixed-schedule actual / candidate / delta realized contribution: "
            f"`{actual.get('final_realized_contribution', '0')} / "
            f"{candidate.get('final_realized_contribution', '0')} / "
            f"{raw.get('delta_final_realized_contribution', '0')}`"
        ),
        (
            "- fixed-schedule max realized drawdown actual / candidate / delta: "
            f"`{actual.get('max_realized_drawdown', '0')} / "
            f"{candidate.get('max_realized_drawdown', '0')} / "
            f"{raw.get('delta_max_realized_drawdown', '0')}`"
        ),
        (
            "- fixed-schedule max positions / overlap actual→candidate: "
            f"`{actual.get('max_concurrent_positions', 0)} / "
            f"{actual.get('overlap_openings', 0)} → "
            f"{candidate.get('max_concurrent_positions', 0)} / "
            f"{candidate.get('overlap_openings', 0)}`"
        ),
        (
            "- fixed-schedule max gross notional actual / candidate / delta: "
            f"`{actual.get('max_gross_notional', '0')} / "
            f"{candidate.get('max_gross_notional', '0')} / "
            f"{raw.get('delta_max_gross_notional', '0')}`"
        ),
        (
            "- fixed-schedule max planned risk actual / candidate / delta: "
            f"`{actual.get('max_planned_risk', '0')} / "
            f"{candidate.get('max_planned_risk', '0')} / "
            f"{raw.get('delta_max_planned_risk', '0')}`"
        ),
        (
            "- fixed-schedule blocked PnL / admitted / blocked: "
            f"`{raw.get('blocked_actual_net_pnl', '0')} / "
            f"{raw.get('admitted_trades', 0)} / "
            f"{raw.get('blocked_trades', 0)}`"
        ),
        (
            "_Fixed observed schedule only: actual sizes and closes are reused; "
            "replacement trades, equity-driven resizing, changed exits, and "
            "unrealized equity are not modeled. This does not change readiness._"
        ),
    ]


def _prospective_filter_robustness_lines(
    raw: object,
) -> list[str]:
    if not isinstance(raw, dict):
        return [
            "- robustness: `not available`",
        ]

    def optional_bool(value: object) -> str:
        if value is None:
            return "n/a"
        return str(bool(value)).lower()

    temporal = raw.get("temporal", {})
    if not isinstance(temporal, dict):
        temporal = {}
    return [
        (
            "- robustness delta / largest trade contribution / share: "
            f"`{raw.get('total_delta_trade_contribution_pnl', '0')} / "
            f"{raw.get('largest_abs_trade_contribution')} / "
            f"{raw.get('largest_abs_trade_share')}`"
        ),
        (
            "- leave-one-trade min delta / positive after any one removed: "
            f"`{raw.get('leave_one_trade_out_min_delta')} / "
            f"{optional_bool(raw.get('positive_after_any_single_trade_removed'))}`"
        ),
        (
            "- largest market / contribution / share: "
            f"`{raw.get('largest_abs_market')} / "
            f"{raw.get('largest_abs_market_contribution')} / "
            f"{raw.get('largest_abs_market_share')}`"
        ),
        (
            "- leave-one-market min delta / positive after any one removed: "
            f"`{raw.get('leave_one_market_out_min_delta')} / "
            f"{optional_bool(raw.get('positive_after_any_single_market_removed'))}`"
        ),
        (
            "- chronological full blocks / positive / all positive: "
            f"`{temporal.get('full_blocks', 0)} / "
            f"{temporal.get('positive_full_blocks', 0)} / "
            f"{str(bool(temporal.get('all_full_blocks_positive'))).lower()}`"
        ),
        (
            "_Robustness is descriptive only and does not change the frozen "
            "prospective readiness gate._"
        ),
    ]


def _prospective_allowed_residual_lines(
    raw: object,
) -> list[str]:
    if not isinstance(raw, dict):
        return ["- allowed-cohort residual: `not available`"]

    overall = raw.get("overall", {})
    if not isinstance(overall, dict):
        overall = {}

    def grouped(field: str) -> str:
        value = raw.get(field, {})
        if not isinstance(value, dict) or not value:
            return "none"
        parts: list[str] = []
        for label in sorted(value):
            item = value[label]
            if not isinstance(item, dict):
                continue
            parts.append(
                f"{label}=n{item.get('trades', 0)}"
                f"/pnl{item.get('net_pnl', '0')}"
            )
        return ", ".join(parts) if parts else "none"

    def worst(field: str) -> str:
        value = raw.get(field)
        if not isinstance(value, dict):
            return "none"
        return (
            f"{value.get('label')} / "
            f"{value.get('net_pnl')} / "
            f"n{value.get('trades', 0)}"
        )

    return [
        (
            "- allowed residual trades / net / winner PnL / loser PnL: "
            f"`{overall.get('trades', 0)} / "
            f"{overall.get('net_pnl', '0')} / "
            f"{overall.get('winner_pnl', '0')} / "
            f"{overall.get('loser_pnl', '0')}`"
        ),
        f"- residual by side: `{grouped('by_side')}`",
        (
            "- residual by lead strategy: "
            f"`{grouped('by_lead_strategy')}`"
        ),
        f"- residual by rank band: `{grouped('by_rank_band')}`",
        (
            "- worst side×strategy / worst market: "
            f"`{worst('worst_side_lead_strategy')} / "
            f"{worst('worst_market')}`"
        ),
        (
            "_Allowed-cohort residual attribution is descriptive only; "
            "it does not change the frozen filter or readiness gate._"
        ),
    ]


def _prospective_entry_filter_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Prospective LONG-trend entry filter",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No prospective entry-filter telemetry in this heartbeat._")
        return lines

    enabled = bool(raw.get("enabled"))
    lines.append(f"- enabled: `{str(enabled).lower()}`")
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(f"- state restore warning: `{restore_error}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    rule = raw.get("rule", {})
    if not isinstance(rule, dict):
        rule = {}
    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- frozen rule: reject "
                f"`{rule.get('direction', 'unknown')}` + "
                f"`{rule.get('lead_strategy', 'unknown')}`"
            ),
            (
                "- prospective closed / attributed / misses: "
                f"`{raw.get('prospective_closed_trades', 0)} / "
                f"{raw.get('attributed_trades', 0)} / "
                f"{raw.get('attribution_misses', 0)}`"
            ),
            (
                "- allowed / blocked trades: "
                f"`{raw.get('allowed_trades', 0)} / "
                f"{raw.get('blocked_trades', 0)}`"
            ),
            (
                "- blocked wins / losses: "
                f"`{raw.get('blocked_wins', 0)} / "
                f"{raw.get('blocked_losses', 0)}`"
            ),
            (
                "- blocked / allowed net PnL: "
                f"`{raw.get('blocked_net_pnl', '0')}` / "
                f"`{raw.get('allowed_net_pnl', '0')}`"
            ),
            (
                "- actual / candidate trade-contribution PnL: "
                f"`{raw.get('actual_net_pnl', '0')}` / "
                f"`{raw.get('candidate_trade_contribution_pnl', '0')}`"
            ),
            (
                "- delta trade contribution: "
                f"`{raw.get('delta_trade_contribution_pnl', '0')}`"
            ),
            (
                "- evidence gate (prospective / blocked / allowed): "
                f"`{readiness.get('min_prospective_closed_trades', 0)} / "
                f"{readiness.get('min_blocked_trades', 0)} / "
                f"{readiness.get('min_allowed_trades', 0)}`"
            ),
            (
                "- still needed P/B/A: "
                f"`{readiness.get('missing_prospective_closed_trades', 0)} / "
                f"{readiness.get('missing_blocked_trades', 0)} / "
                f"{readiness.get('missing_allowed_trades', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_Trade-contribution study only. It does not claim portfolio "
                "PnL because skipping a trade can change later capacity, "
                "cooldowns, and replacement opportunities._"
            ),
        ]
    )
    lines.extend(
        _prospective_filter_robustness_lines(
            raw.get("robustness")
        )
    )
    lines.extend(
        _prospective_allowed_residual_lines(
            raw.get("allowed_residual")
        )
    )
    lines.extend(
        _prospective_filter_fixed_schedule_lines(
            raw.get("fixed_schedule_portfolio")
        )
    )
    return lines


def _prospective_delayed_price_confirmation_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Prospective 60s delayed price confirmation",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No prospective delayed price-confirmation telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(f"- state restore warning: `{restore_error}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- frozen rule: after `60s`, take the delayed visible-book "
                "IOC only when its simulated average fill is no worse than "
                "the immutable opening-plan reference price; otherwise skip"
            ),
            (
                "- prospective closed / evaluated: "
                f"`{raw.get('prospective_closed_trades', 0)} / "
                f"{raw.get('evaluated_trades', 0)}`"
            ),
            (
                "- confirmed / skipped: "
                f"`{raw.get('confirmed_trades', 0)} / "
                f"{raw.get('skipped_trades', 0)}`"
            ),
            (
                "- worse-price / no-fill skips: "
                f"`{raw.get('worse_price_skips', 0)} / "
                f"{raw.get('no_fill_skips', 0)}`"
            ),
            (
                "- missing outcomes / plans / lineage / unresolved: "
                f"`{raw.get('missing_outcomes', 0)} / "
                f"{raw.get('missing_opening_plans', 0)} / "
                f"{raw.get('lineage_mismatches', 0)} / "
                f"{raw.get('unresolved_outcomes', 0)}`"
            ),
            (
                "- actual / candidate trade-contribution PnL: "
                f"`{raw.get('actual_net_pnl', '0')}` / "
                f"`{raw.get('candidate_trade_contribution_pnl', '0')}`"
            ),
            (
                "- delta trade contribution: "
                f"`{raw.get('delta_trade_contribution_pnl', '0')}`"
            ),
            (
                "- mean confirmed price improvement: "
                f"`{raw.get('mean_confirmed_signed_improvement_bps')}` bps"
            ),
            (
                "- evidence gate (evaluated / confirmed / skipped): "
                f"`{readiness.get('min_prospective_evaluated_trades', 0)} / "
                f"{readiness.get('min_confirmed_trades', 0)} / "
                f"{readiness.get('min_skipped_trades', 0)}`"
            ),
            (
                "- still needed E/C/S: "
                f"`{readiness.get('missing_prospective_evaluated_trades', 0)} / "
                f"{readiness.get('missing_confirmed_trades', 0)} / "
                f"{readiness.get('missing_skipped_trades', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_Prospective closed-trade contribution study only. A skipped "
                "trade contributes zero; replacement trades, changed capacity, "
                "and changed exits are not modeled._"
            ),
        ]
    )
    return lines


def _prospective_top10_rank_filter_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Prospective top-10 scanner-rank filter",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No prospective top-10 rank-filter telemetry in this heartbeat._"
        )
        return lines

    enabled = bool(raw.get("enabled"))
    lines.append(f"- enabled: `{str(enabled).lower()}`")
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(
            f"- state restore warning: `{restore_error}`"
        )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    rule = raw.get("rule", {})
    if not isinstance(rule, dict):
        rule = {}
    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- frozen rule: admit scanner rank "
                f"`1-{rule.get('max_admitted_ordinal', 'unknown')}`; "
                "shadow-reject lower-ranked openings"
            ),
            (
                "- maximum accepted rank age: "
                f"`{rule.get('max_rank_age_ms')}`ms"
            ),
            (
                "- prospective closed / attributed: "
                f"`{raw.get('prospective_closed_trades', 0)} / "
                f"{raw.get('attributed_trades', 0)}`"
            ),
            (
                "- missing / stale rank evidence: "
                f"`{raw.get('missing_rank_evidence', 0)} / "
                f"{raw.get('stale_rank_evidence', 0)}`"
            ),
            (
                "- allowed / blocked trades: "
                f"`{raw.get('allowed_trades', 0)} / "
                f"{raw.get('blocked_trades', 0)}`"
            ),
            (
                "- allowed W/L · blocked W/L: "
                f"`{raw.get('allowed_wins', 0)}/"
                f"{raw.get('allowed_losses', 0)} · "
                f"{raw.get('blocked_wins', 0)}/"
                f"{raw.get('blocked_losses', 0)}`"
            ),
            (
                "- allowed / blocked net PnL: "
                f"`{raw.get('allowed_net_pnl', '0')}` / "
                f"`{raw.get('blocked_net_pnl', '0')}`"
            ),
            (
                "- actual / candidate trade-contribution PnL: "
                f"`{raw.get('actual_net_pnl', '0')}` / "
                f"`{raw.get('candidate_trade_contribution_pnl', '0')}`"
            ),
            (
                "- delta trade contribution: "
                f"`{raw.get('delta_trade_contribution_pnl', '0')}`"
            ),
            (
                "- allowed / blocked mean R: "
                f"`{raw.get('allowed_mean_net_r')}` / "
                f"`{raw.get('blocked_mean_net_r')}`"
            ),
            (
                "- allowed / blocked mean rank: "
                f"`{raw.get('allowed_mean_ordinal')}` / "
                f"`{raw.get('blocked_mean_ordinal')}`"
            ),
            (
                "- evidence gate (prospective / blocked / allowed): "
                f"`{readiness.get('min_prospective_closed_trades', 0)} / "
                f"{readiness.get('min_blocked_trades', 0)} / "
                f"{readiness.get('min_allowed_trades', 0)}`"
            ),
            (
                "- still needed P/B/A: "
                f"`{readiness.get('missing_prospective_closed_trades', 0)} / "
                f"{readiness.get('missing_blocked_trades', 0)} / "
                f"{readiness.get('missing_allowed_trades', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_Prospective closed-trade contribution study only. Existing "
                "rank-11–20 losses from before this study do not count toward "
                "the candidate. It does not claim portfolio PnL or alter the "
                "scanner, shortlist, or entry decision._"
            ),
        ]
    )
    lines.extend(
        _prospective_filter_robustness_lines(
            raw.get("robustness")
        )
    )
    lines.extend(
        _prospective_allowed_residual_lines(
            raw.get("allowed_residual")
        )
    )
    lines.extend(
        _prospective_filter_fixed_schedule_lines(
            raw.get("fixed_schedule_portfolio")
        )
    )
    return lines


def _prospective_combined_matched_overlap_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "#### Matched standalone overlap diagnostic",
        "",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No matched standalone-overlap telemetry in this heartbeat._"
        )
        return lines

    error = raw.get("error")
    if error:
        lines.append(f"- diagnostic error: `{error}`")
        return lines

    reasons = raw.get("by_block_reason", {})
    if not isinstance(reasons, dict):
        reasons = {}

    def reason(key: str) -> dict[str, object]:
        value = reasons.get(key, {})
        return value if isinstance(value, dict) else {}

    long_trend = reason("long_trend")
    rank = reason("rank_above_10")
    both = reason("long_trend_and_rank_above_10")

    lines.extend(
        [
            "- authority: `DESCRIPTIVE RESEARCH ONLY / NO EXECUTION`",
            (
                "- standalone starts entry / top-10 / matched overlap: "
                f"`{raw.get('entry_filter_started_at_ms')} / "
                f"{raw.get('top10_rank_filter_started_at_ms')} / "
                f"{raw.get('overlap_started_at_ms')}`"
            ),
            (
                "- closed since overlap / matched / integrity clean: "
                f"`{raw.get('closed_trades_since_overlap_start', 0)} / "
                f"{raw.get('matched_trades', 0)} / "
                f"{str(bool(raw.get('integrity_clean'))).lower()}`"
            ),
            (
                "- overlap allowed / blocked trades: "
                f"`{raw.get('allowed_trades', 0)} / "
                f"{raw.get('blocked_trades', 0)}`"
            ),
            (
                "- overlap allowed W/L · blocked W/L: "
                f"`{raw.get('allowed_wins', 0)}/"
                f"{raw.get('allowed_losses', 0)} · "
                f"{raw.get('blocked_wins', 0)}/"
                f"{raw.get('blocked_losses', 0)}`"
            ),
            (
                "- overlap actual / candidate / delta trade contribution: "
                f"`{raw.get('actual_net_pnl', '0')} / "
                f"{raw.get('candidate_trade_contribution_pnl', '0')} / "
                f"{raw.get('delta_trade_contribution_pnl', '0')}`"
            ),
            (
                "- overlap misses decision / missing rank / stale rank: "
                f"`{raw.get('decision_attribution_misses', 0)} / "
                f"{raw.get('missing_rank_evidence', 0)} / "
                f"{raw.get('stale_rank_evidence', 0)}`"
            ),
            (
                "- overlap blocked reasons LONG+trend / rank>10 / both "
                "(trades · PnL): "
                f"`{long_trend.get('trades', 0)} · "
                f"{long_trend.get('net_pnl', '0')} / "
                f"{rank.get('trades', 0)} · "
                f"{rank.get('net_pnl', '0')} / "
                f"{both.get('trades', 0)} · "
                f"{both.get('net_pnl', '0')}`"
            ),
            (
                "- fresh combined gate credit / changes readiness gate: "
                f"`{raw.get('fresh_combined_gate_credit', 0)} / "
                f"{str(bool(raw.get('changes_readiness_gate'))).lower()}`"
            ),
            "",
            (
                "_This replays the frozen combined rule only on the time window "
                "shared by the two standalone studies. It is descriptive evidence "
                "only and cannot advance the fresh combined prospective gate._"
            ),
        ]
    )
    lines.extend(
        _prospective_filter_robustness_lines(
            raw.get("robustness")
        )
    )
    lines.extend(
        _prospective_filter_fixed_schedule_lines(
            raw.get("fixed_schedule_portfolio")
        )
    )
    return lines


def _prospective_trade_quality_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Prospective side-neutral trade-quality gate",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No prospective trade-quality telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(f"- state restore warning: `{restore_error}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    by_direction = raw.get("by_direction", {})
    if not isinstance(by_direction, dict):
        by_direction = {}
    long_summary = by_direction.get("long", {})
    short_summary = by_direction.get("short", {})
    if not isinstance(long_summary, dict):
        long_summary = {}
    if not isinstance(short_summary, dict):
        short_summary = {}

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- frozen rule: apply the same rule to LONG and SHORT; "
                "require scanner rank 1-10, wait 60s, then admit only a "
                "non-worse visible-book IOC fill"
            ),
            (
                "- prospective closed / evaluated / admitted / skipped: "
                f"`{raw.get('prospective_closed_trades', 0)} / "
                f"{raw.get('evaluated_trades', 0)} / "
                f"{raw.get('admitted_trades', 0)} / "
                f"{raw.get('skipped_trades', 0)}`"
            ),
            (
                "- skip reasons rank / worse-price / no-fill: "
                f"`{raw.get('rank_skips', 0)} / "
                f"{raw.get('worse_price_skips', 0)} / "
                f"{raw.get('no_fill_skips', 0)}`"
            ),
            (
                "- missing rank / stale rank / delayed / plans / lineage: "
                f"`{raw.get('missing_rank_evidence', 0)} / "
                f"{raw.get('stale_rank_evidence', 0)} / "
                f"{raw.get('missing_delayed_outcomes', 0)} / "
                f"{raw.get('missing_opening_plans', 0)} / "
                f"{raw.get('lineage_mismatches', 0)}`"
            ),
            (
                "- actual / candidate / delta trade-contribution PnL: "
                f"`{raw.get('actual_net_pnl', '0')} / "
                f"{raw.get('candidate_trade_contribution_pnl', '0')} / "
                f"{raw.get('delta_trade_contribution_pnl', '0')}`"
            ),
            (
                "- LONG evaluated/admitted/skipped · candidate PnL: "
                f"`{long_summary.get('evaluated', 0)}/"
                f"{long_summary.get('admitted', 0)}/"
                f"{long_summary.get('skipped', 0)} · "
                f"{long_summary.get('candidate_net_pnl', '0')}`"
            ),
            (
                "- SHORT evaluated/admitted/skipped · candidate PnL: "
                f"`{short_summary.get('evaluated', 0)}/"
                f"{short_summary.get('admitted', 0)}/"
                f"{short_summary.get('skipped', 0)} · "
                f"{short_summary.get('candidate_net_pnl', '0')}`"
            ),
            (
                "- evidence gate evaluated/admitted/skipped/LONG/SHORT: "
                f"`{readiness.get('min_prospective_evaluated_trades', 0)} / "
                f"{readiness.get('min_admitted_trades', 0)} / "
                f"{readiness.get('min_skipped_trades', 0)} / "
                f"{readiness.get('min_long_trades', 0)} / "
                f"{readiness.get('min_short_trades', 0)}`"
            ),
            (
                "- still needed E/A/S/L/S: "
                f"`{readiness.get('missing_prospective_evaluated_trades', 0)} / "
                f"{readiness.get('missing_admitted_trades', 0)} / "
                f"{readiness.get('missing_skipped_trades', 0)} / "
                f"{readiness.get('missing_long_trades', 0)} / "
                f"{readiness.get('missing_short_trades', 0)}`"
            ),
            (
                "- integrity clean / ready for review: "
                f"`{str(bool(readiness.get('integrity_clean'))).lower()} / "
                f"{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_This is a prospective closed-trade contribution shadow. "
                "It does not disable either direction, change actual paper "
                "orders, invent replacement trades, or claim portfolio PnL._"
            ),
        ]
    )
    return lines


def _prospective_combined_entry_filter_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Prospective top-10 + no LONG-trend entry filter",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No prospective combined-filter telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(
            f"- state restore warning: `{restore_error}`"
        )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    rule = raw.get("rule", {})
    readiness = raw.get("readiness", {})
    reasons = raw.get("by_block_reason", {})
    if not isinstance(rule, dict):
        rule = {}
    if not isinstance(readiness, dict):
        readiness = {}
    if not isinstance(reasons, dict):
        reasons = {}

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            f"- prospective start: `{raw.get('started_at_ms')}`",
            (
                "- frozen rule: require scanner rank "
                f"`1-{rule.get('max_admitted_ordinal', 'unknown')}` "
                "and reject `long + trend`"
            ),
            (
                "- maximum accepted rank age: "
                f"`{rule.get('max_rank_age_ms')}`ms"
            ),
            (
                "- prospective closed / attributed: "
                f"`{raw.get('prospective_closed_trades', 0)} / "
                f"{raw.get('attributed_trades', 0)}`"
            ),
            (
                "- allowed / blocked trades: "
                f"`{raw.get('allowed_trades', 0)} / "
                f"{raw.get('blocked_trades', 0)}`"
            ),
            (
                "- allowed W/L · blocked W/L: "
                f"`{raw.get('allowed_wins', 0)}/"
                f"{raw.get('allowed_losses', 0)} · "
                f"{raw.get('blocked_wins', 0)}/"
                f"{raw.get('blocked_losses', 0)}`"
            ),
            (
                "- allowed / blocked net PnL: "
                f"`{raw.get('allowed_net_pnl', '0')} / "
                f"{raw.get('blocked_net_pnl', '0')}`"
            ),
            (
                "- actual / candidate / delta trade contribution: "
                f"`{raw.get('actual_net_pnl', '0')} / "
                f"{raw.get('candidate_trade_contribution_pnl', '0')} / "
                f"{raw.get('delta_trade_contribution_pnl', '0')}`"
            ),
            (
                "- decision misses / missing rank / stale rank: "
                f"`{raw.get('decision_attribution_misses', 0)} / "
                f"{raw.get('missing_rank_evidence', 0)} / "
                f"{raw.get('stale_rank_evidence', 0)}`"
            ),
            (
                "- evidence gate prospective / blocked / allowed: "
                f"`{readiness.get('min_prospective_closed_trades', 0)} / "
                f"{readiness.get('min_blocked_trades', 0)} / "
                f"{readiness.get('min_allowed_trades', 0)}`"
            ),
            (
                "- still needed P/B/A: "
                f"`{readiness.get('missing_prospective_closed_trades', 0)} / "
                f"{readiness.get('missing_blocked_trades', 0)} / "
                f"{readiness.get('missing_allowed_trades', 0)}`"
            ),
            (
                "- integrity clean / ready for review: "
                f"`{str(bool(readiness.get('integrity_clean'))).lower()} / "
                f"{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            "| Block reason | Trades | W | L | Net PnL | Mean R | Mean rank |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for key, label in (
        ("long_trend", "LONG+trend"),
        ("rank_above_10", "rank >10"),
        (
            "long_trend_and_rank_above_10",
            "LONG+trend & rank >10",
        ),
    ):
        item = reasons.get(key, {})
        if not isinstance(item, dict):
            item = {}
        lines.append(
            "| {label} | {trades} | {wins} | {losses} | {pnl} | "
            "{mean_r} | {mean_rank} |".format(
                label=label,
                trades=item.get("trades", 0),
                wins=item.get("wins", 0),
                losses=item.get("losses", 0),
                pnl=item.get("net_pnl", "0"),
                mean_r=item.get("mean_net_r"),
                mean_rank=item.get("mean_ordinal"),
            )
        )

    lines.extend(
        [
            "",
            (
                "_Fresh prospective intersection only: evidence from the earlier "
                "standalone LONG+trend and top-10 studies does not count toward "
                "this gate. Skipped trades contribute zero; replacement trades, "
                "changed capacity, and changed exits are not modeled._"
            ),
        ]
    )
    lines.extend(
        _prospective_filter_robustness_lines(
            raw.get("robustness")
        )
    )
    lines.extend(
        _prospective_allowed_residual_lines(
            raw.get("allowed_residual")
        )
    )
    lines.extend(
        _prospective_filter_fixed_schedule_lines(
            raw.get("fixed_schedule_portfolio")
        )
    )
    lines.extend(
        _prospective_combined_matched_overlap_lines(
            raw.get("matched_standalone_overlap")
        )
    )
    return lines


def _opening_rank_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Opening scanner-rank attribution",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No opening-rank telemetry in this heartbeat._")
        return lines

    enabled = bool(raw.get("enabled"))
    lines.append(f"- enabled: `{str(enabled).lower()}`")
    capture_error = raw.get("capture_error")
    if capture_error:
        lines.append(f"- capture warning: `{capture_error}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    lines.extend(
        [
            (
                "- rank definition: "
                f"`{raw.get('rank_definition', 'unknown')}`"
            ),
            (
                "- rank evidence records / attributed closed trades: "
                f"`{raw.get('evidence_records', 0)} / "
                f"{raw.get('attributed_closed_trades', 0)}`"
            ),
            (
                "- closed trades without prospective rank evidence: "
                f"`{raw.get('closed_trades_without_rank_evidence', 0)}`"
            ),
            (
                "- mean / max rank age at opening: "
                f"`{raw.get('mean_rank_age_ms')}`ms / "
                f"`{raw.get('max_rank_age_ms')}`ms"
            ),
        ]
    )
    groups = raw.get("by_rank_bucket", {})
    if not isinstance(groups, dict):
        groups = {}
    if groups:
        lines.extend(
            [
                "",
                "| Rank bucket | Trades | W | L | BE | Net PnL | Mean R |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for bucket in ("1-5", "6-10", "11-20", "21+"):
            group = groups.get(bucket)
            if not isinstance(group, dict):
                continue
            lines.append(
                (
                    "| {bucket} | {trades} | {wins} | {losses} | "
                    "{breakeven} | {net_pnl} | {mean_r} |"
                ).format(
                    bucket=bucket,
                    trades=group.get("trades", 0),
                    wins=group.get("wins", 0),
                    losses=group.get("losses", 0),
                    breakeven=group.get("breakeven", 0),
                    net_pnl=group.get("net_pnl", "0"),
                    mean_r=group.get("mean_net_r"),
                )
            )
    lines.extend(
        [
            "",
            (
                "_Prospective attribution from the latest coarse universe "
                "rank observed before the opening; it does not alter market "
                "selection or entry decisions._"
            ),
        ]
    )
    return lines


def _opening_fill_liquidity_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Opening fill liquidity",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No fill-liquidity telemetry in this heartbeat._")
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    capture_error = raw.get("capture_error")
    if capture_error:
        lines.append(f"- capture warning: `{capture_error}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    lines.extend(
        [
            (
                "- evidence source: "
                f"`{raw.get('evidence_source', 'unknown')}`"
            ),
            (
                "- records / attributed closed / historical without evidence: "
                f"`{raw.get('evidence_records', 0)} / "
                f"{raw.get('attributed_closed_trades', 0)} / "
                f"{raw.get('closed_trades_without_fill_liquidity_evidence', 0)}`"
            ),
            (
                "- open or pending evidence records: "
                f"`{raw.get('unmatched_open_or_pending_records', 0)}`"
            ),
            (
                "- review gate / still needed: "
                f"`{raw.get('review_gate_closed_trades', 0)} / "
                f"{raw.get('still_needed_closed_trades', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(raw.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "| Cohort | N | W | L | Net PnL | Mean R | Spread bps | "
                "Fill slip bps | Entry depth | Depth used | Dir imbalance | "
                "Book recv age |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
                "---: | ---: | ---: | ---: |"
            ),
        ]
    )

    cohorts = (
        ("overall", "Overall"),
        ("winners", "Winners"),
        ("losers", "Losers"),
    )
    by_side = raw.get("by_side", {})
    if not isinstance(by_side, dict):
        by_side = {}

    def row(label: str, item: object) -> None:
        if not isinstance(item, dict):
            return
        lines.append(
            (
                "| {label} | {n} | {wins} | {losses} | {pnl} | {r} | "
                "{spread} | {slip} | {depth} | {usage} | {imbalance} | "
                "{age}ms |"
            ).format(
                label=label,
                n=item.get("trades", 0),
                wins=item.get("wins", 0),
                losses=item.get("losses", 0),
                pnl=item.get("net_pnl", "0"),
                r=item.get("mean_net_r"),
                spread=item.get("mean_spread_bps"),
                slip=item.get("mean_fill_slippage_bps"),
                depth=item.get("mean_entry_depth_25bps"),
                usage=item.get("mean_entry_depth_usage_fraction"),
                imbalance=item.get("mean_directional_book_imbalance"),
                age=item.get("mean_book_receive_age_ms"),
            )
        )

    for key, label in cohorts:
        row(label, raw.get(key))
    row("LONG", by_side.get("long"))
    row("SHORT", by_side.get("short"))

    lines.extend(
        [
            "",
            (
                "_Prospective exact L2 book consumed by the opening IOC. "
                "Historical trades are not backfilled from decision snapshots. "
                "This is descriptive liquidity attribution only, not an entry filter._"
            ),
        ]
    )
    return lines


def _prospective_capacity_reflow_opportunity_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Candidate capacity-reflow opportunity diagnostic",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No capacity-reflow opportunity telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    def counts(value: object) -> str:
        if not isinstance(value, dict) or not value:
            return "none"
        return ", ".join(
            f"{key}={item}"
            for key, item in sorted(value.items())
        )

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- opportunities / baseline rejected: "
                f"`{raw.get('opportunities', 0)} / "
                f"{raw.get('baseline_rejections', 0)}`"
            ),
            (
                "- candidate-eligible / candidate-blocked rejections: "
                f"`{raw.get('candidate_eligible_rejections', 0)} / "
                f"{raw.get('candidate_blocked_rejections', 0)}`"
            ),
            (
                "- missing rank / stale rank / integrity clean: "
                f"`{raw.get('missing_rank_evidence', 0)} / "
                f"{raw.get('stale_rank_evidence', 0)} / "
                f"{str(bool(raw.get('integrity_clean'))).lower()}`"
            ),
            (
                "- candidate-eligible risk-capacity rejections / "
                "unblocked by one-position release: "
                f"`{raw.get('candidate_eligible_capacity_rejections', 0)} / "
                f"{raw.get('single_position_release_unblocked', 0)}`"
            ),
            (
                "- single-position release options: "
                f"`{raw.get('single_position_release_options', 0)}`"
            ),
            (
                "- baseline rejection reasons: "
                f"`{counts(raw.get('by_baseline_rejection_reason'))}`"
            ),
            (
                "- candidate block reasons: "
                f"`{counts(raw.get('by_candidate_block_reason'))}`"
            ),
            (
                "- release markets: "
                f"`{counts(raw.get('by_release_market'))}`"
            ),
            (
                "- release correlation buckets: "
                f"`{counts(raw.get('by_release_bucket'))}`"
            ),
            (
                "- replacement trades / PnL modeled: "
                f"`{str(bool(raw.get('replacement_trades_modeled'))).lower()} / "
                f"{str(bool(raw.get('pnl_modeled'))).lower()}`"
            ),
            "",
            (
                "_This uses only opportunities actually observed at decision time. "
                "The release test asks whether removing one existing position would "
                "restore aggregate/bucket risk capacity for a candidate-eligible "
                "rejection. It does not yet claim that the released position would "
                "have been filtered, that the replacement would fill, or that its "
                "PnL would be positive._"
            ),
        ]
    )
    return lines


def _prospective_capacity_reflow_release_lineage_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Candidate-filtered capacity release lineage",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No candidate-filtered release-lineage telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    def counts(value: object) -> str:
        if not isinstance(value, dict) or not value:
            return "none"
        return ", ".join(
            f"{key}={item}"
            for key, item in sorted(value.items())
        )

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- release options / resolved: "
                f"`{raw.get('release_options', 0)} / "
                f"{raw.get('resolved_release_options', 0)}`"
            ),
            (
                "- resolved opportunities / candidate-caused capacity "
                "release opportunities: "
                f"`{raw.get('resolved_opportunities', 0)} / "
                f"{raw.get('candidate_capacity_release_opportunities', 0)}`"
            ),
            (
                "- candidate-blocked / candidate-allowed release options: "
                f"`{raw.get('candidate_blocked_release_options', 0)} / "
                f"{raw.get('candidate_allowed_release_options', 0)}`"
            ),
            (
                "- lineage / plan / decision / rank / stale-rank misses: "
                f"`{raw.get('release_lineage_misses', 0)} / "
                f"{raw.get('release_plan_misses', 0)} / "
                f"{raw.get('release_decision_misses', 0)} / "
                f"{raw.get('release_rank_misses', 0)} / "
                f"{raw.get('release_stale_ranks', 0)}`"
            ),
            (
                "- integrity clean: "
                f"`{str(bool(raw.get('integrity_clean'))).lower()}`"
            ),
            (
                "- release-position candidate block reasons: "
                f"`{counts(raw.get('by_release_position_block_reason'))}`"
            ),
            (
                "- candidate-blocked release markets: "
                f"`{counts(raw.get('by_candidate_blocked_release_market'))}`"
            ),
            (
                "- replacement trades / PnL modeled: "
                f"`{str(bool(raw.get('replacement_trades_modeled'))).lower()} / "
                f"{str(bool(raw.get('pnl_modeled'))).lower()}`"
            ),
            "",
            (
                "_This joins each capacity-release option back to the exact "
                "historical opening plan, decision fact, and opening scanner rank. "
                "A candidate-caused capacity release therefore requires a real "
                "capacity-consuming position that the frozen rule itself would "
                "have blocked. Replacement fill, exit, and PnL are still not "
                "modeled._"
            ),
        ]
    )
    return lines


def _prospective_capacity_reflow_fill_feasibility_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Candidate-caused replacement entry fill shadow",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No replacement-entry fill telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    def counts(value: object) -> str:
        if not isinstance(value, dict) or not value:
            return "none"
        return ", ".join(
            f"{key}={item}"
            for key, item in sorted(value.items())
        )

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- causal release options / opportunities: "
                f"`{raw.get('candidate_caused_release_options', 0)} / "
                f"{raw.get('candidate_caused_release_opportunities', 0)}`"
            ),
            (
                "- risk approvals / planning approvals / fillable: "
                f"`{raw.get('conservative_risk_approvals', 0)} / "
                f"{raw.get('planning_approvals', 0)} / "
                f"{raw.get('fillable_options', 0)}`"
            ),
            (
                "- full / partial / no-fill / execution-rejected: "
                f"`{raw.get('full_fill_options', 0)} / "
                f"{raw.get('partial_fill_options', 0)} / "
                f"{raw.get('no_fill_options', 0)} / "
                f"{raw.get('execution_rejected_options', 0)}`"
            ),
            (
                "- gross simulated fill notional / taker fees: "
                f"`{raw.get('gross_fill_notional', '0')} / "
                f"{raw.get('taker_fees', '0')}`"
            ),
            (
                "- counterfactual equity delta min / max: "
                f"`{raw.get('counterfactual_equity_delta_min')} / "
                f"{raw.get('counterfactual_equity_delta_max')}`"
            ),
            (
                "- opportunity markets: "
                f"`{counts(raw.get('by_opportunity_market'))}`"
            ),
            (
                "- released markets: "
                f"`{counts(raw.get('by_release_market'))}`"
            ),
            (
                "- risk rejections: "
                f"`{counts(raw.get('by_risk_rejection'))}`"
            ),
            (
                "- planning rejections: "
                f"`{counts(raw.get('by_planning_rejection'))}`"
            ),
            (
                "- execution results: "
                f"`{counts(raw.get('by_execution_result'))}`"
            ),
            (
                "- counterfactual account scope: "
                f"`{raw.get('counterfactual_account_scope', 'unknown')}`"
            ),
            (
                "- replacement entry fills / exits / trade PnL modeled: "
                f"`{str(bool(raw.get('replacement_entry_fills_modeled'))).lower()} / "
                f"{str(bool(raw.get('replacement_exits_modeled'))).lower()} / "
                f"{str(bool(raw.get('pnl_modeled'))).lower()}`"
            ),
            "",
            (
                "_This starts only from release positions the frozen candidate "
                "itself would have blocked. It reconstructs that persisted same-day "
                "position exactly while holding every other baseline position fixed, "
                "applies a conservative weekly-peak bound, reruns the production "
                "risk engine and opening planner, and simulates the exact captured "
                "decision-time L2 IOC. This is a single-release sensitivity, not a "
                "full candidate-portfolio replay; exit selection and replacement "
                "trade PnL remain unmodeled._"
            ),
        ]
    )
    return lines


def _prospective_capacity_reflow_forward_markout_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Candidate-caused replacement forward markouts",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No replacement forward-markout telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- fillable options / paths available / paths missing: "
                f"`{raw.get('fillable_options', 0)} / "
                f"{raw.get('paths_available', 0)} / "
                f"{raw.get('paths_missing', 0)}`"
            ),
            (
                "- maximum accepted mark lag: "
                f"`{raw.get('max_mark_lag_ms', 0)}`ms"
            ),
            "",
            (
                "| Horizon | Settled | Pending | Stale | Missing path | "
                "+ / - / flat | Gross MTM | Entry-fee-adjusted MTM | "
                "Mean directional return |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | "
                "---: | ---: |"
            ),
        ]
    )

    by_horizon = raw.get("by_horizon")
    if isinstance(by_horizon, dict):
        labels = {
            "300000": "5m",
            "900000": "15m",
            "3600000": "1h",
            "21600000": "6h",
        }
        for horizon_key in sorted(
            by_horizon,
            key=lambda value: int(str(value)),
        ):
            item = by_horizon[horizon_key]
            if not isinstance(item, dict):
                continue
            lines.append(
                "| "
                f"{labels.get(str(horizon_key), str(horizon_key) + 'ms')} | "
                f"{item.get('settled_options', 0)} | "
                f"{item.get('pending_options', 0)} | "
                f"{item.get('stale_options', 0)} | "
                f"{item.get('missing_path_options', 0)} | "
                f"{item.get('positive_options', 0)} / "
                f"{item.get('negative_options', 0)} / "
                f"{item.get('flat_options', 0)} | "
                f"{item.get('gross_mark_to_market_pnl', '0')} | "
                f"{item.get('entry_fee_adjusted_mark_to_market_pnl', '0')} | "
                f"{item.get('mean_directional_return_fraction')} |"
            )

    lines.extend(
        [
            "",
            (
                "- replacement entry fills / forward markouts / exits / "
                "realized PnL modeled: "
                f"`{str(bool(raw.get('replacement_entry_fills_modeled'))).lower()} / "
                f"{str(bool(raw.get('replacement_forward_markouts_modeled'))).lower()} / "
                f"{str(bool(raw.get('replacement_exits_modeled'))).lower()} / "
                f"{str(bool(raw.get('realized_pnl_modeled'))).lower()}`"
            ),
            (
                "_A settled markout uses the first real observed market mark at or "
                "after the fixed horizon, only when it arrives within the configured "
                "lag bound. The economic snapshot includes the simulated entry fee "
                "but no synthetic exit fill or exit fee, so it is mark-to-market "
                "research rather than realized replacement-trade PnL._"
            ),
        ]
    )
    return lines


def _prospective_capacity_reflow_exit_fill_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Candidate-caused replacement exit fills",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No replacement exit-fill telemetry in this heartbeat._"
        )
        return lines
    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- fillable options / captured exit books: "
                f"`{raw.get('fillable_options', 0)} / "
                f"{raw.get('exit_book_records', 0)}`"
            ),
            "",
            (
                "| Horizon | Books | Missing | Full close | Partial close | No fill | "
                "Rejected | Fee-adjusted PnL | Unclosed qty |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | "
                "---: | ---: |"
            ),
        ]
    )
    labels = {
        "300000": "5m",
        "900000": "15m",
        "3600000": "1h",
        "21600000": "6h",
    }
    by_horizon = raw.get("by_horizon")
    if isinstance(by_horizon, dict):
        for horizon_key in sorted(
            by_horizon,
            key=lambda value: int(str(value)),
        ):
            item = by_horizon[horizon_key]
            if not isinstance(item, dict):
                continue
            lines.append(
                "| "
                f"{labels.get(str(horizon_key), str(horizon_key) + 'ms')} | "
                f"{item.get('captured_exit_books', 0)} | "
                f"{item.get('missing_exit_books', 0)} | "
                f"{item.get('full_exit_fills', 0)} | "
                f"{item.get('partial_exit_fills', 0)} | "
                f"{item.get('no_exit_fills', 0)} | "
                f"{item.get('rejected_exit_attempts', 0)} | "
                f"{item.get('entry_exit_fee_adjusted_pnl', '0')} | "
                f"{item.get('unclosed_quantity', '0')} |"
            )
    lines.extend(
        [
            "",
            (
                "- entry fills / exit fills / funding / complete trade PnL / "
                "realized PnL claimed: "
                f"`{str(bool(raw.get('replacement_entry_fills_modeled'))).lower()} / "
                f"{str(bool(raw.get('replacement_exit_fills_modeled'))).lower()} / "
                f"{str(bool(raw.get('funding_modeled'))).lower()} / "
                f"{str(bool(raw.get('replacement_trade_pnl_complete'))).lower()} / "
                f"{str(bool(raw.get('realized_pnl_claimed'))).lower()}`"
            ),
            (
                "_Each exit uses the real captured L2 book, the normal reduce-only "
                "planner, normal paper latency, the configured IOC slippage envelope, "
                "and visible depth. Fee-adjusted close economics exclude funding, so "
                "they are not yet a complete realized replacement-trade PnL claim._"
            ),
        ]
    )
    return lines


def _prospective_capacity_reflow_realized_pnl_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Exact replacement realized PnL",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No exact replacement realized-PnL telemetry in this heartbeat._"
        )
        return lines
    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- exact option-horizons available / funding evidence records: "
                f"`{raw.get('exact_realized_pnl_option_horizons', 0)} / "
                f"{raw.get('funding_evidence_records', 0)}`"
            ),
            "",
            (
                "| Horizon | Options | Simulated | Complete closes | "
                "Zero-boundary exact | Funded exact | Funding missing | "
                "Incomplete/missing | Funding PnL | Exact realized PnL |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | "
                "---: | ---: | ---: |"
            ),
        ]
    )
    labels = {
        "300000": "5m",
        "900000": "15m",
        "3600000": "1h",
        "21600000": "6h",
    }
    by_horizon = raw.get("by_horizon")
    if isinstance(by_horizon, dict):
        for horizon_key in sorted(
            by_horizon,
            key=lambda value: int(str(value)),
        ):
            item = by_horizon[horizon_key]
            if not isinstance(item, dict):
                continue
            lines.append(
                "| "
                f"{labels.get(str(horizon_key), str(horizon_key) + 'ms')} | "
                f"{item.get('options', 0)} | "
                f"{item.get('simulated_exits', 0)} | "
                f"{item.get('complete_closes', 0)} | "
                f"{item.get('zero_funding_boundary_closes', 0)} | "
                f"{item.get('funding_evidence_complete_closes', 0)} | "
                f"{item.get('funding_evidence_missing_closes', 0)} | "
                f"{item.get('incomplete_or_missing_exits', 0)} | "
                f"{item.get('funding_cash_pnl', '0')} | "
                f"{item.get('exact_realized_pnl', '0')} |"
            )
    lines.extend(
        [
            "",
            (
                "- funding evidence modeled / zero-boundary funding exact / "
                "cross-horizon aggregation / strategy PnL claimed: "
                f"`{str(bool(raw.get('funding_evidence_modeled'))).lower()} / "
                f"{str(bool(raw.get('zero_funding_boundary_is_exact_zero_funding'))).lower()} / "
                f"{str(bool(raw.get('cross_horizon_economics_aggregated'))).lower()} / "
                f"{str(bool(raw.get('strategy_level_realized_pnl_claimed'))).lower()}`"
            ),
            (
                "_An option-horizon receives exact realized-PnL credit only when "
                "the replacement position is fully closed and every crossed hourly "
                "funding boundary has exact captured oracle/rate evidence. "
                "Zero-boundary intervals remain exact by construction; missing "
                "funding evidence is never estimated or backfilled._"
            ),
        ]
    )
    return lines

def _prospective_replacement_exit_policy_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Prospective 5m replacement exit candidate",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No prospective replacement-exit telemetry in this heartbeat._"
        )
        return lines
    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(f"- state restore warning: `{restore_error}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    def counts(value: object) -> str:
        if not isinstance(value, dict) or not value:
            return "none"
        return ", ".join(
            f"{key}={item}"
            for key, item in sorted(value.items())
        )

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- freeze start / fixed exit horizon: "
                f"`{raw.get('started_at_ms')} / "
                f"{raw.get('exit_horizon_ms')}ms`"
            ),
            (
                "- discovery options excluded / discovery reused: "
                f"`{raw.get('discovery_options_excluded', 0)} / "
                f"{str(bool(raw.get('discovery_cohort_reused_for_validation'))).lower()}`"
            ),
            (
                "- prospective / exact / incomplete options: "
                f"`{raw.get('prospective_options', 0)} / "
                f"{raw.get('exact_realized_pnl_options', 0)} / "
                f"{raw.get('incomplete_options', 0)}`"
            ),
            (
                "- wins / losses / breakeven: "
                f"`{raw.get('wins', 0)} / "
                f"{raw.get('losses', 0)} / "
                f"{raw.get('breakeven', 0)}`"
            ),
            (
                "- exact realized PnL / mean exact PnL: "
                f"`{raw.get('exact_realized_pnl', '0')} / "
                f"{raw.get('mean_exact_realized_pnl')}`"
            ),
            (
                "- zero-boundary / funded exact options: "
                f"`{raw.get('zero_boundary_exact_options', 0)} / "
                f"{raw.get('funded_exact_options', 0)}`"
            ),
            (
                "- incomplete reasons: "
                f"`{counts(raw.get('incomplete_reason_counts'))}`"
            ),
            (
                "- cross-horizon selection frozen / strategy PnL claimed: "
                f"`{str(bool(raw.get('cross_horizon_selection_frozen'))).lower()} / "
                f"{str(bool(raw.get('strategy_level_pnl_claimed'))).lower()}`"
            ),
            "",
            (
                "_The 5-minute horizon was nominated from a pre-freeze discovery "
                "cohort. This gate counts only opportunities observed after the "
                "durable freeze timestamp and requires exact real-L2 exits plus "
                "complete captured funding evidence. It cannot promote or execute._"
            ),
        ]
    )
    return lines


def _prospective_replacement_exit_robustness_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Prospective 5m replacement exit robustness",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No prospective replacement-exit robustness telemetry in this heartbeat._"
        )
        return lines
    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    temporal = raw.get("temporal")
    temporal = temporal if isinstance(temporal, dict) else {}
    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- prospective / exact / incomplete / exact coverage: "
                f"`{raw.get('prospective_options', 0)} / "
                f"{raw.get('exact_options', 0)} / "
                f"{raw.get('incomplete_options', 0)} / "
                f"{raw.get('exact_coverage_fraction')}`"
            ),
            (
                "- exact sample / minimum for review / sample ready: "
                f"`{raw.get('exact_options', 0)} / "
                f"{raw.get('minimum_exact_options_for_review', 0)} / "
                f"{str(bool(raw.get('sample_ready_for_review'))).lower()}`"
            ),
            (
                "- exact PnL / gross profit / gross loss / profit factor: "
                f"`{raw.get('total_exact_realized_pnl', '0')} / "
                f"{raw.get('gross_profit', '0')} / "
                f"{raw.get('gross_loss_abs', '0')} / "
                f"{raw.get('profit_factor')}`"
            ),
            (
                "- largest option PnL / market / absolute-share: "
                f"`{raw.get('largest_abs_option_pnl')} / "
                f"{raw.get('largest_abs_option_market')} / "
                f"{raw.get('largest_abs_option_share')}`"
            ),
            (
                "- leave-one-option min PnL / stays positive: "
                f"`{raw.get('leave_one_option_out_min_pnl')} / "
                f"{str(bool(raw.get('positive_after_any_single_option_removed'))).lower()}`"
            ),
            (
                "- largest market / PnL / absolute-share: "
                f"`{raw.get('largest_abs_market')} / "
                f"{raw.get('largest_abs_market_pnl')} / "
                f"{raw.get('largest_abs_market_share')}`"
            ),
            (
                "- leave-one-market min PnL / stays positive: "
                f"`{raw.get('leave_one_market_out_min_pnl')} / "
                f"{str(bool(raw.get('positive_after_any_single_market_removed'))).lower()}`"
            ),
            (
                "- chronological full blocks / positive / all positive: "
                f"`{temporal.get('full_blocks', 0)} / "
                f"{temporal.get('positive_full_blocks', 0)} / "
                f"{str(bool(temporal.get('all_full_blocks_positive'))).lower()}`"
            ),
            "",
            (
                "_This is a post-freeze robustness diagnostic only. It cannot "
                "change the fixed 5-minute rule, promote it, or execute it._"
            ),
        ]
    )
    return lines


def _prospective_replacement_exit_readiness_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Prospective 5m replacement exit review gate",
        "",
        "- authority: `RESEARCH REVIEW ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No prospective replacement-exit readiness telemetry in this heartbeat._"
        )
        return lines
    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    failed = raw.get("failed_requirements")
    failed_text = (
        "none"
        if not isinstance(failed, list) or not failed
        else ", ".join(str(item) for item in failed)
    )
    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- ready for review / promotion authority / execution authority: "
                f"`{str(bool(raw.get('ready_for_review'))).lower()} / "
                f"{str(bool(raw.get('promotion_authority'))).lower()} / "
                f"{str(bool(raw.get('execution_authority'))).lower()}`"
            ),
            (
                "- exact outcomes / missing to minimum: "
                f"`{raw.get('exact_options', 0)} / "
                f"{raw.get('missing_exact_options', 0)}`"
            ),
            (
                "- exact PnL / profit factor: "
                f"`{raw.get('total_exact_realized_pnl', '0')} / "
                f"{raw.get('profit_factor')}`"
            ),
            (
                "- leave-one option / market stays positive: "
                f"`{str(bool(raw.get('positive_after_any_single_option_removed'))).lower()} / "
                f"{str(bool(raw.get('positive_after_any_single_market_removed'))).lower()}`"
            ),
            (
                "- temporal full / positive / all positive: "
                f"`{raw.get('temporal_full_blocks', 0)} / "
                f"{raw.get('temporal_positive_full_blocks', 0)} / "
                f"{str(bool(raw.get('temporal_all_full_blocks_positive'))).lower()}`"
            ),
            f"- failed requirements: `{failed_text}`",
            "",
            (
                "_This gate was frozen before the prospective sample matured. "
                "Passing it only means the candidate is ready for human review; "
                "it cannot promote the rule or authorize execution._"
            ),
        ]
    )
    return lines


def _prospective_capacity_reflow_forward_excursion_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Candidate-caused replacement forward excursion",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No replacement forward-excursion telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- fillable options / paths available / paths missing: "
                f"`{raw.get('fillable_options', 0)} / "
                f"{raw.get('paths_available', 0)} / "
                f"{raw.get('paths_missing', 0)}`"
            ),
            "",
            (
                "| Horizon | Settled | Pending | Stale | Missing | "
                "Positive peak | Negative end | Peak→negative | "
                "Best MTM | End MTM | Giveback | Mean time-to-best |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | "
                "---: | ---: | ---: | ---: | ---: |"
            ),
        ]
    )

    by_horizon = raw.get("by_horizon")
    if isinstance(by_horizon, dict):
        labels = {
            "300000": "5m",
            "900000": "15m",
            "3600000": "1h",
            "21600000": "6h",
        }
        for horizon_key in sorted(
            by_horizon,
            key=lambda value: int(str(value)),
        ):
            item = by_horizon[horizon_key]
            if not isinstance(item, dict):
                continue
            mean_time_to_best = item.get("mean_time_to_best_ms")
            mean_time_label = (
                "n/a"
                if mean_time_to_best is None
                else f"{mean_time_to_best}ms"
            )
            lines.append(
                "| "
                f"{labels.get(str(horizon_key), str(horizon_key) + 'ms')} | "
                f"{item.get('settled_options', 0)} | "
                f"{item.get('pending_options', 0)} | "
                f"{item.get('stale_options', 0)} | "
                f"{item.get('missing_path_options', 0)} | "
                f"{item.get('positive_peak_options', 0)} | "
                f"{item.get('negative_end_options', 0)} | "
                f"{item.get('positive_peak_to_negative_end_options', 0)} | "
                f"{item.get('best_entry_fee_adjusted_mtm_pnl', '0')} | "
                f"{item.get('ending_entry_fee_adjusted_mtm_pnl', '0')} | "
                f"{item.get('peak_to_end_giveback_pnl', '0')} | "
                f"{mean_time_label} |"
            )

    lines.extend(
        [
            "",
            (
                "- forward excursions / exits / realized PnL modeled: "
                f"`{str(bool(raw.get('replacement_forward_excursions_modeled'))).lower()} / "
                f"{str(bool(raw.get('replacement_exits_modeled'))).lower()} / "
                f"{str(bool(raw.get('realized_pnl_modeled'))).lower()}`"
            ),
            (
                "_This measures best/worst observed mark-to-market and peak giveback "
                "inside the same bounded forward paths used by the fixed-horizon "
                "markout study. It identifies decay and reversals without selecting "
                "a synthetic exit or claiming realized replacement-trade PnL._"
            ),
        ]
    )
    return lines


def _prospective_daily_loss_lockout_reflow_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Candidate daily-loss lockout reflow",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No daily-loss lockout reflow telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    def counts(value: object) -> str:
        if not isinstance(value, dict) or not value:
            return "none"
        return ", ".join(
            f"{key}={item}"
            for key, item in sorted(value.items())
        )

    lines.extend(
        [
            f"- candidate: `{raw.get('candidate_id', 'unknown')}`",
            (
                "- daily-loss lockouts / rule-eligible / "
                "candidate-blocked: "
                f"`{raw.get('daily_loss_lockout_opportunities', 0)} / "
                f"{raw.get('candidate_rule_eligible_lockout_opportunities', 0)} / "
                f"{raw.get('candidate_blocked_lockout_opportunities', 0)}`"
            ),
            (
                "- causal eligible after account-day verification: "
                f"`{raw.get('candidate_eligible_lockout_opportunities', 0)}`"
            ),
            (
                "- account day verified / legacy-unverified / mismatched / "
                "provenance complete: "
                f"`{raw.get('account_day_verified_lockout_opportunities', 0)} / "
                f"{raw.get('account_day_unverified_lockout_opportunities', 0)} / "
                f"{raw.get('account_day_mismatch_lockout_opportunities', 0)} / "
                f"{str(bool(raw.get('account_day_provenance_complete'))).lower()}`"
            ),
            (
                "- opportunity rank missing / stale / integrity clean: "
                f"`{raw.get('opportunity_missing_rank_evidence', 0)} / "
                f"{raw.get('opportunity_stale_rank_evidence', 0)} / "
                f"{str(bool(raw.get('opportunity_integrity_clean'))).lower()}`"
            ),
            (
                "- causal opportunity integrity clean: "
                f"`{str(bool(raw.get('causal_opportunity_integrity_clean'))).lower()}`"
            ),
            (
                "- same-day / cross-day closed-trade instances / open positions: "
                f"`{raw.get('same_day_closed_trade_instances', 0)} / "
                f"{raw.get('cross_day_closed_trade_instances', 0)} / "
                f"{raw.get('open_position_instances', 0)}`"
            ),
            (
                "- cross-day cash modeled / misses / complete: "
                f"`{raw.get('cross_day_cash_modeled_instances', 0)} / "
                f"{raw.get('cross_day_cash_model_misses', 0)} / "
                f"{str(bool(raw.get('cross_day_cash_model_complete'))).lower()}`"
            ),
            (
                "- candidate-blocked closed-trade instances / distinct trades: "
                f"`{raw.get('candidate_blocked_closed_trade_instances', 0)} / "
                f"{raw.get('distinct_candidate_blocked_trade_ids', 0)}`"
            ),
            (
                "- candidate-blocked cross-day trade instances: "
                f"`{raw.get('candidate_blocked_cross_day_trade_instances', 0)}`"
            ),
            (
                "- baseline cash reconciliation misses / clean: "
                f"`{raw.get('baseline_cash_reconciliation_misses', 0)} / "
                f"{str(bool(raw.get('baseline_cash_reconciliation_clean'))).lower()}`"
            ),
            (
                "- trade decision / rank / stale-rank misses: "
                f"`{raw.get('trade_decision_attribution_misses', 0)} / "
                f"{raw.get('trade_rank_attribution_misses', 0)} / "
                f"{raw.get('trade_stale_rank_attribution', 0)}`"
            ),
            (
                "- closed-trade-adjusted unlocks / exact cash scope / "
                "exact candidate unlocks: "
                f"`{raw.get('closed_trade_adjusted_unlock_opportunities', 0)} / "
                f"{raw.get('exact_cash_scope_opportunities', 0)} / "
                f"{raw.get('exact_candidate_unlock_opportunities', 0)}`"
            ),
            (
                "- baseline daily PnL range / candidate-adjusted range: "
                f"`{raw.get('baseline_daily_realized_pnl_min')} .. "
                f"{raw.get('baseline_daily_realized_pnl_max')} / "
                f"{raw.get('candidate_daily_realized_pnl_min')} .. "
                f"{raw.get('candidate_daily_realized_pnl_max')}`"
            ),
            (
                "- daily-loss threshold range: "
                f"`{raw.get('daily_loss_threshold_min')} .. "
                f"{raw.get('daily_loss_threshold_max')}`"
            ),
            (
                "- removed blocked-trade daily cash range: "
                f"`{raw.get('removed_blocked_trade_cash_pnl_min')} .. "
                f"{raw.get('removed_blocked_trade_cash_pnl_max')}`"
            ),
            (
                "- cross-day reconstructed daily cash range: "
                f"`{raw.get('cross_day_daily_cash_min')} .. "
                f"{raw.get('cross_day_daily_cash_max')}`"
            ),
            (
                "- removed-trade candidate block reasons: "
                f"`{counts(raw.get('by_removed_trade_block_reason'))}`"
            ),
            "- open-position cash effects modeled: `false`",
            (
                "- cross-day trade cash effects modeled: "
                f"`{str(bool(raw.get('cross_day_trade_cash_effects_modeled'))).lower()}`"
            ),
            "- replacement trades / PnL modeled: `false / false`",
            "",
            (
                "_The captured daily realized PnL is authoritative. Same-day "
                "closed trades use journal net cash; cross-day trades reconstruct "
                "only current-day exit-fill realized PnL, exit fees, and verified "
                "funding accruals. Causal unlock analysis additionally requires the "
                "captured risk snapshot to prove the correct UTC account-day start; "
                "legacy or mismatched day state is quarantined rather than inferred. "
                "Exact unlock credit then requires complete candidate attribution, "
                "exact daily-cash reconciliation, and no unmodeled open-position "
                "cash effects._"
            ),
        ]
    )
    return lines


def _opening_opportunity_evidence_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Opening opportunity evidence",
        "",
        "- authority: `RESEARCH CAPTURE ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No opening-opportunity capture telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    capture_error = raw.get("capture_error")
    if capture_error:
        lines.append(f"- capture warning: `{capture_error}`")
    forward_mark_error = raw.get("forward_mark_capture_error")
    if forward_mark_error:
        lines.append(
            f"- forward-mark capture warning: `{forward_mark_error}`"
        )
    exit_book_error = raw.get("exit_book_capture_error")
    if exit_book_error:
        lines.append(
            f"- exit-book capture warning: `{exit_book_error}`"
        )
    lines.extend(
        [
            (
                "- records / baseline approvals / baseline rejections: "
                f"`{raw.get('records', 0)} / "
                f"{raw.get('baseline_approvals', 0)} / "
                f"{raw.get('baseline_rejections', 0)}`"
            ),
            (
                "- scanner rank complete / missing: "
                f"`{raw.get('rank_complete', 0)} / "
                f"{raw.get('rank_missing', 0)}`"
            ),
            (
                "- forward mark paths / horizon-complete: "
                f"`{raw.get('forward_mark_paths', 0)} / "
                f"{raw.get('forward_mark_paths_complete', 0)}`"
            ),
            (
                "- forward mark horizon: "
                f"`{raw.get('forward_mark_max_age_ms')}`ms"
            ),
            (
                "- forward mark completion lag: "
                f"`{raw.get('forward_mark_max_completion_lag_ms')}`ms"
            ),
            (
                "- exit-book capture start: "
                f"`{raw.get('exit_book_capture_started_at_ms')}`"
            ),
            (
                "- exit-book registered / captured / pending / missed: "
                f"`{raw.get('exit_book_registered_opportunities', 0)} / "
                f"{raw.get('exit_book_captures', 0)} / "
                f"{raw.get('exit_book_pending', 0)} / "
                f"{raw.get('exit_book_missed', 0)}`"
            ),
            (
                "- exit-book horizons: "
                f"`{raw.get('exit_book_horizons_ms', [])}`"
            ),
            (
                "- exit-book maximum capture lag: "
                f"`{raw.get('exit_book_max_capture_lag_ms')}`ms"
            ),
            (
                "- exit-book capture enabled: "
                f"`{str(bool(raw.get('exit_book_enabled'))).lower()}`"
            ),
            (
                "- exact risk request / full L2 book captured: "
                f"`{str(bool(raw.get('exact_risk_request_captured'))).lower()} / "
                f"{str(bool(raw.get('full_l2_book_captured'))).lower()}`"
            ),
            (
                "- replacement trades modeled: "
                f"`{str(bool(raw.get('replacement_trades_modeled'))).lower()}`"
            ),
            (
                "- opportunity state digest: "
                f"`{raw.get('state_digest', 'unknown')}`"
            ),
            (
                "- forward mark state digest: "
                f"`{raw.get('forward_mark_state_digest', 'unknown')}`"
            ),
            (
                "- exit-book state digest: "
                f"`{raw.get('exit_book_state_digest', 'unknown')}`"
            ),
            "",
            (
                "_Prospective decision-time evidence plus durable forward marks and "
                "real horizon L2 exit books. Exit-book capture starts only when the "
                "protocol is installed and never retroactively substitutes current "
                "liquidity for missed history. These books enable later executable "
                "replacement-exit replay; realized replacement PnL and live execution "
                "remain unmodeled._"
            ),
        ]
    )
    return lines


def _replacement_funding_evidence_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### Replacement funding boundary evidence",
        "",
        "- authority: `RESEARCH CAPTURE ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No replacement-funding capture telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("capture_error")
    if error:
        lines.append(f"- capture warning: `{error}`")

    lines.extend(
        [
            (
                "- capture start / registered opportunities: "
                f"`{raw.get('capture_started_at_ms')} / "
                f"{raw.get('registered_opportunities', 0)}`"
            ),
            (
                "- required boundaries / fresh oracle candidates / captured: "
                f"`{raw.get('required_boundaries', 0)} / "
                f"{raw.get('oracle_candidates', 0)} / "
                f"{raw.get('captured_boundaries', 0)}`"
            ),
            (
                "- pending / missed boundaries: "
                f"`{raw.get('pending_boundaries', 0)} / "
                f"{raw.get('missed_boundaries', 0)}`"
            ),
            (
                "- maximum replacement window / oracle age / funding lag: "
                f"`{raw.get('max_window_ms')}`ms / "
                f"`{raw.get('max_oracle_age_ms')}`ms / "
                f"`{raw.get('max_funding_capture_lag_ms')}`ms"
            ),
            (
                "- funding PnL modeled: "
                f"`{str(bool(raw.get('funding_pnl_modeled'))).lower()}`"
            ),
            (
                "- state digest: "
                f"`{raw.get('state_digest', 'unknown')}`"
            ),
            "",
            (
                "_Funding-boundary evidence is prospective only. Each captured hour "
                "requires a real oracle snapshot observed before the boundary within "
                "the same freshness limit used by paper execution, plus the exact "
                "public funding-history rate for that boundary. This capture does not "
                "yet add funding to replacement PnL or change execution authority._"
            ),
        ]
    )
    return lines


def _entry_markout_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Post-entry markout diagnostic",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No entry-markout telemetry in this heartbeat._")
        return lines

    enabled = bool(raw.get("enabled"))
    lines.append(f"- enabled: `{str(enabled).lower()}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    lines.extend(
        [
            (
                "- definition: "
                f"`{raw.get('definition', 'unknown')}`"
            ),
            (
                "- complete paths / incomplete skipped: "
                f"`{raw.get('complete_path_records', 0)} / "
                f"{raw.get('incomplete_paths_skipped', 0)}`"
            ),
            (
                "- maximum accepted observation lag: "
                f"`{raw.get('max_observation_lag_ms')}`ms"
            ),
            (
                "- missing journal / decision attribution: "
                f"`{raw.get('missing_journal_trade', 0)} / "
                f"{raw.get('missing_decision_attribution', 0)}`"
            ),
            (
                "- missing / stale scanner-rank attribution: "
                f"`{raw.get('missing_rank_attribution', 0)} / "
                f"{raw.get('stale_rank_attribution', 0)}`"
            ),
            (
                "- accepted scanner-rank age / observed mean / max: "
                f"`{raw.get('max_accepted_rank_age_ms')}`ms / "
                f"`{raw.get('mean_rank_age_ms')}`ms / "
                f"`{raw.get('max_rank_age_ms')}`ms"
            ),
            (
                "- evidence gate (observations per horizon): "
                f"`{readiness.get('min_observations_per_horizon', 0)}`"
            ),
            (
                "- all horizons ready for review: "
                f"`{str(bool(readiness.get('all_horizons_ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
        ]
    )

    horizons = raw.get("by_horizon_ms", {})
    if not isinstance(horizons, dict):
        horizons = {}
    rows = (
        ("60000", "1m"),
        ("300000", "5m"),
        ("900000", "15m"),
    )
    lines.extend(
        [
            "",
            (
                "| Horizon | Status | N | Need | + | - | Mean bps | "
                "Mean gross R | Censored | Missing mark | Stale mark | "
                "Mean lag | Max lag |"
            ),
            (
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | "
                "---: | ---: | ---: | ---: | ---: | ---: |"
            ),
        ]
    )
    for key, label in rows:
        item = horizons.get(key, {})
        if not isinstance(item, dict):
            item = {}
        lines.append(
            (
                "| {label} | {status} | {n} | {need} | {positive} | "
                "{negative} | {bps} | {r} | {censored} | {missing} | "
                "{stale} | {mean_lag}ms | {max_lag}ms |"
            ).format(
                label=label,
                status=item.get("readiness_status", "collecting"),
                n=item.get("observations", 0),
                need=item.get("missing_observations", 0),
                positive=item.get("positive", 0),
                negative=item.get("negative", 0),
                bps=item.get("mean_signed_return_bps"),
                r=item.get("mean_gross_r"),
                censored=item.get("censored_before_horizon", 0),
                missing=item.get("missing_observed_mark", 0),
                stale=item.get("stale_observed_mark", 0),
                mean_lag=item.get("mean_observation_lag_ms"),
                max_lag=item.get("max_observation_lag_ms"),
            )
        )

    def grouped_line(
        key: str,
        label: str,
        field: str,
    ) -> None:
        horizon = horizons.get(key, {})
        if not isinstance(horizon, dict):
            return
        groups = horizon.get(field, {})
        if not isinstance(groups, dict) or not groups:
            return
        parts: list[str] = []
        for name, value in sorted(groups.items()):
            if not isinstance(value, dict):
                continue
            parts.append(
                f"{name}: n={value.get('observations', 0)}, "
                f"meanR={value.get('mean_gross_r')}, "
                f"meanbps={value.get('mean_signed_return_bps')}"
            )
        if parts:
            lines.append(f"- {label}: " + "; ".join(parts))

    lines.append("")
    grouped_line("60000", "1m by side", "by_side")
    grouped_line(
        "60000",
        "1m by lead strategy",
        "by_lead_strategy",
    )
    grouped_line(
        "60000",
        "1m by scanner rank",
        "by_scanner_rank_bucket",
    )
    grouped_line(
        "60000",
        "1m by decision age",
        "by_decision_age_bucket",
    )
    grouped_line("300000", "5m by side", "by_side")
    grouped_line(
        "300000",
        "5m by lead strategy",
        "by_lead_strategy",
    )
    grouped_line(
        "300000",
        "5m by scanner rank",
        "by_scanner_rank_bucket",
    )
    grouped_line(
        "300000",
        "5m by decision age",
        "by_decision_age_bucket",
    )
    grouped_line("900000", "15m by side", "by_side")
    grouped_line(
        "900000",
        "15m by lead strategy",
        "by_lead_strategy",
    )
    grouped_line(
        "900000",
        "15m by scanner rank",
        "by_scanner_rank_bucket",
    )
    grouped_line(
        "900000",
        "15m by decision age",
        "by_decision_age_bucket",
    )
    lines.extend(
        [
            "",
            (
                "_Signed markout from the actual paper entry price using the "
                "first observed exact-path mark at or after each fixed "
                "horizon, only when it arrives within the freshness bound. "
                "Short-lived trades are censored; stale/missing marks are "
                "reported and never imputed._"
            ),
        ]
    )
    return lines


def _entry_markout_predictiveness_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Entry markout → final outcome",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No markout-predictiveness telemetry in this heartbeat._")
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    lines.extend(
        [
            (
                "- definition: "
                f"`{raw.get('definition', 'unknown')}`"
            ),
            (
                "- complete paths / incomplete skipped: "
                f"`{raw.get('complete_path_records', 0)} / "
                f"{raw.get('incomplete_paths_skipped', 0)}`"
            ),
            (
                "- all horizons ready for review: "
                f"`{str(bool(raw.get('all_horizons_ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
        ]
    )

    horizons = raw.get("by_horizon_ms", {})
    if not isinstance(horizons, dict):
        horizons = {}
    rows = (("60000", "1m"), ("300000", "5m"), ("900000", "15m"))
    lines.extend(
        [
            "",
            (
                "| H | N | Sign accuracy | Fav N/W/L | Fav mean final R | "
                "Adv N/W/L | Adv mean final R | Need N/F/A |"
            ),
            (
                "| --- | ---: | ---: | --- | ---: | --- | ---: | --- |"
            ),
        ]
    )
    for key, label in rows:
        item = horizons.get(key, {})
        if not isinstance(item, dict):
            item = {}
        favorable = item.get("favorable", {})
        adverse = item.get("adverse", {})
        readiness = item.get("readiness", {})
        if not isinstance(favorable, dict):
            favorable = {}
        if not isinstance(adverse, dict):
            adverse = {}
        if not isinstance(readiness, dict):
            readiness = {}
        lines.append(
            (
                "| {label} | {n} | {accuracy} | {fn}/{fw}/{fl} | {fr} | "
                "{an}/{aw}/{al} | {ar} | {needn}/{needf}/{needa} |"
            ).format(
                label=label,
                n=item.get("observations", 0),
                accuracy=item.get("sign_accuracy"),
                fn=favorable.get("trades", 0),
                fw=favorable.get("wins", 0),
                fl=favorable.get("losses", 0),
                fr=favorable.get("mean_final_net_r"),
                an=adverse.get("trades", 0),
                aw=adverse.get("wins", 0),
                al=adverse.get("losses", 0),
                ar=adverse.get("mean_final_net_r"),
                needn=readiness.get("missing_observations", 0),
                needf=readiness.get("missing_favorable", 0),
                needa=readiness.get("missing_adverse", 0),
            )
        )
    lines.extend(
        [
            "",
            (
                "_This tests whether early markout sign predicts the eventual "
                "closed-trade result. It does not create an entry filter or "
                "exit rule._"
            ),
        ]
    )
    return lines


def _excursion_timing_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Exact-path excursion timing",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No excursion-timing telemetry in this heartbeat._")
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    gate = raw.get("evidence_gate", {})
    if not isinstance(gate, dict):
        gate = {}
    overall = raw.get("overall", {})
    if not isinstance(overall, dict):
        overall = {}
    thresholds = overall.get("thresholds", {})
    if not isinstance(thresholds, dict):
        thresholds = {}

    lines.extend(
        [
            (
                "- complete paths / incomplete skipped: "
                f"`{raw.get('complete_paths_evaluated', 0)} / "
                f"{raw.get('incomplete_paths_skipped', 0)}`"
            ),
            (
                "- missing journal / decision / excursion facts: "
                f"`{raw.get('missing_journal_trade', 0)} / "
                f"{raw.get('missing_decision_attribution', 0)} / "
                f"{raw.get('missing_excursion_metric', 0)}`"
            ),
            (
                "- evidence gate / still needed: "
                f"`{gate.get('min_complete_paths', 0)} / "
                f"{gate.get('missing_complete_paths', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(gate.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "- mean / median time-to-MFE: "
                f"`{overall.get('mean_time_to_mfe_ms')}ms / "
                f"{overall.get('median_time_to_mfe_ms')}ms`"
            ),
            (
                "- mean time-to-MAE: "
                f"`{overall.get('mean_time_to_mae_ms')}ms`"
            ),
            (
                "- mean / median peak-to-close: "
                f"`{overall.get('mean_peak_to_close_ms')}ms / "
                f"{overall.get('median_peak_to_close_ms')}ms`"
            ),
            (
                "- mean peak-to-close share of hold: "
                f"`{overall.get('mean_peak_to_close_fraction_of_hold')}`"
            ),
            "",
            (
                "| Threshold | Reached | Reach fraction | Mean first hit | "
                "Median first hit | Losing closes after hit | "
                "Loser hit→close mean |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
            ),
        ]
    )

    for threshold in ("0.25", "0.5", "1"):
        item = thresholds.get(threshold, {})
        if not isinstance(item, dict):
            item = {}
        lines.append(
            (
                "| +{threshold}R | {reached} | {fraction} | "
                "{mean_hit}ms | {median_hit}ms | {losers} | "
                "{loser_close}ms |"
            ).format(
                threshold=threshold,
                reached=item.get("reached", 0),
                fraction=item.get("reach_fraction"),
                mean_hit=item.get("mean_first_hit_ms"),
                median_hit=item.get("median_first_hit_ms"),
                losers=item.get("losing_closes_after_reach", 0),
                loser_close=item.get(
                    "mean_reach_to_close_ms_for_losers"
                ),
            )
        )

    def grouped_line(field: str, label: str) -> None:
        values = raw.get(field, {})
        if not isinstance(values, dict) or not values:
            return
        parts: list[str] = []
        for name, item in sorted(values.items()):
            if not isinstance(item, dict):
                continue
            group_thresholds = item.get("thresholds", {})
            if not isinstance(group_thresholds, dict):
                group_thresholds = {}
            half = group_thresholds.get("0.5", {})
            one = group_thresholds.get("1", {})
            if not isinstance(half, dict):
                half = {}
            if not isinstance(one, dict):
                one = {}
            parts.append(
                f"{name}: n={item.get('trades', 0)}, "
                f"MFE={item.get('mean_time_to_mfe_ms')}ms, "
                f"peak→close={item.get('mean_peak_to_close_ms')}ms, "
                f"+0.5R={half.get('reached', 0)}, "
                f"+1R={one.get('reached', 0)}"
            )
        if parts:
            lines.append(f"- {label}: " + "; ".join(parts))

    lines.append("")
    grouped_line("by_side", "by side")
    grouped_line("by_lead_strategy", "by lead strategy")
    grouped_line("by_exit_reason", "by exit path")
    lines.extend(
        [
            "",
            (
                "_Timing is measured only from complete exact mark paths. "
                "It describes when favorable/adverse excursion happened and "
                "how long peak profit was exposed before the actual close; "
                "it does not change stops, entries, or exits._"
            ),
        ]
    )
    return lines


def _entry_mid_markout_shadow_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Prospective allMids entry markout shadow",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No allMids entry-markout telemetry in this heartbeat._"
        )
        return lines

    enabled = bool(raw.get("enabled"))
    lines.append(f"- enabled: `{str(enabled).lower()}`")
    lines.append(
        "- durable across workers: "
        f"`{str(bool(raw.get('durable_state'))).lower()}` · "
        "restored this worker: "
        f"`{str(bool(raw.get('state_restored'))).lower()}`"
    )
    restore_error = raw.get("state_restore_error")
    if restore_error:
        lines.append(f"- state restore warning: `{restore_error}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}

    lines.extend(
        [
            f"- source: `{raw.get('source', 'unknown')}`",
            (
                "- maximum accepted observation lag: "
                f"`{raw.get('max_observation_lag_ms')}`ms"
            ),
            (
                "- eligible / excluded open positions: "
                f"`{raw.get('eligible_open_positions', 0)} / "
                f"{raw.get('excluded_open_positions', 0)}`"
            ),
            (
                "- completed prospective trades / excluded / unmatched closes: "
                f"`{raw.get('closed_trade_count', 0)} / "
                f"{raw.get('excluded_closed_trades', 0)} / "
                f"{raw.get('unmatched_closed_trades', 0)}`"
            ),
            (
                "- lineage-mismatch closes / orphaned restored positions: "
                f"`{raw.get('lineage_mismatch_closed_trades', 0)} / "
                f"{raw.get('orphaned_restored_positions', 0)}`"
            ),
            (
                "- evidence gate: "
                f"`{readiness.get('min_fresh_observations_per_horizon', 0)}` "
                "fresh observations per horizon · max non-fresh "
                f"`{readiness.get('max_non_fresh_fraction')}`"
            ),
            (
                "- all horizons ready for review: "
                f"`{str(bool(readiness.get('all_horizons_ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
        ]
    )

    horizons = raw.get("by_horizon_ms", {})
    if not isinstance(horizons, dict):
        horizons = {}
    lines.extend(
        [
            "",
            (
                "| Horizon | Status | Fresh | Need | Non-fresh | Coverage | "
                "Stale | Censored | Missing close | + | - | Mean bps | "
                "Mean gross R | Mean lag | Max lag |"
            ),
            (
                "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | "
                "---: | ---: | ---: | ---: | ---: | ---: | ---: |"
            ),
        ]
    )
    for key, label in (
        ("60000", "1m"),
        ("300000", "5m"),
        ("900000", "15m"),
    ):
        item = horizons.get(key, {})
        if not isinstance(item, dict):
            item = {}
        lines.append(
            (
                "| {label} | {status} | {fresh} | {need} | {non_fresh} | "
                "{coverage} | {stale} | {censored} | {missing} | "
                "{positive} | {negative} | {bps} | {r} | "
                "{mean_lag}ms | {max_lag}ms |"
            ).format(
                label=label,
                status=item.get("readiness_status", "collecting"),
                fresh=item.get("fresh", 0),
                need=item.get("missing_fresh_observations", 0),
                non_fresh=item.get("non_fresh_fraction"),
                coverage=(
                    "ok"
                    if item.get("coverage_quality_ready") is True
                    else "collecting"
                ),
                stale=item.get("stale", 0),
                censored=item.get("censored", 0),
                missing=item.get("missing_at_close", 0),
                positive=item.get("positive", 0),
                negative=item.get("negative", 0),
                bps=item.get("mean_signed_return_bps"),
                r=item.get("mean_gross_r"),
                mean_lag=item.get("mean_observation_lag_ms"),
                max_lag=item.get("max_observation_lag_ms"),
            )
        )

    def grouped_line(
        key: str,
        label: str,
        field: str,
    ) -> None:
        horizon = horizons.get(key, {})
        if not isinstance(horizon, dict):
            return
        groups = horizon.get(field, {})
        if not isinstance(groups, dict) or not groups:
            return
        parts: list[str] = []
        for name, value in sorted(groups.items()):
            if not isinstance(value, dict):
                continue
            parts.append(
                f"{name}: n={value.get('observations', 0)}, "
                f"meanR={value.get('mean_gross_r')}, "
                f"meanbps={value.get('mean_signed_return_bps')}"
            )
        if parts:
            lines.append(f"- {label}: " + "; ".join(parts))

    lines.append("")
    grouped_line("60000", "1m by side", "by_side")
    grouped_line(
        "60000",
        "1m by lead strategy",
        "by_lead_strategy",
    )
    grouped_line("300000", "5m by side", "by_side")
    grouped_line(
        "300000",
        "5m by lead strategy",
        "by_lead_strategy",
    )
    grouped_line("900000", "15m by side", "by_side")
    grouped_line(
        "900000",
        "15m by lead strategy",
        "by_lead_strategy",
    )
    lines.extend(
        [
            "",
            (
                "_Prospective public mid-price observation from the existing "
                "allMids feed. Review readiness also requires adequate fresh "
                "coverage, clean lineage, and zero unmatched closes. It is not "
                "a mark-price claim, executable fill, entry rule, or promotion "
                "signal._"
            ),
        ]
    )
    return lines


def _drawdown_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Drawdown / high-water",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No drawdown telemetry in this heartbeat._")
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    sampled = raw.get("sampled_account", {})
    realized = raw.get("realized_closed_trade", {})
    if not isinstance(sampled, dict):
        sampled = {}
    if not isinstance(realized, dict):
        realized = {}

    lines.extend(
        [
            "",
            "#### Sampled account equity",
            "",
            (
                "- definition / configured checkpoint interval: "
                f"`{sampled.get('definition', 'unknown')}` / "
                f"`{sampled.get('checkpoint_seconds')}s`"
            ),
            (
                "- first / last / peak sample timestamps: "
                f"`{sampled.get('first_timestamp_ms')} / "
                f"{sampled.get('last_timestamp_ms')} / "
                f"{sampled.get('peak_timestamp_ms')}`"
            ),
            (
                "- observed mean sample interval: "
                f"`{sampled.get('mean_observation_interval_ms')}ms`"
            ),
            (
                "- durable state restored / restore warning: "
                f"`{str(bool(sampled.get('state_restored'))).lower()}` / "
                f"`{sampled.get('state_restore_error')}`"
            ),
            (
                "- observations / first / latest / peak equity: "
                f"`{sampled.get('observation_count', 0)} / "
                f"{sampled.get('first_equity')} / "
                f"{sampled.get('last_equity')} / "
                f"{sampled.get('peak_equity')}`"
            ),
            (
                "- current drawdown amount / fraction: "
                f"`{sampled.get('current_drawdown_amount')} / "
                f"{sampled.get('current_drawdown_fraction')}`"
            ),
            (
                "- maximum drawdown amount / fraction: "
                f"`{sampled.get('max_drawdown_amount')} / "
                f"{sampled.get('max_drawdown_fraction')}`"
            ),
            (
                "- max-DD peak / trough equity: "
                f"`{sampled.get('max_drawdown_peak_equity')} / "
                f"{sampled.get('max_drawdown_trough_equity')}`"
            ),
            (
                "- max-DD peak / trough timestamps: "
                f"`{sampled.get('max_drawdown_peak_timestamp_ms')} / "
                f"{sampled.get('max_drawdown_trough_timestamp_ms')}`"
            ),
            "",
            "#### Realized closed-trade equity",
            "",
            (
                "- closed trades / starting / ending / peak equity: "
                f"`{realized.get('closed_trades', 0)} / "
                f"{realized.get('starting_equity')} / "
                f"{realized.get('ending_realized_equity')} / "
                f"{realized.get('peak_realized_equity')}`"
            ),
            (
                "- maximum drawdown amount / fraction: "
                f"`{realized.get('max_drawdown_amount')} / "
                f"{realized.get('max_drawdown_fraction')}`"
            ),
            (
                "- max-DD peak / trough equity: "
                f"`{realized.get('max_drawdown_peak_equity')} / "
                f"{realized.get('max_drawdown_trough_equity')}`"
            ),
            (
                "- max-DD peak / trough timestamps: "
                f"`{realized.get('max_drawdown_peak_timestamp_ms')} / "
                f"{realized.get('max_drawdown_trough_timestamp_ms')}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_Sampled account drawdown includes unrealized PnL only when "
                "the durable checkpoint is actually persisted; scheduling can "
                "make observations coarser than the configured interval, and "
                "intra-sample extremes can be missed. Realized drawdown is the "
                "exact chronological "
                "closed-trade equity curve._"
            ),
        ]
    )
    return lines


def _account_lifecycle_bridge_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Account lifecycle reconciliation",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No lifecycle reconciliation in this heartbeat._")
        return lines

    enabled = bool(raw.get("enabled"))
    lines.append(f"- enabled: `{str(enabled).lower()}`")
    error = raw.get("error")
    if error:
        lines.append(f"- reconciliation error: `{error}`")
        return lines

    account = raw.get("account", {})
    open_lifecycles = raw.get("open_lifecycles", {})
    closed = raw.get("implied_fully_closed_lifecycles", {})
    journal = raw.get("journal_closed_trades", {})
    reconciliation = raw.get("reconciliation", {})
    for item in (
        account,
        open_lifecycles,
        closed,
        journal,
        reconciliation,
    ):
        if not isinstance(item, dict):
            lines.append("_Lifecycle reconciliation payload is malformed._")
            return lines

    lines.extend(
        [
            (
                "- absolute reconciliation tolerance: "
                f"`{reconciliation.get('absolute_tolerance')}`"
            ),
            (
                "- fully closed journal matches account-implied closed "
                "economics: "
                f"`{str(bool(reconciliation.get('closed_journal_matches_account'))).lower()}`"
            ),
            (
                "- realized cash bridge / equity bridge match: "
                f"`{str(bool(reconciliation.get('realized_bridge_matches_account'))).lower()} / "
                f"{str(bool(reconciliation.get('equity_bridge_matches_account'))).lower()}`"
            ),
            (
                "- account cash bridge delta: "
                f"`{reconciliation.get('cash_bridge_delta')}` · match: "
                f"`{str(bool(reconciliation.get('cash_bridge_matches_account'))).lower()}`"
            ),
            (
                "- closed gross / fees / funding / net deltas: "
                f"`{reconciliation.get('closed_gross_delta')} / "
                f"{reconciliation.get('closed_fees_delta')} / "
                f"{reconciliation.get('closed_funding_delta')} / "
                f"{reconciliation.get('closed_net_delta')}`"
            ),
            (
                "- realized / equity bridge deltas: "
                f"`{reconciliation.get('realized_bridge_delta')} / "
                f"{reconciliation.get('equity_bridge_delta')}`"
            ),
            "",
            (
                "| Bucket | Realized gross | Fees | Funding | "
                "Realized net | Unrealized | Mark-to-market |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
            ),
            (
                "| Open lifecycles | {gross} | {fees} | {funding} | "
                "{net} | {unrealized} | {mtm} |"
            ).format(
                gross=open_lifecycles.get("realized_gross_pnl", "0"),
                fees=open_lifecycles.get("fees", "0"),
                funding=open_lifecycles.get("funding", "0"),
                net=open_lifecycles.get("realized_net_cash", "0"),
                unrealized=open_lifecycles.get("unrealized_pnl", "0"),
                mtm=open_lifecycles.get("mark_to_market_pnl", "0"),
            ),
            (
                "| Fully closed (account implied) | {gross} | {fees} | "
                "{funding} | {net} | — | — |"
            ).format(
                gross=closed.get("realized_gross_pnl", "0"),
                fees=closed.get("fees", "0"),
                funding=closed.get("funding", "0"),
                net=closed.get("net_pnl", "0"),
            ),
            (
                "| Closed journal | {gross} | {fees} | {funding} | "
                "{net} | — | — |"
            ).format(
                gross=journal.get("realized_gross_pnl", "0"),
                fees=journal.get("fees", "0"),
                funding=journal.get("funding", "0"),
                net=journal.get("net_pnl", "0"),
            ),
            (
                "| Account total | {gross} | {fees} | {funding} | "
                "{net} | {unrealized} | {total} |"
            ).format(
                gross=account.get("realized_gross_pnl", "0"),
                fees=account.get("cumulative_fees", "0"),
                funding=account.get("cumulative_funding", "0"),
                net=account.get("realized_net_cash", "0"),
                unrealized=account.get("unrealized_pnl", "0"),
                total=account.get("total_account_pnl", "0"),
            ),
        ]
    )

    positions = open_lifecycles.get("positions", [])
    if isinstance(positions, list) and positions:
        lines.extend(
            [
                "",
                "#### Open lifecycle cumulative economics",
                "",
                (
                    "| Market | Side | Qty left | Realized gross | Fees | "
                    "Funding | Realized net | Unrealized | Lifecycle MTM |"
                ),
                (
                    "| --- | --- | ---: | ---: | ---: | ---: | ---: | "
                    "---: | ---: |"
                ),
            ]
        )
        for position in positions:
            if not isinstance(position, dict):
                continue
            lines.append(
                (
                    "| {market} | {side} | {qty} | {gross} | {fees} | "
                    "{funding} | {net} | {unrealized} | {mtm} |"
                ).format(
                    market=position.get("market"),
                    side=position.get("side"),
                    qty=position.get("remaining_quantity"),
                    gross=position.get("cumulative_realized_gross_pnl"),
                    fees=position.get("cumulative_fees"),
                    funding=position.get("cumulative_funding"),
                    net=position.get("realized_net_cash"),
                    unrealized=position.get("unrealized_gross_pnl"),
                    mtm=position.get("lifecycle_mark_to_market_pnl"),
                )
            )

    lines.extend(
        [
            "",
            (
                "_Open-position cumulative realized PnL, fees, and funding "
                "can move account cash before the lifecycle is fully closed. "
                "This bridge separates those amounts from closed journal trades._"
            ),
        ]
    )
    return lines


def _entry_decision_age_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Entry decision age at fill",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No decision-age telemetry in this heartbeat._")
        return lines

    enabled = bool(raw.get("enabled"))
    lines.append(f"- enabled: `{str(enabled).lower()}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    if not isinstance(overall, dict):
        overall = {}
    lines.extend(
        [
            (
                "- definition: "
                f"`{raw.get('definition', 'unknown')}`"
            ),
            (
                "- attributed closed trades / misses: "
                f"`{raw.get('attributed_closed_trades', 0)} / "
                f"{raw.get('attribution_misses', 0)}`"
            ),
            (
                "- review gate / still needed: "
                f"`{raw.get('minimum_attributed_trades_for_review', 0)} / "
                f"{raw.get('still_needed_for_review', 0)}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(raw.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            (
                "- mean / median / p90 / max age: "
                f"`{overall.get('mean_decision_age_ms')}` / "
                f"`{overall.get('median_decision_age_ms')}` / "
                f"`{overall.get('p90_decision_age_ms')}` / "
                f"`{overall.get('max_decision_age_ms')}` ms"
            ),
            (
                "- age >=5s / >=15s / >=30s / >=60s: "
                f"`{raw.get('older_than_5s', 0)} / "
                f"{raw.get('older_than_15s', 0)} / "
                f"{raw.get('older_than_30s', 0)} / "
                f"{raw.get('older_than_60s', 0)}`"
            ),
        ]
    )

    groups = raw.get("by_age_band", {})
    if not isinstance(groups, dict):
        groups = {}
    lines.extend(
        [
            "",
            "| Decision age | Trades | W | L | BE | Net PnL | Mean R | Mean age |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for label in (
        "<1s",
        "1-<5s",
        "5-<15s",
        "15-<30s",
        "30-<60s",
        "60s+",
    ):
        item = groups.get(label, {})
        if not isinstance(item, dict):
            item = {}
        lines.append(
            (
                "| {label} | {trades} | {wins} | {losses} | {be} | "
                "{pnl} | {mean_r} | {mean_age}ms |"
            ).format(
                label=label,
                trades=item.get("trades", 0),
                wins=item.get("wins", 0),
                losses=item.get("losses", 0),
                be=item.get("breakeven", 0),
                pnl=item.get("net_pnl", "0"),
                mean_r=item.get("mean_net_r"),
                mean_age=item.get("mean_decision_age_ms"),
            )
        )

    def grouped_line(field: str, label: str) -> None:
        values = raw.get(field, {})
        if not isinstance(values, dict) or not values:
            return
        parts: list[str] = []
        for name, item in sorted(values.items()):
            if not isinstance(item, dict):
                continue
            parts.append(
                f"{name}: n={item.get('trades', 0)}, "
                f"meanAge={item.get('mean_decision_age_ms')}ms, "
                f"meanR={item.get('mean_net_r')}, "
                f"net={item.get('net_pnl')}"
            )
        if parts:
            lines.append(f"- {label}: " + "; ".join(parts))

    lines.append("")
    grouped_line("by_side", "by side")
    grouped_line("by_lead_strategy", "by lead strategy")
    lines.extend(
        [
            "",
            (
                "_Age is measured from the persisted strategy decision "
                "timestamp to the first actual opening fill. This diagnostic "
                "does not delay, reject, or reprioritize entries._"
            ),
        ]
    )
    return lines


def _closed_trade_robustness_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Closed-trade robustness sensitivity",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No robustness telemetry in this heartbeat._")
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    one = raw.get("remove_best_one", {})
    if not isinstance(one, dict):
        one = {}
    two = raw.get("remove_best_two", {})
    if not isinstance(two, dict):
        two = {}
    market = raw.get("remove_top_positive_market", {})
    if not isinstance(market, dict):
        market = {}

    lines.extend(
        [
            (
                "- closed trades / review gate / still needed: "
                f"`{raw.get('closed_trades', 0)} / "
                f"{readiness.get('min_closed_trades', 0)} / "
                f"{readiness.get('missing_closed_trades', 0)}`"
            ),
            (
                "- largest winner PnL / R: "
                f"`{raw.get('largest_winner_net_pnl')} / "
                f"{raw.get('largest_winner_net_r')}`"
            ),
            (
                "- top-1 / top-2 share of gross profit: "
                f"`{raw.get('top_one_winner_share_of_gross_profit')} / "
                f"{raw.get('top_two_winner_share_of_gross_profit')}`"
            ),
            (
                "- top positive market / net PnL / trades / "
                "positive-market-PnL share: "
                f"`{raw.get('top_positive_market')} / "
                f"{raw.get('top_positive_market_net_pnl')} / "
                f"{raw.get('top_positive_market_trade_count', 0)} / "
                f"{raw.get('top_positive_market_share_of_positive_market_pnl')}`"
            ),
            "",
            (
                "| Scenario | Remaining | Net PnL | Mean R | Median R | "
                "Profit factor | Positive PnL? |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            (
                "| Remove best 1 | {n} | {pnl} | {mean} | {median} | "
                "{pf} | {positive} |"
            ).format(
                n=one.get("remaining_trades", 0),
                pnl=one.get("net_pnl", "0"),
                mean=one.get("mean_net_r"),
                median=one.get("median_net_r"),
                pf=one.get("profit_factor"),
                positive=str(bool(one.get("positive_net_pnl"))).lower(),
            ),
            (
                "| Remove best 2 | {n} | {pnl} | {mean} | {median} | "
                "{pf} | {positive} |"
            ).format(
                n=two.get("remaining_trades", 0),
                pnl=two.get("net_pnl", "0"),
                mean=two.get("mean_net_r"),
                median=two.get("median_net_r"),
                pf=two.get("profit_factor"),
                positive=str(bool(two.get("positive_net_pnl"))).lower(),
            ),
            (
                "| Remove top positive market ({market_name}) | {n} | "
                "{pnl} | {mean} | {median} | {pf} | {positive} |"
            ).format(
                market_name=raw.get("top_positive_market"),
                n=market.get("remaining_trades", 0),
                pnl=market.get("net_pnl", "0"),
                mean=market.get("mean_net_r"),
                median=market.get("median_net_r"),
                pf=market.get("profit_factor"),
                positive=str(
                    bool(market.get("positive_net_pnl"))
                ).lower(),
            ),
            (
                "- positive PnL survives remove best 1 / best 2: "
                f"`{str(bool(raw.get('positive_pnl_survives_remove_best_one'))).lower()} / "
                f"{str(bool(raw.get('positive_pnl_survives_remove_best_two'))).lower()}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_Deterministic sensitivity only: it removes the largest "
                "realized winners or every trade from the top positive market "
                "inside the same closed-trade sample. It does not invent "
                "replacement trades or claim portfolio PnL._"
            ),
        ]
    )
    return lines


def _closed_trade_stability_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Closed-trade chronological stability",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No stability telemetry in this heartbeat._")
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    readiness = raw.get("readiness", {})
    if not isinstance(readiness, dict):
        readiness = {}
    stability = raw.get("stability", {})
    if not isinstance(stability, dict):
        stability = {}
    rolling = raw.get("rolling", {})
    if not isinstance(rolling, dict):
        rolling = {}

    lines.extend(
        [
            (
                "- closed trades / review gate / still needed: "
                f"`{raw.get('closed_trades', 0)} / "
                f"{readiness.get('min_closed_trades', 0)} / "
                f"{readiness.get('missing_closed_trades', 0)}`"
            ),
            (
                "- chronological blocks / min trades per block: "
                f"`{readiness.get('chronological_blocks', 0)} / "
                f"{readiness.get('min_trades_per_block', 0)}`"
            ),
            (
                "- full blocks / all positive PnL / all positive mean R: "
                f"`{stability.get('full_blocks', 0)} / "
                f"{str(bool(stability.get('all_full_blocks_positive_net_pnl'))).lower()} / "
                f"{str(bool(stability.get('all_full_blocks_positive_mean_net_r'))).lower()}`"
            ),
            (
                "- ready for review: "
                f"`{str(bool(readiness.get('ready_for_review'))).lower()}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "| Window | N windows | Positive PnL fraction | "
                "Positive mean-R fraction | Latest PnL | Latest mean R | "
                "Worst mean R | Best mean R |"
            ),
            (
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
            ),
        ]
    )
    for key in ("5", "10"):
        item = rolling.get(key, {})
        if not isinstance(item, dict):
            item = {}
        latest = item.get("latest", {})
        if not isinstance(latest, dict):
            latest = {}
        lines.append(
            (
                "| {size} trades | {count} | {pnl_fraction} | "
                "{r_fraction} | {latest_pnl} | {latest_r} | "
                "{worst_r} | {best_r} |"
            ).format(
                size=key,
                count=item.get("window_count", 0),
                pnl_fraction=item.get("positive_pnl_fraction"),
                r_fraction=item.get("positive_mean_r_fraction"),
                latest_pnl=latest.get("net_pnl"),
                latest_r=latest.get("mean_net_r"),
                worst_r=item.get("worst_mean_net_r"),
                best_r=item.get("best_mean_net_r"),
            )
        )

    blocks = raw.get("chronological_blocks", [])
    if not isinstance(blocks, list):
        blocks = []
    lines.extend(
        [
            "",
            "| Block | Trades | W | L | Net PnL | Mean R | PF |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for block in blocks:
        if not isinstance(block, dict):
            continue
        lines.append(
            (
                "| {block} | {trades} | {wins} | {losses} | "
                "{pnl} | {mean_r} | {pf} |"
            ).format(
                block=block.get("block"),
                trades=block.get("trades", 0),
                wins=block.get("wins", 0),
                losses=block.get("losses", 0),
                pnl=block.get("net_pnl"),
                mean_r=block.get("mean_net_r"),
                pf=block.get("profit_factor"),
            )
        )

    lines.extend(
        [
            "",
            (
                "_Rolling windows overlap and are descriptive. The fixed "
                "review gate requires 40 chronological closed trades so all "
                "four blocks contain at least 10 trades. Review readiness "
                "does not authorize strategy promotion._"
            ),
        ]
    )
    return lines


def _closed_trade_concentration_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Closed-trade concentration",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No concentration telemetry in this heartbeat._")
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    market = raw.get("market", {})
    strategy = raw.get("lead_strategy", {})
    seven_day = raw.get("seven_day", {})
    if not isinstance(market, dict):
        market = {}
    if not isinstance(strategy, dict):
        strategy = {}
    if not isinstance(seven_day, dict):
        seven_day = {}

    lines.extend(
        [
            (
                "- definition: "
                f"`{raw.get('definition', 'unknown')}`"
            ),
            (
                "- trades / markets / lead strategies / 7d buckets: "
                f"`{raw.get('trade_count', 0)} / "
                f"{raw.get('distinct_markets', 0)} / "
                f"{raw.get('distinct_lead_strategies', 0)} / "
                f"{raw.get('distinct_seven_day_buckets', 0)}`"
            ),
            (
                "- decision-fact attribution misses: "
                f"`{raw.get('decision_fact_misses', 0)}`"
            ),
            (
                "- market positive-PnL share / reference max / met: "
                f"`{market.get('max_positive_net_pnl_share')} / "
                f"{raw.get('market_reference_max_share')} / "
                f"{str(raw.get('market_reference_met')).lower()}`"
            ),
            (
                "- seven-day positive-PnL share / reference max / met: "
                f"`{seven_day.get('max_positive_net_pnl_share')} / "
                f"{raw.get('seven_day_reference_max_share')} / "
                f"{str(raw.get('seven_day_reference_met')).lower()}`"
            ),
            (
                "- market trade-count HHI / positive-PnL HHI: "
                f"`{market.get('trade_count_hhi')} / "
                f"{market.get('positive_net_pnl_hhi')}`"
            ),
            (
                "- largest positive market / strategy / 7d bucket: "
                f"`{market.get('largest_positive_contributor')} / "
                f"{strategy.get('largest_positive_contributor')} / "
                f"{seven_day.get('largest_positive_contributor')}`"
            ),
            "- promotion authority: `false`",
        ]
    )

    def render_rows(
        title: str,
        bucket_label: str,
        section: dict[str, object],
    ) -> None:
        rows = section.get("rows", [])
        if not isinstance(rows, list) or not rows:
            return
        lines.extend(
            [
                "",
                f"#### {title}",
                "",
                (
                    f"| {bucket_label} | Trades | W | L | BE | Net PnL | "
                    "Mean R | Trade share | Positive-PnL share |"
                ),
                (
                    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | "
                    "---: | ---: |"
                ),
            ]
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            lines.append(
                (
                    "| {label} | {trades} | {wins} | {losses} | "
                    "{breakeven} | {net_pnl} | {mean_r} | "
                    "{trade_share} | {positive_share} |"
                ).format(
                    label=row.get("label"),
                    trades=row.get("trades", 0),
                    wins=row.get("wins", 0),
                    losses=row.get("losses", 0),
                    breakeven=row.get("breakeven", 0),
                    net_pnl=row.get("net_pnl", "0"),
                    mean_r=row.get("mean_net_r"),
                    trade_share=row.get("trade_count_share"),
                    positive_share=row.get("positive_net_pnl_share"),
                )
            )

    render_rows("Market concentration", "Market", market)
    render_rows("Lead-strategy concentration", "Strategy", strategy)
    render_rows("UTC seven-day concentration", "7d bucket", seven_day)

    lines.extend(
        [
            "",
            (
                "_Positive-PnL concentration matches the Phase 9 rule: first "
                "net PnL inside each group, then divide the largest positive "
                "group by the sum of all positive groups. The 35% market and "
                "50% seven-day values are reference limits only; this "
                "diagnostic cannot block or promote trades._"
            ),
        ]
    )
    return lines


def _closed_trade_utc_hour_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Closed-trade UTC decision-hour attribution",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No UTC-hour telemetry in this heartbeat._")
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    lines.extend(
        [
            (
                "- definition: "
                f"`{raw.get('definition', 'unknown')}`"
            ),
            (
                "- closed / attributed / misses: "
                f"`{raw.get('closed_trades', 0)} / "
                f"{raw.get('attributed_trades', 0)} / "
                f"{raw.get('attribution_misses', 0)}`"
            ),
            (
                "- active UTC hours / positive / negative hours: "
                f"`{raw.get('active_utc_hours', 0)} / "
                f"{raw.get('positive_net_pnl_hours', 0)} / "
                f"{raw.get('negative_net_pnl_hours', 0)}`"
            ),
            (
                "- trade-count HHI across active UTC hours: "
                f"`{raw.get('trade_count_hhi')}`"
            ),
            "- promotion authority: `false`",
        ]
    )

    rows = raw.get("rows", [])
    if not isinstance(rows, list):
        rows = []
    if rows:
        lines.extend(
            [
                "",
                (
                    "| UTC decision hour | Trades | W | L | BE | Net PnL | "
                    "Mean R | Win rate | PF | Trade share |"
                ),
                (
                    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | "
                    "---: | ---: | ---: |"
                ),
            ]
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            lines.append(
                (
                    "| {label} | {trades} | {wins} | {losses} | "
                    "{breakeven} | {net_pnl} | {mean_r} | {win_rate} | "
                    "{pf} | {share} |"
                ).format(
                    label=row.get("label"),
                    trades=row.get("trades", 0),
                    wins=row.get("wins", 0),
                    losses=row.get("losses", 0),
                    breakeven=row.get("breakeven", 0),
                    net_pnl=row.get("net_pnl", "0"),
                    mean_r=row.get("mean_net_r"),
                    win_rate=row.get("win_rate"),
                    pf=row.get("profit_factor"),
                    share=row.get("trade_count_share"),
                )
            )

    lines.extend(
        [
            "",
            (
                "_UTC hour is derived from the immutable strategy-decision "
                "timestamp, not the fill or close timestamp. This diagnostic "
                "does not suppress, delay, or reprioritize trades._"
            ),
        ]
    )
    return lines


def _closed_trade_friction_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### Closed-trade friction attribution",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append("_No friction telemetry in this heartbeat._")
        return lines

    enabled = bool(raw.get("enabled"))
    lines.append(f"- enabled: `{str(enabled).lower()}`")
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        return lines

    overall = raw.get("overall", {})
    if not isinstance(overall, dict):
        overall = {}
    lines.extend(
        [
            (
                "- definition: "
                f"`{raw.get('definition', 'unknown')}`"
            ),
            (
                "- decision-fact attribution misses: "
                f"`{raw.get('decision_fact_attribution_misses', 0)}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "| Ref-price gross | Signed slippage | Actual gross | Fees | "
                "Funding | Net PnL | Net cost drag |"
            ),
            (
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
            ),
            (
                "| {reference} | {slippage} | {gross} | {fees} | "
                "{funding} | {net} | {drag} |"
            ).format(
                reference=overall.get("reference_gross_pnl", "0"),
                slippage=overall.get("signed_slippage_amount", "0"),
                gross=overall.get("actual_gross_realized_pnl", "0"),
                fees=overall.get("fees", "0"),
                funding=overall.get("funding_cash_pnl", "0"),
                net=overall.get("net_pnl", "0"),
                drag=overall.get("net_cost_drag", "0"),
            ),
            (
                "- adverse / favorable slippage amounts: "
                f"`{overall.get('adverse_slippage_amount', '0')} / "
                f"{overall.get('favorable_slippage_amount', '0')}`"
            ),
            (
                "- positive trades before slippage / after slippage / net: "
                f"`{overall.get('reference_gross_positive_trades', 0)} / "
                f"{overall.get('actual_gross_positive_trades', 0)} / "
                f"{overall.get('net_positive_trades', 0)}`"
            ),
            (
                "- friction-flipped / fee+funding-flipped / rescued: "
                f"`{overall.get('friction_flipped_trades', 0)} / "
                f"{overall.get('fee_funding_flipped_trades', 0)} / "
                f"{overall.get('friction_rescued_trades', 0)}`"
            ),
            (
                "- mean R: reference gross / slippage drag / fee drag / "
                "funding / total cost drag / net: "
                f"`{overall.get('mean_reference_gross_r')} / "
                f"{overall.get('mean_slippage_drag_r')} / "
                f"{overall.get('mean_fee_drag_r')} / "
                f"{overall.get('mean_funding_r')} / "
                f"{overall.get('mean_net_cost_drag_r')} / "
                f"{overall.get('mean_net_r')}`"
            ),
        ]
    )

    for field, label in (
        ("by_side", "Side"),
        ("by_lead_strategy", "Lead strategy"),
    ):
        groups = raw.get(field, {})
        if not isinstance(groups, dict) or not groups:
            continue
        lines.extend(
            [
                "",
                f"#### {label} friction",
                "",
                (
                    "| Bucket | N | Ref gross | Slippage | Fees | Funding | "
                    "Net | Flipped | Mean ref R | Mean drag R | Mean net R |"
                ),
                (
                    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | "
                    "---: | ---: | ---: | ---: |"
                ),
            ]
        )
        for bucket, value in sorted(groups.items()):
            if not isinstance(value, dict):
                continue
            lines.append(
                (
                    "| {bucket} | {trades} | {reference} | {slippage} | "
                    "{fees} | {funding} | {net} | {flipped} | "
                    "{mean_ref} | {mean_drag} | {mean_net} |"
                ).format(
                    bucket=bucket,
                    trades=value.get("trades", 0),
                    reference=value.get("reference_gross_pnl", "0"),
                    slippage=value.get("signed_slippage_amount", "0"),
                    fees=value.get("fees", "0"),
                    funding=value.get("funding_cash_pnl", "0"),
                    net=value.get("net_pnl", "0"),
                    flipped=value.get("friction_flipped_trades", 0),
                    mean_ref=value.get("mean_reference_gross_r"),
                    mean_drag=value.get("mean_net_cost_drag_r"),
                    mean_net=value.get("mean_net_r"),
                )
            )

    lines.extend(
        [
            "",
            (
                "_Waterfall identity: reference-price gross − signed slippage "
                "= actual gross; actual gross − fees + funding = net PnL. "
                "Positive signed slippage is adverse; negative is favorable._"
            ),
        ]
    )
    return lines


def _research_readiness_board_lines(
    payload: Mapping[str, Any],
) -> list[str]:
    def mapping(key: str) -> dict[str, object]:
        value = payload.get(key, {})
        return value if isinstance(value, dict) else {}

    def readiness(raw: dict[str, object]) -> dict[str, object]:
        value = raw.get("readiness", {})
        return value if isinstance(value, dict) else {}

    def status(
        raw: dict[str, object],
        *,
        ready: bool,
    ) -> str:
        if raw.get("error"):
            return "error"
        if raw.get("enabled") is False:
            return "disabled"
        return "review-ready" if ready else "collecting"

    profit = mapping("profit_lock_counterfactual")
    profit_ready = bool(
        readiness(profit).get("all_rules_ready_for_review")
    )

    execution = mapping("profit_lock_execution_shadow")
    execution_gate = readiness(execution)
    execution_ready = bool(
        execution_gate.get("all_rules_ready_for_review")
    )
    execution_integrity = (
        f"mismatch={execution.get('lineage_mismatch_closed_trades', 0)}, "
        f"orphan={execution.get('orphaned_restored_positions', 0)}"
    )

    delayed = mapping("delayed_entry_execution_shadow")
    delayed_gate = readiness(delayed)
    delayed_ready = bool(
        delayed_gate.get("ready_for_review")
    )
    delayed_same_exit = mapping("delayed_entry_same_exit")
    delayed_same_exit_gate = readiness(delayed_same_exit)
    delayed_same_exit_ready = bool(
        delayed_same_exit_gate.get("ready_for_review")
    )
    delayed_fill_weighted = mapping("delayed_entry_fill_weighted")
    delayed_fill_weighted_gate = readiness(delayed_fill_weighted)
    delayed_fill_weighted_ready = bool(
        delayed_fill_weighted_gate.get("ready_for_review")
    )
    delayed_fill_weighted_overall = delayed_fill_weighted.get(
        "overall",
        {},
    )
    if not isinstance(delayed_fill_weighted_overall, dict):
        delayed_fill_weighted_overall = {}
    delayed_portfolio = mapping(
        "delayed_entry_fixed_schedule_portfolio"
    )
    delayed_portfolio_gate = readiness(delayed_portfolio)
    delayed_portfolio_ready = bool(
        delayed_portfolio_gate.get("ready_for_review")
    )
    delayed_portfolio_actual = delayed_portfolio.get("actual", {})
    if not isinstance(delayed_portfolio_actual, dict):
        delayed_portfolio_actual = {}
    delayed_mtm_portfolio = mapping("delayed_entry_mtm_portfolio")
    delayed_mtm_portfolio_gate = readiness(delayed_mtm_portfolio)
    delayed_mtm_portfolio_ready = bool(
        delayed_mtm_portfolio_gate.get("ready_for_review")
    )
    delayed_mtm_actual = delayed_mtm_portfolio.get("actual", {})
    if not isinstance(delayed_mtm_actual, dict):
        delayed_mtm_actual = {}
    delayed_capacity = mapping("delayed_entry_portfolio_capacity")
    delayed_capacity_gate = readiness(delayed_capacity)
    delayed_capacity_ready = bool(
        delayed_capacity_gate.get("ready_for_review")
    )
    delayed_capacity_candidate = delayed_capacity.get("candidate", {})
    if not isinstance(delayed_capacity_candidate, dict):
        delayed_capacity_candidate = {}
    delayed_capacity_actual_admission = delayed_capacity.get(
        "actual_admission",
        {},
    )
    delayed_capacity_candidate_admission = delayed_capacity.get(
        "candidate_admission",
        {},
    )
    if not isinstance(delayed_capacity_actual_admission, dict):
        delayed_capacity_actual_admission = {}
    if not isinstance(delayed_capacity_candidate_admission, dict):
        delayed_capacity_candidate_admission = {}
    delayed_120 = mapping("delayed_entry_120s_execution_shadow")
    delayed_120_gate = readiness(delayed_120)
    delayed_120_ready = bool(
        delayed_120_gate.get("ready_for_review")
    )
    delayed_pair = mapping("delayed_entry_pair")
    delayed_pair_gate = readiness(delayed_pair)
    delayed_pair_ready = bool(
        delayed_pair_gate.get("ready_for_review")
    )
    delayed_pair_fill_weighted = mapping(
        "delayed_entry_pair_fill_weighted"
    )
    delayed_pair_fill_weighted_gate = readiness(
        delayed_pair_fill_weighted
    )
    delayed_pair_fill_weighted_ready = bool(
        delayed_pair_fill_weighted_gate.get("ready_for_review")
    )
    adaptive_delay = mapping("adaptive_delay_selector")
    adaptive_delay_gate = readiness(adaptive_delay)
    adaptive_delay_ready = bool(
        adaptive_delay_gate.get("ready_for_review")
    )
    fill_aware_delay = mapping("fill_aware_delay_selector")
    fill_aware_delay_gate = readiness(fill_aware_delay)
    fill_aware_delay_ready = bool(
        fill_aware_delay_gate.get("ready_for_review")
    )
    delayed_integrity = (
        f"mismatch={delayed.get('lineage_mismatch_closed_trades', 0)}, "
        f"orphan={delayed.get('orphaned_restored_positions', 0)}"
    )

    entry_filter = mapping("prospective_entry_filter")
    entry_filter_gate = readiness(entry_filter)
    entry_filter_ready = bool(
        entry_filter_gate.get("ready_for_review")
    )

    delayed_price_confirm = mapping(
        "prospective_delayed_price_confirmation"
    )
    delayed_price_confirm_gate = readiness(
        delayed_price_confirm
    )
    delayed_price_confirm_ready = bool(
        delayed_price_confirm_gate.get("ready_for_review")
    )

    rank_filter = mapping("prospective_top10_rank_filter")
    rank_filter_gate = readiness(rank_filter)
    rank_filter_ready = bool(
        rank_filter_gate.get("ready_for_review")
    )

    combined_filter = mapping(
        "prospective_combined_entry_filter"
    )
    combined_filter_gate = readiness(combined_filter)
    combined_filter_ready = bool(
        combined_filter_gate.get("ready_for_review")
    )
    fill_liquidity = mapping("opening_fill_liquidity")
    fill_liquidity_ready = bool(
        fill_liquidity.get("ready_for_review")
    )

    markout = mapping("entry_markout")
    markout_gate = readiness(markout)
    markout_ready = bool(
        markout_gate.get("all_horizons_ready_for_review")
    )
    markout_horizons = markout.get("by_horizon_ms", {})
    if not isinstance(markout_horizons, dict):
        markout_horizons = {}
    markout_counts: list[str] = []
    for key in ("60000", "300000", "900000"):
        item = markout_horizons.get(key, {})
        if not isinstance(item, dict):
            item = {}
        markout_counts.append(str(item.get("observations", 0)))

    mid = mapping("entry_mid_markout_shadow")
    mid_gate = readiness(mid)
    mid_ready = bool(
        mid_gate.get("all_horizons_ready_for_review")
    )
    mid_horizons = mid.get("by_horizon_ms", {})
    if not isinstance(mid_horizons, dict):
        mid_horizons = {}
    mid_counts: list[str] = []
    for key in ("60000", "300000", "900000"):
        item = mid_horizons.get(key, {})
        if not isinstance(item, dict):
            item = {}
        mid_counts.append(str(item.get("fresh", 0)))
    mid_integrity = (
        f"unmatched={mid.get('unmatched_closed_trades', 0)}, "
        f"mismatch={mid.get('lineage_mismatch_closed_trades', 0)}, "
        f"orphan={mid.get('orphaned_restored_positions', 0)}"
    )

    decision_age = mapping("entry_decision_age")
    decision_age_ready = bool(
        decision_age.get("ready_for_review")
    )

    excursion = mapping("excursion_timing")
    excursion_gate = mapping("excursion_timing").get(
        "evidence_gate",
        {},
    )
    if not isinstance(excursion_gate, dict):
        excursion_gate = {}
    excursion_ready = bool(
        excursion_gate.get("ready_for_review")
    )

    trade_stability = mapping("closed_trade_stability")
    trade_stability_gate = readiness(trade_stability)
    trade_stability_ready = bool(
        trade_stability_gate.get("ready_for_review")
    )
    trade_stability_state = trade_stability.get("stability", {})
    if not isinstance(trade_stability_state, dict):
        trade_stability_state = {}
    trade_stability_all_pnl_positive = str(
        bool(
            trade_stability_state.get(
                "all_full_blocks_positive_net_pnl"
            )
        )
    ).lower()

    rows = (
        (
            "fixed profit-lock",
            status(profit, ready=profit_ready),
            (
                f"paths={profit.get('evaluated_trade_count', 0)}/"
                f"{profit.get('path_record_count', 0)}"
            ),
            f"skipped={profit.get('skipped_incomplete_paths', 0)}",
        ),
        (
            "IOC profit-lock",
            status(execution, ready=execution_ready),
            f"closed={execution.get('closed_outcome_count', 0)}",
            execution_integrity,
        ),
        (
            "60s delayed entry",
            status(delayed, ready=delayed_ready),
            (
                f"closed={delayed.get('closed_eligible_trades', 0)}, "
                f"full={delayed.get('full_delayed_fills', 0)}, "
                f"better={delayed.get('better_price_full_fills', 0)}, "
                f"worse={delayed.get('worse_price_full_fills', 0)}"
            ),
            delayed_integrity,
        ),
        (
            "120s delayed entry",
            status(delayed_120, ready=delayed_120_ready),
            (
                f"closed={delayed_120.get('closed_eligible_trades', 0)}, "
                f"full={delayed_120.get('full_delayed_fills', 0)}, "
                f"better={delayed_120.get('better_price_full_fills', 0)}, "
                f"worse={delayed_120.get('worse_price_full_fills', 0)}"
            ),
            (
                f"mismatch={delayed_120.get('lineage_mismatch_closed_trades', 0)}, "
                f"orphan={delayed_120.get('orphaned_restored_positions', 0)}"
            ),
        ),
        (
            "60s vs 120s paired",
            status(delayed_pair, ready=delayed_pair_ready),
            (
                f"closed={delayed_pair.get('prospective_closed_trades', 0)}, "
                f"paired={delayed_pair.get('paired_full_fills', 0)}"
            ),
            (
                f"missing60={delayed_pair.get('missing_base_outcome', 0)}, "
                f"missing120={delayed_pair.get('missing_challenger_outcome', 0)}, "
                f"mismatch={delayed_pair.get('lineage_mismatches', 0)}"
            ),
        ),
        (
            "60s vs 120s fill-weighted",
            status(
                delayed_pair_fill_weighted,
                ready=delayed_pair_fill_weighted_ready,
            ),
            (
                f"closed={delayed_pair_fill_weighted.get('prospective_closed_trades', 0)}, "
                f"paired={delayed_pair_fill_weighted.get('paired_evaluable_attempts', 0)}"
            ),
            (
                f"missing60={delayed_pair_fill_weighted.get('missing_base_outcome', 0)}, "
                f"missing120={delayed_pair_fill_weighted.get('missing_challenger_outcome', 0)}, "
                f"mismatch={delayed_pair_fill_weighted.get('lineage_mismatches', 0)}"
            ),
        ),
        (
            "adaptive 60s/120s delay",
            status(adaptive_delay, ready=adaptive_delay_ready),
            (
                f"closed={adaptive_delay.get('prospective_closed_trades', 0)}, "
                f"causal={adaptive_delay.get('causal_evaluable_trades', 0)}"
            ),
            (
                f"midmiss={adaptive_delay.get('missing_mid_outcome', 0)}, "
                f"late={adaptive_delay.get('late_mid_signal', 0)}, "
                f"mismatch={adaptive_delay.get('lineage_mismatches', 0)}"
            ),
        ),
        (
            "fill-aware 60s/120s delay",
            status(fill_aware_delay, ready=fill_aware_delay_ready),
            (
                f"closed={fill_aware_delay.get('prospective_closed_trades', 0)}, "
                f"causal={fill_aware_delay.get('causal_evaluable_trades', 0)}"
            ),
            (
                f"non60={fill_aware_delay.get('non_evaluable_base', 0)}, "
                f"non120={fill_aware_delay.get('non_evaluable_challenger', 0)}, "
                f"mismatch={fill_aware_delay.get('lineage_mismatches', 0)}"
            ),
        ),
        (
            "60s delayed same-exit",
            status(
                delayed_same_exit,
                ready=delayed_same_exit_ready,
            ),
            (
                f"closed={delayed_same_exit.get('closed_shadow_outcomes', 0)}, "
                f"full={delayed_same_exit.get('evaluated_full_delayed_fills', 0)}"
            ),
            (
                f"missing={delayed_same_exit.get('missing_journal_trades', 0)}, "
                f"mismatch={delayed_same_exit.get('lineage_mismatches', 0)}"
            ),
        ),
        (
            "60s delayed fill-weighted",
            status(
                delayed_fill_weighted,
                ready=delayed_fill_weighted_ready,
            ),
            (
                f"closed={delayed_fill_weighted.get('closed_shadow_outcomes', 0)}, "
                f"eval={delayed_fill_weighted.get('evaluated_delayed_attempts', 0)}, "
                f"fill={delayed_fill_weighted_overall.get('mean_fill_fraction')}"
            ),
            (
                f"missing={delayed_fill_weighted.get('missing_journal_trades', 0)}, "
                f"mismatch={delayed_fill_weighted.get('lineage_mismatches', 0)}"
            ),
        ),
        (
            "60s delayed fixed-schedule portfolio",
            status(
                delayed_portfolio,
                ready=delayed_portfolio_ready,
            ),
            (
                f"closed={delayed_portfolio.get('closed_shadow_outcomes', 0)}, "
                f"eval={delayed_portfolio.get('evaluated_delayed_attempts', 0)}, "
                f"overlap={delayed_portfolio_actual.get('overlap_openings', 0)}"
            ),
            (
                f"unresolved={delayed_portfolio.get('unresolved_outcomes', 0)}, "
                f"missing={delayed_portfolio.get('missing_journal_trades', 0)}/"
                f"{delayed_portfolio.get('missing_opening_plans', 0)}, "
                f"mismatch={delayed_portfolio.get('lineage_mismatches', 0)}, "
                f"risk={delayed_portfolio.get('candidate_risk_ceiling_exceeded', 0)}"
            ),
        ),
        (
            "60s delayed MTM portfolio",
            status(
                delayed_mtm_portfolio,
                ready=delayed_mtm_portfolio_ready,
            ),
            (
                f"closed={delayed_mtm_portfolio.get('closed_shadow_outcomes', 0)}, "
                f"paths={delayed_mtm_portfolio.get('evaluated_complete_path_trades', 0)}, "
                f"overlap={delayed_mtm_actual.get('overlap_openings', 0)}"
            ),
            (
                f"unresolved={delayed_mtm_portfolio.get('unresolved_outcomes', 0)}, "
                f"missing={delayed_mtm_portfolio.get('missing_journal_trades', 0)}/"
                f"{delayed_mtm_portfolio.get('missing_exact_paths', 0)}, "
                f"incomplete={delayed_mtm_portfolio.get('incomplete_exact_paths', 0)}, "
                f"mismatch={delayed_mtm_portfolio.get('lineage_mismatches', 0)}"
            ),
        ),
        (
            "60s delayed capacity overlay",
            status(
                delayed_capacity,
                ready=delayed_capacity_ready,
            ),
            (
                f"closed={delayed_capacity.get('closed_shadow_outcomes', 0)}, "
                f"fills={delayed_capacity.get('candidate_filled_positions', 0)}, "
                f"overlap={delayed_capacity_candidate.get('overlap_openings', 0)}, "
                f"admit/reject="
                f"{delayed_capacity_candidate_admission.get('admitted_openings', 0)}/"
                f"{delayed_capacity_candidate_admission.get('rejected_openings', 0)}"
            ),
            (
                f"viol={delayed_capacity_candidate.get('capacity_violations', 0)}, "
                f"marginrej="
                f"{delayed_capacity_candidate_admission.get('margin_capacity_rejections', 0)}, "
                f"actualrej="
                f"{delayed_capacity_actual_admission.get('rejected_openings', 0)}, "
                f"unresolved={delayed_capacity.get('unresolved_outcomes', 0)}, "
                f"missing={delayed_capacity.get('missing_journal_trades', 0)}/"
                f"{delayed_capacity.get('missing_opening_plans', 0)}/"
                f"{delayed_capacity.get('missing_venue_max_leverage', 0)}/"
                f"{delayed_capacity.get('missing_exact_paths', 0)}, "
                f"incomplete={delayed_capacity.get('incomplete_exact_paths', 0)}, "
                f"mismatch={delayed_capacity.get('lineage_mismatches', 0)}"
            ),
        ),
        (
            "LONG+trend filter",
            status(entry_filter, ready=entry_filter_ready),
            (
                f"closed={entry_filter.get('prospective_closed_trades', 0)}, "
                f"blocked={entry_filter.get('blocked_trades', 0)}, "
                f"allowed={entry_filter.get('allowed_trades', 0)}"
            ),
            f"misses={entry_filter.get('attribution_misses', 0)}",
        ),
        (
            "60s price confirmation",
            status(
                delayed_price_confirm,
                ready=delayed_price_confirm_ready,
            ),
            (
                f"eval={delayed_price_confirm.get('evaluated_trades', 0)}, "
                f"confirmed={delayed_price_confirm.get('confirmed_trades', 0)}, "
                f"skipped={delayed_price_confirm.get('skipped_trades', 0)}"
            ),
            (
                f"missing={delayed_price_confirm.get('missing_outcomes', 0)}, "
                f"plan={delayed_price_confirm.get('missing_opening_plans', 0)}, "
                f"mismatch={delayed_price_confirm.get('lineage_mismatches', 0)}"
            ),
        ),
        (
            "top-10 rank filter",
            status(rank_filter, ready=rank_filter_ready),
            (
                f"closed={rank_filter.get('prospective_closed_trades', 0)}, "
                f"blocked={rank_filter.get('blocked_trades', 0)}, "
                f"allowed={rank_filter.get('allowed_trades', 0)}"
            ),
            (
                f"missing={rank_filter.get('missing_rank_evidence', 0)}, "
                f"stale={rank_filter.get('stale_rank_evidence', 0)}"
            ),
        ),
        (
            "top-10 + no LONG-trend",
            status(
                combined_filter,
                ready=combined_filter_ready,
            ),
            (
                f"closed={combined_filter.get('prospective_closed_trades', 0)}, "
                f"blocked={combined_filter.get('blocked_trades', 0)}, "
                f"allowed={combined_filter.get('allowed_trades', 0)}"
            ),
            (
                f"fact={combined_filter.get('decision_attribution_misses', 0)}, "
                f"rank={combined_filter.get('missing_rank_evidence', 0)}, "
                f"stale={combined_filter.get('stale_rank_evidence', 0)}"
            ),
        ),
        (
            "opening fill liquidity",
            status(
                fill_liquidity,
                ready=fill_liquidity_ready,
            ),
            (
                f"closed={fill_liquidity.get('attributed_closed_trades', 0)}, "
                f"need={fill_liquidity.get('still_needed_closed_trades', 0)}"
            ),
            (
                f"historical_missing="
                f"{fill_liquidity.get('closed_trades_without_fill_liquidity_evidence', 0)}, "
                f"capture={fill_liquidity.get('capture_error')}"
            ),
        ),
        (
            "exact-path entry markout",
            status(markout, ready=markout_ready),
            "1m/5m/15m=" + "/".join(markout_counts),
            (
                f"decision_miss={markout.get('missing_decision_attribution', 0)}, "
                f"rank_miss={markout.get('missing_rank_attribution', 0)}"
            ),
        ),
        (
            "allMids entry markout",
            status(mid, ready=mid_ready),
            "fresh 1m/5m/15m=" + "/".join(mid_counts),
            mid_integrity,
        ),
        (
            "excursion timing",
            status(excursion, ready=excursion_ready),
            (
                f"paths={excursion.get('complete_paths_evaluated', 0)}, "
                f"need={excursion_gate.get('missing_complete_paths', 0)}"
            ),
            (
                f"decision_miss="
                f"{excursion.get('missing_decision_attribution', 0)}, "
                f"excursion_miss="
                f"{excursion.get('missing_excursion_metric', 0)}"
            ),
        ),
        (
            "decision age at fill",
            status(decision_age, ready=decision_age_ready),
            (
                f"attributed={decision_age.get('attributed_closed_trades', 0)}, "
                f"need={decision_age.get('still_needed_for_review', 0)}"
            ),
            f"misses={decision_age.get('attribution_misses', 0)}",
        ),
        (
            "closed-trade stability",
            status(
                trade_stability,
                ready=trade_stability_ready,
            ),
            (
                f"closed={trade_stability.get('closed_trades', 0)}, "
                f"need={trade_stability_gate.get('missing_closed_trades', 0)}"
            ),
            (
                f"full_blocks={trade_stability_state.get('full_blocks', 0)}, "
                f"all_pnl_positive={trade_stability_all_pnl_positive}"
            ),
        ),
    )

    lines = [
        "",
        "### Research readiness board",
        "",
        (
            "- authority: `OBSERVABILITY ONLY` · review readiness never "
            "changes paper execution"
        ),
        "",
        "| Study | Status | Evidence | Integrity |",
        "| --- | --- | --- | --- |",
    ]
    for name, study_status, evidence, integrity in rows:
        lines.append(
            f"| {name} | {study_status} | {evidence} | {integrity} |"
        )
    ready_count = sum(
        1 for _name, study_status, _evidence, _integrity in rows
        if study_status == "review-ready"
    )
    lines.extend(
        [
            "",
            f"- review-ready studies: `{ready_count} / {len(rows)}`",
            (
                "_Collecting means the frozen evidence gate is not yet met. "
                "Review-ready still grants no promotion or execution authority._"
            ),
        ]
    )
    return lines


def _delayed_entry_stop_l2_lines(
    raw: object,
) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry exact stop L2 replay",
        "",
        "- authority: `RESEARCH ONLY / NO EXECUTION`",
    ]
    if not isinstance(raw, dict):
        lines.append(
            "_No exact delayed stop-L2 telemetry in this heartbeat._"
        )
        return lines

    lines.append(
        f"- enabled: `{str(bool(raw.get('enabled'))).lower()}`"
    )
    error = raw.get("error")
    if error:
        lines.append(f"- research error: `{error}`")
        capture_error = raw.get("capture_error")
        if capture_error:
            lines.append(
                f"- stop-book capture error: `{capture_error}`"
            )
        return lines

    overall = raw.get("overall", {})
    readiness = raw.get("readiness", {})
    if not isinstance(overall, dict):
        overall = {}
    if not isinstance(readiness, dict):
        readiness = {}
    source_counts = raw.get("source_counts", {})
    non_evaluable_sources = raw.get(
        "non_evaluable_source_counts",
        raw.get("unresolved_source_counts", {}),
    )
    if not isinstance(source_counts, dict):
        source_counts = {}
    if not isinstance(non_evaluable_sources, dict):
        non_evaluable_sources = {}

    def source_summary(value: dict[object, object]) -> str:
        if not value:
            return "none"
        return ", ".join(
            f"{key}={value[key]}"
            for key in sorted(value, key=str)
        )

    lines.extend(
        [
            f"- scope: `{raw.get('claim_scope', 'unknown')}`",
            (
                "- capture start / legacy excluded: "
                f"`{raw.get('capture_started_at_ms')} / "
                f"{raw.get('pre_capture_legacy_outcomes', 0)}`"
            ),
            (
                "- delayed-entry source counts: "
                f"`{source_summary(source_counts)}`"
            ),
            (
                "- post-capture non-evaluable entries / sources: "
                f"`{raw.get('non_evaluable_entry_outcomes', raw.get('unresolved_outcomes', 0))} / "
                f"{source_summary(non_evaluable_sources)}`"
            ),
            (
                "- upstream integrity misses journal / path / gaps / funding / "
                "lineage / timing / stop-book: "
                f"`{raw.get('missing_journal_trades', 0)} / "
                f"{raw.get('missing_exact_paths', 0)} / "
                f"{raw.get('incomplete_or_gapped_paths', 0)} / "
                f"{raw.get('missing_funding_events', 0)} / "
                f"{raw.get('lineage_mismatches', 0)} / "
                f"{raw.get('invalid_candidate_timing', 0)} / "
                f"{raw.get('stop_book_capture_errors', 0)}`"
            ),
            (
                "- evaluated / mark crossings / captured stop plans: "
                f"`{overall.get('evaluated_filled_candidates', 0)} / "
                f"{overall.get('mark_stop_crossings', 0)} / "
                f"{overall.get('captured_stop_plans', 0)}`"
            ),
            (
                "- full / partial / no-fill / quantized remainder exits: "
                f"`{overall.get('full_stop_exits', 0)} / "
                f"{overall.get('partial_stop_exits', 0)} / "
                f"{overall.get('no_fill_stop_exits', 0)} / "
                f"{overall.get('full_ioc_position_remainders', 0)}`"
            ),
            (
                "- rejections / pending / capture-unreliable: "
                f"`{overall.get('planning_or_execution_rejections', 0)} / "
                f"{overall.get('pending_stop_evidence', 0)} / "
                f"{overall.get('stop_capture_unreliable', 0)}`"
            ),
            (
                "- resolved / unresolved stop actions: "
                f"`{overall.get('resolved_candidates', 0)} / "
                f"{overall.get('unresolved_stop_actions', 0)}`"
            ),
            (
                "- resolved actual / candidate / delta PnL: "
                f"`{overall.get('resolved_actual_net_pnl', '0')} / "
                f"{overall.get('resolved_candidate_net_pnl', '0')} / "
                f"{overall.get('resolved_delta_vs_actual', '0')}`"
            ),
            (
                "- full-stop same-exit / exact PnL / removed edge: "
                f"`{overall.get('same_exit_pnl_on_full_stop_exits', '0')} / "
                f"{overall.get('exact_pnl_on_full_stop_exits', '0')} / "
                f"{overall.get('same_exit_minus_exact_on_full_stop_exits', '0')}`"
            ),
            (
                "- transient crossings kept same-exit / late funding excluded: "
                f"`{overall.get('transient_mark_crossings_without_stop_plan', 0)} / "
                f"{overall.get('late_funding_boundaries_excluded', 0)}`"
            ),
            (
                "- integrity clean / complete cohort / ready for descriptive review: "
                f"`{str(bool(readiness.get('integrity_clean'))).lower()} / "
                f"{str(bool(readiness.get('complete_counterfactual_cohort'))).lower()} / "
                f"{str(bool(readiness.get('ready_for_descriptive_review'))).lower()}`"
            ),
            (
                "- full-stop evidence gate / still needed: "
                f"`{readiness.get('min_full_stop_exits', 0)} / "
                f"{readiness.get('missing_full_stop_exits', 0)}`"
            ),
            "- promotion authority: `false`",
            "",
            (
                "_Exact first-IOC stop economics use captured visible L2. "
                "Partial/no-fill/rejected exits and quantized position "
                "remainders stay unresolved; no synthetic remainder exit "
                "is invented._"
            ),
        ]
    )
    return lines


def render_live_status(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    head_sha: str,
    predecessor_run_id: str,
) -> str:
    timestamp_ms = int(payload["timestamp_ms"])
    timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    positions_raw = payload.get("positions", [])
    if not isinstance(positions_raw, list):
        raise ValueError("positions must be a list")
    decisions = payload.get("session_decisions", {})
    if not isinstance(decisions, dict):
        decisions = {}
    risk = payload.get("session_risk", {})
    if not isinstance(risk, dict):
        risk = {}
    performance = payload.get("closed_trade_performance", {})
    if not isinstance(performance, dict):
        performance = {}
    trade_path_evidence = payload.get("trade_path_evidence", {})
    if not isinstance(trade_path_evidence, dict):
        trade_path_evidence = {}

    lines = [
        "## Continuous paper runtime live status",
        "",
        f"**Updated:** `{timestamp.isoformat()}`",
        f"**Worker run:** `{run_id}`",
        f"**Worker head SHA:** `{head_sha}`",
        (
            "**Predecessor run:** "
            + (
                f"`{predecessor_run_id}`"
                if predecessor_run_id
                else "_fresh/watchdog restore_"
            )
        ),
        "**Execution:** `PAPER ONLY` · **Live orders:** `false`",
        "",
        "### Account",
        "",
        f"- starting cash: `{payload.get('starting_cash', 'unknown')}`",
        f"- equity: `{payload['equity']}`",
        f"- total account PnL: `{payload.get('total_account_pnl', 'unknown')}`",
        (
            "- total return fraction: "
            f"`{payload.get('total_return_fraction', 'unknown')}`"
        ),
        f"- cash: `{payload['cash']}`",
        (
            "- UTC day start / equity: "
            f"`{payload.get('day_start_ms', 'unknown')} / "
            f"{payload.get('day_start_equity', 'unknown')}`"
        ),
        (
            "- daily realized PnL: "
            f"`{payload.get('daily_realized_pnl', 'unknown')}`"
        ),
        f"- unrealized PnL: `{payload['unrealized_pnl']}`",
        f"- realized gross PnL: `{payload['realized_gross_pnl']}`",
        f"- cumulative fees: `{payload['cumulative_fees']}`",
        f"- cumulative funding: `{payload['cumulative_funding']}`",
        f"- cumulative closed trades: `{payload['closed_trades']}`",
        (
            "- closed trades this worker: "
            f"`{payload.get('session_closed_trades', 0)}`"
        ),
        f"- open planned risk: `{payload.get('open_planned_risk', '0')}`",
        (
            "- open planned risk / equity: "
            f"`{payload.get('open_planned_risk_fraction_of_equity', '0')}`"
        ),
        (
            "- stop-trigger gross PnL at current stops: "
            f"`{payload.get('open_stop_trigger_gross_pnl', '0')}`"
        ),
        (
            "- stop-trigger gross R / planned risk: "
            f"`{payload.get('open_stop_trigger_gross_r')}`"
        ),
        (
            "- positions with profit-protecting stop: "
            f"`{payload.get('open_positions_with_profit_protected_stop', 0)} / "
            f"{payload.get('open_position_count', len(positions_raw))}`"
        ),
        f"- gross open notional: `{payload.get('gross_open_notional', '0')}`",
        (
            "- gross open notional / equity: "
            f"`{payload.get('gross_open_notional_fraction_of_equity', '0')}`"
        ),
        f"- available margin: `{payload.get('available_margin', '0')}`",
        (
            "- execution healthy: "
            f"`{str(payload['execution_healthy']).lower()}`"
        ),
    ]
    lines.extend(
        _drawdown_lines(
            payload.get("drawdown")
        )
    )
    lines.extend(
        _account_lifecycle_bridge_lines(
            payload.get("account_lifecycle_economics")
        )
    )
    lines.extend(_research_readiness_board_lines(payload))
    lines.extend(
        [
            "",
            "### Trade-path evidence",
            "",
            (
                "- authority: `RESEARCH ONLY / NO EXECUTION` · "
                "durable across workers: "
                f"`{str(bool(trade_path_evidence.get('durable_across_workers'))).lower()}`"
            ),
            (
                "- completed exact trade paths: "
                f"`{trade_path_evidence.get('closed_path_count', 0)}`"
            ),
            (
                "- staged open trade paths: "
                f"`{trade_path_evidence.get('staged_open_path_count', 0)}`"
            ),
            (
                "- capture error: "
                f"`{trade_path_evidence.get('capture_error')}`"
            ),
        ]
    )
    lines.extend(
        _profit_lock_lines(payload.get("profit_lock_counterfactual"))
    )
    lines.extend(
        _profit_lock_execution_shadow_lines(
            payload.get("profit_lock_execution_shadow")
        )
    )
    lines.extend(
        _delayed_entry_execution_shadow_lines(
            payload.get("delayed_entry_execution_shadow")
        )
    )
    lines.extend(
        _delayed_entry_execution_shadow_lines(
            payload.get("delayed_entry_120s_execution_shadow"),
            title="120s delayed-entry execution shadow",
        )
    )
    lines.extend(
        _delayed_entry_pair_lines(
            payload.get("delayed_entry_pair")
        )
    )
    lines.extend(
        _delayed_entry_pair_fill_weighted_lines(
            payload.get("delayed_entry_pair_fill_weighted")
        )
    )
    lines.extend(
        _adaptive_delay_selector_lines(
            payload.get("adaptive_delay_selector")
        )
    )
    lines.extend(
        _fill_aware_delay_selector_lines(
            payload.get("fill_aware_delay_selector")
        )
    )
    lines.extend(
        _delay_selector_comparison_lines(
            payload.get("delay_selector_comparison")
        )
    )
    lines.extend(
        _delayed_entry_same_exit_lines(
            payload.get("delayed_entry_same_exit")
        )
    )
    lines.extend(
        _delayed_entry_fill_capacity_lines(
            payload.get("delayed_entry_fill_capacity")
        )
    )
    lines.extend(
        _delayed_entry_fill_weighted_lines(
            payload.get("delayed_entry_fill_weighted")
        )
    )
    lines.extend(
        _delayed_entry_fill_weighted_funding_lines(
            payload.get("delayed_entry_fill_weighted_funding")
        )
    )
    lines.extend(
        _delayed_entry_fixed_schedule_portfolio_lines(
            payload.get("delayed_entry_fixed_schedule_portfolio")
        )
    )
    lines.extend(
        _delayed_entry_mtm_portfolio_lines(
            payload.get("delayed_entry_mtm_portfolio")
        )
    )
    lines.extend(
        _delayed_entry_stop_survivability_lines(
            payload.get("delayed_entry_stop_survivability"),
            payload.get("delayed_entry_same_exit_stop_validity"),
            payload.get("delayed_entry_stop_exit_proxy"),
        )
    )
    lines.extend(
        _delayed_entry_stop_l2_lines(
            payload.get("delayed_entry_stop_l2_replay")
        )
    )
    lines.extend(
        _delayed_entry_portfolio_capacity_lines(
            payload.get("delayed_entry_portfolio_capacity")
        )
    )
    lines.extend(
        _delayed_entry_contribution_decomposition_lines(
            payload.get("delayed_entry_contribution_decomposition"),
            payload.get(
                "delayed_entry_contribution_decomposition_funding"
            ),
        )
    )
    lines.extend(
        _delayed_entry_risk_geometry_lines(
            payload.get("delayed_entry_risk_geometry")
        )
    )
    lines.extend(
        _prospective_entry_filter_lines(
            payload.get("prospective_entry_filter")
        )
    )
    lines.extend(
        _prospective_delayed_price_confirmation_lines(
            payload.get("prospective_delayed_price_confirmation")
        )
    )
    lines.extend(
        _prospective_top10_rank_filter_lines(
            payload.get("prospective_top10_rank_filter")
        )
    )
    lines.extend(
        _prospective_trade_quality_lines(
            payload.get("prospective_trade_quality")
        )
    )
    lines.extend(
        _prospective_combined_entry_filter_lines(
            payload.get("prospective_combined_entry_filter")
        )
    )
    lines.extend(
        _prospective_capacity_reflow_opportunity_lines(
            payload.get("prospective_capacity_reflow_opportunities")
        )
    )
    lines.extend(
        _prospective_capacity_reflow_release_lineage_lines(
            payload.get("prospective_capacity_reflow_release_lineage")
        )
    )
    lines.extend(
        _prospective_capacity_reflow_fill_feasibility_lines(
            payload.get(
                "prospective_capacity_reflow_fill_feasibility"
            )
        )
    )
    lines.extend(
        _prospective_capacity_reflow_exit_fill_lines(
            payload.get(
                "prospective_capacity_reflow_exit_fill"
            )
        )
    )
    lines.extend(
        _prospective_capacity_reflow_realized_pnl_lines(
            payload.get(
                "prospective_capacity_reflow_realized_pnl"
            )
        )
    )
    lines.extend(
        _prospective_replacement_exit_policy_lines(
            payload.get("prospective_replacement_exit_policy")
        )
    )
    lines.extend(
        _prospective_replacement_exit_robustness_lines(
            payload.get("prospective_replacement_exit_robustness")
        )
    )
    lines.extend(
        _prospective_replacement_exit_readiness_lines(
            payload.get("prospective_replacement_exit_readiness")
        )
    )
    lines.extend(
        _prospective_capacity_reflow_forward_markout_lines(
            payload.get(
                "prospective_capacity_reflow_forward_markout"
            )
        )
    )
    lines.extend(
        _prospective_capacity_reflow_forward_excursion_lines(
            payload.get(
                "prospective_capacity_reflow_forward_excursion"
            )
        )
    )
    lines.extend(
        _prospective_daily_loss_lockout_reflow_lines(
            payload.get("prospective_daily_loss_lockout_reflow")
        )
    )
    lines.extend(
        _opening_rank_lines(
            payload.get("opening_scanner_rank")
        )
    )
    lines.extend(
        _opening_fill_liquidity_lines(
            payload.get("opening_fill_liquidity")
        )
    )
    lines.extend(
        _opening_opportunity_evidence_lines(
            payload.get("opening_opportunity_evidence")
        )
    )
    lines.extend(
        _replacement_funding_evidence_lines(
            payload.get("replacement_funding_evidence")
        )
    )
    lines.extend(
        _entry_markout_lines(
            payload.get("entry_markout")
        )
    )
    lines.extend(
        _entry_markout_predictiveness_lines(
            payload.get("entry_markout_predictiveness")
        )
    )
    lines.extend(
        _excursion_timing_lines(
            payload.get("excursion_timing")
        )
    )
    lines.extend(
        _entry_mid_markout_shadow_lines(
            payload.get("entry_mid_markout_shadow")
        )
    )
    lines.extend(["", "### Open positions", ""])

    if positions_raw:
        lines.extend(
            [
                (
                    "| Market | Side | Qty | Entry | Stop | Mark | "
                    "Unrealized gross PnL | Current R | Stop-lock PnL | "
                    "Stop-lock R | Protected? | Planned risk |"
                ),
                (
                    "| --- | --- | ---: | ---: | ---: | ---: | ---: | "
                    "---: | ---: | ---: | --- | ---: |"
                ),
            ]
        )
        for raw in positions_raw:
            if not isinstance(raw, dict):
                raise ValueError("position must be an object")
            lines.append(
                "| {market} | {side} | {quantity} | {entry} | {stop} | "
                "{mark} | {pnl} | {current_r} | {stop_pnl} | {stop_r} | "
                "{protected} | {risk} |".format(
                    market=raw["market"],
                    side=raw["side"],
                    quantity=raw["quantity"],
                    entry=raw["average_entry_price"],
                    stop=raw["stop_price"],
                    mark=raw["latest_mark"],
                    pnl=raw["unrealized_gross_pnl"],
                    current_r=raw.get("current_gross_r") or "n/a",
                    stop_pnl=raw.get("stop_trigger_gross_pnl", "n/a"),
                    stop_r=raw.get("stop_trigger_gross_r", "n/a"),
                    protected=(
                        "yes"
                        if raw.get("stop_protects_profit") is True
                        else "no"
                    ),
                    risk=raw["planned_risk"],
                )
            )
    else:
        lines.append("_No open paper positions in this heartbeat._")

    recent_closed = payload.get("recent_closed_trades", [])
    if not isinstance(recent_closed, list):
        raise ValueError("recent_closed_trades must be a list")
    lines.extend(["", "### Recent closed trades", ""])
    if recent_closed:
        lines.extend(
            [
                (
                    "| Market | Side | Entry | Exit | Net PnL | Net R | "
                    "MFE R | MAE R | Fees | Funding | Hold | Exit reason |"
                ),
                (
                    "| --- | --- | ---: | ---: | ---: | ---: | ---: | "
                    "---: | ---: | ---: | ---: | --- |"
                ),
            ]
        )
        for raw in recent_closed:
            if not isinstance(raw, dict):
                raise ValueError("recent closed trade must be an object")
            fees = str(
                Decimal(str(raw["entry_fees"]))
                + Decimal(str(raw["exit_fees"]))
            )
            lines.append(
                "| {market} | {direction} | {entry} | {exit} | {net_pnl} | "
                "{net_r} | {mfe_r} | {mae_r} | {fees} | {funding} | "
                "{hold}ms | {reason} |".format(
                    market=raw["market"],
                    direction=raw["direction"],
                    entry=raw["entry_price"],
                    exit=raw["exit_price"],
                    net_pnl=raw["net_pnl"],
                    net_r=raw["net_r"],
                    mfe_r=raw.get("mfe_r") or "n/a",
                    mae_r=raw.get("mae_r") or "n/a",
                    fees=fees,
                    funding=raw["funding_cash_pnl"],
                    hold=raw["holding_duration_ms"],
                    reason=raw["exit_reason"],
                )
            )
    else:
        lines.append("_No closed paper trades in durable state yet._")

    lines.extend(
        _entry_decision_age_lines(
            payload.get("entry_decision_age")
        )
    )
    lines.extend(
        _closed_trade_concentration_lines(
            payload.get("closed_trade_concentration")
        )
    )
    lines.extend(
        _closed_trade_utc_hour_lines(
            payload.get("closed_trade_utc_hour")
        )
    )
    lines.extend(
        _closed_trade_friction_lines(
            payload.get("closed_trade_friction")
        )
    )
    lines.extend(
        _closed_trade_robustness_lines(
            payload.get("closed_trade_robustness")
        )
    )
    lines.extend(
        _closed_trade_stability_lines(
            payload.get("closed_trade_stability")
        )
    )
    lines.extend(["", "### Closed trade performance", ""])
    if performance:
        profit_factor = performance.get("profit_factor")
        lines.extend(
            [
                (
                    "| Trades | Wins | Losses | BE | Net PnL | Gross profit | "
                    "Gross loss | Profit factor | Mean R | Avg hold |"
                ),
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                (
                    "| {trades} | {wins} | {losses} | {breakeven} | {net_pnl} | "
                    "{gross_profit} | {gross_loss_abs} | {profit_factor} | "
                    "{mean_net_r} | {average_holding_ms}ms |"
                ).format(
                    trades=performance.get("trades", 0),
                    wins=performance.get("wins", 0),
                    losses=performance.get("losses", 0),
                    breakeven=performance.get("breakeven", 0),
                    net_pnl=performance.get("net_pnl", "0"),
                    gross_profit=performance.get("gross_profit", "0"),
                    gross_loss_abs=performance.get("gross_loss_abs", "0"),
                    profit_factor="n/a" if profit_factor is None else profit_factor,
                    mean_net_r=performance.get("mean_net_r", "n/a"),
                    average_holding_ms=performance.get("average_holding_ms", "n/a"),
                ),
                (
                    "- decision-fact attribution: "
                    f"`{performance.get('decision_fact_attributed_trades', 0)} / "
                    f"{performance.get('trades', 0)}` trades"
                ),
                (
                    "- decision-fact misses / feature-regime fallbacks / "
                    "unattributed regimes: "
                    f"`{performance.get('decision_fact_attribution_misses', 0)} / "
                    f"{performance.get('feature_snapshot_fallback_trades', 0)} / "
                    f"{performance.get('regime_attribution_misses', 0)}`"
                ),
                "",
                "#### Excursion diagnostics",
                "",
                (
                    "- complete MFE/MAE evidence: "
                    f"`{performance.get('complete_excursion_trades', 0)} / "
                    f"{performance.get('trades', 0)}` trades"
                ),
                (
                    "- mean favorable / adverse excursion: "
                    f"`{performance.get('mean_mfe_r')}`R / "
                    f"`{performance.get('mean_mae_r')}`R"
                ),
                (
                    "- reached +0.5R / +1R MFE: "
                    f"`{performance.get('mfe_ge_0_5r', 0)} / "
                    f"{performance.get('mfe_ge_1r', 0)}`"
                ),
                (
                    "- losses that never reached +0.25R MFE: "
                    f"`{performance.get('losses_with_mfe_lt_0_25r', 0)}`"
                ),
                (
                    "- losses after reaching +0.5R / +1R MFE: "
                    f"`{performance.get('losses_after_mfe_ge_0_5r', 0)} / "
                    f"{performance.get('losses_after_mfe_ge_1r', 0)}`"
                ),
                (
                    "- incomplete/missing excursion evidence: "
                    f"`{performance.get('incomplete_or_missing_excursion_trades', 0)}`"
                ),
                "",
                "#### Exit giveback diagnostics",
                "",
                (
                    "- mean peak-to-close giveback: "
                    f"`{performance.get('mean_peak_to_close_giveback_r')}`R"
                ),
                (
                    "- mean giveback after reaching +0.5R / +1R: "
                    f"`{performance.get('mean_giveback_after_mfe_ge_0_5r')}`R / "
                    f"`{performance.get('mean_giveback_after_mfe_ge_1r')}`R"
                ),
                (
                    "- positive closes after reaching +0.5R / +1R: "
                    f"`{performance.get('positive_closes_after_mfe_ge_0_5r', 0)} / "
                    f"{performance.get('positive_closes_after_mfe_ge_1r', 0)}`"
                ),
                (
                    "- mean final net R after reaching +0.5R / +1R: "
                    f"`{performance.get('mean_final_net_r_after_mfe_ge_0_5r')}`R / "
                    f"`{performance.get('mean_final_net_r_after_mfe_ge_1r')}`R"
                ),
            ]
        )
        exit_groups = performance.get("by_exit_reason", {})
        if isinstance(exit_groups, dict) and exit_groups:
            lines.extend(
                [
                    "",
                    "#### Exit-path giveback attribution",
                    "",
                    (
                        "| Exit path | Trades | +0.5R reached | +1R reached | "
                        "Positive after +0.5R | Mean giveback | "
                        "Giveback after +0.5R | Final R after +0.5R |"
                    ),
                    (
                        "| --- | ---: | ---: | ---: | ---: | ---: | "
                        "---: | ---: |"
                    ),
                ]
            )
            for bucket, raw_group in sorted(exit_groups.items()):
                if not isinstance(raw_group, dict):
                    continue
                lines.append(
                    (
                        "| {bucket} | {trades} | {mfe_half} | {mfe_one} | "
                        "{positive_half} | {giveback} | {giveback_half} | "
                        "{final_half} |"
                    ).format(
                        bucket=bucket,
                        trades=raw_group.get("trades", 0),
                        mfe_half=raw_group.get("mfe_ge_0_5r", 0),
                        mfe_one=raw_group.get("mfe_ge_1r", 0),
                        positive_half=raw_group.get(
                            "positive_closes_after_mfe_ge_0_5r",
                            0,
                        ),
                        giveback=raw_group.get(
                            "mean_peak_to_close_giveback_r",
                            "n/a",
                        ),
                        giveback_half=raw_group.get(
                            "mean_giveback_after_mfe_ge_0_5r",
                            "n/a",
                        ),
                        final_half=raw_group.get(
                            "mean_final_net_r_after_mfe_ge_0_5r",
                            "n/a",
                        ),
                    )
                )

        dimension_labels = (
            ("by_lead_strategy", "Lead strategy"),
            ("by_decision_score_band", "Decision score band"),
            ("by_side", "Side"),
            ("by_trend_regime", "Entry trend regime"),
            ("by_volatility_regime", "Entry volatility regime"),
        )
        for field, label in dimension_labels:
            raw_groups = performance.get(field, {})
            if not isinstance(raw_groups, dict) or not raw_groups:
                continue
            lines.extend(
                [
                    "",
                    f"#### {label} attribution",
                    "",
                    "| Bucket | Trades | W | L | BE | Net PnL | Mean R | Avg hold |",
                    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                ]
            )
            for bucket, raw_group in sorted(raw_groups.items()):
                if not isinstance(raw_group, dict):
                    continue
                lines.append(
                    (
                        "| {bucket} | {trades} | {wins} | {losses} | {breakeven} | "
                        "{net_pnl} | {mean_net_r} | {average_holding_ms}ms |"
                    ).format(
                        bucket=bucket,
                        trades=raw_group.get("trades", 0),
                        wins=raw_group.get("wins", 0),
                        losses=raw_group.get("losses", 0),
                        breakeven=raw_group.get("breakeven", 0),
                        net_pnl=raw_group.get("net_pnl", "0"),
                        mean_net_r=raw_group.get("mean_net_r", "n/a"),
                        average_holding_ms=raw_group.get("average_holding_ms", "n/a"),
                    )
                )
    else:
        lines.append("_No cumulative performance diagnostics are available yet._")

    lines.extend(
        [
            "",
            "### Latest observation",
            "",
            "```json",
            json.dumps(payload.get("last_observation"), indent=2, sort_keys=True),
            "```",
            "",
            "### Decision path",
            "",
            f"- session decision epochs: `{payload.get('session_decision_epochs', 0)}`",
            (
                "- last decision boundary ms: "
                f"`{payload.get('last_decision_boundary_ms')}`"
            ),
            (
                "- last decision evaluated ms: "
                f"`{payload.get('last_decision_evaluated_at_ms')}`"
            ),
            (
                "- LONG / SHORT / NO_TRADE: "
                f"`{decisions.get('long', 0)} / "
                f"{decisions.get('short', 0)} / "
                f"{decisions.get('no_trade', 0)}`"
            ),
            (
                "- risk evaluations / approvals / rejections: "
                f"`{risk.get('evaluations', 0)} / "
                f"{risk.get('approvals', 0)} / "
                f"{risk.get('rejections', 0)}`"
            ),
            (
                "- opening execution attempts / fills: "
                f"`{payload.get('session_opening_execution_attempts', 0)} / "
                f"{payload.get('session_opening_fills', 0)}`"
            ),
            (
                "- strategy reasons: "
                f"`{_reason_summary(payload.get('session_decision_reason_counts', {}))}`"
            ),
            (
                "- risk reasons: "
                f"`{_reason_summary(risk.get('reason_counts', {}))}`"
            ),
            "",
        ]
    )
    lines.extend(_cadence_shadow_lines(payload.get("cadence_shadow")))
    lines.extend(
        _cadence_opportunity_learning_lines(
            payload.get("cadence_opportunity_learning")
        )
    )
    lines.extend(
        [
            "",
            "### Runtime",
            "",
            f"- selected markets: `{payload['selected_market_count']}`",
            f"- processed records: `{payload['processed_records']}`",
            f"- journal observations: `{payload['journal_observations']}`",
            "",
            (
                "> Full heartbeat JSON is intentionally omitted from this live "
                "issue to keep publication reliable. Completed artifacts and "
                "journal state remain the durable audit authority."
            ),
        ]
    )
    return _bounded_issue_body("\n".join(lines) + "\n")


def main() -> None:
    raw = os.environ.get("HEARTBEAT_JSON", "")
    if not raw:
        raw = sys.stdin.read()
    if not raw.strip():
        raise RuntimeError(
            "heartbeat JSON is required via stdin or HEARTBEAT_JSON"
        )
    decoded: object = json.loads(raw)
    if not isinstance(decoded, dict):
        raise RuntimeError("heartbeat JSON must be an object")
    print(
        render_live_status(
            decoded,
            run_id=os.environ.get("GITHUB_RUN_ID", "unknown"),
            head_sha=os.environ.get("GITHUB_SHA", "unknown"),
            predecessor_run_id=os.environ.get("PREDECESSOR_RUN_ID", ""),
        ),
        end="",
    )


if __name__ == "__main__":
    main()
