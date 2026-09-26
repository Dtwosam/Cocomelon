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
        "closed_trades": 12,
        "session_closed_trades": 2,
        "open_planned_risk": "10",
        "open_planned_risk_fraction_of_equity": "0.0009997500624843789052736815796",
        "gross_open_notional": "650",
        "available_margin": "9500",
        "execution_healthy": True,
        "selected_market_count": 20,
        "processed_records": 123,
        "journal_observations": 7,
        "session_decision_epochs": 1,
        "last_decision_boundary_ms": 1_699_999_970_000,
        "last_decision_evaluated_at_ms": 1_700_000_000_000,
        "session_decisions": {"long": 1, "short": 0, "no_trade": 19},
        "session_decision_reason_counts": {"NO_SIGNAL": 19, "trend": 1},
        "session_risk": {
            "evaluations": 1,
            "approvals": 1,
            "rejections": 0,
            "reason_counts": {"APPROVED": 1},
        },
        "session_opening_execution_attempts": 1,
        "session_opening_fills": 1,
        "last_observation": {
            "kind": "execution",
            "timestamp_ms": 1_700_000_000_000,
            "market": "BTC",
            "reason_codes": ["OPEN_FILLED"],
            "plan_id": "plan-1",
        },
        "recent_closed_trades": [
            {
                "trade_id": "trade-1",
                "market": "ETH",
                "direction": "short",
                "opened_at_ms": 1_699_999_000_000,
                "closed_at_ms": 1_700_000_000_000,
                "holding_duration_ms": 1_000_000,
                "entry_price": "3500",
                "exit_price": "3480",
                "filled_quantity": "0.5",
                "initial_stop": "3520",
                "initial_risk_amount": "10",
                "gross_realized_pnl": "10",
                "entry_fees": "0.8",
                "exit_fees": "0.8",
                "funding_cash_pnl": "0.1",
                "net_pnl": "8.5",
                "net_r": "0.85",
                "exit_reason": "thesis_exit",
            }
        ],
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
        "cadence_shadow": {
            "enabled": True,
            "error": None,
            "shadow_only": True,
            "execution_authority": False,
            "session_only": True,
            "pending_outcome_count": 3,
            "censored_due_to_unsubscribe": 1,
            "cadences": {
                "300000": {
                    "decision_counts": {
                        "long": 2,
                        "short": 1,
                        "no_trade": 7,
                    },
                    "off_primary_boundary_outcomes_by_horizon_ms": {
                        "900000": {
                            "settled_count": 2,
                            "mean_net_return": "0.003",
                            "positive_net_count": 1,
                        },
                        "3600000": {
                            "settled_count": 1,
                            "mean_net_return": "-0.002",
                            "positive_net_count": 0,
                        },
                    },
                },
                "900000": {
                    "decision_counts": {
                        "long": 1,
                        "short": 0,
                        "no_trade": 3,
                    },
                },
            },
        },
    }
    env = dict(os.environ)
    env["HEARTBEAT_JSON"] = json.dumps(payload)
    env["GITHUB_RUN_ID"] = "12345"
    env["GITHUB_SHA"] = "abcdef123456"
    env["PREDECESSOR_RUN_ID"] = "12222"
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
    assert "5m cadence shadow diagnostic" in output
    assert "RESEARCH ONLY / NO EXECUTION" in output
    assert "2 / 1 / 7" in output
    assert "mean net=`0.003`" in output
    assert "Recent closed trades" in output
    assert "ETH" in output
    assert "8.5" in output
    assert "0.85" in output
    assert "thesis_exit" in output
    assert "abcdef123456" in output
    assert "12222" in output
    assert "### Decision path" in output
    assert "LONG / SHORT / NO_TRADE" in output
    assert "`1 / 0 / 19`" in output
    assert "risk evaluations / approvals / rejections" in output
    assert "opening execution attempts / fills" in output
    assert "strategy reasons:" in output
    assert "NO_SIGNAL=19" in output
    assert "risk reasons:" in output
    assert "APPROVED=1" in output
    assert "cumulative closed trades" in output
    assert "closed trades this worker" in output
    assert "`12`" in output
    assert "`2`" in output
    assert "open planned risk" in output
    assert "gross open notional" in output
