from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from cocomelon.domain.market import PerpDex, PerpMarketSnapshot
from cocomelon.hyperliquid.normalize import normalize_meta_and_asset_ctxs, normalize_perp_dexs
from cocomelon.util.time import utc_now_ms


class InfoReader(Protocol):
    def perp_dexs(self) -> object: ...

    def meta_and_asset_ctxs(self, dex: str = "") -> object: ...


@dataclass(frozen=True, slots=True)
class MarketRegistrySnapshot:
    dexs: tuple[PerpDex, ...]
    markets: Mapping[str, PerpMarketSnapshot]
    received_at_ms: int


class MarketRegistry:
    def __init__(
        self,
        client: InfoReader,
        *,
        now_ms: Callable[[], int] = utc_now_ms,
    ) -> None:
        self._client = client
        self._now_ms = now_ms
        self._snapshot: MarketRegistrySnapshot | None = None

    def refresh(self) -> MarketRegistrySnapshot:
        dexes = normalize_perp_dexs(self._client.perp_dexs())
        combined: dict[str, PerpMarketSnapshot] = {}
        received_at_ms = self._now_ms()
        for dex in ("", *(item.name for item in dexes)):
            raw = self._client.meta_and_asset_ctxs(dex)
            received_at_ms = self._now_ms()
            for market in normalize_meta_and_asset_ctxs(
                dex,
                raw,
                received_at_ms=received_at_ms,
            ):
                key = market.meta.market.canonical
                if key in combined:
                    raise ValueError(f"duplicate market across perp DEXes: {key}")
                combined[key] = market

        snapshot = MarketRegistrySnapshot(
            dexs=dexes,
            markets=MappingProxyType(combined.copy()),
            received_at_ms=received_at_ms,
        )
        self._snapshot = snapshot
        return snapshot

    def get(self, canonical_market: str) -> PerpMarketSnapshot:
        if self._snapshot is None:
            raise RuntimeError("market registry has not been refreshed")
        return self._snapshot.markets[canonical_market]

    @property
    def snapshot(self) -> MarketRegistrySnapshot:
        if self._snapshot is None:
            raise RuntimeError("market registry has not been refreshed")
        return self._snapshot
