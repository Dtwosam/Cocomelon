from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


def render_live_status(
    payload: Mapping[str, Any],
    *,
    run_id: str,
) -> str:
    timestamp_ms = int(payload["timestamp_ms"])
    timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    positions_raw = payload.get("positions", [])
    if not isinstance(positions_raw, list):
        raise ValueError("positions must be a list")

    lines = [
        "## Continuous paper runtime live status",
        "",
        f"**Updated:** `{timestamp.isoformat()}`",
        f"**Worker run:** `{run_id}`",
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

    lines.extend(
        [
            "",
            "### Latest observation",
            "",
            "```json",
            json.dumps(payload.get("last_observation"), indent=2, sort_keys=True),
            "```",
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
        ),
        end="",
    )


if __name__ == "__main__":
    main()
