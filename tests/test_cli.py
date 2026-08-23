from cocomelon.cli import status_payload
from cocomelon.config import Settings


def test_status_payload_is_safe_and_explicit() -> None:
    payload = status_payload(Settings())

    assert payload["execution_mode"] == "paper"
    assert payload["api_url"] == "https://api.hyperliquid.xyz"
    assert payload["ws_url"] == "wss://api.hyperliquid.xyz/ws"
    assert payload["live_activation_valid"] is False
    assert payload["risk_per_trade"] == 0.0025
    assert "live_ack" not in payload
