from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathMark,
    ContinuousPaperTradePathStore,
)
from cocomelon.research.historical_baselines import ExecutionCostAssumptions

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
DEFAULT_PROFIT_LOCK_COSTS: Final = ExecutionCostAssumptions(
    round_trip_fee_fraction=Decimal("0.0009"),
    round_trip_slippage_fraction=Decimal("0.0005"),
    funding_reserve_fraction_per_hour=Decimal("0.0001"),
)


class ProfitLockCounterfactualError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProfitLockRule:
    rule_id: str
    activate_at_r: Decimal
    lock_at_r: Decimal

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must not be empty")
        for field in ("activate_at_r", "lock_at_r"):
            value = getattr(self, field)
            if not value.is_finite() or value < ZERO:
                raise ValueError(f"{field} must be non-negative and finite")
        if self.lock_at_r > self.activate_at_r:
            raise ValueError("lock_at_r must not exceed activate_at_r")


DEFAULT_PROFIT_LOCK_RULES: Final = (
    ProfitLockRule(
        rule_id="breakeven_after_0_5r",
        activate_at_r=Decimal("0.5"),
        lock_at_r=ZERO,
    ),
    ProfitLockRule(
        rule_id="lock_0_5r_after_1r",
        activate_at_r=ONE,
        lock_at_r=Decimal("0.5"),
    ),
)


@dataclass(frozen=True, slots=True)
class ProfitLockTradeOutcome:
    trade_id: str
    market: str
    direction: str
    rule_id: str
    activated: bool
    activation_timestamp_ms: int | None
    triggered: bool
    trigger_timestamp_ms: int | None
    trigger_mark_px: Decimal | None
    actual_net_pnl: Decimal
    actual_net_r: Decimal
    candidate_net_pnl_estimate: Decimal
    candidate_net_r_estimate: Decimal
    delta_net_pnl_estimate: Decimal
    delta_net_r_estimate: Decimal
    used_actual_close: bool

    def __post_init__(self) -> None:
        if not self.trade_id.strip() or not self.market.strip() or not self.rule_id.strip():
            raise ValueError("outcome identity must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.activated != (self.activation_timestamp_ms is not None):
            raise ValueError("activation state must reconcile")
        if self.triggered != (self.trigger_timestamp_ms is not None):
            raise ValueError("trigger state must reconcile")
        if self.triggered != (self.trigger_mark_px is not None):
            raise ValueError("trigger mark state must reconcile")
        if self.triggered and not self.activated:
            raise ValueError("triggered outcome must be activated")
        if self.used_actual_close == self.triggered:
            raise ValueError("actual-close usage must invert trigger state")
        for field in (
            "actual_net_pnl",
            "actual_net_r",
            "candidate_net_pnl_estimate",
            "candidate_net_r_estimate",
            "delta_net_pnl_estimate",
            "delta_net_r_estimate",
        ):
            if not getattr(self, field).is_finite():
                raise ValueError(f"{field} must be finite")


@dataclass(frozen=True, slots=True)
class ProfitLockRuleSummary:
    rule_id: str
    activate_at_r: Decimal
    lock_at_r: Decimal
    evaluated_trades: int
    activated_trades: int
    triggered_trades: int
    actual_positive_trades: int
    candidate_positive_trades_estimate: int
    actual_net_pnl: Decimal
    candidate_net_pnl_estimate: Decimal
    delta_net_pnl_estimate: Decimal
    actual_mean_net_r: Decimal | None
    candidate_mean_net_r_estimate: Decimal | None
    delta_mean_net_r_estimate: Decimal | None

    def __post_init__(self) -> None:
        if self.evaluated_trades < 0:
            raise ValueError("evaluated_trades must be non-negative")
        if not 0 <= self.activated_trades <= self.evaluated_trades:
            raise ValueError("activated_trades must reconcile")
        if not 0 <= self.triggered_trades <= self.activated_trades:
            raise ValueError("triggered_trades must reconcile")
        for field in (
            "actual_positive_trades",
            "candidate_positive_trades_estimate",
        ):
            if not 0 <= getattr(self, field) <= self.evaluated_trades:
                raise ValueError(f"{field} must reconcile")
        for field in (
            "actual_net_pnl",
            "candidate_net_pnl_estimate",
            "delta_net_pnl_estimate",
        ):
            if not getattr(self, field).is_finite():
                raise ValueError(f"{field} must be finite")
        for field in (
            "actual_mean_net_r",
            "candidate_mean_net_r_estimate",
            "delta_mean_net_r_estimate",
        ):
            value = getattr(self, field)
            if value is not None and not value.is_finite():
                raise ValueError(f"{field} must be finite when present")


@dataclass(frozen=True, slots=True)
class ProfitLockStudy:
    path_record_count: int
    evaluated_trade_count: int
    skipped_incomplete_paths: int
    rules: tuple[ProfitLockRuleSummary, ...]
    outcomes: tuple[ProfitLockTradeOutcome, ...]
    evidence_class: str = "research_only_mark_path_counterfactual"
    execution_authority: bool = False
    fill_model: str = "first_crossing_mark_minus_frozen_cost_reserve"

    def __post_init__(self) -> None:
        if self.path_record_count < 0 or self.evaluated_trade_count < 0:
            raise ValueError("study counts must be non-negative")
        if self.skipped_incomplete_paths < 0:
            raise ValueError("skipped_incomplete_paths must be non-negative")
        if self.evaluated_trade_count + self.skipped_incomplete_paths != self.path_record_count:
            raise ValueError("path counts must reconcile")
        if self.execution_authority:
            raise ValueError("profit-lock study cannot have execution authority")


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProfitLockCounterfactualError(f"{field} must be an object")
    return value


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfitLockCounterfactualError(f"{field} must be a non-empty string")
    return value


def _require_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfitLockCounterfactualError(f"{field} must be an integer")
    return value


def _require_decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ProfitLockCounterfactualError(f"{field} must be a decimal string")
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise ProfitLockCounterfactualError(f"{field} must be a decimal string") from exc
    if not resolved.is_finite():
        raise ProfitLockCounterfactualError(f"{field} must be finite")
    return resolved


def _path_marks(raw: Mapping[str, object]) -> tuple[ContinuousPaperTradePathMark, ...]:
    values = raw.get("marks")
    if not isinstance(values, list):
        raise ProfitLockCounterfactualError("marks must be an array")
    try:
        return tuple(ContinuousPaperTradePathMark.from_dict(item) for item in values)
    except (TypeError, ValueError) as exc:
        raise ProfitLockCounterfactualError("trade path marks are invalid") from exc


def _validate_path_lineage(
    trade: TradeJournalEntry,
    raw: Mapping[str, object],
) -> tuple[ContinuousPaperTradePathMark, ...]:
    expected_strings = {
        "trade_id": trade.trade_id,
        "market": trade.market.canonical,
        "direction": trade.direction.value,
        "entry_price": str(trade.entry_price),
        "exit_price": str(trade.exit_price),
        "initial_stop": str(trade.initial_stop),
        "initial_risk_amount": str(trade.initial_risk_amount),
        "filled_quantity": str(trade.filled_quantity),
    }
    for field, expected in expected_strings.items():
        if _require_string(raw.get(field), field) != expected:
            raise ProfitLockCounterfactualError(
                f"trade path {field} does not match journal"
            )
    if _require_integer(raw.get("opened_at_ms"), "opened_at_ms") != trade.opened_at_ms:
        raise ProfitLockCounterfactualError(
            "trade path opened_at_ms does not match journal"
        )
    if _require_integer(raw.get("closed_at_ms"), "closed_at_ms") != trade.closed_at_ms:
        raise ProfitLockCounterfactualError(
            "trade path closed_at_ms does not match journal"
        )
    return _path_marks(raw)


def _gross_r(trade: TradeJournalEntry, mark_px: Decimal) -> Decimal:
    if trade.direction is Direction.LONG:
        gross = (mark_px - trade.entry_price) * trade.filled_quantity
    else:
        gross = (trade.entry_price - mark_px) * trade.filled_quantity
    return gross / trade.initial_risk_amount


def _lock_price(trade: TradeJournalEntry, lock_at_r: Decimal) -> Decimal:
    per_unit = lock_at_r * trade.initial_risk_amount / trade.filled_quantity
    if trade.direction is Direction.LONG:
        return trade.entry_price + per_unit
    return trade.entry_price - per_unit


def _crossed_lock(
    trade: TradeJournalEntry,
    mark_px: Decimal,
    lock_px: Decimal,
) -> bool:
    if trade.direction is Direction.LONG:
        return mark_px <= lock_px
    return mark_px >= lock_px


def _candidate_net_estimate(
    trade: TradeJournalEntry,
    *,
    trigger_mark_px: Decimal,
    trigger_timestamp_ms: int,
    costs: ExecutionCostAssumptions,
) -> tuple[Decimal, Decimal]:
    if trade.direction is Direction.LONG:
        gross = (trigger_mark_px - trade.entry_price) * trade.filled_quantity
    else:
        gross = (trade.entry_price - trigger_mark_px) * trade.filled_quantity
    horizon_ms = max(1, trigger_timestamp_ms - trade.opened_at_ms)
    modeled_cost = (
        trade.entry_price
        * trade.filled_quantity
        * costs.total_cost_fraction(horizon_ms)
    )
    net = gross - modeled_cost
    return net, net / trade.initial_risk_amount


def evaluate_profit_lock_rule(
    trade: TradeJournalEntry,
    marks: Sequence[ContinuousPaperTradePathMark],
    rule: ProfitLockRule,
    *,
    costs: ExecutionCostAssumptions = DEFAULT_PROFIT_LOCK_COSTS,
) -> ProfitLockTradeOutcome:
    activated = False
    activation_timestamp_ms: int | None = None
    trigger_mark: ContinuousPaperTradePathMark | None = None
    lock_px = _lock_price(trade, rule.lock_at_r)

    for mark in marks:
        if not activated:
            if _gross_r(trade, mark.mark_px) >= rule.activate_at_r:
                activated = True
                activation_timestamp_ms = mark.available_at_ms
            continue
        if _crossed_lock(trade, mark.mark_px, lock_px):
            trigger_mark = mark
            break

    if trigger_mark is None:
        candidate_net_pnl = trade.net_pnl
        candidate_net_r = trade.net_r
    else:
        candidate_net_pnl, candidate_net_r = _candidate_net_estimate(
            trade,
            trigger_mark_px=trigger_mark.mark_px,
            trigger_timestamp_ms=trigger_mark.available_at_ms,
            costs=costs,
        )

    return ProfitLockTradeOutcome(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        rule_id=rule.rule_id,
        activated=activated,
        activation_timestamp_ms=activation_timestamp_ms,
        triggered=trigger_mark is not None,
        trigger_timestamp_ms=(
            None if trigger_mark is None else trigger_mark.available_at_ms
        ),
        trigger_mark_px=None if trigger_mark is None else trigger_mark.mark_px,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        candidate_net_pnl_estimate=candidate_net_pnl,
        candidate_net_r_estimate=candidate_net_r,
        delta_net_pnl_estimate=candidate_net_pnl - trade.net_pnl,
        delta_net_r_estimate=candidate_net_r - trade.net_r,
        used_actual_close=trigger_mark is None,
    )


def _summary(
    rule: ProfitLockRule,
    outcomes: Sequence[ProfitLockTradeOutcome],
) -> ProfitLockRuleSummary:
    items = tuple(outcomes)
    count = len(items)
    actual_net_pnl = sum((item.actual_net_pnl for item in items), ZERO)
    candidate_net_pnl = sum(
        (item.candidate_net_pnl_estimate for item in items),
        ZERO,
    )
    actual_mean_r = (
        None
        if not items
        else sum((item.actual_net_r for item in items), ZERO) / Decimal(count)
    )
    candidate_mean_r = (
        None
        if not items
        else sum(
            (item.candidate_net_r_estimate for item in items),
            ZERO,
        )
        / Decimal(count)
    )
    return ProfitLockRuleSummary(
        rule_id=rule.rule_id,
        activate_at_r=rule.activate_at_r,
        lock_at_r=rule.lock_at_r,
        evaluated_trades=count,
        activated_trades=sum(1 for item in items if item.activated),
        triggered_trades=sum(1 for item in items if item.triggered),
        actual_positive_trades=sum(1 for item in items if item.actual_net_pnl > ZERO),
        candidate_positive_trades_estimate=sum(
            1 for item in items if item.candidate_net_pnl_estimate > ZERO
        ),
        actual_net_pnl=actual_net_pnl,
        candidate_net_pnl_estimate=candidate_net_pnl,
        delta_net_pnl_estimate=candidate_net_pnl - actual_net_pnl,
        actual_mean_net_r=actual_mean_r,
        candidate_mean_net_r_estimate=candidate_mean_r,
        delta_mean_net_r_estimate=(
            None
            if actual_mean_r is None or candidate_mean_r is None
            else candidate_mean_r - actual_mean_r
        ),
    )


def evaluate_profit_lock_study(
    trades: Sequence[TradeJournalEntry],
    path_payloads: Sequence[dict[str, object]],
    *,
    rules: Sequence[ProfitLockRule] = DEFAULT_PROFIT_LOCK_RULES,
    costs: ExecutionCostAssumptions = DEFAULT_PROFIT_LOCK_COSTS,
) -> ProfitLockStudy:
    resolved_rules = tuple(rules)
    if not resolved_rules:
        raise ValueError("rules must not be empty")
    if len({rule.rule_id for rule in resolved_rules}) != len(resolved_rules):
        raise ValueError("rule ids must be unique")

    trades_by_id = {trade.trade_id: trade for trade in trades}
    if len(trades_by_id) != len(tuple(trades)):
        raise ProfitLockCounterfactualError("journal contains duplicate trade ids")

    outcomes: list[ProfitLockTradeOutcome] = []
    evaluated_trade_count = 0
    skipped_incomplete_paths = 0

    for payload in path_payloads:
        raw = _require_mapping(payload, "trade path")
        trade_id = _require_string(raw.get("trade_id"), "trade_id")
        trade = trades_by_id.get(trade_id)
        if trade is None:
            raise ProfitLockCounterfactualError(
                "trade path has no matching journal trade"
            )
        path_complete = raw.get("path_complete")
        if not isinstance(path_complete, bool):
            raise ProfitLockCounterfactualError(
                "path_complete must be a boolean"
            )
        marks = _validate_path_lineage(trade, raw)
        if not path_complete:
            skipped_incomplete_paths += 1
            continue
        if not marks:
            raise ProfitLockCounterfactualError(
                "complete trade path must contain marks"
            )
        evaluated_trade_count += 1
        for rule in resolved_rules:
            outcomes.append(
                evaluate_profit_lock_rule(
                    trade,
                    marks,
                    rule,
                    costs=costs,
                )
            )

    summaries = tuple(
        _summary(
            rule,
            tuple(item for item in outcomes if item.rule_id == rule.rule_id),
        )
        for rule in resolved_rules
    )
    return ProfitLockStudy(
        path_record_count=len(tuple(path_payloads)),
        evaluated_trade_count=evaluated_trade_count,
        skipped_incomplete_paths=skipped_incomplete_paths,
        rules=summaries,
        outcomes=tuple(
            sorted(
                outcomes,
                key=lambda item: (item.rule_id, item.trade_id),
            )
        ),
    )


def evaluate_profit_lock_state(
    journal: JournalStore,
    path_store: ContinuousPaperTradePathStore,
    *,
    rules: Sequence[ProfitLockRule] = DEFAULT_PROFIT_LOCK_RULES,
    costs: ExecutionCostAssumptions = DEFAULT_PROFIT_LOCK_COSTS,
) -> ProfitLockStudy:
    return evaluate_profit_lock_study(
        tuple(journal.iter_trades()),
        path_store.iter_payloads(),
        rules=rules,
        costs=costs,
    )
