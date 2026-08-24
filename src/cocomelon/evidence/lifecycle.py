from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from cocomelon.domain.evaluation import EquityFactKind
from cocomelon.domain.execution import (
    ExecutionAttempt,
    PaperFill,
    PaperOrderPlan,
    PositionAction,
)
from cocomelon.domain.journal import JournalObservation, TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evaluation.facts import account_equity_fact, decision_evaluation_fact
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.baseline import (
    RecordedStateBook,
    replay_record_funding_rate,
    replay_record_stream_event,
)
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import (
    DECISION_INTERVAL_MS,
    BaselineDecisionEngine,
    DecisionEpoch,
    EpochMarketEvaluation,
    _effective_snapshot,
)
from cocomelon.evidence.openings import (
    BaselineOpeningEngine,
    BaselineOpeningTrace,
    _instrument,
)
from cocomelon.execution.funding import FundingAccrual, reconcile_funding_boundary
from cocomelon.execution.interface import PositionManagement
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.features.microstructure import calculate_microstructure_features
from cocomelon.journal.assembler import (
    JournalInconsistency,
    TradeLifecycleInput,
    assemble_trade_journal_entry,
)
from cocomelon.journal.observations import (
    observation_from_account_state,
    observation_from_execution,
    observation_from_funding_accrual,
    observation_from_funding_gap,
    observation_from_position_action,
    observation_from_risk,
    observation_from_strategy,
)
from cocomelon.replay.adapters import ReplayRequirements
from cocomelon.replay.engine import ReplayActivity, ReplayInvariantError, ReplayPipeline

HOUR_MS = 3_600_000
ZERO = Decimal("0")


class DecisionEpochEngine(Protocol):
    @property
    def state_book(self) -> RecordedStateBook: ...

    def observe(self, record: ReplayRecord, now_ms: int) -> tuple[DecisionEpoch, ...]: ...

    def flush(self, end_ms: int) -> tuple[DecisionEpoch, ...]: ...


@dataclass(slots=True)
class _OpenTradeLifecycle:
    evaluation: EpochMarketEvaluation
    opening: BaselineOpeningTrace
    exit_plans: dict[str, PaperOrderPlan] = field(default_factory=dict)
    exit_attempts: dict[str, ExecutionAttempt] = field(default_factory=dict)
    fills: dict[str, PaperFill] = field(default_factory=dict)
    actions: dict[tuple[str, int], PositionAction] = field(default_factory=dict)
    funding: dict[str, FundingAccrual] = field(default_factory=dict)
    marks: dict[str, ReplayRecord] = field(default_factory=dict)

    @property
    def market(self) -> MarketId:
        return self.evaluation.decision.market


def _receive_ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1000)


class BaselineReplayPipeline:
    def __init__(
        self,
        replay_config: BaselineReplayConfig,
        execution: PaperExecutionAdapter,
        facts: EvaluationFactStore,
        *,
        selected_markets: Sequence[MarketId],
        replay_run_id: str,
        evidence_class: EvidenceClass,
        decision_engine: DecisionEpochEngine | None = None,
    ) -> None:
        if not replay_run_id.strip():
            raise ValueError("replay_run_id must not be empty")
        markets = tuple(sorted(selected_markets, key=lambda item: item.canonical))
        if not markets:
            raise ValueError("selected_markets must not be empty")
        if len({market.canonical for market in markets}) != len(markets):
            raise ValueError("selected_markets must not contain duplicates")
        if evidence_class is not EvidenceClass.MICROSTRUCTURE:
            raise ValueError("baseline replay pipeline requires microstructure evidence")

        self._config = replay_config
        self._execution = execution
        self._facts = facts
        self._run_id = replay_run_id
        self._evidence_class = evidence_class
        self._decision_engine = decision_engine or BaselineDecisionEngine(
            markets,
            replay_config=replay_config,
        )
        self._state = self._decision_engine.state_book
        self._opening = BaselineOpeningEngine(replay_config, execution, self._state)
        self._latest_evaluation: dict[str, EpochMarketEvaluation] = {}
        self._lifecycles: dict[str, _OpenTradeLifecycle] = {}
        self._completed: dict[str, TradeJournalEntry] = {}
        self._oracle_history: dict[str, list[StreamEvent]] = {}
        self._latest_mark: dict[str, StreamEvent] = {}
        self._funding_resolved: set[tuple[str, int]] = set()
        self._funding_gaps: set[tuple[str, int]] = set()
        self._funding_inconsistent = False
        self._gap_intervals: list[tuple[int, int | None]] = []
        self._recorded_account_states: set[str] = set()
        self._initial_observation_emitted = False

    @property
    def funding_inconsistent(self) -> bool:
        return self._funding_inconsistent

    @property
    def state_book(self) -> RecordedStateBook:
        return self._state

    def _account_observation(
        self,
        kind: EquityFactKind,
    ) -> JournalObservation:
        account = self._execution.account
        if account.state_id not in self._recorded_account_states:
            self._facts.record_equity_fact(
                account_equity_fact(
                    account,
                    replay_run_id=self._run_id,
                    kind=kind,
                )
            )
            self._recorded_account_states.add(account.state_id)
        return observation_from_account_state(account, replay_run_id=self._run_id)

    def _ensure_initial_account_observation(self) -> tuple[JournalObservation, ...]:
        if self._initial_observation_emitted:
            return ()
        self._initial_observation_emitted = True
        return (self._account_observation(EquityFactKind.ACCOUNT_UPDATE),)

    def _process_epoch(self, epoch: DecisionEpoch) -> tuple[JournalObservation, ...]:
        observations: list[JournalObservation] = []
        for evaluation in epoch.markets:
            decision = evaluation.decision
            self._latest_evaluation[decision.market.canonical] = evaluation
            self._facts.record_decision_fact(
                decision_evaluation_fact(
                    decision,
                    evaluation.feature,
                    replay_run_id=self._run_id,
                )
            )
            observations.append(
                observation_from_strategy(decision, replay_run_id=self._run_id)
            )
        if not self._funding_inconsistent:
            self._opening.stage_epoch(epoch)
        return tuple(observations)

    def _all_current_marks(self, now_ms: int) -> dict[MarketId, Decimal] | None:
        marks: dict[MarketId, Decimal] = {}
        for position in self._execution.account.positions:
            snapshot = _effective_snapshot(
                self._state.state(position.market),
                as_of_ms=now_ms,
            )
            if snapshot is None:
                return None
            mark = snapshot.context.mark_px
            if mark is None or not mark.is_finite() or mark <= ZERO:
                return None
            marks[position.market] = mark
        return marks

    def _mark_account(
        self,
        record: ReplayRecord,
        event: StreamEvent,
        now_ms: int,
    ) -> tuple[JournalObservation, ...]:
        history = self._oracle_history.setdefault(event.market.canonical, [])
        history.append(event)
        history.sort(key=lambda item: (_receive_ms(item), item.event_key))
        self._latest_mark[event.market.canonical] = event

        lifecycle = self._lifecycles.get(event.market.canonical)
        if lifecycle is not None and record.event_key is not None:
            lifecycle.marks[record.event_key] = record

        if not self._execution.account.positions:
            return ()
        marks = self._all_current_marks(now_ms)
        if marks is None:
            return ()
        self._execution.mark_account_to_market(marks, timestamp_ms=now_ms)
        return (self._account_observation(EquityFactKind.MARK),)

    def _oracle_before(self, market: MarketId, boundary_ms: int) -> StreamEvent | None:
        candidates = tuple(
            event
            for event in self._oracle_history.get(market.canonical, [])
            if _receive_ms(event) <= boundary_ms
        )
        if not candidates:
            return None
        return max(candidates, key=lambda item: (_receive_ms(item), item.event_key))

    def _due_funding(self, now_ms: int) -> tuple[JournalObservation, ...]:
        observations: list[JournalObservation] = []
        for position in tuple(self._execution.account.positions):
            first_boundary = (position.opened_at_ms // HOUR_MS + 1) * HOUR_MS
            boundary_ms = first_boundary
            while boundary_ms <= now_ms:
                key = (position.position_id, boundary_ms)
                if key in self._funding_resolved or key in self._funding_gaps:
                    boundary_ms += HOUR_MS
                    continue

                state = self._state.state(position.market)
                funding_record = state.funding_by_boundary.get(boundary_ms)
                oracle = self._oracle_before(position.market, boundary_ms)
                grace_elapsed = (
                    now_ms - boundary_ms
                    >= self._config.execution.funding_reconciliation_grace_ms
                )
                if funding_record is None and not grace_elapsed:
                    boundary_ms += HOUR_MS
                    continue
                if oracle is None and not grace_elapsed:
                    boundary_ms += HOUR_MS
                    continue

                result = reconcile_funding_boundary(
                    position,
                    boundary_ms,
                    oracle,
                    funding_record,
                    now_ms=now_ms,
                    config=self._config.execution,
                )
                lifecycle = self._lifecycles.get(position.market.canonical)
                if isinstance(result, FundingAccrual):
                    self._execution.apply_funding(result, timestamp_ms=now_ms)
                    self._funding_resolved.add(key)
                    if lifecycle is not None:
                        lifecycle.funding[result.accrual_id] = result
                    observations.append(
                        observation_from_funding_accrual(
                            result,
                            replay_run_id=self._run_id,
                        )
                    )
                    observations.append(
                        self._account_observation(EquityFactKind.FUNDING)
                    )
                elif grace_elapsed:
                    self._funding_gaps.add(key)
                    self._funding_inconsistent = (
                        self._funding_inconsistent or result.account_inconsistent
                    )
                    observations.append(
                        observation_from_funding_gap(
                            result,
                            replay_run_id=self._run_id,
                        )
                    )
                boundary_ms += HOUR_MS
        return tuple(observations)

    def _record_opening_trace(
        self,
        trace: BaselineOpeningTrace,
    ) -> tuple[JournalObservation, ...]:
        submission = trace.submission
        observations: list[JournalObservation] = [
            observation_from_risk(
                submission.risk_decision,
                replay_run_id=self._run_id,
            )
        ]
        simulation = submission.simulation
        if simulation is not None:
            observations.append(
                observation_from_execution(
                    simulation.attempt,
                    replay_run_id=self._run_id,
                )
            )
        observations.append(
            self._account_observation(
                EquityFactKind.FILL
                if simulation is not None and simulation.fills
                else EquityFactKind.ACCOUNT_UPDATE
            )
        )

        if submission.plan is None or simulation is None or not simulation.fills:
            return tuple(observations)

        market_key = trace.evaluation.decision.market.canonical
        if market_key in self._lifecycles:
            raise ReplayInvariantError("opening fill collided with existing lifecycle")
        lifecycle = _OpenTradeLifecycle(
            evaluation=trace.evaluation,
            opening=trace,
        )
        for fill in simulation.fills:
            lifecycle.fills[fill.fill_id] = fill
        self._lifecycles[market_key] = lifecycle
        return tuple(observations)

    def _latest_strategy(self, market: MarketId) -> StrategyDecision | None:
        evaluation = self._latest_evaluation.get(market.canonical)
        return None if evaluation is None else evaluation.decision

    def _strategy_fresh(self, decision: StrategyDecision | None, now_ms: int) -> bool:
        if decision is None or decision.timestamp_ms > now_ms:
            return False
        max_age = DECISION_INTERVAL_MS + self._config.decision_grace_ms
        return now_ms - decision.timestamp_ms <= max_age

    def _record_management(
        self,
        management: PositionManagement,
    ) -> tuple[JournalObservation, ...]:
        observations: list[JournalObservation] = []
        action = management.action
        if action.reason_codes not in {("HOLD",), ("MARK_CONTEXT_UNUSABLE",)}:
            observations.append(
                observation_from_position_action(action, replay_run_id=self._run_id)
            )
        simulation = management.simulation
        if simulation is not None:
            observations.append(
                observation_from_execution(
                    simulation.attempt,
                    replay_run_id=self._run_id,
                )
            )
        if management.plan is not None or simulation is not None:
            observations.append(
                self._account_observation(
                    EquityFactKind.FILL
                    if simulation is not None and simulation.fills
                    else EquityFactKind.POSITION_ACTION
                )
            )
        return tuple(observations)

    def _append_management_to_lifecycle(
        self,
        management: PositionManagement,
    ) -> None:
        lifecycle = self._lifecycles.get(management.action.market.canonical)
        if lifecycle is None:
            return
        action = management.action
        lifecycle.actions[(action.action_type.value, action.timestamp_ms)] = action
        if management.plan is not None:
            lifecycle.exit_plans[management.plan.plan_id] = management.plan
        if management.simulation is not None:
            attempt = management.simulation.attempt
            lifecycle.exit_attempts[attempt.attempt_id] = attempt
            for fill in management.simulation.fills:
                lifecycle.fills[fill.fill_id] = fill

    def _close_lifecycle(self, market: MarketId) -> None:
        lifecycle = self._lifecycles.get(market.canonical)
        if lifecycle is None:
            raise ReplayInvariantError("closed position has no replay lifecycle")
        submission = lifecycle.opening.submission
        if submission.plan is None or submission.simulation is None:
            raise ReplayInvariantError("journal lifecycle is missing opening execution")
        actions = tuple(
            sorted(
                lifecycle.actions.values(),
                key=lambda item: (item.timestamp_ms, item.action_type.value),
            )
        )
        exit_reason = actions[-1].reason_codes[0] if actions else "POSITION_CLOSED"
        assembled = assemble_trade_journal_entry(
            TradeLifecycleInput(
                feature_snapshot_id=lifecycle.evaluation.feature.snapshot_id,
                opening_plan=submission.plan,
                opening_attempt=submission.simulation.attempt,
                exit_plans=tuple(lifecycle.exit_plans.values()),
                exit_attempts=tuple(lifecycle.exit_attempts.values()),
                fills=tuple(lifecycle.fills.values()),
                position_actions=actions,
                funding_accruals=tuple(lifecycle.funding.values()),
                equity_before=lifecycle.opening.equity_before,
                equity_after=self._execution.account.equity,
                exit_reason=exit_reason,
                mark_observations=tuple(lifecycle.marks.values()),
                known_gap_intervals=tuple(self._gap_intervals),
                evidence_class=self._evidence_class,
                replay_run_id=self._run_id,
            )
        )
        if isinstance(assembled, JournalInconsistency) or not isinstance(
            assembled,
            TradeJournalEntry,
        ):
            detail = (
                assembled.reason
                if isinstance(assembled, JournalInconsistency)
                else type(assembled).__name__
            )
            raise ReplayInvariantError(f"journal lifecycle inconsistent: {detail}")
        self._completed[assembled.trade_id] = assembled
        del self._lifecycles[market.canonical]

    def _manage_book(
        self,
        book: StreamEvent,
        now_ms: int,
    ) -> tuple[JournalObservation, ...]:
        matches = tuple(
            position
            for position in self._execution.account.positions
            if position.market == book.market
        )
        if not matches:
            return ()
        if len(matches) != 1:
            raise ReplayInvariantError("paper account contains duplicate market positions")
        position = matches[0]
        state = self._state.state(position.market)
        snapshot = state.latest_snapshot
        if snapshot is None:
            return ()
        instrument = _instrument(snapshot, self._config.execution)
        micro = calculate_microstructure_features(book, as_of_ms=now_ms)
        mark_event = self._latest_mark.get(position.market.canonical)
        decision = self._latest_strategy(position.market)
        action_timestamp = now_ms if mark_event is None else _receive_ms(mark_event)
        if action_timestamp < position.updated_at_ms:
            action_timestamp = now_ms
        management = self._execution.manage_position(
            position.market,
            instrument,
            mark_event,
            book,
            strategy_decision=decision,
            strategy_fresh=self._strategy_fresh(decision, action_timestamp),
            critical_health=not self._execution.health.healthy_for_new_exposure,
            explicit_reduction_quantity=None,
            reference_price=micro.mid_px,
            timestamp_ms=action_timestamp,
            attempt_timestamp_ms=now_ms,
        )
        self._append_management_to_lifecycle(management)
        observations = list(self._record_management(management))
        if not any(
            current.market == position.market
            for current in self._execution.account.positions
        ):
            self._close_lifecycle(position.market)
        return tuple(observations)

    def _handle_book(
        self,
        record: ReplayRecord,
        book: StreamEvent,
        now_ms: int,
    ) -> tuple[JournalObservation, ...]:
        del record
        observations = list(self._manage_book(book, now_ms))
        if not self._funding_inconsistent:
            self._opening.on_book(book, now_ms)
            for trace in self._opening.take_traces():
                observations.extend(self._record_opening_trace(trace))
        return tuple(observations)

    def on_record(
        self,
        record: ReplayRecord,
        now_ms: int,
    ) -> tuple[JournalObservation, ...]:
        if now_ms < record.available_at_ms:
            raise ReplayInvariantError("baseline replay consumed future evidence")
        observations = list(self._ensure_initial_account_observation())

        if record.record_kind is SourceRecordKind.DATA_GAP:
            self._gap_intervals.append((record.available_at_ms, None))

        for epoch in self._decision_engine.observe(record, now_ms):
            observations.extend(self._process_epoch(epoch))

        if record.record_kind is SourceRecordKind.DATA_GAP:
            observations.extend(self._due_funding(now_ms))
            return tuple(observations)
        if record.event_kind is None:
            raise ReplayInvariantError("normalized baseline record is missing event_kind")

        if record.event_kind == StreamKind.ACTIVE_ASSET_CTX.value:
            event = replay_record_stream_event(record)
            observations.extend(self._mark_account(record, event, now_ms))
            observations.extend(self._due_funding(now_ms))
        elif record.event_kind == "funding_rate":
            replay_record_funding_rate(record)
            observations.extend(self._due_funding(now_ms))
        elif record.event_kind == StreamKind.L2_BOOK.value:
            book = replay_record_stream_event(record)
            observations.extend(self._due_funding(now_ms))
            observations.extend(self._handle_book(record, book, now_ms))
            observations.extend(self._due_funding(now_ms))
        else:
            observations.extend(self._due_funding(now_ms))
        return tuple(observations)

    def finalize(self, end_ms: int) -> tuple[TradeJournalEntry, ...]:
        if end_ms < 0:
            raise ValueError("end_ms must be non-negative")
        return tuple(
            sorted(
                self._completed.values(),
                key=lambda item: (item.closed_at_ms, item.trade_id),
            )
        )

    def replay_activity(self) -> ReplayActivity:
        fill_ids = {
            fill_id
            for trade in self._completed.values()
            for fill_id in trade.fill_ids
        }
        for lifecycle in self._lifecycles.values():
            fill_ids.update(lifecycle.fills)
        return ReplayActivity(
            fills=len(fill_ids),
            opened_positions=len(self._completed) + len(self._lifecycles),
            closed_positions=len(self._completed),
        )

    def replay_pipeline(self) -> ReplayPipeline:
        return ReplayPipeline(
            on_record=self.on_record,
            finalize=self.finalize,
            requirements=ReplayRequirements(requires_l2=True),
            activity=self.replay_activity,
        )
