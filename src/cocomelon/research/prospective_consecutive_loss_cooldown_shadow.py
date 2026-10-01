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
from cocomelon.research.prospective_combined_entry_filter import (
    MAX_ACCEPTED_RANK_AGE_MS,
    TOP10_MAX_ORDINAL,
)
from cocomelon.risk.engine import evaluate_risk

STATE_SCHEMA_VERSION: Final = 1
CANDIDATE_ID: Final = (
    "prospective-consecutive-loss-cooldown-relaxation-v1"
)
COOLDOWN_REASON: Final = "consecutive_loss_cooldown"
EMBARGO_MS: Final = 6 * 60 * 60 * 1_000
RELAXED_COOLDOWN_WINDOWS_MS: Final = (
    15 * 60 * 1_000,
    30 * 60 * 1_000,
    45 * 60 * 1_000,
)
FORWARD_HORIZONS_MS: Final = (
    5 * 60 * 1_000,
    15 * 60 * 1_000,
    60 * 60 * 1_000,
)
MAX_MARK_LAG_MS: Final = 120_000
ZERO: Final = Decimal("0")


class ProspectiveConsecutiveLossCooldownShadowError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveConsecutiveLossCooldownShadowState:
    frozen_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.frozen_at_ms < 0:
            raise ValueError("frozen_at_ms must be non-negative")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("unsupported cooldown shadow schema")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("unsupported cooldown shadow candidate")

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
            "relaxed_cooldown_windows_ms": list(
                RELAXED_COOLDOWN_WINDOWS_MS
            ),
            "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
            "max_mark_lag_ms": MAX_MARK_LAG_MS,
            "rule": {
                "baseline_rejection_reason": COOLDOWN_REASON,
                "counterfactual_change": (
                    "expire_only_consecutive_loss_cooldown"
                ),
                "entry_screen": (
                    "top10_rank_and_no_long_trend"
                ),
                "execution_model": (
                    "captured_risk_planner_and_decision_time_ioc"
                ),
                "outcome_scope": (
                    "observed_forward_mark_to_market_only"
                ),
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveConsecutiveLossCooldownShadowState:
        if not isinstance(raw, dict):
            raise ProspectiveConsecutiveLossCooldownShadowError(
                "cooldown shadow state must be an object"
            )
        expected = cls(frozen_at_ms=0).payload()
        for key in (
            "schema_version",
            "candidate_id",
            "embargo_ms",
            "relaxed_cooldown_windows_ms",
            "forward_horizons_ms",
            "max_mark_lag_ms",
            "rule",
        ):
            if raw.get(key) != expected[key]:
                raise ProspectiveConsecutiveLossCooldownShadowError(
                    "cooldown shadow state does not match frozen candidate"
                )
        frozen_at_ms = raw.get("frozen_at_ms")
        started_at_ms = raw.get("started_at_ms")
        if (
            isinstance(frozen_at_ms, bool)
            or not isinstance(frozen_at_ms, int)
        ):
            raise ProspectiveConsecutiveLossCooldownShadowError(
                "frozen_at_ms must be an integer"
            )
        if (
            isinstance(started_at_ms, bool)
            or not isinstance(started_at_ms, int)
        ):
            raise ProspectiveConsecutiveLossCooldownShadowError(
                "started_at_ms must be an integer"
            )
        try:
            state = cls(frozen_at_ms=frozen_at_ms)
        except ValueError as exc:
            raise ProspectiveConsecutiveLossCooldownShadowError(
                str(exc)
            ) from exc
        if started_at_ms != state.started_at_ms:
            raise ProspectiveConsecutiveLossCooldownShadowError(
                "cooldown shadow clean start does not match embargo"
            )
        return state


@dataclass(slots=True)
class _Aggregate:
    options: int = 0
    fillable: int = 0
    settled_1h: int = 0
    positive_1h: int = 0
    negative_1h: int = 0
    flat_1h: int = 0
    pnl_1h: Decimal = ZERO

    def payload(self) -> dict[str, object]:
        return {
            "options": self.options,
            "fillable": self.fillable,
            "settled_1h": self.settled_1h,
            "positive_1h": self.positive_1h,
            "negative_1h": self.negative_1h,
            "flat_1h": self.flat_1h,
            "entry_fee_adjusted_1h_pnl": str(self.pnl_1h),
        }


def _rank_age_ms(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> int | None:
    observed = evidence.rank_observed_at_ms
    if observed is None:
        return None
    age = evidence.opportunity_timestamp_ms - observed
    if age < 0:
        raise ProspectiveConsecutiveLossCooldownShadowError(
            "cooldown opportunity rank is from the future"
        )
    return age


def _candidate_block_reason(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> str | None:
    ordinal = evidence.rank_ordinal
    if ordinal is None:
        raise ProspectiveConsecutiveLossCooldownShadowError(
            "cooldown candidate screen requires scanner rank"
        )
    long_trend = (
        evidence.direction == "long"
        and evidence.lead_strategy == "trend"
    )
    above_rank = ordinal > TOP10_MAX_ORDINAL
    if long_trend and above_rank:
        return "long_trend_and_rank_above_10"
    if long_trend:
        return "long_trend"
    if above_rank:
        return "rank_above_10"
    return None


def _execution_config_compatible(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    config: PaperExecutionConfig,
) -> None:
    request = evidence.risk_request_object
    if request.cost_estimate != conservative_cost_estimate(config):
        raise ProspectiveConsecutiveLossCooldownShadowError(
            "cooldown opportunity cost estimate drift"
        )
    instrument = evidence.instrument_object
    if (
        instrument.minimum_order_notional
        != config.native_perp_min_notional
        or request.limits.max_gross_leverage
        != config.paper_max_gross_leverage
    ):
        raise ProspectiveConsecutiveLossCooldownShadowError(
            "cooldown opportunity execution envelope drift"
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
        raise ProspectiveConsecutiveLossCooldownShadowError(
            "cooldown opportunity timing violates execution latency"
        )


def _expire_only_cooldown(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> tuple[RiskRequest, int, int]:
    request = evidence.risk_request_object
    if request.timestamp_ms != evidence.opportunity_timestamp_ms:
        raise ProspectiveConsecutiveLossCooldownShadowError(
            "cooldown opportunity request timestamp drift"
        )
    account = request.account_state
    limits = request.limits
    last_closed_ms = account.last_closed_trade_ms
    if (
        account.consecutive_losses
        < limits.consecutive_loss_cooldown
        or last_closed_ms is None
        or last_closed_ms > request.timestamp_ms
    ):
        raise ProspectiveConsecutiveLossCooldownShadowError(
            "captured cooldown rejection has inconsistent loss state"
        )
    elapsed_ms = request.timestamp_ms - last_closed_ms
    if elapsed_ms >= limits.cooldown_ms:
        raise ProspectiveConsecutiveLossCooldownShadowError(
            "captured cooldown rejection is already expired"
        )
    adjusted_account = replace(
        account,
        last_closed_trade_ms=(
            request.timestamp_ms - limits.cooldown_ms
        ),
    )
    return (
        replace(request, account_state=adjusted_account),
        elapsed_ms,
        limits.cooldown_ms,
    )


def _path_by_id(
    paths: tuple[ContinuousPaperOpeningOpportunityPath, ...],
) -> dict[str, ContinuousPaperOpeningOpportunityPath]:
    output: dict[str, ContinuousPaperOpeningOpportunityPath] = {}
    for path in paths:
        if path.opportunity_id in output:
            raise ProspectiveConsecutiveLossCooldownShadowError(
                "duplicate cooldown forward path"
            )
        output[path.opportunity_id] = path
    return output


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
        raise ProspectiveConsecutiveLossCooldownShadowError(
            "cooldown forward path lineage mismatch"
        )
    if horizon_ms > path.max_path_age_ms:
        raise ProspectiveConsecutiveLossCooldownShadowError(
            "cooldown markout horizon exceeds captured path"
        )
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
        if not isinstance(markout, dict):
            continue
        if markout.get("status") != "settled":
            continue
        raw_pnl = markout.get(
            "entry_fee_adjusted_mark_to_market_pnl"
        )
        if not isinstance(raw_pnl, str):
            continue
        market = result.get("market")
        if not isinstance(market, str):
            continue
        settled.append((market, Decimal(raw_pnl)))

    total = sum((pnl for _market, pnl in settled), ZERO)
    leave_trade = tuple(total - pnl for _market, pnl in settled)
    by_market: dict[str, Decimal] = {}
    for market, pnl in settled:
        by_market[market] = by_market.get(market, ZERO) + pnl
    leave_market = tuple(
        total - pnl for pnl in by_market.values()
    )
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


def _result_sort_key(
    item: dict[str, object],
) -> tuple[int, str, str]:
    return (
        cast(int, item["timestamp_ms"]),
        cast(str, item["market"]),
        cast(str, item["opportunity_id"]),
    )


def _relaxed_window_applies(
    item: dict[str, object],
    *,
    window_ms: int,
) -> bool:
    elapsed = item.get("baseline_elapsed_since_last_close_ms")
    baseline = item.get("baseline_cooldown_ms")
    return (
        isinstance(elapsed, int)
        and not isinstance(elapsed, bool)
        and elapsed >= window_ms
        and isinstance(baseline, int)
        and not isinstance(baseline, bool)
        and baseline > window_ms
    )


def prospective_consecutive_loss_cooldown_shadow_summary(
    opportunities: tuple[
        ContinuousPaperOpeningOpportunityEvidence,
        ...,
    ],
    paths: tuple[ContinuousPaperOpeningOpportunityPath, ...],
    state: ProspectiveConsecutiveLossCooldownShadowState,
    config: PaperExecutionConfig,
) -> dict[str, object]:
    path_map = _path_by_id(paths)
    all_cooldown = tuple(
        evidence
        for evidence in opportunities
        if not evidence.baseline_risk_approved
        and COOLDOWN_REASON
        in evidence.baseline_risk_reason_codes
    )
    touched = tuple(
        evidence
        for evidence in all_cooldown
        if evidence.opportunity_timestamp_ms < state.started_at_ms
    )
    prospective = tuple(
        evidence
        for evidence in all_cooldown
        if evidence.opportunity_timestamp_ms >= state.started_at_ms
    )

    missing_rank = 0
    stale_rank = 0
    candidate_blocked: Counter[str] = Counter()
    eligible: list[ContinuousPaperOpeningOpportunityEvidence] = []
    for evidence in prospective:
        age = _rank_age_ms(evidence)
        if age is None or evidence.rank_ordinal is None:
            missing_rank += 1
            continue
        if age > MAX_ACCEPTED_RANK_AGE_MS:
            stale_rank += 1
            continue
        block_reason = _candidate_block_reason(evidence)
        if block_reason is not None:
            candidate_blocked[block_reason] += 1
            continue
        eligible.append(evidence)

    results: list[dict[str, object]] = []
    risk_rejections: Counter[str] = Counter()
    planning_rejections: Counter[str] = Counter()
    execution_results: Counter[str] = Counter()
    by_elapsed_bucket: dict[str, _Aggregate] = {
        "0-15m": _Aggregate(),
        "15-30m": _Aggregate(),
        "30-45m": _Aggregate(),
        "45m+": _Aggregate(),
    }
    by_direction: dict[str, _Aggregate] = {
        "long": _Aggregate(),
        "short": _Aggregate(),
    }

    for evidence in eligible:
        _execution_config_compatible(evidence, config)
        request, elapsed_ms, baseline_cooldown_ms = (
            _expire_only_cooldown(evidence)
        )
        if elapsed_ms < 15 * 60 * 1_000:
            elapsed_bucket = "0-15m"
        elif elapsed_ms < 30 * 60 * 1_000:
            elapsed_bucket = "15-30m"
        elif elapsed_ms < 45 * 60 * 1_000:
            elapsed_bucket = "30-45m"
        else:
            elapsed_bucket = "45m+"
        by_elapsed_bucket[elapsed_bucket].options += 1
        by_direction[evidence.direction].options += 1

        result: dict[str, object] = {
            "opportunity_id": evidence.opportunity_id,
            "timestamp_ms": evidence.opportunity_timestamp_ms,
            "market": evidence.market,
            "direction": evidence.direction,
            "lead_strategy": evidence.lead_strategy,
            "rank_ordinal": evidence.rank_ordinal,
            "baseline_consecutive_losses": (
                evidence.risk_request_object.account_state.consecutive_losses
            ),
            "baseline_elapsed_since_last_close_ms": elapsed_ms,
            "baseline_cooldown_ms": baseline_cooldown_ms,
            "elapsed_bucket": elapsed_bucket,
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
            raise ProspectiveConsecutiveLossCooldownShadowError(
                "cooldown fill is missing average price"
            )
        quantity = attempt.filled_quantity
        entry_price = attempt.average_fill_price
        entry_fee = attempt.fee
        result["filled_quantity"] = str(quantity)
        result["average_fill_price"] = str(entry_price)
        result["entry_fee"] = str(entry_fee)
        by_elapsed_bucket[elapsed_bucket].fillable += 1
        by_direction[evidence.direction].fillable += 1

        path = path_map.get(evidence.opportunity_id)
        markouts: dict[str, dict[str, object]] = {}
        for horizon_ms in FORWARD_HORIZONS_MS:
            markouts[str(horizon_ms)] = _markout(
                path=path,
                evidence=evidence,
                horizon_ms=horizon_ms,
                entry_price=entry_price,
                quantity=quantity,
                entry_fee=entry_fee,
            )
        result["markouts"] = markouts

        one_hour = markouts[str(60 * 60 * 1_000)]
        if one_hour["status"] == "settled":
            raw_pnl = one_hour[
                "entry_fee_adjusted_mark_to_market_pnl"
            ]
            if not isinstance(raw_pnl, str):
                raise ProspectiveConsecutiveLossCooldownShadowError(
                    "settled cooldown markout is missing PnL"
                )
            pnl = Decimal(raw_pnl)
            for aggregate in (
                by_elapsed_bucket[elapsed_bucket],
                by_direction[evidence.direction],
            ):
                aggregate.settled_1h += 1
                aggregate.pnl_1h += pnl
                if pnl > ZERO:
                    aggregate.positive_1h += 1
                elif pnl < ZERO:
                    aggregate.negative_1h += 1
                else:
                    aggregate.flat_1h += 1
        results.append(result)

    result_tuple = tuple(
        sorted(
            results,
            key=_result_sort_key,
        )
    )

    by_horizon: dict[str, dict[str, object]] = {}
    for horizon_ms in FORWARD_HORIZONS_MS:
        key = str(horizon_ms)
        settled = 0
        pending = 0
        stale = 0
        missing_path = 0
        positive = 0
        negative = 0
        flat = 0
        pnl = ZERO
        returns = ZERO
        for result in result_tuple:
            markouts = result["markouts"]
            if not isinstance(markouts, dict):
                continue
            markout = markouts.get(key)
            if not isinstance(markout, dict):
                continue
            status = markout.get("status")
            if status == "pending":
                pending += 1
                continue
            if status == "stale":
                stale += 1
                continue
            if status == "missing_path":
                missing_path += 1
                continue
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
                raise ProspectiveConsecutiveLossCooldownShadowError(
                    "settled cooldown markout is incomplete"
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
            "settled": settled,
            "pending": pending,
            "stale": stale,
            "missing_path": missing_path,
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

    one_hour_key = str(60 * 60 * 1_000)
    relaxation: dict[str, dict[str, object]] = {}
    for window_ms in RELAXED_COOLDOWN_WINDOWS_MS:
        candidates = tuple(
            result
            for result in result_tuple
            if _relaxed_window_applies(
                result,
                window_ms=window_ms,
            )
        )
        fillable = tuple(
            result
            for result in candidates
            if result.get("filled_quantity") is not None
        )
        relaxation[str(window_ms)] = {
            "relaxed_cooldown_ms": window_ms,
            "would_unblock_opportunities": len(candidates),
            "fillable_opportunities": len(fillable),
            "one_hour_robustness": _robustness(
                fillable,
                horizon_key=one_hour_key,
            ),
        }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_risk_limits": False,
        "candidate_id": state.candidate_id,
        "frozen_at_ms": state.frozen_at_ms,
        "started_at_ms": state.started_at_ms,
        "embargo_ms": EMBARGO_MS,
        "relaxed_cooldown_windows_ms": list(
            RELAXED_COOLDOWN_WINDOWS_MS
        ),
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "observed_cooldown_rejections": len(all_cooldown),
        "pre_clean_touched_cooldown_rejections": len(touched),
        "clean_cooldown_rejections": len(prospective),
        "candidate_eligible_cooldown_rejections": len(eligible),
        "missing_rank_evidence": missing_rank,
        "stale_rank_evidence": stale_rank,
        "candidate_blocked": dict(sorted(candidate_blocked.items())),
        "counterfactual_risk_rejections": dict(
            sorted(risk_rejections.items())
        ),
        "planning_rejections": dict(
            sorted(planning_rejections.items())
        ),
        "execution_results": dict(
            sorted(execution_results.items())
        ),
        "by_elapsed_bucket": {
            key: value.payload()
            for key, value in by_elapsed_bucket.items()
        },
        "by_direction": {
            key: value.payload()
            for key, value in by_direction.items()
        },
        "by_horizon": by_horizon,
        "relaxation_windows": relaxation,
        "option_results": list(result_tuple),
        "forward_markout_only": True,
        "replacement_exits_modeled": False,
        "realized_pnl_modeled": False,
    }


def evaluate_prospective_consecutive_loss_cooldown_shadow(
    opportunity_store: ContinuousPaperOpeningOpportunityStore,
    path_store: ContinuousPaperOpeningOpportunityPathStore,
    state: ProspectiveConsecutiveLossCooldownShadowState,
    config: PaperExecutionConfig,
) -> dict[str, object]:
    return prospective_consecutive_loss_cooldown_shadow_summary(
        opportunity_store.iter_records(),
        path_store.iter_paths(),
        state,
        config,
    )
