from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


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


def _delayed_entry_execution_shadow_lines(raw: object) -> list[str]:
    lines = [
        "",
        "### 60s delayed-entry execution shadow",
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
                f"`{str(bool(raw.get('positive_pnl_survives_remove_top_positive_market'))).lower()}`"
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
    delayed_integrity = (
        f"mismatch={delayed.get('lineage_mismatch_closed_trades', 0)}, "
        f"orphan={delayed.get('orphaned_restored_positions', 0)}"
    )

    entry_filter = mapping("prospective_entry_filter")
    entry_filter_gate = readiness(entry_filter)
    entry_filter_ready = bool(
        entry_filter_gate.get("ready_for_review")
    )

    rank_filter = mapping("prospective_top10_rank_filter")
    rank_filter_gate = readiness(rank_filter)
    rank_filter_ready = bool(
        rank_filter_gate.get("ready_for_review")
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
        _prospective_entry_filter_lines(
            payload.get("prospective_entry_filter")
        )
    )
    lines.extend(
        _prospective_top10_rank_filter_lines(
            payload.get("prospective_top10_rank_filter")
        )
    )
    lines.extend(
        _opening_rank_lines(
            payload.get("opening_scanner_rank")
        )
    )
    lines.extend(
        _entry_markout_lines(
            payload.get("entry_markout")
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
        [
            "",
            "### Runtime",
            "",
            f"- selected markets: `{payload['selected_market_count']}`",
            f"- processed records: `{payload['processed_records']}`",
            f"- journal observations: `{payload['journal_observations']}`",
            "",
            "<details><summary>Full heartbeat JSON</summary>",
            "",
            "```json",
            json.dumps(dict(payload), indent=2, sort_keys=True),
            "```",
            "</details>",
            "",
            (
                "> Operational telemetry only. Completed artifacts and journal "
                "state remain the durable audit authority."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    raw = os.environ.get("HEARTBEAT_JSON", "")
    if not raw:
        raise RuntimeError("HEARTBEAT_JSON is required")
    decoded: object = json.loads(raw)
    if not isinstance(decoded, dict):
        raise RuntimeError("HEARTBEAT_JSON must be an object")
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
