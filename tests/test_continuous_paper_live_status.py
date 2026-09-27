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
        "open_stop_trigger_gross_pnl": "4",
        "open_stop_trigger_gross_r": "0.4",
        "open_positions_with_profit_protected_stop": 1,
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
        "closed_trade_robustness": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": None,
            "closed_trades": 4,
            "net_pnl": "4",
            "gross_profit": "15",
            "median_net_r": "0.1",
            "largest_winner_net_pnl": "10",
            "largest_winner_net_r": "1.0",
            "largest_winner_trade_id": "best",
            "top_one_winner_share_of_gross_profit": "0.6666666666666666666666666667",
            "top_two_winner_share_of_gross_profit": "1",
            "top_positive_market": "NIL",
            "top_positive_market_net_pnl": "70",
            "top_positive_market_trade_count": 3,
            "top_positive_market_share_of_positive_market_pnl": (
                "0.8235294117647058823529411765"
            ),
            "remove_top_positive_market": {
                "remaining_trades": 17,
                "removed_trade_count": 3,
                "removed_trade_ids": ["nil-a", "nil-b", "nil-c"],
                "removed_net_pnl": "70",
                "net_pnl": "-58",
                "mean_net_r": "-0.22",
                "median_net_r": "-0.2",
                "profit_factor": "0.45",
                "positive_net_pnl": False,
            },
            "positive_pnl_survives_remove_top_positive_market": False,
            "remove_best_one": {
                "remaining_trades": 3,
                "removed_trade_count": 1,
                "removed_trade_ids": ["best"],
                "removed_net_pnl": "10",
                "net_pnl": "-6",
                "mean_net_r": "-0.2",
                "median_net_r": "-0.3",
                "profit_factor": "0.4545454545454545454545454545",
                "positive_net_pnl": False,
            },
            "remove_best_two": {
                "remaining_trades": 2,
                "removed_trade_count": 2,
                "removed_trade_ids": ["best", "second"],
                "removed_net_pnl": "15",
                "net_pnl": "-11",
                "mean_net_r": "-0.55",
                "median_net_r": "-0.55",
                "profit_factor": "0",
                "positive_net_pnl": False,
            },
            "positive_pnl_survives_remove_best_one": False,
            "positive_pnl_survives_remove_best_two": False,
            "readiness": {
                "min_closed_trades": 30,
                "missing_closed_trades": 26,
                "ready_for_review": False,
            },
        },
        "closed_trade_stability": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": None,
            "definition": "chronological_closed_trade_net_economics",
            "closed_trades": 20,
            "overall": {
                "trades": 20,
                "wins": 5,
                "losses": 15,
                "breakeven": 0,
                "net_pnl": "12",
                "mean_net_r": "0.03",
                "median_net_r": "-0.2",
                "profit_factor": "1.2",
                "positive_net_pnl": True,
                "positive_mean_net_r": True,
                "first_closed_at_ms": 1000,
                "last_closed_at_ms": 20000,
            },
            "rolling": {
                "5": {
                    "window_size": 5,
                    "window_count": 16,
                    "positive_pnl_windows": 8,
                    "positive_mean_r_windows": 6,
                    "positive_pnl_fraction": "0.5",
                    "positive_mean_r_fraction": "0.375",
                    "worst_mean_net_r": "-0.4",
                    "best_mean_net_r": "1.0",
                    "worst_net_pnl": "-15",
                    "best_net_pnl": "30",
                    "latest": {
                        "net_pnl": "-10",
                        "mean_net_r": "-0.2",
                    },
                },
                "10": {
                    "window_size": 10,
                    "window_count": 11,
                    "positive_pnl_windows": 6,
                    "positive_mean_r_windows": 5,
                    "positive_pnl_fraction": "0.5454545454545454545454545455",
                    "positive_mean_r_fraction": "0.4545454545454545454545454545",
                    "worst_mean_net_r": "-0.25",
                    "best_mean_net_r": "0.45",
                    "worst_net_pnl": "-20",
                    "best_net_pnl": "35",
                    "latest": {
                        "net_pnl": "-5",
                        "mean_net_r": "-0.1",
                    },
                },
            },
            "chronological_blocks": [
                {
                    "block": 1,
                    "trades": 5,
                    "wins": 2,
                    "losses": 3,
                    "net_pnl": "10",
                    "mean_net_r": "0.2",
                    "profit_factor": "2",
                },
                {
                    "block": 2,
                    "trades": 5,
                    "wins": 1,
                    "losses": 4,
                    "net_pnl": "5",
                    "mean_net_r": "0.1",
                    "profit_factor": "1.3",
                },
                {
                    "block": 3,
                    "trades": 5,
                    "wins": 1,
                    "losses": 4,
                    "net_pnl": "-2",
                    "mean_net_r": "-0.04",
                    "profit_factor": "0.9",
                },
                {
                    "block": 4,
                    "trades": 5,
                    "wins": 1,
                    "losses": 4,
                    "net_pnl": "-1",
                    "mean_net_r": "-0.02",
                    "profit_factor": "0.95",
                },
            ],
            "stability": {
                "all_full_blocks_positive_net_pnl": False,
                "all_full_blocks_positive_mean_net_r": False,
                "full_blocks": 0,
            },
            "readiness": {
                "min_closed_trades": 40,
                "chronological_blocks": 4,
                "min_trades_per_block": 10,
                "missing_closed_trades": 20,
                "ready_for_review": False,
            },
        },
        "drawdown": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": None,
            "sampled_account": {
                "definition": "prospective_runtime_checkpoint_equity",
                "checkpoint_seconds": 30,
                "started_at_ms": 1_699_999_000_000,
                "state_restored": True,
                "state_restore_error": None,
                "observation_count": 12,
                "first_timestamp_ms": 1_699_999_000_000,
                "last_timestamp_ms": 1_699_999_660_000,
                "peak_timestamp_ms": 1_699_999_600_000,
                "mean_observation_interval_ms": 60000,
                "first_equity": "10000",
                "last_equity": "10002.5",
                "peak_equity": "10020",
                "current_drawdown_fraction": "0.001746506986027944111776447106",
                "current_drawdown_amount": "17.5",
                "max_drawdown_fraction": "0.004",
                "max_drawdown_amount": "40",
                "max_drawdown_peak_equity": "10000",
                "max_drawdown_trough_equity": "9960",
                "max_drawdown_peak_timestamp_ms": 1_699_999_000_000,
                "max_drawdown_trough_timestamp_ms": 1_699_999_300_000,
            },
            "realized_closed_trade": {
                "closed_trades": 3,
                "starting_equity": "10000",
                "ending_realized_equity": "9993",
                "peak_realized_equity": "10005",
                "max_drawdown_fraction": "0.001199400299850074962518740630",
                "max_drawdown_amount": "12",
                "max_drawdown_peak_equity": "10005",
                "max_drawdown_trough_equity": "9993",
                "max_drawdown_peak_timestamp_ms": 1_699_999_100_000,
                "max_drawdown_trough_timestamp_ms": 1_699_999_300_000,
            },
        },
        "account_lifecycle_economics": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": None,
            "closed_trade_count": 1,
            "open_position_count": 1,
            "account": {
                "realized_gross_pnl": "52",
                "cumulative_fees": "3",
                "cumulative_funding": "0",
                "realized_net_cash": "49",
                "unrealized_pnl": "1",
                "total_account_pnl": "50",
            },
            "open_lifecycles": {
                "realized_gross_pnl": "60",
                "fees": "1",
                "funding": "0",
                "realized_net_cash": "59",
                "unrealized_pnl": "1",
                "mark_to_market_pnl": "60",
                "positions": [
                    {
                        "market": "BTC",
                        "side": "long",
                        "remaining_quantity": "1",
                        "cumulative_realized_gross_pnl": "60",
                        "cumulative_fees": "1",
                        "cumulative_funding": "0",
                        "realized_net_cash": "59",
                        "unrealized_gross_pnl": "1",
                        "lifecycle_mark_to_market_pnl": "60",
                    }
                ],
            },
            "implied_fully_closed_lifecycles": {
                "realized_gross_pnl": "-8",
                "fees": "2",
                "funding": "0",
                "net_pnl": "-10",
            },
            "journal_closed_trades": {
                "realized_gross_pnl": "-8",
                "fees": "2",
                "funding": "0",
                "net_pnl": "-10",
            },
            "reconciliation": {
                "absolute_tolerance": "1E-18",
                "cash_bridge_delta": "0",
                "closed_gross_delta": "0",
                "closed_fees_delta": "0",
                "closed_funding_delta": "0",
                "closed_net_delta": "0",
                "realized_bridge_delta": "0",
                "equity_bridge_delta": "0",
                "cash_bridge_matches_account": True,
                "closed_journal_matches_account": True,
                "realized_bridge_matches_account": True,
                "equity_bridge_matches_account": True,
            },
        },
        "entry_decision_age": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": None,
            "definition": "strategy_decision_timestamp_to_first_opening_fill",
            "attributed_closed_trades": 4,
            "attribution_misses": 0,
            "minimum_attributed_trades_for_review": 30,
            "ready_for_review": False,
            "still_needed_for_review": 26,
            "older_than_5s": 3,
            "older_than_15s": 2,
            "older_than_30s": 2,
            "older_than_60s": 1,
            "overall": {
                "trades": 4,
                "wins": 2,
                "losses": 2,
                "breakeven": 0,
                "net_pnl": "2",
                "mean_net_r": "0.05",
                "mean_decision_age_ms": 26875,
                "median_decision_age_ms": 35000,
                "p90_decision_age_ms": 65000,
                "max_decision_age_ms": 65000,
            },
            "by_age_band": {
                "<1s": {
                    "trades": 1,
                    "wins": 1,
                    "losses": 0,
                    "breakeven": 0,
                    "net_pnl": "5",
                    "mean_net_r": "0.5",
                    "mean_decision_age_ms": 500,
                },
                "1-<5s": {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "breakeven": 0,
                    "net_pnl": "0",
                    "mean_net_r": None,
                    "mean_decision_age_ms": None,
                },
                "5-<15s": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "breakeven": 0,
                    "net_pnl": "-2",
                    "mean_net_r": "-0.2",
                    "mean_decision_age_ms": 7000,
                },
                "15-<30s": {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "breakeven": 0,
                    "net_pnl": "0",
                    "mean_net_r": None,
                    "mean_decision_age_ms": None,
                },
                "30-<60s": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "breakeven": 0,
                    "net_pnl": "-4",
                    "mean_net_r": "-0.4",
                    "mean_decision_age_ms": 35000,
                },
                "60s+": {
                    "trades": 1,
                    "wins": 1,
                    "losses": 0,
                    "breakeven": 0,
                    "net_pnl": "3",
                    "mean_net_r": "0.3",
                    "mean_decision_age_ms": 65000,
                },
            },
            "by_side": {
                "long": {
                    "trades": 2,
                    "wins": 1,
                    "losses": 1,
                    "breakeven": 0,
                    "net_pnl": "1",
                    "mean_net_r": "0.05",
                    "mean_decision_age_ms": 17750,
                },
                "short": {
                    "trades": 2,
                    "wins": 1,
                    "losses": 1,
                    "breakeven": 0,
                    "net_pnl": "1",
                    "mean_net_r": "0.05",
                    "mean_decision_age_ms": 36000,
                },
            },
            "by_lead_strategy": {
                "breakout": {
                    "trades": 2,
                    "wins": 2,
                    "losses": 0,
                    "breakeven": 0,
                    "net_pnl": "8",
                    "mean_net_r": "0.4",
                    "mean_decision_age_ms": 32750,
                },
                "trend": {
                    "trades": 2,
                    "wins": 0,
                    "losses": 2,
                    "breakeven": 0,
                    "net_pnl": "-6",
                    "mean_net_r": "-0.3",
                    "mean_decision_age_ms": 21000,
                },
            },
        },
        "closed_trade_concentration": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": None,
            "definition": "phase9_positive_group_net_pnl_share",
            "trade_count": 5,
            "distinct_markets": 3,
            "distinct_lead_strategies": 2,
            "distinct_seven_day_buckets": 3,
            "decision_fact_misses": 0,
            "market_reference_max_share": "0.35",
            "seven_day_reference_max_share": "0.50",
            "market_reference_met": False,
            "seven_day_reference_met": False,
            "market": {
                "group_count": 3,
                "largest_positive_contributor": "SOL",
                "max_positive_net_pnl_share": "0.6",
                "trade_count_hhi": "0.36",
                "positive_net_pnl_hhi": "0.52",
                "rows": [
                    {
                        "label": "BTC",
                        "trades": 2,
                        "wins": 1,
                        "losses": 1,
                        "breakeven": 0,
                        "net_pnl": "0",
                        "mean_net_r": "0",
                        "trade_count_share": "0.4",
                        "positive_net_pnl_share": "0",
                    },
                    {
                        "label": "ETH",
                        "trades": 1,
                        "wins": 1,
                        "losses": 0,
                        "breakeven": 0,
                        "net_pnl": "20",
                        "mean_net_r": "2",
                        "trade_count_share": "0.2",
                        "positive_net_pnl_share": "0.4",
                    },
                    {
                        "label": "SOL",
                        "trades": 2,
                        "wins": 1,
                        "losses": 1,
                        "breakeven": 0,
                        "net_pnl": "30",
                        "mean_net_r": "1.5",
                        "trade_count_share": "0.4",
                        "positive_net_pnl_share": "0.6",
                    },
                ],
            },
            "lead_strategy": {
                "group_count": 2,
                "largest_positive_contributor": "breakout",
                "max_positive_net_pnl_share": "0.5",
                "trade_count_hhi": "0.52",
                "positive_net_pnl_hhi": "0.50",
                "rows": [
                    {
                        "label": "breakout",
                        "trades": 2,
                        "wins": 2,
                        "losses": 0,
                        "breakeven": 0,
                        "net_pnl": "25",
                        "mean_net_r": "1.25",
                        "trade_count_share": "0.4",
                        "positive_net_pnl_share": "0.5",
                    },
                    {
                        "label": "trend",
                        "trades": 3,
                        "wins": 1,
                        "losses": 2,
                        "breakeven": 0,
                        "net_pnl": "25",
                        "mean_net_r": "0.8333333333333333333333333333",
                        "trade_count_share": "0.6",
                        "positive_net_pnl_share": "0.5",
                    },
                ],
            },
            "seven_day": {
                "group_count": 3,
                "largest_positive_contributor": "0",
                "max_positive_net_pnl_share": "0.6",
                "trade_count_hhi": "0.36",
                "positive_net_pnl_hhi": "0.46",
                "rows": [
                    {
                        "label": "0",
                        "trades": 2,
                        "wins": 1,
                        "losses": 1,
                        "breakeven": 0,
                        "net_pnl": "30",
                        "mean_net_r": "1.5",
                        "trade_count_share": "0.4",
                        "positive_net_pnl_share": "0.6",
                    },
                    {
                        "label": "1",
                        "trades": 2,
                        "wins": 1,
                        "losses": 1,
                        "breakeven": 0,
                        "net_pnl": "15",
                        "mean_net_r": "0.75",
                        "trade_count_share": "0.4",
                        "positive_net_pnl_share": "0.3",
                    },
                    {
                        "label": "2",
                        "trades": 1,
                        "wins": 1,
                        "losses": 0,
                        "breakeven": 0,
                        "net_pnl": "5",
                        "mean_net_r": "0.5",
                        "trade_count_share": "0.2",
                        "positive_net_pnl_share": "0.1",
                    },
                ],
            },
        },
        "closed_trade_utc_hour": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": None,
            "definition": "strategy_decision_timestamp_utc_hour",
            "closed_trades": 4,
            "attributed_trades": 4,
            "attribution_misses": 0,
            "active_utc_hours": 3,
            "positive_net_pnl_hours": 1,
            "negative_net_pnl_hours": 2,
            "trade_count_hhi": "0.375",
            "rows": [
                {
                    "utc_hour": 0,
                    "label": "00:00-00:59",
                    "trades": 1,
                    "wins": 1,
                    "losses": 0,
                    "breakeven": 0,
                    "net_pnl": "10",
                    "mean_net_r": "1",
                    "win_rate": "1",
                    "profit_factor": None,
                    "trade_count_share": "0.25",
                },
                {
                    "utc_hour": 8,
                    "label": "08:00-08:59",
                    "trades": 2,
                    "wins": 1,
                    "losses": 1,
                    "breakeven": 0,
                    "net_pnl": "-3",
                    "mean_net_r": "-0.15",
                    "win_rate": "0.5",
                    "profit_factor": "0.4",
                    "trade_count_share": "0.5",
                },
                {
                    "utc_hour": 23,
                    "label": "23:00-23:59",
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "breakeven": 0,
                    "net_pnl": "-1",
                    "mean_net_r": "-0.1",
                    "win_rate": "0",
                    "profit_factor": "0",
                    "trade_count_share": "0.25",
                },
            ],
        },
        "closed_trade_friction": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": None,
            "definition": (
                "reference_gross_minus_slippage_minus_fees_plus_funding"
            ),
            "decision_fact_attribution_misses": 0,
            "overall": {
                "trades": 3,
                "reference_gross_pnl": "6",
                "signed_slippage_amount": "1",
                "adverse_slippage_amount": "3",
                "favorable_slippage_amount": "2",
                "actual_gross_realized_pnl": "5",
                "fees": "5.5",
                "funding_cash_pnl": "2",
                "net_pnl": "1.5",
                "net_cost_drag": "4.5",
                "reference_gross_positive_trades": 2,
                "actual_gross_positive_trades": 2,
                "net_positive_trades": 2,
                "friction_flipped_trades": 1,
                "fee_funding_flipped_trades": 1,
                "friction_rescued_trades": 1,
                "mean_reference_gross_r": "0.2",
                "mean_slippage_drag_r": "0.03333333333333333333333333333",
                "mean_fee_drag_r": "0.1833333333333333333333333333",
                "mean_funding_r": "0.06666666666666666666666666667",
                "mean_net_r": "0.05",
                "mean_net_cost_drag_r": "0.15",
            },
            "by_side": {
                "long": {
                    "trades": 2,
                    "reference_gross_pnl": "9",
                    "signed_slippage_amount": "3",
                    "adverse_slippage_amount": "3",
                    "favorable_slippage_amount": "0",
                    "actual_gross_realized_pnl": "6",
                    "fees": "5",
                    "funding_cash_pnl": "0",
                    "net_pnl": "1",
                    "net_cost_drag": "8",
                    "reference_gross_positive_trades": 2,
                    "actual_gross_positive_trades": 2,
                    "net_positive_trades": 1,
                    "friction_flipped_trades": 1,
                    "fee_funding_flipped_trades": 1,
                    "friction_rescued_trades": 0,
                    "mean_reference_gross_r": "0.45",
                    "mean_slippage_drag_r": "0.15",
                    "mean_fee_drag_r": "0.25",
                    "mean_funding_r": "0",
                    "mean_net_r": "0.05",
                    "mean_net_cost_drag_r": "0.4",
                },
                "short": {
                    "trades": 1,
                    "reference_gross_pnl": "-3",
                    "signed_slippage_amount": "-2",
                    "adverse_slippage_amount": "0",
                    "favorable_slippage_amount": "2",
                    "actual_gross_realized_pnl": "-1",
                    "fees": "0.5",
                    "funding_cash_pnl": "2",
                    "net_pnl": "0.5",
                    "net_cost_drag": "-3.5",
                    "reference_gross_positive_trades": 0,
                    "actual_gross_positive_trades": 0,
                    "net_positive_trades": 1,
                    "friction_flipped_trades": 0,
                    "fee_funding_flipped_trades": 0,
                    "friction_rescued_trades": 1,
                    "mean_reference_gross_r": "-0.3",
                    "mean_slippage_drag_r": "-0.2",
                    "mean_fee_drag_r": "0.05",
                    "mean_funding_r": "0.2",
                    "mean_net_r": "0.05",
                    "mean_net_cost_drag_r": "-0.35",
                },
            },
            "by_lead_strategy": {
                "breakout": {
                    "trades": 1,
                    "reference_gross_pnl": "-3",
                    "signed_slippage_amount": "-2",
                    "fees": "0.5",
                    "funding_cash_pnl": "2",
                    "net_pnl": "0.5",
                    "friction_flipped_trades": 0,
                    "mean_reference_gross_r": "-0.3",
                    "mean_net_cost_drag_r": "-0.35",
                    "mean_net_r": "0.05",
                },
                "trend": {
                    "trades": 2,
                    "reference_gross_pnl": "9",
                    "signed_slippage_amount": "3",
                    "fees": "5",
                    "funding_cash_pnl": "0",
                    "net_pnl": "1",
                    "friction_flipped_trades": 1,
                    "mean_reference_gross_r": "0.45",
                    "mean_net_cost_drag_r": "0.4",
                    "mean_net_r": "0.05",
                },
            },
        },
        "trade_path_evidence": {
            "research_only": True,
            "durable_across_workers": True,
            "closed_path_count": 3,
            "staged_open_path_count": 1,
            "capture_error": None,
        },
        "profit_lock_execution_shadow": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "durable_state": True,
            "state_restored": True,
            "state_restore_error": None,
            "state_schema_version": 1,
            "fill_model": "visible_book_ioc_plus_actual_entry_fee_plus_funding_reserve",
            "eligible_open_positions": 1,
            "excluded_open_positions": 0,
            "excluded_closed_trades": 1,
            "closed_outcome_count": 2,
            "error": None,
            "readiness": {
                "all_rules_ready_for_review": False,
                "min_economically_evaluated_trades_per_rule": 30,
                "min_activated_trades_per_rule": 15,
                "min_triggered_trades_per_rule": 10,
                "min_simulated_full_closes_per_rule": 10,
                "promotion_authority": False,
                "execution_authority": False,
            },
            "rules": [
                {
                    "rule_id": "breakeven_after_0_5r",
                    "activate_at_r": "0.5",
                    "lock_at_r": "0",
                    "closed_eligible_trades": 2,
                    "economically_evaluated_trades": 2,
                    "activated_trades": 2,
                    "triggered_trades": 1,
                    "simulated_full_closes": 1,
                    "triggered_incomplete": 0,
                    "actual_positive_trades": 0,
                    "candidate_positive_trades_estimate": 1,
                    "actual_net_pnl": "-12",
                    "candidate_net_pnl_estimate": "3",
                    "delta_net_pnl_estimate": "15",
                    "actual_mean_net_r": "-0.6",
                    "candidate_mean_net_r_estimate": "0.15",
                    "delta_mean_net_r_estimate": "0.75",
                    "readiness_status": "collecting",
                    "missing_evaluated_trades": 28,
                    "missing_activated_trades": 13,
                    "missing_triggered_trades": 9,
                    "missing_simulated_full_closes": 9,
                }
            ],
        },
        "delayed_entry_execution_shadow": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "durable_state": True,
            "state_restored": True,
            "state_restore_error": None,
            "state_schema_version": 2,
            "started_at_ms": 1700000000000,
            "delay_ms": 60000,
            "max_observation_lag_ms": 60000,
            "stop_source": "persisted_opening_plan",
            "open_tracked_positions": 1,
            "eligible_open_positions": 1,
            "excluded_open_positions": 0,
            "closed_eligible_trades": 12,
            "full_delayed_fills": 8,
            "partial_delayed_fills": 1,
            "no_fills": 1,
            "rejections": 1,
            "expired": 1,
            "censored_before_delay": 0,
            "missing_delayed_book": 0,
            "better_price_full_fills": 5,
            "worse_price_full_fills": 3,
            "mean_signed_price_improvement_bps": "12.5",
            "mean_gross_r_improvement": "0.08",
            "excluded_closed_trades": 1,
            "lineage_mismatch_closed_trades": 0,
            "orphaned_restored_positions": 0,
            "readiness": {
                "ready_for_review": False,
                "min_closed_eligible_trades": 30,
                "min_full_delayed_fills": 20,
                "missing_closed_eligible_trades": 18,
                "missing_full_delayed_fills": 12,
            },
            "error": None,
        },
        "delayed_entry_120s_execution_shadow": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "durable_state": True,
            "state_restored": True,
            "state_restore_error": None,
            "state_schema_version": 2,
            "started_at_ms": 1700000500000,
            "delay_ms": 120000,
            "max_observation_lag_ms": 60000,
            "stop_source": "persisted_opening_plan",
            "open_tracked_positions": 1,
            "eligible_open_positions": 1,
            "excluded_open_positions": 0,
            "closed_eligible_trades": 10,
            "full_delayed_fills": 6,
            "partial_delayed_fills": 1,
            "no_fills": 1,
            "rejections": 1,
            "expired": 1,
            "censored_before_delay": 0,
            "missing_delayed_book": 0,
            "better_price_full_fills": 4,
            "worse_price_full_fills": 2,
            "mean_signed_price_improvement_bps": "18.5",
            "mean_gross_r_improvement": "0.11",
            "excluded_closed_trades": 0,
            "lineage_mismatch_closed_trades": 0,
            "orphaned_restored_positions": 0,
            "readiness": {
                "ready_for_review": False,
                "min_closed_eligible_trades": 30,
                "min_full_delayed_fills": 20,
                "missing_closed_eligible_trades": 20,
                "missing_full_delayed_fills": 14,
            },
            "error": None,
        },
        "delayed_entry_pair": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": "paired_same_exit_trade_contribution_only",
            "base_delay_ms": 60000,
            "challenger_delay_ms": 120000,
            "started_at_ms": 1700000500000,
            "prospective_closed_trades": 10,
            "paired_full_fills": 5,
            "missing_base_outcome": 0,
            "missing_challenger_outcome": 0,
            "non_full_base": 2,
            "non_full_challenger": 3,
            "lineage_mismatches": 0,
            "overall": {
                "trades": 5,
                "challenger_better": 3,
                "base_better": 2,
                "equal": 0,
                "base_same_exit_net_pnl": "-4",
                "challenger_same_exit_net_pnl": "1",
                "challenger_minus_base_pnl": "5",
                "mean_challenger_minus_base_r": "0.07",
                "mean_challenger_minus_base_bps": "6.5",
            },
            "by_side": {
                "long": {
                    "trades": 2,
                    "challenger_better": 1,
                    "base_better": 1,
                    "equal": 0,
                    "base_same_exit_net_pnl": "-2",
                    "challenger_same_exit_net_pnl": "-1",
                    "challenger_minus_base_pnl": "1",
                    "mean_challenger_minus_base_r": "0.02",
                    "mean_challenger_minus_base_bps": "2.5",
                },
                "short": {
                    "trades": 3,
                    "challenger_better": 2,
                    "base_better": 1,
                    "equal": 0,
                    "base_same_exit_net_pnl": "-2",
                    "challenger_same_exit_net_pnl": "2",
                    "challenger_minus_base_pnl": "4",
                    "mean_challenger_minus_base_r": "0.10",
                    "mean_challenger_minus_base_bps": "9.1",
                },
            },
            "readiness": {
                "ready_for_review": False,
                "min_prospective_closed_trades": 30,
                "min_paired_full_fills": 20,
                "min_long_paired_full_fills": 5,
                "min_short_paired_full_fills": 5,
                "missing_prospective_closed_trades": 20,
                "missing_paired_full_fills": 15,
                "missing_long_paired_full_fills": 3,
                "missing_short_paired_full_fills": 2,
            },
            "base_error": None,
            "challenger_error": None,
            "error": None,
        },
        "delayed_entry_pair_fill_weighted": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "paired_fill_weighted_same_exit_trade_contribution_only"
            ),
            "base_delay_ms": 60000,
            "challenger_delay_ms": 120000,
            "started_at_ms": 1700000500000,
            "prospective_closed_trades": 10,
            "paired_evaluable_attempts": 7,
            "missing_base_outcome": 0,
            "missing_challenger_outcome": 0,
            "non_evaluable_base": 1,
            "non_evaluable_challenger": 2,
            "lineage_mismatches": 0,
            "source_pairs": {
                "full_visible_book_ioc->full_visible_book_ioc": 4,
                "partial_visible_book_ioc->partial_visible_book_ioc": 2,
                "partial_visible_book_ioc->no_fill": 1,
            },
            "overall": {
                "trades": 7,
                "challenger_better": 3,
                "base_better": 4,
                "equal": 0,
                "actual_net_pnl": "-8",
                "base_fill_weighted_net_pnl": "2",
                "challenger_fill_weighted_net_pnl": "0.5",
                "challenger_minus_base_pnl": "-1.5",
                "mean_challenger_minus_base_r": "-0.03",
                "mean_base_fill_fraction": "0.8",
                "mean_challenger_fill_fraction": "0.65",
                "challenger_loses_fill_fraction": 3,
                "challenger_gains_fill_fraction": 1,
                "equal_fill_fraction": 3,
            },
            "by_side": {
                "long": {
                    "trades": 3,
                    "challenger_better": 1,
                    "base_better": 2,
                    "equal": 0,
                    "actual_net_pnl": "-5",
                    "base_fill_weighted_net_pnl": "0",
                    "challenger_fill_weighted_net_pnl": "-1",
                    "challenger_minus_base_pnl": "-1",
                    "mean_challenger_minus_base_r": "-0.04",
                    "mean_base_fill_fraction": "0.75",
                    "mean_challenger_fill_fraction": "0.5",
                    "challenger_loses_fill_fraction": 2,
                    "challenger_gains_fill_fraction": 0,
                    "equal_fill_fraction": 1,
                },
                "short": {
                    "trades": 4,
                    "challenger_better": 2,
                    "base_better": 2,
                    "equal": 0,
                    "actual_net_pnl": "-3",
                    "base_fill_weighted_net_pnl": "2",
                    "challenger_fill_weighted_net_pnl": "1.5",
                    "challenger_minus_base_pnl": "-0.5",
                    "mean_challenger_minus_base_r": "-0.02",
                    "mean_base_fill_fraction": "0.8375",
                    "mean_challenger_fill_fraction": "0.7625",
                    "challenger_loses_fill_fraction": 1,
                    "challenger_gains_fill_fraction": 1,
                    "equal_fill_fraction": 2,
                },
            },
            "readiness": {
                "ready_for_review": False,
                "min_prospective_closed_trades": 30,
                "min_paired_evaluable_attempts": 20,
                "min_long_paired_evaluable_attempts": 5,
                "min_short_paired_evaluable_attempts": 5,
                "missing_prospective_closed_trades": 20,
                "missing_paired_evaluable_attempts": 13,
                "missing_long_paired_evaluable_attempts": 2,
                "missing_short_paired_evaluable_attempts": 1,
            },
            "base_error": None,
            "challenger_error": None,
            "error": None,
        },
        "adaptive_delay_selector": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": "adverse-1m-mid-waits-to-120s-v1",
            "started_at_ms": 1700000600000,
            "state_restore_error": None,
            "error": None,
            "claim_scope": (
                "fill_weighted_same_exit_trade_contribution_only"
            ),
            "rule": (
                "if_fresh_1m_mid_gross_r_lt_0_choose_120s_"
                "else_choose_60s"
            ),
            "causality_rule": (
                "1m_mid_observed_at_or_before_60s_ioc_observation"
            ),
            "base_delay_ms": 60000,
            "challenger_delay_ms": 120000,
            "prospective_closed_trades": 8,
            "causal_evaluable_trades": 6,
            "missing_mid_outcome": 0,
            "non_fresh_mid_outcome": 1,
            "late_mid_signal": 1,
            "missing_base_outcome": 0,
            "missing_challenger_outcome": 0,
            "non_evaluable_base": 0,
            "non_evaluable_challenger": 0,
            "lineage_mismatches": 0,
            "overall": {
                "trades": 6,
                "selected_60s": 3,
                "selected_120s": 3,
                "adaptive_better_than_60s": 2,
                "adaptive_worse_than_60s": 1,
                "adaptive_equal_to_60s": 3,
                "adaptive_better_than_120s": 2,
                "adaptive_worse_than_120s": 1,
                "adaptive_equal_to_120s": 3,
                "actual_net_pnl": "-6",
                "always_60s_net_pnl": "-2",
                "always_120s_net_pnl": "-1",
                "adaptive_net_pnl": "1",
                "adaptive_minus_actual_pnl": "7",
                "adaptive_minus_60s_pnl": "3",
                "adaptive_minus_120s_pnl": "2",
                "mean_adaptive_fill_fraction": "0.9",
                "mean_adaptive_r_contribution": "0.02",
            },
            "by_side": {
                "long": {
                    "trades": 3,
                    "selected_60s": 1,
                    "selected_120s": 2,
                    "adaptive_net_pnl": "0.5",
                    "adaptive_minus_60s_pnl": "1.5",
                    "adaptive_minus_120s_pnl": "0.5",
                    "mean_adaptive_fill_fraction": "0.85",
                },
                "short": {
                    "trades": 3,
                    "selected_60s": 2,
                    "selected_120s": 1,
                    "adaptive_net_pnl": "0.5",
                    "adaptive_minus_60s_pnl": "1.5",
                    "adaptive_minus_120s_pnl": "1.5",
                    "mean_adaptive_fill_fraction": "0.95",
                },
            },
            "robustness": {
                "descriptive_only": True,
                "changes_readiness_gate": False,
                "adaptive_minus_60s": {
                    "trades": 6,
                    "markets": 4,
                    "total_delta_pnl": "3",
                    "largest_abs_trade_contribution": "1.2",
                    "largest_abs_trade_share": "0.30",
                    "leave_one_trade_out_min_delta": "1.8",
                    "positive_after_any_single_trade_removed": True,
                    "largest_abs_market": "SOL",
                    "largest_abs_market_contribution": "1.4",
                    "largest_abs_market_share": "0.35",
                    "leave_one_market_out_min_delta": "1.6",
                    "positive_after_any_single_market_removed": True,
                },
                "adaptive_minus_120s": {
                    "trades": 6,
                    "markets": 4,
                    "total_delta_pnl": "2",
                    "largest_abs_trade_contribution": "1.0",
                    "largest_abs_trade_share": "0.40",
                    "leave_one_trade_out_min_delta": "1.0",
                    "positive_after_any_single_trade_removed": True,
                    "largest_abs_market": "BTC",
                    "largest_abs_market_contribution": "1.1",
                    "largest_abs_market_share": "0.44",
                    "leave_one_market_out_min_delta": "0.9",
                    "positive_after_any_single_market_removed": True,
                },
            },
            "readiness": {
                "ready_for_review": False,
                "min_prospective_closed_trades": 30,
                "min_causal_evaluable_trades": 20,
                "min_selected_60s_trades": 5,
                "min_selected_120s_trades": 5,
                "missing_prospective_closed_trades": 22,
                "missing_causal_evaluable_trades": 14,
                "missing_selected_60s_trades": 2,
                "missing_selected_120s_trades": 2,
            },
        },
        "delayed_entry_same_exit": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": "same_exit_trade_contribution_only",
            "funding_assumption": "actual_trade_funding_held_constant",
            "exit_assumption": (
                "actual_trade_exit_price_and_exit_fee_held_constant"
            ),
            "closed_shadow_outcomes": 12,
            "full_delayed_fill_outcomes": 8,
            "evaluated_full_delayed_fills": 8,
            "missing_journal_trades": 0,
            "lineage_mismatches": 0,
            "overall": {
                "trades": 8,
                "actual_wins": 2,
                "actual_losses": 6,
                "candidate_wins_estimate": 4,
                "candidate_losses_estimate": 4,
                "loss_to_win_flips_estimate": 2,
                "win_to_loss_flips_estimate": 0,
                "actual_net_pnl": "-10",
                "candidate_net_pnl_estimate": "6",
                "delta_net_pnl_estimate": "16",
                "actual_mean_net_r": "-0.10",
                "candidate_mean_net_r_estimate": "0.06",
                "mean_delta_net_r_estimate": "0.16",
                "mean_gross_entry_improvement": "2.1",
                "mean_entry_fee_improvement": "-0.1",
            },
            "by_side": {
                "long": {
                    "trades": 3,
                    "actual_wins": 1,
                    "actual_losses": 2,
                    "candidate_wins_estimate": 2,
                    "candidate_losses_estimate": 1,
                    "loss_to_win_flips_estimate": 1,
                    "win_to_loss_flips_estimate": 0,
                    "actual_net_pnl": "-4",
                    "candidate_net_pnl_estimate": "2",
                    "delta_net_pnl_estimate": "6",
                    "actual_mean_net_r": "-0.12",
                    "candidate_mean_net_r_estimate": "0.05",
                    "mean_delta_net_r_estimate": "0.17",
                    "mean_gross_entry_improvement": "2.1",
                    "mean_entry_fee_improvement": "-0.1",
                },
                "short": {
                    "trades": 5,
                    "actual_wins": 1,
                    "actual_losses": 4,
                    "candidate_wins_estimate": 2,
                    "candidate_losses_estimate": 3,
                    "loss_to_win_flips_estimate": 1,
                    "win_to_loss_flips_estimate": 0,
                    "actual_net_pnl": "-6",
                    "candidate_net_pnl_estimate": "4",
                    "delta_net_pnl_estimate": "10",
                    "actual_mean_net_r": "-0.09",
                    "candidate_mean_net_r_estimate": "0.07",
                    "mean_delta_net_r_estimate": "0.16",
                    "mean_gross_entry_improvement": "2.1",
                    "mean_entry_fee_improvement": "-0.1",
                },
            },
            "readiness": {
                "ready_for_review": False,
                "min_closed_shadow_outcomes": 30,
                "min_full_delayed_fills": 20,
                "missing_closed_shadow_outcomes": 18,
                "missing_full_delayed_fills": 12,
            },
            "error": None,
        },
        "opening_scanner_rank": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "rank_definition": "latest_coarse_rank_before_open",
            "prospective_only": True,
            "evidence_records": 4,
            "attributed_closed_trades": 3,
            "closed_trades_without_rank_evidence": 10,
            "mean_rank_age_ms": 32000,
            "max_rank_age_ms": 58000,
            "capture_error": None,
            "error": None,
            "by_rank_bucket": {
                "1-5": {
                    "trades": 1,
                    "wins": 1,
                    "losses": 0,
                    "breakeven": 0,
                    "net_pnl": "5",
                    "mean_net_r": "0.5",
                },
                "11-20": {
                    "trades": 2,
                    "wins": 0,
                    "losses": 2,
                    "breakeven": 0,
                    "net_pnl": "-7",
                    "mean_net_r": "-0.35",
                },
            },
        },
        "opening_fill_liquidity": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "evidence_source": "exact_opening_ioc_l2_book",
            "evidence_records": 5,
            "attributed_closed_trades": 3,
            "closed_trades_without_fill_liquidity_evidence": 9,
            "unmatched_open_or_pending_records": 2,
            "review_gate_closed_trades": 30,
            "still_needed_closed_trades": 27,
            "ready_for_review": False,
            "capture_error": None,
            "error": None,
            "overall": {
                "trades": 3,
                "wins": 1,
                "losses": 2,
                "net_pnl": "-4",
                "mean_net_r": "-0.13",
                "mean_spread_bps": "3",
                "mean_fill_slippage_bps": "1.5",
                "mean_entry_depth_25bps": "100000",
                "mean_exit_depth_25bps": "90000",
                "mean_entry_depth_usage_fraction": "0.01",
                "mean_directional_book_imbalance": "-0.1",
                "mean_book_receive_age_ms": 12,
            },
            "winners": {
                "trades": 1,
                "wins": 1,
                "losses": 0,
                "net_pnl": "5",
                "mean_net_r": "0.5",
                "mean_spread_bps": "1",
                "mean_fill_slippage_bps": "0.5",
                "mean_entry_depth_25bps": "150000",
                "mean_exit_depth_25bps": "140000",
                "mean_entry_depth_usage_fraction": "0.005",
                "mean_directional_book_imbalance": "0.3",
                "mean_book_receive_age_ms": 5,
            },
            "losers": {
                "trades": 2,
                "wins": 0,
                "losses": 2,
                "net_pnl": "-9",
                "mean_net_r": "-0.45",
                "mean_spread_bps": "4",
                "mean_fill_slippage_bps": "2",
                "mean_entry_depth_25bps": "75000",
                "mean_exit_depth_25bps": "65000",
                "mean_entry_depth_usage_fraction": "0.02",
                "mean_directional_book_imbalance": "-0.3",
                "mean_book_receive_age_ms": 16,
            },
            "by_side": {
                "long": {
                    "trades": 2,
                    "wins": 1,
                    "losses": 1,
                    "net_pnl": "1",
                    "mean_net_r": "0.05",
                    "mean_spread_bps": "2",
                    "mean_fill_slippage_bps": "1",
                    "mean_entry_depth_25bps": "120000",
                    "mean_exit_depth_25bps": "110000",
                    "mean_entry_depth_usage_fraction": "0.01",
                    "mean_directional_book_imbalance": "0.1",
                    "mean_book_receive_age_ms": 10,
                },
                "short": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "net_pnl": "-5",
                    "mean_net_r": "-0.5",
                    "mean_spread_bps": "5",
                    "mean_fill_slippage_bps": "2.5",
                    "mean_entry_depth_25bps": "60000",
                    "mean_exit_depth_25bps": "50000",
                    "mean_entry_depth_usage_fraction": "0.03",
                    "mean_directional_book_imbalance": "-0.5",
                    "mean_book_receive_age_ms": 20,
                },
            },
        },
        "entry_markout_predictiveness": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": None,
            "definition": "early_markout_sign_vs_final_closed_trade_outcome",
            "complete_path_records": 4,
            "incomplete_paths_skipped": 0,
            "missing_journal_trade": 0,
            "max_observation_lag_ms": 60000,
            "all_horizons_ready_for_review": False,
            "by_horizon_ms": {
                "60000": {
                    "observations": 4,
                    "nonflat_observations": 4,
                    "sign_correct_final_outcomes": 2,
                    "sign_accuracy": "0.5",
                    "favorable": {
                        "trades": 2,
                        "wins": 1,
                        "losses": 1,
                        "flat": 0,
                        "win_rate": "0.5",
                        "net_pnl": "1",
                        "mean_final_net_r": "0.05",
                    },
                    "adverse": {
                        "trades": 2,
                        "wins": 1,
                        "losses": 1,
                        "flat": 0,
                        "win_rate": "0.5",
                        "net_pnl": "-3",
                        "mean_final_net_r": "-0.15",
                    },
                    "flat": {
                        "trades": 0,
                        "wins": 0,
                        "losses": 0,
                        "flat": 0,
                        "win_rate": None,
                        "net_pnl": "0",
                        "mean_final_net_r": None,
                    },
                    "censored_before_horizon": 0,
                    "stale_or_missing_mark": 0,
                    "readiness": {
                        "ready_for_review": False,
                        "min_observations": 30,
                        "min_favorable": 10,
                        "min_adverse": 10,
                        "missing_observations": 26,
                        "missing_favorable": 8,
                        "missing_adverse": 8,
                    },
                },
                "300000": {
                    "observations": 3,
                    "nonflat_observations": 3,
                    "sign_correct_final_outcomes": 2,
                    "sign_accuracy": "0.6666666666666666666666666667",
                    "favorable": {
                        "trades": 1,
                        "wins": 1,
                        "losses": 0,
                        "flat": 0,
                        "win_rate": "1",
                        "net_pnl": "5",
                        "mean_final_net_r": "0.5",
                    },
                    "adverse": {
                        "trades": 2,
                        "wins": 0,
                        "losses": 2,
                        "flat": 0,
                        "win_rate": "0",
                        "net_pnl": "-10",
                        "mean_final_net_r": "-0.5",
                    },
                    "flat": {
                        "trades": 0,
                        "wins": 0,
                        "losses": 0,
                        "flat": 0,
                        "win_rate": None,
                        "net_pnl": "0",
                        "mean_final_net_r": None,
                    },
                    "censored_before_horizon": 1,
                    "stale_or_missing_mark": 0,
                    "readiness": {
                        "ready_for_review": False,
                        "min_observations": 30,
                        "min_favorable": 10,
                        "min_adverse": 10,
                        "missing_observations": 27,
                        "missing_favorable": 9,
                        "missing_adverse": 8,
                    },
                },
                "900000": {
                    "observations": 2,
                    "nonflat_observations": 2,
                    "sign_correct_final_outcomes": 1,
                    "sign_accuracy": "0.5",
                    "favorable": {
                        "trades": 1,
                        "wins": 1,
                        "losses": 0,
                        "flat": 0,
                        "win_rate": "1",
                        "net_pnl": "5",
                        "mean_final_net_r": "0.5",
                    },
                    "adverse": {
                        "trades": 1,
                        "wins": 1,
                        "losses": 0,
                        "flat": 0,
                        "win_rate": "1",
                        "net_pnl": "3",
                        "mean_final_net_r": "0.3",
                    },
                    "flat": {
                        "trades": 0,
                        "wins": 0,
                        "losses": 0,
                        "flat": 0,
                        "win_rate": None,
                        "net_pnl": "0",
                        "mean_final_net_r": None,
                    },
                    "censored_before_horizon": 2,
                    "stale_or_missing_mark": 0,
                    "readiness": {
                        "ready_for_review": False,
                        "min_observations": 30,
                        "min_favorable": 10,
                        "min_adverse": 10,
                        "missing_observations": 28,
                        "missing_favorable": 9,
                        "missing_adverse": 9,
                    },
                },
            },
        },
        "entry_markout": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": None,
            "definition": (
                "first_observed_mark_at_or_after_horizon_within_max_lag"
            ),
            "max_observation_lag_ms": 60000,
            "horizons_ms": [60000, 300000, 900000],
            "readiness": {
                "all_horizons_ready_for_review": False,
                "min_observations_per_horizon": 30,
                "promotion_authority": False,
                "execution_authority": False,
            },
            "complete_path_records": 3,
            "incomplete_paths_skipped": 0,
            "missing_journal_trade": 0,
            "missing_decision_attribution": 0,
            "missing_rank_attribution": 0,
            "stale_rank_attribution": 0,
            "max_accepted_rank_age_ms": 300000,
            "mean_rank_age_ms": 32000,
            "max_rank_age_ms": 58000,
            "by_horizon_ms": {
                "60000": {
                    "readiness_status": "collecting",
                    "missing_observations": 27,
                    "observations": 3,
                    "positive": 2,
                    "negative": 1,
                    "flat": 0,
                    "mean_signed_return_bps": "25",
                    "mean_gross_r": "0.05",
                    "mean_observation_lag_ms": 1000,
                    "max_observation_lag_ms": 3000,
                    "censored_before_horizon": 0,
                    "missing_observed_mark": 0,
                    "stale_observed_mark": 0,
                    "by_side": {
                        "long": {
                            "observations": 2,
                            "positive": 1,
                            "negative": 1,
                            "flat": 0,
                            "mean_signed_return_bps": "-10",
                            "mean_gross_r": "-0.02",
                            "mean_observation_lag_ms": 1000,
                            "max_observation_lag_ms": 2000,
                        },
                        "short": {
                            "observations": 1,
                            "positive": 1,
                            "negative": 0,
                            "flat": 0,
                            "mean_signed_return_bps": "95",
                            "mean_gross_r": "0.19",
                            "mean_observation_lag_ms": 1000,
                            "max_observation_lag_ms": 1000,
                        },
                    },
                    "by_lead_strategy": {
                        "trend": {
                            "observations": 2,
                            "positive": 1,
                            "negative": 1,
                            "flat": 0,
                            "mean_signed_return_bps": "-10",
                            "mean_gross_r": "-0.02",
                            "mean_observation_lag_ms": 1000,
                            "max_observation_lag_ms": 2000,
                        },
                        "breakout": {
                            "observations": 1,
                            "positive": 1,
                            "negative": 0,
                            "flat": 0,
                            "mean_signed_return_bps": "95",
                            "mean_gross_r": "0.19",
                            "mean_observation_lag_ms": 1000,
                            "max_observation_lag_ms": 1000,
                        },
                    },
                    "by_decision_age_bucket": {
                        "<1s": {
                            "observations": 1,
                            "positive": 1,
                            "negative": 0,
                            "flat": 0,
                            "mean_signed_return_bps": "95",
                            "mean_gross_r": "0.19",
                            "mean_observation_lag_ms": 1000,
                            "max_observation_lag_ms": 1000,
                        },
                        "5-<15s": {
                            "observations": 2,
                            "positive": 1,
                            "negative": 1,
                            "flat": 0,
                            "mean_signed_return_bps": "-10",
                            "mean_gross_r": "-0.02",
                            "mean_observation_lag_ms": 1000,
                            "max_observation_lag_ms": 2000,
                        },
                    },
                    "by_scanner_rank_bucket": {
                        "1-5": {
                            "observations": 1,
                            "positive": 1,
                            "negative": 0,
                            "flat": 0,
                            "mean_signed_return_bps": "95",
                            "mean_gross_r": "0.19",
                            "mean_observation_lag_ms": 1000,
                            "max_observation_lag_ms": 1000,
                        },
                        "11-20": {
                            "observations": 2,
                            "positive": 1,
                            "negative": 1,
                            "flat": 0,
                            "mean_signed_return_bps": "-10",
                            "mean_gross_r": "-0.02",
                            "mean_observation_lag_ms": 1000,
                            "max_observation_lag_ms": 2000,
                        },
                    },
                },
                "300000": {
                    "readiness_status": "collecting",
                    "missing_observations": 28,
                    "observations": 2,
                    "positive": 1,
                    "negative": 1,
                    "flat": 0,
                    "mean_signed_return_bps": "-10",
                    "mean_gross_r": "-0.02",
                    "mean_observation_lag_ms": 1500,
                    "max_observation_lag_ms": 2500,
                    "censored_before_horizon": 1,
                    "missing_observed_mark": 0,
                    "stale_observed_mark": 0,
                    "by_side": {},
                    "by_lead_strategy": {},
                    "by_scanner_rank_bucket": {},
                    "by_decision_age_bucket": {},
                },
                "900000": {
                    "readiness_status": "collecting",
                    "missing_observations": 29,
                    "observations": 1,
                    "positive": 1,
                    "negative": 0,
                    "flat": 0,
                    "mean_signed_return_bps": "80",
                    "mean_gross_r": "0.16",
                    "mean_observation_lag_ms": 500,
                    "max_observation_lag_ms": 500,
                    "censored_before_horizon": 2,
                    "missing_observed_mark": 0,
                    "stale_observed_mark": 0,
                    "by_side": {},
                    "by_lead_strategy": {},
                    "by_scanner_rank_bucket": {},
                    "by_decision_age_bucket": {},
                },
            },
        },
        "entry_mid_markout_shadow": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "durable_state": True,
            "state_restored": True,
            "state_restore_error": None,
            "state_schema_version": 1,
            "started_at_ms": 1_699_999_500_000,
            "source": "allMids_mid_px",
            "horizons_ms": [60000, 300000, 900000],
            "max_observation_lag_ms": 60000,
            "eligible_open_positions": 1,
            "excluded_open_positions": 0,
            "excluded_closed_trades": 0,
            "unmatched_closed_trades": 0,
            "closed_trade_count": 3,
            "error": None,
            "readiness": {
                "all_horizons_ready_for_review": False,
                "min_fresh_observations_per_horizon": 30,
                "max_non_fresh_fraction": "0.10",
                "unmatched_closed_trades": 0,
                "promotion_authority": False,
                "execution_authority": False,
            },
            "by_horizon_ms": {
                "60000": {
                    "horizon_ms": 60000,
                    "readiness_status": "collecting",
                    "missing_fresh_observations": 27,
                    "non_fresh_fraction": "0",
                    "coverage_quality_ready": True,
                    "observations": 3,
                    "fresh": 3,
                    "stale": 0,
                    "censored": 0,
                    "missing_at_close": 0,
                    "positive": 2,
                    "negative": 1,
                    "flat": 0,
                    "mean_signed_return_bps": "30",
                    "mean_gross_r": "0.06",
                    "mean_observation_lag_ms": 800,
                    "max_observation_lag_ms": 1400,
                    "decision_attribution_misses": 0,
                    "by_side": {
                        "long": {
                            "observations": 2,
                            "positive": 1,
                            "negative": 1,
                            "flat": 0,
                            "mean_signed_return_bps": "-5",
                            "mean_gross_r": "-0.01",
                            "mean_observation_lag_ms": 900,
                            "max_observation_lag_ms": 1400,
                        },
                        "short": {
                            "observations": 1,
                            "positive": 1,
                            "negative": 0,
                            "flat": 0,
                            "mean_signed_return_bps": "100",
                            "mean_gross_r": "0.2",
                            "mean_observation_lag_ms": 600,
                            "max_observation_lag_ms": 600,
                        },
                    },
                    "by_lead_strategy": {
                        "trend": {
                            "observations": 2,
                            "positive": 1,
                            "negative": 1,
                            "flat": 0,
                            "mean_signed_return_bps": "-5",
                            "mean_gross_r": "-0.01",
                            "mean_observation_lag_ms": 900,
                            "max_observation_lag_ms": 1400,
                        },
                        "breakout": {
                            "observations": 1,
                            "positive": 1,
                            "negative": 0,
                            "flat": 0,
                            "mean_signed_return_bps": "100",
                            "mean_gross_r": "0.2",
                            "mean_observation_lag_ms": 600,
                            "max_observation_lag_ms": 600,
                        },
                    },
                },
                "300000": {
                    "horizon_ms": 300000,
                    "readiness_status": "collecting",
                    "missing_fresh_observations": 28,
                    "non_fresh_fraction": "0.3333333333333333333333333333",
                    "coverage_quality_ready": False,
                    "observations": 2,
                    "fresh": 2,
                    "stale": 1,
                    "censored": 0,
                    "missing_at_close": 0,
                    "positive": 1,
                    "negative": 1,
                    "flat": 0,
                    "mean_signed_return_bps": "20",
                    "mean_gross_r": "0.04",
                    "mean_observation_lag_ms": 1000,
                    "max_observation_lag_ms": 1600,
                    "decision_attribution_misses": 0,
                    "by_side": {},
                    "by_lead_strategy": {},
                },
                "900000": {
                    "horizon_ms": 900000,
                    "readiness_status": "collecting",
                    "missing_fresh_observations": 29,
                    "non_fresh_fraction": "0",
                    "coverage_quality_ready": True,
                    "observations": 1,
                    "fresh": 1,
                    "stale": 0,
                    "censored": 2,
                    "missing_at_close": 0,
                    "positive": 1,
                    "negative": 0,
                    "flat": 0,
                    "mean_signed_return_bps": "50",
                    "mean_gross_r": "0.1",
                    "mean_observation_lag_ms": 500,
                    "max_observation_lag_ms": 500,
                    "decision_attribution_misses": 0,
                    "by_side": {},
                    "by_lead_strategy": {},
                },
            },
        },
        "prospective_delayed_price_confirmation": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": "prospective-60s-price-confirm-v1",
            "started_at_ms": 1_700_000_000_000,
            "state_restore_error": None,
            "error": None,
            "claim_scope": "closed_trade_contribution_only",
            "portfolio_counterfactual": False,
            "rule": {
                "delay_ms": 60000,
                "minimum_signed_improvement_bps": "0",
                "on_pass": "take_delayed_visible_book_ioc",
                "on_fail": "skip_trade_contribution",
            },
            "prospective_closed_trades": 12,
            "evaluated_trades": 10,
            "confirmed_trades": 6,
            "skipped_trades": 4,
            "no_fill_skips": 1,
            "worse_price_skips": 3,
            "missing_outcomes": 0,
            "missing_opening_plans": 0,
            "lineage_mismatches": 0,
            "unresolved_outcomes": 2,
            "actual_net_pnl": "-18",
            "candidate_trade_contribution_pnl": "-9",
            "delta_trade_contribution_pnl": "9",
            "mean_confirmed_signed_improvement_bps": "18",
            "readiness": {
                "ready_for_review": False,
                "min_prospective_evaluated_trades": 30,
                "min_confirmed_trades": 10,
                "min_skipped_trades": 10,
                "missing_prospective_evaluated_trades": 20,
                "missing_confirmed_trades": 4,
                "missing_skipped_trades": 6,
            },
        },
        "prospective_top10_rank_filter": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": "prospective-admit-top10-rank-v1",
            "started_at_ms": 1_699_999_600_000,
            "state_restore_error": None,
            "error": None,
            "rule": {
                "max_admitted_ordinal": 10,
                "action_above_threshold": "reject",
                "max_rank_age_ms": 300000,
            },
            "claim_scope": "closed_trade_contribution_only",
            "portfolio_counterfactual": False,
            "prospective_closed_trades": 12,
            "attributed_trades": 11,
            "missing_rank_evidence": 1,
            "stale_rank_evidence": 0,
            "allowed_trades": 6,
            "blocked_trades": 5,
            "allowed_wins": 3,
            "allowed_losses": 3,
            "blocked_wins": 0,
            "blocked_losses": 5,
            "allowed_net_pnl": "20",
            "blocked_net_pnl": "-30",
            "actual_net_pnl": "-10",
            "candidate_trade_contribution_pnl": "20",
            "delta_trade_contribution_pnl": "30",
            "actual_mean_net_r": "-0.08",
            "allowed_mean_net_r": "0.25",
            "blocked_mean_net_r": "-0.5",
            "allowed_mean_ordinal": "6.5",
            "blocked_mean_ordinal": "15",
            "mean_rank_age_ms": 32000,
            "max_rank_age_ms": 58000,
            "readiness": {
                "ready_for_review": False,
                "min_prospective_closed_trades": 30,
                "min_blocked_trades": 10,
                "min_allowed_trades": 10,
                "missing_prospective_closed_trades": 18,
                "missing_blocked_trades": 5,
                "missing_allowed_trades": 4,
                "requires_zero_missing_rank_evidence": True,
                "requires_zero_stale_rank_evidence": True,
            },
        },
        "excursion_timing": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": None,
            "complete_paths_evaluated": 12,
            "incomplete_paths_skipped": 2,
            "missing_journal_trade": 0,
            "missing_decision_attribution": 0,
            "missing_excursion_metric": 0,
            "evidence_gate": {
                "min_complete_paths": 30,
                "missing_complete_paths": 18,
                "ready_for_review": False,
            },
            "overall": {
                "trades": 12,
                "wins": 4,
                "losses": 8,
                "mean_time_to_mfe_ms": 240000,
                "median_time_to_mfe_ms": 180000,
                "mean_time_to_mae_ms": 150000,
                "mean_peak_to_close_ms": 420000,
                "median_peak_to_close_ms": 360000,
                "mean_peak_to_close_fraction_of_hold": "0.42",
                "thresholds": {
                    "0.25": {
                        "reached": 9,
                        "reach_fraction": "0.75",
                        "mean_first_hit_ms": 90000,
                        "median_first_hit_ms": 60000,
                        "losing_closes_after_reach": 5,
                        "mean_reach_to_close_ms_for_losers": 600000,
                    },
                    "0.5": {
                        "reached": 7,
                        "reach_fraction": "0.5833333333333333333333333333",
                        "mean_first_hit_ms": 150000,
                        "median_first_hit_ms": 120000,
                        "losing_closes_after_reach": 4,
                        "mean_reach_to_close_ms_for_losers": 540000,
                    },
                    "1": {
                        "reached": 5,
                        "reach_fraction": "0.4166666666666666666666666667",
                        "mean_first_hit_ms": 300000,
                        "median_first_hit_ms": 240000,
                        "losing_closes_after_reach": 3,
                        "mean_reach_to_close_ms_for_losers": 480000,
                    },
                },
            },
            "by_side": {
                "long": {
                    "trades": 7,
                    "mean_time_to_mfe_ms": 210000,
                    "mean_peak_to_close_ms": 390000,
                    "thresholds": {
                        "0.5": {"reached": 4},
                        "1": {"reached": 3},
                    },
                },
                "short": {
                    "trades": 5,
                    "mean_time_to_mfe_ms": 282000,
                    "mean_peak_to_close_ms": 462000,
                    "thresholds": {
                        "0.5": {"reached": 3},
                        "1": {"reached": 2},
                    },
                },
            },
            "by_lead_strategy": {
                "trend": {
                    "trades": 9,
                    "mean_time_to_mfe_ms": 260000,
                    "mean_peak_to_close_ms": 450000,
                    "thresholds": {
                        "0.5": {"reached": 5},
                        "1": {"reached": 3},
                    },
                }
            },
            "by_exit_reason": {
                "MARK_STOP_TRIGGERED": {
                    "trades": 8,
                    "mean_time_to_mfe_ms": 230000,
                    "mean_peak_to_close_ms": 500000,
                    "thresholds": {
                        "0.5": {"reached": 5},
                        "1": {"reached": 4},
                    },
                }
            },
        },
        "delayed_entry_fill_capacity": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "evaluated_attempts": 10,
            "missing_journal_trades": 0,
            "lineage_mismatches": 0,
            "overall": {
                "attempts": 10,
                "mean_fill_fraction": "0.85",
                "full": 8,
                "partial": 1,
                "no_fill": 1,
            },
            "by_side": {
                "long": {
                    "attempts": 4,
                    "mean_fill_fraction": "0.75",
                    "full": 3,
                    "partial": 1,
                    "no_fill": 0,
                },
                "short": {
                    "attempts": 6,
                    "mean_fill_fraction": "0.9166666666666666666666666667",
                    "full": 5,
                    "partial": 0,
                    "no_fill": 1,
                },
            },
            "by_cause": {
                "legacy_unknown_partial": {
                    "attempts": 1,
                    "mean_fill_fraction": "0.5",
                    "full": 0,
                    "partial": 1,
                    "no_fill": 0,
                },
                "visible_depth_exhausted": {
                    "attempts": 1,
                    "mean_fill_fraction": "0.7",
                    "full": 0,
                    "partial": 1,
                    "no_fill": 0,
                },
                "slippage_boundary_reached": {
                    "attempts": 1,
                    "mean_fill_fraction": "0.8",
                    "full": 0,
                    "partial": 1,
                    "no_fill": 0,
                },
                "full_fill": {
                    "attempts": 8,
                    "mean_fill_fraction": "1",
                    "full": 8,
                    "partial": 0,
                    "no_fill": 0,
                },
                "no_fill": {
                    "attempts": 1,
                    "mean_fill_fraction": "0",
                    "full": 0,
                    "partial": 0,
                    "no_fill": 1,
                },
            },
            "cause_known_partial_fills": 0,
            "legacy_unknown_partial_fills": 1,
            "readiness": {
                "ready_for_review": False,
                "min_evaluated_attempts": 30,
                "min_cause_known_partial_fills": 10,
                "missing_evaluated_attempts": 20,
                "missing_cause_known_partial_fills": 10,
            },
            "open_attempts": {
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "attempted_open_positions": 1,
                "rows": [
                    {
                        "opening_plan_id": "open-live-1",
                        "market": "SOL",
                        "side": "long",
                        "attempted_at_ms": 1700000060300,
                        "result": "partial",
                        "attempt_reason": "IOC_REMAINDER_CANCELLED",
                        "capacity_cause": "slippage_boundary_reached",
                        "requested_quantity": "2",
                        "filled_quantity": "1",
                        "fill_fraction": "0.5",
                        "observation_lag_ms": 300,
                    }
                ],
            },
            "error": None,
        },
        "delayed_entry_fill_weighted": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": "fill_weighted_same_exit_trade_contribution_only",
            "exit_assumption": (
                "actual_exit_price_with_exit_fee_scaled_by_fill_fraction"
            ),
            "funding_assumption": (
                "actual_trade_funding_scaled_by_fill_fraction"
            ),
            "unfilled_assumption": (
                "unfilled_quantity_contributes_zero_and_is_not_replaced"
            ),
            "closed_shadow_outcomes": 12,
            "evaluated_delayed_attempts": 10,
            "missing_journal_trades": 0,
            "lineage_mismatches": 0,
            "source_counts": {
                "full_visible_book_ioc": 8,
                "partial_visible_book_ioc": 1,
                "no_fill": 1,
                "censored_before_delay": 0,
                "missing_delayed_book": 0,
                "rejected": 1,
                "expired": 1,
            },
            "overall": {
                "trades": 10,
                "actual_wins": 3,
                "actual_losses": 7,
                "candidate_positive_contributions": 4,
                "candidate_negative_contributions": 4,
                "candidate_zero_contributions": 2,
                "candidate_better_than_actual": 6,
                "candidate_worse_than_actual": 4,
                "candidate_equal_to_actual": 0,
                "actual_win_to_nonpositive_contribution": 1,
                "actual_loss_to_nonnegative_contribution": 3,
                "actual_net_pnl": "-12",
                "candidate_fill_weighted_net_pnl": "4",
                "delta_net_pnl_estimate": "16",
                "actual_mean_net_r": "-0.2",
                "candidate_mean_r_contribution": "0.05",
                "mean_delta_r_contribution": "0.25",
                "mean_fill_fraction": "0.85",
            },
            "by_side": {
                "long": {
                    "trades": 4,
                    "actual_net_pnl": "-5",
                    "candidate_fill_weighted_net_pnl": "-1",
                    "delta_net_pnl_estimate": "4",
                    "mean_delta_r_contribution": "0.1",
                    "mean_fill_fraction": "0.75",
                },
                "short": {
                    "trades": 6,
                    "actual_net_pnl": "-7",
                    "candidate_fill_weighted_net_pnl": "5",
                    "delta_net_pnl_estimate": "12",
                    "mean_delta_r_contribution": "0.35",
                    "mean_fill_fraction": "0.9166666666666666666666666667",
                },
            },
            "by_source": {
                "full_visible_book_ioc": {
                    "trades": 8,
                    "actual_net_pnl": "-10",
                    "candidate_fill_weighted_net_pnl": "3",
                    "delta_net_pnl_estimate": "13",
                    "mean_delta_r_contribution": "0.2",
                    "mean_fill_fraction": "1",
                },
                "partial_visible_book_ioc": {
                    "trades": 1,
                    "actual_net_pnl": "2",
                    "candidate_fill_weighted_net_pnl": "1",
                    "delta_net_pnl_estimate": "-1",
                    "mean_delta_r_contribution": "-0.1",
                    "mean_fill_fraction": "0.5",
                },
                "no_fill": {
                    "trades": 1,
                    "actual_net_pnl": "-4",
                    "candidate_fill_weighted_net_pnl": "0",
                    "delta_net_pnl_estimate": "4",
                    "mean_delta_r_contribution": "0.4",
                    "mean_fill_fraction": "0",
                },
            },
            "readiness": {
                "ready_for_review": False,
                "min_closed_shadow_outcomes": 30,
                "min_evaluated_delayed_attempts": 20,
                "missing_closed_shadow_outcomes": 18,
                "missing_evaluated_delayed_attempts": 10,
            },
            "error": None,
        },
        "delayed_entry_contribution_decomposition": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "fill_weighted_same_exit_delta_decomposition"
            ),
            "identity": (
                "price_effect + entry_fee_effect + "
                "exposure_effect = total_delta"
            ),
            "closed_shadow_outcomes": 12,
            "evaluated_delayed_attempts": 10,
            "missing_journal_trades": 0,
            "lineage_mismatches": 0,
            "overall": {
                "trades": 10,
                "mean_fill_fraction": "0.85",
                "price_effect_pnl": "14",
                "entry_fee_effect_pnl": "1.2",
                "exposure_effect_pnl": "0.8",
                "total_delta_pnl": "16",
                "mean_price_effect_r": "0.20",
                "mean_entry_fee_effect_r": "0.02",
                "mean_exposure_effect_r": "0.03",
                "mean_total_delta_r": "0.25",
                "price_benefit_positive": 8,
                "price_benefit_negative": 1,
                "exposure_effect_positive": 4,
                "exposure_effect_negative": 3,
            },
            "by_side": {
                "long": {
                    "trades": 4,
                    "mean_fill_fraction": "0.75",
                    "price_effect_pnl": "4",
                    "entry_fee_effect_pnl": "0.4",
                    "exposure_effect_pnl": "-0.4",
                    "total_delta_pnl": "4",
                    "mean_total_delta_r": "0.1",
                },
                "short": {
                    "trades": 6,
                    "mean_fill_fraction": "0.9166666666666666666666666667",
                    "price_effect_pnl": "10",
                    "entry_fee_effect_pnl": "0.8",
                    "exposure_effect_pnl": "1.2",
                    "total_delta_pnl": "12",
                    "mean_total_delta_r": "0.35",
                },
            },
            "by_source": {
                "full_visible_book_ioc": {
                    "trades": 8,
                    "mean_fill_fraction": "1",
                    "price_effect_pnl": "12",
                    "entry_fee_effect_pnl": "1",
                    "exposure_effect_pnl": "0",
                    "total_delta_pnl": "13",
                    "mean_total_delta_r": "0.2",
                },
                "partial_visible_book_ioc": {
                    "trades": 1,
                    "mean_fill_fraction": "0.5",
                    "price_effect_pnl": "2",
                    "entry_fee_effect_pnl": "0.2",
                    "exposure_effect_pnl": "-3.2",
                    "total_delta_pnl": "-1",
                    "mean_total_delta_r": "-0.1",
                },
                "no_fill": {
                    "trades": 1,
                    "mean_fill_fraction": "0",
                    "price_effect_pnl": "0",
                    "entry_fee_effect_pnl": "0",
                    "exposure_effect_pnl": "4",
                    "total_delta_pnl": "4",
                    "mean_total_delta_r": "0.4",
                },
            },
            "by_capacity_cause": {
                "full_fill": {
                    "trades": 8,
                    "mean_fill_fraction": "1",
                    "price_effect_pnl": "12",
                    "entry_fee_effect_pnl": "1",
                    "exposure_effect_pnl": "0",
                    "total_delta_pnl": "13",
                    "mean_total_delta_r": "0.2",
                },
                "risk_ceiling_clip": {
                    "trades": 1,
                    "mean_fill_fraction": "0.5",
                    "price_effect_pnl": "2",
                    "entry_fee_effect_pnl": "0.2",
                    "exposure_effect_pnl": "-3.2",
                    "total_delta_pnl": "-1",
                    "mean_total_delta_r": "-0.1",
                },
                "no_fill": {
                    "trades": 1,
                    "mean_fill_fraction": "0",
                    "price_effect_pnl": "0",
                    "entry_fee_effect_pnl": "0",
                    "exposure_effect_pnl": "4",
                    "total_delta_pnl": "4",
                    "mean_total_delta_r": "0.4",
                },
            },
            "readiness": {
                "ready_for_review": False,
                "min_closed_shadow_outcomes": 30,
                "min_evaluated_delayed_attempts": 20,
                "missing_closed_shadow_outcomes": 18,
                "missing_evaluated_delayed_attempts": 10,
            },
            "error": None,
        },
        "delayed_entry_risk_geometry": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "definition": "delayed_average_fill_risk_vs_actual_position_risk",
            "evaluated_filled_attempts": 10,
            "no_fill_outcomes": 1,
            "missing_journal_trades": 0,
            "missing_opening_plans": 0,
            "lineage_mismatches": 0,
            "missing_delayed_fill_price": 0,
            "overall": {
                "attempts": 10,
                "mean_fill_fraction": "0.85",
                "mean_risk_utilization": "0.82",
                "mean_full_size_risk_ratio": "0.94",
                "mean_risk_capacity_fraction": "0.96",
                "mean_unit_risk_change_fraction": "-0.04",
                "risk_clipped": 2,
                "full_size_risk_above_ceiling": 2,
            },
            "risk_clipped": {
                "attempts": 2,
                "mean_fill_fraction": "0.70",
                "mean_risk_utilization": "0.99",
                "mean_full_size_risk_ratio": "1.18",
                "mean_risk_capacity_fraction": "0.85",
                "mean_unit_risk_change_fraction": "0.18",
                "risk_clipped": 2,
                "full_size_risk_above_ceiling": 2,
            },
            "by_side": {
                "long": {
                    "attempts": 4,
                    "mean_fill_fraction": "0.75",
                    "mean_risk_utilization": "0.90",
                    "mean_full_size_risk_ratio": "1.05",
                    "mean_risk_capacity_fraction": "0.91",
                    "mean_unit_risk_change_fraction": "0.05",
                    "risk_clipped": 2,
                    "full_size_risk_above_ceiling": 2,
                },
                "short": {
                    "attempts": 6,
                    "mean_fill_fraction": "0.9166666667",
                    "mean_risk_utilization": "0.77",
                    "mean_full_size_risk_ratio": "0.87",
                    "mean_risk_capacity_fraction": "1",
                    "mean_unit_risk_change_fraction": "-0.10",
                    "risk_clipped": 0,
                    "full_size_risk_above_ceiling": 0,
                },
            },
            "by_cause": {
                "full_fill": {
                    "attempts": 8,
                    "mean_fill_fraction": "1",
                    "mean_risk_utilization": "0.78",
                    "mean_full_size_risk_ratio": "0.78",
                    "mean_risk_capacity_fraction": "1",
                    "mean_unit_risk_change_fraction": "-0.08",
                    "risk_clipped": 0,
                    "full_size_risk_above_ceiling": 0,
                },
                "risk_ceiling_clip": {
                    "attempts": 2,
                    "mean_fill_fraction": "0.70",
                    "mean_risk_utilization": "0.99",
                    "mean_full_size_risk_ratio": "1.18",
                    "mean_risk_capacity_fraction": "0.85",
                    "mean_unit_risk_change_fraction": "0.18",
                    "risk_clipped": 2,
                    "full_size_risk_above_ceiling": 2,
                },
            },
            "readiness": {
                "ready_for_review": False,
                "min_evaluated_filled_attempts": 20,
                "min_risk_clipped_attempts": 5,
                "missing_evaluated_filled_attempts": 10,
                "missing_risk_clipped_attempts": 3,
            },
            "error": None,
        },
        "prospective_entry_filter": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": "prospective-reject-long-trend-v1",
            "started_at_ms": 1_699_999_500_000,
            "state_restore_error": None,
            "error": None,
            "rule": {
                "direction": "long",
                "lead_strategy": "trend",
                "action": "reject",
            },
            "claim_scope": "closed_trade_contribution_only",
            "portfolio_counterfactual": False,
            "prospective_closed_trades": 12,
            "attributed_trades": 12,
            "attribution_misses": 0,
            "allowed_trades": 7,
            "blocked_trades": 5,
            "blocked_wins": 0,
            "blocked_losses": 5,
            "blocked_net_pnl": "-30",
            "allowed_net_pnl": "18",
            "actual_net_pnl": "-12",
            "candidate_trade_contribution_pnl": "18",
            "delta_trade_contribution_pnl": "30",
            "actual_mean_net_r": "-0.1",
            "candidate_mean_net_r_contribution": "0.15",
            "readiness": {
                "ready_for_review": False,
                "min_prospective_closed_trades": 30,
                "min_blocked_trades": 10,
                "min_allowed_trades": 10,
                "missing_prospective_closed_trades": 18,
                "missing_blocked_trades": 5,
                "missing_allowed_trades": 3,
            },
        },
        "profit_lock_counterfactual": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "error": None,
            "evidence_class": "research_only_mark_path_counterfactual",
            "fill_model": "first_crossing_mark_minus_frozen_cost_reserve",
            "path_record_count": 3,
            "evaluated_trade_count": 2,
            "skipped_incomplete_paths": 1,
            "readiness": {
                "all_rules_ready_for_review": False,
                "min_complete_paths": 30,
                "min_activated_trades_per_rule": 15,
                "min_triggered_trades_per_rule": 10,
            },
            "rules": [
                {
                    "rule_id": "lock_0_5r_after_1r",
                    "activate_at_r": "1",
                    "lock_at_r": "0.5",
                    "evaluated_trades": 2,
                    "activated_trades": 2,
                    "triggered_trades": 1,
                    "actual_positive_trades": 0,
                    "candidate_positive_trades_estimate": 1,
                    "actual_net_pnl": "-12",
                    "candidate_net_pnl_estimate": "4",
                    "delta_net_pnl_estimate": "16",
                    "actual_mean_net_r": "-0.6",
                    "candidate_mean_net_r_estimate": "0.2",
                    "delta_mean_net_r_estimate": "0.8",
                    "readiness_status": "collecting",
                    "missing_complete_paths": 28,
                    "missing_activated_trades": 13,
                    "missing_triggered_trades": 9,
                }
            ],
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
                "current_gross_r": "0.2",
                "stop_trigger_gross_pnl": "4",
                "stop_trigger_gross_r": "0.4",
                "stop_protects_profit": True,
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
    assert "stop-trigger gross PnL at current stops" in output
    assert "stop-trigger gross R / planned risk" in output
    assert "positions with profit-protecting stop" in output
    assert "Current R" in output
    assert "Stop-lock PnL" in output
    assert "Stop-lock R" in output
    assert "| BTC | long | 0.01 | 65000 | 64000 | 65200 | 2 | 0.2 | 4 | 0.4 | yes | 10 |" in output
    assert "gross open notional" in output
    assert "### Research readiness board" in output
    assert "OBSERVABILITY ONLY" in output
    assert (
        "| fixed profit-lock | collecting | paths=2/3 | skipped=1 |"
        in output
    )
    assert (
        "| IOC profit-lock | collecting | closed=2 | "
        "mismatch=0, orphan=0 |" in output
    )
    assert (
        "| 60s delayed entry | collecting | "
        "closed=12, full=8, better=5, worse=3 | "
        "mismatch=0, orphan=0 |" in output
    )
    assert (
        "| LONG+trend filter | collecting | "
        "closed=12, blocked=5, allowed=7 | misses=0 |" in output
    )
    assert (
        "| top-10 rank filter | collecting | "
        "closed=12, blocked=5, allowed=6 | missing=1, stale=0 |"
        in output
    )
    assert (
        "| exact-path entry markout | collecting | "
        "1m/5m/15m=3/2/1 | decision_miss=0, rank_miss=0 |"
        in output
    )
    assert (
        "| allMids entry markout | collecting | "
        "fresh 1m/5m/15m=3/2/1 | "
        "unmatched=0, mismatch=0, orphan=0 |" in output
    )
    assert (
        "| decision age at fill | collecting | "
        "attributed=4, need=26 | misses=0 |" in output
    )
    assert (
        "| excursion timing | collecting | paths=12, need=18 | "
        "decision_miss=0, excursion_miss=0 |" in output
    )
    assert (
        "| closed-trade stability | collecting | closed=20, need=20 | "
        "full_blocks=0, all_pnl_positive=false |" in output
    )
    assert "| opening fill liquidity | collecting | closed=3, need=27 |" in output
    assert "review-ready studies: `0 / " in output
    assert "| 60s price confirmation | collecting | eval=10, confirmed=6, skipped=4 |" in output
    assert "### Trade-path evidence" in output
    assert "completed exact trade paths" in output
    assert "staged open trade paths" in output
    assert "`3`" in output
    assert "`1`" in output
    assert "### Fixed profit-lock counterfactual" in output
    assert "### 60s delayed-entry execution shadow" in output
    assert "prospective start / state schema" in output
    assert "`1700000000000` / `v2`" in output
    assert "frozen delay / max observation lag" in output
    assert "`60000ms / 60000ms`" in output
    assert "stop source" in output
    assert "`persisted_opening_plan`" in output
    assert "closed eligible / excluded closes" in output
    assert "`12 / 1`" in output
    assert "full / partial / no-fill / rejected / expired" in output
    assert "`8 / 1 / 1 / 1 / 1`" in output
    assert "better / worse price among full delayed fills" in output
    assert "`5 / 3`" in output
    assert "mean signed price improvement / gross-R improvement" in output
    assert "`12.5` bps / `0.08` R" in output
    assert "### 120s delayed-entry execution shadow" in output
    assert "`120000ms / 60000ms`" in output
    assert "`18.5` bps / `0.11` R" in output
    assert "### Paired 60s vs 120s delayed-entry study" in output
    assert "paired_same_exit_trade_contribution_only" in output
    assert "120s better / 60s better / equal" in output
    assert "`3 / 2 / 0`" in output
    assert "60s / 120s same-exit PnL / incremental" in output
    assert "`-4` / `1` / `5`" in output
    assert "evidence gate closed / paired / LONG / SHORT" in output
    assert "`30 / 20 / 5 / 5`" in output
    assert "still needed C/P/L/S" in output
    assert "`20 / 15 / 3 / 2`" in output
    assert "| LONG | 2 | 1 | 1 | 1 | 0.02 | 2.5 |" in output
    assert "| SHORT | 3 | 2 | 1 | 4 | 0.10 | 9.1 |" in output
    assert "### Paired 60s vs 120s fill-weighted delay" in output
    assert "paired_fill_weighted_same_exit_trade_contribution_only" in output
    assert "prospective closed / paired evaluable" in output
    assert "`10 / 7`" in output
    assert "non-evaluable 60s / 120s" in output
    assert "`1 / 2`" in output
    assert "60s / 120s fill-weighted PnL / incremental" in output
    assert "`2` / `0.5` / `-1.5`" in output
    assert "mean 60s / 120s fill fraction" in output
    assert "`0.8 / 0.65`" in output
    assert "120s loses / gains / matches fill fraction" in output
    assert "`3 / 1 / 3`" in output
    assert "evidence gate closed / paired / LONG / SHORT" in output
    assert "`30 / 20 / 5 / 5`" in output
    assert "still needed C/P/L/S" in output
    assert "`20 / 13 / 2 / 1`" in output
    assert (
        "| LONG | 3 | 1 | 2 | 0 | 0.75 | 0.5 | 0 | -1 | -1 | -0.04 |"
        in output
    )
    assert "### Adaptive 60s/120s delayed-entry selector" in output
    assert "adverse-1m-mid-waits-to-120s-v1" in output
    assert "prospective closed / causal evaluable" in output
    assert "`8 / 6`" in output
    assert "selected 60s / 120s" in output
    assert "`3 / 3`" in output
    assert "actual / always-60 / always-120 / adaptive PnL" in output
    assert "`-6` / `-2` / `-1` / `1`" in output
    assert "adaptive Δ vs actual / 60s / 120s" in output
    assert "`7` / `3` / `2`" in output
    assert "missing mid / non-fresh / late signal" in output
    assert "`0 / 1 / 1`" in output
    assert "robustness is descriptive only / changes gate" in output
    assert "`true / false`" in output
    assert "Δ vs 60s robustness total / LOTO trade / LOMO market" in output
    assert "`3 / 1.8 / 1.6`" in output
    assert "Δ vs 60s survives any one trade / market removal" in output
    assert "`True / True`" in output
    assert "Δ vs 120s robustness total / LOTO trade / LOMO market" in output
    assert "`2 / 1.0 / 0.9`" in output
    assert "largest |Δ| market vs 60s / share" in output
    assert "`SOL / 0.35`" in output
    assert "largest |Δ| market vs 120s / share" in output
    assert "`BTC / 0.44`" in output
    assert "evidence gate closed / causal / 60s / 120s" in output
    assert "`30 / 20 / 5 / 5`" in output
    assert "still needed C/E/60/120" in output
    assert "`22 / 14 / 2 / 2`" in output
    assert (
        "| LONG | 3 | 1 | 2 | 0.5 | 1.5 | 0.5 | 0.85 |"
        in output
    )
    assert (
        "| SHORT | 3 | 2 | 1 | 0.5 | 1.5 | 1.5 | 0.95 |"
        in output
    )
    assert "### 60s delayed-entry same-exit contribution" in output
    assert "same_exit_trade_contribution_only" in output
    assert "closed shadow / full fills / evaluated" in output
    assert "`12 / 8 / 8`" in output
    assert "actual W/L → estimated W/L" in output
    assert "`2/6 → 4/4`" in output
    assert "estimated loss→win / win→loss flips" in output
    assert "`2 / 0`" in output
    assert "actual / same-exit estimated PnL / delta" in output
    assert "`-10` / `6` / `16`" in output
    assert "| LONG | 3 | 1/2 | 2/1 | 1 | -4 | 2 | 6 | 0.17 |" in output
    assert "| SHORT | 5 | 1/4 | 2/3 | 1 | -6 | 4 | 10 | 0.16 |" in output
    assert "### 60s delayed-entry fill-capacity diagnostic" in output
    assert "attempts / mean fill fraction" in output
    assert "`10 / 0.85`" in output
    assert "cause-known / legacy-unknown partials" in output
    assert "`0 / 1`" in output
    assert "| LONG | 4 | 0.75 | 3 | 1 | 0 |" in output
    assert "| SHORT | 6 | 0.9166666666666666666666666667 | 5 | 0 | 1 |" in output
    assert "legacy_unknown_partial: n=1, mean_fill=0.5" in output
    assert "visible_depth_exhausted: n=1, mean_fill=0.7" in output
    assert "slippage_boundary_reached: n=1, mean_fill=0.8" in output
    assert "current open positions with completed +60s attempt" in output
    assert "`1`" in output
    assert (
        "| SOL | long | partial | 0.5 | slippage_boundary_reached | "
        "IOC_REMAINDER_CANCELLED | 300ms |" in output
    )
    assert "### 60s delayed-entry fill-weighted contribution" in output
    assert "fill_weighted_same_exit_trade_contribution_only" in output
    assert "closed shadow / evaluated attempts" in output
    assert "`12 / 10`" in output
    assert "full / partial / no-fill" in output
    assert "`8 / 1 / 1`" in output
    assert "mean delayed fill fraction" in output
    assert "`0.85`" in output
    assert "actual / fill-weighted candidate PnL / delta" in output
    assert "`-12` / `4` / `16`" in output
    assert "actual winner→nonpositive / loss→nonnegative" in output
    assert "`1 / 3`" in output
    assert "evidence gate (closed / evaluated)" in output
    assert "`30 / 20`" in output
    assert "still needed closed / evaluated" in output
    assert "`18 / 10`" in output
    assert "| Partial fill | 1 | 0.5 | 2 | 1 | -1 | -0.1 |" in output
    assert "| No fill | 1 | 0 | -4 | 0 | 4 | 0.4 |" in output
    assert "### 60s delayed-entry contribution decomposition" in output
    assert "price_effect + entry_fee_effect + exposure_effect = total_delta" in output
    assert "price / entry-fee / exposure / total Δ PnL" in output
    assert "`14` / `1.2` / `0.8` / `16`" in output
    assert (
        "| Partial fill | 1 | 0.5 | 2 | 0.2 | -3.2 | -1 | -0.1 |"
        in output
    )
    assert (
        "| Cause: risk_ceiling_clip | 1 | 0.5 | 2 | 0.2 | "
        "-3.2 | -1 | -0.1 |" in output
    )
    assert "### 60s delayed-entry risk geometry" in output
    assert "delayed_average_fill_risk_vs_actual_position_risk" in output
    assert "filled attempts / no-fill outcomes" in output
    assert "`10 / 1`" in output
    assert "evidence gate (filled / risk-clipped)" in output
    assert "`20 / 5`" in output
    assert "still needed filled / risk-clipped" in output
    assert "`10 / 3`" in output
    assert (
        "| Risk-clipped | 2 | 0.70 | 0.99 | 1.18 | 0.85 | 0.18 | 2 | 2 |"
        in output
    )
    assert (
        "| Cause: risk_ceiling_clip | 2 | 0.70 | 0.99 | 1.18 | "
        "0.85 | 0.18 | 2 | 2 |" in output
    )
    assert "Full-size risk / ceiling above 1" in output
    assert (
        "| 120s delayed entry | collecting | "
        "closed=10, full=6, better=4, worse=2 | "
        "mismatch=0, orphan=0 |" in output
    )
    assert (
        "| 60s vs 120s paired | collecting | "
        "closed=10, paired=5 | "
        "missing60=0, missing120=0, mismatch=0 |" in output
    )
    assert (
        "| 60s vs 120s fill-weighted | collecting | "
        "closed=10, paired=7 | "
        "missing60=0, missing120=0, mismatch=0 |" in output
    )
    assert (
        "| adaptive 60s/120s delay | collecting | "
        "closed=8, causal=6 | midmiss=0, late=1, mismatch=0 |"
        in output
    )
    assert (
        "| 60s delayed same-exit | collecting | "
        "closed=12, full=8 | missing=0, mismatch=0 |" in output
    )
    assert (
        "| 60s delayed fill-weighted | collecting | "
        "closed=12, eval=10, fill=0.85 | "
        "missing=0, mismatch=0 |" in output
    )
    assert "evidence gate (closed eligible / full delayed fills)" in output
    assert "`30 / 20`" in output
    assert "still needed closed / full" in output
    assert "`18 / 12`" in output
    assert "### Prospective LONG-trend entry filter" in output
    assert "### Prospective 60s delayed price confirmation" in output
    assert "prospective-60s-price-confirm-v1" in output
    assert "simulated average fill is no worse" in output
    assert "prospective closed / evaluated" in output
    assert "`12 / 10`" in output
    assert "confirmed / skipped" in output
    assert "`6 / 4`" in output
    assert "worse-price / no-fill skips" in output
    assert "`3 / 1`" in output
    assert "actual / candidate trade-contribution PnL" in output
    assert "`-18` / `-9`" in output
    assert "evidence gate (evaluated / confirmed / skipped)" in output
    assert "`30 / 10 / 10`" in output
    assert "still needed E/C/S" in output
    assert "`20 / 4 / 6`" in output
    assert "### Prospective top-10 scanner-rank filter" in output
    assert "prospective-admit-top10-rank-v1" in output
    assert "admit scanner rank `1-10`" in output
    assert "maximum accepted rank age" in output
    assert "`300000`ms" in output
    assert "prospective closed / attributed" in output
    assert "`12 / 11`" in output
    assert "missing / stale rank evidence" in output
    assert "`1 / 0`" in output
    assert "allowed / blocked trades" in output
    assert "`6 / 5`" in output
    assert "allowed W/L · blocked W/L" in output
    assert "`3/3 · 0/5`" in output
    assert "allowed / blocked net PnL" in output
    assert "`20` / `-30`" in output
    assert "allowed / blocked mean R" in output
    assert "`0.25` / `-0.5`" in output
    assert "allowed / blocked mean rank" in output
    assert "`6.5` / `15`" in output
    assert "evidence gate (prospective / blocked / allowed)" in output
    assert "`30 / 10 / 10`" in output
    assert "still needed P/B/A" in output
    assert "`18 / 5 / 4`" in output
    assert "ready for review: `false`" in output
    assert "Existing rank-11–20 losses from before this study do not count" in output
    assert "### Opening scanner-rank attribution" in output
    assert "latest_coarse_rank_before_open" in output
    assert "rank evidence records / attributed closed trades" in output
    assert "`4 / 3`" in output
    assert "mean / max rank age at opening" in output
    assert "`32000`ms / `58000`ms" in output
    assert "| 1-5 | 1 | 1 | 0 | 0 | 5 | 0.5 |" in output
    assert "| 11-20 | 2 | 0 | 2 | 0 | -7 | -0.35 |" in output
    assert "### Opening fill liquidity" in output
    assert "exact_opening_ioc_l2_book" in output
    assert "records / attributed closed / historical without evidence" in output
    assert "`5 / 3 / 9`" in output
    assert "review gate / still needed" in output
    assert "`30 / 27`" in output
    assert (
        "| Overall | 3 | 1 | 2 | -4 | -0.13 | 3 | 1.5 | "
        "100000 | 0.01 | -0.1 | 12ms |"
    ) in output
    assert (
        "| Winners | 1 | 1 | 0 | 5 | 0.5 | 1 | 0.5 | "
        "150000 | 0.005 | 0.3 | 5ms |"
    ) in output
    assert (
        "| Losers | 2 | 0 | 2 | -9 | -0.45 | 4 | 2 | "
        "75000 | 0.02 | -0.3 | 16ms |"
    ) in output
    assert "Historical trades are not backfilled" in output
    assert "### Entry markout → final outcome" in output
    assert "early_markout_sign_vs_final_closed_trade_outcome" in output
    assert "| 1m | 4 | 0.5 | 2/1/1 | 0.05 | 2/1/1 | -0.15 | 26/8/8 |" in output
    assert (
        "| 5m | 3 | 0.6666666666666666666666666667 | "
        "1/1/0 | 0.5 | 2/0/2 | -0.5 | 27/9/8 |"
    ) in output
    assert "| 15m | 2 | 0.5 | 1/1/0 | 0.5 | 1/1/0 | 0.3 | 28/9/9 |" in output
    assert "does not create an entry filter or exit rule" in output
    assert "### Post-entry markout diagnostic" in output
    assert "### Exact-path excursion timing" in output
    assert "complete paths / incomplete skipped" in output
    assert "`12 / 2`" in output
    assert "evidence gate / still needed" in output
    assert "`30 / 18`" in output
    assert "ready for review: `false`" in output
    assert "mean / median time-to-MFE" in output
    assert "`240000ms / 180000ms`" in output
    assert "| +0.5R | 7 |" in output
    assert "| +1R | 5 |" in output
    assert "by side:" in output
    assert "long: n=7, MFE=210000ms" in output
    assert "by lead strategy:" in output
    assert "trend: n=9, MFE=260000ms" in output
    assert "by exit path:" in output
    assert "MARK_STOP_TRIGGERED: n=8" in output
    assert "first_observed_mark_at_or_after_horizon_within_max_lag" in output
    assert "maximum accepted observation lag" in output
    assert "`60000`ms" in output
    assert "complete paths / incomplete skipped" in output
    assert "`3 / 0`" in output
    assert "missing / stale scanner-rank attribution" in output
    assert "`0 / 0`" in output
    assert "accepted scanner-rank age / observed mean / max" in output
    assert "`300000`ms / `32000`ms / `58000`ms" in output
    assert "evidence gate (observations per horizon)" in output
    assert "`30`" in output
    assert "all horizons ready for review: `false`" in output
    assert (
        "| 1m | collecting | 3 | 27 | 2 | 1 | 25 | 0.05 | "
        "0 | 0 | 0 | 1000ms | 3000ms |"
    ) in output
    assert (
        "| 5m | collecting | 2 | 28 | 1 | 1 | -10 | -0.02 | "
        "1 | 0 | 0 | 1500ms | 2500ms |"
    ) in output
    assert (
        "| 15m | collecting | 1 | 29 | 1 | 0 | 80 | 0.16 | "
        "2 | 0 | 0 | 500ms | 500ms |"
    ) in output
    assert "1m by side:" in output
    assert "long: n=2, meanR=-0.02, meanbps=-10" in output
    assert "short: n=1, meanR=0.19, meanbps=95" in output
    assert "1m by lead strategy:" in output
    assert "trend: n=2, meanR=-0.02, meanbps=-10" in output
    assert "1m by scanner rank:" in output
    assert "1-5: n=1, meanR=0.19, meanbps=95" in output
    assert "11-20: n=2, meanR=-0.02, meanbps=-10" in output
    assert "1m by decision age:" in output
    assert "<1s: n=1, meanR=0.19, meanbps=95" in output
    assert "5-<15s: n=2, meanR=-0.02, meanbps=-10" in output
    assert "stale/missing marks are reported and never imputed" in output
    assert "### Prospective allMids entry markout shadow" in output
    assert "allMids_mid_px" in output
    assert "completed prospective trades / excluded / unmatched closes" in output
    assert "`3 / 0 / 0`" in output
    assert "evidence gate:" in output
    assert "`30` fresh observations per horizon" in output
    assert "max non-fresh `0.10`" in output
    assert "all horizons ready for review: `false`" in output
    assert (
        "| 1m | collecting | 3 | 27 | 0 | ok | 0 | 0 | 0 | "
        "2 | 1 | 30 | 0.06 | 800ms | 1400ms |"
    ) in output
    assert (
        "| 5m | collecting | 2 | 28 | "
        "0.3333333333333333333333333333 | collecting | 1 | 0 | 0 | "
        "1 | 1 | 20 | 0.04 | 1000ms | 1600ms |"
    ) in output
    assert (
        "| 15m | collecting | 1 | 29 | 0 | ok | 0 | 2 | 0 | "
        "1 | 0 | 50 | 0.1 | 500ms | 500ms |"
    ) in output
    assert "long: n=2, meanR=-0.01, meanbps=-5" in output
    assert "short: n=1, meanR=0.2, meanbps=100" in output
    assert "Prospective public mid-price observation" in output
    assert "not a mark-price claim, executable fill" in output
    assert "prospective-reject-long-trend-v1" in output
    assert "reject `long` + `trend`" in output
    assert "allowed / blocked trades" in output
    assert "`7 / 5`" in output
    assert "blocked wins / losses" in output
    assert "`0 / 5`" in output
    assert "delta trade contribution" in output
    assert "`30`" in output
    assert "evidence gate (prospective / blocked / allowed)" in output
    assert "`30 / 10 / 10`" in output
    assert "still needed P/B/A" in output
    assert "`18 / 5 / 3`" in output
    assert "ready for review: `false`" in output
    assert "Trade-contribution study only" in output
    assert "### Profit-lock execution shadow" in output
    assert "visible_book_ioc_plus_actual_entry_fee_plus_funding_reserve" in output
    assert "eligible / excluded open positions" in output
    assert "IOC full" in output
    assert "evidence gate (economic / armed / triggered / IOC full)" in output
    assert "`30 / 15 / 10 / 10`" in output
    assert "Need E/A/T/F" in output
    assert "28/13/9/9" in output
    assert "breakeven_after_0_5r" in output
    assert "complete paths evaluated" in output
    assert "`2 / 3`" in output
    assert "lock_0_5r_after_1r" in output
    assert "evidence gate (paths / armed / triggered)" in output
    assert "`30 / 15 / 10`" in output
    assert "all rules ready for review: `false`" in output
    assert "promotion authority: `false`" in output
    assert (
        "| lock_0_5r_after_1r | collecting | 2 | 2 | 1 | 28/13/9 | "
        "0 | 1 | -12 | 4 | 16 | -0.6 | 0.2 | 0.8 |"
    ) in output
    assert "not an executable fill claim" in output
    assert "RESEARCH ONLY / NO EXECUTION" in output
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
    assert "### Drawdown / high-water" in output
    assert "#### Sampled account equity" in output
    assert "prospective_runtime_checkpoint_equity" in output
    assert "configured checkpoint interval" in output
    assert "first / last / peak sample timestamps" in output
    assert "observed mean sample interval" in output
    assert "`60000ms`" in output
    assert "observations / first / latest / peak equity" in output
    assert "`12 / 10000 / 10002.5 / 10020`" in output
    assert "current drawdown amount / fraction" in output
    assert "`17.5 / 0.001746506986027944111776447106`" in output
    assert "maximum drawdown amount / fraction" in output
    assert "`40 / 0.004`" in output
    assert "#### Realized closed-trade equity" in output
    assert "`3 / 10000 / 9993 / 10005`" in output
    assert "`12 / 0.001199400299850074962518740630`" in output
    assert "scheduling can make observations coarser" in output
    assert "intra-sample extremes can be missed" in output
    assert "### Account lifecycle reconciliation" in output
    assert "absolute reconciliation tolerance" in output
    assert "`1E-18`" in output
    assert "fully closed journal matches account-implied closed economics" in output
    assert "realized cash bridge / equity bridge match" in output
    assert "`true / true`" in output
    assert "account cash bridge delta" in output
    assert "`0` · match: `true`" in output
    assert "closed gross / fees / funding / net deltas" in output
    assert "`0 / 0 / 0 / 0`" in output
    assert "| Open lifecycles | 60 | 1 | 0 | 59 | 1 | 60 |" in output
    assert "| Fully closed (account implied) | -8 | 2 | 0 | -10 | — | — |" in output
    assert "| Closed journal | -8 | 2 | 0 | -10 | — | — |" in output
    assert "| Account total | 52 | 3 | 0 | 49 | 1 | 50 |" in output
    assert "#### Open lifecycle cumulative economics" in output
    assert "| BTC | long | 1 | 60 | 1 | 0 | 59 | 1 | 60 |" in output
    assert "can move account cash before the lifecycle is fully closed" in output
    assert "### Entry decision age at fill" in output
    assert "strategy_decision_timestamp_to_first_opening_fill" in output
    assert "attributed closed trades / misses" in output
    assert "`4 / 0`" in output
    assert "review gate / still needed" in output
    assert "`30 / 26`" in output
    assert "mean / median / p90 / max age" in output
    assert "`26875` / `35000` / `65000` / `65000` ms" in output
    assert "| <1s | 1 | 1 | 0 | 0 | 5 | 0.5 | 500ms |" in output
    assert "| 30-<60s | 1 | 0 | 1 | 0 | -4 | -0.4 | 35000ms |" in output
    assert "by lead strategy:" in output
    assert "trend: n=2, meanAge=21000ms, meanR=-0.3, net=-6" in output
    assert "### Closed-trade concentration" in output
    assert "phase9_positive_group_net_pnl_share" in output
    assert "trades / markets / lead strategies / 7d buckets" in output
    assert "`5 / 3 / 2 / 3`" in output
    assert "market positive-PnL share / reference max / met" in output
    assert "`0.6 / 0.35 / false`" in output
    assert "seven-day positive-PnL share / reference max / met" in output
    assert "`0.6 / 0.50 / false`" in output
    assert "market trade-count HHI / positive-PnL HHI" in output
    assert "`0.36 / 0.52`" in output
    assert "largest positive market / strategy / 7d bucket" in output
    assert "`SOL / breakout / 0`" in output
    assert "#### Market concentration" in output
    assert "| SOL | 2 | 1 | 1 | 0 | 30 | 1.5 | 0.4 | 0.6 |" in output
    assert "#### Lead-strategy concentration" in output
    assert "| breakout | 2 | 2 | 0 | 0 | 25 | 1.25 | 0.4 | 0.5 |" in output
    assert "#### UTC seven-day concentration" in output
    assert "| 0 | 2 | 1 | 1 | 0 | 30 | 1.5 | 0.4 | 0.6 |" in output
    assert "35% market and 50% seven-day values are reference limits only" in output
    assert "### Closed-trade UTC decision-hour attribution" in output
    assert "strategy_decision_timestamp_utc_hour" in output
    assert "closed / attributed / misses" in output
    assert "`4 / 4 / 0`" in output
    assert "active UTC hours / positive / negative hours" in output
    assert "`3 / 1 / 2`" in output
    assert "trade-count HHI across active UTC hours" in output
    assert "`0.375`" in output
    assert "| 00:00-00:59 | 1 | 1 | 0 | 0 | 10 | 1 | 1 | None | 0.25 |" in output
    assert "| 08:00-08:59 | 2 | 1 | 1 | 0 | -3 | -0.15 | 0.5 | 0.4 | 0.5 |" in output
    assert "| 23:00-23:59 | 1 | 0 | 1 | 0 | -1 | -0.1 | 0 | 0 | 0.25 |" in output
    assert "immutable strategy-decision timestamp" in output
    assert "### Closed-trade friction attribution" in output
    assert "reference_gross_minus_slippage_minus_fees_plus_funding" in output
    assert "| 6 | 1 | 5 | 5.5 | 2 | 1.5 | 4.5 |" in output
    assert "adverse / favorable slippage amounts" in output
    assert "`3 / 2`" in output
    assert "friction-flipped / fee+funding-flipped / rescued" in output
    assert "`1 / 1 / 1`" in output
    assert "#### Side friction" in output
    assert "| long | 2 | 9 | 3 | 5 | 0 | 1 | 1 | 0.45 | 0.4 | 0.05 |" in output
    assert "#### Lead strategy friction" in output
    assert "| trend | 2 | 9 | 3 | 5 | 0 | 1 | 1 | 0.45 | 0.4 | 0.05 |" in output
    assert "Positive signed slippage is adverse" in output
    assert "### Closed-trade robustness sensitivity" in output
    assert "largest winner PnL / R" in output
    assert "`10 / 1.0`" in output
    assert "top-1 / top-2 share of gross profit" in output
    assert "`0.6666666666666666666666666667 / 1`" in output
    assert (
        "top positive market / net PnL / trades / "
        "positive-market-PnL share" in output
    )
    assert (
        "`NIL / 70 / 3 / 0.8235294117647058823529411765`"
        in output
    )
    assert (
        "| Remove top positive market (NIL) | 17 | -58 | -0.22 | "
        "-0.2 | 0.45 | false |" in output
    )
    assert "positive PnL survives remove top positive market" in output
    assert "`false`" in output
    assert (
        "| Remove best 1 | 3 | -6 | -0.2 | -0.3 | "
        "0.4545454545454545454545454545 | false |"
    ) in output
    assert "| Remove best 2 | 2 | -11 | -0.55 | -0.55 | 0 | false |" in output
    assert "positive PnL survives remove best 1 / best 2" in output
    assert "`false / false`" in output
    assert "Deterministic sensitivity only" in output
    assert "### Closed-trade chronological stability" in output
    assert "closed trades / review gate / still needed" in output
    assert "`20 / 40 / 20`" in output
    assert "chronological blocks / min trades per block" in output
    assert "`4 / 10`" in output
    assert "full blocks / all positive PnL / all positive mean R" in output
    assert "`0 / false / false`" in output
    assert "| 5 trades | 16 | 0.5 | 0.375 | -10 | -0.2 | -0.4 | 1.0 |" in output
    assert "| 10 trades | 11 |" in output
    assert "| 3 | 5 | 1 | 4 | -2 | -0.04 | 0.9 |" in output
    assert "review gate requires 40 chronological closed trades" in output
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
