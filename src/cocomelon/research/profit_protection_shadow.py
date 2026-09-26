from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.stream import StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.historical_baselines import ExecutionCostAssumptions

ZERO: Final = Decimal("0")
DEFAULT_PROTECTION_COSTS: Final = ExecutionCostAssumptions(
    round_trip_fee_fraction=Decimal("0.0009"),
    round_trip_slippage_fraction=Decimal("0.0005"),
    funding_reserve_fraction_per_hour=ZERO,
)


@dataclass(frozen=True, slots=True)
class ProfitProtectionRule:
    rule_id: str
    activation_r: Decimal
    protected_r: Decimal

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must not be empty")
        for field_name, value in (
            ("activation_r", self.activation_r),
            ("protected_r", self.protected_r),
        ):
            if not value.is_finite() or value < ZERO:
                raise ValueError(f"{field_name} must be non-negative and finite")
        if self.protected_r >= self.activation_r:
            raise ValueError("protected_r must be below activation_r")


DEFAULT_PROTECTION_RULES: Final = (
    ProfitProtectionRule(
        rule_id="breakeven_after_0_5r",
        activation_r=Decimal("0.5"),
        protected_r=ZERO,
    ),
    ProfitProtectionRule(
        rule_id="half_r_after_1r",
        activation_r=Decimal("1"),
        protected_r=Decimal("0.5"),
    ),
)


@dataclass(slots=True)
class _LiveRuleState:
    armed_at_ms: int | None = None
    triggered_at_ms: int | None = None
    triggered_mark: Decimal | None = None
    triggered_gross_r: Decimal | None = None
    modeled_net_trigger_r: Decimal | None = None


@dataclass(slots=True)
class _LivePositionState:
    opening_plan_id: str
    market: str
    side: PositionSide
    entry_price: Decimal
    quantity: Decimal
    initial_risk_amount: Decimal
    max_favorable_r: Decimal = ZERO
    latest_gross_r: Decimal = ZERO
    latest_mark: Decimal | None = None
    rules: dict[str, _LiveRuleState] = field(default_factory=dict)


def _mark_from_record(record: ReplayRecord) -> tuple[str, Decimal, int] | None:
    if (
        record.record_kind is not SourceRecordKind.NORMALIZED_EVENT
        or record.event_kind != StreamKind.ACTIVE_ASSET_CTX.value
        or record.market is None
    ):
        return None
    payload = record.payload
    if not isinstance(payload, dict):
        return None
    raw_mark = payload.get("mark_px")
    if isinstance(raw_mark, bool) or not isinstance(
        raw_mark,
        (str, int, float, Decimal),
    ):
        return None
    try:
        mark = Decimal(str(raw_mark))
    except (InvalidOperation, ValueError):
        return None
    if not mark.is_finite() or mark <= ZERO:
        return None
    return record.market, mark, record.available_at_ms


def _gross_r(position: PaperPosition, mark: Decimal) -> Decimal | None:
    if position.planned_risk <= ZERO:
        return None
    if position.side is PositionSide.LONG:
        pnl = (mark - position.average_entry_price) * position.quantity
    else:
        pnl = (position.average_entry_price - mark) * position.quantity
    return pnl / position.planned_risk


def _modeled_cost_r(
    *,
    entry_price: Decimal,
    quantity: Decimal,
    initial_risk_amount: Decimal,
    costs: ExecutionCostAssumptions,
) -> Decimal:
    if initial_risk_amount <= ZERO:
        raise ValueError("initial_risk_amount must be positive")
    cost_fraction = (
        costs.round_trip_fee_fraction
        + costs.round_trip_slippage_fraction
    )
    return entry_price * quantity * cost_fraction / initial_risk_amount


class ProfitProtectionShadowComparator:
    """Research-only profit protection observer with zero execution authority."""

    def __init__(
        self,
        *,
        rules: tuple[ProfitProtectionRule, ...] = DEFAULT_PROTECTION_RULES,
        costs: ExecutionCostAssumptions = DEFAULT_PROTECTION_COSTS,
    ) -> None:
        if not rules:
            raise ValueError("profit protection rules must not be empty")
        if len({rule.rule_id for rule in rules}) != len(rules):
            raise ValueError("profit protection rule ids must be unique")
        self._rules = rules
        self._costs = costs
        self._states: dict[str, _LivePositionState] = {}
        self._skipped_zero_risk_positions = 0

    def _state_for(self, position: PaperPosition) -> _LivePositionState | None:
        if position.planned_risk <= ZERO:
            self._skipped_zero_risk_positions += 1
            return None
        state = self._states.get(position.opening_plan_id)
        if state is None:
            state = _LivePositionState(
                opening_plan_id=position.opening_plan_id,
                market=position.market.canonical,
                side=position.side,
                entry_price=position.average_entry_price,
                quantity=position.quantity,
                initial_risk_amount=position.planned_risk,
                rules={
                    rule.rule_id: _LiveRuleState()
                    for rule in self._rules
                },
            )
            self._states[position.opening_plan_id] = state
        return state

    def observe(
        self,
        record: ReplayRecord,
        positions: tuple[PaperPosition, ...],
    ) -> None:
        observed = _mark_from_record(record)
        if observed is None:
            return
        market, mark, timestamp_ms = observed
        position = next(
            (
                item
                for item in positions
                if item.market.canonical == market
            ),
            None,
        )
        if position is None:
            return
        state = self._state_for(position)
        if state is None:
            return
        current_r = _gross_r(position, mark)
        if current_r is None:
            return

        state.latest_mark = mark
        state.latest_gross_r = current_r
        state.max_favorable_r = max(state.max_favorable_r, current_r)
        modeled_cost_r = _modeled_cost_r(
            entry_price=state.entry_price,
            quantity=state.quantity,
            initial_risk_amount=state.initial_risk_amount,
            costs=self._costs,
        )

        for rule in self._rules:
            rule_state = state.rules[rule.rule_id]
            if (
                rule_state.armed_at_ms is None
                and state.max_favorable_r >= rule.activation_r
            ):
                rule_state.armed_at_ms = timestamp_ms
            if (
                rule_state.armed_at_ms is not None
                and rule_state.triggered_at_ms is None
                and current_r <= rule.protected_r
            ):
                rule_state.triggered_at_ms = timestamp_ms
                rule_state.triggered_mark = mark
                rule_state.triggered_gross_r = current_r
                rule_state.modeled_net_trigger_r = current_r - modeled_cost_r

    def reconcile_positions(
        self,
        positions: tuple[PaperPosition, ...],
    ) -> None:
        active = {position.opening_plan_id for position in positions}
        for plan_id in tuple(self._states):
            if plan_id not in active:
                del self._states[plan_id]

    def summary_payload(self) -> dict[str, object]:
        rule_payload: dict[str, object] = {}
        for rule in self._rules:
            armed = tuple(
                state
                for state in self._states.values()
                if state.rules[rule.rule_id].armed_at_ms is not None
            )
            triggered = tuple(
                state
                for state in self._states.values()
                if state.rules[rule.rule_id].triggered_at_ms is not None
            )
            rule_payload[rule.rule_id] = {
                "activation_r": str(rule.activation_r),
                "protected_r": str(rule.protected_r),
                "armed_open_positions": len(armed),
                "triggered_open_positions": len(triggered),
            }

        positions_payload = []
        for state in sorted(
            self._states.values(),
            key=lambda item: (item.market, item.opening_plan_id),
        ):
            positions_payload.append(
                {
                    "market": state.market,
                    "opening_plan_id": state.opening_plan_id,
                    "side": state.side.value,
                    "entry_price": str(state.entry_price),
                    "latest_mark": (
                        None
                        if state.latest_mark is None
                        else str(state.latest_mark)
                    ),
                    "latest_gross_r": str(state.latest_gross_r),
                    "max_favorable_r": str(state.max_favorable_r),
                    "rules": {
                        rule.rule_id: {
                            "armed_at_ms": (
                                state.rules[rule.rule_id].armed_at_ms
                            ),
                            "triggered_at_ms": (
                                state.rules[rule.rule_id].triggered_at_ms
                            ),
                            "triggered_mark": (
                                None
                                if state.rules[rule.rule_id].triggered_mark
                                is None
                                else str(
                                    state.rules[
                                        rule.rule_id
                                    ].triggered_mark
                                )
                            ),
                            "triggered_gross_r": (
                                None
                                if state.rules[
                                    rule.rule_id
                                ].triggered_gross_r
                                is None
                                else str(
                                    state.rules[
                                        rule.rule_id
                                    ].triggered_gross_r
                                )
                            ),
                            "modeled_net_trigger_r": (
                                None
                                if state.rules[
                                    rule.rule_id
                                ].modeled_net_trigger_r
                                is None
                                else str(
                                    state.rules[
                                        rule.rule_id
                                    ].modeled_net_trigger_r
                                )
                            ),
                        }
                        for rule in self._rules
                    },
                }
            )

        return {
            "shadow_only": True,
            "execution_authority": False,
            "rules": rule_payload,
            "tracked_open_positions": len(self._states),
            "skipped_zero_risk_positions": self._skipped_zero_risk_positions,
            "positions": positions_payload,
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
        }


def historical_profit_protection_summary(
    trades: tuple[TradeJournalEntry, ...],
    *,
    rules: tuple[ProfitProtectionRule, ...] = DEFAULT_PROTECTION_RULES,
    costs: ExecutionCostAssumptions = DEFAULT_PROTECTION_COSTS,
) -> dict[str, object]:
    """Retrospective path-constrained diagnostic; never promotion evidence."""

    rule_payload: dict[str, object] = {}
    for rule in rules:
        eligible = []
        triggered = []
        actual_sum = ZERO
        counterfactual_sum = ZERO
        delta_sum = ZERO
        improved_losses = 0

        for trade in trades:
            if (
                trade.mfe is None
                or trade.mfe.r_multiple is None
                or not trade.mfe.complete
            ):
                continue
            if trade.mfe.r_multiple < rule.activation_r:
                continue
            eligible.append(trade)

            gross_close_r = (
                trade.gross_realized_pnl / trade.initial_risk_amount
            )
            would_trigger = gross_close_r <= rule.protected_r
            counterfactual_r = trade.net_r
            if would_trigger:
                triggered.append(trade)
                cost_r = _modeled_cost_r(
                    entry_price=trade.entry_price,
                    quantity=trade.filled_quantity,
                    initial_risk_amount=trade.initial_risk_amount,
                    costs=costs,
                )
                counterfactual_r = rule.protected_r - cost_r
                if trade.net_r < ZERO and counterfactual_r > trade.net_r:
                    improved_losses += 1

            actual_sum += trade.net_r
            counterfactual_sum += counterfactual_r
            delta_sum += counterfactual_r - trade.net_r

        count = len(eligible)
        triggered_count = len(triggered)
        rule_payload[rule.rule_id] = {
            "activation_r": str(rule.activation_r),
            "protected_r": str(rule.protected_r),
            "eligible_trades": count,
            "would_trigger_trades": triggered_count,
            "improved_losing_trades": improved_losses,
            "actual_net_r_sum": str(actual_sum),
            "modeled_counterfactual_net_r_sum": str(counterfactual_sum),
            "modeled_delta_r_sum": str(delta_sum),
            "mean_actual_net_r": (
                None
                if count == 0
                else str(actual_sum / Decimal(count))
            ),
            "mean_modeled_counterfactual_net_r": (
                None
                if count == 0
                else str(counterfactual_sum / Decimal(count))
            ),
            "mean_modeled_delta_r": (
                None
                if count == 0
                else str(delta_sum / Decimal(count))
            ),
        }

    return {
        "retrospective_only": True,
        "promotion_evidence": False,
        "execution_authority": False,
        "complete_trade_count": len(trades),
        "rules": rule_payload,
        "costs": {
            "round_trip_fee_fraction": str(
                costs.round_trip_fee_fraction
            ),
            "round_trip_slippage_fraction": str(
                costs.round_trip_slippage_fraction
            ),
            "funding_reserve_fraction_per_hour": str(
                costs.funding_reserve_fraction_per_hour
            ),
        },
    }
