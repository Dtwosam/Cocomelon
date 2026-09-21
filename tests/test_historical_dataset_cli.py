from __future__ import annotations

from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.historical_dataset_cli import _parse_market, build_historical_dataset


def test_parse_market_supports_native_and_hip3() -> None:
    assert _parse_market("BTC") == MarketId(dex="", coin="BTC")
    assert _parse_market("xyz:NVDA") == MarketId(dex="xyz", coin="NVDA")


def test_build_historical_dataset_rejects_nonpositive_horizons(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        build_historical_dataset(
            source_root=tmp_path / "sources",
            output_root=tmp_path / "dataset",
            markets=(MarketId(dex="", coin="ETH"),),
            horizons_ms=(0,),
        )
