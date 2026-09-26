from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from cocomelon.continuous_paper import _closed_trade_performance


def _trade(
    *,
    pnl: str,
    net_r: str,
    side: str,
    reason: str,
    feature_id: str,
    hold_ms: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        net_pnl=Decimal(pnl),
        net_r=Decimal(net_r),
        direction=SimpleNamespace(value=side),
        exit_reason=reason,
        feature_snapshot_id=feature_id,
        holding_duration_ms=hold_ms,
    )


class _FeatureStore:
    def load(self, snapshot_id: str) -> SimpleNamespace | None:
        regimes = {
            "feature-up": ("uptrend", "normal"),
            "feature-down": ("downtrend", "high"),
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


def test_closed_trade_performance_attributes_realized_outcomes() -> None:
    trades = (
        _trade(
            pnl="5",
            net_r="0.5",
            side="long",
            reason="OPPOSITE_FRESH_THESIS",
            feature_id="feature-up",
            hold_ms=60_000,
        ),
        _trade(
            pnl="-2",
            net_r="-0.2",
            side="long",
            reason="OPPOSITE_FRESH_THESIS",
            feature_id="feature-down",
            hold_ms=120_000,
        ),
        _trade(
            pnl="-10",
            net_r="-1",
            side="short",
            reason="MARK_STOP_TRIGGERED",
            feature_id="feature-missing",
            hold_ms=180_000,
        ),
    )

    result = _closed_trade_performance(  # type: ignore[arg-type]
        trades,
        _FeatureStore(),  # type: ignore[arg-type]
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
    assert result["unattributed_feature_trades"] == 1

    by_side = result["by_side"]
    assert isinstance(by_side, dict)
    assert by_side["long"]["net_pnl"] == "3"
    assert by_side["long"]["wins"] == 1
    assert by_side["long"]["losses"] == 1
    assert by_side["short"]["net_pnl"] == "-10"

    by_reason = result["by_exit_reason"]
    assert isinstance(by_reason, dict)
    assert by_reason["OPPOSITE_FRESH_THESIS"]["trades"] == 2
    assert by_reason["MARK_STOP_TRIGGERED"]["net_pnl"] == "-10"

    by_trend = result["by_trend_regime"]
    assert isinstance(by_trend, dict)
    assert by_trend["uptrend"]["net_pnl"] == "5"
    assert by_trend["downtrend"]["net_pnl"] == "-2"
    assert by_trend["unknown"]["net_pnl"] == "-10"

    by_vol = result["by_volatility_regime"]
    assert isinstance(by_vol, dict)
    assert by_vol["normal"]["net_pnl"] == "5"
    assert by_vol["high"]["net_pnl"] == "-2"
    assert by_vol["unknown"]["net_pnl"] == "-10"
