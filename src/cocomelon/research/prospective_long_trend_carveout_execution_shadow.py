from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from typing import Final, cast

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.risk import RiskRequest
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
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    SCHEMA_VERSION as SOURCE_SCHEMA_VERSION,
)
from cocomelon.risk.engine import evaluate_risk

FORWARD_HORIZONS_MS: Final = (
    5 * 60 * 1_000,
    15 * 60 * 1_000,
    60 * 60 * 1_000,
)
MAX_MARK_LAG_MS: Final = 120_000
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


def _validate_source(raw: object) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, dict):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source must be an object"
        )
    if raw.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source schema is unsupported"
        )
    if raw.get("kind") != SOURCE_KIND:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source kind is unsupported"
        )
    if raw.get("candidate_id") != LONG_TREND_CARVEOUT_CANDIDATE_ID:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow candidate drift"
        )
    if raw.get("baseline_risk_reason") != WEEKLY_DRAWDOWN_REASON:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow baseline risk reason drift"
        )
    for key, expected in (
        ("research_only", True),
        ("execution_authority", False),
        ("promotion_authority", False),
        ("changes_execution", False),
        ("changes_risk_limits", False),
        ("changes_candidate_readiness", False),
        ("durable_gate_required", True),
    ):
        if raw.get(key) is not expected:
            raise ProspectiveLongTrendExecutionShadowError(
                f"execution-shadow source authority drift: {key}"
            )

    source_sha256 = raw.get("source_sha256")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source digest is invalid"
        )
    digest_payload = {
        key: value
        for key, value in raw.items()
        if key != "source_sha256"
    }
    if _sha256(digest_payload) != source_sha256:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source digest mismatch"
        )

    opportunities = raw.get("opportunities")
    if not isinstance(opportunities, list):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow opportunities must be a list"
        )
    if raw.get("source_opportunity_count") != len(opportunities):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source opportunity count mismatch"
        )
    if raw.get("missing_opportunity_evidence") != 0:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow source has missing opening evidence"
        )
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in opportunities:
        if not isinstance(item, dict):
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opportunity row must be an object"
            )
        opportunity_id = item.get("opportunity_id")
        if not isinstance(opportunity_id, str) or not opportunity_id:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opportunity id is invalid"
            )
        if opportunity_id in seen:
            raise ProspectiveLongTrendExecutionShadowError(
                "duplicate execution-shadow opportunity id"
            )
        seen.add(opportunity_id)
        rows.append(item)
    return tuple(rows)


def _execution_config_compatible(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    config: PaperExecutionConfig,
) -> None:
    request = evidence.risk_request_object
    instrument = evidence.instrument_object
    if request.cost_estimate != conservative_cost_estimate(config):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow cost estimate drift"
        )
    if (
        instrument.minimum_order_notional
        != config.native_perp_min_notional
        or request.limits.max_gross_leverage
        != config.paper_max_gross_leverage
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow execution envelope drift"
        )
    received_at_ms = int(
        evidence.book_event.receive_time.timestamp() * 1000
    )
    earliest_ms = (
        request.strategy_decision.timestamp_ms + config.latency_ms
    )
    if (
        request.timestamp_ms < earliest_ms
        or received_at_ms < earliest_ms
        or received_at_ms > request.timestamp_ms
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow captured timing violates execution latency"
        )


def _neutralize_weekly_drawdown(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> RiskRequest:
    request = evidence.risk_request_object
    baseline = evaluate_risk(request)
    if (
        baseline.approved
        or baseline.reason_codes != (WEEKLY_DRAWDOWN_REASON,)
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow baseline request is not weekly-drawdown-only"
        )
    account = request.account_state
    peak = account.rolling_7d_peak_equity
    if peak <= ZERO or account.equity <= ZERO or peak < account.equity:
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow weekly drawdown state is invalid"
        )
    adjusted_account = replace(
        account,
        rolling_7d_peak_equity=account.equity,
    )
    return replace(request, account_state=adjusted_account)


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
    base: dict[str, object] = {
        "horizon_ms": horizon_ms,
        "target_at_ms": target_at_ms,
        "observed_at_ms": None,
        "observation_lag_ms": None,
        "mark_px": None,
        "directional_return_fraction": None,
        "gross_mark_to_market_pnl": None,
        "entry_fee_adjusted_mark_to_market_pnl": None,
    }
    if path is None:
        return {**base, "status": "missing_path"}
    if (
        path.opportunity_id != evidence.opportunity_id
        or path.market != evidence.market
        or path.direction != evidence.direction
        or path.opportunity_timestamp_ms
        != evidence.opportunity_timestamp_ms
    ):
        raise ProspectiveLongTrendExecutionShadowError(
            "execution-shadow forward path lineage mismatch"
        )
    if horizon_ms > path.max_path_age_ms:
        return {**base, "status": "unsupported_horizon"}

    mark = next(
        (
            item
            for item in path.marks
            if item.observed_at_ms >= target_at_ms
        ),
        None,
    )
    if mark is None:
        return {**base, "status": "pending"}
    lag_ms = mark.observed_at_ms - target_at_ms
    observed = {
        **base,
        "observed_at_ms": mark.observed_at_ms,
        "observation_lag_ms": lag_ms,
        "mark_px": str(mark.mark_px),
    }
    if lag_ms > MAX_MARK_LAG_MS:
        return {**observed, "status": "stale"}

    signed_move = mark.mark_px - entry_price
    gross = signed_move * quantity
    fee_adjusted = gross - entry_fee
    return {
        **observed,
        "status": "settled",
        "directional_return_fraction": str(
            signed_move / entry_price
        ),
        "gross_mark_to_market_pnl": str(gross),
        "entry_fee_adjusted_mark_to_market_pnl": str(
            fee_adjusted
        ),
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
        market = result.get("market")
        if not isinstance(raw_pnl, str) or not isinstance(market, str):
            continue
        settled.append((market, Decimal(raw_pnl)))

    total = sum((pnl for _market, pnl in settled), ZERO)
    leave_option = tuple(total - pnl for _market, pnl in settled)
    by_market: dict[str, Decimal] = {}
    for market, pnl in settled:
        by_market[market] = by_market.get(market, ZERO) + pnl
    leave_market = tuple(
        total - pnl for pnl in by_market.values()
    )
    return {
        "settled_fills": len(settled),
        "market_count": len(by_market),
        "total_entry_fee_adjusted_pnl": str(total),
        "leave_one_option_out_min_pnl": str(
            min(leave_option, default=ZERO)
        ),
        "positive_after_removing_any_one_option": (
            len(settled) >= 2
            and min(leave_option, default=ZERO) > ZERO
        ),
        "leave_one_market_out_min_pnl": str(
            min(leave_market, default=ZERO)
        ),
        "positive_after_removing_any_one_market": (
            len(by_market) >= 2
            and min(leave_market, default=ZERO) > ZERO
        ),
    }


def _horizon_summary(
    results: tuple[dict[str, object], ...],
    horizon_ms: int,
) -> dict[str, object]:
    key = str(horizon_ms)
    status_counts: Counter[str] = Counter()
    settled_pnl: list[Decimal] = []
    settled_returns: list[Decimal] = []
    for result in results:
        markouts = result.get("markouts")
        if not isinstance(markouts, dict):
            continue
        markout = markouts.get(key)
        if not isinstance(markout, dict):
            continue
        status = markout.get("status")
        if isinstance(status, str):
            status_counts[status] += 1
        if status != "settled":
            continue
        raw_pnl = markout.get(
            "entry_fee_adjusted_mark_to_market_pnl"
        )
        raw_return = markout.get("directional_return_fraction")
        if not isinstance(raw_pnl, str) or not isinstance(
            raw_return, str
        ):
            raise ProspectiveLongTrendExecutionShadowError(
                "settled execution-shadow markout is incomplete"
            )
        settled_pnl.append(Decimal(raw_pnl))
        settled_returns.append(Decimal(raw_return))

    positive = tuple(value for value in settled_pnl if value > ZERO)
    negative = tuple(value for value in settled_pnl if value < ZERO)
    flat = sum(value == ZERO for value in settled_pnl)
    gross_profit = sum(positive, ZERO)
    gross_loss = -sum(negative, ZERO)
    settled_count = len(settled_pnl)
    return {
        "horizon_ms": horizon_ms,
        "status_counts": dict(sorted(status_counts.items())),
        "settled": settled_count,
        "positive": len(positive),
        "negative": len(negative),
        "flat": flat,
        "positive_fraction": (
            None
            if settled_count == 0
            else str(Decimal(len(positive)) / Decimal(settled_count))
        ),
        "total_entry_fee_adjusted_mark_to_market_pnl": str(
            sum(settled_pnl, ZERO)
        ),
        "mean_entry_fee_adjusted_mark_to_market_pnl": (
            None
            if settled_count == 0
            else str(sum(settled_pnl, ZERO) / Decimal(settled_count))
        ),
        "mean_directional_return_fraction": (
            None
            if settled_count == 0
            else str(
                sum(settled_returns, ZERO)
                / Decimal(settled_count)
            )
        ),
        "gross_profit": str(gross_profit),
        "gross_loss": str(gross_loss),
        "profit_factor": (
            None
            if gross_loss == ZERO
            else str(gross_profit / gross_loss)
        ),
        "robustness": _robustness(
            results,
            horizon_key=key,
        ),
    }


def prospective_long_trend_execution_shadow_summary(
    source: object,
    config: PaperExecutionConfig,
) -> dict[str, object]:
    rows = _validate_source(source)
    results: list[dict[str, object]] = []
    risk_rejections: Counter[str] = Counter()
    planning_rejections: Counter[str] = Counter()
    execution_results: Counter[str] = Counter()

    for row in rows:
        opportunity_id = cast(str, row["opportunity_id"])
        raw_opportunity = row.get("opportunity")
        try:
            evidence = ContinuousPaperOpeningOpportunityEvidence.from_dict(
                raw_opportunity
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opening evidence is invalid"
            ) from exc
        if evidence.opportunity_id != opportunity_id:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opening evidence id mismatch"
            )
        if (
            evidence.direction != "long"
            or evidence.lead_strategy != "trend"
            or evidence.baseline_risk_approved
            or evidence.baseline_risk_reason_codes
            != (WEEKLY_DRAWDOWN_REASON,)
        ):
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow opening evidence lineage mismatch"
            )

        raw_path = row.get("path")
        path: ContinuousPaperOpeningOpportunityPath | None
        if raw_path is None:
            path = None
        else:
            try:
                path = ContinuousPaperOpeningOpportunityPath.from_dict(
                    raw_path
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProspectiveLongTrendExecutionShadowError(
                    "execution-shadow forward path is invalid"
                ) from exc

        _execution_config_compatible(evidence, config)
        adjusted_request = _neutralize_weekly_drawdown(evidence)
        risk = evaluate_risk(adjusted_request)

        result: dict[str, object] = {
            "opportunity_id": opportunity_id,
            "timestamp_ms": evidence.opportunity_timestamp_ms,
            "market": evidence.market,
            "direction": evidence.direction,
            "lead_strategy": evidence.lead_strategy,
            "counterfactual_risk_approved": risk.approved,
            "counterfactual_risk_reason_codes": list(
                risk.reason_codes
            ),
            "planning_approved": False,
            "planning_rejection": None,
            "execution_result": None,
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
            config,
            adjusted_request.entry_reference_price,
            adjusted_request.strategy_decision.timestamp_ms,
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
            attempt_timestamp_ms=adjusted_request.timestamp_ms,
        )
        attempt = simulation.attempt
        result["execution_result"] = attempt.result.value
        execution_results[attempt.result.value] += 1
        if not simulation.fills:
            results.append(result)
            continue
        if attempt.average_fill_price is None:
            raise ProspectiveLongTrendExecutionShadowError(
                "execution-shadow fill is missing average price"
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
    fillable = sum(
        item["filled_quantity"] is not None
        for item in result_tuple
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "candidate_id": LONG_TREND_CARVEOUT_CANDIDATE_ID,
        "baseline_risk_reason": WEEKLY_DRAWDOWN_REASON,
        "execution_model": (
            "captured_request_plus_decision_time_visible_book_ioc"
        ),
        "outcome_scope": (
            "entry_fee_adjusted_forward_mark_to_market_only"
        ),
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "source_opportunities": len(rows),
        "counterfactual_risk_approvals": sum(
            item["counterfactual_risk_approved"] is True
            for item in result_tuple
        ),
        "counterfactual_risk_rejections": dict(
            sorted(risk_rejections.items())
        ),
        "planning_approvals": sum(
            item["planning_approved"] is True
            for item in result_tuple
        ),
        "planning_rejections": dict(
            sorted(planning_rejections.items())
        ),
        "execution_results": dict(
            sorted(execution_results.items())
        ),
        "fillable_opportunities": fillable,
        "by_horizon": {
            str(horizon_ms): _horizon_summary(
                result_tuple,
                horizon_ms,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        },
        "option_results": list(result_tuple),
        "replacement_exits_modeled": False,
        "exit_fees_modeled": False,
        "funding_modeled": False,
        "realized_pnl_modeled": False,
    }
