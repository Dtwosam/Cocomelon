from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "src" / "cocomelon" / "evidence"
OFFLINE_REPLAY_MODULES = (
    "baseline.py",
    "bundle.py",
    "contracts.py",
    "epochs.py",
    "lifecycle.py",
    "openings.py",
    "resume.py",
)
FORBIDDEN_CAPABILITY_TOKENS = (
    "testnet",
    "Exchange",
    "place_order",
    "create_order",
    "wallet",
    "private_key",
    "signing",
    "withdraw",
    "transfer",
    "userFills",
    "orderUpdates",
    "scikit",
    "sklearn",
    "xgboost",
    "lightgbm",
    "optimizer",
    "grid_search",
    "random_search",
)
NETWORK_IMPORT_TOKENS = (
    "cocomelon.hyperliquid.client",
    "cocomelon.hyperliquid.ws_client",
)


def _source(name: str) -> str:
    return (EVIDENCE_ROOT / name).read_text(encoding="utf-8")


def test_offline_replay_modules_exclude_live_private_ml_and_search_capabilities() -> None:
    for name in OFFLINE_REPLAY_MODULES:
        source = _source(name)
        for token in FORBIDDEN_CAPABILITY_TOKENS:
            assert token not in source, f"{name} contains forbidden capability token {token!r}"


def test_offline_replay_modules_do_not_import_network_clients() -> None:
    for name in OFFLINE_REPLAY_MODULES:
        source = _source(name)
        for token in NETWORK_IMPORT_TOKENS:
            assert token not in source, f"{name} imports online network surface {token!r}"


def test_network_clients_are_confined_to_explicit_online_recording_boundary() -> None:
    source = _source("cli_support.py")
    online_start = source.index("def _run_mainnet_evidence(")
    online_end = source.index("\ndef record_mainnet_evidence_payload(", online_start)
    online_body = source[online_start:online_end]

    assert "from cocomelon.hyperliquid.client import InfoClient" in online_body
    assert "from cocomelon.hyperliquid.ws_client import" in online_body
    assert "connect_mainnet_ws" in online_body

    offline_body = source[:online_start] + source[online_end:]
    assert "from cocomelon.hyperliquid.client import InfoClient" not in offline_body
    assert "from cocomelon.hyperliquid.ws_client import" not in offline_body
    assert "connect_mainnet_ws" not in offline_body


def test_candle_records_cannot_populate_book_or_trade_microstructure_state() -> None:
    source = _source("baseline.py")
    marker = "elif record.event_kind == StreamKind.CANDLE.value:"
    start = source.index(marker)
    end = source.index("\n        else:", start)
    candle_branch = source[start:end]

    assert "self._apply_candle(state, record)" in candle_branch
    assert "latest_book" not in candle_branch
    assert "micro_events" not in candle_branch
    assert "StreamKind.L2_BOOK" not in candle_branch
    assert "StreamKind.TRADE" not in candle_branch


def test_offline_baseline_cli_routes_before_runtime_settings_and_network_commands() -> None:
    source = (ROOT / "src" / "cocomelon" / "cli.py").read_text(encoding="utf-8")
    route = 'elif args.command == "run-baseline-replay":'
    settings = "settings = Settings.from_env()"

    assert route in source
    assert settings in source
    assert source.index(route) < source.index(settings)
