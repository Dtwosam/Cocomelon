from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from cocomelon.domain.strategy import StrategyDecision, StrategySignal
from cocomelon.domain.stream import StreamKind
from cocomelon.strategies.microstructure import ALLOWED_KINDS

STRATEGY_ROOT = Path(__file__).parents[1] / "src" / "cocomelon" / "strategies"

FORBIDDEN_CONTRACT_FIELDS = {
    "account",
    "account_equity",
    "equity",
    "leverage",
    "margin",
    "notional",
    "order",
    "order_type",
    "quantity",
    "risk",
    "risk_budget",
    "size",
    "wallet",
}
FORBIDDEN_INTERNAL_IMPORT_PREFIXES = (
    "cocomelon.domain.execution",
    "cocomelon.domain.risk",
    "cocomelon.execution",
    "cocomelon.hyperliquid",
    "cocomelon.risk",
)
FORBIDDEN_ML_IMPORT_ROOTS = {
    "catboost",
    "keras",
    "lightgbm",
    "sklearn",
    "tensorflow",
    "torch",
    "xgboost",
}


def _strategy_modules() -> tuple[Path, ...]:
    return tuple(sorted(STRATEGY_ROOT.glob("*.py")))


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    return tuple(imported)


def test_strategy_contracts_exclude_position_sizing_and_execution_fields() -> None:
    decision_fields = {field.name for field in fields(StrategyDecision)}
    signal_fields = {field.name for field in fields(StrategySignal)}

    assert decision_fields.isdisjoint(FORBIDDEN_CONTRACT_FIELDS)
    assert signal_fields.isdisjoint(FORBIDDEN_CONTRACT_FIELDS)


def test_strategies_do_not_import_risk_execution_or_exchange_apis() -> None:
    violations: list[str] = []
    for path in _strategy_modules():
        for imported in _imports(path):
            if imported.startswith(FORBIDDEN_INTERNAL_IMPORT_PREFIXES):
                violations.append(f"{path.name}: {imported}")

    assert violations == []


def test_strategies_have_no_ml_dependencies() -> None:
    violations: list[str] = []
    for path in _strategy_modules():
        for imported in _imports(path):
            if imported.split(".", maxsplit=1)[0] in FORBIDDEN_ML_IMPORT_ROOTS:
                violations.append(f"{path.name}: {imported}")

    assert violations == []


def test_microstructure_boundary_allows_only_real_trade_and_l2_events() -> None:
    assert ALLOWED_KINDS == frozenset({StreamKind.TRADE, StreamKind.L2_BOOK})
    assert StreamKind.CANDLE not in ALLOWED_KINDS


def test_phase_5_strategy_package_contains_all_five_evidence_engines() -> None:
    names = {path.name for path in _strategy_modules()}
    assert {
        "breakout.py",
        "funding_oi.py",
        "mean_reversion.py",
        "order_flow.py",
        "trend.py",
    }.issubset(names)
