from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from typing import Final, cast

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.evidence.openings import conservative_cost_estimate
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.execution.planner import PlanningRejection, plan_opening_order
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
)
from cocomelon.research.prospective_full_stack_forward_markout import (
    LONG_TREND_CARVEOUT_CANDIDATE_ID,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    SOURCE_KIND,
    WEEKLY_DRAWDOWN_REASON,
)
from cocomelon.research.prospective_momentum_band_forward_markout import (
    FORWARD_HORIZONS_MS,
    MAX_MARK_LAG_MS,
)
from cocomelon.risk.engine import evaluate_risk

SCHEMA_VERSION: Final = 1
SHADOW_KIND: Final = (
    "prospective-long-trend-carveout-execution-shadow-v1"
)
ZERO: Final = Decimal("0")


class ProspectiveLongTrendExecutionShadowError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _validate_source(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source must be an object"
        )
    if raw.get("enabled") is not True or raw.get("error") is not None:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source is not cleanly enabled"
        )
    if (
        raw.get("schema_version") != 1
        or raw.get("kind") != SOURCE_KIND
        or raw.get("candidate_id")
        != LONG_TREND_CARVEOUT_CANDIDATE_ID
        or raw.get("baseline_risk_reason") != WEEKLY_DRAWDOWN_REASON
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source contract drift"
        )
    if (
        raw.get("research_only") is not True
        or raw.get("execution_authority") is not False
        or raw.get("promotion_authority") is not False
        or raw.get("changes_execution") is not False
        or raw.get("changes_risk_limits") is not False
        or raw.get("changes_candidate_readiness") is not False
        or raw.get("durable_gate_required") is not True
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source authority drift"
        )
    expected_digest = raw.get("source_sha256")
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source digest is invalid"
        )
    digest_payload = {
        key: value
        for key, value in raw.items()
        if key not in {"source_sha256", "enabled", "error"}
    }
    if _sha256(digest_payload) != expected_digest:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source digest mismatch"
        )
    rows = raw.get("opportunities")
    if not isinstance(rows, list):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source opportunities must be a list"
        )
    if raw.get("source_opportunity_count") != len(rows):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source opportunity count mismatch"
        )
    return raw


def _execution_config_compatible(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    config: PaperExecutionConfig,
) -> None:
    request = evidence.risk_request_object
    if request.cost_estimate != conservative_cost_estimate(config):
        raise ProspectiveLongTrendExecutionShadowError(
            "LONG+trend opportunity cost estimate drift"
        )
    instrument = evidence.instrument_object
    if (
        instrument.minimum_order_notional
        != config.native_perp_min_notional
        or request.limits.max_gross_leverage
        != config.paper_max_gross_leverage
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "LONG+trend opportunity execution envelope drift"
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
        raise ProspectiveLongTrendExecutionShadowError(
            "LONG+trend opportunity timing violates execution latency"
        )


def _neutralize_weekly_drawdown_only(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
):
    if (
        evidence.baseline_risk_approved
        or evidence.baseline_risk_reason_codes
        != (WEEKLY_DRAWDOWN_REASON,)
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "LONG+trend shadow requires exact weekly-drawdown rejection"
        )
    request = evidence.risk_request_object
    if request.timestamp_ms != evidence.opportunity_timestamp_ms:
        raise ProspectiveLongTrendExecutionShadowError(
            "LONG+trend opportunity request timestamp drift"
        )
    baseline = evaluate_risk(request)
    if (
        baseline.approved
        or baseline.reason_codes != (WEEKLY_DRAWDOWN_REASON,)
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "captured weekly-drawdown rejection does not reproduce"
        )

    account = request.account_state
    drawdown = (
        account.rolling_7d_peak_equity - account.equity
    ) / account.rolling_7d_peak_equity
    if drawdown < request.limits.weekly_drawdown_limit:
        raise ProspectiveLongTrendExecutionShadowError(
            "captured weekly drawdown is below the frozen limit"
        )

    adjusted_account = replace(
        account,
        rolling_7d_peak_equity=account.equity,
    )
    adjusted_request = replace(
        request,
        account_state=adjusted_account,
    )
    if (
        adjusted_request.account_state.equity != account.equity
        or adjusted_request.account_state.day_start_equity
        != account.day_start_equity
        or adjusted_request.account_state.daily_realized_pnl
        != account.daily_realized_pnl
        or adjusted_request.account_state.available_margin
        != account.available_margin
        or adjusted_request.account_state.gross_open_notional
        != account.gross_open_notional
        or adjusted_request.account_state.consecutive_losses
        != account.consecutive_losses
        or adjusted_request.account_state.last_closed_trade_ms
        != account.last_closed_trade_ms
        or adjusted_request.account_state.as_of_ms != account.as_of_ms
        or adjusted_request.open_positions != request.open_positions
        or adjusted_request.health_state != request.health_state
        or adjusted_request.cost_estimate != request.cost_estimate
        or adjusted_request.liquidity_state != request.liquidity_state
        or adjusted_request.limits != request.limits
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "weekly-drawdown counterfactual changed unrelated risk state"
        )
    return adjusted_request, drawdown


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
        path.opportunity_id != evidence.opportunity_id
        or path.market != evidence.market
        or path.direction != evidence.direction
        or path.opportunity_timestamp_ms
        != evidence.opportunity_timestamp_ms
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "LONG+trend forward path lineage mismatch"
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
        "entry_fee_adjusted_mark_to_market_pnl": str(
            gross - entry_fee
        ),
    }


def _horizon_summary(
    results: tuple[dict[str, object], ...],
    horizon_ms: int,
) -> dict[str, object]:
    key = str(horizon_ms)
    statuses: Counter[str] = Counter()
    pnl_values: list[tuple[str, Decimal]] = []
    return_values: list[Decimal] = []
    for result in results:
        markouts = result.get("markouts")
        if not isinstance(markouts, dict):
            continue
        markout = markouts.get(key)
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
        raw_return = markout.get("directional_return_fraction")
        market = result.get("market")
        if (
            not isinstance(raw_pnl, str)
            or not isinstance(raw_return, str)
            or not isinstance(market, str)
        ):
            raise ProspectiveLongTrendExecutionShadowError(
                "settled LONG+trend markout is incomplete"
            )
        pnl_values.append((market, Decimal(raw_pnl)))
        return_values.append(Decimal(raw_return))

    total_pnl = sum((value for _market, value in pnl_values), ZERO)
    leave_trade = tuple(
        total_pnl - value for _market, value in pnl_values
    )
    by_market: dict[str, Decimal] = {}
    for market, value in pnl_values:
        by_market[market] = by_market.get(market, ZERO) + value
    leave_market = tuple(
        total_pnl - value for value in by_market.values()
    )
    return {
        "horizon_ms": horizon_ms,
        "status_counts": dict(sorted(statuses.items())),
        "settled": len(pnl_values),
        "market_count": len(by_market),
        "positive": sum(value > ZERO for _market, value in pnl_values),
        "negative": sum(value < ZERO for _market, value in pnl_values),
        "flat": sum(value == ZERO for _market, value in pnl_values),
        "mean_directional_return": (
            None
            if not return_values
            else str(
                sum(return_values, ZERO)
                / Decimal(len(return_values))
            )
        ),
        "total_entry_fee_adjusted_mark_to_market_pnl": str(
            total_pnl
        ),
        "leave_one_opportunity_min_pnl": (
            None if not leave_trade else str(min(leave_trade))
        ),
        "leave_one_market_min_pnl": (
            None if not leave_market else str(min(leave_market))
        ),
    }


def evaluate_long_trend_carveout_execution_shadow(
    source: object,
    *,
    durable_gate_ready: bool,
    durable_gate_ledger_sha256: str,
    config: PaperExecutionConfig | None = None,
) -> dict[str, object]:
    validated = _validate_source(source)
    if not durable_gate_ledger_sha256.strip():
        raise ProspectiveLongTrendExecutionShadowError(
            "durable gate ledger digest must not be empty"
        )
    base: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": SHADOW_KIND,
        "candidate_id": LONG_TREND_CARVEOUT_CANDIDATE_ID,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "durable_gate_ready": durable_gate_ready,
        "durable_gate_ledger_sha256": durable_gate_ledger_sha256,
        "source_sha256": validated["source_sha256"],
        "execution_model": (
            "captured_risk_planner_and_decision_time_ioc"
        ),
        "counterfactual_change": (
            "neutralize_only_weekly_drawdown_peak_reference"
        ),
        "outcome_scope": "fixed_forward_mark_to_market_only",
        "realized_pnl_modeled": False,
        "replacement_exits_modeled": False,
    }
    if not durable_gate_ready:
        return {
            **base,
            "status": "dormant_gate_not_ready",
            "source_opportunity_count": validated[
                "source_opportunity_count"
            ],
            "evaluated": 0,
            "results": [],
            "horizons": {},
        }

    execution_config = (
        PaperExecutionConfig() if config is None else config
    )
    raw_rows = cast(list[object], validated["opportunities"])
    results: list[dict[str, object]] = []
    risk_rejections: Counter[str] = Counter()
    planning_rejections: Counter[str] = Counter()
    execution_results: Counter[str] = Counter()

    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow source row must be an object"
            )
        opportunity_raw = raw.get("opportunity")
        path_raw = raw.get("path")
        evidence = ContinuousPaperOpeningOpportunityEvidence.from_dict(
            opportunity_raw
        )
        if evidence.opportunity_id != raw.get("opportunity_id"):
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opportunity id mismatch"
            )
        if evidence.direction != "long" or evidence.lead_strategy != "trend":
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow source is not pure LONG+trend"
            )
        path = (
            None
            if path_raw is None
            else ContinuousPaperOpeningOpportunityPath.from_dict(
                path_raw
            )
        )
        _execution_config_compatible(evidence, execution_config)
        request, baseline_drawdown = _neutralize_weekly_drawdown_only(
            evidence
        )
        risk = evaluate_risk(request)
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
            "counterfactual_risk_approved": risk.approved,
            "counterfactual_risk_reason_codes": list(
                risk.reason_codes
            ),
            "planning_approved": False,
            "planning_rejection": None,
            "execution_result": None,
            "execution_reason_codes": [],
            "filled_quantity": None,
            "average_fill_price": None,
            "entry_fee": None,
            "markouts": {},
        }
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
            execution_config,
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
            execution_config,
            attempt_timestamp_ms=request.timestamp_ms,
        )
        attempt = simulation.attempt
        result["execution_result"] = attempt.result.value
        result["execution_reason_codes"] = list(
            attempt.reason_codes
        )
        execution_results[attempt.result.value] += 1
        if not simulation.fills:
            results.append(result)
            continue
        if attempt.average_fill_price is None:
            raise ProspectiveLongTrendExecutionShadowError(
                "LONG+trend fill is missing average price"
            )
        quantity = attempt.filled_quantity
        entry_price = attempt.average_fill_price
        entry_fee = attempt.fee
        result["filled_quantity"] = str(quantity)
        result["average_fill_price"] = str(entry_price)
        result["entry_fee"] = str(entry_fee)
        result["markouts"] = {
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
    payload = {
        **base,
        "status": "evaluated",
        "source_opportunity_count": validated[
            "source_opportunity_count"
        ],
        "evaluated": len(result_tuple),
        "counterfactual_risk_rejections": dict(
            sorted(risk_rejections.items())
        ),
        "planning_rejections": dict(
            sorted(planning_rejections.items())
        ),
        "execution_results": dict(
            sorted(execution_results.items())
        ),
        "fillable": sum(
            result["filled_quantity"] is not None
            for result in result_tuple
        ),
        "horizons": {
            str(horizon_ms): _horizon_summary(
                result_tuple,
                horizon_ms,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        },
        "results": list(result_tuple),
    }
    payload["shadow_sha256"] = _sha256(payload)
    return payload
