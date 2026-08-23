from dataclasses import fields
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import RiskDecision
from cocomelon.domain.strategy import Direction

ROOT = Path(__file__).resolve().parents[1]
RISK_DIR = ROOT / "src" / "cocomelon" / "risk"


def _risk_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(RISK_DIR.glob("*.py"))
    )


def test_risk_package_does_not_import_execution_or_exchange_capabilities() -> None:
    source = _risk_source().lower()
    forbidden_imports = (
        "cocomelon.domain.execution",
        "cocomelon.hyperliquid",
        "hyperliquid.exchange",
        "hyperliquid-python-sdk",
    )

    for forbidden in forbidden_imports:
        assert forbidden not in source


def test_risk_package_has_no_wallet_transfer_fill_or_ml_capability() -> None:
    source = _risk_source().lower()
    forbidden_capabilities = (
        "private_key",
        "sign_order",
        "place_order",
        "submit_order",
        "cancel_order",
        "withdraw",
        "withdrawal",
        "transfer_funds",
        "fill_simulator",
        "simulate_fill",
        "sklearn",
        "lightgbm",
        "xgboost",
        "torch",
        "tensorflow",
    )

    for forbidden in forbidden_capabilities:
        assert forbidden not in source


def test_risk_public_api_has_no_add_position_or_loss_recovery_sizing_path() -> None:
    source = _risk_source().lower()
    forbidden_behaviors = (
        "average_down",
        "averaging_down",
        "add_position",
        "pyramid_position",
        "martingale",
        "loss_recovery",
        "recovery_multiplier",
    )

    for forbidden in forbidden_behaviors:
        assert forbidden not in source


def test_risk_decision_is_an_approval_envelope_not_an_order() -> None:
    names = {field.name for field in fields(RiskDecision)}
    forbidden = {
        "quantity",
        "order_type",
        "order_id",
        "client_order_id",
        "limit_price",
        "reduce_only",
        "wallet",
        "private_key",
        "fill_price",
    }

    assert names.isdisjoint(forbidden)


def test_rejected_decision_contract_requires_zero_exposure() -> None:
    decision = RiskDecision(
        strategy_decision_id="strategy-1",
        market=MarketId("", "BTC"),
        direction=Direction.LONG,
        approved=False,
        reason_codes=("daily_loss_lockout",),
        target_risk_amount=Decimal("25"),
        approved_risk_amount=Decimal("0"),
        approved_notional=Decimal("0"),
        entry_reference_price=Decimal("100"),
        stop_price=Decimal("99"),
        stop_distance_fraction=Decimal("0.01"),
        effective_loss_fraction=Decimal("0.0124"),
        correlation_bucket="crypto_beta",
        binding_caps=(),
        timestamp_ms=1_000,
    )

    assert decision.approved is False
    assert decision.approved_risk_amount == Decimal("0")
    assert decision.approved_notional == Decimal("0")
