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
            "excluded_pre_observer_open_positions": 0,
            "excluded_closed_trades": 0,
            "unmatched_closed_trades": 0,
            "closed_trade_count": 3,
            "error": None,
            "by_horizon_ms": {
                "60000": {
                    "horizon_ms": 60000,
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
    assert "### Trade-path evidence" in output
    assert "completed exact trade paths" in output
    assert "staged open trade paths" in output
    assert "`3`" in output
    assert "`1`" in output
    assert "### Fixed profit-lock counterfactual" in output
    assert "### Prospective LONG-trend entry filter" in output
    assert "### Opening scanner-rank attribution" in output
    assert "latest_coarse_rank_before_open" in output
    assert "rank evidence records / attributed closed trades" in output
    assert "`4 / 3`" in output
    assert "mean / max rank age at opening" in output
    assert "`32000`ms / `58000`ms" in output
    assert "| 1-5 | 1 | 1 | 0 | 0 | 5 | 0.5 |" in output
    assert "| 11-20 | 2 | 0 | 2 | 0 | -7 | -0.35 |" in output
    assert "### Post-entry markout diagnostic" in output
    assert "first_observed_mark_at_or_after_horizon_within_max_lag" in output
    assert "maximum accepted observation lag" in output
    assert "`60000`ms" in output
    assert "complete paths / incomplete skipped" in output
    assert "`3 / 0`" in output
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
    assert "stale/missing marks are reported and never imputed" in output
    assert "### Prospective allMids entry markout shadow" in output
    assert "allMids_mid_px" in output
    assert "completed prospective trades / excluded / unmatched closes" in output
    assert "`3 / 0 / 0`" in output
    assert (
        "| 1m | 3 | 0 | 0 | 0 | 2 | 1 | 30 | 0.06 | "
        "800ms | 1400ms |"
    ) in output
    assert (
        "| 5m | 2 | 1 | 0 | 0 | 1 | 1 | 20 | 0.04 | "
        "1000ms | 1600ms |"
    ) in output
    assert (
        "| 15m | 1 | 0 | 2 | 0 | 1 | 0 | 50 | 0.1 | "
        "500ms | 500ms |"
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
