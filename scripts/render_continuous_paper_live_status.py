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
        f"- equity: `{payload['equity']}`",
        f"- cash: `{payload['cash']}`",
        f"- unrealized PnL: `{payload['unrealized_pnl']}`",
        f"- realized gross PnL: `{payload['realized_gross_pnl']}`",
        f"- cumulative fees: `{payload['cumulative_fees']}`",
        f"- cumulative funding: `{payload['cumulative_funding']}`",
        f"- closed trades: `{payload['closed_trades']}`",
        f"- open planned risk: `{payload.get('open_planned_risk', '0')}`",
        (
            "- open planned risk / equity: "
            f"`{payload.get('open_planned_risk_fraction_of_equity', '0')}`"
        ),
        f"- gross open notional: `{payload.get('gross_open_notional', '0')}`",
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
                    "Unrealized gross PnL | Planned risk |"
                ),
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for raw in positions_raw:
            if not isinstance(raw, dict):
                raise ValueError("position must be an object")
            lines.append(
                "| {market} | {side} | {quantity} | {entry} | {stop} | "
                "{mark} | {pnl} | {risk} |".format(
                    market=raw["market"],
                    side=raw["side"],
                    quantity=raw["quantity"],
                    entry=raw["average_entry_price"],
                    stop=raw["stop_price"],
                    mark=raw["latest_mark"],
                    pnl=raw["unrealized_gross_pnl"],
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
                    "Fees | Funding | Hold | Exit reason |"
                ),
                (
                    "| --- | --- | ---: | ---: | ---: | ---: | ---: | "
                    "---: | ---: | --- |"
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
                "{net_r} | {fees} | {funding} | {hold}ms | {reason} |".format(
                    market=raw["market"],
                    direction=raw["direction"],
                    entry=raw["entry_price"],
                    exit=raw["exit_price"],
                    net_pnl=raw["net_pnl"],
                    net_r=raw["net_r"],
                    fees=fees,
                    funding=raw["funding_cash_pnl"],
                    hold=raw["holding_duration_ms"],
                    reason=raw["exit_reason"],
                )
            )
    else:
        lines.append("_No closed paper trades in durable state yet._")

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
