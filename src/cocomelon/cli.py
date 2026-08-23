from __future__ import annotations

import argparse
import json
from typing import Any

from cocomelon.config import Settings


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="cocomelon")
    parser.add_argument("command", choices=("status",))
    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(status_payload(Settings.from_env()), indent=2, sort_keys=True))
