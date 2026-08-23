from dataclasses import dataclass
from enum import StrEnum

from cocomelon.domain.market import MarketId


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKETABLE_IOC = "marketable_ioc"
    LIMIT_GTC = "limit_gtc"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    intent_id: str
    market: MarketId
    side: OrderSide
    quantity: float
    order_type: OrderType
    reduce_only: bool
    limit_price: float | None
    created_at_ms: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    intent_id: str
    market: MarketId
    side: OrderSide
    price: float
    quantity: float
    fee: float
    timestamp_ms: int


@dataclass(frozen=True, slots=True)
class Position:
    market: MarketId
    signed_quantity: float
    average_entry_price: float
    stop_price: float | None
    realized_pnl: float = 0.0
