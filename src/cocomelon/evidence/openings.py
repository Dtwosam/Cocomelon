from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.execution import InstrumentExecutionSpec, PaperExecutionConfig
from cocomelon.domain.market import MarketId, PerpMarketSnapshot
from cocomelon.domain.risk import (
    ExecutionCostEstimate,
    LiquidityRiskState,
    RiskHealthState,
    RiskRequest,
)
from cocomelon.domain.strategy import Direction, StrategyContext
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.baseline import RecordedStateBook
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import (
    DECISION_INTERVAL_MS,
    DecisionEpoch,
    EpochMarketEvaluation,
    _effective_snapshot,
)
from cocomelon.execution.accounting import risk_state_from_paper
from cocomelon.execution.interface import OpeningSubmission
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.features.microstructure import calculate_microstructure_features
from cocomelon.strategies.microstructure import build_microstructure_window
from cocomelon.strategies.order_flow import evaluate_order_flow

BPS = Decimal("10000")
ONE = Decimal("1")
ZERO = Decimal("0")
ENTRY_TRIGGER_MIN_SCORE = Decimal("75")
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class _PendingOpening:
    evaluated_at_ms: int
    evaluation: EpochMarketEvaluation

    @property
    def market(self) -> MarketId:
        return self.evaluation.decision.market


@dataclass(frozen=True, slots=True)
class EntryTimingActivity:
    pending_candidates: int
    expired_candidates: int
    superseded_candidates: int
    trigger_waits: int
    trigger_approvals: int
    wait_reason_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class BaselineOpeningTrace:
    evaluation: EpochMarketEvaluation
    submission: OpeningSubmission
    equity_before: Decimal

    def __post_init__(self) -> None:
        if not self.equity_before.is_finite() or self.equity_before <= ZERO:
            raise ValueError("equity_before must be positive and finite")
        if (
            self.evaluation.decision.decision_id
            != self.submission.risk_decision.strategy_decision_id
        ):
            raise ValueError("opening trace strategy lineage mismatch")


def _receive_ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1000)


def conservative_cost_estimate(config: PaperExecutionConfig) -> ExecutionCostEstimate:
    with localcontext(AUTHORITATIVE_CONTEXT):
        slippage = config.max_ioc_slippage_bps / BPS
        round_trip_fee = config.taker_fee_rate * Decimal("2")
    return ExecutionCostEstimate(
        entry_slippage_fraction=slippage,
        stop_slippage_fraction=slippage,
        round_trip_fee_fraction=round_trip_fee,
    )


def paper_liquidation_surrogate(
    entry: Decimal,
    direction: Direction,
    *,
    paper_max_leverage: Decimal,
    venue_max_leverage: Decimal,
) -> Decimal:
    """Return a conservative paper risk surrogate, never a venue liquidation quote."""
    for value, field in (
        (entry, "entry"),
        (paper_max_leverage, "paper_max_leverage"),
        (venue_max_leverage, "venue_max_leverage"),
    ):
        if not value.is_finite() or value <= ZERO:
            raise ValueError(f"{field} must be finite and positive")
    if direction is Direction.NO_TRADE:
        raise ValueError("liquidation surrogate requires LONG or SHORT direction")

    leverage = min(paper_max_leverage, venue_max_leverage)
    with localcontext(AUTHORITATIVE_CONTEXT):
        distance = ONE / leverage
        if direction is Direction.LONG:
            result = entry * (ONE - distance)
        else:
            result = entry * (ONE + distance)
    if result <= ZERO:
        raise ValueError("paper liquidation surrogate must remain positive")
    return result


def _instrument(
    snapshot: PerpMarketSnapshot,
    config: PaperExecutionConfig,
) -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=snapshot.meta.market,
        sz_decimals=snapshot.meta.sz_decimals,
        venue_max_leverage=Decimal(snapshot.meta.max_leverage),
        minimum_order_notional=config.native_perp_min_notional,
        metadata_received_at_ms=snapshot.received_at_ms,
        metadata_source=snapshot.source,
    )


class BaselineOpeningEngine:
    def __init__(
        self,
        replay_config: BaselineReplayConfig,
        execution: PaperExecutionAdapter,
        state_book: RecordedStateBook,
        *,
        require_fresh_order_flow_entry: bool = False,
    ) -> None:
        self._config = replay_config
        self._execution = execution
        self._state = state_book
        self._pending: list[_PendingOpening] = []
        self._books: dict[str, StreamEvent] = {}
        self._traces: list[BaselineOpeningTrace] = []
        self._require_fresh_order_flow_entry = require_fresh_order_flow_entry
        self._expired_candidates = 0
        self._superseded_candidates = 0
        self._trigger_waits = 0
        self._trigger_approvals = 0
        self._wait_reason_counts: dict[str, int] = {}

    @property
    def pending_markets(self) -> tuple[MarketId, ...]:
        return tuple(item.market for item in self._pending)

    @property
    def entry_timing_activity(self) -> EntryTimingActivity:
        return EntryTimingActivity(
            pending_candidates=len(self._pending),
            expired_candidates=self._expired_candidates,
            superseded_candidates=self._superseded_candidates,
            trigger_waits=self._trigger_waits,
            trigger_approvals=self._trigger_approvals,
            wait_reason_counts=tuple(sorted(self._wait_reason_counts.items())),
        )

    def take_traces(self) -> tuple[BaselineOpeningTrace, ...]:
        traces = tuple(self._traces)
        self._traces.clear()
        return traces

    def stage_epoch(self, epoch: DecisionEpoch) -> None:
        evaluated_markets = {
            item.decision.market.canonical for item in epoch.markets
        }
        retained = [
            item
            for item in self._pending
            if item.market.canonical not in evaluated_markets
        ]
        self._superseded_candidates += len(self._pending) - len(retained)
        self._pending = retained

        directional = tuple(
            item
            for item in epoch.markets
            if item.decision.direction is not Direction.NO_TRADE
        )
        for evaluation in directional:
            self._pending.append(
                _PendingOpening(
                    evaluated_at_ms=epoch.evaluated_at_ms,
                    evaluation=evaluation,
                )
            )
        self._pending.sort(
            key=lambda item: (
                item.evaluated_at_ms,
                item.market.canonical,
            )
        )

    def _expire_pending(self, now_ms: int) -> None:
        retained: list[_PendingOpening] = []
        for pending in self._pending:
            if now_ms >= pending.evaluated_at_ms + DECISION_INTERVAL_MS:
                self._expired_candidates += 1
                continue
            retained.append(pending)
        self._pending = retained

    def _record_trigger_wait(self, reasons: tuple[str, ...]) -> None:
        self._trigger_waits += 1
        for reason in reasons:
            self._wait_reason_counts[reason] = (
                self._wait_reason_counts.get(reason, 0) + 1
            )

    def _entry_trigger_ready(
        self,
        pending: _PendingOpening,
        *,
        now_ms: int,
    ) -> bool:
        state = self._state.state(pending.market)
        snapshot = _effective_snapshot(state, as_of_ms=now_ms)
        if snapshot is None:
            self._record_trigger_wait(("missing_market_context",))
            return False
        events = tuple(
            event
            for event in state.micro_events
            if _receive_ms(event) <= now_ms
        )
        microstructure = build_microstructure_window(
            events,
            market=pending.market,
            as_of_ms=now_ms,
            window_ms=self._config.microstructure_window_ms,
        )
        context = StrategyContext(
            market_snapshot=snapshot,
            feature_snapshot=pending.evaluation.feature,
            eligibility=pending.evaluation.eligibility,
            candles_5m=tuple(
                state.candles_5m[key] for key in sorted(state.candles_5m)
            ),
            candles_15m=tuple(
                state.candles_15m[key] for key in sorted(state.candles_15m)
            ),
            microstructure=microstructure,
            as_of_ms=now_ms,
        )
        signal = evaluate_order_flow(context)
        direction = pending.evaluation.decision.direction
        if direction in signal.veto_directions:
            self._record_trigger_wait(("fresh_order_flow_veto", *signal.reason_codes))
            return False
        if signal.direction is direction and signal.score >= ENTRY_TRIGGER_MIN_SCORE:
            self._trigger_approvals += 1
            return True
        self._record_trigger_wait(("fresh_order_flow_not_supportive", *signal.reason_codes))
        return False

    def _refresh_account(self, now_ms: int) -> bool:
        marks: dict[MarketId, Decimal] = {}
        for position in self._execution.account.positions:
            state = self._state.state(position.market)
            snapshot = _effective_snapshot(state, as_of_ms=now_ms)
            if snapshot is None:
                return False
            mark = snapshot.context.mark_px
            if mark is None or not mark.is_finite() or mark <= ZERO:
                return False
            marks[position.market] = mark
        self._execution.mark_account_to_market(marks, timestamp_ms=now_ms)
        return True

    def _risk_request(
        self,
        pending: _PendingOpening,
        book: StreamEvent,
        *,
        now_ms: int,
    ) -> tuple[RiskRequest, InstrumentExecutionSpec, Decimal]:
        market = pending.market
        state = self._state.state(market)
        full_snapshot = state.latest_snapshot
        if full_snapshot is None:
            raise ValueError("baseline opening requires a recorded full market snapshot")
        if full_snapshot.received_at_ms > now_ms:
            raise ValueError("baseline opening market metadata is from the future")
        snapshot = _effective_snapshot(state, as_of_ms=now_ms)
        if snapshot is None:
            raise ValueError("baseline opening requires recorded market context")

        account_refreshed = self._refresh_account(now_ms)
        risk_account, open_positions = risk_state_from_paper(self._execution.account)
        micro = calculate_microstructure_features(book, as_of_ms=now_ms)
        direction = pending.evaluation.decision.direction
        if direction is Direction.LONG:
            entry_depth = micro.ask_depth_25bps
            exit_depth = micro.bid_depth_25bps
        elif direction is Direction.SHORT:
            entry_depth = micro.bid_depth_25bps
            exit_depth = micro.ask_depth_25bps
        else:
            raise ValueError("baseline opening candidate must be directional")

        instrument = _instrument(full_snapshot, self._config.execution)
        liquidation = paper_liquidation_surrogate(
            micro.mid_px,
            direction,
            paper_max_leverage=self._config.execution.paper_max_gross_leverage,
            venue_max_leverage=instrument.venue_max_leverage,
        )
        book_received_ms = _receive_ms(book)
        context_age_ms = now_ms - snapshot.received_at_ms
        book_age_ms = now_ms - book_received_ms
        market_fresh = (
            context_age_ms >= 0
            and context_age_ms <= self._config.execution.max_asset_ctx_age_ms
            and book_age_ms >= 0
            and book_age_ms <= self._config.execution.max_book_age_ms
        )
        account_fresh = (
            account_refreshed
            and now_ms - self._execution.account.updated_at_ms
            <= self._config.risk_limits.max_state_age_ms
        )
        state_consistent = (
            snapshot.meta.market == market
            and book.market == market
            and book.exchange_time_ms is not None
            and book.exchange_time_ms <= now_ms
        )
        request = RiskRequest(
            strategy_decision=pending.evaluation.decision,
            entry_reference_price=micro.mid_px,
            correlation_bucket=self._config.correlation_bucket,
            account_state=risk_account,
            open_positions=open_positions,
            health_state=RiskHealthState(
                market_data_fresh=market_fresh,
                account_state_fresh=account_fresh,
                execution_health_ok=self._execution.health.healthy_for_new_exposure,
                state_consistent=state_consistent,
                as_of_ms=now_ms,
            ),
            cost_estimate=conservative_cost_estimate(self._config.execution),
            liquidity_state=LiquidityRiskState(
                entry_side_visible_notional_25bps=entry_depth,
                exit_side_visible_notional_25bps=exit_depth,
                venue_max_leverage=instrument.venue_max_leverage,
                liquidation_price=liquidation,
                venue_min_notional=instrument.minimum_order_notional,
                as_of_ms=book_received_ms,
            ),
            limits=self._config.risk_limits,
            timestamp_ms=now_ms,
        )
        return request, instrument, micro.mid_px

    def on_book(
        self,
        book: StreamEvent,
        now_ms: int,
    ) -> tuple[OpeningSubmission, ...]:
        if book.kind is not StreamKind.L2_BOOK:
            raise ValueError("baseline opening engine accepts only L2 book events")
        received_ms = _receive_ms(book)
        if received_ms > now_ms:
            raise ValueError("book cannot be consumed before receive time")
        existing = self._books.get(book.market.canonical)
        if existing is None or _receive_ms(existing) <= received_ms:
            self._books[book.market.canonical] = book

        self._expire_pending(now_ms)
        outcomes: list[OpeningSubmission] = []

        if self._require_fresh_order_flow_entry:
            candidates = tuple(
                pending
                for pending in self._pending
                if pending.market == book.market
            )
            for pending in candidates:
                earliest_ms = (
                    pending.evaluated_at_ms + self._config.execution.latency_ms
                )
                if received_ms < earliest_ms:
                    continue
                if not self._entry_trigger_ready(pending, now_ms=now_ms):
                    continue
                request, instrument, reference = self._risk_request(
                    pending,
                    book,
                    now_ms=now_ms,
                )
                equity_before = self._execution.account.equity
                submission = self._execution.submit_risk_request(
                    request,
                    instrument,
                    book,
                    reference_price=reference,
                    created_at_ms=pending.evaluated_at_ms,
                    attempt_timestamp_ms=now_ms,
                )
                outcomes.append(submission)
                self._traces.append(
                    BaselineOpeningTrace(
                        evaluation=pending.evaluation,
                        submission=submission,
                        equity_before=equity_before,
                    )
                )
                self._pending.remove(pending)
            return tuple(outcomes)

        while self._pending:
            pending = self._pending[0]
            candidate_book = self._books.get(pending.market.canonical)
            if candidate_book is None:
                break
            earliest_ms = pending.evaluated_at_ms + self._config.execution.latency_ms
            if _receive_ms(candidate_book) < earliest_ms:
                break

            request, instrument, reference = self._risk_request(
                pending,
                candidate_book,
                now_ms=now_ms,
            )
            equity_before = self._execution.account.equity
            submission = self._execution.submit_risk_request(
                request,
                instrument,
                candidate_book,
                reference_price=reference,
                created_at_ms=pending.evaluated_at_ms,
                attempt_timestamp_ms=now_ms,
            )
            outcomes.append(submission)
            self._traces.append(
                BaselineOpeningTrace(
                    evaluation=pending.evaluation,
                    submission=submission,
                    equity_before=equity_before,
                )
            )
            self._pending.pop(0)
        return tuple(outcomes)
