from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from cocomelon.continuous_paper import _closed_trade_performance


def _excursion(kind: str, r_multiple: str, *, complete: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        kind=kind,
        r_multiple=Decimal(r_multiple),
        complete=complete,
    )


def _trade(
    *,
    pnl: str,
    net_r: str,
    side: str,
    reason: str,
    feature_id: str,
    decision_id: str,
    hold_ms: int,
    mfe_r: str = "0",
    mae_r: str = "0",
    excursion_complete: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        net_pnl=Decimal(pnl),
        net_r=Decimal(net_r),
        direction=SimpleNamespace(value=side),
        exit_reason=reason,
        feature_snapshot_id=feature_id,
        strategy_decision_id=decision_id,
        replay_run_id="continuous-paper-mainnet-v1",
        holding_duration_ms=hold_ms,
        mfe=_excursion("mfe", mfe_r, complete=excursion_complete),
        mae=_excursion("mae", mae_r, complete=excursion_complete),
    )


class _FeatureStore:
    def load(self, snapshot_id: str) -> SimpleNamespace | None:
        regimes = {
            "feature-up": ("up", "normal"),
            "feature-down": ("down", "high"),
        }
        resolved = regimes.get(snapshot_id)
        if resolved is None:
            return None
        trend, volatility = resolved
        return SimpleNamespace(
            snapshot=SimpleNamespace(
                trend_regime=SimpleNamespace(value=trend),
                volatility_regime=SimpleNamespace(value=volatility),
            )
        )


class _FactStore:
    def load_decision_by_strategy_id(
        self,
        strategy_decision_id: str,
        replay_run_id: str,
    ) -> SimpleNamespace | None:
        if replay_run_id != "continuous-paper-mainnet-v1":
            return None
        facts = {
            "decision-1": ("trend", "68", "up", "normal"),
            "decision-2": ("breakout", "76", "down", "high"),
        }
        resolved = facts.get(strategy_decision_id)
        if resolved is None:
            return None
        lead_strategy, score, trend, volatility = resolved
        return SimpleNamespace(
            lead_strategy=lead_strategy,
            score=Decimal(score),
            trend_regime=SimpleNamespace(value=trend),
            volatility_regime=SimpleNamespace(value=volatility),
        )


def test_closed_trade_performance_attributes_realized_outcomes() -> None:
    trades = (
        _trade(
            pnl="5",
            net_r="0.5",
            side="long",
            reason="OPPOSITE_FRESH_THESIS",
            feature_id="feature-up",
            decision_id="decision-1",
            hold_ms=60_000,
            mfe_r="1.2",
            mae_r="0.3",
        ),
        _trade(
            pnl="-2",
            net_r="-0.2",
            side="long",
            reason="OPPOSITE_FRESH_THESIS",
            feature_id="feature-down",
            decision_id="decision-2",
            hold_ms=120_000,
            mfe_r="0.6",
            mae_r="0.8",
        ),
        _trade(
            pnl="-10",
            net_r="-1",
            side="short",
            reason="MARK_STOP_TRIGGERED",
            feature_id="feature-missing",
            decision_id="decision-missing",
            hold_ms=180_000,
            mfe_r="0.1",
            mae_r="1.1",
        ),
    )

    result = _closed_trade_performance(  # type: ignore[arg-type]
        trades,
        _FeatureStore(),  # type: ignore[arg-type]
        _FactStore(),  # type: ignore[arg-type]
    )

    assert result["trades"] == 3
    assert result["wins"] == 1
    assert result["losses"] == 2
    assert result["breakeven"] == 0
    assert result["net_pnl"] == "-7"
    assert result["gross_profit"] == "5"
    assert result["gross_loss_abs"] == "12"
    assert Decimal(str(result["profit_factor"])) == Decimal("5") / Decimal("12")
    assert result["average_holding_ms"] == 120_000
    assert result["decision_fact_attributed_trades"] == 2
    assert result["decision_fact_attribution_misses"] == 1
    assert result["feature_snapshot_fallback_trades"] == 0
    assert result["regime_attribution_misses"] == 1
    assert result["unattributed_feature_trades"] == 1

    assert result["complete_excursion_trades"] == 3
    assert result["incomplete_or_missing_excursion_trades"] == 0
    assert Decimal(str(result["mean_mfe_r"])) == Decimal("1.9") / Decimal("3")
    assert Decimal(str(result["mean_mae_r"])) == Decimal("2.2") / Decimal("3")
    assert result["mfe_ge_0_5r"] == 2
    assert result["mfe_ge_1r"] == 1
    assert result["losses_with_mfe_lt_0_25r"] == 1
    assert result["losses_after_mfe_ge_0_5r"] == 1
    assert result["losses_after_mfe_ge_1r"] == 0
    assert Decimal(str(result["mean_peak_to_close_giveback_r"])) == (
        Decimal("2.6") / Decimal("3")
    )
    assert result["mean_giveback_after_mfe_ge_0_5r"] == "0.75"
    assert result["mean_giveback_after_mfe_ge_1r"] == "0.7"
    assert result["positive_closes_after_mfe_ge_0_5r"] == 1
    assert result["positive_closes_after_mfe_ge_1r"] == 1
    assert result["mean_final_net_r_after_mfe_ge_0_5r"] == "0.15"
    assert result["mean_final_net_r_after_mfe_ge_1r"] == "0.5"

    by_side = result["by_side"]
    assert isinstance(by_side, dict)
    assert by_side["long"]["net_pnl"] == "3"
    assert by_side["long"]["wins"] == 1
    assert by_side["long"]["losses"] == 1
    assert by_side["short"]["net_pnl"] == "-10"

    by_reason = result["by_exit_reason"]
    assert isinstance(by_reason, dict)
    assert by_reason["OPPOSITE_FRESH_THESIS"]["trades"] == 2
    assert by_reason["OPPOSITE_FRESH_THESIS"]["mfe_ge_0_5r"] == 2
    assert by_reason["OPPOSITE_FRESH_THESIS"][
        "positive_closes_after_mfe_ge_0_5r"
    ] == 1
    assert by_reason["OPPOSITE_FRESH_THESIS"][
        "mean_giveback_after_mfe_ge_0_5r"
    ] == "0.75"
    assert by_reason["MARK_STOP_TRIGGERED"]["net_pnl"] == "-10"
    assert by_reason["MARK_STOP_TRIGGERED"][
        "mean_peak_to_close_giveback_r"
    ] == "1.1"

    by_strategy = result["by_lead_strategy"]
    assert isinstance(by_strategy, dict)
    assert by_strategy["trend"]["net_pnl"] == "5"
    assert by_strategy["breakout"]["net_pnl"] == "-2"
    assert by_strategy["unknown"]["net_pnl"] == "-10"

    by_score = result["by_decision_score_band"]
    assert isinstance(by_score, dict)
    assert by_score["65-<70"]["net_pnl"] == "5"
    assert by_score["75-<80"]["net_pnl"] == "-2"
    assert by_score["unknown"]["net_pnl"] == "-10"

    by_trend = result["by_trend_regime"]
    assert isinstance(by_trend, dict)
    assert by_trend["up"]["net_pnl"] == "5"
    assert by_trend["down"]["net_pnl"] == "-2"
    assert by_trend["unknown"]["net_pnl"] == "-10"

    by_vol = result["by_volatility_regime"]
    assert isinstance(by_vol, dict)
    assert by_vol["normal"]["net_pnl"] == "5"
    assert by_vol["high"]["net_pnl"] == "-2"
    assert by_vol["unknown"]["net_pnl"] == "-10"


def test_closed_trade_performance_excludes_incomplete_excursions() -> None:
    trade = _trade(
        pnl="-1",
        net_r="-0.1",
        side="long",
        reason="MARK_STOP_TRIGGERED",
        feature_id="feature-up",
        decision_id="decision-1",
        hold_ms=60_000,
        mfe_r="2",
        mae_r="2",
        excursion_complete=False,
    )

    result = _closed_trade_performance(  # type: ignore[arg-type]
        (trade,),
        _FeatureStore(),  # type: ignore[arg-type]
        _FactStore(),  # type: ignore[arg-type]
    )

    assert result["complete_excursion_trades"] == 0
    assert result["incomplete_or_missing_excursion_trades"] == 1
    assert result["mean_mfe_r"] is None
    assert result["mean_mae_r"] is None
    assert result["mfe_ge_0_5r"] == 0
    assert result["losses_after_mfe_ge_0_5r"] == 0
    assert result["mean_peak_to_close_giveback_r"] is None
    assert result["mean_giveback_after_mfe_ge_0_5r"] is None
    assert result["mean_final_net_r_after_mfe_ge_0_5r"] is None
