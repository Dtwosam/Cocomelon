from __future__ import annotations

import tomllib
from pathlib import Path

from cocomelon.replay.adapters import MICROSTRUCTURE_KINDS

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "cocomelon"
PHASE8_FILES = (
    SRC / "domain" / "journal.py",
    SRC / "domain" / "replay.py",
    *sorted((SRC / "journal").glob("*.py")),
    *sorted((SRC / "replay").glob("*.py")),
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _phase8_source() -> str:
    return "\n".join(_source(path) for path in PHASE8_FILES).lower()


def test_phase8_adds_no_network_wallet_or_live_order_capability() -> None:
    source = _phase8_source()
    forbidden = (
        "private_key",
        "privatekey",
        "wallet",
        "sign_message",
        "sign_transaction",
        "withdraw",
        "place_order",
        "cancel_order",
        "submit_order",
        "exchange_client",
        "testnet",
        "requests.",
        "httpx.",
        "websockets.",
        "urllib.request",
        "socket.",
    )

    for token in forbidden:
        assert token not in source, f"forbidden Phase 8 capability: {token}"


def test_phase8_has_no_ml_or_parameter_search_stack() -> None:
    source = _phase8_source()
    pyproject = _source(ROOT / "pyproject.toml").lower()
    forbidden = (
        "tensorflow",
        "pytorch",
        "torch",
        "scikit-learn",
        "sklearn",
        "xgboost",
        "lightgbm",
        "optuna",
        "hyperopt",
        "gridsearch",
        "randomizedsearch",
        "parameter_sweep",
    )

    for token in forbidden:
        assert token not in source, f"Phase 9/10 capability introduced early: {token}"
        assert token not in pyproject, f"Phase 9/10 dependency introduced early: {token}"


def test_pyarrow_is_research_only_and_recorder_does_not_import_it() -> None:
    config = tomllib.loads(_source(ROOT / "pyproject.toml"))
    base_dependencies = tuple(config["project"].get("dependencies", ()))
    optional = config["project"].get("optional-dependencies", {})
    research_dependencies = tuple(optional.get("research", ()))

    assert all("pyarrow" not in dependency.lower() for dependency in base_dependencies)
    assert any(dependency.lower().startswith("pyarrow") for dependency in research_dependencies)
    assert "pyarrow" not in _source(SRC / "recorder.py").lower()


def test_microstructure_evidence_cannot_be_synthesized_from_candles() -> None:
    assert MICROSTRUCTURE_KINDS == frozenset({"l2_book", "trade"})
    source = _phase8_source()
    forbidden = (
        "candle_to_book",
        "book_from_candle",
        "l2_from_candle",
        "candle_to_trade",
        "trade_from_candle",
        "synthetic_l2",
        "synthetic_trade",
        "fabricated_l2",
        "fabricated_trade",
    )

    for token in forbidden:
        assert token not in source, f"candle-derived microstructure path introduced: {token}"


def test_replay_kernel_has_no_wall_clock_sleep_random_or_network_calls() -> None:
    kernel_source = "\n".join(
        _source(path)
        for path in (
            SRC / "replay" / "clock.py",
            SRC / "replay" / "engine.py",
            SRC / "replay" / "manifest.py",
        )
    ).lower()
    forbidden = (
        "datetime.now",
        "datetime.utcnow",
        "time.time",
        "time.sleep",
        "asyncio.sleep",
        "random.",
        "secrets.",
        "requests.",
        "httpx.",
        "websockets.",
        "socket.",
    )

    for token in forbidden:
        assert token not in kernel_source, f"nondeterministic replay dependency: {token}"
