from decimal import Decimal

import pytest

from cocomelon.config import ExecutionMode, Settings


def test_defaults_are_mainnet_and_paper(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "COCOMELON_API_URL",
        "COCOMELON_WS_URL",
        "COCOMELON_EXECUTION_MODE",
        "COCOMELON_LIVE_ACK",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings.from_env()

    assert settings.api_url == "https://api.hyperliquid.xyz"
    assert settings.ws_url == "wss://api.hyperliquid.xyz/ws"
    assert settings.execution_mode is ExecutionMode.PAPER
    assert settings.live_activation_valid is False
    assert settings.risk_per_trade == Decimal("0.0025")
    assert settings.max_open_risk == Decimal("0.0075")
    assert settings.daily_loss_limit == Decimal("0.01")
    assert settings.weekly_drawdown_limit == Decimal("0.03")
    assert settings.consecutive_loss_cooldown == 3
    assert settings.cooldown_ms == 3_600_000
    assert settings.correlation_bucket_risk_limit == Decimal("0.005")
    assert settings.max_gross_leverage == Decimal("3")
    assert settings.max_available_margin_fraction == Decimal("0.50")
    assert settings.max_visible_depth_fraction == Decimal("0.10")
    assert settings.min_liquidation_stop_multiple == Decimal("2")
    assert settings.max_state_age_ms == 5_000


@pytest.mark.parametrize(
    "env_key,url",
    [
        ("COCOMELON_API_URL", "https://api.hyperliquid-testnet.xyz"),
        ("COCOMELON_WS_URL", "wss://api.hyperliquid-testnet.xyz/ws"),
        ("COCOMELON_API_URL", "https://foo.testnet.example"),
    ],
)
def test_testnet_urls_are_rejected(
    monkeypatch: pytest.MonkeyPatch, env_key: str, url: str
) -> None:
    monkeypatch.setenv(env_key, url)
    with pytest.raises(ValueError, match="testnet"):
        Settings.from_env()


def test_live_mode_requires_exact_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COCOMELON_EXECUTION_MODE", "live")
    monkeypatch.setenv("COCOMELON_LIVE_ACK", "yes")
    settings = Settings.from_env()
    assert settings.live_activation_valid is False

    monkeypatch.setenv(
        "COCOMELON_LIVE_ACK", "I_UNDERSTAND_REAL_FUNDS_ARE_AT_RISK"
    )
    settings = Settings.from_env()
    assert settings.live_activation_valid is True
