from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cocomelon.config import ExecutionMode, Settings
from cocomelon.domain.features import OpportunityRank
from cocomelon.evidence.recording import _startup_ranks
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.hyperliquid.registry import MarketRegistry


@dataclass(frozen=True, slots=True)
class UniverseRankRow:
    market: str
    dex: str
    ordinal: int
    score: Decimal
    reason_codes: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "market": self.market,
            "dex": self.dex,
            "ordinal": self.ordinal,
            "score": str(self.score),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class UniverseOpportunityDiagnostics:
    observed_at_ms: int
    dex_count: int
    market_count: int
    rankable_count: int
    native_rankable_count: int
    hip3_rankable_count: int
    current_native_deep_limit: int
    hip3_in_combined_top_n: int
    combined_top_n: tuple[UniverseRankRow, ...]
    current_native_top_n: tuple[UniverseRankRow, ...]
    top_hip3: tuple[UniverseRankRow, ...]
    native_only_top_n_absent_from_combined: tuple[str, ...]
    paper_trading_policy: str = "native_only"
    economic_authority: bool = False
    live_orders: bool = False

    def payload(self) -> dict[str, object]:
        return {
            "observed_at_ms": self.observed_at_ms,
            "dex_count": self.dex_count,
            "market_count": self.market_count,
            "rankable_count": self.rankable_count,
            "native_rankable_count": self.native_rankable_count,
            "hip3_rankable_count": self.hip3_rankable_count,
            "current_native_deep_limit": self.current_native_deep_limit,
            "hip3_in_combined_top_n": self.hip3_in_combined_top_n,
            "combined_top_n": [item.payload() for item in self.combined_top_n],
            "current_native_top_n": [
                item.payload() for item in self.current_native_top_n
            ],
            "top_hip3": [item.payload() for item in self.top_hip3],
            "native_only_top_n_absent_from_combined": list(
                self.native_only_top_n_absent_from_combined
            ),
            "paper_trading_policy": self.paper_trading_policy,
            "economic_authority": self.economic_authority,
            "live_orders": self.live_orders,
        }


def _row(rank: OpportunityRank) -> UniverseRankRow:
    return UniverseRankRow(
        market=rank.market.canonical,
        dex=rank.market.dex,
        ordinal=rank.ordinal,
        score=rank.score,
        reason_codes=rank.reason_codes,
    )


def build_universe_opportunity_diagnostics(
    combined_ranks: tuple[OpportunityRank, ...],
    native_ranks: tuple[OpportunityRank, ...],
    *,
    observed_at_ms: int,
    dex_count: int,
    market_count: int,
    deep_limit: int = 20,
    top_hip3_limit: int = 10,
) -> UniverseOpportunityDiagnostics:
    if observed_at_ms < 0:
        raise ValueError("observed_at_ms must be non-negative")
    if dex_count < 0 or market_count < 0:
        raise ValueError("universe counts must be non-negative")
    if deep_limit <= 0 or top_hip3_limit <= 0:
        raise ValueError("diagnostic limits must be positive")

    if any(rank.market.dex != "" for rank in native_ranks):
        raise ValueError("native_ranks must contain only native markets")
    hip3 = tuple(
        rank for rank in combined_ranks if rank.market.dex != ""
    )
    combined_top = combined_ranks[:deep_limit]
    current_native_top = native_ranks[:deep_limit]
    combined_native_markets = {
        rank.market.canonical
        for rank in combined_top
        if rank.market.dex == ""
    }
    native_set_changes = tuple(
        rank.market.canonical
        for rank in current_native_top
        if rank.market.canonical not in combined_native_markets
    )

    return UniverseOpportunityDiagnostics(
        observed_at_ms=observed_at_ms,
        dex_count=dex_count,
        market_count=market_count,
        rankable_count=len(combined_ranks),
        native_rankable_count=len(native_ranks),
        hip3_rankable_count=len(hip3),
        current_native_deep_limit=deep_limit,
        hip3_in_combined_top_n=sum(
            1 for rank in combined_top if rank.market.dex != ""
        ),
        combined_top_n=tuple(_row(rank) for rank in combined_top),
        current_native_top_n=tuple(_row(rank) for rank in current_native_top),
        top_hip3=tuple(_row(rank) for rank in hip3[:top_hip3_limit]),
        native_only_top_n_absent_from_combined=native_set_changes,
    )


def collect_universe_opportunity_diagnostics(
    *,
    settings: Settings | None = None,
    deep_limit: int = 20,
    top_hip3_limit: int = 10,
) -> UniverseOpportunityDiagnostics:
    settings = settings or Settings.from_env()
    if settings.execution_mode is not ExecutionMode.PAPER:
        raise RuntimeError(
            "universe diagnostics refuse non-paper execution configuration"
        )

    registry = MarketRegistry(InfoClient(settings)).refresh()
    _features, combined_ranks = _startup_ranks(
        registry.markets,
        as_of_ms=registry.received_at_ms,
    )
    native_markets = {
        key: value
        for key, value in registry.markets.items()
        if value.meta.market.dex == ""
    }
    _native_features, native_ranks = _startup_ranks(
        native_markets,
        as_of_ms=registry.received_at_ms,
    )
    return build_universe_opportunity_diagnostics(
        combined_ranks,
        native_ranks,
        observed_at_ms=registry.received_at_ms,
        dex_count=len(registry.dexs),
        market_count=len(registry.markets),
        deep_limit=deep_limit,
        top_hip3_limit=top_hip3_limit,
    )
