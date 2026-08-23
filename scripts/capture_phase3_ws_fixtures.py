from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from cocomelon.config import Settings
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.hyperliquid.normalize import normalize_meta_and_asset_ctxs, normalize_perp_dexs
from cocomelon.hyperliquid.ws_client import connect_mainnet_ws
from cocomelon.hyperliquid.ws_protocol import normalize_ws_message, subscribe_message
from cocomelon.util.time import utc_now_ms

CAPTURE_TIMEOUT_SECONDS = 12.0
MAX_HIP3_DEX_PROBES = 5


async def capture_subscription(
    subscription: dict[str, object],
    *,
    expected_channel: str,
    expected_market: str | None = None,
    expected_dex: str | None = None,
) -> dict[str, object]:
    settings = Settings()
    connection = await connect_mainnet_ws(settings)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + CAPTURE_TIMEOUT_SECONDS
    try:
        await connection.send_json(subscribe_message(subscription))
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"timed out waiting for {expected_channel} from subscription {subscription}"
                )
            raw = await asyncio.wait_for(connection.recv_json(), timeout=remaining)
            if raw.get("channel") != expected_channel:
                continue

            events = normalize_ws_message(raw, receive_time=datetime.now(UTC))
            if not events:
                continue
            if expected_market is not None and not any(
                event.market.canonical == expected_market for event in events
            ):
                continue
            if expected_dex is not None and not any(
                event.market.dex == expected_dex for event in events
            ):
                raise RuntimeError(
                    f"{expected_channel} response did not preserve expected dex {expected_dex!r}"
                )
            return raw
    finally:
        await connection.close()


def discover_hip3_market() -> tuple[str, str] | None:
    settings = Settings()
    client = InfoClient(settings)
    dexes = normalize_perp_dexs(client.perp_dexs())
    for dex in dexes[:MAX_HIP3_DEX_PROBES]:
        snapshots = normalize_meta_and_asset_ctxs(
            dex.name,
            client.meta_and_asset_ctxs(dex.name),
            received_at_ms=utc_now_ms(),
        )
        active = next((item for item in snapshots if not item.meta.is_delisted), None)
        if active is not None:
            return dex.name, active.meta.market.canonical
    return None


async def capture_all(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    captures: dict[str, dict[str, object]] = {}

    captures["all_mids_native"] = await capture_subscription(
        {"type": "allMids"},
        expected_channel="allMids",
    )
    captures["l2_book_btc"] = await capture_subscription(
        {"type": "l2Book", "coin": "BTC"},
        expected_channel="l2Book",
        expected_market="BTC",
    )
    captures["trades_btc"] = await capture_subscription(
        {"type": "trades", "coin": "BTC"},
        expected_channel="trades",
        expected_market="BTC",
    )
    captures["candle_btc_1m"] = await capture_subscription(
        {"type": "candle", "coin": "BTC", "interval": "1m"},
        expected_channel="candle",
        expected_market="BTC",
    )

    hip3 = discover_hip3_market()
    hip3_summary: dict[str, str] | None = None
    if hip3 is not None:
        dex, market = hip3
        captures["all_mids_hip3"] = await capture_subscription(
            {"type": "allMids", "dex": dex},
            expected_channel="allMids",
            expected_dex=dex,
        )
        captures["l2_book_hip3"] = await capture_subscription(
            {"type": "l2Book", "coin": market},
            expected_channel="l2Book",
            expected_market=market,
        )
        hip3_summary = {"dex": dex, "market": market}

    for name, payload in captures.items():
        path = output_dir / f"{name}.json"
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    summary: dict[str, object] = {
        "capture_count": len(captures),
        "files": sorted(f"{name}.json" for name in captures),
        "hip3": hip3_summary,
        "source": "wss://api.hyperliquid.xyz/ws",
    }
    (output_dir / "capture_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/phase3_ws_capture"),
    )
    args = parser.parse_args()

    summary = asyncio.run(capture_all(args.output_dir))
    print("PHASE3_CAPTURE_SUMMARY=" + json.dumps(summary, sort_keys=True))
    for path in sorted(args.output_dir.glob("*.json")):
        print(f"PHASE3_FIXTURE_FILE={path.name}")
        print(path.read_text(encoding="utf-8").rstrip())


if __name__ == "__main__":
    main()
