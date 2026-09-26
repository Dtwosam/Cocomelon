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
        "",
        "### Open positions",
        "",
    ]

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
