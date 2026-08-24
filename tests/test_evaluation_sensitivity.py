from decimal import Decimal

from cocomelon.domain.evaluation import TradeEvaluationSample
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.sensitivity import (
    apply_cost_stress,
    predeclared_cost_stress_profiles,
)

MARKET = MarketId("", "SOL")


def sample(
    *,
    gross_pnl: str = "10",
    entry_fee: str = "1",
    exit_fee: str = "1",
    funding: str = "1",
    net_pnl: str = "9",
    entry_slippage: str = "2",
    exit_slippage: str = "-1",
) -> TradeEvaluationSample:
    return TradeEvaluationSample(
        trade_id="trade-1",
        replay_run_id="run-1",
        strategy_decision_id="strategy-1",
        market=MARKET,
        direction=Direction.LONG,
        decision_timestamp_ms=900,
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        score=Decimal("70"),
        lead_strategy="trend",
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        gross_realized_pnl=Decimal(gross_pnl),
        entry_fees=Decimal(entry_fee),
        exit_fees=Decimal(exit_fee),
        funding_cash_pnl=Decimal(funding),
        net_pnl=Decimal(net_pnl),
        entry_slippage_amount=Decimal(entry_slippage),
        exit_slippage_amount=Decimal(exit_slippage),
        net_r=Decimal("0.36"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10009"),
        holding_duration_ms=1_000,
        reason_codes=("TEST",),
    )


def profiles():
    return {item.profile_id: item for item in predeclared_cost_stress_profiles()}


def test_predeclared_profiles_are_exact_and_not_a_search_grid() -> None:
    assert tuple(item.profile_id for item in predeclared_cost_stress_profiles()) == (
        "base",
        "fees_1_25x",
        "adverse_slippage_1_50x",
        "adverse_funding_1_50x",
        "combined_stress",
    )


def test_base_reconstruction_matches_recorded_net_pnl() -> None:
    item = sample()

    assert apply_cost_stress(item, profiles()["base"]) == item.net_pnl


def test_adverse_slippage_stresses_legs_separately_and_removes_favorable_credit() -> None:
    item = sample()

    stressed = apply_cost_stress(item, profiles()["adverse_slippage_1_50x"])

    assert stressed == Decimal("7")


def test_combined_stress_applies_fees_slippage_and_funding_conservatively() -> None:
    item = sample()

    stressed = apply_cost_stress(item, profiles()["combined_stress"])

    assert stressed == Decimal("5.5")


def test_adverse_funding_amplifies_negative_funding_and_removes_positive_funding() -> None:
    positive = sample()
    negative = sample(funding="-2", net_pnl="6")
    profile = profiles()["adverse_funding_1_50x"]

    assert apply_cost_stress(positive, profile) == Decimal("8")
    assert apply_cost_stress(negative, profile) == Decimal("5")


def test_every_adverse_profile_is_monotonic_against_conservative_base() -> None:
    item = sample()
    available = profiles()
    base = apply_cost_stress(item, available["base"])

    for profile_id in (
        "fees_1_25x",
        "adverse_slippage_1_50x",
        "adverse_funding_1_50x",
        "combined_stress",
    ):
        assert apply_cost_stress(item, available[profile_id]) <= base
