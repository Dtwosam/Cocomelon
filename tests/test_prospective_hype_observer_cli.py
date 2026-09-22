from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.config import ExecutionMode, Settings
from cocomelon.domain.market import MarketId
from cocomelon.prospective_hype_observer_cli import prospective_hype_observer_payload
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)

HOUR = 3_600_000
FIFTEEN = 900_000
CUTOVER = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.validation_not_before_ms
ANCHOR = CUTOVER + HOUR
AS_OF = ANCHOR + 5 * 60_000
CLOSES = {"BTC": "95", "ETH": "96", "HYPE": "96", "SOL": "97"}


class FakePublicReader:
    def __init__(self) -> None:
        self.candle_calls: list[tuple[str, str]] = []

    def meta_and_asset_ctxs(self, dex: str = "") -> object:
        assert dex == ""
        universe = [
            {
                "name": market,
                "szDecimals": 4,
                "maxLeverage": 20,
                "onlyIsolated": False,
                "isDelisted": False,
            }
            for market in ("BTC", "ETH", "HYPE", "SOL")
        ]
        contexts = [
            {
                "markPx": CLOSES[market],
                "midPx": CLOSES[market],
                "oraclePx": CLOSES[market],
                "funding": "0.0001",
                "openInterest": "10000",
                "dayNtlVlm": "1000000",
                "premium": "0",
                "prevDayPx": str(Decimal(CLOSES[market]) + Decimal("1")),
            }
            for market in ("BTC", "ETH", "HYPE", "SOL")
        ]
        return [{"universe": universe}, contexts]

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        del start_ms, end_ms
        self.candle_calls.append((market.canonical, interval))
        if interval == "1h":
            assert market.canonical == "HYPE"
            return [
                {
                    "t": ANCHOR - HOUR + 1,
                    "T": ANCHOR,
                    "s": "HYPE",
                    "i": "1h",
                    "o": "96",
                    "h": "96.2",
                    "l": "95.8",
                    "c": "96",
                    "v": "5000",
                    "n": 500,
                }
            ]

        assert interval == "15m"
        target = Decimal(CLOSES[market.canonical])
        closes = (Decimal("100"), Decimal("99"), Decimal("98"), Decimal("97"), target)
        first_end = ANCHOR - 4 * FIFTEEN
        return [
            {
                "t": first_end + index * FIFTEEN - FIFTEEN + 1,
                "T": first_end + index * FIFTEEN,
                "s": market.canonical,
                "i": "15m",
                "o": str(close),
                "h": str(close + Decimal("0.1")),
                "l": str(close - Decimal("0.1")),
                "c": str(close),
                "v": "1000",
                "n": 100,
            }
            for index, close in enumerate(closes)
        ]


class ExplodingReader:
    def meta_and_asset_ctxs(self, dex: str = "") -> object:
        raise AssertionError("live-mode guard must run before any public request")

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        raise AssertionError("live-mode guard must run before any public request")


def test_payload_runs_one_paper_only_clean_observation_cycle(tmp_path) -> None:
    reader = FakePublicReader()

    payload = prospective_hype_observer_payload(
        Settings(execution_mode=ExecutionMode.PAPER),
        root=tmp_path,
        reader=reader,
        clock_ms=lambda: AS_OF,
    )

    assert payload["execution_mode"] == "paper"
    assert payload["evidence_class"] == "prospective_clean"
    assert payload["promotion_eligible"] is False
    observation = payload["observation"]
    assert isinstance(observation, dict)
    assert observation["status"] == "recorded"
    assert observation["raw_direction"] == "long"
    assert observation["effective_direction"] == "long"
    assert observation["context_state_1h"] == "down/bearish/near_basket"
    assert payload["observation_count"] == 1
    assert payload["outcome_count"] == 0
    assert len(payload["state_digest"]) == 64
    assert reader.candle_calls == [
        ("BTC", "15m"),
        ("ETH", "15m"),
        ("HYPE", "15m"),
        ("SOL", "15m"),
        ("HYPE", "1h"),
    ]


def test_payload_rejects_live_mode_before_any_market_request(tmp_path) -> None:
    with pytest.raises(ValueError, match="requires paper execution mode"):
        prospective_hype_observer_payload(
            Settings(execution_mode=ExecutionMode.LIVE),
            root=tmp_path,
            reader=ExplodingReader(),
            clock_ms=lambda: AS_OF,
        )
