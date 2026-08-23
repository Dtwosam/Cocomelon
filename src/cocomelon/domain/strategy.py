from dataclasses import dataclass
from enum import StrEnum

from cocomelon.domain.market import MarketId


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"
    NO_TRADE = "no_trade"


@dataclass(frozen=True, slots=True)
class StrategySignal:
    strategy: str
    market: MarketId
    direction: Direction
    score: float
    timestamp_ms: int
    reasons: tuple[str, ...]
    invalidation_price: float | None

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 100.0:
            raise ValueError("score must be between 0 and 100")
        if self.direction is not Direction.NO_TRADE and self.invalidation_price is None:
            raise ValueError("trade signals require invalidation_price")
