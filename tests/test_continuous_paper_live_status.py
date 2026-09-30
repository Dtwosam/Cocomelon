from __future__ import annotations

import json
import os
import subprocess
import sys

from scripts.render_continuous_paper_live_status import (
    _cadence_opportunity_learning_lines,
    _closed_trade_stop_reentry_lines,
    _delayed_entry_stop_l2_lines,
    _opening_opportunity_evidence_lines,
    _prospective_allowed_residual_lines,
    _prospective_capacity_reflow_exit_fill_lines,
    _prospective_capacity_reflow_fill_feasibility_lines,
    _prospective_capacity_reflow_forward_excursion_lines,
    _prospective_capacity_reflow_forward_markout_lines,
    _prospective_capacity_reflow_opportunity_lines,
    _prospective_capacity_reflow_realized_pnl_lines,
    _prospective_capacity_reflow_release_lineage_lines,
    _prospective_combined_entry_filter_lines,
    _prospective_combined_matched_overlap_lines,
    _prospective_daily_loss_lockout_reflow_lines,
    _prospective_filter_fixed_schedule_lines,
    _prospective_filter_robustness_lines,
    _prospective_replacement_exit_policy_lines,
    _prospective_replacement_exit_readiness_lines,
    _prospective_replacement_exit_robustness_lines,
    _prospective_residual_profit_lock_lines,
    _replacement_funding_evidence_lines,
    render_live_status,
)

SCRIPT = "scripts/render_continuous_paper_live_status.py"


def test_live_status_renderer_exposes_current_position_and_paper_only_state() -> None:
    payload = {
        "timestamp_ms": 1_700_000_000_000,
        "starting_cash": "10000",
        "equity": "10002.5",
        "total_account_pnl": "2.5",
        "total_return_fraction": "0.00025",
        "cash": "9990",
        "day_start_ms": 1_699_920_000_000,
        "day_start_equity": "10010",
        "daily_realized_pnl": "-7.5",
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
            "state_schema_version": 3,
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
            "state_schema_version": 3,
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
                "temporal": {
                    "configured_blocks": 4,
                    "min_trades_per_full_block": 5,
                    "full_blocks": 0,
                    "positive_blocks_vs_60s": 0,
                    "positive_blocks_vs_120s": 0,
                    "all_full_blocks_positive_vs_60s": False,
                    "all_full_blocks_positive_vs_120s": False,
                    "chronological_blocks": [
                        {
                            "block": 1,
                            "trades": 2,
                            "first_closed_at_ms": 1700000900000,
                            "last_closed_at_ms": 1700001900000,
                            "selected_60s": 1,
                            "selected_120s": 1,
                            "adaptive_minus_60s_pnl": "1.2",
                            "adaptive_minus_120s_pnl": "0.8",
                            "adaptive_minus_actual_pnl": "3",
                            "positive_vs_60s": True,
                            "positive_vs_120s": True,
                        },
                        {
                            "block": 2,
                            "trades": 2,
                            "first_closed_at_ms": 1700002900000,
                            "last_closed_at_ms": 1700003900000,
                            "selected_60s": 1,
                            "selected_120s": 1,
                            "adaptive_minus_60s_pnl": "1.0",
                            "adaptive_minus_120s_pnl": "0.7",
                            "adaptive_minus_actual_pnl": "2",
                            "positive_vs_60s": True,
                            "positive_vs_120s": True,
                        },
                        {
                            "block": 3,
                            "trades": 1,
                            "first_closed_at_ms": 1700004900000,
                            "last_closed_at_ms": 1700004900000,
                            "selected_60s": 1,
                            "selected_120s": 0,
                            "adaptive_minus_60s_pnl": "0",
                            "adaptive_minus_120s_pnl": "0.3",
                            "adaptive_minus_actual_pnl": "1",
                            "positive_vs_60s": False,
                            "positive_vs_120s": True,
                        },
                        {
                            "block": 4,
                            "trades": 1,
                            "first_closed_at_ms": 1700005900000,
                            "last_closed_at_ms": 1700005900000,
                            "selected_60s": 0,
                            "selected_120s": 1,
                            "adaptive_minus_60s_pnl": "0.8",
                            "adaptive_minus_120s_pnl": "0.2",
                            "adaptive_minus_actual_pnl": "1",
                            "positive_vs_60s": True,
                            "positive_vs_120s": True,
                        },
                    ],
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
        "fill_aware_delay_selector": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": "nonfull-60s-waits-to-120s-v1",
            "started_at_ms": 1700000700000,
            "state_restore_error": None,
            "error": None,
            "claim_scope": (
                "fill_weighted_same_exit_trade_contribution_only"
            ),
            "rule": (
                "if_60s_full_visible_book_ioc_choose_60s_"
                "else_if_60s_partial_or_no_fill_choose_120s"
            ),
            "base_delay_ms": 60000,
            "challenger_delay_ms": 120000,
            "prospective_closed_trades": 8,
            "causal_evaluable_trades": 6,
            "missing_base_outcome": 0,
            "missing_challenger_outcome": 0,
            "non_evaluable_base": 1,
            "non_evaluable_challenger": 1,
            "lineage_mismatches": 0,
            "overall": {
                "trades": 6,
                "selected_60s": 3,
                "selected_120s": 3,
                "actual_net_pnl": "-6",
                "always_60s_net_pnl": "-2",
                "always_120s_net_pnl": "-1",
                "fill_aware_net_pnl": "2",
                "fill_aware_minus_actual_pnl": "8",
                "fill_aware_minus_60s_pnl": "4",
                "fill_aware_minus_120s_pnl": "3",
                "fill_aware_better_than_60s": 2,
                "fill_aware_worse_than_60s": 0,
                "fill_aware_better_than_120s": 2,
                "fill_aware_worse_than_120s": 1,
                "mean_selected_fill_fraction": "0.92",
                "mean_selected_r_contribution": "0.03",
            },
            "by_side": {
                "long": {
                    "trades": 3,
                    "selected_60s": 1,
                    "selected_120s": 2,
                    "fill_aware_net_pnl": "0.5",
                    "fill_aware_minus_60s_pnl": "2",
                    "fill_aware_minus_120s_pnl": "1",
                    "mean_selected_fill_fraction": "0.88",
                },
                "short": {
                    "trades": 3,
                    "selected_60s": 2,
                    "selected_120s": 1,
                    "fill_aware_net_pnl": "1.5",
                    "fill_aware_minus_60s_pnl": "2",
                    "fill_aware_minus_120s_pnl": "2",
                    "mean_selected_fill_fraction": "0.96",
                },
            },
            "by_60s_source": {
                "full_visible_book_ioc": {
                    "trades": 3,
                    "selected_60s": 3,
                    "selected_120s": 0,
                    "fill_aware_net_pnl": "3",
                    "fill_aware_minus_60s_pnl": "0",
                    "fill_aware_minus_120s_pnl": "1",
                    "mean_selected_fill_fraction": "1",
                },
                "partial_visible_book_ioc": {
                    "trades": 2,
                    "selected_60s": 0,
                    "selected_120s": 2,
                    "fill_aware_net_pnl": "-0.5",
                    "fill_aware_minus_60s_pnl": "3",
                    "fill_aware_minus_120s_pnl": "0",
                    "mean_selected_fill_fraction": "0.9",
                },
                "no_fill": {
                    "trades": 1,
                    "selected_60s": 0,
                    "selected_120s": 1,
                    "fill_aware_net_pnl": "-0.5",
                    "fill_aware_minus_60s_pnl": "1",
                    "fill_aware_minus_120s_pnl": "0",
                    "mean_selected_fill_fraction": "0.8",
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
        "delay_selector_comparison": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": "markout-vs-fill-aware-delay-v1",
            "started_at_ms": 1700000800000,
            "state_restore_error": None,
            "error": None,
            "claim_scope": (
                "paired_fill_weighted_same_exit_trade_contribution_only"
            ),
            "prospective_closed_trades": 9,
            "causal_evaluable_trades": 7,
            "disagreement_trades": 4,
            "missing_mid_outcome": 0,
            "missing_base_outcome": 0,
            "missing_challenger_outcome": 0,
            "non_evaluable_base": 1,
            "non_evaluable_challenger": 1,
            "lineage_mismatches": 0,
            "overall": {
                "trades": 7,
                "agreements": 3,
                "disagreements": 4,
                "both_60s": 2,
                "both_120s": 1,
                "markout_60s_fill_120s": 3,
                "markout_120s_fill_60s": 1,
                "fill_aware_better": 2,
                "markout_better": 1,
                "equal_contribution": 4,
                "markout_selector_pnl": "1",
                "fill_aware_selector_pnl": "3",
                "fill_aware_minus_markout_pnl": "2",
                "mean_fill_aware_minus_markout_pnl": (
                    "0.2857142857142857142857142857"
                ),
            },
            "disagreements": {
                "trades": 4,
                "agreements": 0,
                "disagreements": 4,
                "both_60s": 0,
                "both_120s": 0,
                "markout_60s_fill_120s": 3,
                "markout_120s_fill_60s": 1,
                "fill_aware_better": 2,
                "markout_better": 1,
                "equal_contribution": 1,
                "markout_selector_pnl": "-2",
                "fill_aware_selector_pnl": "1",
                "fill_aware_minus_markout_pnl": "3",
                "mean_fill_aware_minus_markout_pnl": "0.75",
            },
            "by_side": {},
            "by_disagreement_type": {
                "markout_60s_fill_120s": {
                    "trades": 3,
                    "agreements": 0,
                    "disagreements": 3,
                    "both_60s": 0,
                    "both_120s": 0,
                    "markout_60s_fill_120s": 3,
                    "markout_120s_fill_60s": 0,
                    "fill_aware_better": 2,
                    "markout_better": 0,
                    "equal_contribution": 1,
                    "markout_selector_pnl": "-2",
                    "fill_aware_selector_pnl": "2",
                    "fill_aware_minus_markout_pnl": "4",
                    "mean_fill_aware_minus_markout_pnl": (
                        "1.333333333333333333333333333"
                    ),
                },
                "markout_120s_fill_60s": {
                    "trades": 1,
                    "agreements": 0,
                    "disagreements": 1,
                    "both_60s": 0,
                    "both_120s": 0,
                    "markout_60s_fill_120s": 0,
                    "markout_120s_fill_60s": 1,
                    "fill_aware_better": 0,
                    "markout_better": 1,
                    "equal_contribution": 0,
                    "markout_selector_pnl": "0",
                    "fill_aware_selector_pnl": "-1",
                    "fill_aware_minus_markout_pnl": "-1",
                    "mean_fill_aware_minus_markout_pnl": "-1",
                },
            },
            "readiness": {
                "ready_for_review": False,
                "min_prospective_closed_trades": 30,
                "min_causal_evaluable_trades": 20,
                "min_disagreement_trades": 10,
                "missing_prospective_closed_trades": 21,
                "missing_causal_evaluable_trades": 13,
                "missing_disagreement_trades": 6,
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
        "prospective_combined_entry_filter": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": "prospective-top10-no-long-trend-v1",
            "started_at_ms": 1_699_999_800_000,
            "state_restore_error": None,
            "error": None,
            "rule": {
                "max_admitted_ordinal": 10,
                "max_rank_age_ms": 300000,
                "reject_direction": "long",
                "reject_lead_strategy": "trend",
                "combination": "all_conditions_must_pass",
            },
            "claim_scope": "prospective_closed_trade_contribution_only",
            "portfolio_counterfactual": False,
            "prospective_closed_trades": 8,
            "attributed_trades": 8,
            "decision_attribution_misses": 0,
            "missing_rank_evidence": 0,
            "stale_rank_evidence": 0,
            "allowed_trades": 4,
            "blocked_trades": 4,
            "allowed_wins": 3,
            "allowed_losses": 1,
            "blocked_wins": 0,
            "blocked_losses": 4,
            "allowed_net_pnl": "12",
            "blocked_net_pnl": "-20",
            "actual_net_pnl": "-8",
            "candidate_trade_contribution_pnl": "12",
            "delta_trade_contribution_pnl": "20",
            "actual_mean_net_r": "-0.10",
            "allowed_mean_net_r": "0.30",
            "blocked_mean_net_r": "-0.50",
            "allowed_mean_ordinal": "5",
            "blocked_mean_ordinal": "14",
            "by_block_reason": {
                "long_trend": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "net_pnl": "-5",
                    "mean_net_r": "-0.5",
                    "mean_ordinal": "5",
                },
                "rank_above_10": {
                    "trades": 2,
                    "wins": 0,
                    "losses": 2,
                    "net_pnl": "-9",
                    "mean_net_r": "-0.45",
                    "mean_ordinal": "15",
                },
                "long_trend_and_rank_above_10": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "net_pnl": "-6",
                    "mean_net_r": "-0.6",
                    "mean_ordinal": "16",
                },
            },
            "readiness": {
                "ready_for_review": False,
                "integrity_clean": True,
                "min_prospective_closed_trades": 30,
                "min_blocked_trades": 10,
                "min_allowed_trades": 10,
                "missing_prospective_closed_trades": 22,
                "missing_blocked_trades": 6,
                "missing_allowed_trades": 6,
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
        "delayed_entry_fixed_schedule_portfolio": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "fixed_observed_schedule_portfolio_contribution_only"
            ),
            "delay_ms": 60000,
            "exit_assumption": (
                "actual_trade_close_timestamp_and_exit_economics"
            ),
            "replacement_trades_modeled": False,
            "changed_exit_timing_modeled": False,
            "unrealized_equity_modeled": False,
            "closed_shadow_outcomes": 12,
            "evaluated_delayed_attempts": 10,
            "unresolved_outcomes": 2,
            "missing_journal_trades": 0,
            "missing_opening_plans": 0,
            "lineage_mismatches": 0,
            "candidate_risk_ceiling_exceeded": 0,
            "candidate_no_fill_trades": 1,
            "cohort_reference_equity": "10000",
            "actual": {
                "final_realized_contribution": "-12",
                "max_realized_drawdown": "18",
                "max_concurrent_positions": 4,
                "overlap_openings": 6,
                "max_gross_notional": "1500",
                "max_planned_risk": "45",
                "position_exposure_hours": "7.5",
                "notional_exposure_hours": "2800",
                "risk_exposure_hours": "85",
            },
            "candidate": {
                "final_realized_contribution": "4",
                "max_realized_drawdown": "9",
                "max_concurrent_positions": 3,
                "overlap_openings": 4,
                "max_gross_notional": "1100",
                "max_planned_risk": "34",
                "position_exposure_hours": "5.9",
                "notional_exposure_hours": "2100",
                "risk_exposure_hours": "64",
            },
            "delta_final_realized_contribution": "16",
            "delta_max_realized_drawdown": "-9",
            "delta_max_gross_notional": "-400",
            "delta_max_planned_risk": "-11",
            "readiness": {
                "ready_for_review": False,
                "min_closed_shadow_outcomes": 30,
                "min_evaluated_delayed_attempts": 20,
                "min_actual_overlap_openings": 5,
                "missing_closed_shadow_outcomes": 18,
                "missing_evaluated_delayed_attempts": 10,
                "missing_actual_overlap_openings": 0,
            },
            "error": None,
        },
        "delayed_entry_mtm_portfolio": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "fixed_observed_schedule_mark_to_market_contribution_only"
            ),
            "delay_ms": 60000,
            "mark_model": (
                "latest_observed_exact_path_mark_carried_forward"
            ),
            "entry_fee_timing_modeled": True,
            "exit_fee_settled_at_actual_close": True,
            "intratrade_funding_timing_modeled": True,
            "funding_model": (
                "exact_recorded_boundary_oracle_and_rate_with_"
                "candidate_quantity_scaled_by_delayed_fill_fraction"
            ),
            "replacement_trades_modeled": False,
            "changed_exit_timing_modeled": False,
            "closed_shadow_outcomes": 12,
            "evaluated_complete_path_trades": 9,
            "candidate_filled_positions": 8,
            "candidate_no_fill_trades": 1,
            "unresolved_outcomes": 2,
            "missing_journal_trades": 0,
            "missing_exact_paths": 1,
            "incomplete_exact_paths": 0,
            "missing_funding_events": 0,
            "lineage_mismatches": 0,
            "actual": {
                "final_realized_contribution": "-11",
                "max_observed_equity_drawdown": "21",
                "min_observed_equity_contribution": "-17",
                "max_observed_equity_contribution": "6",
                "max_concurrent_positions": 4,
                "overlap_openings": 6,
                "observation_events": 48,
                "max_mark_carry_age_ms": 45000,
                "funding_events": 3,
                "funding_cash_pnl": "-2",
            },
            "candidate": {
                "final_realized_contribution": "3",
                "max_observed_equity_drawdown": "10",
                "min_observed_equity_contribution": "-7",
                "max_observed_equity_contribution": "8",
                "max_concurrent_positions": 3,
                "overlap_openings": 4,
                "observation_events": 40,
                "max_mark_carry_age_ms": 38000,
                "funding_events": 2,
                "funding_cash_pnl": "-1",
            },
            "delta_final_realized_contribution": "14",
            "delta_max_observed_equity_drawdown": "-11",
            "readiness": {
                "ready_for_review": False,
                "min_closed_shadow_outcomes": 30,
                "min_evaluated_complete_path_trades": 20,
                "min_actual_overlap_openings": 5,
                "missing_closed_shadow_outcomes": 18,
                "missing_evaluated_complete_path_trades": 11,
                "missing_actual_overlap_openings": 0,
            },
            "error": None,
        },
        "delayed_entry_stop_survivability": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "delayed_entry_original_stop_survivability_only"
            ),
            "delay_ms": 60000,
            "mark_ordering_assumption": (
                "only_marks_strictly_after_delayed_open_are_causal"
            ),
            "stop_price_source": (
                "immutable_closed_trade_initial_stop"
            ),
            "stop_fill_price_modeled": False,
            "full_exit_policy_modeled": False,
            "replacement_trades_modeled": False,
            "closed_shadow_outcomes": 12,
            "evaluated_filled_candidates": 8,
            "candidate_no_fill_trades": 1,
            "unresolved_outcomes": 2,
            "missing_journal_trades": 0,
            "missing_exact_paths": 1,
            "incomplete_or_gapped_paths": 0,
            "lineage_mismatches": 0,
            "invalid_candidate_timing": 0,
            "overall": {
                "filled_candidates": 8,
                "definite_original_stop_crossings": 3,
                "survived_observed_path_to_actual_close": 5,
                "crossing_fraction": "0.375",
                "mean_time_to_stop_ms": 42000,
                "median_time_to_stop_ms": 38000,
                "min_time_to_stop_ms": 12000,
            },
            "by_side": {},
            "by_source": {},
            "readiness": {
                "ready_for_review": False,
                "min_closed_shadow_outcomes": 30,
                "min_evaluated_filled_candidates": 20,
                "missing_closed_shadow_outcomes": 18,
                "missing_evaluated_filled_candidates": 12,
            },
            "error": None,
        },
        "delayed_entry_same_exit_stop_validity": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "funding_corrected_same_exit_stop_validity_partition_only"
            ),
            "delay_ms": 60000,
            "same_exit_pnl_interpretation": (
                "stop_crossed_candidate_pnl_is_flagged_as_path_invalid_"
                "rather_than_repriced"
            ),
            "stop_fill_price_modeled": False,
            "changed_exit_timing_modeled": False,
            "replacement_trades_modeled": False,
            "closed_shadow_outcomes": 12,
            "evaluated_filled_candidates": 8,
            "candidate_no_fill_trades": 1,
            "unresolved_outcomes": 2,
            "missing_journal_trades": 0,
            "missing_exact_paths": 1,
            "incomplete_or_gapped_paths": 0,
            "missing_funding_events": 0,
            "lineage_mismatches": 0,
            "invalid_candidate_timing": 0,
            "overall": {
                "filled_candidates": 8,
                "definite_original_stop_crossings": 3,
                "survived_observed_path_to_actual_close": 5,
                "crossing_fraction": "0.375",
                "actual_net_pnl": "-10",
                "same_exit_candidate_net_pnl": "5",
                "same_exit_delta_vs_actual": "15",
                "candidate_actual_decimal_rounding_residual_pnl": "-1E-25",
                "same_exit_candidate_pnl_on_definite_stop_crossings": "4",
                "same_exit_candidate_pnl_on_observed_survivors": "1",
                "same_exit_delta_on_definite_stop_crossings": "8",
                "same_exit_delta_on_observed_survivors": "7",
                "absolute_candidate_pnl_on_stop_crossings_fraction": "0.8",
                "positive_same_exit_candidate_pnl_on_stop_crossings": "4",
                "negative_same_exit_candidate_pnl_on_stop_crossings": "0",
                "mean_time_to_stop_ms": 42000,
            },
            "by_side": {},
            "by_source": {},
            "readiness": {
                "ready_for_review": False,
                "min_closed_shadow_outcomes": 30,
                "min_evaluated_filled_candidates": 20,
                "missing_closed_shadow_outcomes": 18,
                "missing_evaluated_filled_candidates": 12,
            },
            "error": None,
        },
        "delayed_entry_stop_exit_proxy": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "delayed_entry_stop_exit_full_quantity_proxy_range_only"
            ),
            "delay_ms": 60000,
            "stop_price_proxy": (
                "idealized_full_exit_at_immutable_original_stop"
            ),
            "crossing_mark_proxy": (
                "full_exit_at_first_observed_stop_crossing_mark"
            ),
            "ioc_boundary_proxy": (
                "full_exit_at_first_crossing_mark_plus_configured_"
                "max_ioc_slippage_boundary"
            ),
            "visible_exit_depth_modeled": False,
            "partial_stop_fill_modeled": False,
            "exact_stop_fill_price_modeled": False,
            "funding_at_exact_stop_timestamp_modeled": False,
            "taker_fee_rate": "0.00045",
            "max_ioc_slippage_bps": "25",
            "closed_shadow_outcomes": 12,
            "evaluated_filled_candidates": 8,
            "candidate_no_fill_trades": 1,
            "unresolved_outcomes": 2,
            "missing_journal_trades": 0,
            "missing_exact_paths": 1,
            "incomplete_or_gapped_paths": 0,
            "missing_funding_events": 0,
            "ambiguous_stop_funding_timing": 0,
            "lineage_mismatches": 0,
            "invalid_candidate_timing": 0,
            "overall": {
                "filled_candidates": 8,
                "definite_original_stop_crossings": 3,
                "survived_observed_path_to_actual_close": 5,
                "actual_net_pnl": "-10",
                "same_exit_candidate_net_pnl": "5",
                "same_exit_candidate_pnl_on_stop_crossings": "4",
                "stop_price_proxy_pnl_on_stop_crossings": "-7",
                "crossing_mark_proxy_pnl_on_stop_crossings": "-9",
                "ioc_boundary_proxy_pnl_on_stop_crossings": "-10",
                "stop_price_proxy_cohort_net_pnl": "-6",
                "crossing_mark_proxy_cohort_net_pnl": "-8",
                "ioc_boundary_proxy_cohort_net_pnl": "-9",
                "same_exit_delta_vs_actual": "15",
                "stop_price_proxy_delta_vs_actual": "4",
                "crossing_mark_proxy_delta_vs_actual": "2",
                "ioc_boundary_proxy_delta_vs_actual": "1",
                "same_exit_minus_ioc_boundary_proxy_pnl": "14",
                "positive_same_exit_crossings_to_nonpositive_boundary": 2,
                "ioc_boundary_proxy_positive_crossings": 0,
                "mean_stop_to_ioc_boundary_proxy_spread": "1",
            },
            "by_side": {},
            "by_source": {},
            "readiness": {
                "ready_for_review": False,
                "min_closed_shadow_outcomes": 30,
                "min_evaluated_filled_candidates": 20,
                "missing_closed_shadow_outcomes": 18,
                "missing_evaluated_filled_candidates": 12,
            },
            "error": None,
        },
        "delayed_entry_portfolio_capacity": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "fixed_observed_schedule_portfolio_capacity_overlay"
            ),
            "delay_ms": 60000,
            "reference_equity": "10000",
            "correlation_bucket_assumption": (
                "single_runtime_configured_bucket"
            ),
            "limits": {
                "max_open_risk": "0.0075",
                "correlation_bucket_risk_limit": "0.005",
                "max_gross_leverage": "3",
                "max_available_margin_fraction": "0.50",
                "max_visible_depth_fraction": "0.10",
                "native_perp_min_notional": "10",
                "paper_max_gross_leverage": "3",
                "min_liquidation_stop_multiple": "2",
            },
            "changed_admissions_modeled": True,
            "admission_policy": (
                "reject_opening_when_configured_risk_or_capacity_gate_breached"
            ),
            "replacement_trades_modeled": False,
            "intratrade_funding_timing_modeled": True,
            "funding_model": (
                "exact_recorded_boundary_oracle_and_rate_with_"
                "candidate_quantity_scaled_by_delayed_fill_fraction"
            ),
            "available_margin_capacity_modeled": True,
            "visible_liquidity_capacity_modeled": True,
            "venue_min_notional_modeled": True,
            "liquidation_buffer_modeled": True,
            "closed_shadow_outcomes": 12,
            "candidate_filled_positions": 8,
            "candidate_no_fill_trades": 1,
            "background_positions": 2,
            "unresolved_outcomes": 2,
            "missing_journal_trades": 0,
            "missing_opening_plans": 0,
            "missing_venue_max_leverage": 0,
            "missing_opening_liquidity_evidence": 0,
            "missing_delayed_liquidity_evidence": 0,
            "missing_delayed_reference_price": 0,
            "missing_funding_events": 0,
            "missing_exact_paths": 1,
            "incomplete_exact_paths": 0,
            "lineage_mismatches": 0,
            "actual": {
                "opening_checks": 10,
                "funding_events": 3,
                "funding_cash_pnl": "-2",
                "overlap_openings": 6,
                "capacity_violations": 0,
                "delayed_opening_violations": 0,
                "background_opening_violations": 0,
                "aggregate_risk_violations": 0,
                "correlation_bucket_risk_violations": 0,
                "gross_leverage_violations": 0,
                "margin_capacity_violations": 0,
                "liquidity_capacity_violations": 0,
                "venue_min_notional_violations": 0,
                "liquidation_buffer_violations": 0,
                "non_positive_equity_events": 0,
                "max_aggregate_risk_utilization": "0.66",
                "max_correlation_bucket_risk_utilization": "0.99",
                "max_gross_leverage": "0.18",
                "max_margin_capacity_utilization": "0.22",
                "max_liquidity_capacity_utilization": "0.20",
                "min_aggregate_risk_headroom": "22",
                "min_correlation_bucket_risk_headroom": "0.5",
                "min_gross_notional_headroom": "28000",
                "min_margin_notional_headroom": "12000",
                "min_liquidity_notional_headroom": "5000",
                "min_venue_notional_headroom": "90",
                "min_liquidation_stop_multiple": "3.3",
                "min_liquidation_stop_headroom": "1.3",
            },
            "candidate": {
                "opening_checks": 10,
                "funding_events": 2,
                "funding_cash_pnl": "-1",
                "overlap_openings": 4,
                "capacity_violations": 2,
                "delayed_opening_violations": 1,
                "background_opening_violations": 1,
                "aggregate_risk_violations": 0,
                "correlation_bucket_risk_violations": 2,
                "gross_leverage_violations": 0,
                "margin_capacity_violations": 1,
                "liquidity_capacity_violations": 1,
                "venue_min_notional_violations": 0,
                "liquidation_buffer_violations": 1,
                "non_positive_equity_events": 0,
                "max_aggregate_risk_utilization": "0.68",
                "max_correlation_bucket_risk_utilization": "1.02",
                "max_gross_leverage": "0.16",
                "max_margin_capacity_utilization": "1.01",
                "max_liquidity_capacity_utilization": "1.25",
                "min_aggregate_risk_headroom": "20",
                "min_correlation_bucket_risk_headroom": "-1",
                "min_gross_notional_headroom": "28500",
                "min_margin_notional_headroom": "-25",
                "min_liquidity_notional_headroom": "-50",
                "min_venue_notional_headroom": "40",
                "min_liquidation_stop_multiple": "1.7",
                "min_liquidation_stop_headroom": "-0.3",
            },
            "actual_admission": {
                "opening_opportunities": 10,
                "funding_events": 3,
                "funding_cash_pnl": "-2",
                "skipped_rejected_funding_events": 0,
                "overlap_opening_opportunities": 6,
                "admitted_openings": 10,
                "rejected_openings": 0,
                "delayed_candidate_admitted": 0,
                "delayed_candidate_rejected": 0,
                "observed_schedule_admitted": 10,
                "observed_schedule_rejected": 0,
                "aggregate_risk_rejections": 0,
                "correlation_bucket_risk_rejections": 0,
                "gross_leverage_rejections": 0,
                "margin_capacity_rejections": 0,
                "liquidity_capacity_rejections": 0,
                "venue_min_notional_rejections": 0,
                "liquidation_buffer_rejections": 0,
                "non_positive_equity_rejections": 0,
                "max_concurrent_positions": 4,
                "max_admitted_aggregate_risk_utilization": "0.66",
                "max_admitted_correlation_bucket_risk_utilization": "0.99",
                "max_admitted_gross_leverage": "0.18",
                "max_admitted_margin_capacity_utilization": "0.22",
                "max_admitted_liquidity_capacity_utilization": "0.20",
                "min_admitted_liquidation_stop_multiple": "3.3",
                "final_realized_contribution": "-11",
            },
            "candidate_admission": {
                "opening_opportunities": 10,
                "funding_events": 1,
                "funding_cash_pnl": "-0.5",
                "skipped_rejected_funding_events": 1,
                "overlap_opening_opportunities": 4,
                "admitted_openings": 8,
                "rejected_openings": 2,
                "delayed_candidate_admitted": 7,
                "delayed_candidate_rejected": 1,
                "observed_schedule_admitted": 1,
                "observed_schedule_rejected": 1,
                "aggregate_risk_rejections": 0,
                "correlation_bucket_risk_rejections": 2,
                "gross_leverage_rejections": 0,
                "margin_capacity_rejections": 1,
                "liquidity_capacity_rejections": 1,
                "venue_min_notional_rejections": 0,
                "liquidation_buffer_rejections": 1,
                "non_positive_equity_rejections": 0,
                "max_concurrent_positions": 3,
                "max_admitted_aggregate_risk_utilization": "0.64",
                "max_admitted_correlation_bucket_risk_utilization": "0.96",
                "max_admitted_gross_leverage": "0.15",
                "max_admitted_margin_capacity_utilization": "0.75",
                "max_admitted_liquidity_capacity_utilization": "0.80",
                "min_admitted_liquidation_stop_multiple": "2.2",
                "final_realized_contribution": "5",
            },
            "fixed_candidate_final_realized_contribution": "3",
            "admitted_candidate_final_realized_contribution": "5",
            "admission_delta_vs_fixed_schedule": "2",
            "readiness": {
                "ready_for_review": False,
                "min_closed_shadow_outcomes": 30,
                "min_candidate_filled_positions": 20,
                "min_candidate_overlap_openings": 5,
                "missing_closed_shadow_outcomes": 18,
                "missing_candidate_filled_positions": 12,
                "missing_candidate_overlap_openings": 1,
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
        "delayed_entry_fill_weighted_funding": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "funding_corrected_fill_weighted_same_exit_"
                "trade_contribution_only"
            ),
            "delay_ms": 60000,
            "exit_assumption": (
                "actual_exit_price_with_exit_fee_scaled_by_fill_fraction"
            ),
            "legacy_funding_assumption": (
                "actual_trade_funding_scaled_by_fill_fraction"
            ),
            "corrected_funding_assumption": (
                "recorded_funding_boundaries_strictly_after_delayed_open_"
                "with_recorded_boundary_quantity_scaled_by_fill_fraction"
            ),
            "unfilled_assumption": (
                "unfilled_quantity_contributes_zero_and_pays_no_funding"
            ),
            "closed_shadow_outcomes": 12,
            "evaluated_delayed_attempts": 10,
            "missing_journal_trades": 0,
            "missing_funding_events": 0,
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
                "actual_net_pnl": "-12",
                "legacy_fill_weighted_candidate_net_pnl": "4",
                "funding_corrected_candidate_net_pnl": "5",
                "legacy_scaled_funding_pnl": "-3",
                "exact_post_delay_funding_pnl": "-2",
                "funding_timing_delta_pnl": "1",
                "corrected_delta_vs_actual_pnl": "17",
                "corrected_delta_vs_legacy_pnl": "1",
                "corrected_better_than_actual": 6,
                "corrected_worse_than_actual": 4,
                "corrected_equal_to_actual": 0,
                "mean_fill_fraction": "0.85",
                "corrected_mean_r_contribution": "0.06",
                "corrected_mean_delta_r_contribution": "0.26",
            },
            "by_side": {},
            "by_source": {},
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
                "decimal_rounding_residual_pnl": "-1E-26",
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
        "delayed_entry_contribution_decomposition_funding": {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "funding_corrected_fill_weighted_same_exit_delta_decomposition"
            ),
            "identity": (
                "price_effect + entry_fee_effect + exposure_effect + "
                "funding_timing_effect = corrected_total_delta"
            ),
            "legacy_identity": (
                "price_effect + entry_fee_effect + exposure_effect = "
                "legacy_total_delta"
            ),
            "closed_shadow_outcomes": 12,
            "evaluated_delayed_attempts": 10,
            "missing_journal_trades": 0,
            "missing_funding_events": 0,
            "lineage_mismatches": 0,
            "overall": {
                "trades": 10,
                "mean_fill_fraction": "0.85",
                "price_effect_pnl": "14",
                "entry_fee_effect_pnl": "1.2",
                "exposure_effect_pnl": "0.8",
                "funding_timing_effect_pnl": "1",
                "legacy_total_delta_pnl": "16",
                "corrected_total_delta_pnl": "17",
                "actual_net_pnl": "-12",
                "corrected_candidate_net_pnl": "5",
                "component_decimal_rounding_residual_pnl": "-2E-26",
                "legacy_bridge_decimal_rounding_residual_pnl": "1E-26",
                "candidate_bridge_decimal_rounding_residual_pnl": "0",
                "mean_price_effect_r": "0.20",
                "mean_entry_fee_effect_r": "0.02",
                "mean_exposure_effect_r": "0.03",
                "mean_funding_timing_effect_r": "0.01",
                "mean_corrected_total_delta_r": "0.26",
                "funding_correction_positive": 2,
                "funding_correction_negative": 0,
                "funding_correction_zero": 8,
            },
            "by_side": {},
            "by_source": {},
            "by_capacity_cause": {},
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
        "| 60s delayed fixed-schedule portfolio | collecting | "
        "closed=12, eval=10, overlap=6 | "
        "unresolved=2, missing=0/0, mismatch=0, risk=0 |" in output
    )
    assert (
        "| 60s delayed MTM portfolio | collecting | "
        "closed=12, paths=9, overlap=6 | "
        "unresolved=2, missing=0/1, incomplete=0, mismatch=0 |" in output
    )
    assert (
        "| 60s delayed capacity overlay | collecting | "
        "closed=12, fills=8, overlap=4, admit/reject=8/2 | "
        "viol=2, marginrej=1, actualrej=0, unresolved=2, "
        "missing=0/0/0/1, incomplete=0, mismatch=0 |"
        in output
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
        "| top-10 + no LONG-trend | collecting | "
        "closed=8, blocked=4, allowed=4 | fact=0, rank=0, stale=0 |"
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
    assert "review-ready studies: `0 / 23`" in output
    assert "| 60s price confirmation | collecting | eval=10, confirmed=6, skipped=4 |" in output
    assert "### Trade-path evidence" in output
    assert "completed exact trade paths" in output
    assert "staged open trade paths" in output
    assert "`3`" in output
    assert "`1`" in output
    assert "### Fixed profit-lock counterfactual" in output
    assert "### 60s delayed-entry execution shadow" in output
    assert "prospective start / state schema" in output
    assert "`1700000000000` / `v3`" in output
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
    assert "temporal full / positive vs 60s / positive vs 120s" in output
    assert "`0 / 0 / 0`" in output
    assert "all full temporal blocks positive vs 60s / 120s" in output
    assert "`False / False`" in output
    assert "temporal block design" in output
    assert "`4 × 5 trades`" in output
    assert "| Time block | N | 60s | 120s | Δ vs 60s | Δ vs 120s |" in output
    assert "| 1 | 2 | 1 | 1 | 1.2 | 0.8 |" in output
    assert "| 4 | 1 | 0 | 1 | 0.8 | 0.2 |" in output
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
    assert "### Fill-aware 60s/120s delayed-entry selector" in output
    assert "nonfull-60s-waits-to-120s-v1" in output
    assert "prospective closed / causal evaluable" in output
    assert "`8 / 6`" in output
    assert "actual / always-60 / always-120 / fill-aware PnL" in output
    assert "`-6` / `-2` / `-1` / `2`" in output
    assert "fill-aware Δ vs actual / 60s / 120s" in output
    assert "`8` / `4` / `3`" in output
    assert "missing 60s / 120s, non-evaluable 60s / 120s" in output
    assert "`0 / 0 / 1 / 1`" in output
    assert "| 60s full fill | 3 | 3 | 0 | 3 | 0 | 1 | 1 |" in output
    assert "| 60s partial fill | 2 | 0 | 2 | -0.5 | 3 | 0 | 0.9 |" in output
    assert "| 60s no fill | 1 | 0 | 1 | -0.5 | 1 | 0 | 0.8 |" in output
    assert "### Markout vs fill-aware delay selector" in output
    assert "markout-vs-fill-aware-delay-v1" in output
    assert "prospective closed / causal evaluable / disagreements" in output
    assert "`9 / 7 / 4`" in output
    assert "agreement / disagreement" in output
    assert "`3 / 4`" in output
    assert "disagreements: fill-aware better / markout better / equal" in output
    assert "`2 / 1 / 1`" in output
    assert "disagreement PnL markout / fill-aware / delta" in output
    assert "`-2` / `1` / `3`" in output
    assert "evidence gate closed / evaluable / disagreements" in output
    assert "`30 / 20 / 10`" in output
    assert "still needed C/E/D" in output
    assert "`21 / 13 / 6`" in output
    assert (
        "| Markout 60s / Fill-aware 120s | 3 | 2 | 0 | 4 |"
        in output
    )
    assert (
        "| Markout 120s / Fill-aware 60s | 1 | 0 | 1 | -1 |"
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
    assert "### 60s delayed-entry funding-corrected fill weighting" in output
    assert "funding_corrected_fill_weighted_same_exit_trade_contribution_only" in output
    assert "legacy scaled / exact post-delay funding / correction" in output
    assert "`-3 / -2 / 1`" in output
    assert "legacy / funding-corrected candidate PnL / correction" in output
    assert "`4 / 5 / 1`" in output
    assert "corrected candidate delta vs actual" in output
    assert "`17`" in output
    assert "missing journal / funding / lineage" in output
    assert "`0 / 0 / 0`" in output
    assert "filled candidates pay verified recorded boundaries" in output
    assert "genuine no-fills pay zero" in output
    assert "### 60s delayed-entry fixed-schedule portfolio shadow" in output
    assert "fixed_observed_schedule_portfolio_contribution_only" in output
    assert "actual / candidate realized contribution / delta" in output
    assert "`-12` / `4` / `16`" in output
    assert "actual / candidate max realized drawdown / delta" in output
    assert "`18` / `9` / `-9`" in output
    assert "actual / candidate max concurrent positions" in output
    assert "`4 / 3`" in output
    assert "actual / candidate overlap openings" in output
    assert "`6 / 4`" in output
    assert "actual / candidate max gross notional / delta" in output
    assert "`1500` / `1100` / `-400`" in output
    assert "actual / candidate max planned risk / delta" in output
    assert "`45` / `34` / `-11`" in output
    assert "complete cohort required (unresolved must be zero)" in output
    assert "`2 unresolved`" in output
    assert "evidence gate closed / evaluated / overlap" in output
    assert "`30 / 20 / 5`" in output
    assert "Fixed observed schedule only" in output
    assert "### 60s delayed-entry mark-to-market portfolio shadow" in output
    assert "fixed_observed_schedule_mark_to_market_contribution_only" in output
    assert "latest_observed_exact_path_mark_carried_forward" in output
    assert "closed shadow / complete paths / unresolved" in output
    assert "`12 / 9 / 2`" in output
    assert "candidate filled / no-fill positions" in output
    assert "`8 / 1`" in output
    assert "missing journal / exact path / incomplete / funding / lineage" in output
    assert "`0 / 1 / 0 / 0 / 0`" in output
    assert "actual / candidate observed equity drawdown / delta" in output
    assert "`21` / `10` / `-11`" in output
    assert "actual / candidate min observed equity contribution" in output
    assert "`-17 / -7`" in output
    assert "actual / candidate funding events / cash" in output
    assert "`3 / 2 / -2 / -1`" in output
    assert "actual / candidate max carried-mark age" in output
    assert "`45000ms / 38000ms`" in output
    assert "evidence gate closed / complete-path / overlap" in output
    assert "`30 / 20 / 5`" in output
    assert "still needed C/P/O" in output
    assert "`18 / 11 / 0`" in output
    assert "Observed-mark contribution equity only" in output
    assert "funding is applied at exact recorded hourly boundaries" in output
    assert "### 60s delayed-entry original-stop survivability" in output
    assert "delayed_entry_original_stop_survivability_only" in output
    assert "closed / evaluated fills / no-fills" in output
    assert "`12 / 8 / 1`" in output
    assert "definite original-stop crossings / observed survivors" in output
    assert "`3 / 5`" in output
    assert "crossing fraction / mean / median / fastest time-to-stop" in output
    assert "`0.375 / 42000 / 38000 / 12000`" in output
    assert "unresolved / missing journal / path / gapped / lineage / timing" in output
    assert "`2 / 0 / 1 / 0 / 0 / 0`" in output
    assert "same-millisecond marks are excluded" in output
    assert "stop fill price and the full exit policy are not modeled" in output
    assert "corrected same-exit candidate PnL all / stop-crossed / survived" in output
    assert "`5 / 4 / 1`" in output
    assert "same-exit Δ vs actual all / stop-crossed / survived" in output
    assert "`15 / 8 / 7`" in output
    assert "stop-validity candidate/actual Decimal residual" in output
    assert "`-1E-25`" in output
    assert "absolute candidate PnL on definite stop crossings" in output
    assert "`0.8`" in output
    assert "stop-validity missing path / funding / lineage" in output
    assert "`1 / 0 / 0`" in output
    assert "flagged as path-invalid" in output
    assert "not repriced into a synthetic stop-fill result" in output
    assert (
        "stop-exit cohort PnL same-exit / stop / mark / IOC-boundary"
        in output
    )
    assert "`5 / -6 / -8 / -9`" in output
    assert (
        "stop-exit Δ vs actual same-exit / stop / mark / IOC-boundary"
        in output
    )
    assert "`15 / 4 / 2 / 1`" in output
    assert (
        "same-exit edge removed by IOC-boundary proxy / "
        "positive→nonpositive crossings"
    ) in output
    assert "`14 / 2`" in output
    assert "stop proxy config taker fee / max slippage bps" in output
    assert "`0.00045 / 25`" in output
    assert (
        "stop proxy missing path / funding / ambiguous funding / lineage"
        in output
    )
    assert "`1 / 0 / 0 / 0`" in output
    assert "full-exit price proxies only" in output
    assert "Exit-side L2 depth and partial stop fills are not reconstructed" in output
    assert "### 60s delayed-entry portfolio capacity overlay" in output
    assert "fixed_observed_schedule_portfolio_capacity_overlay" in output
    assert (
        "frozen limits open-risk / bucket-risk / gross leverage / "
        "margin fraction / visible-depth fraction / venue minimum / "
        "paper leverage / liquidation stop multiple"
    ) in output
    assert "`0.0075 / 0.005 / 3 / 0.50 / 0.10 / 10 / 3 / 2`" in output
    assert "candidate opening checks / capacity violations" in output
    assert "`10 / 2`" in output
    assert "candidate violations delayed / background" in output
    assert "`1 / 1`" in output
    assert (
        "candidate violations aggregate / bucket / leverage / margin / "
        "liquidity / min-notional / liquidation"
    ) in output
    assert "`0 / 2 / 0 / 1 / 1 / 0 / 1`" in output
    assert (
        "candidate max utilization aggregate / bucket / leverage / margin / "
        "liquidity" in output
    )
    assert "`0.68 / 1.02 / 0.16 / 1.01 / 1.25`" in output
    assert (
        "candidate min headroom aggregate / bucket / gross / margin / "
        "liquidity / venue-min notional" in output
    )
    assert "`20 / -1 / 28500 / -25 / -50 / 40`" in output
    assert "candidate liquidation min multiple / headroom" in output
    assert "`1.7 / -0.3`" in output
    assert "causal admissions modeled / replacement trades modeled" in output
    assert "`true / false`" in output
    assert "actual admission admitted / rejected" in output
    assert "`10 / 0`" in output
    assert "candidate admission admitted / rejected" in output
    assert "`8 / 2`" in output
    assert "candidate delayed admitted / rejected" in output
    assert "`7 / 1`" in output
    assert "candidate observed-schedule admitted / rejected" in output
    assert "`1 / 1`" in output
    assert (
        "candidate admission rejection causes aggregate / bucket / "
        "leverage / margin / liquidity / min-notional / liquidation / "
        "non-positive-equity"
    ) in output
    assert "`0 / 2 / 0 / 1 / 1 / 0 / 1 / 0`" in output
    assert (
        "candidate admitted max utilization aggregate / bucket / leverage / "
        "margin / liquidity" in output
    )
    assert "`0.64 / 0.96 / 0.15 / 0.75 / 0.80`" in output
    assert "admitted candidate minimum liquidation stop multiple" in output
    assert "`2.2`" in output
    assert "funding events/cash fixed A/C · admitted A/C" in output
    assert "`3/2 -2/-1 · 3/1 -2/-0.5`" in output
    assert "fixed / admitted candidate realized contribution / admission Δ" in output
    assert "`3 / 5 / 2`" in output
    assert "evidence gate closed / candidate fills / candidate overlap" in output
    assert "`30 / 20 / 5`" in output
    assert "still needed C/F/O" in output
    assert "`18 / 12 / 1`" in output
    assert "The fixed overlay still reports every opening opportunity" in output
    assert "causal admission shadow separately skips any opening" in output
    assert "visible-liquidity capacity" in output
    assert "paper liquidation buffer" in output
    assert "venue minimum notional" in output
    assert "Funding is applied at exact recorded boundaries" in output
    assert "does not invent resized or replacement trades" in output
    assert "### 60s delayed-entry contribution decomposition" in output
    assert "price_effect + entry_fee_effect + exposure_effect = total_delta" in output
    assert "price / entry-fee / exposure / total Δ PnL" in output
    assert "`14` / `1.2` / `0.8` / `16`" in output
    assert "aggregate Decimal rounding residual" in output
    assert "`-1E-26`" in output
    assert (
        "| Partial fill | 1 | 0.5 | 2 | 0.2 | -3.2 | -1 | -0.1 |"
        in output
    )
    assert (
        "| Cause: risk_ceiling_clip | 1 | 0.5 | 2 | 0.2 | "
        "-3.2 | -1 | -0.1 |" in output
    )
    assert "funding timing / corrected total Δ PnL" in output
    assert "`1 / 17`" in output
    assert "legacy / corrected total Δ PnL" in output
    assert "`16 / 17`" in output
    assert "funding summary Decimal residuals" in output
    assert "`-2E-26 / 1E-26 / 0`" in output
    assert "funding-aware missing journal / funding / lineage" in output
    assert "`0 / 0 / 0`" in output
    assert "Funding timing is the explicit fourth effect" in output
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
        "| fill-aware 60s/120s delay | collecting | "
        "closed=8, causal=6 | non60=1, non120=1, mismatch=0 |"
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
    assert "### Prospective top-10 + no LONG-trend entry filter" in output
    assert "actual / candidate / delta trade contribution" in output
    assert "`-8 / 12 / 20`" in output
    assert "| LONG+trend | 1 | 0 | 1 | -5 | -0.5 | 5 |" in output
    assert "| rank >10 | 2 | 0 | 2 | -9 | -0.45 | 15 |" in output
    assert "Fresh prospective intersection only" in output
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
    assert "UTC day start / equity" in output
    assert "`1699920000000 / 10010`" in output
    assert "daily realized PnL: `-7.5`" in output
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


def test_renderer_main_accepts_heartbeat_from_stdin() -> None:
    payload = {
        "kind": "continuous-paper-heartbeat",
        "timestamp_ms": 1,
        "paper_only": True,
        "live_orders": False,
        "selected_market_count": 0,
        "selected_markets": [],
        "processed_records": 0,
        "journal_observations": 0,
        "closed_trades": 0,
        "session_closed_trades": 0,
        "positions": [],
        "open_position_count": 0,
        "starting_cash": "10000",
        "cash": "10000",
        "equity": "10000",
        "total_account_pnl": "0",
        "total_return_fraction": "0",
        "realized_gross_pnl": "0",
        "unrealized_pnl": "0",
        "cumulative_fees": "0",
        "cumulative_funding": "0",
        "available_margin": "10000",
        "gross_open_notional": "0",
        "open_planned_risk": "0",
        "open_planned_risk_fraction_of_equity": "0",
        "open_stop_trigger_gross_pnl": "0",
        "open_stop_trigger_gross_r": None,
        "open_positions_with_profit_protected_stop": 0,
        "execution_healthy": True,
        "execution_reason_codes": [],
        "session_decision_epochs": 0,
        "session_decisions": {},
        "session_decision_reason_counts": {},
        "session_risk": {},
        "session_opening_execution_attempts": 0,
        "session_opening_fills": 0,
    }
    env = dict(os.environ)
    env.pop("HEARTBEAT_JSON", None)
    completed = subprocess.run(
        [sys.executable, SCRIPT],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    assert "Continuous paper runtime live status" in completed.stdout


def test_renderer_omits_full_heartbeat_and_bounds_oversized_issue_body() -> None:
    payload = {
        "kind": "continuous-paper-heartbeat",
        "timestamp_ms": 1,
        "paper_only": True,
        "live_orders": False,
        "selected_market_count": 0,
        "selected_markets": [],
        "processed_records": 0,
        "journal_observations": 0,
        "closed_trades": 0,
        "session_closed_trades": 0,
        "positions": [],
        "open_position_count": 0,
        "starting_cash": "10000",
        "cash": "10000",
        "equity": "10000",
        "total_account_pnl": "0",
        "total_return_fraction": "0",
        "realized_gross_pnl": "0",
        "unrealized_pnl": "0",
        "cumulative_fees": "0",
        "cumulative_funding": "0",
        "available_margin": "10000",
        "gross_open_notional": "0",
        "open_planned_risk": "0",
        "open_planned_risk_fraction_of_equity": "0",
        "open_stop_trigger_gross_pnl": "0",
        "open_stop_trigger_gross_r": None,
        "open_positions_with_profit_protected_stop": 0,
        "execution_healthy": True,
        "execution_reason_codes": [],
        "session_decision_epochs": 0,
        "session_decisions": {},
        "session_decision_reason_counts": {},
        "session_risk": {},
        "session_opening_execution_attempts": 0,
        "session_opening_fills": 0,
        "last_observation": {"blob": "x" * 300_000},
    }
    completed = subprocess.run(
        [sys.executable, SCRIPT],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env={key: value for key, value in os.environ.items() if key != "HEARTBEAT_JSON"},
    )

    assert len(completed.stdout) <= 240_000
    assert "Full heartbeat JSON" not in completed.stdout
    assert "body was compacted" in completed.stdout
    assert "audit authority" in completed.stdout


def test_exact_stop_l2_renderer_keeps_execution_reality_separate() -> None:
    lines = _delayed_entry_stop_l2_lines(
        {
            "enabled": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "prospective_manager_triggered_original_stop_visible_l2_"
                "first_ioc_replay"
            ),
            "capture_started_at_ms": 1_700_000_000_000,
            "pre_capture_legacy_outcomes": 9,
            "source_counts": {
                "full_visible_book_ioc": 8,
                "expired": 2,
            },
            "non_evaluable_entry_outcomes": 2,
            "non_evaluable_source_counts": {
                "expired": 2,
            },
            "missing_journal_trades": 0,
            "missing_exact_paths": 0,
            "incomplete_or_gapped_paths": 0,
            "missing_funding_events": 0,
            "lineage_mismatches": 0,
            "invalid_candidate_timing": 0,
            "stop_book_capture_errors": 0,
            "overall": {
                "evaluated_filled_candidates": 8,
                "mark_stop_crossings": 4,
                "captured_stop_plans": 3,
                "full_stop_exits": 2,
                "partial_stop_exits": 1,
                "no_fill_stop_exits": 0,
                "full_ioc_position_remainders": 1,
                "planning_or_execution_rejections": 0,
                "pending_stop_evidence": 0,
                "stop_capture_unreliable": 0,
                "resolved_candidates": 6,
                "unresolved_stop_actions": 2,
                "resolved_actual_net_pnl": "-8",
                "resolved_candidate_net_pnl": "-2",
                "resolved_delta_vs_actual": "6",
                "same_exit_pnl_on_full_stop_exits": "7",
                "exact_pnl_on_full_stop_exits": "-3",
                "same_exit_minus_exact_on_full_stop_exits": "10",
                "transient_mark_crossings_without_stop_plan": 1,
                "late_funding_boundaries_excluded": 2,
            },
            "readiness": {
                "integrity_clean": True,
                "complete_counterfactual_cohort": False,
                "min_full_stop_exits": 5,
                "missing_full_stop_exits": 3,
                "ready_for_descriptive_review": False,
            },
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "### 60s delayed-entry exact stop L2 replay" in output
    assert "delayed-entry source counts" in output
    assert "`expired=2, full_visible_book_ioc=8`" in output
    assert "post-capture non-evaluable entries / sources" in output
    assert "`2 / expired=2`" in output
    assert (
        "upstream integrity misses journal / path / gaps / funding / "
        "lineage / timing / stop-book" in output
    )
    assert "`0 / 0 / 0 / 0 / 0 / 0 / 0`" in output
    assert "evaluated / mark crossings / captured stop plans" in output
    assert "`8 / 4 / 3`" in output
    assert "full / partial / no-fill / quantized remainder exits" in output
    assert "`2 / 1 / 0 / 1`" in output
    assert "resolved / unresolved stop actions" in output
    assert "`6 / 2`" in output
    assert "full-stop same-exit / exact PnL / removed edge" in output
    assert "`7 / -3 / 10`" in output
    assert "no synthetic remainder exit is invented" in output


def test_combined_entry_filter_renderer_shows_frozen_intersection() -> None:
    lines = _prospective_combined_entry_filter_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-top10-no-long-trend-v1",
            "started_at_ms": 123,
            "rule": {
                "max_admitted_ordinal": 10,
                "max_rank_age_ms": 300000,
            },
            "prospective_closed_trades": 4,
            "attributed_trades": 4,
            "allowed_trades": 1,
            "blocked_trades": 3,
            "allowed_wins": 1,
            "allowed_losses": 0,
            "blocked_wins": 0,
            "blocked_losses": 3,
            "allowed_net_pnl": "5",
            "blocked_net_pnl": "-21",
            "actual_net_pnl": "-16",
            "candidate_trade_contribution_pnl": "5",
            "delta_trade_contribution_pnl": "21",
            "decision_attribution_misses": 0,
            "missing_rank_evidence": 0,
            "stale_rank_evidence": 0,
            "by_block_reason": {
                "long_trend": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "net_pnl": "-8",
                    "mean_net_r": "-0.8",
                    "mean_ordinal": "5",
                },
                "rank_above_10": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "net_pnl": "-6",
                    "mean_net_r": "-0.6",
                    "mean_ordinal": "15",
                },
                "long_trend_and_rank_above_10": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "net_pnl": "-7",
                    "mean_net_r": "-0.7",
                    "mean_ordinal": "16",
                },
            },
            "readiness": {
                "integrity_clean": True,
                "ready_for_review": False,
                "min_prospective_closed_trades": 30,
                "min_blocked_trades": 10,
                "min_allowed_trades": 10,
                "missing_prospective_closed_trades": 26,
                "missing_blocked_trades": 7,
                "missing_allowed_trades": 9,
            },
            "error": None,
        }
    )
    output = "\n".join(lines)
    assert "top-10 + no LONG-trend" in output
    assert "`-16 / 5 / 21`" in output
    assert "LONG+trend & rank >10" in output
    assert "earlier standalone LONG+trend and top-10 studies" in output


def test_combined_matched_overlap_renderer_is_explicitly_descriptive() -> None:
    lines = _prospective_combined_matched_overlap_lines(
        {
            "enabled": True,
            "entry_filter_started_at_ms": 100,
            "top10_rank_filter_started_at_ms": 200,
            "overlap_started_at_ms": 200,
            "closed_trades_since_overlap_start": 35,
            "matched_trades": 35,
            "integrity_clean": True,
            "allowed_trades": 15,
            "blocked_trades": 20,
            "allowed_wins": 6,
            "allowed_losses": 9,
            "blocked_wins": 4,
            "blocked_losses": 16,
            "actual_net_pnl": "-100",
            "candidate_trade_contribution_pnl": "-10",
            "delta_trade_contribution_pnl": "90",
            "decision_attribution_misses": 0,
            "missing_rank_evidence": 0,
            "stale_rank_evidence": 0,
            "fresh_combined_gate_credit": 0,
            "changes_readiness_gate": False,
            "by_block_reason": {
                "long_trend": {
                    "trades": 9,
                    "net_pnl": "-45",
                },
                "rank_above_10": {
                    "trades": 7,
                    "net_pnl": "-25",
                },
                "long_trend_and_rank_above_10": {
                    "trades": 4,
                    "net_pnl": "-20",
                },
            },
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Matched standalone overlap diagnostic" in output
    assert "`100 / 200 / 200`" in output
    assert "`35 / 35 / true`" in output
    assert "`-100 / -10 / 90`" in output
    assert "`9 · -45 / 7 · -25 / 4 · -20`" in output
    assert "fresh combined gate credit" in output
    assert "`0 / false`" in output
    assert "cannot advance the fresh combined prospective gate" in output

def test_opening_opportunity_renderer_exposes_capture_completeness() -> None:
    lines = _opening_opportunity_evidence_lines(
        {
            "enabled": True,
            "records": 12,
            "baseline_approvals": 8,
            "baseline_rejections": 4,
            "rank_complete": 11,
            "rank_missing": 1,
            "state_digest": "a" * 64,
            "capture_error": None,
            "forward_mark_paths": 12,
            "forward_mark_paths_complete": 7,
            "forward_mark_max_age_ms": 21_600_000,
            "forward_mark_state_digest": "b" * 64,
            "forward_mark_capture_error": None,
            "exit_book_capture_started_at_ms": 1_000,
            "exit_book_registered_opportunities": 9,
            "exit_book_captures": 14,
            "exit_book_pending": 18,
            "exit_book_missed": 4,
            "exit_book_horizons_ms": [
                300_000,
                900_000,
                3_600_000,
                21_600_000,
            ],
            "exit_book_max_capture_lag_ms": 120_000,
            "exit_book_state_digest": "c" * 64,
            "exit_book_enabled": True,
            "exit_book_capture_error": None,
            "full_l2_book_captured": True,
            "exact_risk_request_captured": True,
            "replacement_trades_modeled": False,
        }
    )
    output = "\n".join(lines)

    assert "Opening opportunity evidence" in output
    assert "`12 / 8 / 4`" in output
    assert "`11 / 1`" in output
    assert "`true / true`" in output
    assert "`12 / 7`" in output
    assert "`21600000`ms" in output
    assert "`9 / 14 / 18 / 4`" in output
    assert "`120000`ms" in output
    assert "`" + "b" * 64 + "`" in output
    assert "`" + "c" * 64 + "`" in output
    assert "exit-book capture enabled: `true`" in output
    assert "replacement trades modeled: `false`" in output
    assert "forward mark paths" in output
    assert "real horizon L2 exit books" in output
    assert "never retroactively" in output


def test_replacement_funding_renderer_exposes_boundary_coverage() -> None:
    lines = _replacement_funding_evidence_lines(
        {
            "enabled": True,
            "capture_started_at_ms": 1_000,
            "registered_opportunities": 4,
            "required_boundaries": 9,
            "oracle_candidates": 7,
            "captured_boundaries": 6,
            "pending_boundaries": 2,
            "missed_boundaries": 1,
            "max_window_ms": 21_720_250,
            "max_oracle_age_ms": 5_000,
            "max_funding_capture_lag_ms": 300_000,
            "state_digest": "d" * 64,
            "capture_error": None,
            "funding_pnl_modeled": False,
        }
    )
    output = "\n".join(lines)

    assert "Replacement funding boundary evidence" in output
    assert "`1000 / 4`" in output
    assert "`9 / 7 / 6`" in output
    assert "`2 / 1`" in output
    assert "`5000`ms" in output
    assert "`300000`ms" in output
    assert "funding PnL modeled: `false`" in output
    assert "`" + "d" * 64 + "`" in output
    assert "observed before the boundary" in output


def test_capacity_reflow_fill_renderer_exposes_exact_entry_shadow() -> None:
    lines = _prospective_capacity_reflow_fill_feasibility_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-top10-no-long-trend-v1",
            "candidate_caused_release_options": 5,
            "candidate_caused_release_opportunities": 5,
            "conservative_risk_approvals": 5,
            "planning_approvals": 5,
            "fillable_options": 4,
            "full_fill_options": 3,
            "partial_fill_options": 1,
            "no_fill_options": 1,
            "execution_rejected_options": 0,
            "gross_fill_notional": "1200",
            "taker_fees": "0.54",
            "counterfactual_equity_delta_min": "-2",
            "counterfactual_equity_delta_max": "4",
            "by_opportunity_market": {"SOL": 3, "XRP": 2},
            "by_release_market": {"CRV": 5},
            "by_risk_rejection": {},
            "by_planning_rejection": {},
            "by_execution_result": {
                "full": 3,
                "no_fill": 1,
                "partial": 1,
            },
            "counterfactual_account_scope": (
                "same_utc_day_release_position_exact_cash_"
                "margin_and_equity_with_conservative_peak_bound"
            ),
            "replacement_entry_fills_modeled": True,
            "replacement_exits_modeled": False,
            "pnl_modeled": False,
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Candidate-caused replacement entry fill shadow" in output
    assert "`5 / 5`" in output
    assert "`5 / 5 / 4`" in output
    assert "`3 / 1 / 1 / 0`" in output
    assert "CRV=5" in output
    assert "full=3" in output
    assert "true / false / false" in output
    assert "exact captured decision-time L2 IOC" in output


def test_capacity_reflow_renderer_exposes_observed_release_sensitivity() -> None:
    lines = _prospective_capacity_reflow_opportunity_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-top10-no-long-trend-v1",
            "opportunities": 10,
            "baseline_rejections": 10,
            "candidate_eligible_rejections": 4,
            "candidate_blocked_rejections": 6,
            "missing_rank_evidence": 0,
            "stale_rank_evidence": 0,
            "integrity_clean": True,
            "candidate_eligible_capacity_rejections": 3,
            "single_position_release_unblocked": 2,
            "single_position_release_options": 3,
            "by_baseline_rejection_reason": {
                "correlation_bucket_exhausted": 8,
                "aggregate_risk_exhausted": 2,
            },
            "by_candidate_block_reason": {
                "long_trend": 4,
                "rank_above_10": 2,
            },
            "by_release_market": {"BTC": 2, "ETH": 1},
            "by_release_bucket": {"majors": 3},
            "replacement_trades_modeled": False,
            "pnl_modeled": False,
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Candidate capacity-reflow opportunity diagnostic" in output
    assert "`10 / 10`" in output
    assert "`4 / 6`" in output
    assert "`3 / 2`" in output
    assert "correlation_bucket_exhausted=8" in output
    assert "BTC=2" in output
    assert "replacement trades / PnL modeled: `false / false`" in output
    assert "does not yet claim" in output


def test_capacity_reflow_release_lineage_renderer_exposes_causal_join() -> None:
    lines = _prospective_capacity_reflow_release_lineage_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-top10-no-long-trend-v1",
            "release_options": 5,
            "resolved_release_options": 5,
            "resolved_opportunities": 3,
            "candidate_blocked_release_options": 2,
            "candidate_allowed_release_options": 3,
            "candidate_capacity_release_opportunities": 2,
            "release_lineage_misses": 0,
            "release_plan_misses": 0,
            "release_decision_misses": 0,
            "release_rank_misses": 0,
            "release_stale_ranks": 0,
            "integrity_clean": True,
            "by_release_position_block_reason": {
                "long_trend": 2,
            },
            "by_candidate_blocked_release_market": {
                "BTC": 1,
                "SOL": 1,
            },
            "replacement_trades_modeled": False,
            "pnl_modeled": False,
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Candidate-filtered capacity release lineage" in output
    assert "`5 / 5`" in output
    assert "`3 / 2`" in output
    assert "`2 / 3`" in output
    assert "`0 / 0 / 0 / 0 / 0`" in output
    assert "long_trend=2" in output
    assert "BTC=1" in output
    assert "replacement trades / PnL modeled: `false / false`" in output
    assert "exact historical opening plan" in output


def test_capacity_reflow_exit_fill_renderer_exposes_real_l2_closes() -> None:
    lines = _prospective_capacity_reflow_exit_fill_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-top10-no-long-trend-v1",
            "fillable_options": 5,
            "exit_book_records": 7,
            "by_horizon": {
                "300000": {
                    "captured_exit_books": 5,
                    "missing_exit_books": 0,
                    "full_exit_fills": 3,
                    "partial_exit_fills": 2,
                    "no_exit_fills": 0,
                    "rejected_exit_attempts": 0,
                    "entry_exit_fee_adjusted_pnl": "12.5",
                    "unclosed_quantity": "4",
                },
                "21600000": {
                    "captured_exit_books": 0,
                    "missing_exit_books": 5,
                    "full_exit_fills": 0,
                    "partial_exit_fills": 0,
                    "no_exit_fills": 0,
                    "rejected_exit_attempts": 0,
                    "entry_exit_fee_adjusted_pnl": "0",
                    "unclosed_quantity": "0",
                },
            },
            "replacement_entry_fills_modeled": True,
            "replacement_exit_fills_modeled": True,
            "funding_modeled": False,
            "replacement_trade_pnl_complete": False,
            "realized_pnl_claimed": False,
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Candidate-caused replacement exit fills" in output
    assert "`5 / 7`" in output
    assert "| 5m | 5 | 0 | 3 | 2 | 0 | 0 | 12.5 | 4 |" in output
    assert "| 6h | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 0 |" in output
    assert "`true / true / false / false / false`" in output
    assert "real captured L2 book" in output


def test_capacity_reflow_realized_pnl_renderer_exposes_exact_scope() -> None:
    lines = _prospective_capacity_reflow_realized_pnl_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-top10-no-long-trend-v1",
            "exact_realized_pnl_option_horizons": 4,
            "funding_evidence_records": 3,
            "by_horizon": {
                "300000": {
                    "options": 5,
                    "simulated_exits": 5,
                    "complete_closes": 4,
                    "zero_funding_boundary_closes": 3,
                    "funding_evidence_required_closes": 1,
                    "funding_evidence_complete_closes": 1,
                    "funding_evidence_missing_closes": 0,
                    "incomplete_or_missing_exits": 1,
                    "exact_realized_pnl_options": 4,
                    "funding_cash_pnl": "-0.2",
                    "exact_realized_pnl": "9.3",
                },
                "3600000": {
                    "options": 5,
                    "simulated_exits": 5,
                    "complete_closes": 4,
                    "zero_funding_boundary_closes": 0,
                    "funding_evidence_required_closes": 4,
                    "funding_evidence_complete_closes": 2,
                    "funding_evidence_missing_closes": 2,
                    "incomplete_or_missing_exits": 1,
                    "exact_realized_pnl_options": 2,
                    "funding_cash_pnl": "0.4",
                    "exact_realized_pnl": "-1.6",
                },
            },
            "funding_evidence_modeled": True,
            "zero_funding_boundary_is_exact_zero_funding": True,
            "cross_horizon_economics_aggregated": False,
            "strategy_level_realized_pnl_claimed": False,
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Exact replacement realized PnL" in output
    assert "exact option-horizons available / funding evidence records" in output
    assert "`4 / 3`" in output
    assert "| 5m | 5 | 5 | 4 | 3 | 1 | 0 | 1 | -0.2 | 9.3 |" in output
    assert "| 1h | 5 | 5 | 4 | 0 | 2 | 2 | 1 | 0.4 | -1.6 |" in output
    assert "`true / true / false / false`" in output
    assert "never estimated or backfilled" in output

def test_prospective_replacement_exit_policy_renderer_exposes_freeze() -> None:
    lines = _prospective_replacement_exit_policy_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-replacement-5m-real-l2-exit-v1",
            "started_at_ms": 1_800_000_000_000,
            "exit_horizon_ms": 300_000,
            "discovery_options_excluded": 5,
            "discovery_cohort_reused_for_validation": False,
            "prospective_options": 3,
            "exact_realized_pnl_options": 2,
            "incomplete_options": 1,
            "wins": 1,
            "losses": 1,
            "breakeven": 0,
            "exact_realized_pnl": "0.5",
            "mean_exact_realized_pnl": "0.25",
            "zero_boundary_exact_options": 1,
            "funded_exact_options": 1,
            "incomplete_reason_counts": {
                "funding_evidence_required": 1
            },
            "cross_horizon_selection_frozen": True,
            "strategy_level_pnl_claimed": False,
            "state_restore_error": None,
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Prospective 5m replacement exit candidate" in output
    assert "prospective-replacement-5m-real-l2-exit-v1" in output
    assert "`1800000000000 / 300000ms`" in output
    assert "`5 / false`" in output
    assert "`3 / 2 / 1`" in output
    assert "`1 / 1 / 0`" in output
    assert "`0.5 / 0.25`" in output
    assert "funding_evidence_required=1" in output
    assert "`true / false`" in output
    assert "only opportunities observed after the durable freeze" in output


def test_replacement_exit_robustness_renderer_exposes_concentration() -> None:
    lines = _prospective_replacement_exit_robustness_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-replacement-5m-real-l2-exit-v1",
            "prospective_options": 12,
            "exact_options": 10,
            "incomplete_options": 2,
            "exact_coverage_fraction": "0.8333333333333333333333333333",
            "minimum_exact_options_for_review": 30,
            "sample_ready_for_review": False,
            "total_exact_realized_pnl": "14",
            "gross_profit": "22",
            "gross_loss_abs": "8",
            "profit_factor": "2.75",
            "largest_abs_option_pnl": "7",
            "largest_abs_option_market": "SOL",
            "largest_abs_option_share": "0.2333",
            "leave_one_option_out_min_pnl": "7",
            "positive_after_any_single_option_removed": True,
            "largest_abs_market": "SOL",
            "largest_abs_market_pnl": "9",
            "largest_abs_market_share": "0.3",
            "leave_one_market_out_min_pnl": "5",
            "positive_after_any_single_market_removed": True,
            "temporal": {
                "full_blocks": 2,
                "positive_full_blocks": 2,
                "all_full_blocks_positive": False,
            },
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Prospective 5m replacement exit robustness" in output
    assert "`12 / 10 / 2 / 0.8333333333333333333333333333`" in output
    assert "`10 / 30 / false`" in output
    assert "`14 / 22 / 8 / 2.75`" in output
    assert "`7 / SOL / 0.2333`" in output
    assert "`7 / true`" in output
    assert "`SOL / 9 / 0.3`" in output
    assert "`5 / true`" in output
    assert "`2 / 2 / false`" in output
    assert "cannot change the fixed 5-minute rule" in output


def test_replacement_exit_readiness_renderer_exposes_frozen_gate() -> None:
    lines = _prospective_replacement_exit_readiness_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-replacement-5m-real-l2-exit-v1",
            "ready_for_review": False,
            "promotion_authority": False,
            "execution_authority": False,
            "exact_options": 12,
            "missing_exact_options": 18,
            "total_exact_realized_pnl": "8",
            "profit_factor": "1.4",
            "positive_after_any_single_option_removed": True,
            "positive_after_any_single_market_removed": False,
            "temporal_full_blocks": 2,
            "temporal_positive_full_blocks": 2,
            "temporal_all_full_blocks_positive": False,
            "failed_requirements": [
                "minimum_exact_options",
                "positive_after_any_single_market_removed",
                "all_four_full_chronological_blocks_positive",
            ],
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Prospective 5m replacement exit review gate" in output
    assert "`false / false / false`" in output
    assert "`12 / 18`" in output
    assert "`8 / 1.4`" in output
    assert "`true / false`" in output
    assert "`2 / 2 / false`" in output
    assert "minimum_exact_options" in output
    assert "ready for human review" in output


def test_capacity_reflow_forward_excursion_renderer_exposes_giveback() -> None:
    lines = _prospective_capacity_reflow_forward_excursion_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-top10-no-long-trend-v1",
            "fillable_options": 5,
            "paths_available": 5,
            "paths_missing": 0,
            "by_horizon": {
                "300000": {
                    "settled_options": 5,
                    "pending_options": 0,
                    "stale_options": 0,
                    "missing_path_options": 0,
                    "positive_peak_options": 4,
                    "negative_end_options": 3,
                    "positive_peak_to_negative_end_options": 2,
                    "best_entry_fee_adjusted_mtm_pnl": "42",
                    "ending_entry_fee_adjusted_mtm_pnl": "22",
                    "peak_to_end_giveback_pnl": "20",
                    "mean_time_to_best_ms": 180000,
                },
                "21600000": {
                    "settled_options": 0,
                    "pending_options": 5,
                    "stale_options": 0,
                    "missing_path_options": 0,
                    "positive_peak_options": 0,
                    "negative_end_options": 0,
                    "positive_peak_to_negative_end_options": 0,
                    "best_entry_fee_adjusted_mtm_pnl": "0",
                    "ending_entry_fee_adjusted_mtm_pnl": "0",
                    "peak_to_end_giveback_pnl": "0",
                    "mean_time_to_best_ms": None,
                },
            },
            "replacement_forward_excursions_modeled": True,
            "replacement_exits_modeled": False,
            "realized_pnl_modeled": False,
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Candidate-caused replacement forward excursion" in output
    assert "`5 / 5 / 0`" in output
    assert "| 5m | 5 | 0 | 0 | 0 | 4 | 3 | 2 | 42 | 22 | 20 | 180000ms |" in output
    assert "| 6h | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | n/a |" in output
    assert "`true / false / false`" in output
    assert "decay and reversals" in output


def test_capacity_reflow_forward_markout_renderer_exposes_horizons() -> None:
    lines = _prospective_capacity_reflow_forward_markout_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-top10-no-long-trend-v1",
            "fillable_options": 3,
            "paths_available": 2,
            "paths_missing": 1,
            "max_mark_lag_ms": 120_000,
            "by_horizon": {
                "300000": {
                    "settled_options": 2,
                    "pending_options": 0,
                    "stale_options": 0,
                    "missing_path_options": 1,
                    "positive_options": 1,
                    "negative_options": 1,
                    "flat_options": 0,
                    "gross_mark_to_market_pnl": "4",
                    "entry_fee_adjusted_mark_to_market_pnl": "3.5",
                    "mean_directional_return_fraction": "0.01",
                },
                "21600000": {
                    "settled_options": 0,
                    "pending_options": 2,
                    "stale_options": 0,
                    "missing_path_options": 1,
                    "positive_options": 0,
                    "negative_options": 0,
                    "flat_options": 0,
                    "gross_mark_to_market_pnl": "0",
                    "entry_fee_adjusted_mark_to_market_pnl": "0",
                    "mean_directional_return_fraction": None,
                },
            },
            "replacement_entry_fills_modeled": True,
            "replacement_forward_markouts_modeled": True,
            "replacement_exits_modeled": False,
            "realized_pnl_modeled": False,
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Candidate-caused replacement forward markouts" in output
    assert "`3 / 2 / 1`" in output
    assert "| 5m | 2 | 0 | 0 | 1 | 1 / 1 / 0 | 4 | 3.5 | 0.01 |" in output
    assert "| 6h | 0 | 2 | 0 | 1 | 0 / 0 / 0 | 0 | 0 | None |" in output
    assert "`true / true / false / false`" in output
    assert "no synthetic exit fill" in output


def test_daily_loss_lockout_reflow_renderer_exposes_exact_unlocks() -> None:
    lines = _prospective_daily_loss_lockout_reflow_lines(
        {
            "enabled": True,
            "candidate_id": "prospective-top10-no-long-trend-v1",
            "daily_loss_lockout_opportunities": 10,
            "candidate_rule_eligible_lockout_opportunities": 2,
            "candidate_eligible_lockout_opportunities": 2,
            "candidate_blocked_lockout_opportunities": 8,
            "account_day_verified_lockout_opportunities": 2,
            "account_day_unverified_lockout_opportunities": 0,
            "account_day_mismatch_lockout_opportunities": 0,
            "account_day_provenance_complete": True,
            "opportunity_missing_rank_evidence": 0,
            "opportunity_stale_rank_evidence": 0,
            "opportunity_integrity_clean": True,
            "causal_opportunity_integrity_clean": True,
            "same_day_closed_trade_instances": 8,
            "cross_day_closed_trade_instances": 2,
            "cross_day_cash_modeled_instances": 2,
            "cross_day_cash_model_misses": 0,
            "cross_day_cash_model_complete": True,
            "cross_day_trade_cash_effects_modeled": True,
            "open_position_instances": 0,
            "baseline_cash_reconciliation_misses": 0,
            "baseline_cash_reconciliation_clean": True,
            "candidate_blocked_closed_trade_instances": 4,
            "candidate_blocked_cross_day_trade_instances": 1,
            "distinct_candidate_blocked_trade_ids": 2,
            "trade_decision_attribution_misses": 0,
            "trade_rank_attribution_misses": 0,
            "trade_stale_rank_attribution": 0,
            "closed_trade_adjusted_unlock_opportunities": 2,
            "exact_cash_scope_opportunities": 2,
            "exact_candidate_unlock_opportunities": 2,
            "baseline_daily_realized_pnl_min": "-120",
            "baseline_daily_realized_pnl_max": "-105",
            "candidate_daily_realized_pnl_min": "-80",
            "candidate_daily_realized_pnl_max": "-60",
            "daily_loss_threshold_min": "-100",
            "daily_loss_threshold_max": "-100",
            "removed_blocked_trade_net_pnl_min": "-60",
            "removed_blocked_trade_net_pnl_max": "-40",
            "removed_blocked_trade_cash_pnl_min": "-60",
            "removed_blocked_trade_cash_pnl_max": "-40",
            "cross_day_daily_cash_min": "-20",
            "cross_day_daily_cash_max": "-20",
            "by_removed_trade_block_reason": {"long_trend": 4},
            "error": None,
        }
    )
    output = "\n".join(lines)

    assert "Candidate daily-loss lockout reflow" in output
    assert "`10 / 2 / 8`" in output
    assert "causal eligible after account-day verification: `2`" in output
    assert "`2 / 0 / 0 / true`" in output
    assert "causal opportunity integrity clean: `true`" in output
    assert "`2 / 2 / 2`" in output
    assert "cross-day cash modeled / misses / complete" in output
    assert "`2 / 0 / true`" in output
    assert "candidate-blocked cross-day trade instances: `1`" in output
    assert "baseline cash reconciliation misses / clean" in output
    assert "`0 / true`" in output
    assert "cross-day trade cash effects modeled: `true`" in output
    assert "cross-day reconstructed daily cash range" in output
    assert "long_trend=4" in output
    assert "authoritative" in output
    assert "open-position cash effects modeled: `false`" in output


def test_prospective_filter_robustness_renderer_exposes_concentration() -> None:
    lines = _prospective_filter_robustness_lines(
        {
            "total_delta_trade_contribution_pnl": "41",
            "largest_abs_trade_contribution": "23",
            "largest_abs_trade_share": "0.56",
            "leave_one_trade_out_min_delta": "18",
            "positive_after_any_single_trade_removed": True,
            "largest_abs_market": "ALGO",
            "largest_abs_market_contribution": "23",
            "largest_abs_market_share": "0.56",
            "leave_one_market_out_min_delta": "18",
            "positive_after_any_single_market_removed": True,
            "temporal": {
                "full_blocks": 4,
                "positive_full_blocks": 3,
                "all_full_blocks_positive": False,
            },
        }
    )
    output = "\n".join(lines)

    assert "robustness delta / largest trade contribution / share" in output
    assert "`41 / 23 / 0.56`" in output
    assert "leave-one-trade min delta" in output
    assert "`18 / true`" in output
    assert "largest market / contribution / share" in output
    assert "`ALGO / 23 / 0.56`" in output
    assert "chronological full blocks / positive / all positive" in output
    assert "`4 / 3 / false`" in output
    assert "does not change the frozen prospective readiness gate" in output


def test_allowed_residual_renderer_exposes_remaining_loss_clusters() -> None:
    lines = _prospective_allowed_residual_lines(
        {
            "overall": {
                "trades": 6,
                "net_pnl": "-4",
                "winner_pnl": "12",
                "loser_pnl": "-16",
                "complete_excursion_losses": 3,
                "missing_or_incomplete_excursion_losses": 1,
                "losses_with_mfe_lt_0_25r": 1,
                "losses_with_mfe_0_25_to_lt_0_5r": 1,
                "losses_after_mfe_ge_0_5r": 2,
                "losses_after_mfe_ge_1r": 1,
                "loss_pnl_with_mfe_lt_0_25r": "-8",
                "loss_pnl_with_mfe_0_25_to_lt_0_5r": "-1",
                "loss_pnl_after_mfe_ge_0_5r": "-7",
                "loss_pnl_after_mfe_ge_1r": "-4",
            },
            "by_side": {
                "long": {
                    "trades": 2,
                    "net_pnl": "-9",
                },
                "short": {
                    "trades": 4,
                    "net_pnl": "5",
                },
            },
            "by_lead_strategy": {
                "breakout": {
                    "trades": 3,
                    "net_pnl": "-7",
                },
                "trend": {
                    "trades": 3,
                    "net_pnl": "3",
                },
            },
            "by_rank_band": {
                "1-5": {
                    "trades": 2,
                    "net_pnl": "-6",
                },
                "6-10": {
                    "trades": 4,
                    "net_pnl": "2",
                },
            },
            "worst_side_lead_strategy": {
                "label": "long:breakout",
                "net_pnl": "-8",
                "trades": 2,
            },
            "worst_market": {
                "label": "SOL",
                "net_pnl": "-10",
                "trades": 2,
            },
            "worst_market_never_worked": {
                "label": "SOL",
                "losses": 1,
                "loss_pnl": "-8",
            },
            "worst_market_giveback": {
                "label": "ETH",
                "losses": 1,
                "loss_pnl": "-4",
            },
            "worst_side_lead_strategy_never_worked": {
                "label": "long:breakout",
                "losses": 1,
                "loss_pnl": "-8",
            },
            "worst_side_lead_strategy_giveback": {
                "label": "short:trend",
                "losses": 1,
                "loss_pnl": "-4",
            },
        }
    )
    output = "\n".join(lines)

    assert "allowed residual trades / net / winner PnL / loser PnL" in output
    assert "`6 / -4 / 12 / -16`" in output
    assert "long=n2/pnl-9" in output
    assert "short=n4/pnl5" in output
    assert "breakout=n3/pnl-7" in output
    assert "1-5=n2/pnl-6" in output
    assert "long:breakout / -8 / n2" in output
    assert "SOL / -10 / n2" in output
    assert "residual loss shape complete / missing excursion" in output
    assert "`3 / 1`" in output
    assert "never-worked (<0.25R MFE) losses / PnL" in output
    assert "`1 / -8`" in output
    assert "partial-traction (0.25-<0.5R MFE) losses / PnL" in output
    assert "`1 / -1`" in output
    assert "giveback (>=0.5R MFE) losses / PnL" in output
    assert "`2 / -7`" in output
    assert "deep giveback (>=1R MFE) losses / PnL" in output
    assert "`1 / -4`" in output
    assert "worst never-worked market / giveback market" in output
    assert "SOL / -8 / n1" in output
    assert "ETH / -4 / n1" in output
    assert "does not change the frozen filter or readiness gate" in output


def test_fixed_schedule_filter_renderer_exposes_portfolio_effects() -> None:
    lines = _prospective_filter_fixed_schedule_lines(
        {
            "actual": {
                "final_realized_contribution": "-20",
                "max_realized_drawdown": "25",
                "max_concurrent_positions": 3,
                "overlap_openings": 2,
                "max_gross_notional": "1200",
                "max_planned_risk": "60",
            },
            "candidate": {
                "final_realized_contribution": "5",
                "max_realized_drawdown": "8",
                "max_concurrent_positions": 2,
                "overlap_openings": 1,
                "max_gross_notional": "700",
                "max_planned_risk": "35",
            },
            "delta_final_realized_contribution": "25",
            "delta_max_realized_drawdown": "-17",
            "delta_max_gross_notional": "-500",
            "delta_max_planned_risk": "-25",
            "blocked_actual_net_pnl": "-25",
            "admitted_trades": 8,
            "blocked_trades": 4,
        }
    )
    output = "\n".join(lines)

    assert "actual / candidate / delta realized contribution" in output
    assert "`-20 / 5 / 25`" in output
    assert "max realized drawdown actual / candidate / delta" in output
    assert "`25 / 8 / -17`" in output
    assert "max positions / overlap actual→candidate" in output
    assert "`3 / 2 → 2 / 1`" in output
    assert "max gross notional actual / candidate / delta" in output
    assert "`1200 / 700 / -500`" in output
    assert "max planned risk actual / candidate / delta" in output
    assert "`60 / 35 / -25`" in output
    assert "fixed-schedule blocked PnL / admitted / blocked" in output
    assert "`-25 / 8 / 4`" in output
    assert "replacement trades, equity-driven resizing" in output


def test_cadence_opportunity_learning_renderer_shows_primary_surfaces() -> None:
    lines = _cadence_opportunity_learning_lines(
        {
            "enabled": True,
            "error": None,
            "settled_outcomes": 1000,
            "model_family": "hierarchical_grouped_mean_v1",
            "primary_ready_for_review": True,
            "development_qualified": False,
            "surfaces": {
                "900000:900000": {
                    "status": "completed",
                    "training_rows": 400,
                    "validation_rows": 100,
                    "purged_overlap_rows": 1,
                    "admitted_rows": 25,
                    "skipped_rows": 75,
                    "actual_net_return_sum": "-0.4",
                    "candidate_net_return_sum": "0.2",
                    "delta_net_return_sum": "0.6",
                    "by_direction": {
                        "long": {"admitted_rows": 12},
                        "short": {"admitted_rows": 13},
                    },
                    "stability_blocks": (
                        {"passes": True},
                        {"passes": False},
                    ),
                    "admitted_cohorts": (
                        {
                            "direction": "long",
                            "lead_strategy": "mean_reversion",
                            "score_band": "80+",
                            "training_estimate_mean_net_return": "0.004",
                            "training_estimate_rows": 44,
                            "training_estimate_specificity": (
                                "direction_strategy_score"
                            ),
                            "validation_rows": 8,
                            "validation_mean_net_return": "0.006",
                            "validation_net_return_sum": "0.048",
                        },
                    ),
                    "skipped_cohorts": (
                        {
                            "direction": "short",
                            "lead_strategy": "breakout",
                            "score_band": "70-<75",
                            "training_estimate_mean_net_return": "-0.003",
                            "training_estimate_rows": 31,
                            "training_estimate_specificity": (
                                "direction_strategy_score"
                            ),
                            "validation_rows": 7,
                            "validation_mean_net_return": "-0.004",
                            "validation_net_return_sum": "-0.028",
                        },
                    ),
                },
                "900000:3600000": {
                    "status": "completed",
                    "training_rows": 390,
                    "validation_rows": 100,
                    "purged_overlap_rows": 4,
                    "admitted_rows": 30,
                    "skipped_rows": 70,
                    "actual_net_return_sum": "-0.3",
                    "candidate_net_return_sum": "0.1",
                    "delta_net_return_sum": "0.4",
                    "by_direction": {
                        "long": {"admitted_rows": 14},
                        "short": {"admitted_rows": 16},
                    },
                    "stability_blocks": (
                        {"passes": True},
                        {"passes": True},
                    ),
                },
            },
        }
    )
    rendered = "\n".join(lines)
    assert "Cadence opportunity learning" in rendered
    assert "15m → 15m" in rendered
    assert "15m → 1h" in rendered
    assert "12" in rendered
    assert "16" in rendered
    assert "development-qualified" in rendered
    assert "Top admitted validation cohorts" in rendered
    assert "mean_reversion" in rendered
    assert "Most negative skipped validation cohorts" in rendered
    assert "breakout" in rendered


def test_operational_heartbeat_renders_without_research_sections() -> None:
    payload = {
        "heartbeat_scope": "operational",
        "timestamp_ms": 1_700_000_000_000,
        "starting_cash": "10000",
        "equity": "10005",
        "total_account_pnl": "5",
        "total_return_fraction": "0.0005",
        "cash": "9990",
        "daily_realized_pnl": "1",
        "unrealized_pnl": "4",
        "realized_gross_pnl": "2",
        "cumulative_fees": "1",
        "cumulative_funding": "0",
        "closed_trades": 3,
        "session_closed_trades": 1,
        "open_planned_risk": "10",
        "open_planned_risk_fraction_of_equity": "0.001",
        "open_stop_trigger_gross_pnl": "2",
        "open_stop_trigger_gross_r": "0.2",
        "open_positions_with_profit_protected_stop": 1,
        "gross_open_notional": "500",
        "gross_open_notional_fraction_of_equity": "0.05",
        "available_margin": "9500",
        "execution_healthy": True,
        "execution_reason_codes": [],
        "selected_market_count": 20,
        "processed_records": 99,
        "journal_observations": 12,
        "session_decision_epochs": 2,
        "last_decision_boundary_ms": 1_699_999_900_000,
        "last_decision_evaluated_at_ms": 1_700_000_000_000,
        "session_decisions": {
            "long": 1,
            "short": 1,
            "no_trade": 38,
        },
        "session_decision_reason_counts": {
            "trend": 1,
            "mean_reversion": 1,
            "NO_SIGNAL": 38,
        },
        "session_risk": {
            "evaluations": 2,
            "approvals": 2,
            "rejections": 0,
            "reason_counts": {"APPROVED": 2},
        },
        "session_opening_execution_attempts": 2,
        "session_opening_fills": 2,
        "positions": [
            {
                "market": "BTC",
                "side": "long",
                "quantity": "0.01",
                "average_entry_price": "100000",
                "stop_price": "99000",
                "latest_mark": "101000",
                "unrealized_gross_pnl": "10",
                "current_gross_r": "1",
                "stop_trigger_gross_pnl": "-10",
                "stop_trigger_gross_r": "-1",
                "stop_protects_profit": False,
                "planned_risk": "10",
            }
        ],
        "recent_closed_trades": [],
        "last_observation": {
            "kind": "execution",
            "market": "BTC",
            "reason_codes": ["OPEN_FILLED"],
        },
    }

    rendered = render_live_status(
        payload,
        run_id="123",
        head_sha="a" * 40,
        predecessor_run_id="122",
    )

    assert "Operational heartbeat only" in rendered
    assert "Worker run: 123" in rendered
    assert "BTC" in rendered
    assert "research telemetry deferred: true" in rendered
    assert "Cadence opportunity learning" not in rendered
    assert "Fixed profit-lock counterfactual" not in rendered


def test_residual_profit_lock_renderer_exposes_exact_path_saves() -> None:
    lines = _prospective_residual_profit_lock_lines(
        {
            "enabled": True,
            "source_error": None,
            "residual_loss_trades": 3,
            "complete_mfe_residual_losses": 3,
            "giveback_residual_losses": 2,
            "deep_giveback_residual_losses": 1,
            "by_rule": {
                "breakeven_after_0_5r": {
                    "matched_exact_path_losses": 3,
                    "missing_exact_path_losses": 0,
                    "triggered_losses": 2,
                    "rescued_to_nonnegative": 1,
                    "actual_net_pnl": "-18",
                    "candidate_net_pnl_estimate": "-8.5",
                    "delta_net_pnl_estimate": "9.5",
                    "giveback_triggered_losses": 2,
                    "giveback_delta_net_pnl_estimate": "9.5",
                    "giveback_delta_net_r_estimate": "0.95",
                    "pnl_robustness": {
                        "positive_after_removing_any_one_loss": True,
                    },
                    "net_r_robustness": {
                        "positive_after_removing_any_one_loss": True,
                    },
                },
                "lock_0_5r_after_1r": {
                    "matched_exact_path_losses": 3,
                    "missing_exact_path_losses": 0,
                    "triggered_losses": 1,
                    "rescued_to_nonnegative": 1,
                    "actual_net_pnl": "-18",
                    "candidate_net_pnl_estimate": "-11",
                    "delta_net_pnl_estimate": "7",
                    "giveback_triggered_losses": 1,
                    "giveback_delta_net_pnl_estimate": "7",
                    "giveback_delta_net_r_estimate": "0.7",
                    "pnl_robustness": {
                        "positive_after_removing_any_one_loss": False,
                    },
                    "net_r_robustness": {
                        "positive_after_removing_any_one_loss": False,
                    },
                },
            },
        }
    )
    output = "\n".join(lines)

    assert "residual losses / complete-MFE / giveback / deep giveback" in output
    assert "`3 / 3 / 2 / 1`" in output
    assert "breakeven_after_0_5r exact-path matched / missing / triggered / rescued" in output
    assert "`3 / 0 / 2 / 1`" in output
    assert "breakeven_after_0_5r actual / candidate / delta PnL" in output
    assert "`-18 / -8.5 / 9.5`" in output
    assert "robust after removing any one loss PnL / R" in output
    assert "`True / True`" in output
    assert "does not change the combined-filter or profit-lock readiness gates" in output


def test_residual_profit_lock_renderer_exposes_source_failure() -> None:
    output = "\n".join(
        _prospective_residual_profit_lock_lines(
            {
                "enabled": False,
                "source_error": "RuntimeError: path boom",
            }
        )
    )

    assert "source unavailable" in output
    assert "RuntimeError: path boom" in output


def test_stop_reentry_renderer_exposes_fixed_windows_and_sides() -> None:
    lines = _closed_trade_stop_reentry_lines(
        {
            "enabled": True,
            "error": None,
            "closed_trades": 12,
            "reentry_trades": 5,
            "fresh_or_reset_trades": 7,
            "reentry_wins": 1,
            "reentry_losses": 4,
            "reentry_net_pnl": "-18",
            "reentry_mean_net_r": "-0.36",
            "fresh_or_reset_wins": 4,
            "fresh_or_reset_losses": 3,
            "fresh_or_reset_net_pnl": "9",
            "fresh_or_reset_mean_net_r": "0.12",
            "by_gap_bucket": {
                "0-5m": {
                    "trades": 2,
                    "wins": 0,
                    "losses": 2,
                    "net_pnl": "-11",
                    "mean_net_r": "-0.55",
                },
                "5-30m": {
                    "trades": 1,
                    "wins": 1,
                    "losses": 0,
                    "net_pnl": "4",
                    "mean_net_r": "0.4",
                },
                "30-120m": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "net_pnl": "-5",
                    "mean_net_r": "-0.5",
                },
                "120m+": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "net_pnl": "-6",
                    "mean_net_r": "-0.6",
                },
            },
            "by_prior_losing_stop_streak": {
                "0": {
                    "trades": 7,
                    "wins": 4,
                    "losses": 3,
                    "net_pnl": "9",
                    "mean_net_r": "0.12",
                },
                "1": {
                    "trades": 2,
                    "wins": 1,
                    "losses": 1,
                    "net_pnl": "2",
                    "mean_net_r": "0.1",
                },
                "2": {
                    "trades": 2,
                    "wins": 0,
                    "losses": 2,
                    "net_pnl": "-14",
                    "mean_net_r": "-0.7",
                },
                "3+": {
                    "trades": 1,
                    "wins": 0,
                    "losses": 1,
                    "net_pnl": "-6",
                    "mean_net_r": "-0.6",
                },
            },
            "skip_after_prior_losing_stops": {
                "after_1": {
                    "blocked_trades": 5,
                    "blocked_winners": 1,
                    "blocked_losses": 4,
                    "blocked_net_pnl": "-18",
                    "delta_trade_contribution_pnl": "18",
                    "robustness": {
                        "leave_one_trade_out_min_delta_pnl": "7",
                        "positive_after_removing_any_one_trade": True,
                    },
                    "market_robustness": {
                        "leave_one_market_out_min_delta_pnl": "4",
                        "positive_after_removing_any_one_market": True,
                    },
                },
                "after_2": {
                    "blocked_trades": 3,
                    "blocked_winners": 0,
                    "blocked_losses": 3,
                    "blocked_net_pnl": "-20",
                    "delta_trade_contribution_pnl": "20",
                    "robustness": {
                        "leave_one_trade_out_min_delta_pnl": "8",
                        "positive_after_removing_any_one_trade": True,
                    },
                    "market_robustness": {
                        "leave_one_market_out_min_delta_pnl": "6",
                        "positive_after_removing_any_one_market": True,
                    },
                },
                "after_3": {
                    "blocked_trades": 1,
                    "blocked_winners": 0,
                    "blocked_losses": 1,
                    "blocked_net_pnl": "-6",
                    "delta_trade_contribution_pnl": "6",
                    "robustness": {
                        "leave_one_trade_out_min_delta_pnl": "0",
                        "positive_after_removing_any_one_trade": False,
                    },
                    "market_robustness": {
                        "leave_one_market_out_min_delta_pnl": "0",
                        "positive_after_removing_any_one_market": False,
                    },
                },
            },
            "skip_windows": {
                "within_5m": {
                    "blocked_trades": 2,
                    "blocked_winners": 0,
                    "blocked_losses": 2,
                    "blocked_net_pnl": "-11",
                    "delta_trade_contribution_pnl": "11",
                    "robustness": {
                        "leave_one_trade_out_min_delta_pnl": "5",
                        "positive_after_removing_any_one_trade": True,
                    },
                },
                "within_30m": {
                    "blocked_trades": 3,
                    "blocked_winners": 1,
                    "blocked_losses": 2,
                    "blocked_net_pnl": "-7",
                    "delta_trade_contribution_pnl": "7",
                    "robustness": {
                        "leave_one_trade_out_min_delta_pnl": "-4",
                        "positive_after_removing_any_one_trade": False,
                    },
                },
                "within_120m": {
                    "blocked_trades": 4,
                    "blocked_winners": 1,
                    "blocked_losses": 3,
                    "blocked_net_pnl": "-12",
                    "delta_trade_contribution_pnl": "12",
                    "robustness": {
                        "leave_one_trade_out_min_delta_pnl": "1",
                        "positive_after_removing_any_one_trade": True,
                    },
                },
            },
            "reentry_by_direction": {
                "long": {
                    "trades": 3,
                    "wins": 1,
                    "losses": 2,
                    "net_pnl": "-6",
                    "mean_net_r": "-0.2",
                },
                "short": {
                    "trades": 2,
                    "wins": 0,
                    "losses": 2,
                    "net_pnl": "-12",
                    "mean_net_r": "-0.6",
                },
            },
        }
    )
    output = "\n".join(lines)

    assert "Same-side stop re-entry attribution" in output
    assert "closed / re-entry / fresh-or-reset trades" in output
    assert "`12 / 5 / 7`" in output
    assert "| 0-5m | 2 | 0 | 2 | -11 | -0.55 |" in output
    assert "| 2 | 2 | 0 | 2 | -14 | -0.7 |" in output
    assert (
        "| >=2 prior stops | 3 | 0 | 3 | -20 | 20 | 8 | 6 | "
        "True | True |" in output
    )
    assert "| <=5m | 2 | 0 | 2 | -11 | 11 | 5 | True |" in output
    assert "| <=30m | 3 | 1 | 2 | -7 | 7 | -4 | False |" in output
    assert "| LONG | 3 | 1 | 2 | -6 | -0.2 |" in output
    assert "| SHORT | 2 | 0 | 2 | -12 | -0.6 |" in output
    assert "most recent completed trade in the same market and same direction" in output
    assert "descriptive only" in output


def test_stop_reentry_renderer_exposes_failure() -> None:
    output = "\n".join(
        _closed_trade_stop_reentry_lines(
            {
                "enabled": False,
                "error": "RuntimeError: reentry boom",
            }
        )
    )

    assert "research error" in output
    assert "RuntimeError: reentry boom" in output
