from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.stream import StreamKind
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.execution.accounting import PaperPosition, PositionSide

ZERO: Final = Decimal("0")
BPS: Final = Decimal("10000")
ENTRY_MID_MARKOUT_STATE_SCHEMA_VERSION: Final = 1
ENTRY_MID_MARKOUT_HORIZONS_MS: Final = (
    60_000,
    300_000,
    900_000,
)
ENTRY_MID_MARKOUT_MAX_LAG_MS: Final = 60_000

_PENDING: Final = "pending"
_FRESH: Final = "fresh"
_STALE: Final = "stale"
_CENSORED: Final = "censored"
_MISSING_AT_CLOSE: Final = "missing_at_close"
_FINAL_STATUSES: Final = frozenset(
    {_FRESH, _STALE, _CENSORED, _MISSING_AT_CLOSE}
)


class EntryMidMarkoutShadowError(RuntimeError):
    pass


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EntryMidMarkoutShadowError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise EntryMidMarkoutShadowError(
            f"{field} must be finite"
        )
    return resolved


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EntryMidMarkoutShadowError(
            f"{field} must be an integer"
        )
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EntryMidMarkoutShadowError(
            f"{field} must be a non-empty string"
        )
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field)


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _signed_mid_economics(
    *,
    side: PositionSide,
    entry_price: Decimal,
    quantity: Decimal,
    planned_risk: Decimal,
    mid_px: Decimal,
) -> tuple[Decimal, Decimal]:
    signed_move = (
        mid_px - entry_price
        if side is PositionSide.LONG
        else entry_price - mid_px
    )
    signed_return_bps = (
        signed_move / entry_price * BPS
    )
    gross_r = signed_move * quantity / planned_risk
    return signed_return_bps, gross_r


@dataclass(slots=True)
class _HorizonState:
    horizon_ms: int
    target_timestamp_ms: int
    status: str = _PENDING
    observed_timestamp_ms: int | None = None
    observation_lag_ms: int | None = None
    mid_px: Decimal | None = None
    signed_return_bps: Decimal | None = None
    gross_r: Decimal | None = None

    def __post_init__(self) -> None:
        if self.horizon_ms not in ENTRY_MID_MARKOUT_HORIZONS_MS:
            raise ValueError("unsupported mid-markout horizon")
        if self.target_timestamp_ms < 0:
            raise ValueError(
                "target_timestamp_ms must be non-negative"
            )
        if self.status not in {_PENDING, *_FINAL_STATUSES}:
            raise ValueError("unsupported mid-markout status")
        observed = self.observed_timestamp_ms is not None
        lagged = self.observation_lag_ms is not None
        if observed != lagged:
            raise ValueError(
                "observation timestamp/lag must reconcile"
            )
        if observed:
            if (
                self.observed_timestamp_ms is None
                or self.observation_lag_ms is None
            ):
                raise ValueError("observation state is incomplete")
            if self.observed_timestamp_ms < self.target_timestamp_ms:
                raise ValueError(
                    "observed timestamp precedes horizon target"
                )
            if self.observation_lag_ms != (
                self.observed_timestamp_ms
                - self.target_timestamp_ms
            ):
                raise ValueError(
                    "observation lag must reconcile"
                )
        economics = (
            self.mid_px,
            self.signed_return_bps,
            self.gross_r,
        )
        if self.status == _FRESH:
            if not observed or any(
                value is None for value in economics
            ):
                raise ValueError(
                    "fresh mid markout requires economics"
                )
            if (
                self.observation_lag_ms is None
                or self.observation_lag_ms
                > ENTRY_MID_MARKOUT_MAX_LAG_MS
            ):
                raise ValueError(
                    "fresh mid markout exceeds max lag"
                )
        else:
            if any(value is not None for value in economics):
                raise ValueError(
                    "non-fresh mid markout cannot carry economics"
                )
        if self.status == _STALE:
            if (
                self.observation_lag_ms is None
                or self.observation_lag_ms
                <= ENTRY_MID_MARKOUT_MAX_LAG_MS
            ):
                raise ValueError(
                    "stale mid markout must exceed max lag"
                )
        if self.status in {_CENSORED, _MISSING_AT_CLOSE}:
            if observed:
                raise ValueError(
                    "terminal no-price state cannot be observed"
                )

    def payload(self) -> dict[str, object]:
        return {
            "horizon_ms": self.horizon_ms,
            "target_timestamp_ms": self.target_timestamp_ms,
            "status": self.status,
            "observed_timestamp_ms": self.observed_timestamp_ms,
            "observation_lag_ms": self.observation_lag_ms,
            "mid_px": (
                None if self.mid_px is None else str(self.mid_px)
            ),
            "signed_return_bps": (
                None
                if self.signed_return_bps is None
                else str(self.signed_return_bps)
            ),
            "gross_r": (
                None if self.gross_r is None else str(self.gross_r)
            ),
        }

    @classmethod
    def from_payload(cls, raw: object) -> _HorizonState:
        if not isinstance(raw, Mapping):
            raise EntryMidMarkoutShadowError(
                "mid-markout horizon state must be an object"
            )
        state = cls(
            horizon_ms=_integer(
                raw.get("horizon_ms"),
                "horizon_ms",
            ),
            target_timestamp_ms=_integer(
                raw.get("target_timestamp_ms"),
                "target_timestamp_ms",
            ),
            status=_string(raw.get("status"), "status"),
            observed_timestamp_ms=_optional_integer(
                raw.get("observed_timestamp_ms"),
                "observed_timestamp_ms",
            ),
            observation_lag_ms=_optional_integer(
                raw.get("observation_lag_ms"),
                "observation_lag_ms",
            ),
            mid_px=_optional_decimal(
                raw.get("mid_px"),
                "mid_px",
            ),
            signed_return_bps=_optional_decimal(
                raw.get("signed_return_bps"),
                "signed_return_bps",
            ),
            gross_r=_optional_decimal(
                raw.get("gross_r"),
                "gross_r",
            ),
        )
        return state


@dataclass(slots=True)
class _TrackedPosition:
    opening_plan_id: str
    market: str
    side: PositionSide
    initial_quantity: Decimal
    entry_price: Decimal
    planned_risk: Decimal
    opened_at_ms: int
    eligible: bool
    exclusion_reason: str | None
    horizons: dict[int, _HorizonState]


@dataclass(frozen=True, slots=True)
class EntryMidMarkoutOutcome:
    trade_id: str
    opening_plan_id: str
    market: str
    direction: str
    strategy_decision_id: str
    feature_snapshot_id: str
    replay_run_id: str | None
    horizon_ms: int
    status: str
    target_timestamp_ms: int
    observed_timestamp_ms: int | None
    observation_lag_ms: int | None
    mid_px: Decimal | None
    signed_return_bps: Decimal | None
    gross_r: Decimal | None

    def __post_init__(self) -> None:
        for value in (
            self.trade_id,
            self.opening_plan_id,
            self.market,
            self.direction,
            self.strategy_decision_id,
            self.feature_snapshot_id,
        ):
            if not value.strip():
                raise ValueError(
                    "mid-markout outcome identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.replay_run_id is not None and not (
            self.replay_run_id.strip()
        ):
            raise ValueError(
                "replay_run_id must be null or non-empty"
            )
        _HorizonState(
            horizon_ms=self.horizon_ms,
            target_timestamp_ms=self.target_timestamp_ms,
            status=self.status,
            observed_timestamp_ms=self.observed_timestamp_ms,
            observation_lag_ms=self.observation_lag_ms,
            mid_px=self.mid_px,
            signed_return_bps=self.signed_return_bps,
            gross_r=self.gross_r,
        )
        if self.status == _PENDING:
            raise ValueError(
                "closed outcome cannot remain pending"
            )

    def payload(self) -> dict[str, object]:
        return {
            "trade_id": self.trade_id,
            "opening_plan_id": self.opening_plan_id,
            "market": self.market,
            "direction": self.direction,
            "strategy_decision_id": self.strategy_decision_id,
            "feature_snapshot_id": self.feature_snapshot_id,
            "replay_run_id": self.replay_run_id,
            "horizon_ms": self.horizon_ms,
            "status": self.status,
            "target_timestamp_ms": self.target_timestamp_ms,
            "observed_timestamp_ms": self.observed_timestamp_ms,
            "observation_lag_ms": self.observation_lag_ms,
            "mid_px": (
                None if self.mid_px is None else str(self.mid_px)
            ),
            "signed_return_bps": (
                None
                if self.signed_return_bps is None
                else str(self.signed_return_bps)
            ),
            "gross_r": (
                None if self.gross_r is None else str(self.gross_r)
            ),
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> EntryMidMarkoutOutcome:
        if not isinstance(raw, Mapping):
            raise EntryMidMarkoutShadowError(
                "mid-markout outcome must be an object"
            )
        return cls(
            trade_id=_string(raw.get("trade_id"), "trade_id"),
            opening_plan_id=_string(
                raw.get("opening_plan_id"),
                "opening_plan_id",
            ),
            market=_string(raw.get("market"), "market"),
            direction=_string(
                raw.get("direction"),
                "direction",
            ),
            strategy_decision_id=_string(
                raw.get("strategy_decision_id"),
                "strategy_decision_id",
            ),
            feature_snapshot_id=_string(
                raw.get("feature_snapshot_id"),
                "feature_snapshot_id",
            ),
            replay_run_id=_optional_string(
                raw.get("replay_run_id"),
                "replay_run_id",
            ),
            horizon_ms=_integer(
                raw.get("horizon_ms"),
                "horizon_ms",
            ),
            status=_string(raw.get("status"), "status"),
            target_timestamp_ms=_integer(
                raw.get("target_timestamp_ms"),
                "target_timestamp_ms",
            ),
            observed_timestamp_ms=_optional_integer(
                raw.get("observed_timestamp_ms"),
                "observed_timestamp_ms",
            ),
            observation_lag_ms=_optional_integer(
                raw.get("observation_lag_ms"),
                "observation_lag_ms",
            ),
            mid_px=_optional_decimal(
                raw.get("mid_px"),
                "mid_px",
            ),
            signed_return_bps=_optional_decimal(
                raw.get("signed_return_bps"),
                "signed_return_bps",
            ),
            gross_r=_optional_decimal(
                raw.get("gross_r"),
                "gross_r",
            ),
        )


class EntryMidMarkoutShadow:
    def __init__(
        self,
        *,
        started_at_ms: int,
    ) -> None:
        if started_at_ms < 0:
            raise ValueError(
                "started_at_ms must be non-negative"
            )
        self._started_at_ms = started_at_ms
        self._positions: dict[str, _TrackedPosition] = {}
        self._outcomes: list[EntryMidMarkoutOutcome] = []
        self._excluded_closed_trades = 0
        self._unmatched_closed_trades = 0
        self._lineage_mismatch_closed_trades = 0
        self._state_restored = False
        self._state_restore_error: str | None = None

    @property
    def started_at_ms(self) -> int:
        return self._started_at_ms

    @property
    def outcomes(self) -> tuple[EntryMidMarkoutOutcome, ...]:
        return tuple(self._outcomes)

    def _track_position(
        self,
        position: PaperPosition,
    ) -> _TrackedPosition:
        existing = self._positions.get(
            position.opening_plan_id
        )
        if existing is not None:
            if (
                existing.market != position.market.canonical
                or existing.side is not position.side
                or existing.entry_price
                != position.average_entry_price
                or existing.opened_at_ms
                != position.opened_at_ms
            ):
                raise EntryMidMarkoutShadowError(
                    "mid-markout position identity drifted"
                )
            return existing

        eligible = (
            position.opened_at_ms >= self._started_at_ms
            and position.planned_risk > ZERO
        )
        exclusion_reason: str | None = None
        if position.opened_at_ms < self._started_at_ms:
            exclusion_reason = "PRE_OBSERVER_POSITION"
        elif position.planned_risk <= ZERO:
            exclusion_reason = "NON_POSITIVE_PLANNED_RISK"

        state = _TrackedPosition(
            opening_plan_id=position.opening_plan_id,
            market=position.market.canonical,
            side=position.side,
            initial_quantity=position.quantity,
            entry_price=position.average_entry_price,
            planned_risk=position.planned_risk,
            opened_at_ms=position.opened_at_ms,
            eligible=eligible,
            exclusion_reason=exclusion_reason,
            horizons={
                horizon_ms: _HorizonState(
                    horizon_ms=horizon_ms,
                    target_timestamp_ms=(
                        position.opened_at_ms + horizon_ms
                    ),
                )
                for horizon_ms in ENTRY_MID_MARKOUT_HORIZONS_MS
            },
        )
        self._positions[position.opening_plan_id] = state
        return state

    def observe(
        self,
        record: ReplayRecord,
        positions: Sequence[PaperPosition],
        *,
        now_ms: int,
    ) -> None:
        if now_ms < record.available_at_ms:
            raise EntryMidMarkoutShadowError(
                "mid-markout consumed future record"
            )
        for position in positions:
            self._track_position(position)

        if (
            record.record_kind
            is not SourceRecordKind.NORMALIZED_EVENT
            or record.event_kind != StreamKind.ALL_MIDS.value
            or record.market is None
        ):
            return
        raw = record.payload
        if not isinstance(raw, dict):
            raise EntryMidMarkoutShadowError(
                "allMids payload must be an object"
            )
        mid_px = _decimal(raw.get("mid_px"), "mid_px")
        if mid_px <= ZERO:
            raise EntryMidMarkoutShadowError(
                "mid_px must be positive"
            )

        matching = tuple(
            state
            for state in self._positions.values()
            if state.market == record.market
            and state.eligible
        )
        if len(matching) > 1:
            raise EntryMidMarkoutShadowError(
                "multiple tracked positions for one market"
            )
        if not matching:
            return
        state = matching[0]

        for horizon in state.horizons.values():
            if horizon.status != _PENDING:
                continue
            if record.available_at_ms < (
                horizon.target_timestamp_ms
            ):
                continue
            lag = (
                record.available_at_ms
                - horizon.target_timestamp_ms
            )
            if lag > ENTRY_MID_MARKOUT_MAX_LAG_MS:
                horizon.status = _STALE
                horizon.observed_timestamp_ms = (
                    record.available_at_ms
                )
                horizon.observation_lag_ms = lag
                continue
            signed_bps, gross_r = _signed_mid_economics(
                side=state.side,
                entry_price=state.entry_price,
                quantity=state.initial_quantity,
                planned_risk=state.planned_risk,
                mid_px=mid_px,
            )
            horizon.status = _FRESH
            horizon.observed_timestamp_ms = (
                record.available_at_ms
            )
            horizon.observation_lag_ms = lag
            horizon.mid_px = mid_px
            horizon.signed_return_bps = signed_bps
            horizon.gross_r = gross_r

    def record_closed_trade(
        self,
        trade: TradeJournalEntry,
    ) -> None:
        state = self._positions.pop(
            trade.opening_plan_id,
            None,
        )
        if state is None:
            self._unmatched_closed_trades += 1
            return
        if not state.eligible:
            self._excluded_closed_trades += 1
            return
        if (
            state.market != trade.market.canonical
            or state.side.value != trade.direction.value
            or state.entry_price != trade.entry_price
            or state.opened_at_ms != trade.opened_at_ms
            or state.planned_risk
            != trade.initial_risk_amount
            or state.initial_quantity
            != trade.filled_quantity
        ):
            self._lineage_mismatch_closed_trades += 1
            return

        for horizon_ms in ENTRY_MID_MARKOUT_HORIZONS_MS:
            horizon = state.horizons[horizon_ms]
            if horizon.status == _PENDING:
                if trade.closed_at_ms < (
                    horizon.target_timestamp_ms
                ):
                    horizon.status = _CENSORED
                else:
                    horizon.status = _MISSING_AT_CLOSE

            self._outcomes.append(
                EntryMidMarkoutOutcome(
                    trade_id=trade.trade_id,
                    opening_plan_id=trade.opening_plan_id,
                    market=trade.market.canonical,
                    direction=trade.direction.value,
                    strategy_decision_id=(
                        trade.strategy_decision_id
                    ),
                    feature_snapshot_id=(
                        trade.feature_snapshot_id
                    ),
                    replay_run_id=trade.replay_run_id,
                    horizon_ms=horizon.horizon_ms,
                    status=horizon.status,
                    target_timestamp_ms=(
                        horizon.target_timestamp_ms
                    ),
                    observed_timestamp_ms=(
                        horizon.observed_timestamp_ms
                    ),
                    observation_lag_ms=(
                        horizon.observation_lag_ms
                    ),
                    mid_px=horizon.mid_px,
                    signed_return_bps=(
                        horizon.signed_return_bps
                    ),
                    gross_r=horizon.gross_r,
                )
            )

    def _horizon_payload(
        self,
        horizon_ms: int,
        outcomes: tuple[EntryMidMarkoutOutcome, ...],
        fact_store: EvaluationFactStore,
    ) -> dict[str, object]:
        fresh = tuple(
            outcome
            for outcome in outcomes
            if outcome.status == _FRESH
        )

        def summarize(
            items: tuple[EntryMidMarkoutOutcome, ...],
        ) -> dict[str, object]:
            if not items:
                return {
                    "observations": 0,
                    "positive": 0,
                    "negative": 0,
                    "flat": 0,
                    "mean_signed_return_bps": None,
                    "mean_gross_r": None,
                    "mean_observation_lag_ms": None,
                    "max_observation_lag_ms": None,
                }
            count = len(items)
            return {
                "observations": count,
                "positive": sum(
                    1
                    for item in items
                    if item.gross_r is not None
                    and item.gross_r > ZERO
                ),
                "negative": sum(
                    1
                    for item in items
                    if item.gross_r is not None
                    and item.gross_r < ZERO
                ),
                "flat": sum(
                    1
                    for item in items
                    if item.gross_r == ZERO
                ),
                "mean_signed_return_bps": str(
                    sum(
                        (
                            item.signed_return_bps
                            for item in items
                            if item.signed_return_bps
                            is not None
                        ),
                        ZERO,
                    )
                    / Decimal(count)
                ),
                "mean_gross_r": str(
                    sum(
                        (
                            item.gross_r
                            for item in items
                            if item.gross_r is not None
                        ),
                        ZERO,
                    )
                    / Decimal(count)
                ),
                "mean_observation_lag_ms": (
                    sum(
                        item.observation_lag_ms or 0
                        for item in items
                    )
                    // count
                ),
                "max_observation_lag_ms": max(
                    item.observation_lag_ms or 0
                    for item in items
                ),
            }

        by_side: dict[str, list[EntryMidMarkoutOutcome]] = {}
        by_strategy: dict[str, list[EntryMidMarkoutOutcome]] = {}
        attribution_misses = 0
        for outcome in fresh:
            by_side.setdefault(
                outcome.direction,
                [],
            ).append(outcome)
            strategy = "unknown"
            if outcome.replay_run_id is not None:
                fact = fact_store.load_decision_by_strategy_id(
                    outcome.strategy_decision_id,
                    outcome.replay_run_id,
                )
                if fact is not None:
                    if (
                        fact.market.canonical
                        != outcome.market
                        or fact.direction.value
                        != outcome.direction
                        or fact.feature_snapshot_id
                        != outcome.feature_snapshot_id
                    ):
                        raise EntryMidMarkoutShadowError(
                            "mid-markout decision lineage mismatch"
                        )
                    strategy = (
                        fact.lead_strategy or "unknown"
                    )
                else:
                    attribution_misses += 1
            else:
                attribution_misses += 1
            by_strategy.setdefault(
                strategy,
                [],
            ).append(outcome)

        return {
            **summarize(fresh),
            "horizon_ms": horizon_ms,
            "fresh": len(fresh),
            "stale": sum(
                1
                for outcome in outcomes
                if outcome.status == _STALE
            ),
            "censored": sum(
                1
                for outcome in outcomes
                if outcome.status == _CENSORED
            ),
            "missing_at_close": sum(
                1
                for outcome in outcomes
                if outcome.status == _MISSING_AT_CLOSE
            ),
            "decision_attribution_misses": (
                attribution_misses
            ),
            "by_side": {
                label: summarize(tuple(items))
                for label, items in sorted(
                    by_side.items()
                )
            },
            "by_lead_strategy": {
                label: summarize(tuple(items))
                for label, items in sorted(
                    by_strategy.items()
                )
            },
        }

    def summary_payload(
        self,
        fact_store: EvaluationFactStore,
    ) -> dict[str, object]:
        eligible_open = sum(
            1
            for state in self._positions.values()
            if state.eligible
        )
        excluded_open = (
            len(self._positions) - eligible_open
        )
        return {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "durable_state": True,
            "state_restored": self._state_restored,
            "state_restore_error": (
                self._state_restore_error
            ),
            "state_schema_version": (
                ENTRY_MID_MARKOUT_STATE_SCHEMA_VERSION
            ),
            "started_at_ms": self._started_at_ms,
            "source": "allMids_mid_px",
            "horizons_ms": list(
                ENTRY_MID_MARKOUT_HORIZONS_MS
            ),
            "max_observation_lag_ms": (
                ENTRY_MID_MARKOUT_MAX_LAG_MS
            ),
            "eligible_open_positions": eligible_open,
            "excluded_open_positions": excluded_open,
            "excluded_closed_trades": (
                self._excluded_closed_trades
            ),
            "unmatched_closed_trades": (
                self._unmatched_closed_trades
            ),
            "lineage_mismatch_closed_trades": (
                self._lineage_mismatch_closed_trades
            ),
            "closed_trade_count": len(
                {
                    outcome.trade_id
                    for outcome in self._outcomes
                }
            ),
            "by_horizon_ms": {
                str(horizon_ms): self._horizon_payload(
                    horizon_ms,
                    tuple(
                        outcome
                        for outcome in self._outcomes
                        if outcome.horizon_ms
                        == horizon_ms
                    ),
                    fact_store,
                )
                for horizon_ms
                in ENTRY_MID_MARKOUT_HORIZONS_MS
            },
        }

    def state_payload(self) -> dict[str, object]:
        positions = []
        for state in sorted(
            self._positions.values(),
            key=lambda item: item.opening_plan_id,
        ):
            positions.append(
                {
                    "opening_plan_id": (
                        state.opening_plan_id
                    ),
                    "market": state.market,
                    "side": state.side.value,
                    "initial_quantity": str(
                        state.initial_quantity
                    ),
                    "entry_price": str(
                        state.entry_price
                    ),
                    "planned_risk": str(
                        state.planned_risk
                    ),
                    "opened_at_ms": state.opened_at_ms,
                    "eligible": state.eligible,
                    "exclusion_reason": (
                        state.exclusion_reason
                    ),
                    "horizons": [
                        state.horizons[
                            horizon_ms
                        ].payload()
                        for horizon_ms
                        in ENTRY_MID_MARKOUT_HORIZONS_MS
                    ],
                }
            )
        return {
            "schema_version": (
                ENTRY_MID_MARKOUT_STATE_SCHEMA_VERSION
            ),
            "started_at_ms": self._started_at_ms,
            "horizons_ms": list(
                ENTRY_MID_MARKOUT_HORIZONS_MS
            ),
            "max_observation_lag_ms": (
                ENTRY_MID_MARKOUT_MAX_LAG_MS
            ),
            "positions": positions,
            "outcomes": [
                outcome.payload()
                for outcome in sorted(
                    self._outcomes,
                    key=lambda item: (
                        item.trade_id,
                        item.horizon_ms,
                    ),
                )
            ],
            "excluded_closed_trades": (
                self._excluded_closed_trades
            ),
            "unmatched_closed_trades": (
                self._unmatched_closed_trades
            ),
            "lineage_mismatch_closed_trades": (
                self._lineage_mismatch_closed_trades
            ),
        }

    def restore_state(self, raw: object) -> None:
        if not isinstance(raw, Mapping):
            raise EntryMidMarkoutShadowError(
                "mid-markout state must be an object"
            )
        if raw.get("schema_version") != (
            ENTRY_MID_MARKOUT_STATE_SCHEMA_VERSION
        ):
            raise EntryMidMarkoutShadowError(
                "unsupported mid-markout state schema"
            )
        if raw.get("horizons_ms") != list(
            ENTRY_MID_MARKOUT_HORIZONS_MS
        ):
            raise EntryMidMarkoutShadowError(
                "mid-markout horizon mismatch"
            )
        if raw.get("max_observation_lag_ms") != (
            ENTRY_MID_MARKOUT_MAX_LAG_MS
        ):
            raise EntryMidMarkoutShadowError(
                "mid-markout lag policy mismatch"
            )
        started_at_ms = _integer(
            raw.get("started_at_ms"),
            "started_at_ms",
        )
        if started_at_ms < 0:
            raise EntryMidMarkoutShadowError(
                "started_at_ms must be non-negative"
            )
        raw_positions = raw.get("positions")
        raw_outcomes = raw.get("outcomes")
        if not isinstance(raw_positions, list):
            raise EntryMidMarkoutShadowError(
                "positions must be an array"
            )
        if not isinstance(raw_outcomes, list):
            raise EntryMidMarkoutShadowError(
                "outcomes must be an array"
            )

        positions: dict[str, _TrackedPosition] = {}
        for item in raw_positions:
            if not isinstance(item, Mapping):
                raise EntryMidMarkoutShadowError(
                    "tracked position must be an object"
                )
            raw_horizons = item.get("horizons")
            if not isinstance(raw_horizons, list):
                raise EntryMidMarkoutShadowError(
                    "tracked horizons must be an array"
                )
            horizons = tuple(
                _HorizonState.from_payload(value)
                for value in raw_horizons
            )
            if tuple(
                value.horizon_ms for value in horizons
            ) != ENTRY_MID_MARKOUT_HORIZONS_MS:
                raise EntryMidMarkoutShadowError(
                    "tracked horizon identity mismatch"
                )
            eligible = item.get("eligible")
            if not isinstance(eligible, bool):
                raise EntryMidMarkoutShadowError(
                    "eligible must be boolean"
                )
            exclusion_reason = item.get(
                "exclusion_reason"
            )
            if exclusion_reason is not None:
                exclusion_reason = _string(
                    exclusion_reason,
                    "exclusion_reason",
                )
            opening_plan_id = _string(
                item.get("opening_plan_id"),
                "opening_plan_id",
            )
            tracked = _TrackedPosition(
                opening_plan_id=opening_plan_id,
                market=_string(
                    item.get("market"),
                    "market",
                ),
                side=PositionSide(
                    _string(
                        item.get("side"),
                        "side",
                    )
                ),
                initial_quantity=_decimal(
                    item.get("initial_quantity"),
                    "initial_quantity",
                ),
                entry_price=_decimal(
                    item.get("entry_price"),
                    "entry_price",
                ),
                planned_risk=_decimal(
                    item.get("planned_risk"),
                    "planned_risk",
                ),
                opened_at_ms=_integer(
                    item.get("opened_at_ms"),
                    "opened_at_ms",
                ),
                eligible=eligible,
                exclusion_reason=exclusion_reason,
                horizons={
                    value.horizon_ms: value
                    for value in horizons
                },
            )
            if (
                tracked.initial_quantity <= ZERO
                or tracked.entry_price <= ZERO
                or tracked.planned_risk < ZERO
                or tracked.opened_at_ms < 0
            ):
                raise EntryMidMarkoutShadowError(
                    "tracked position economics are invalid"
                )
            if opening_plan_id in positions:
                raise EntryMidMarkoutShadowError(
                    "duplicate opening plan"
                )
            positions[opening_plan_id] = tracked

        outcomes = [
            EntryMidMarkoutOutcome.from_payload(item)
            for item in raw_outcomes
        ]
        keys = {
            (outcome.trade_id, outcome.horizon_ms)
            for outcome in outcomes
        }
        if len(keys) != len(outcomes):
            raise EntryMidMarkoutShadowError(
                "duplicate mid-markout outcome"
            )
        excluded = _integer(
            raw.get("excluded_closed_trades"),
            "excluded_closed_trades",
        )
        unmatched = _integer(
            raw.get("unmatched_closed_trades"),
            "unmatched_closed_trades",
        )
        lineage_mismatch = _integer(
            raw.get("lineage_mismatch_closed_trades", 0),
            "lineage_mismatch_closed_trades",
        )
        if (
            excluded < 0
            or unmatched < 0
            or lineage_mismatch < 0
        ):
            raise EntryMidMarkoutShadowError(
                "closed trade counters must be non-negative"
            )

        self._started_at_ms = started_at_ms
        self._positions = positions
        self._outcomes = outcomes
        self._excluded_closed_trades = excluded
        self._unmatched_closed_trades = unmatched
        self._lineage_mismatch_closed_trades = (
            lineage_mismatch
        )
        self._state_restored = True
        self._state_restore_error = None

    def mark_state_restore_error(
        self,
        error: str,
    ) -> None:
        if not error.strip():
            raise ValueError(
                "state restore error must not be empty"
            )
        self._state_restore_error = error
