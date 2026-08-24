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
from cocomelon.domain.strategy import Direction
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.baseline import RecordedStateBook
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import DecisionEpoch, EpochMarketEvaluation, _effective_snapshot
from cocomelon.execution.accounting import risk_state_from_paper
from cocomelon.execution.interface import OpeningSubmission
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.features.microstructure import calculate_microstructure_features

BPS = Decimal("10000")
ONE = Decimal("1")
ZERO = Decimal("0")
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class _PendingOpening:
    evaluated_at_ms: int
    evaluation: EpochMarketEvaluation

    @property
    def market(self) -> MarketId:
        return self.evaluation.decision.market


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
    ) -> None:
        self._config = replay_config
        self._execution = execution
        self._state = state_book
        self._pending: list[_PendingOpening] = []
        self._books: dict[str, StreamEvent] = {}
        self._traces: list[BaselineOpeningTrace] = []

    @property
    def pending_markets(self) -> tuple[MarketId, ...]:
        return tuple(item.market for item in self._pending)

    def take_traces(self) -> tuple[BaselineOpeningTrace, ...]:
        traces = tuple(self._traces)
        self._traces.clear()
        return traces

    def stage_epoch(self, epoch: DecisionEpoch) -> None:
        directional = tuple(
            item
            for item in epoch.markets
            if item.decision.direction is not Direction.NO_TRADE
        )
        existing = {
            (item.evaluated_at_ms, item.market.canonical) for item in self._pending
        }
        for evaluation in directional:
            key = (epoch.evaluated_at_ms, evaluation.decision.market.canonical)
            if key in existing:
                raise ValueError("baseline opening candidate already staged")
            self._pending.append(
                _PendingOpening(
                    evaluated_at_ms=epoch.evaluated_at_ms,
                    evaluation=evaluation,
                )
            )
            existing.add(key)
        self._pending.sort(
            key=lambda item: (
                item.evaluated_at_ms,
                item.market.canonical,
            )
        )

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

        outcomes: list[OpeningSubmission] = []
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
