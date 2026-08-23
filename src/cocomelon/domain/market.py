from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class MarketId:
    dex: str
    coin: str

    def __post_init__(self) -> None:
        if not self.coin.strip():
            raise ValueError("coin must not be empty")
        if ":" in self.coin:
            raise ValueError("coin must be unqualified; use MarketId.from_wire_name")

    @classmethod
    def from_wire_name(cls, dex: str, wire_name: str) -> "MarketId":
        name = wire_name.strip()
        if not name:
            raise ValueError("wire_name must not be empty")
        if not dex:
            if ":" in name:
                raise ValueError("native market wire name must not include a dex prefix")
            return cls(dex="", coin=name)

        prefix = f"{dex}:"
        if not name.startswith(prefix):
            raise ValueError(f"wire market prefix does not match dex {dex!r}: {wire_name!r}")
        coin = name[len(prefix) :]
        if not coin or ":" in coin:
            raise ValueError(f"invalid HIP-3 wire market name: {wire_name!r}")
        return cls(dex=dex, coin=coin)

    @property
    def canonical(self) -> str:
        return f"{self.dex}:{self.coin}" if self.dex else self.coin

    @property
    def wire_name(self) -> str:
        return self.canonical


@dataclass(frozen=True, slots=True)
class PerpDex:
    name: str
    full_name: str
    deployer: str
    oracle_updater: str | None
    fee_recipient: str | None


@dataclass(frozen=True, slots=True)
class PerpMarketMeta:
    market: MarketId
    wire_name: str
    sz_decimals: int
    max_leverage: int
    margin_table_id: int | None
    only_isolated: bool
    is_delisted: bool
    margin_mode: str | None


@dataclass(frozen=True, slots=True)
class PerpMarketContext:
    market: MarketId
    mark_px: Decimal | None
    mid_px: Decimal | None
    oracle_px: Decimal | None
    funding: Decimal
    open_interest: Decimal
    day_ntl_vlm: Decimal
    premium: Decimal | None
    prev_day_px: Decimal


@dataclass(frozen=True, slots=True)
class PerpMarketSnapshot:
    meta: PerpMarketMeta
    context: PerpMarketContext
    source: str
    received_at_ms: int
    schema_version: int


@dataclass(frozen=True, slots=True)
class Candle:
    market: MarketId
    interval: str
    start_ms: int
    end_ms: int
    open_px: Decimal
    high_px: Decimal
    low_px: Decimal
    close_px: Decimal
    volume: Decimal
    trade_count: int
    source: str
    received_at_ms: int
    schema_version: int


@dataclass(frozen=True, slots=True)
class FundingRate:
    market: MarketId
    time_ms: int
    funding_rate: Decimal
    premium: Decimal
    source: str
    received_at_ms: int
    schema_version: int
