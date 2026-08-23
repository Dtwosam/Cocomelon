from __future__ import annotations

import argparse
import json
from typing import Any

from cocomelon.config import Settings
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.hyperliquid.registry import InfoReader, MarketRegistry


def status_payload(settings: Settings) -> dict[str, Any]:
    return {
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "ws_url": settings.ws_url,
        "live_activation_valid": settings.live_activation_valid,
        "risk_per_trade": settings.risk_per_trade,
        "max_open_risk": settings.max_open_risk,
        "daily_loss_limit": settings.daily_loss_limit,
        "weekly_drawdown_limit": settings.weekly_drawdown_limit,
    }


def markets_payload(
    settings: Settings,
    *,
    client: InfoReader | None = None,
) -> dict[str, Any]:
    reader = client or InfoClient(settings)
    snapshot = MarketRegistry(reader).refresh()
    market_names = list(snapshot.markets)
    delisted_count = sum(1 for item in snapshot.markets.values() if item.meta.is_delisted)
    return {
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "live_activation_valid": settings.live_activation_valid,
        "perp_dex_count": 1 + len(snapshot.dexs),
        "hip3_dex_count": len(snapshot.dexs),
        "market_count": len(snapshot.markets),
        "active_market_count": len(snapshot.markets) - delisted_count,
        "delisted_market_count": delisted_count,
        "sample_markets": market_names[:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="cocomelon")
    parser.add_argument("command", choices=("status", "markets"))
    args = parser.parse_args()
    settings = Settings.from_env()

    if args.command == "status":
        payload = status_payload(settings)
    else:
        payload = markets_payload(settings)
    print(json.dumps(payload, indent=2, sort_keys=True))
