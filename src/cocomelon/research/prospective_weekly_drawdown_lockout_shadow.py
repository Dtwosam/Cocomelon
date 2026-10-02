from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final, cast

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.risk import RiskRequest
from cocomelon.evidence.openings import conservative_cost_estimate
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.execution.planner import PlanningRejection, plan_opening_order
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
    ContinuousPaperOpeningOpportunityPathStore,
)
from cocomelon.risk.engine import evaluate_risk

STATE_SCHEMA_VERSION: Final = 1
CANDIDATE_ID: Final = "prospective-weekly-drawdown-lockout-shadow-v1"
WEEKLY_REASON: Final = "weekly_drawdown_lockout"
EMBARGO_MS: Final = 6 * 60 * 60 * 1_000
FORWARD_HORIZONS_MS: Final = (
    5 * 60 * 1_000,
    15 * 60 * 1_000,
    60 * 60 * 1_000,
)
MAX_MARK_LAG_MS: Final = 120_000
ZERO: Final = Decimal("0")


class ProspectiveWeeklyDrawdownLockoutShadowError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveWeeklyDrawdownLockoutShadowState:
    frozen_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.frozen_at_ms < 0:
            raise ValueError("frozen_at_ms must be non-negative")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("unsupported weekly drawdown shadow schema")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("unsupported weekly drawdown shadow candidate")

    @property
    def started_at_ms(self) -> int:
        return self.frozen_at_ms + EMBARGO_MS

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "frozen_at_ms": self.frozen_at_ms,
            "started_at_ms": self.started_at_ms,
            "embargo_ms": EMBARGO_MS,
            "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
            "max_mark_lag_ms": MAX_MARK_LAG_MS,
            "rule": {
                "baseline_rejection_reason": WEEKLY_REASON,
                "counterfactual_change": (
                    "reset_only_rolling_7d_peak_to_current_equity"
                ),
                "entry_screen": "frozen_full_stack_admit",
                "execution_model": (
                    "captured_risk_planner_and_decision_time_ioc"
                ),
                "outcome_scope": (
                    "entry_fee_adjusted_forward_mark_to_market_only"
                ),
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveWeeklyDrawdownLockoutShadowState:
        if not isinstance(raw, dict):
            raise ProspectiveWeeklyDrawdownLockoutShadowError(
                "weekly drawdown shadow state must be an object"
            )
        expected = cls(frozen_at_ms=0).payload()
        for key in (
            "schema_version",
            "candidate_id",
            "embargo_ms",
            "forward_horizons_ms",
            "max_mark_lag_ms",
            "rule",
        ):
            if raw.get(key) != expected[key]:
                raise ProspectiveWeeklyDrawdownLockoutShadowError(
                    "weekly drawdown shadow state does not match frozen candidate"
                )
        frozen_at_ms = raw.get("frozen_at_ms")
        started_at_ms = raw.get("started_at_ms")
        if (
            isinstance(frozen_at_ms, bool)
            or not isinstance(frozen_at_ms, int)
            or isinstance(started_at_ms, bool)
            or not isinstance(started_at_ms, int)
        ):
            raise ProspectiveWeeklyDrawdownLockoutShadowError(
                "weekly drawdown shadow timestamps must be integers"
            )
        try:
            state = cls(frozen_at_ms=frozen_at_ms)
        except ValueError as exc:
            raise ProspectiveWeeklyDrawdownLockoutShadowError(
                str(exc)
            ) from exc
        if started_at_ms != state.started_at_ms:
            raise ProspectiveWeeklyDrawdownLockoutShadowError(
                "weekly drawdown clean start does not match embargo"
            )
        return state


def _path_by_id(
    paths: tuple[ContinuousPaperOpeningOpportunityPath, ...],
) -> dict[str, ContinuousPaperOpeningOpportunityPath]:
    output: dict[str, ContinuousPaperOpeningOpportunityPath] = {}
    for path in paths:
        if path.opportunity_id in output:
            raise ProspectiveWeeklyDrawdownLockoutShadowError(
                "duplicate weekly drawdown forward path"
            )
        output[path.opportunity_id] = path
    return output


def _full_stack_admitted_ids(
    summary: object,
) -> tuple[set[str], bool]:
    if not isinstance(summary, dict):
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "full-stack summary must be an object"
        )
    if summary.get("enabled") is not True or summary.get("error") is not None:
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "full-stack summary is not cleanly enabled"
        )
    if summary.get("candidate_stack") != "combined+two_strike+momentum":
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "full-stack candidate identity drift"
        )
    raw_rows = summary.get("risk_rejected_rows")
    if not isinstance(raw_rows, list):
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "full-stack risk-rejected rows are missing"
        )
    evaluated = summary.get("risk_rejected_stack_evaluated")
    if (
        isinstance(evaluated, bool)
        or not isinstance(evaluated, int)
        or evaluated != len(raw_rows)
    ):
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "full-stack risk-rejected row count does not reconcile"
        )
    integrity = summary.get("risk_rejected_integrity_clean")
    if not isinstance(integrity, bool):
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "full-stack risk-rejected integrity flag is invalid"
        )

    output: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise ProspectiveWeeklyDrawdownLockoutShadowError(
                "full-stack risk-rejected row must be an object"
            )
        reasons = raw.get("baseline_risk_reason_codes")
        if not isinstance(reasons, list):
            raise ProspectiveWeeklyDrawdownLockoutShadowError(
                "full-stack row risk reasons are invalid"
            )
        if WEEKLY_REASON not in reasons:
            continue
        if raw.get("stack_decision") != "ADMIT":
            continue
        opportunity_id = raw.get("opportunity_id")
        if not isinstance(opportunity_id, str) or not opportunity_id:
            raise ProspectiveWeeklyDrawdownLockoutShadowError(
                "full-stack admitted row opportunity id is invalid"
            )
        output.add(opportunity_id)
    return output, integrity


def _execution_config_compatible(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    config: PaperExecutionConfig,
) -> None:
    request = evidence.risk_request_object
    if request.cost_estimate != conservative_cost_estimate(config):
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "weekly drawdown opportunity cost estimate drift"
        )
    instrument = evidence.instrument_object
    if (
        instrument.minimum_order_notional
        != config.native_perp_min_notional
        or request.limits.max_gross_leverage
        != config.paper_max_gross_leverage
    ):
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "weekly drawdown execution envelope drift"
        )
    received_at_ms = int(
        evidence.book_event.receive_time.timestamp() * 1000
    )
    earliest_ms = (
        request.strategy_decision.timestamp_ms
        + config.latency_ms
    )
    if (
        request.timestamp_ms < earliest_ms
        or received_at_ms < earliest_ms
    ):
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "weekly drawdown opportunity timing violates execution latency"
        )


def _remove_only_weekly_lockout(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> tuple[RiskRequest, Decimal]:
    request = evidence.risk_request_object
    if evidence.baseline_risk_approved:
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "weekly drawdown shadow requires baseline risk rejection"
        )
    if evidence.baseline_risk_reason_codes != (WEEKLY_REASON,):
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "weekly drawdown shadow requires the sole baseline veto"
        )
    account = request.account_state
    peak = account.rolling_7d_peak_equity
    drawdown = (peak - account.equity) / peak
    if drawdown < request.limits.weekly_drawdown_limit:
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "captured weekly drawdown rejection does not reproduce"
        )
    adjusted = replace(
        account,
        rolling_7d_peak_equity=account.equity,
    )
    return replace(request, account_state=adjusted), drawdown


def _markout(
    *,
    path: ContinuousPaperOpeningOpportunityPath | None,
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    horizon_ms: int,
    entry_price: Decimal,
    quantity: Decimal,
    entry_fee: Decimal,
) -> dict[str, object]:
    target_at_ms = evidence.opportunity_timestamp_ms + horizon_ms
    if path is None:
        return {
            "status": "missing_path",
            "horizon_ms": horizon_ms,
            "target_at_ms": target_at_ms,
            "observed_at_ms": None,
            "observation_lag_ms": None,
            "mark_px": None,
            "directional_return_fraction": None,
            "gross_mark_to_market_pnl": None,
            "entry_fee_adjusted_mark_to_market_pnl": None,
        }
    if (
        path.market != evidence.market
        or path.direction != evidence.direction
        or path.opportunity_timestamp_ms
        != evidence.opportunity_timestamp_ms
    ):
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "weekly drawdown forward path lineage mismatch"
        )
    if horizon_ms > path.max_path_age_ms:
        return {
            "status": "unsupported_horizon",
            "horizon_ms": horizon_ms,
            "target_at_ms": target_at_ms,
            "observed_at_ms": None,
            "observation_lag_ms": None,
            "mark_px": None,
            "directional_return_fraction": None,
            "gross_mark_to_market_pnl": None,
            "entry_fee_adjusted_mark_to_market_pnl": None,
        }
    mark = next(
        (
            item
            for item in path.marks
            if item.observed_at_ms >= target_at_ms
        ),
        None,
    )
    if mark is None:
        return {
            "status": "pending",
            "horizon_ms": horizon_ms,
            "target_at_ms": target_at_ms,
            "observed_at_ms": None,
            "observation_lag_ms": None,
            "mark_px": None,
            "directional_return_fraction": None,
            "gross_mark_to_market_pnl": None,
            "entry_fee_adjusted_mark_to_market_pnl": None,
        }
    lag_ms = mark.observed_at_ms - target_at_ms
    if lag_ms > MAX_MARK_LAG_MS:
        return {
            "status": "stale",
            "horizon_ms": horizon_ms,
            "target_at_ms": target_at_ms,
            "observed_at_ms": mark.observed_at_ms,
            "observation_lag_ms": lag_ms,
            "mark_px": str(mark.mark_px),
            "directional_return_fraction": None,
            "gross_mark_to_market_pnl": None,
            "entry_fee_adjusted_mark_to_market_pnl": None,
        }
    signed_move = (
        mark.mark_px - entry_price
        if evidence.direction == "long"
        else entry_price - mark.mark_px
    )
    gross = signed_move * quantity
    adjusted = gross - entry_fee
    return {
        "status": "settled",
        "horizon_ms": horizon_ms,
        "target_at_ms": target_at_ms,
        "observed_at_ms": mark.observed_at_ms,
        "observation_lag_ms": lag_ms,
        "mark_px": str(mark.mark_px),
        "directional_return_fraction": str(
            signed_move / entry_price
        ),
        "gross_mark_to_market_pnl": str(gross),
        "entry_fee_adjusted_mark_to_market_pnl": str(adjusted),
    }


def _robustness(
    results: tuple[dict[str, object], ...],
    *,
    horizon_key: str,
) -> dict[str, object]:
    settled: list[tuple[str, Decimal]] = []
    for result in results:
        markouts = result.get("markouts")
        if not isinstance(markouts, dict):
            continue
        markout = markouts.get(horizon_key)
        if (
            not isinstance(markout, dict)
            or markout.get("status") != "settled"
        ):
            continue
        raw_pnl = markout.get(
            "entry_fee_adjusted_mark_to_market_pnl"
        )
        market = result.get("market")
        if not isinstance(raw_pnl, str) or not isinstance(market, str):
            continue
        settled.append((market, Decimal(raw_pnl)))
    total = sum((value for _market, value in settled), ZERO)
    leave_trade = tuple(total - value for _market, value in settled)
    by_market: dict[str, Decimal] = {}
    for market, value in settled:
        by_market[market] = by_market.get(market, ZERO) + value
    leave_market = tuple(total - value for value in by_market.values())
    return {
        "settled_options": len(settled),
        "market_count": len(by_market),
        "total_entry_fee_adjusted_pnl": str(total),
        "leave_one_option_out_min_pnl": str(
            min(leave_trade, default=ZERO)
        ),
        "positive_after_removing_any_one_option": (
            len(settled) >= 2
            and min(leave_trade, default=ZERO) > ZERO
        ),
        "leave_one_market_out_min_pnl": str(
            min(leave_market, default=ZERO)
        ),
        "positive_after_removing_any_one_market": (
            len(by_market) >= 2
            and min(leave_market, default=ZERO) > ZERO
        ),
    }


def prospective_weekly_drawdown_lockout_shadow_summary(
    opportunities: tuple[
        ContinuousPaperOpeningOpportunityEvidence,
        ...,
    ],
    paths: tuple[ContinuousPaperOpeningOpportunityPath, ...],
    full_stack_summary: object,
    state: ProspectiveWeeklyDrawdownLockoutShadowState,
    config: PaperExecutionConfig,
) -> dict[str, object]:
    admitted_ids, stack_integrity_clean = _full_stack_admitted_ids(
        full_stack_summary
    )
    path_map = _path_by_id(paths)
    by_id = {item.opportunity_id: item for item in opportunities}
    if len(by_id) != len(opportunities):
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "duplicate opening opportunity ids"
        )
    missing_opportunities = admitted_ids - set(by_id)
    if missing_opportunities:
        raise ProspectiveWeeklyDrawdownLockoutShadowError(
            "full-stack admitted opportunity evidence is missing"
        )

    all_weekly = tuple(
        item
        for item in opportunities
        if (
            not item.baseline_risk_approved
            and item.baseline_risk_reason_codes == (WEEKLY_REASON,)
        )
    )
    all_admitted = tuple(
        by_id[opportunity_id]
        for opportunity_id in sorted(
            admitted_ids,
            key=lambda value: (
                by_id[value].opportunity_timestamp_ms,
                by_id[value].market,
                value,
            ),
        )
    )
    touched = tuple(
        item
        for item in all_admitted
        if item.opportunity_timestamp_ms < state.started_at_ms
    )
    prospective = tuple(
        item
        for item in all_admitted
        if item.opportunity_timestamp_ms >= state.started_at_ms
    )

    results: list[dict[str, object]] = []
    risk_rejections: Counter[str] = Counter()
    planning_rejections: Counter[str] = Counter()
    execution_results: Counter[str] = Counter()

    for evidence in prospective:
        _execution_config_compatible(evidence, config)
        request, baseline_drawdown = _remove_only_weekly_lockout(
            evidence
        )
        result: dict[str, object] = {
            "opportunity_id": evidence.opportunity_id,
            "timestamp_ms": evidence.opportunity_timestamp_ms,
            "market": evidence.market,
            "direction": evidence.direction,
            "lead_strategy": evidence.lead_strategy,
            "rank_ordinal": evidence.rank_ordinal,
            "baseline_weekly_drawdown_fraction": str(
                baseline_drawdown
            ),
            "counterfactual_risk_approved": False,
            "counterfactual_risk_reason_codes": [],
            "planning_approved": False,
            "planning_rejection": None,
            "execution_result": None,
            "filled_quantity": None,
            "average_fill_price": None,
            "entry_fee": None,
            "markouts": {},
        }
        risk = evaluate_risk(request)
        result["counterfactual_risk_approved"] = risk.approved
        result["counterfactual_risk_reason_codes"] = list(
            risk.reason_codes
        )
        if not risk.approved:
            reason = (
                risk.reason_codes[0]
                if risk.reason_codes
                else "unknown"
            )
            risk_rejections[reason] += 1
            results.append(result)
            continue

        plan = plan_opening_order(
            risk,
            evidence.instrument_object,
            config,
            request.entry_reference_price,
            request.strategy_decision.timestamp_ms,
        )
        if isinstance(plan, PlanningRejection):
            result["planning_rejection"] = plan.reason
            planning_rejections[plan.reason] += 1
            results.append(result)
            continue
        result["planning_approved"] = True

        simulation = simulate_ioc(
            plan,
            evidence.book_event,
            evidence.instrument_object,
            config,
            attempt_timestamp_ms=request.timestamp_ms,
        )
        attempt = simulation.attempt
        result["execution_result"] = attempt.result.value
        execution_results[attempt.result.value] += 1
        if not simulation.fills:
            results.append(result)
            continue
        if attempt.average_fill_price is None:
            raise ProspectiveWeeklyDrawdownLockoutShadowError(
                "weekly drawdown fill is missing average price"
            )
        quantity = attempt.filled_quantity
        entry_price = attempt.average_fill_price
        entry_fee = attempt.fee
        result["filled_quantity"] = str(quantity)
        result["average_fill_price"] = str(entry_price)
        result["entry_fee"] = str(entry_fee)

        path = path_map.get(evidence.opportunity_id)
        markouts = {
            str(horizon_ms): _markout(
                path=path,
                evidence=evidence,
                horizon_ms=horizon_ms,
                entry_price=entry_price,
                quantity=quantity,
                entry_fee=entry_fee,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        }
        result["markouts"] = markouts
        results.append(result)

    result_tuple = tuple(
        sorted(
            results,
            key=lambda item: (
                cast(int, item["timestamp_ms"]),
                cast(str, item["market"]),
                cast(str, item["opportunity_id"]),
            ),
        )
    )

    by_horizon: dict[str, dict[str, object]] = {}
    for horizon_ms in FORWARD_HORIZONS_MS:
        key = str(horizon_ms)
        statuses: Counter[str] = Counter()
        settled = 0
        positive = 0
        negative = 0
        flat = 0
        pnl = ZERO
        returns = ZERO
        for result in result_tuple:
            raw_markouts = result.get("markouts")
            if not isinstance(raw_markouts, dict):
                continue
            markout = raw_markouts.get(key)
            if not isinstance(markout, dict):
                continue
            status = markout.get("status")
            if isinstance(status, str):
                statuses[status] += 1
            if status != "settled":
                continue
            raw_pnl = markout.get(
                "entry_fee_adjusted_mark_to_market_pnl"
            )
            raw_return = markout.get(
                "directional_return_fraction"
            )
            if not isinstance(raw_pnl, str) or not isinstance(
                raw_return,
                str,
            ):
                raise ProspectiveWeeklyDrawdownLockoutShadowError(
                    "settled weekly drawdown markout is incomplete"
                )
            value = Decimal(raw_pnl)
            pnl += value
            returns += Decimal(raw_return)
            settled += 1
            if value > ZERO:
                positive += 1
            elif value < ZERO:
                negative += 1
            else:
                flat += 1
        by_horizon[key] = {
            "horizon_ms": horizon_ms,
            "status_counts": dict(sorted(statuses.items())),
            "settled": settled,
            "positive": positive,
            "negative": negative,
            "flat": flat,
            "entry_fee_adjusted_mark_to_market_pnl": str(pnl),
            "mean_directional_return_fraction": (
                None
                if settled == 0
                else str(returns / Decimal(settled))
            ),
            "robustness": _robustness(
                result_tuple,
                horizon_key=key,
            ),
        }

    by_direction = {
        direction: sum(
            item["direction"] == direction
            for item in result_tuple
        )
        for direction in ("long", "short")
    }
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "candidate_id": state.candidate_id,
        "frozen_at_ms": state.frozen_at_ms,
        "started_at_ms": state.started_at_ms,
        "embargo_ms": EMBARGO_MS,
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "full_stack_risk_rejected_integrity_clean": (
            stack_integrity_clean
        ),
        "observed_weekly_drawdown_rejections": len(all_weekly),
        "full_stack_admitted_weekly_rejections": len(all_admitted),
        "pre_clean_touched_admitted_rejections": len(touched),
        "clean_admitted_weekly_rejections": len(prospective),
        "counterfactual_risk_rejections": dict(
            sorted(risk_rejections.items())
        ),
        "planning_rejections": dict(
            sorted(planning_rejections.items())
        ),
        "execution_results": dict(
            sorted(execution_results.items())
        ),
        "by_direction": by_direction,
        "by_horizon": by_horizon,
        "option_results": list(result_tuple),
        "forward_markout_only": True,
        "replacement_exits_modeled": False,
        "realized_pnl_modeled": False,
    }


def evaluate_prospective_weekly_drawdown_lockout_shadow(
    opportunity_store: ContinuousPaperOpeningOpportunityStore,
    path_store: ContinuousPaperOpeningOpportunityPathStore,
    full_stack_summary: object,
    state: ProspectiveWeeklyDrawdownLockoutShadowState,
    config: PaperExecutionConfig,
) -> dict[str, object]:
    return prospective_weekly_drawdown_lockout_shadow_summary(
        opportunity_store.iter_records(),
        path_store.iter_paths(),
        full_stack_summary,
        state,
        config,
    )
