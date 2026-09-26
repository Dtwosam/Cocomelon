from __future__ import annotations

import json
import os
import subprocess
import sys

SCRIPT = "scripts/render_continuous_paper_live_status.py"


def test_live_status_renderer_exposes_current_position_and_paper_only_state() -> None:
    payload = {
        "timestamp_ms": 1_700_000_000_000,
        "starting_cash": "10000",
        "equity": "10002.5",
        "total_account_pnl": "2.5",
        "total_return_fraction": "0.00025",
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
        "gross_open_notional_fraction_of_equity": "0.06498375406148462884278930267",
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
                "mfe_r": "1.4",
                "mae_r": "0.25",
                "excursion_complete": True,
                "exit_reason": "thesis_exit",
            }
        ],
        "closed_trade_performance": {
            "trades": 3,
            "wins": 1,
            "losses": 2,
            "breakeven": 0,
            "net_pnl": "-7",
            "mean_net_pnl": "-2.333333333333333333333333333",
            "mean_net_r": "-0.2333333333333333333333333333",
            "average_holding_ms": 120000,
            "gross_profit": "5",
            "gross_loss_abs": "12",
            "profit_factor": "0.4166666666666666666666666667",
            "decision_fact_attributed_trades": 3,
            "decision_fact_attribution_misses": 0,
            "feature_snapshot_fallback_trades": 0,
            "regime_attribution_misses": 0,
            "unattributed_feature_trades": 0,
            "complete_excursion_trades": 3,
            "incomplete_or_missing_excursion_trades": 0,
            "mean_mfe_r": "0.6333333333333333333333333333",
            "mean_mae_r": "0.7333333333333333333333333333",
            "mfe_ge_0_5r": 2,
            "mfe_ge_1r": 1,
            "losses_with_mfe_lt_0_25r": 1,
            "losses_after_mfe_ge_0_5r": 1,
            "losses_after_mfe_ge_1r": 0,
            "mean_peak_to_close_giveback_r": "0.8666666666666666666666666667",
            "mean_giveback_after_mfe_ge_0_5r": "0.75",
            "mean_giveback_after_mfe_ge_1r": "0.7",
            "positive_closes_after_mfe_ge_0_5r": 1,
            "positive_closes_after_mfe_ge_1r": 1,
            "mean_final_net_r_after_mfe_ge_0_5r": "0.15",
            "mean_final_net_r_after_mfe_ge_1r": "0.5",
            "by_lead_strategy": {
                "trend": {
                    "trades": 2,
                    "wins": 1,
                    "losses": 1,
                    "breakeven": 0,
                    "net_pnl": "3",
                    "mean_net_pnl": "1.5",
                    "mean_net_r": "0.15",
                    "average_holding_ms": 90000,
                }
            },
            "by_decision_score_band": {
                "65-<70": {
                    "trades": 2,
                    "wins": 1,
                    "losses": 1,
                    "breakeven": 0,
                    "net_pnl": "3",
                    "mean_net_pnl": "1.5",
                    "mean_net_r": "0.15",
                    "average_holding_ms": 90000,
                }
            },
            "by_side": {
                "long": {
                    "trades": 2,
                    "wins": 1,
                    "losses": 1,
                    "breakeven": 0,
                    "net_pnl": "3",
                    "mean_net_pnl": "1.5",
                    "mean_net_r": "0.15",
                    "average_holding_ms": 90000,
                },
                "short": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "breakeven": 0,
                    "net_pnl": "-10",
                    "mean_net_pnl": "-10",
                    "mean_net_r": "-1",
                    "average_holding_ms": 180000,
                },
            },
            "by_exit_reason": {
                "OPPOSITE_FRESH_THESIS": {
                    "trades": 2,
                    "wins": 1,
                    "losses": 1,
                    "breakeven": 0,
                    "net_pnl": "3",
                    "mean_net_pnl": "1.5",
                    "mean_net_r": "0.15",
                    "average_holding_ms": 90000,
                    "complete_excursion_trades": 2,
                    "incomplete_or_missing_excursion_trades": 0,
                    "mean_mfe_r": "0.9",
                    "mean_mae_r": "0.55",
                    "mfe_ge_0_5r": 2,
                    "mfe_ge_1r": 1,
                    "losses_with_mfe_lt_0_25r": 0,
                    "losses_after_mfe_ge_0_5r": 1,
                    "losses_after_mfe_ge_1r": 0,
                    "mean_peak_to_close_giveback_r": "0.75",
                    "mean_giveback_after_mfe_ge_0_5r": "0.75",
                    "mean_giveback_after_mfe_ge_1r": "0.7",
                    "positive_closes_after_mfe_ge_0_5r": 1,
                    "positive_closes_after_mfe_ge_1r": 1,
                    "mean_final_net_r_after_mfe_ge_0_5r": "0.15",
                    "mean_final_net_r_after_mfe_ge_1r": "0.5",
                }
            },
            "by_trend_regime": {
                "downtrend": {
                    "trades": 2,
                    "wins": 0,
                    "losses": 2,
                    "breakeven": 0,
                    "net_pnl": "-12",
                    "mean_net_pnl": "-6",
                    "mean_net_r": "-0.6",
                    "average_holding_ms": 150000,
                }
            },
            "by_volatility_regime": {},
        },
        "cadence_shadow": {
            "enabled": True,
            "error": None,
            "shadow_only": True,
            "execution_authority": False,
            "session_only": False,
            "durable_state": True,
            "state_restored": True,
            "state_restore_error": None,
            "state_schema_version": 1,
            "pending_outcome_count": 3,
            "censored_due_to_unsubscribe": 1,
            "skipped_missing_lead_strategy": 0,
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
                    "outcomes_by_lead_strategy_by_horizon_ms": {
                        "900000": {
                            "trend": {
                                "settled_count": 3,
                                "mean_net_return": "-0.001",
                                "positive_net_count": 1,
                            }
                        },
                        "3600000": {
                            "trend": {
                                "settled_count": 2,
                                "mean_net_return": "0.002",
                                "positive_net_count": 1,
                            }
                        },
                    },
                    "outcomes_by_score_band_by_horizon_ms": {
                        "900000": {
                            "65-<70": {
                                "settled_count": 1,
                                "mean_net_return": "-0.004",
                                "positive_net_count": 0,
                            },
                            "80+": {
                                "settled_count": 2,
                                "mean_net_return": "0.0005",
                                "positive_net_count": 1,
                            },
                        },
                        "3600000": {
                            "65-<70": {
                                "settled_count": 1,
                                "mean_net_return": "-0.003",
                                "positive_net_count": 0,
                            },
                            "80+": {
                                "settled_count": 1,
                                "mean_net_return": "0.007",
                                "positive_net_count": 1,
                            },
                        },
                    },
                },
            },
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
    assert "5m cadence shadow diagnostic" in output
    assert "RESEARCH ONLY / NO EXECUTION" in output
    assert "durable across workers" in output
    assert "restored this worker: `true`" in output
    assert "2 / 1 / 7" in output
    assert "mean net=`0.003`" in output
    assert "#### 15m lead-strategy forward outcomes" in output
    assert "| trend | 3 | -0.001 | 1 | 2 | 0.002 | 1 |" in output
    assert "#### 15m decision-score forward outcomes" in output
    assert "| 65-<70 | 1 | -0.004 | 0 | 1 | -0.003 | 0 |" in output
    assert "| 80+ | 2 | 0.0005 | 1 | 1 | 0.007 | 1 |" in output
    assert "skipped directional signals missing lead strategy" in output
    assert "starting cash" in output
    assert "total account PnL" in output
    assert "2.5" in output
    assert "total return fraction" in output
    assert "gross open notional / equity" in output
    assert "### Closed trade performance" in output
    assert "decision-fact attribution" in output
    assert "`3 / 3` trades" in output
    assert "decision-fact misses / feature-regime fallbacks" in output
    assert "#### Lead strategy attribution" in output
    assert "| trend | 2 | 1 | 1 | 0 | 3 |" in output
    assert "#### Decision score band attribution" in output
    assert "| 65-<70 | 2 | 1 | 1 | 0 | 3 |" in output
    assert "#### Excursion diagnostics" in output
    assert "complete MFE/MAE evidence" in output
    assert "0.6333333333333333333333333333" in output
    assert "losses that never reached +0.25R MFE" in output
    assert "losses after reaching +0.5R / +1R MFE" in output
    assert "MFE R | MAE R" in output
    assert "1.4" in output
    assert "0.25" in output
    assert "#### Exit giveback diagnostics" in output
    assert "mean peak-to-close giveback" in output
    assert "0.8666666666666666666666666667" in output
    assert "positive closes after reaching +0.5R / +1R" in output
    assert "#### Exit-path giveback attribution" in output
    assert "| OPPOSITE_FRESH_THESIS | 2 | 2 | 1 | 1 | 0.75 | 0.75 | 0.15 |" in output
    assert "| 3 | 1 | 2 | 0 | -7 | 5 | 12 |" in output
    assert "#### Side attribution" in output
    assert "| long | 2 | 1 | 1 | 0 | 3 |" in output
    assert "#### Entry trend regime attribution" in output
    assert "| downtrend | 2 | 0 | 2 | 0 | -12 |" in output
