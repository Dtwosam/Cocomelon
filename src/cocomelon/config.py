from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from urllib.parse import urlparse

MAINNET_API_URL = "https://api.hyperliquid.xyz"
MAINNET_WS_URL = "wss://api.hyperliquid.xyz/ws"
LIVE_ACK = "I_UNDERSTAND_REAL_FUNDS_ARE_AT_RISK"


class ExecutionMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


def _reject_testnet(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "testnet" in host:
        raise ValueError(f"Hyperliquid testnet is forbidden: {url}")
    return url


@dataclass(frozen=True, slots=True)
class Settings:
    api_url: str = MAINNET_API_URL
    ws_url: str = MAINNET_WS_URL
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    live_ack: str = ""
    risk_per_trade: Decimal = Decimal("0.0025")
    max_open_risk: Decimal = Decimal("0.0075")
    daily_loss_limit: Decimal = Decimal("0.01")
    weekly_drawdown_limit: Decimal = Decimal("0.03")
    consecutive_loss_cooldown: int = 3
    cooldown_ms: int = 3_600_000
    correlation_bucket_risk_limit: Decimal = Decimal("0.005")
    max_gross_leverage: Decimal = Decimal("3")
    max_available_margin_fraction: Decimal = Decimal("0.50")
    max_visible_depth_fraction: Decimal = Decimal("0.10")
    min_liquidation_stop_multiple: Decimal = Decimal("2")
    max_state_age_ms: int = 5_000

    @classmethod
    def from_env(cls) -> Settings:
        mode = ExecutionMode(os.getenv("COCOMELON_EXECUTION_MODE", "paper").lower())
        return cls(
            api_url=_reject_testnet(os.getenv("COCOMELON_API_URL", MAINNET_API_URL)),
            ws_url=_reject_testnet(os.getenv("COCOMELON_WS_URL", MAINNET_WS_URL)),
            execution_mode=mode,
            live_ack=os.getenv("COCOMELON_LIVE_ACK", ""),
        )

    @property
    def live_activation_valid(self) -> bool:
        return self.execution_mode is ExecutionMode.LIVE and self.live_ack == LIVE_ACK
