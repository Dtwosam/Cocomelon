from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from cocomelon.domain.execution import InstrumentExecutionSpec, PaperOrderPlan, PositionAction
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import RiskDecision, RiskRequest
from cocomelon.domain.strategy import StrategyDecision
from cocomelon.domain.stream import StreamEvent
from cocomelon.execution.accounting import PaperAccountState
from cocomelon.execution.ioc import IocSimulation
from cocomelon.execution.planner import PlanningRejection


@dataclass(frozen=True, slots=True)
class ExecutionHealth:
    healthy_for_new_exposure: bool
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OpeningSubmission:
    risk_decision: RiskDecision
    plan: PaperOrderPlan | None
    rejection: PlanningRejection | None
    simulation: IocSimulation | None
    account: PaperAccountState


@dataclass(frozen=True, slots=True)
class PositionManagement:
    action: PositionAction
    plan: PaperOrderPlan | None
    rejection: PlanningRejection | None
    simulation: IocSimulation | None
    account: PaperAccountState


class TradingExecution(Protocol):
    @property
    def account(self) -> PaperAccountState: ...

    @property
    def health(self) -> ExecutionHealth: ...

    def submit_risk_request(
        self,
        request: RiskRequest,
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        created_at_ms: int,
        attempt_timestamp_ms: int,
    ) -> OpeningSubmission: ...

    def submit_opening(
        self,
        risk_decision: RiskDecision,
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        created_at_ms: int,
        attempt_timestamp_ms: int,
    ) -> OpeningSubmission: ...

    def manage_position(
        self,
        market: MarketId,
        instrument: InstrumentExecutionSpec,
        mark_event: StreamEvent | None,
        book: StreamEvent,
        *,
        strategy_decision: StrategyDecision | None,
        strategy_fresh: bool,
        critical_health: bool,
        explicit_reduction_quantity: Decimal | None,
        reference_price: Decimal,
        timestamp_ms: int,
        attempt_timestamp_ms: int,
    ) -> PositionManagement: ...
