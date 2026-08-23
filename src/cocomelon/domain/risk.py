from dataclasses import dataclass

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision_id: str
    market: MarketId
    direction: Direction
    approved: bool
    reasons: tuple[str, ...]
    risk_budget: float
    approved_notional: float
    stop_price: float | None
    timestamp_ms: int
