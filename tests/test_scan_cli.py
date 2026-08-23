from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

import pytest

import cocomelon.cli as cli
from cocomelon.config import Settings
from cocomelon.domain.features import EligibilityDecision, OpportunityRank
from cocomelon.domain.market import (
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.features.assemble import assemble_feature_snapshot
from cocomelon.features.broad import BroadFeatureValues
from cocomelon.hyperliquid.registry import MarketRegistrySnapshot

AS_OF_MS = 1_000


def _market(coin: str) -> PerpMarketSnapshot:
    market = MarketId("", coin)
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market,
            wire_name=coin,
            sz_decimals=2,
            max_leverage=20,
            margin_table_id=None,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=market,
            mark_px=Decimal("100"),
            mid_px=Decimal("100"),
            oracle_px=Decimal("100"),
            funding=Decimal("0.0001"),
            open_interest=Decimal("1000"),
            day_ntl_vlm=Decimal("1000000"),
            premium=Decimal("0"),
            prev_day_px=Decimal("99"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=AS_OF_MS,
        schema_version=1,
    )


def _feature(coin: str):
    market = MarketId("", coin)
    broad = BroadFeatureValues(
        source_received_at_ms=AS_OF_MS,
        day_return=Decimal("0.01"),
        funding=Decimal("0.0001"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
    )
    return assemble_feature_snapshot(
        market,
        broad,
        as_of_ms=AS_OF_MS,
        provenance=("hyperliquid-mainnet-info",),
    )


@dataclass
class FakeRegistry:
    snapshot: MarketRegistrySnapshot
    refresh_calls: int = 0

    def refresh(self) -> MarketRegistrySnapshot:
        self.refresh_calls += 1
        return self.snapshot


class FakeBroadScanner:
    def __init__(self) -> None:
        self.market_keys: tuple[str, ...] = ()
        self.as_of_ms: int | None = None

    def __call__(self, markets, *, as_of_ms: int):
        self.market_keys = tuple(markets)
        self.as_of_ms = as_of_ms
        features = (_feature("A"), _feature("B"), _feature("C"))
        decisions = (
            EligibilityDecision(MarketId("", "A"), True, False, ()),
            EligibilityDecision(MarketId("", "B"), True, False, ()),
            EligibilityDecision(MarketId("", "C"), False, False, ("delisted",)),
        )
        ranks = (
            OpportunityRank(MarketId("", "A"), 1, Decimal("0.9"), (), ("volume",)),
            OpportunityRank(MarketId("", "B"), 2, Decimal("0.7"), (), ("funding",)),
        )
        return cli.BroadScanResult(features, decisions, ranks)


def _registry() -> FakeRegistry:
    markets = {coin: _market(coin) for coin in ("A", "B", "C")}
    return FakeRegistry(
        MarketRegistrySnapshot(
            dexs=(),
            markets=MappingProxyType(markets),
            received_at_ms=AS_OF_MS,
        )
    )


def test_scan_once_parser_defaults_to_20_and_caps_at_100() -> None:
    parser = cli.build_parser()

    assert parser.parse_args(["scan-once"]).limit == 20
    assert parser.parse_args(["scan-once", "--limit", "100"]).limit == 100
    with pytest.raises(SystemExit):
        parser.parse_args(["scan-once", "--limit", "101"])
    with pytest.raises(SystemExit):
        parser.parse_args(["scan-once", "--limit", "0"])


@pytest.mark.parametrize(
    "flag",
    ("--wallet", "--key", "--order", "--live"),
)
def test_scan_once_parser_rejects_trading_and_secret_flags(flag: str) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["scan-once", flag, "value"])


def test_scan_once_refreshes_once_and_scans_entire_registry() -> None:
    registry = _registry()
    scanner = FakeBroadScanner()

    payload = cli.scan_once_payload(
        Settings(),
        limit=1,
        registry=registry,
        scanner=scanner,
    )

    assert registry.refresh_calls == 1
    assert scanner.market_keys == ("A", "B", "C")
    assert scanner.as_of_ms == AS_OF_MS
    assert payload["market_count"] == 3
    assert payload["rankable_count"] == 2
    assert payload["rejected_count"] == 1
    assert len(payload["results"]) == 1


def test_scan_once_output_is_bounded_direction_neutral_evidence() -> None:
    payload = cli.scan_once_payload(
        Settings(),
        limit=2,
        registry=_registry(),
        scanner=FakeBroadScanner(),
    )

    assert payload["results"] == [
        {
            "market": "A",
            "ordinal": 1,
            "score": 0.9,
            "reasons": [],
            "feature_snapshot_id": _feature("A").snapshot_id,
        },
        {
            "market": "B",
            "ordinal": 2,
            "score": 0.7,
            "reasons": [],
            "feature_snapshot_id": _feature("B").snapshot_id,
        },
    ]
    rendered = json.dumps(payload, sort_keys=True).lower()
    assert '"direction"' not in rendered
    assert '"long"' not in rendered
    assert '"short"' not in rendered
    assert '"leverage"' not in rendered
    assert '"position_size"' not in rendered
    assert '"order"' not in rendered
