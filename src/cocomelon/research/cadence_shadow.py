from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.market import Candle, MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction
from cocomelon.evidence.baseline import replay_record_candle
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import (
    BaselineDecisionEngine,
    DecisionEpoch,
    _effective_snapshot,
)
from cocomelon.research.historical_baselines import ExecutionCostAssumptions

FIVE_MINUTES_MS: Final = 5 * 60 * 1_000
FIFTEEN_MINUTES_MS: Final = 15 * 60 * 1_000
ONE_HOUR_MS: Final = 60 * 60 * 1_000
SUPPORTED_CADENCES_MS: Final = (FIVE_MINUTES_MS, FIFTEEN_MINUTES_MS)
DEFAULT_HORIZONS_MS: Final = (FIFTEEN_MINUTES_MS, ONE_HOUR_MS)
DEFAULT_COSTS: Final = ExecutionCostAssumptions(
    round_trip_fee_fraction=Decimal("0.0009"),
    round_trip_slippage_fraction=Decimal("0.0005"),
    funding_reserve_fraction_per_hour=Decimal("0.0001"),
)
ZERO: Final = Decimal("0")


def _initial_boundary_for_interval(
    available_at_ms: int,
    *,
    grace_ms: int,
    interval_ms: int,
) -> int:
    if available_at_ms < 0:
        raise ValueError("available_at_ms must be non-negative")
    if grace_ms < 0:
        raise ValueError("grace_ms must be non-negative")
    if interval_ms <= 0:
        raise ValueError("interval_ms must be positive")
    floor = available_at_ms // interval_ms * interval_ms
    if available_at_ms <= floor + grace_ms:
        return floor
    return floor + interval_ms


class ShadowCadenceDecisionEngine(BaselineDecisionEngine):
    """Research-only decision clock over the unchanged baseline strategy stack."""

    def __init__(
        self,
        selected_markets: Sequence[MarketId],
        *,
        replay_config: BaselineReplayConfig,
        interval_ms: int,
    ) -> None:
        if interval_ms not in SUPPORTED_CADENCES_MS:
            raise ValueError("unsupported shadow cadence")
        super().__init__(
            selected_markets,
            replay_config=replay_config,
        )
        self._shadow_interval_ms = interval_ms

    @property
    def interval_ms(self) -> int:
        return self._shadow_interval_ms

    def _emit_shadow_due(
        self,
        cutoff_ms: int,
        *,
        inclusive: bool,
    ) -> tuple[DecisionEpoch, ...]:
        emitted: list[DecisionEpoch] = []
        while self._next_boundary_ms is not None:
            evaluated_at_ms = (
                self._next_boundary_ms + self._config.decision_grace_ms
            )
            due = (
                evaluated_at_ms <= cutoff_ms
                if inclusive
                else evaluated_at_ms < cutoff_ms
            )
            if not due:
                break
            emitted.append(self._evaluate_epoch(self._next_boundary_ms))
            self._next_boundary_ms += self._shadow_interval_ms
        return tuple(emitted)

    def observe(
        self,
        record: ReplayRecord,
        now_ms: int,
    ) -> tuple[DecisionEpoch, ...]:
        if now_ms < record.available_at_ms:
            raise ValueError("now_ms cannot precede record availability")
        if (
            self._last_available_at_ms is not None
            and record.available_at_ms < self._last_available_at_ms
        ):
            raise ValueError(
                "shadow cadence records must not regress in availability time"
            )
        if self._next_boundary_ms is None:
            self._next_boundary_ms = _initial_boundary_for_interval(
                record.available_at_ms,
                grace_ms=self._config.decision_grace_ms,
                interval_ms=self._shadow_interval_ms,
            )

        emitted = self._emit_shadow_due(
            record.available_at_ms,
            inclusive=False,
        )
        self._state.apply(record, now_ms)
        self._last_available_at_ms = record.available_at_ms
        return emitted

    def flush(self, end_ms: int) -> tuple[DecisionEpoch, ...]:
        if end_ms < 0:
            raise ValueError("end_ms must be non-negative")
        if (
            self._last_available_at_ms is not None
            and end_ms < self._last_available_at_ms
        ):
            raise ValueError(
                "flush end_ms cannot precede observed shadow evidence"
            )
        return self._emit_shadow_due(end_ms, inclusive=True)


@dataclass(frozen=True, slots=True)
class ShadowCadenceDecision:
    cadence_ms: int
    boundary_ms: int
    evaluated_at_ms: int
    market: MarketId
    direction: Direction
    score: Decimal
    decision_id: str
    feature_snapshot_id: str
    entry_px: Decimal
    horizon_ms: int
    target_end_ms: int
    cost_fraction: Decimal
    off_primary_boundary: bool

    def __post_init__(self) -> None:
        if self.cadence_ms not in SUPPORTED_CADENCES_MS:
            raise ValueError("unsupported cadence_ms")
        if self.boundary_ms < 0 or self.evaluated_at_ms < self.boundary_ms:
            raise ValueError("decision timestamps are invalid")
        if self.direction is Direction.NO_TRADE:
            raise ValueError("shadow cadence sample must be directional")
        if not self.score.is_finite():
            raise ValueError("score must be finite")
        if not self.decision_id.strip() or not self.feature_snapshot_id.strip():
            raise ValueError("decision lineage must not be empty")
        if not self.entry_px.is_finite() or self.entry_px <= ZERO:
            raise ValueError("entry_px must be positive and finite")
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if self.target_end_ms != self.boundary_ms + self.horizon_ms:
            raise ValueError("target_end_ms must equal boundary plus horizon")
        if (
            not self.cost_fraction.is_finite()
            or self.cost_fraction < ZERO
        ):
            raise ValueError("cost_fraction must be non-negative and finite")


@dataclass(frozen=True, slots=True)
class ShadowCadenceOutcome:
    sample: ShadowCadenceDecision
    exit_px: Decimal
    gross_return: Decimal
    net_return: Decimal

    def __post_init__(self) -> None:
        if not self.exit_px.is_finite() or self.exit_px <= ZERO:
            raise ValueError("exit_px must be positive and finite")
        if not self.gross_return.is_finite() or not self.net_return.is_finite():
            raise ValueError("returns must be finite")
        expected_net = self.gross_return - self.sample.cost_fraction
        if self.net_return != expected_net:
            raise ValueError("net_return does not match gross minus costs")


def settle_shadow_decision(
    sample: ShadowCadenceDecision,
    *,
    exit_px: Decimal,
) -> ShadowCadenceOutcome:
    if not exit_px.is_finite() or exit_px <= ZERO:
        raise ValueError("exit_px must be positive and finite")
    if sample.direction is Direction.LONG:
        gross = (exit_px - sample.entry_px) / sample.entry_px
    elif sample.direction is Direction.SHORT:
        gross = (sample.entry_px - exit_px) / sample.entry_px
    else:
        raise ValueError("cannot settle a NO_TRADE sample")
    return ShadowCadenceOutcome(
        sample=sample,
        exit_px=exit_px,
        gross_return=gross,
        net_return=gross - sample.cost_fraction,
    )


class CadenceShadowComparator:
    """Non-economic 5m vs 15m cadence observer over authenticated live evidence."""

    def __init__(
        self,
        selected_markets: Sequence[MarketId],
        *,
        replay_config: BaselineReplayConfig | None = None,
        horizons_ms: Sequence[int] = DEFAULT_HORIZONS_MS,
        costs: ExecutionCostAssumptions = DEFAULT_COSTS,
    ) -> None:
        config = replay_config or BaselineReplayConfig()
        horizons = tuple(sorted(set(horizons_ms)))
        if not horizons or any(
            value <= 0 or value % FIVE_MINUTES_MS != 0
            for value in horizons
        ):
            raise ValueError(
                "shadow horizons must be positive 5m multiples"
            )
        markets = tuple(
            sorted(set(selected_markets), key=lambda item: item.canonical)
        )
        if not markets:
            raise ValueError("selected_markets must not be empty")

        self._horizons_ms = horizons
        self._costs = costs
        self._engines = {
            interval_ms: ShadowCadenceDecisionEngine(
                markets,
                replay_config=config,
                interval_ms=interval_ms,
            )
            for interval_ms in SUPPORTED_CADENCES_MS
        }
        self._decision_counts: dict[int, Counter[str]] = {
            interval_ms: Counter()
            for interval_ms in SUPPORTED_CADENCES_MS
        }
        self._pending: dict[
            tuple[str, int],
            list[ShadowCadenceDecision],
        ] = defaultdict(list)
        self._outcomes: list[ShadowCadenceOutcome] = []
        self._censored_count = 0
        self._skipped_missing_entry_px = 0

    def reconcile_markets(
        self,
        selected_markets: Sequence[MarketId],
    ) -> None:
        markets = tuple(
            sorted(set(selected_markets), key=lambda item: item.canonical)
        )
        if not markets:
            raise ValueError("selected_markets must not be empty")
        active = {market.canonical for market in markets}
        for engine in self._engines.values():
            engine.reconcile_markets(markets)

        for key in tuple(self._pending):
            if key[0] in active:
                continue
            self._censored_count += len(self._pending.pop(key))

    def _capture_epoch(
        self,
        cadence_ms: int,
        engine: ShadowCadenceDecisionEngine,
        epoch: DecisionEpoch,
    ) -> None:
        counts = self._decision_counts[cadence_ms]
        for evaluation in epoch.markets:
            direction = evaluation.decision.direction
            counts[direction.value] += 1
            if direction is Direction.NO_TRADE:
                continue

            state = engine.state_book.state(evaluation.decision.market)
            snapshot = _effective_snapshot(
                state,
                as_of_ms=epoch.evaluated_at_ms,
            )
            if snapshot is None:
                self._skipped_missing_entry_px += 1
                continue
            entry_px = snapshot.context.mid_px
            if entry_px is None:
                entry_px = snapshot.context.mark_px
            if (
                entry_px is None
                or not entry_px.is_finite()
                or entry_px <= ZERO
            ):
                self._skipped_missing_entry_px += 1
                continue

            for horizon_ms in self._horizons_ms:
                sample = ShadowCadenceDecision(
                    cadence_ms=cadence_ms,
                    boundary_ms=epoch.boundary_ms,
                    evaluated_at_ms=epoch.evaluated_at_ms,
                    market=evaluation.decision.market,
                    direction=direction,
                    score=evaluation.decision.score,
                    decision_id=evaluation.decision.decision_id,
                    feature_snapshot_id=evaluation.feature.snapshot_id,
                    entry_px=entry_px,
                    horizon_ms=horizon_ms,
                    target_end_ms=epoch.boundary_ms + horizon_ms,
                    cost_fraction=self._costs.total_cost_fraction(
                        horizon_ms
                    ),
                    off_primary_boundary=(
                        epoch.boundary_ms % FIFTEEN_MINUTES_MS != 0
                    ),
                )
                self._pending[
                    (sample.market.canonical, sample.target_end_ms)
                ].append(sample)

    def _settle_candle(self, candle: Candle) -> None:
        key = (candle.market.canonical, candle.end_ms)
        samples = tuple(self._pending.pop(key, []))
        for sample in samples:
            self._outcomes.append(
                settle_shadow_decision(
                    sample,
                    exit_px=candle.close_px,
                )
            )

    def observe(
        self,
        record: ReplayRecord,
        now_ms: int,
    ) -> None:
        for cadence_ms in SUPPORTED_CADENCES_MS:
            engine = self._engines[cadence_ms]
            for epoch in engine.observe(record, now_ms):
                self._capture_epoch(cadence_ms, engine, epoch)

        if (
            record.record_kind is SourceRecordKind.NORMALIZED_EVENT
            and record.event_kind == "candle"
        ):
            candle = replay_record_candle(record)
            if (
                candle.interval == "5m"
                and record.available_at_ms >= candle.end_ms
            ):
                self._settle_candle(candle)

    def _outcome_summary(
        self,
        *,
        cadence_ms: int,
        horizon_ms: int,
        off_primary_only: bool,
    ) -> dict[str, object]:
        outcomes = tuple(
            item
            for item in self._outcomes
            if item.sample.cadence_ms == cadence_ms
            and item.sample.horizon_ms == horizon_ms
            and (
                not off_primary_only
                or item.sample.off_primary_boundary
            )
        )
        net_sum = sum(
            (item.net_return for item in outcomes),
            ZERO,
        )
        gross_sum = sum(
            (item.gross_return for item in outcomes),
            ZERO,
        )
        count = len(outcomes)
        return {
            "settled_count": count,
            "positive_net_count": sum(
                1 for item in outcomes if item.net_return > ZERO
            ),
            "negative_net_count": sum(
                1 for item in outcomes if item.net_return < ZERO
            ),
            "flat_net_count": sum(
                1 for item in outcomes if item.net_return == ZERO
            ),
            "gross_return_sum": str(gross_sum),
            "net_return_sum": str(net_sum),
            "mean_gross_return": (
                None if count == 0 else str(gross_sum / Decimal(count))
            ),
            "mean_net_return": (
                None if count == 0 else str(net_sum / Decimal(count))
            ),
        }

    def summary_payload(self) -> dict[str, object]:
        cadence_payload: dict[str, object] = {}
        for cadence_ms in SUPPORTED_CADENCES_MS:
            counts = self._decision_counts[cadence_ms]
            outcomes_by_horizon: dict[str, object] = {}
            off_cycle_by_horizon: dict[str, object] = {}
            for horizon_ms in self._horizons_ms:
                key = str(horizon_ms)
                outcomes_by_horizon[key] = self._outcome_summary(
                    cadence_ms=cadence_ms,
                    horizon_ms=horizon_ms,
                    off_primary_only=False,
                )
                off_cycle_by_horizon[key] = self._outcome_summary(
                    cadence_ms=cadence_ms,
                    horizon_ms=horizon_ms,
                    off_primary_only=True,
                )
            cadence_payload[str(cadence_ms)] = {
                "decision_counts": {
                    "long": counts[Direction.LONG.value],
                    "short": counts[Direction.SHORT.value],
                    "no_trade": counts[Direction.NO_TRADE.value],
                },
                "directional_count": (
                    counts[Direction.LONG.value]
                    + counts[Direction.SHORT.value]
                ),
                "outcomes_by_horizon_ms": outcomes_by_horizon,
                "off_primary_boundary_outcomes_by_horizon_ms": (
                    off_cycle_by_horizon
                ),
            }

        pending_by_cadence = Counter(
            sample.cadence_ms
            for samples in self._pending.values()
            for sample in samples
        )
        return {
            "shadow_only": True,
            "execution_authority": False,
            "session_only": True,
            "primary_execution_cadence_ms": FIFTEEN_MINUTES_MS,
            "candidate_cadence_ms": FIVE_MINUTES_MS,
            "horizons_ms": list(self._horizons_ms),
            "costs": {
                "round_trip_fee_fraction": str(
                    self._costs.round_trip_fee_fraction
                ),
                "round_trip_slippage_fraction": str(
                    self._costs.round_trip_slippage_fraction
                ),
                "funding_reserve_fraction_per_hour": str(
                    self._costs.funding_reserve_fraction_per_hour
                ),
            },
            "cadences": cadence_payload,
            "pending_outcome_count": sum(pending_by_cadence.values()),
            "pending_by_cadence_ms": {
                str(key): value
                for key, value in sorted(pending_by_cadence.items())
            },
            "censored_due_to_unsubscribe": self._censored_count,
            "skipped_missing_entry_px": self._skipped_missing_entry_px,
        }
