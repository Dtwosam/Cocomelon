from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
    PositionActionType,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import RiskDecision, RiskRequest
from cocomelon.domain.strategy import StrategyDecision
from cocomelon.domain.stream import StreamEvent
from cocomelon.execution.accounting import (
    PaperAccountState,
    apply_opening_fills,
    apply_reduce_only_fills,
    empty_account,
)
from cocomelon.execution.interface import (
    ExecutionHealth,
    OpeningSubmission,
    PositionManagement,
)
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.execution.manager import evaluate_position
from cocomelon.execution.planner import (
    PlanningRejection,
    plan_opening_order,
    plan_reduce_only_order,
)
from cocomelon.execution.store import PaperExecutionStore
from cocomelon.risk.engine import evaluate_risk


class PaperExecutionAdapter:
    def __init__(
        self,
        path: str | Path,
        config: PaperExecutionConfig,
        *,
        starting_cash: Decimal,
        startup_timestamp_ms: int,
    ) -> None:
        self._config = config
        self.store = PaperExecutionStore(path)
        recovered = self.store.load_and_reconcile()
        self._health = ExecutionHealth(
            healthy_for_new_exposure=recovered.healthy,
            reason_codes=recovered.reason_codes,
        )
        self._account = (
            recovered.account
            if recovered.account is not None
            else empty_account(starting_cash, startup_timestamp_ms)
        )

    @property
    def account(self) -> PaperAccountState:
        return self._account

    @property
    def health(self) -> ExecutionHealth:
        return self._health

    def close(self) -> None:
        self.store.close()

    def _mark_store_failure(self, reason: str) -> None:
        self._health = ExecutionHealth(False, (reason,))

    def submit_risk_request(
        self,
        request: RiskRequest,
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        created_at_ms: int,
        attempt_timestamp_ms: int,
    ) -> OpeningSubmission:
        risk_decision = evaluate_risk(request)
        return self.submit_opening(
            risk_decision,
            instrument,
            book,
            reference_price=reference_price,
            created_at_ms=created_at_ms,
            attempt_timestamp_ms=attempt_timestamp_ms,
        )

    def submit_opening(
        self,
        risk_decision: RiskDecision,
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        created_at_ms: int,
        attempt_timestamp_ms: int,
    ) -> OpeningSubmission:
        if not self._health.healthy_for_new_exposure:
            return OpeningSubmission(
                risk_decision=risk_decision,
                plan=None,
                rejection=PlanningRejection("EXECUTION_STATE_UNHEALTHY"),
                simulation=None,
                account=self._account,
            )
        if any(
            position.market == risk_decision.market
            for position in self._account.positions
        ):
            return OpeningSubmission(
                risk_decision=risk_decision,
                plan=None,
                rejection=PlanningRejection("POSITION_ALREADY_OPEN"),
                simulation=None,
                account=self._account,
            )

        planned = plan_opening_order(
            risk_decision,
            instrument,
            self._config,
            reference_price,
            created_at_ms,
        )
        if isinstance(planned, PlanningRejection):
            return OpeningSubmission(
                risk_decision=risk_decision,
                plan=None,
                rejection=planned,
                simulation=None,
                account=self._account,
            )

        self.store.persist_plan(planned)
        simulation = simulate_ioc(
            planned,
            book,
            instrument,
            self._config,
            attempt_timestamp_ms=attempt_timestamp_ms,
        )
        candidate = self._account
        if simulation.fills:
            candidate = apply_opening_fills(
                self._account,
                planned,
                simulation.fills,
                correlation_bucket=risk_decision.correlation_bucket,
                venue_max_leverage=instrument.venue_max_leverage,
            )
        try:
            self.store.persist_execution(simulation.attempt, simulation.fills, candidate)
        except Exception:
            self._mark_store_failure("DURABLE_EXECUTION_WRITE_FAILED")
            raise
        self._account = candidate
        return OpeningSubmission(
            risk_decision=risk_decision,
            plan=planned,
            rejection=None,
            simulation=simulation,
            account=self._account,
        )

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
    ) -> PositionManagement:
        matches = tuple(
            position for position in self._account.positions if position.market == market
        )
        if len(matches) != 1:
            raise ValueError("position manager requires exactly one open position")
        position = matches[0]
        action = evaluate_position(
            position,
            mark_event=mark_event,
            strategy_decision=strategy_decision,
            strategy_fresh=strategy_fresh,
            critical_health=critical_health,
            explicit_reduction_quantity=explicit_reduction_quantity,
            config=self._config,
            timestamp_ms=timestamp_ms,
        )

        if action.action_type in {
            PositionActionType.HOLD,
            PositionActionType.TIGHTEN_STOP,
        }:
            return PositionManagement(
                action=action,
                plan=None,
                rejection=None,
                simulation=None,
                account=self._account,
            )

        planned = plan_reduce_only_order(
            position,
            action,
            instrument,
            self._config,
            reference_price=reference_price,
            created_at_ms=timestamp_ms,
        )
        if isinstance(planned, PlanningRejection):
            return PositionManagement(
                action=action,
                plan=None,
                rejection=planned,
                simulation=None,
                account=self._account,
            )

        self.store.persist_plan(planned)
        simulation = simulate_ioc(
            planned,
            book,
            instrument,
            self._config,
            attempt_timestamp_ms=attempt_timestamp_ms,
        )
        candidate = self._account
        if simulation.fills:
            candidate = apply_reduce_only_fills(
                self._account,
                market,
                simulation.fills,
                attempt_timestamp_ms,
            )
        try:
            self.store.persist_execution(simulation.attempt, simulation.fills, candidate)
        except Exception:
            self._mark_store_failure("DURABLE_EXECUTION_WRITE_FAILED")
            raise
        self._account = candidate
        return PositionManagement(
            action=action,
            plan=planned,
            rejection=None,
            simulation=simulation,
            account=self._account,
        )
