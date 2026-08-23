from dataclasses import dataclass

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision_id: str
    market: MarketId
    direction: Direction
    timestamp_ms: int
    regime: str
    strategy_names: tuple[str, ...]
    approved_by_risk: bool
    reason_codes: tuple[str, ...]
