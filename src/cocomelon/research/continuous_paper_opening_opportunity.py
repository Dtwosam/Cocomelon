from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from cocomelon.domain.execution import InstrumentExecutionSpec
from cocomelon.domain.features import OpportunityRank
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import (
    ExecutionCostEstimate,
    LiquidityRiskState,
    OpenPositionRisk,
    RiskAccountState,
    RiskHealthState,
    RiskLimits,
    RiskRequest,
)
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.openings import BaselineOpeningTrace

SCHEMA_VERSION: Final = 1
ZERO: Final = Decimal("0")


class ContinuousPaperOpeningOpportunityError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContinuousPaperOpeningOpportunityError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ContinuousPaperOpeningOpportunityError(
            f"{field} must be finite"
        )
    return resolved


def _market(value: str) -> MarketId:
    if ":" in value:
        dex = value.split(":", 1)[0]
        return MarketId.from_wire_name(dex, value)
    return MarketId.from_wire_name("", value)


def _decision_payload(decision: StrategyDecision) -> dict[str, object]:
    return {
        "market": decision.market.canonical,
        "direction": decision.direction.value,
        "score": str(decision.score),
        "timestamp_ms": decision.timestamp_ms,
        "feature_snapshot_id": decision.feature_snapshot_id,
        "lead_strategy": decision.lead_strategy,
        "invalidation_price": (
            None
            if decision.invalidation_price is None
            else str(decision.invalidation_price)
        ),
        "signal_ids": list(decision.signal_ids),
        "reason_codes": list(decision.reason_codes),
    }


def _decision_from_payload(raw: object) -> StrategyDecision:
    if not isinstance(raw, dict):
        raise ContinuousPaperOpeningOpportunityError(
            "strategy decision payload must be an object"
        )
    invalidation = raw.get("invalidation_price")
    signals = raw.get("signal_ids")
    reasons = raw.get("reason_codes")
    if not isinstance(signals, list) or not all(
        isinstance(value, str) for value in signals
    ):
        raise ContinuousPaperOpeningOpportunityError(
            "strategy signal ids must be a string array"
        )
    if not isinstance(reasons, list) or not all(
        isinstance(value, str) for value in reasons
    ):
        raise ContinuousPaperOpeningOpportunityError(
            "strategy reason codes must be a string array"
        )
    lead = raw.get("lead_strategy")
    if lead is not None and not isinstance(lead, str):
        raise ContinuousPaperOpeningOpportunityError(
            "lead strategy must be a string or null"
        )
    return StrategyDecision(
        market=_market(str(raw["market"])),
        direction=Direction(str(raw["direction"])),
        score=_decimal(raw["score"], "strategy score"),
        timestamp_ms=int(raw["timestamp_ms"]),
        feature_snapshot_id=str(raw["feature_snapshot_id"]),
        lead_strategy=lead,
        invalidation_price=(
            None
            if invalidation is None
            else _decimal(invalidation, "invalidation price")
        ),
        signal_ids=tuple(signals),
        reason_codes=tuple(reasons),
    )


def _risk_request_payload(request: RiskRequest) -> dict[str, object]:
    limits = request.limits
    account = request.account_state
    health = request.health_state
    cost = request.cost_estimate
    liquidity = request.liquidity_state
    return {
        "strategy_decision": _decision_payload(
            request.strategy_decision
        ),
        "entry_reference_price": str(request.entry_reference_price),
        "correlation_bucket": request.correlation_bucket,
        "account_state": {
            "equity": str(account.equity),
            "day_start_equity": str(account.day_start_equity),
            "daily_realized_pnl": str(account.daily_realized_pnl),
            "rolling_7d_peak_equity": str(
                account.rolling_7d_peak_equity
            ),
            "available_margin": str(account.available_margin),
            "gross_open_notional": str(account.gross_open_notional),
            "consecutive_losses": account.consecutive_losses,
            "last_closed_trade_ms": account.last_closed_trade_ms,
            "as_of_ms": account.as_of_ms,
        },
        "open_positions": [
            {
                "market": item.market.canonical,
                "direction": item.direction.value,
                "planned_risk": str(item.planned_risk),
                "notional": str(item.notional),
                "correlation_bucket": item.correlation_bucket,
                "entry_price": str(item.entry_price),
                "stop_price": str(item.stop_price),
            }
            for item in request.open_positions
        ],
        "health_state": {
            "market_data_fresh": health.market_data_fresh,
            "account_state_fresh": health.account_state_fresh,
            "execution_health_ok": health.execution_health_ok,
            "state_consistent": health.state_consistent,
            "as_of_ms": health.as_of_ms,
        },
        "cost_estimate": {
            "entry_slippage_fraction": str(
                cost.entry_slippage_fraction
            ),
            "stop_slippage_fraction": str(
                cost.stop_slippage_fraction
            ),
            "round_trip_fee_fraction": str(
                cost.round_trip_fee_fraction
            ),
        },
        "liquidity_state": {
            "entry_side_visible_notional_25bps": str(
                liquidity.entry_side_visible_notional_25bps
            ),
            "exit_side_visible_notional_25bps": str(
                liquidity.exit_side_visible_notional_25bps
            ),
            "venue_max_leverage": str(
                liquidity.venue_max_leverage
            ),
            "liquidation_price": (
                None
                if liquidity.liquidation_price is None
                else str(liquidity.liquidation_price)
            ),
            "venue_min_notional": (
                None
                if liquidity.venue_min_notional is None
                else str(liquidity.venue_min_notional)
            ),
            "as_of_ms": liquidity.as_of_ms,
        },
        "limits": {
            "risk_per_trade": str(limits.risk_per_trade),
            "max_open_risk": str(limits.max_open_risk),
            "daily_loss_limit": str(limits.daily_loss_limit),
            "weekly_drawdown_limit": str(
                limits.weekly_drawdown_limit
            ),
            "consecutive_loss_cooldown": (
                limits.consecutive_loss_cooldown
            ),
            "cooldown_ms": limits.cooldown_ms,
            "correlation_bucket_risk_limit": str(
                limits.correlation_bucket_risk_limit
            ),
            "max_gross_leverage": str(
                limits.max_gross_leverage
            ),
            "max_available_margin_fraction": str(
                limits.max_available_margin_fraction
            ),
            "max_visible_depth_fraction": str(
                limits.max_visible_depth_fraction
            ),
            "min_liquidation_stop_multiple": str(
                limits.min_liquidation_stop_multiple
            ),
            "max_state_age_ms": limits.max_state_age_ms,
        },
        "timestamp_ms": request.timestamp_ms,
    }


def risk_request_from_payload(raw: object) -> RiskRequest:
    if not isinstance(raw, dict):
        raise ContinuousPaperOpeningOpportunityError(
            "risk request payload must be an object"
        )
    account = raw.get("account_state")
    positions = raw.get("open_positions")
    health = raw.get("health_state")
    cost = raw.get("cost_estimate")
    liquidity = raw.get("liquidity_state")
    limits = raw.get("limits")
    if not all(
        isinstance(value, dict)
        for value in (account, health, cost, liquidity, limits)
    ):
        raise ContinuousPaperOpeningOpportunityError(
            "risk request nested state must be objects"
        )
    if not isinstance(positions, list):
        raise ContinuousPaperOpeningOpportunityError(
            "open positions must be an array"
        )
    assert isinstance(account, dict)
    assert isinstance(health, dict)
    assert isinstance(cost, dict)
    assert isinstance(liquidity, dict)
    assert isinstance(limits, dict)
    liquidation = liquidity.get("liquidation_price")
    venue_min = liquidity.get("venue_min_notional")
    return RiskRequest(
        strategy_decision=_decision_from_payload(
            raw["strategy_decision"]
        ),
        entry_reference_price=_decimal(
            raw["entry_reference_price"],
            "entry reference price",
        ),
        correlation_bucket=str(raw["correlation_bucket"]),
        account_state=RiskAccountState(
            equity=_decimal(account["equity"], "equity"),
            day_start_equity=_decimal(
                account["day_start_equity"],
                "day start equity",
            ),
            daily_realized_pnl=_decimal(
                account["daily_realized_pnl"],
                "daily realized pnl",
            ),
            rolling_7d_peak_equity=_decimal(
                account["rolling_7d_peak_equity"],
                "rolling peak equity",
            ),
            available_margin=_decimal(
                account["available_margin"],
                "available margin",
            ),
            gross_open_notional=_decimal(
                account["gross_open_notional"],
                "gross open notional",
            ),
            consecutive_losses=int(
                account["consecutive_losses"]
            ),
            last_closed_trade_ms=(
                None
                if account["last_closed_trade_ms"] is None
                else int(account["last_closed_trade_ms"])
            ),
            as_of_ms=int(account["as_of_ms"]),
        ),
        open_positions=tuple(
            OpenPositionRisk(
                market=_market(str(item["market"])),
                direction=Direction(str(item["direction"])),
                planned_risk=_decimal(
                    item["planned_risk"],
                    "position planned risk",
                ),
                notional=_decimal(
                    item["notional"],
                    "position notional",
                ),
                correlation_bucket=str(
                    item["correlation_bucket"]
                ),
                entry_price=_decimal(
                    item["entry_price"],
                    "position entry price",
                ),
                stop_price=_decimal(
                    item["stop_price"],
                    "position stop price",
                ),
            )
            for item in positions
            if isinstance(item, dict)
        ),
        health_state=RiskHealthState(
            market_data_fresh=bool(health["market_data_fresh"]),
            account_state_fresh=bool(
                health["account_state_fresh"]
            ),
            execution_health_ok=bool(
                health["execution_health_ok"]
            ),
            state_consistent=bool(health["state_consistent"]),
            as_of_ms=int(health["as_of_ms"]),
        ),
        cost_estimate=ExecutionCostEstimate(
            entry_slippage_fraction=_decimal(
                cost["entry_slippage_fraction"],
                "entry slippage",
            ),
            stop_slippage_fraction=_decimal(
                cost["stop_slippage_fraction"],
                "stop slippage",
            ),
            round_trip_fee_fraction=_decimal(
                cost["round_trip_fee_fraction"],
                "round trip fee",
            ),
        ),
        liquidity_state=LiquidityRiskState(
            entry_side_visible_notional_25bps=_decimal(
                liquidity["entry_side_visible_notional_25bps"],
                "entry visible notional",
            ),
            exit_side_visible_notional_25bps=_decimal(
                liquidity["exit_side_visible_notional_25bps"],
                "exit visible notional",
            ),
            venue_max_leverage=_decimal(
                liquidity["venue_max_leverage"],
                "venue max leverage",
            ),
            liquidation_price=(
                None
                if liquidation is None
                else _decimal(
                    liquidation,
                    "liquidation price",
                )
            ),
            venue_min_notional=(
                None
                if venue_min is None
                else _decimal(
                    venue_min,
                    "venue minimum notional",
                )
            ),
            as_of_ms=int(liquidity["as_of_ms"]),
        ),
        limits=RiskLimits(
            risk_per_trade=_decimal(
                limits["risk_per_trade"],
                "risk per trade",
            ),
            max_open_risk=_decimal(
                limits["max_open_risk"],
                "max open risk",
            ),
            daily_loss_limit=_decimal(
                limits["daily_loss_limit"],
                "daily loss limit",
            ),
            weekly_drawdown_limit=_decimal(
                limits["weekly_drawdown_limit"],
                "weekly drawdown limit",
            ),
            consecutive_loss_cooldown=int(
                limits["consecutive_loss_cooldown"]
            ),
            cooldown_ms=int(limits["cooldown_ms"]),
            correlation_bucket_risk_limit=_decimal(
                limits["correlation_bucket_risk_limit"],
                "bucket risk limit",
            ),
            max_gross_leverage=_decimal(
                limits["max_gross_leverage"],
                "max gross leverage",
            ),
            max_available_margin_fraction=_decimal(
                limits["max_available_margin_fraction"],
                "max margin fraction",
            ),
            max_visible_depth_fraction=_decimal(
                limits["max_visible_depth_fraction"],
                "max depth fraction",
            ),
            min_liquidation_stop_multiple=_decimal(
                limits["min_liquidation_stop_multiple"],
                "minimum liquidation stop multiple",
            ),
            max_state_age_ms=int(limits["max_state_age_ms"]),
        ),
        timestamp_ms=int(raw["timestamp_ms"]),
    )


def _book_levels(
    value: object,
) -> tuple[tuple[Decimal, Decimal, int], ...]:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes),
    ):
        raise ContinuousPaperOpeningOpportunityError(
            "book side must be a sequence"
        )
    result: list[tuple[Decimal, Decimal, int]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ContinuousPaperOpeningOpportunityError(
                "book level must be an object"
            )
        count = item.get("n", 0)
        if isinstance(count, bool) or not isinstance(count, int):
            raise ContinuousPaperOpeningOpportunityError(
                "book order count must be an integer"
            )
        result.append(
            (
                _decimal(item.get("px"), "book price"),
                _decimal(item.get("sz"), "book quantity"),
                count,
            )
        )
    if not result:
        raise ContinuousPaperOpeningOpportunityError(
            "book side must not be empty"
        )
    return tuple(result)


def _book_payload(event: StreamEvent) -> dict[str, object]:
    if event.kind is not StreamKind.L2_BOOK:
        raise ContinuousPaperOpeningOpportunityError(
            "opening opportunity requires an L2 book"
        )
    return {
        "event_key": event.event_key,
        "exchange_time_ms": event.exchange_time_ms,
        "received_at_ms": int(
            event.receive_time.timestamp() * 1000
        ),
        "source": event.source,
        "schema_version": event.schema_version,
        "bids": [
            {"px": str(px), "sz": str(sz), "n": count}
            for px, sz, count in _book_levels(
                event.payload.get("bids")
            )
        ],
        "asks": [
            {"px": str(px), "sz": str(sz), "n": count}
            for px, sz, count in _book_levels(
                event.payload.get("asks")
            )
        ],
    }


def book_event_from_payload(
    market: MarketId,
    raw: object,
) -> StreamEvent:
    if not isinstance(raw, dict):
        raise ContinuousPaperOpeningOpportunityError(
            "book payload must be an object"
        )

    def side(name: str) -> tuple[dict[str, object], ...]:
        rows = raw.get(name)
        if not isinstance(rows, list):
            raise ContinuousPaperOpeningOpportunityError(
                f"{name} must be an array"
            )
        result: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ContinuousPaperOpeningOpportunityError(
                    f"{name} row must be an object"
                )
            result.append(
                {
                    "px": _decimal(row["px"], "book price"),
                    "sz": _decimal(row["sz"], "book quantity"),
                    "n": int(row["n"]),
                }
            )
        return tuple(result)

    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=market,
        exchange_time_ms=(
            None
            if raw["exchange_time_ms"] is None
            else int(raw["exchange_time_ms"])
        ),
        receive_time=datetime.fromtimestamp(
            int(raw["received_at_ms"]) / 1000,
            tz=UTC,
        ),
        schema_version=int(raw["schema_version"]),
        source=str(raw["source"]),
        event_key=str(raw["event_key"]),
        payload={
            "bids": side("bids"),
            "asks": side("asks"),
        },
    )


def _instrument_payload(
    instrument: InstrumentExecutionSpec,
) -> dict[str, object]:
    return {
        "market": instrument.market.canonical,
        "sz_decimals": instrument.sz_decimals,
        "venue_max_leverage": str(
            instrument.venue_max_leverage
        ),
        "minimum_order_notional": str(
            instrument.minimum_order_notional
        ),
        "metadata_received_at_ms": (
            instrument.metadata_received_at_ms
        ),
        "metadata_source": instrument.metadata_source,
    }


def instrument_from_payload(raw: object) -> InstrumentExecutionSpec:
    if not isinstance(raw, dict):
        raise ContinuousPaperOpeningOpportunityError(
            "instrument payload must be an object"
        )
    return InstrumentExecutionSpec(
        market=_market(str(raw["market"])),
        sz_decimals=int(raw["sz_decimals"]),
        venue_max_leverage=_decimal(
            raw["venue_max_leverage"],
            "instrument venue leverage",
        ),
        minimum_order_notional=_decimal(
            raw["minimum_order_notional"],
            "instrument minimum notional",
        ),
        metadata_received_at_ms=int(
            raw["metadata_received_at_ms"]
        ),
        metadata_source=str(raw["metadata_source"]),
    )


@dataclass(frozen=True, slots=True)
class ContinuousPaperOpeningOpportunityEvidence:
    strategy_decision_id: str
    feature_snapshot_id: str
    market: str
    direction: str
    lead_strategy: str
    opportunity_timestamp_ms: int
    baseline_risk_approved: bool
    baseline_risk_reason_codes: tuple[str, ...]
    baseline_risk_decision_id: str
    equity_before: Decimal
    risk_request: dict[str, object]
    instrument: dict[str, object]
    book: dict[str, object]
    rank_observed_at_ms: int | None = None
    rank_ordinal: int | None = None
    rank_score: Decimal | None = None
    rank_pool_size: int | None = None
    rank_reason_codes: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, field in (
            (self.strategy_decision_id, "strategy_decision_id"),
            (self.feature_snapshot_id, "feature_snapshot_id"),
            (self.market, "market"),
            (self.direction, "direction"),
            (self.lead_strategy, "lead_strategy"),
            (
                self.baseline_risk_decision_id,
                "baseline_risk_decision_id",
            ),
        ):
            if not value.strip():
                raise ValueError(f"{field} must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.opportunity_timestamp_ms < 0:
            raise ValueError(
                "opportunity timestamp must be non-negative"
            )
        if not self.equity_before.is_finite() or self.equity_before <= ZERO:
            raise ValueError("equity_before must be positive")
        if any(
            not reason.strip()
            for reason in self.baseline_risk_reason_codes
        ):
            raise ValueError(
                "baseline risk reasons must not be empty"
            )
        rank_values = (
            self.rank_observed_at_ms,
            self.rank_ordinal,
            self.rank_score,
            self.rank_pool_size,
        )
        present = tuple(value is not None for value in rank_values)
        if any(present) and not all(present):
            raise ValueError(
                "rank opportunity evidence must be complete or absent"
            )
        if all(present):
            assert self.rank_observed_at_ms is not None
            assert self.rank_ordinal is not None
            assert self.rank_score is not None
            assert self.rank_pool_size is not None
            if self.rank_observed_at_ms > self.opportunity_timestamp_ms:
                raise ValueError(
                    "rank observation cannot follow opportunity"
                )
            if self.rank_ordinal <= 0:
                raise ValueError("rank ordinal must be positive")
            if self.rank_pool_size < self.rank_ordinal:
                raise ValueError(
                    "rank pool must include ordinal"
                )
            if (
                not self.rank_score.is_finite()
                or not ZERO <= self.rank_score <= Decimal("1")
            ):
                raise ValueError("rank score must be in [0, 1]")
        elif self.rank_reason_codes:
            raise ValueError(
                "rank reasons require rank opportunity evidence"
            )
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                "unsupported opening opportunity schema"
            )

    @property
    def opportunity_id(self) -> str:
        return _digest(
            {
                "strategy_decision_id": self.strategy_decision_id,
                "opportunity_timestamp_ms": (
                    self.opportunity_timestamp_ms
                ),
                "book_event_key": self.book.get("event_key"),
                "schema_version": self.schema_version,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy_decision_id": self.strategy_decision_id,
            "feature_snapshot_id": self.feature_snapshot_id,
            "market": self.market,
            "direction": self.direction,
            "lead_strategy": self.lead_strategy,
            "opportunity_timestamp_ms": (
                self.opportunity_timestamp_ms
            ),
            "baseline_risk_approved": (
                self.baseline_risk_approved
            ),
            "baseline_risk_reason_codes": list(
                self.baseline_risk_reason_codes
            ),
            "baseline_risk_decision_id": (
                self.baseline_risk_decision_id
            ),
            "equity_before": str(self.equity_before),
            "risk_request": self.risk_request,
            "instrument": self.instrument,
            "book": self.book,
            "rank_observed_at_ms": self.rank_observed_at_ms,
            "rank_ordinal": self.rank_ordinal,
            "rank_score": (
                None
                if self.rank_score is None
                else str(self.rank_score)
            ),
            "rank_pool_size": self.rank_pool_size,
            "rank_reason_codes": list(self.rank_reason_codes),
            "schema_version": self.schema_version,
            "opportunity_id": self.opportunity_id,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> ContinuousPaperOpeningOpportunityEvidence:
        if not isinstance(raw, dict):
            raise ContinuousPaperOpeningOpportunityError(
                "opening opportunity must be an object"
            )
        baseline_reasons = raw.get(
            "baseline_risk_reason_codes"
        )
        rank_reasons = raw.get("rank_reason_codes")
        if not isinstance(baseline_reasons, list) or not all(
            isinstance(value, str) for value in baseline_reasons
        ):
            raise ContinuousPaperOpeningOpportunityError(
                "baseline risk reasons must be a string array"
            )
        if not isinstance(rank_reasons, list) or not all(
            isinstance(value, str) for value in rank_reasons
        ):
            raise ContinuousPaperOpeningOpportunityError(
                "rank reasons must be a string array"
            )
        rank_score = raw.get("rank_score")
        result = cls(
            strategy_decision_id=str(
                raw["strategy_decision_id"]
            ),
            feature_snapshot_id=str(raw["feature_snapshot_id"]),
            market=str(raw["market"]),
            direction=str(raw["direction"]),
            lead_strategy=str(raw["lead_strategy"]),
            opportunity_timestamp_ms=int(
                raw["opportunity_timestamp_ms"]
            ),
            baseline_risk_approved=bool(
                raw["baseline_risk_approved"]
            ),
            baseline_risk_reason_codes=tuple(
                baseline_reasons
            ),
            baseline_risk_decision_id=str(
                raw["baseline_risk_decision_id"]
            ),
            equity_before=_decimal(
                raw["equity_before"],
                "equity before",
            ),
            risk_request=dict(raw["risk_request"]),
            instrument=dict(raw["instrument"]),
            book=dict(raw["book"]),
            rank_observed_at_ms=(
                None
                if raw["rank_observed_at_ms"] is None
                else int(raw["rank_observed_at_ms"])
            ),
            rank_ordinal=(
                None
                if raw["rank_ordinal"] is None
                else int(raw["rank_ordinal"])
            ),
            rank_score=(
                None
                if rank_score is None
                else _decimal(rank_score, "rank score")
            ),
            rank_pool_size=(
                None
                if raw["rank_pool_size"] is None
                else int(raw["rank_pool_size"])
            ),
            rank_reason_codes=tuple(rank_reasons),
            schema_version=int(raw["schema_version"]),
        )
        if raw.get("opportunity_id") != result.opportunity_id:
            raise ContinuousPaperOpeningOpportunityError(
                "opening opportunity id mismatch"
            )
        request = result.risk_request_object
        if (
            request.strategy_decision_id
            != result.strategy_decision_id
            or request.market.canonical != result.market
            or request.direction.value != result.direction
            or request.timestamp_ms
            != result.opportunity_timestamp_ms
        ):
            raise ContinuousPaperOpeningOpportunityError(
                "opening opportunity risk lineage mismatch"
            )
        if result.instrument_object.market != request.market:
            raise ContinuousPaperOpeningOpportunityError(
                "opening opportunity instrument lineage mismatch"
            )
        if result.book_event.market != request.market:
            raise ContinuousPaperOpeningOpportunityError(
                "opening opportunity book lineage mismatch"
            )
        return result

    @property
    def risk_request_object(self) -> RiskRequest:
        return risk_request_from_payload(self.risk_request)

    @property
    def instrument_object(self) -> InstrumentExecutionSpec:
        return instrument_from_payload(self.instrument)

    @property
    def book_event(self) -> StreamEvent:
        return book_event_from_payload(
            _market(self.market),
            self.book,
        )


def evidence_from_opening_trace(
    trace: BaselineOpeningTrace,
    *,
    rank_snapshot: tuple[int, OpportunityRank, int] | None,
) -> ContinuousPaperOpeningOpportunityEvidence:
    decision = trace.evaluation.decision
    if decision.direction is Direction.NO_TRADE:
        raise ContinuousPaperOpeningOpportunityError(
            "opening opportunity must be directional"
        )
    if decision.lead_strategy is None:
        raise ContinuousPaperOpeningOpportunityError(
            "opening opportunity lost lead strategy"
        )
    rank_observed_at_ms: int | None = None
    rank_ordinal: int | None = None
    rank_score: Decimal | None = None
    rank_pool_size: int | None = None
    rank_reasons: tuple[str, ...] = ()
    if rank_snapshot is not None:
        (
            rank_observed_at_ms,
            rank,
            rank_pool_size,
        ) = rank_snapshot
        rank_ordinal = rank.ordinal
        rank_score = rank.score
        rank_reasons = tuple(rank.reason_codes)

    return ContinuousPaperOpeningOpportunityEvidence(
        strategy_decision_id=decision.decision_id,
        feature_snapshot_id=decision.feature_snapshot_id,
        market=decision.market.canonical,
        direction=decision.direction.value,
        lead_strategy=decision.lead_strategy,
        opportunity_timestamp_ms=trace.risk_request.timestamp_ms,
        baseline_risk_approved=(
            trace.submission.risk_decision.approved
        ),
        baseline_risk_reason_codes=tuple(
            trace.submission.risk_decision.reason_codes
        ),
        baseline_risk_decision_id=(
            trace.submission.risk_decision.risk_decision_id
        ),
        equity_before=trace.equity_before,
        risk_request=_risk_request_payload(trace.risk_request),
        instrument=_instrument_payload(trace.instrument),
        book=_book_payload(trace.book_event),
        rank_observed_at_ms=rank_observed_at_ms,
        rank_ordinal=rank_ordinal,
        rank_score=rank_score,
        rank_pool_size=rank_pool_size,
        rank_reason_codes=rank_reasons,
    )


class ContinuousPaperOpeningOpportunityStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.records_root = self.root / "records"
        self.records_root.mkdir(parents=True, exist_ok=True)

    def _path(self, opportunity_id: str) -> Path:
        if not opportunity_id.strip():
            raise ValueError(
                "opportunity_id must not be empty"
            )
        return self.records_root / f"{opportunity_id}.json"

    def record(
        self,
        evidence: ContinuousPaperOpeningOpportunityEvidence,
    ) -> bool:
        path = self._path(evidence.opportunity_id)
        encoded = (
            _canonical_json(evidence.to_dict()) + "\n"
        ).encode("utf-8")
        if path.exists():
            if path.read_bytes() != encoded:
                raise ContinuousPaperOpeningOpportunityError(
                    "OPENING_OPPORTUNITY_CONFLICT"
                )
            return False
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != encoded:
                    raise ContinuousPaperOpeningOpportunityError(
                        "OPENING_OPPORTUNITY_CONFLICT"
                    ) from None
                return False
        finally:
            if temporary.exists():
                temporary.unlink()
        return True

    def load(
        self,
        opportunity_id: str,
    ) -> ContinuousPaperOpeningOpportunityEvidence | None:
        path = self._path(opportunity_id)
        if not path.exists():
            return None
        return self._load_path(path)

    def _load_path(
        self,
        path: Path,
    ) -> ContinuousPaperOpeningOpportunityEvidence:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContinuousPaperOpeningOpportunityError(
                "OPENING_OPPORTUNITY_UNREADABLE"
            ) from exc
        record = ContinuousPaperOpeningOpportunityEvidence.from_dict(
            raw
        )
        if path.name != f"{record.opportunity_id}.json":
            raise ContinuousPaperOpeningOpportunityError(
                "opening opportunity filename mismatch"
            )
        canonical = (
            _canonical_json(record.to_dict()) + "\n"
        ).encode("utf-8")
        if path.read_bytes() != canonical:
            raise ContinuousPaperOpeningOpportunityError(
                "opening opportunity record is non-canonical"
            )
        return record

    def iter_records(
        self,
    ) -> tuple[ContinuousPaperOpeningOpportunityEvidence, ...]:
        return tuple(
            sorted(
                (
                    self._load_path(path)
                    for path in self.records_root.glob("*.json")
                ),
                key=lambda item: (
                    item.opportunity_timestamp_ms,
                    item.market,
                    item.opportunity_id,
                ),
            )
        )

    @property
    def record_count(self) -> int:
        return len(self.iter_records())

    @property
    def approved_count(self) -> int:
        return sum(
            1
            for item in self.iter_records()
            if item.baseline_risk_approved
        )

    @property
    def rejected_count(self) -> int:
        return sum(
            1
            for item in self.iter_records()
            if not item.baseline_risk_approved
        )

    @property
    def complete_rank_count(self) -> int:
        return sum(
            1
            for item in self.iter_records()
            if item.rank_ordinal is not None
        )

    @property
    def state_digest(self) -> str:
        return _digest(
            tuple(
                item.to_dict()
                for item in self.iter_records()
            )
        )
