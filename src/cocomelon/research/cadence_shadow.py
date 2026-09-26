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
CADENCE_SHADOW_STATE_SCHEMA_VERSION: Final = 1


def _score_band(score: Decimal) -> str:
    if score < Decimal("65"):
        return "<65"
    if score < Decimal("70"):
        return "65-<70"
    if score < Decimal("75"):
        return "70-<75"
    if score < Decimal("80"):
        return "75-<80"
    return "80+"


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
    lead_strategy: str
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
        if not self.lead_strategy.strip():
            raise ValueError("lead_strategy must not be empty")
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


def _market_from_canonical(value: str) -> MarketId:
    if ":" in value:
        dex = value.split(":", 1)[0]
        return MarketId.from_wire_name(dex, value)
    return MarketId.from_wire_name("", value)


def _sample_key(sample: ShadowCadenceDecision) -> tuple[int, str, int]:
    return sample.cadence_ms, sample.decision_id, sample.horizon_ms


def _sample_payload(sample: ShadowCadenceDecision) -> dict[str, object]:
    return {
        "cadence_ms": sample.cadence_ms,
        "boundary_ms": sample.boundary_ms,
        "evaluated_at_ms": sample.evaluated_at_ms,
        "market": sample.market.canonical,
        "direction": sample.direction.value,
        "score": str(sample.score),
        "lead_strategy": sample.lead_strategy,
        "decision_id": sample.decision_id,
        "feature_snapshot_id": sample.feature_snapshot_id,
        "entry_px": str(sample.entry_px),
        "horizon_ms": sample.horizon_ms,
        "target_end_ms": sample.target_end_ms,
        "cost_fraction": str(sample.cost_fraction),
        "off_primary_boundary": sample.off_primary_boundary,
    }


def _sample_from_payload(raw: object) -> ShadowCadenceDecision:
    if not isinstance(raw, dict):
        raise ValueError("cadence shadow sample state must be an object")
    return ShadowCadenceDecision(
        cadence_ms=int(raw["cadence_ms"]),
        boundary_ms=int(raw["boundary_ms"]),
        evaluated_at_ms=int(raw["evaluated_at_ms"]),
        market=_market_from_canonical(str(raw["market"])),
        direction=Direction(str(raw["direction"])),
        score=Decimal(str(raw["score"])),
        lead_strategy=str(raw["lead_strategy"]),
        decision_id=str(raw["decision_id"]),
        feature_snapshot_id=str(raw["feature_snapshot_id"]),
        entry_px=Decimal(str(raw["entry_px"])),
        horizon_ms=int(raw["horizon_ms"]),
        target_end_ms=int(raw["target_end_ms"]),
        cost_fraction=Decimal(str(raw["cost_fraction"])),
        off_primary_boundary=(
            raw["off_primary_boundary"]
            if isinstance(raw["off_primary_boundary"], bool)
            else (_ for _ in ()).throw(
                ValueError(
                    "cadence shadow off_primary_boundary must be boolean"
                )
            )
        ),
    )


def _outcome_payload(outcome: ShadowCadenceOutcome) -> dict[str, object]:
    return {
        "sample": _sample_payload(outcome.sample),
        "exit_px": str(outcome.exit_px),
        "gross_return": str(outcome.gross_return),
        "net_return": str(outcome.net_return),
    }


def _outcome_from_payload(raw: object) -> ShadowCadenceOutcome:
    if not isinstance(raw, dict):
        raise ValueError("cadence shadow outcome state must be an object")
    return ShadowCadenceOutcome(
        sample=_sample_from_payload(raw["sample"]),
        exit_px=Decimal(str(raw["exit_px"])),
        gross_return=Decimal(str(raw["gross_return"])),
        net_return=Decimal(str(raw["net_return"])),
    )


def _counter_from_payload(raw: object) -> Counter[str]:
    if not isinstance(raw, dict):
        raise ValueError("cadence shadow counter state must be an object")
    counter: Counter[str] = Counter()
    for key, value in raw.items():
        if not isinstance(key, str) or isinstance(value, bool):
            raise ValueError("cadence shadow counter state is invalid")
        count = int(value)
        if count < 0:
            raise ValueError("cadence shadow counter values must be non-negative")
        counter[key] = count
    return counter


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


def _five_minute_close_boundary_ms(candle: Candle) -> int:
    if candle.interval != "5m":
        raise ValueError("cadence shadow settlement requires a 5m candle")
    boundary_ms = candle.start_ms + FIVE_MINUTES_MS
    if candle.end_ms not in {boundary_ms - 1, boundary_ms}:
        raise ValueError("5m candle timestamps do not match interval boundaries")
    return boundary_ms


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
        self._directional_counts_by_lead_strategy: dict[
            int,
            dict[str, Counter[str]],
        ] = {
            interval_ms: defaultdict(Counter)
            for interval_ms in SUPPORTED_CADENCES_MS
        }
        self._directional_counts_by_score_band: dict[
            int,
            dict[str, Counter[str]],
        ] = {
            interval_ms: defaultdict(Counter)
            for interval_ms in SUPPORTED_CADENCES_MS
        }
        self._pending: dict[
            tuple[str, int],
            list[ShadowCadenceDecision],
        ] = defaultdict(list)
        self._outcomes: list[ShadowCadenceOutcome] = []
        self._censored_count = 0
        self._skipped_missing_entry_px = 0
        self._skipped_missing_lead_strategy = 0
        self._seen_decisions: set[tuple[int, str]] = set()
        self._state_restored = False
        self._state_restore_error: str | None = None

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
            decision_key = (
                cadence_ms,
                evaluation.decision.decision_id,
            )
            if decision_key in self._seen_decisions:
                continue
            self._seen_decisions.add(decision_key)
            direction = evaluation.decision.direction
            counts[direction.value] += 1
            if direction is Direction.NO_TRADE:
                continue
            lead_strategy = evaluation.decision.lead_strategy
            if lead_strategy is None or not lead_strategy.strip():
                self._skipped_missing_lead_strategy += 1
                continue
            score_band = _score_band(evaluation.decision.score)
            self._directional_counts_by_lead_strategy[cadence_ms][
                lead_strategy
            ][direction.value] += 1
            self._directional_counts_by_score_band[cadence_ms][
                score_band
            ][direction.value] += 1

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
                    lead_strategy=lead_strategy,
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
        close_boundary_ms = _five_minute_close_boundary_ms(candle)
        key = (candle.market.canonical, close_boundary_ms)
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
            if candle.interval == "5m":
                close_boundary_ms = _five_minute_close_boundary_ms(candle)
                if record.available_at_ms >= close_boundary_ms:
                    self._settle_candle(candle)

    def _outcome_summary(
        self,
        *,
        cadence_ms: int,
        horizon_ms: int,
        off_primary_only: bool,
        lead_strategy: str | None = None,
        score_band: str | None = None,
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
            and (
                lead_strategy is None
                or item.sample.lead_strategy == lead_strategy
            )
            and (
                score_band is None
                or _score_band(item.sample.score) == score_band
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

    def _grouped_outcomes(
        self,
        *,
        cadence_ms: int,
        horizon_ms: int,
        field: str,
    ) -> dict[str, dict[str, object]]:
        if field == "lead_strategy":
            labels = sorted(
                {
                    item.sample.lead_strategy
                    for item in self._outcomes
                    if item.sample.cadence_ms == cadence_ms
                    and item.sample.horizon_ms == horizon_ms
                }
            )
            return {
                label: self._outcome_summary(
                    cadence_ms=cadence_ms,
                    horizon_ms=horizon_ms,
                    off_primary_only=False,
                    lead_strategy=label,
                )
                for label in labels
            }
        if field == "score_band":
            score_labels = {
                _score_band(item.sample.score)
                for item in self._outcomes
                if item.sample.cadence_ms == cadence_ms
                and item.sample.horizon_ms == horizon_ms
            }
            order = ("<65", "65-<70", "70-<75", "75-<80", "80+")
            return {
                label: self._outcome_summary(
                    cadence_ms=cadence_ms,
                    horizon_ms=horizon_ms,
                    off_primary_only=False,
                    score_band=label,
                )
                for label in order
                if label in score_labels
            }
        raise ValueError("unsupported grouped shadow outcome field")

    @staticmethod
    def _directional_count_payload(
        grouped: dict[str, Counter[str]],
        *,
        score_order: bool = False,
    ) -> dict[str, dict[str, int]]:
        labels = list(grouped)
        if score_order:
            order = ("<65", "65-<70", "70-<75", "75-<80", "80+")
            labels = [label for label in order if label in grouped]
        else:
            labels.sort()
        return {
            label: {
                "long": grouped[label][Direction.LONG.value],
                "short": grouped[label][Direction.SHORT.value],
                "total": (
                    grouped[label][Direction.LONG.value]
                    + grouped[label][Direction.SHORT.value]
                ),
            }
            for label in labels
        }

    def state_payload(self) -> dict[str, object]:
        pending = sorted(
            (
                sample
                for samples in self._pending.values()
                for sample in samples
            ),
            key=lambda item: (
                item.target_end_ms,
                item.market.canonical,
                item.cadence_ms,
                item.decision_id,
                item.horizon_ms,
            ),
        )
        outcomes = sorted(
            self._outcomes,
            key=lambda item: (
                item.sample.target_end_ms,
                item.sample.market.canonical,
                item.sample.cadence_ms,
                item.sample.decision_id,
                item.sample.horizon_ms,
            ),
        )
        return {
            "schema_version": CADENCE_SHADOW_STATE_SCHEMA_VERSION,
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
            "decision_counts": {
                str(cadence_ms): dict(self._decision_counts[cadence_ms])
                for cadence_ms in SUPPORTED_CADENCES_MS
            },
            "directional_counts_by_lead_strategy": {
                str(cadence_ms): {
                    label: dict(counter)
                    for label, counter in sorted(
                        self._directional_counts_by_lead_strategy[
                            cadence_ms
                        ].items()
                    )
                }
                for cadence_ms in SUPPORTED_CADENCES_MS
            },
            "directional_counts_by_score_band": {
                str(cadence_ms): {
                    label: dict(counter)
                    for label, counter in sorted(
                        self._directional_counts_by_score_band[
                            cadence_ms
                        ].items()
                    )
                }
                for cadence_ms in SUPPORTED_CADENCES_MS
            },
            "seen_decisions": [
                [cadence_ms, decision_id]
                for cadence_ms, decision_id in sorted(self._seen_decisions)
            ],
            "pending": [_sample_payload(sample) for sample in pending],
            "outcomes": [_outcome_payload(outcome) for outcome in outcomes],
            "censored_count": self._censored_count,
            "skipped_missing_entry_px": self._skipped_missing_entry_px,
            "skipped_missing_lead_strategy": (
                self._skipped_missing_lead_strategy
            ),
        }

    def restore_state(self, raw: object) -> None:
        if not isinstance(raw, dict):
            raise ValueError("cadence shadow state must be an object")
        if raw.get("schema_version") != CADENCE_SHADOW_STATE_SCHEMA_VERSION:
            raise ValueError("cadence shadow state schema is unsupported")
        horizons_raw = raw.get("horizons_ms")
        if not isinstance(horizons_raw, list):
            raise ValueError("cadence shadow state horizons are invalid")
        horizons = tuple(int(value) for value in horizons_raw)
        if horizons != self._horizons_ms:
            raise ValueError("cadence shadow state horizons do not match runtime")

        costs_raw = raw.get("costs")
        if not isinstance(costs_raw, dict):
            raise ValueError("cadence shadow state costs are invalid")
        expected_costs = {
            "round_trip_fee_fraction": str(
                self._costs.round_trip_fee_fraction
            ),
            "round_trip_slippage_fraction": str(
                self._costs.round_trip_slippage_fraction
            ),
            "funding_reserve_fraction_per_hour": str(
                self._costs.funding_reserve_fraction_per_hour
            ),
        }
        if costs_raw != expected_costs:
            raise ValueError("cadence shadow state costs do not match runtime")

        decision_raw = raw.get("decision_counts")
        lead_raw = raw.get("directional_counts_by_lead_strategy")
        score_raw = raw.get("directional_counts_by_score_band")
        if not isinstance(decision_raw, dict):
            raise ValueError("cadence shadow decision counts are invalid")
        if not isinstance(lead_raw, dict) or not isinstance(score_raw, dict):
            raise ValueError("cadence shadow grouped counts are invalid")

        decision_counts: dict[int, Counter[str]] = {}
        lead_counts: dict[int, dict[str, Counter[str]]] = {}
        score_counts: dict[int, dict[str, Counter[str]]] = {}
        for cadence_ms in SUPPORTED_CADENCES_MS:
            key = str(cadence_ms)
            decision_counts[cadence_ms] = _counter_from_payload(
                decision_raw.get(key, {})
            )
            raw_lead_groups = lead_raw.get(key, {})
            raw_score_groups = score_raw.get(key, {})
            if not isinstance(raw_lead_groups, dict):
                raise ValueError("cadence shadow lead groups are invalid")
            if not isinstance(raw_score_groups, dict):
                raise ValueError("cadence shadow score groups are invalid")
            lead_counts[cadence_ms] = defaultdict(
                Counter,
                {
                    str(label): _counter_from_payload(counter)
                    for label, counter in raw_lead_groups.items()
                },
            )
            score_counts[cadence_ms] = defaultdict(
                Counter,
                {
                    str(label): _counter_from_payload(counter)
                    for label, counter in raw_score_groups.items()
                },
            )

        seen_raw = raw.get("seen_decisions")
        pending_raw = raw.get("pending")
        outcomes_raw = raw.get("outcomes")
        if not isinstance(seen_raw, list):
            raise ValueError("cadence shadow seen decisions are invalid")
        if not isinstance(pending_raw, list) or not isinstance(
            outcomes_raw,
            list,
        ):
            raise ValueError("cadence shadow evidence arrays are invalid")

        seen: set[tuple[int, str]] = set()
        for item in seen_raw:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError("cadence shadow seen decision is invalid")
            cadence_ms = int(item[0])
            decision_id = str(item[1])
            if cadence_ms not in SUPPORTED_CADENCES_MS or not decision_id:
                raise ValueError("cadence shadow seen decision is invalid")
            seen.add((cadence_ms, decision_id))

        pending_samples = tuple(_sample_from_payload(item) for item in pending_raw)
        outcomes = tuple(_outcome_from_payload(item) for item in outcomes_raw)
        seen.update(
            (sample.cadence_ms, sample.decision_id)
            for sample in pending_samples
        )
        seen.update(
            (outcome.sample.cadence_ms, outcome.sample.decision_id)
            for outcome in outcomes
        )
        all_keys = [_sample_key(sample) for sample in pending_samples]
        all_keys.extend(_sample_key(outcome.sample) for outcome in outcomes)
        if len(all_keys) != len(set(all_keys)):
            raise ValueError("cadence shadow state contains duplicate evidence")
        if any(sample.horizon_ms not in self._horizons_ms for sample in pending_samples):
            raise ValueError("cadence shadow pending horizon is unsupported")
        if any(
            outcome.sample.horizon_ms not in self._horizons_ms
            for outcome in outcomes
        ):
            raise ValueError("cadence shadow outcome horizon is unsupported")

        pending: dict[
            tuple[str, int],
            list[ShadowCadenceDecision],
        ] = defaultdict(list)
        for sample in pending_samples:
            pending[(sample.market.canonical, sample.target_end_ms)].append(
                sample
            )

        censored_count = int(raw.get("censored_count", 0))
        skipped_entry = int(raw.get("skipped_missing_entry_px", 0))
        skipped_strategy = int(
            raw.get("skipped_missing_lead_strategy", 0)
        )
        if min(censored_count, skipped_entry, skipped_strategy) < 0:
            raise ValueError("cadence shadow state counters must be non-negative")

        self._decision_counts = decision_counts
        self._directional_counts_by_lead_strategy = lead_counts
        self._directional_counts_by_score_band = score_counts
        self._seen_decisions = seen
        self._pending = pending
        self._outcomes = list(outcomes)
        self._censored_count = censored_count
        self._skipped_missing_entry_px = skipped_entry
        self._skipped_missing_lead_strategy = skipped_strategy
        self._state_restored = True
        self._state_restore_error = None

    def mark_state_restore_error(self, error: str) -> None:
        if not error.strip():
            raise ValueError("cadence shadow restore error must not be empty")
        self._state_restore_error = error

    def summary_payload(self) -> dict[str, object]:
        cadence_payload: dict[str, object] = {}
        for cadence_ms in SUPPORTED_CADENCES_MS:
            counts = self._decision_counts[cadence_ms]
            outcomes_by_horizon: dict[str, object] = {}
            off_cycle_by_horizon: dict[str, object] = {}
            outcomes_by_lead_strategy: dict[str, object] = {}
            outcomes_by_score_band: dict[str, object] = {}
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
                outcomes_by_lead_strategy[key] = self._grouped_outcomes(
                    cadence_ms=cadence_ms,
                    horizon_ms=horizon_ms,
                    field="lead_strategy",
                )
                outcomes_by_score_band[key] = self._grouped_outcomes(
                    cadence_ms=cadence_ms,
                    horizon_ms=horizon_ms,
                    field="score_band",
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
                "directional_counts_by_lead_strategy": (
                    self._directional_count_payload(
                        self._directional_counts_by_lead_strategy[
                            cadence_ms
                        ]
                    )
                ),
                "directional_counts_by_score_band": (
                    self._directional_count_payload(
                        self._directional_counts_by_score_band[cadence_ms],
                        score_order=True,
                    )
                ),
                "outcomes_by_lead_strategy_by_horizon_ms": (
                    outcomes_by_lead_strategy
                ),
                "outcomes_by_score_band_by_horizon_ms": (
                    outcomes_by_score_band
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
            "session_only": False,
            "durable_state": True,
            "state_restored": self._state_restored,
            "state_restore_error": self._state_restore_error,
            "state_schema_version": CADENCE_SHADOW_STATE_SCHEMA_VERSION,
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
            "skipped_missing_lead_strategy": (
                self._skipped_missing_lead_strategy
            ),
        }
