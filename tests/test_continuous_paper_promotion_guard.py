from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from cocomelon.domain.market import MarketId
from cocomelon.research.continuous_paper_promotion_guard import (
    continuous_paper_promotion_guard,
)
from cocomelon.research.learning_clean_review_dossier import (
    PROMOTION_REQUIREMENTS,
)

DAY_MS = 86_400_000


def _trade(
    *,
    idx: int,
    pnl: str,
    opened_at_ms: int,
    market: str,
) -> SimpleNamespace:
    value = Decimal(pnl)
    return SimpleNamespace(
        trade_id=f"trade-{idx}",
        net_pnl=value,
        net_r=value / Decimal("10"),
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 60_000,
        market=MarketId("", market),
    )


def _drawdown(
    *,
    started_at_ms: int,
    maximum: str = "0.02",
    restore_error: str | None = None,
) -> dict[str, object]:
    return {
        "enabled": True,
        "sampled_account": {
            "started_at_ms": started_at_ms,
            "observation_count": 10,
            "state_restore_error": restore_error,
            "max_drawdown_fraction": maximum,
        },
    }


def _gate_map(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    raw = payload["gates"]
    assert isinstance(raw, list)
    return {
        str(item["requirement"]): item
        for item in raw
        if isinstance(item, dict)
    }


def test_small_profitable_sample_stays_blocked_by_volume_and_concentration() -> None:
    started = 10 * DAY_MS
    trades = (
        _trade(
            idx=1,
            pnl="20",
            opened_at_ms=started + 1_000,
            market="BTC",
        ),
        _trade(
            idx=2,
            pnl="-5",
            opened_at_ms=started + 2_000,
            market="ETH",
        ),
    )

    payload = continuous_paper_promotion_guard(
        trades,  # type: ignore[arg-type]
        _drawdown(started_at_ms=started),
        timestamp_ms=started + DAY_MS,
        execution_healthy=True,
        execution_reason_codes=(),
    )
    gates = _gate_map(payload)

    assert gates["closed_mainnet_paper_trades"]["status"] == "collecting"
    assert gates["shadow_calendar_days"]["status"] == "collecting"
    assert gates["positive_net_expectancy_after_costs"]["status"] == "pass"
    assert gates["profit_factor"]["status"] == "pass"
    assert gates["maximum_paper_drawdown"]["status"] == "pass"
    assert gates["market_concentration"]["status"] == "fail"
    assert gates["seven_day_concentration"]["status"] == "fail"
    assert gates["positive_untouched_oos"]["status"] == "external_required"
    assert gates["walk_forward_stability"]["status"] == "external_required"
    assert gates["risk_invariants"]["status"] == "external_required"
    assert gates["recovery_reconciliation"]["status"] == "external_required"
    assert gates["explicit_live_authorization"]["status"] == "not_authorized"
    assert payload["live_promotion_ready"] is False
    assert payload["promotion_authority"] is False


def test_numeric_gates_can_pass_without_granting_live_promotion() -> None:
    started = 20 * DAY_MS
    markets = ("BTC", "ETH", "SOL", "HYPE")
    trades = tuple(
        _trade(
            idx=i,
            pnl="2" if i % 5 < 3 else "-1",
            opened_at_ms=started + (i % 45) * DAY_MS + i,
            market=markets[i % len(markets)],
        )
        for i in range(500)
    )

    payload = continuous_paper_promotion_guard(
        trades,  # type: ignore[arg-type]
        _drawdown(started_at_ms=started, maximum="0.04"),
        timestamp_ms=started + 44 * DAY_MS + 1_000,
        execution_healthy=True,
        execution_reason_codes=(),
    )
    gates = _gate_map(payload)

    numeric = (
        "closed_mainnet_paper_trades",
        "shadow_calendar_days",
        "positive_net_expectancy_after_costs",
        "profit_factor",
        "maximum_paper_drawdown",
        "market_concentration",
        "seven_day_concentration",
    )
    assert all(gates[key]["status"] == "pass" for key in numeric)
    assert payload["all_observable_numeric_gates_pass"] is True
    assert payload["live_promotion_ready"] is False
    assert gates["positive_untouched_oos"]["status"] == "external_required"
    assert gates["walk_forward_stability"]["status"] == "external_required"
    assert gates["risk_invariants"]["status"] == "external_required"
    assert gates["recovery_reconciliation"]["status"] == "external_required"
    assert gates["explicit_live_authorization"]["status"] == "not_authorized"

    gate_order = tuple(
        str(item["requirement"])
        for item in payload["gates"]  # type: ignore[union-attr]
    )
    assert gate_order == tuple(key for key, _ in PROMOTION_REQUIREMENTS)


def test_unhealthy_execution_is_immediate_risk_gate_failure() -> None:
    started = 30 * DAY_MS
    payload = continuous_paper_promotion_guard(
        (),
        _drawdown(started_at_ms=started),
        timestamp_ms=started,
        execution_healthy=False,
        execution_reason_codes=("risk-state-corrupt",),
    )
    gates = _gate_map(payload)

    risk = gates["risk_invariants"]
    assert risk["status"] == "fail"
    observed = risk["observed"]
    assert isinstance(observed, dict)
    assert observed["current_execution_healthy"] is False
    assert observed["current_reason_codes"] == [
        "risk-state-corrupt"
    ]


def test_drawdown_restore_error_prevents_drawdown_gate_pass() -> None:
    started = 40 * DAY_MS
    payload = continuous_paper_promotion_guard(
        (),
        _drawdown(
            started_at_ms=started,
            maximum="0.01",
            restore_error="bad state",
        ),
        timestamp_ms=started,
        execution_healthy=True,
        execution_reason_codes=(),
    )
    gates = _gate_map(payload)

    assert gates["maximum_paper_drawdown"]["status"] == "collecting"
    assert payload["live_promotion_ready"] is False
