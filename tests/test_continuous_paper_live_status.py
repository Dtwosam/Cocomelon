from __future__ import annotations

import json
import os
import subprocess
import sys

SCRIPT = "scripts/render_continuous_paper_live_status.py"


def test_live_status_renderer_exposes_current_position_and_paper_only_state() -> None:
    payload = {
        "timestamp_ms": 1_700_000_000_000,
        "equity": "10002.5",
        "cash": "9990",
        "unrealized_pnl": "12.5",
        "realized_gross_pnl": "0",
        "cumulative_fees": "0.5",
        "cumulative_funding": "0",
        "closed_trades": 0,
        "execution_healthy": True,
        "selected_market_count": 20,
        "processed_records": 123,
        "journal_observations": 7,
        "last_observation": {
            "kind": "execution",
            "timestamp_ms": 1_700_000_000_000,
            "market": "BTC",
            "reason_codes": ["OPEN_FILLED"],
            "plan_id": "plan-1",
        },
        "positions": [
            {
                "market": "BTC",
                "side": "long",
                "quantity": "0.01",
                "average_entry_price": "65000",
                "stop_price": "64000",
                "latest_mark": "65200",
                "unrealized_gross_pnl": "2",
                "planned_risk": "10",
                "opened_at_ms": 1_700_000_000_000,
                "opening_plan_id": "plan-1",
            }
        ],
        "paper_only": True,
        "live_orders": False,
        "selected_markets": ["BTC"],
        "execution_reason_codes": [],
    }
    env = dict(os.environ)
    env["HEARTBEAT_JSON"] = json.dumps(payload)
    env["GITHUB_RUN_ID"] = "12345"
    completed = subprocess.run(
        [sys.executable, SCRIPT],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    output = completed.stdout
    assert "PAPER ONLY" in output
    assert "Live orders:" in output
    assert "BTC" in output
    assert "65000" in output
    assert "64000" in output
    assert "65200" in output
    assert "12345" in output
