from pathlib import Path

from cocomelon.hyperliquid.ws_protocol import PUBLIC_TYPES

ROOT = Path(__file__).resolve().parents[1]
EXECUTION_DIR = ROOT / "src" / "cocomelon" / "execution"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _execution_source() -> str:
    return "\n".join(
        _source(path) for path in sorted(EXECUTION_DIR.glob("*.py"))
    ).lower()


def test_execution_package_has_no_wallet_signing_transfer_or_testnet_capability() -> None:
    source = _execution_source()
    forbidden = (
        "private_key",
        "privatekey",
        "wallet",
        "sign_message",
        "sign_transaction",
        "withdraw",
        "transfer",
        "testnet",
        "eth_account",
        "web3",
    )

    for token in forbidden:
        assert token not in source, f"forbidden Phase 7 execution capability: {token}"


def test_execution_interface_exposes_no_generic_exchange_client_escape_hatch() -> None:
    source = _source(EXECUTION_DIR / "interface.py").lower()
    forbidden = (
        "hyperliquidclient",
        "exchangeclient",
        "exchange_client",
        "place_order",
        "cancel_order",
        "modify_order",
        "submit_order",
        "raw_client",
    )

    for token in forbidden:
        assert token not in source, f"forbidden execution interface escape hatch: {token}"


def test_phase7_websocket_surface_remains_public_market_data_only() -> None:
    assert PUBLIC_TYPES == frozenset(
        {"allMids", "activeAssetCtx", "l2Book", "trades", "candle"}
    )


def test_ioc_fill_model_requires_l2_and_has_no_candle_or_maker_fill_path() -> None:
    source = _source(EXECUTION_DIR / "ioc.py")
    lower = source.lower()

    assert "StreamKind.L2_BOOK" in source
    assert "StreamKind.CANDLE" not in source
    assert "maker" not in lower
    assert "rebate" not in lower


def test_phase7_has_no_machine_learning_dependency() -> None:
    pyproject = _source(ROOT / "pyproject.toml").lower()
    forbidden = ("tensorflow", "torch", "pytorch", "scikit-learn", "sklearn", "xgboost")

    for token in forbidden:
        assert token not in pyproject, f"ML dependency introduced before its phase: {token}"
