from __future__ import annotations

import ast
from pathlib import Path

from cocomelon.cli import build_parser

EVALUATION_ROOT = Path("src/cocomelon/evaluation")
PHASE9_COMMANDS = (
    "freeze-evaluation-dataset",
    "freeze-evaluation-splits",
    "evaluate",
    "inspect-evaluation",
)


def _evaluation_sources() -> tuple[Path, ...]:
    return tuple(sorted(EVALUATION_ROOT.glob("*.py")))


def _imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return tuple(modules)


def test_phase9_evaluation_has_no_network_wallet_live_or_ml_imports() -> None:
    forbidden_roots = {
        "httpx",
        "requests",
        "websockets",
        "numpy",
        "pandas",
        "sklearn",
        "lightgbm",
        "xgboost",
        "torch",
        "tensorflow",
        "optuna",
        "hyperopt",
    }
    forbidden_internal_prefixes = (
        "cocomelon.hyperliquid",
        "cocomelon.execution.live",
    )

    for path in _evaluation_sources():
        for module in _imported_modules(path):
            assert module.split(".", 1)[0] not in forbidden_roots, (path, module)
            assert not module.startswith(forbidden_internal_prefixes), (path, module)


def test_phase9_source_contains_no_order_wallet_testnet_or_optimizer_capability() -> None:
    forbidden_fragments = (
        "testnet",
        "private_key",
        "seed_phrase",
        "wallet_secret",
        "sign_transaction",
        "sign_order",
        "withdraw(",
        "transfer(",
        "place_order",
        "cancel_order",
        "live_adapter",
        "grid_search",
        "random_search",
        "bayesian_optimization",
        "objective_maximization",
        "optuna",
        "hyperopt",
        "synthetic_book",
        "candle_to_book",
        "candle-derived-book",
    )

    for path in _evaluation_sources():
        source = path.read_text(encoding="utf-8").lower()
        for fragment in forbidden_fragments:
            assert fragment not in source, (path, fragment)


def test_phase9_cli_commands_expose_only_local_research_arguments() -> None:
    parser = build_parser()
    subparser_action = next(action for action in parser._actions if action.choices)
    choices = subparser_action.choices
    forbidden_options = (
        "--api-url",
        "--ws-url",
        "--testnet",
        "--live",
        "--wallet",
        "--private-key",
        "--optimize",
        "--grid-search",
        "--random-search",
    )

    for command in PHASE9_COMMANDS:
        help_text = choices[command].format_help().lower()
        for option in forbidden_options:
            assert option not in help_text, (command, option)


def test_phase9_does_not_add_heavy_ml_dependencies_to_core() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8").lower()
    core = pyproject.split("[project.optional-dependencies]", 1)[0]
    for dependency in (
        "numpy",
        "pandas",
        "sklearn",
        "scikit-learn",
        "lightgbm",
        "xgboost",
        "torch",
        "tensorflow",
        "pyarrow",
    ):
        assert dependency not in core

    assert 'research = [' in pyproject
    assert '"pyarrow>=' in pyproject
