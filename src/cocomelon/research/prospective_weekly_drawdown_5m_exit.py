from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Final, cast

from cocomelon.domain.execution import (
    PaperExecutionConfig,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.risk import RiskRequest
from cocomelon.evidence.openings import conservative_cost_estimate
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.execution.funding import (
    FUNDING_INTERVAL_MS,
    funding_cash_delta,
)
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.execution.planner import (
    PlanningRejection,
    plan_opening_order,
    plan_reduce_only_order,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    OpeningOpportunityExitBookEvidence,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ReplacementFundingBoundaryEvidence,
)
from cocomelon.research.prospective_weekly_drawdown_5m_exit_source import (
    CANDIDATE_ID,
    EXIT_HORIZON_MS,
    SCHEMA_VERSION,
    SOURCE_KIND,
    WEEKLY_DRAWDOWN_REASON,
    ProspectiveWeeklyDrawdown5mExitState,
    execution_config_payload,
)
from cocomelon.risk.engine import evaluate_risk

ZERO: Final = Decimal("0")


class ProspectiveWeeklyDrawdown5mExitError(RuntimeError):
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


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProspectiveWeeklyDrawdown5mExitError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ProspectiveWeeklyDrawdown5mExitError(
            f"{field} must be finite"
        )
    return resolved


def _execution_config_from_payload(
    raw: object,
) -> PaperExecutionConfig:
    if not isinstance(raw, dict):
        raise ProspectiveWeeklyDrawdown5mExitError(
            "captured execution config must be an object"
        )

    def required_int(key: str) -> int:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProspectiveWeeklyDrawdown5mExitError(
                f"captured execution config {key} is invalid"
            )
        return value

    def required_string(key: str) -> str:
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise ProspectiveWeeklyDrawdown5mExitError(
                f"captured execution config {key} is invalid"
            )
        return value

    raw_max_position_age_ms = raw.get("max_position_age_ms")
    max_position_age_ms: int | None
    if raw_max_position_age_ms is None:
        max_position_age_ms = None
    elif (
        isinstance(raw_max_position_age_ms, bool)
        or not isinstance(raw_max_position_age_ms, int)
    ):
        raise ProspectiveWeeklyDrawdown5mExitError(
            "captured execution config max_position_age_ms is invalid"
        )
    else:
        max_position_age_ms = raw_max_position_age_ms

    try:
        return PaperExecutionConfig(
            config_version=required_string("config_version"),
            latency_ms=required_int("latency_ms"),
            max_book_age_ms=required_int("max_book_age_ms"),
            max_asset_ctx_age_ms=required_int(
                "max_asset_ctx_age_ms"
            ),
            max_position_age_ms=max_position_age_ms,
            funding_reconciliation_grace_ms=required_int(
                "funding_reconciliation_grace_ms"
            ),
            max_ioc_slippage_bps=Decimal(
                required_string("max_ioc_slippage_bps")
            ),
            taker_fee_rate=Decimal(
                required_string("taker_fee_rate")
            ),
            fee_schedule_id=required_string("fee_schedule_id"),
            native_perp_min_notional=Decimal(
                required_string("native_perp_min_notional")
            ),
            paper_max_gross_leverage=Decimal(
                required_string("paper_max_gross_leverage")
            ),
        )
    except (ValueError, ArithmeticError) as exc:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "captured execution config is invalid"
        ) from exc


def _validate_source(
    raw: object,
) -> tuple[
    tuple[dict[str, object], ...],
    PaperExecutionConfig,
    ProspectiveWeeklyDrawdown5mExitState,
]:
    if not isinstance(raw, dict):
        raise ProspectiveWeeklyDrawdown5mExitError(
            "weekly-drawdown 5m source must be an object"
        )
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "weekly-drawdown 5m source schema is unsupported"
        )
    if raw.get("kind") != SOURCE_KIND:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "weekly-drawdown 5m source kind is unsupported"
        )
    if raw.get("candidate_id") != CANDIDATE_ID:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "weekly-drawdown 5m candidate drift"
        )
    if raw.get("exit_horizon_ms") != EXIT_HORIZON_MS:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "weekly-drawdown 5m horizon drift"
        )
    if raw.get("baseline_risk_reason") != WEEKLY_DRAWDOWN_REASON:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "weekly-drawdown 5m risk reason drift"
        )
    for key, expected in (
        ("research_only", True),
        ("execution_authority", False),
        ("promotion_authority", False),
        ("changes_execution", False),
        ("changes_risk_limits", False),
        ("changes_candidate_readiness", False),
        ("discovery_cohort_reused_for_validation", False),
        ("cross_horizon_selection_frozen", True),
    ):
        if raw.get(key) is not expected:
            raise ProspectiveWeeklyDrawdown5mExitError(
                f"weekly-drawdown 5m source authority drift: {key}"
            )

    source_sha256 = raw.get("source_sha256")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "source digest is invalid"
        )
    digest_payload = {
        key: value
        for key, value in raw.items()
        if key != "source_sha256"
    }
    if _sha256(digest_payload) != source_sha256:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "source digest mismatch"
        )

    config_payload = raw.get("execution_config")
    config_sha256 = raw.get("execution_config_sha256")
    if (
        not isinstance(config_sha256, str)
        or len(config_sha256) != 64
        or _sha256(config_payload) != config_sha256
    ):
        raise ProspectiveWeeklyDrawdown5mExitError(
            "execution config digest mismatch"
        )
    config = _execution_config_from_payload(config_payload)
    state = ProspectiveWeeklyDrawdown5mExitState.from_payload(
        raw.get("candidate_state")
    )
    if raw.get("started_at_ms") != state.started_at_ms:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "candidate start does not match frozen state"
        )

    opportunities = raw.get("opportunities")
    if not isinstance(opportunities, list):
        raise ProspectiveWeeklyDrawdown5mExitError(
            "source opportunities must be a list"
        )
    if raw.get("source_opportunity_count") != len(opportunities):
        raise ProspectiveWeeklyDrawdown5mExitError(
            "source opportunity count mismatch"
        )
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in opportunities:
        if not isinstance(item, dict):
            raise ProspectiveWeeklyDrawdown5mExitError(
                "source opportunity row must be an object"
            )
        opportunity_id = item.get("opportunity_id")
        if not isinstance(opportunity_id, str) or not opportunity_id:
            raise ProspectiveWeeklyDrawdown5mExitError(
                "source opportunity id is invalid"
            )
        if opportunity_id in seen:
            raise ProspectiveWeeklyDrawdown5mExitError(
                "duplicate source opportunity id"
            )
        seen.add(opportunity_id)
        rows.append(item)
    return tuple(rows), config, state


def _execution_config_compatible(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    config: PaperExecutionConfig,
) -> None:
    request = evidence.risk_request_object
    instrument = evidence.instrument_object
    if request.cost_estimate != conservative_cost_estimate(config):
        raise ProspectiveWeeklyDrawdown5mExitError(
            "execution cost estimate drift"
        )
    if (
        instrument.minimum_order_notional
        != config.native_perp_min_notional
        or request.limits.max_gross_leverage
        != config.paper_max_gross_leverage
    ):
        raise ProspectiveWeeklyDrawdown5mExitError(
            "execution envelope drift"
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
        raise ProspectiveWeeklyDrawdown5mExitError(
            "captured entry timing violates execution latency"
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
        raise ProspectiveWeeklyDrawdown5mExitError(
            "baseline request is not weekly-drawdown-only"
        )
    account = request.account_state
    peak = account.rolling_7d_peak_equity
    if peak <= ZERO or account.equity <= ZERO or peak < account.equity:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "weekly drawdown state is invalid"
        )
    return replace(
        request,
        account_state=replace(
            account,
            rolling_7d_peak_equity=account.equity,
        ),
    )


def _best_reference(
    evidence: OpeningOpportunityExitBookEvidence,
    side: PositionSide,
) -> Decimal:
    raw = (
        evidence.book_event.payload.get("bids")
        if side is PositionSide.LONG
        else evidence.book_event.payload.get("asks")
    )
    if not isinstance(raw, (tuple, list)) or not raw:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "five-minute exit book side is empty"
        )
    prices: list[Decimal] = []
    for row in raw:
        if not isinstance(row, dict):
            raise ProspectiveWeeklyDrawdown5mExitError(
                "five-minute exit book level is invalid"
            )
        price = _decimal(row.get("px"), "five-minute exit book price")
        if price <= ZERO:
            raise ProspectiveWeeklyDrawdown5mExitError(
                "five-minute exit book price must be positive"
            )
        prices.append(price)
    return max(prices) if side is PositionSide.LONG else min(prices)


def _gross_pnl(
    *,
    side: PositionSide,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    if side is PositionSide.LONG:
        return (exit_price - entry_price) * quantity
    return (entry_price - exit_price) * quantity


def _funding_boundaries(
    *,
    opened_at_ms: int,
    closed_at_ms: int,
) -> tuple[int, ...]:
    if closed_at_ms < opened_at_ms:
        raise ProspectiveWeeklyDrawdown5mExitError(
            "five-minute exit precedes entry"
        )
    first = (
        (opened_at_ms // FUNDING_INTERVAL_MS) + 1
    ) * FUNDING_INTERVAL_MS
    if first > closed_at_ms:
        return ()
    return tuple(
        range(first, closed_at_ms + 1, FUNDING_INTERVAL_MS)
    )


def _funding_index(
    raw: object,
) -> dict[tuple[str, int], ReplacementFundingBoundaryEvidence]:
    if not isinstance(raw, list):
        raise ProspectiveWeeklyDrawdown5mExitError(
            "funding evidence must be a list"
        )
    output: dict[
        tuple[str, int],
        ReplacementFundingBoundaryEvidence,
    ] = {}
    for item in raw:
        try:
            evidence = ReplacementFundingBoundaryEvidence.from_dict(item)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProspectiveWeeklyDrawdown5mExitError(
                "funding evidence is invalid"
            ) from exc
        key = (evidence.market, evidence.boundary_ms)
        if key in output:
            raise ProspectiveWeeklyDrawdown5mExitError(
                "duplicate funding evidence"
            )
        output[key] = evidence
    return output


def prospective_weekly_drawdown_5m_exit_summary(
    source: object,
) -> dict[str, object]:
    rows, config, state = _validate_source(source)
    results: list[dict[str, object]] = []
    risk_rejections: Counter[str] = Counter()
    planning_rejections: Counter[str] = Counter()
    entry_execution_results: Counter[str] = Counter()
    exit_execution_results: Counter[str] = Counter()

    for row in rows:
        opportunity_id = cast(str, row["opportunity_id"])
        try:
            evidence = ContinuousPaperOpeningOpportunityEvidence.from_dict(
                row.get("opportunity")
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProspectiveWeeklyDrawdown5mExitError(
                "opening opportunity evidence is invalid"
            ) from exc
        if evidence.opportunity_id != opportunity_id:
            raise ProspectiveWeeklyDrawdown5mExitError(
                "opening opportunity id mismatch"
            )
        if (
            evidence.opportunity_timestamp_ms < state.started_at_ms
            or evidence.baseline_risk_approved
            or evidence.baseline_risk_reason_codes
            != (WEEKLY_DRAWDOWN_REASON,)
        ):
            raise ProspectiveWeeklyDrawdown5mExitError(
                "opening opportunity candidate lineage mismatch"
            )

        lineage = row.get("lineage")
        if (
            not isinstance(lineage, dict)
            or lineage.get("stack_decision") != "ADMIT"
            or lineage.get("block_layer") != "none"
        ):
            raise ProspectiveWeeklyDrawdown5mExitError(
                "full-stack candidate lineage mismatch"
            )

        raw_stop_path = row.get("stop_path")
        if not isinstance(raw_stop_path, dict):
            raise ProspectiveWeeklyDrawdown5mExitError(
                "five-minute stop-path evidence is missing"
            )
        stop_status = raw_stop_path.get("status")
        if not isinstance(stop_status, str):
            raise ProspectiveWeeklyDrawdown5mExitError(
                "five-minute stop-path status is invalid"
            )
        if raw_stop_path.get("claim_scope") != (
            "observed_mark_stop_crossing_only"
        ):
            raise ProspectiveWeeklyDrawdown5mExitError(
                "five-minute stop-path claim scope drift"
            )

        _execution_config_compatible(evidence, config)
        adjusted_request = _neutralize_weekly_drawdown(evidence)
        risk = evaluate_risk(adjusted_request)
        result: dict[str, object] = {
            "opportunity_id": opportunity_id,
            "timestamp_ms": evidence.opportunity_timestamp_ms,
            "market": evidence.market,
            "direction": evidence.direction,
            "counterfactual_risk_approved": risk.approved,
            "counterfactual_risk_reason_codes": list(risk.reason_codes),
            "planning_approved": False,
            "planning_rejection": None,
            "entry_execution_result": None,
            "entry_filled_quantity": None,
            "entry_average_fill_price": None,
            "entry_fee": None,
            "stop_path_status": stop_status,
            "stop_path_observed_mark_count": raw_stop_path.get(
                "observed_mark_count"
            ),
            "stop_path_stop_crossed": raw_stop_path.get("stop_crossed"),
            "stop_path_survived_to_5m": raw_stop_path.get(
                "survived_observed_marks_to_horizon"
            ),
            "exit_execution_result": None,
            "complete_close": False,
            "gross_realized_pnl": None,
            "exit_fee": None,
            "funding_boundary_count": None,
            "funding_evidence_count": None,
            "funding_cash_pnl": None,
            "exact_realized_pnl": None,
            "exact_realized_return_fraction": None,
            "incomplete_reason": None,
        }
        if not risk.approved:
            reason = risk.reason_codes[0] if risk.reason_codes else "unknown"
            risk_rejections[reason] += 1
            result["incomplete_reason"] = "counterfactual_risk_rejected"
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
            planning_rejections[plan.reason] += 1
            result["planning_rejection"] = plan.reason
            result["incomplete_reason"] = "entry_planning_rejected"
            results.append(result)
            continue
        result["planning_approved"] = True

        entry_simulation = simulate_ioc(
            plan,
            evidence.book_event,
            evidence.instrument_object,
            config,
            attempt_timestamp_ms=adjusted_request.timestamp_ms,
        )
        entry_attempt = entry_simulation.attempt
        result["entry_execution_result"] = entry_attempt.result.value
        entry_execution_results[entry_attempt.result.value] += 1
        if not entry_simulation.fills:
            result["incomplete_reason"] = "entry_not_filled"
            results.append(result)
            continue
        if entry_attempt.average_fill_price is None:
            raise ProspectiveWeeklyDrawdown5mExitError(
                "entry fill is missing average price"
            )
        if plan.stop_price is None or plan.cost_buffer_fraction is None:
            raise ProspectiveWeeklyDrawdown5mExitError(
                "opening plan risk geometry is incomplete"
            )

        quantity = entry_attempt.filled_quantity
        entry_price = entry_attempt.average_fill_price
        entry_fee = entry_attempt.fee
        opened_at_ms = max(fill.timestamp_ms for fill in entry_simulation.fills)
        side = (
            PositionSide.LONG
            if evidence.direction == "long"
            else PositionSide.SHORT
        )
        position = PaperPosition(
            market=evidence.instrument_object.market,
            side=side,
            quantity=quantity,
            average_entry_price=entry_price,
            stop_price=plan.stop_price,
            opening_plan_id=plan.plan_id,
            opened_at_ms=opened_at_ms,
            updated_at_ms=opened_at_ms,
            initial_risk_decision_id=plan.risk_decision_id,
            correlation_bucket=adjusted_request.correlation_bucket,
            cost_buffer_fraction=plan.cost_buffer_fraction,
            planned_risk=(
                ZERO
                if plan.approved_risk_amount_ceiling is None
                else plan.approved_risk_amount_ceiling
            ),
            cumulative_fees=entry_fee,
            venue_max_leverage=evidence.instrument_object.venue_max_leverage,
            latest_mark=entry_price,
        )
        result["entry_filled_quantity"] = str(quantity)
        result["entry_average_fill_price"] = str(entry_price)
        result["entry_fee"] = str(entry_fee)

        if stop_status == "observed_stop_crossing":
            result["incomplete_reason"] = (
                "observed_stop_crossing_before_5m"
            )
            results.append(result)
            continue
        if stop_status != "observed_path_survivor":
            result["incomplete_reason"] = "stop_path_not_evaluable"
            results.append(result)
            continue
        if (
            raw_stop_path.get("stop_crossed") is not False
            or raw_stop_path.get(
                "survived_observed_marks_to_horizon"
            )
            is not True
        ):
            raise ProspectiveWeeklyDrawdown5mExitError(
                "observed stop survivor flags are inconsistent"
            )

        raw_exit = row.get("exit_book")
        if raw_exit is None:
            result["incomplete_reason"] = "missing_exit_book"
            results.append(result)
            continue
        try:
            exit_evidence = OpeningOpportunityExitBookEvidence.from_dict(
                raw_exit
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProspectiveWeeklyDrawdown5mExitError(
                "five-minute exit book evidence is invalid"
            ) from exc
        if (
            exit_evidence.opportunity_id != opportunity_id
            or exit_evidence.market != evidence.market
            or exit_evidence.direction != evidence.direction
            or exit_evidence.opportunity_timestamp_ms
            != evidence.opportunity_timestamp_ms
            or exit_evidence.horizon_ms != EXIT_HORIZON_MS
        ):
            raise ProspectiveWeeklyDrawdown5mExitError(
                "five-minute exit book lineage mismatch"
            )

        reference_price = _best_reference(exit_evidence, side)
        action = PositionAction(
            action_type=PositionActionType.EXIT_THESIS,
            market=position.market,
            quantity=position.quantity,
            new_stop_price=None,
            reason_codes=("weekly_drawdown_fixed_5m_exit",),
            timestamp_ms=exit_evidence.observed_at_ms,
        )
        exit_plan = plan_reduce_only_order(
            position,
            action,
            exit_evidence.instrument,
            config,
            originating_risk_decision_id=plan.risk_decision_id,
            originating_strategy_decision_id=plan.strategy_decision_id,
            reference_price=reference_price,
            created_at_ms=exit_evidence.observed_at_ms,
        )
        if isinstance(exit_plan, PlanningRejection):
            result["incomplete_reason"] = "exit_planning_rejected"
            results.append(result)
            continue

        exit_simulation = simulate_ioc(
            exit_plan,
            exit_evidence.book_event,
            exit_evidence.instrument,
            config,
            attempt_timestamp_ms=(
                exit_evidence.observed_at_ms + config.latency_ms
            ),
        )
        exit_attempt = exit_simulation.attempt
        result["exit_execution_result"] = exit_attempt.result.value
        exit_execution_results[exit_attempt.result.value] += 1
        if not exit_simulation.fills:
            result["incomplete_reason"] = "five_minute_exit_not_filled"
            results.append(result)
            continue

        gross = sum(
            (
                _gross_pnl(
                    side=side,
                    entry_price=entry_price,
                    exit_price=fill.price,
                    quantity=fill.quantity,
                )
                for fill in exit_simulation.fills
            ),
            ZERO,
        )
        complete_close = exit_attempt.filled_quantity == quantity
        result["complete_close"] = complete_close
        result["gross_realized_pnl"] = str(gross)
        result["exit_fee"] = str(exit_attempt.fee)
        if not complete_close:
            result["incomplete_reason"] = "position_not_fully_closed"
            results.append(result)
            continue

        boundaries = _funding_boundaries(
            opened_at_ms=opened_at_ms,
            closed_at_ms=exit_attempt.attempt_timestamp_ms,
        )
        funding = _funding_index(row.get("funding_evidence"))
        missing_boundaries = tuple(
            boundary
            for boundary in boundaries
            if (evidence.market, boundary) not in funding
        )
        result["funding_boundary_count"] = len(boundaries)
        result["funding_evidence_count"] = (
            len(boundaries) - len(missing_boundaries)
        )
        if missing_boundaries:
            result["incomplete_reason"] = "funding_evidence_required"
            results.append(result)
            continue

        signed_quantity = (
            quantity if side is PositionSide.LONG else -quantity
        )
        funding_cash = sum(
            (
                funding_cash_delta(
                    signed_quantity,
                    funding[(evidence.market, boundary)].oracle_px,
                    funding[(evidence.market, boundary)].funding_rate,
                )
                for boundary in boundaries
            ),
            ZERO,
        )
        exact_pnl = gross - entry_fee - exit_attempt.fee + funding_cash
        result["funding_cash_pnl"] = str(funding_cash)
        result["exact_realized_pnl"] = str(exact_pnl)
        result["exact_realized_return_fraction"] = str(
            exact_pnl / (entry_price * quantity)
        )
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
    exact_pnls = tuple(
        Decimal(cast(str, item["exact_realized_pnl"]))
        for item in result_tuple
        if item["exact_realized_pnl"] is not None
    )
    gross_profit = sum(
        (value for value in exact_pnls if value > ZERO),
        ZERO,
    )
    gross_loss_abs = -sum(
        (value for value in exact_pnls if value < ZERO),
        ZERO,
    )
    config_payload = execution_config_payload(config)

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "candidate_id": CANDIDATE_ID,
        "started_at_ms": state.started_at_ms,
        "exit_horizon_ms": EXIT_HORIZON_MS,
        "baseline_risk_reason": WEEKLY_DRAWDOWN_REASON,
        "discovery_cohort_reused_for_validation": False,
        "cross_horizon_selection_frozen": True,
        "execution_config": config_payload,
        "execution_config_sha256": _sha256(config_payload),
        "entry_execution_model": (
            "captured_request_plus_decision_time_visible_book_ioc"
        ),
        "exit_execution_model": (
            "captured_real_l2_reduce_only_ioc_at_fixed_5m"
        ),
        "funding_model": "exact_captured_hourly_boundaries",
        "claim_scope": (
            "observed_stop_survivor_exact_5m_entry_exit_funding_pnl"
        ),
        "observed_stop_path_claim_scope": (
            "observed_mark_stop_crossing_only"
        ),
        "unseen_intraperiod_stop_path_complete": False,
        "portfolio_counterfactual_complete": False,
        "source_opportunities": len(rows),
        "observed_stop_survivor_options": sum(
            item["stop_path_status"] == "observed_path_survivor"
            for item in result_tuple
        ),
        "observed_stop_crossing_options": sum(
            item["stop_path_status"] == "observed_stop_crossing"
            for item in result_tuple
        ),
        "observed_stop_path_incomplete_options": sum(
            item["stop_path_status"]
            not in {"observed_path_survivor", "observed_stop_crossing"}
            for item in result_tuple
        ),
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
        "entry_execution_results": dict(
            sorted(entry_execution_results.items())
        ),
        "exit_execution_results": dict(
            sorted(exit_execution_results.items())
        ),
        "entry_fills": sum(
            item["entry_filled_quantity"] is not None
            for item in result_tuple
        ),
        "complete_five_minute_exits": sum(
            item["complete_close"] is True
            for item in result_tuple
        ),
        "exact_realized_pnl_options": len(exact_pnls),
        "wins": sum(value > ZERO for value in exact_pnls),
        "losses": sum(value < ZERO for value in exact_pnls),
        "breakeven": sum(value == ZERO for value in exact_pnls),
        "gross_profit": str(gross_profit),
        "gross_loss_abs": str(gross_loss_abs),
        "profit_factor": (
            None
            if gross_loss_abs == ZERO
            else str(gross_profit / gross_loss_abs)
        ),
        "total_exact_realized_pnl": str(sum(exact_pnls, ZERO)),
        "mean_exact_realized_pnl": (
            None
            if not exact_pnls
            else str(
                sum(exact_pnls, ZERO) / Decimal(len(exact_pnls))
            )
        ),
        "option_results": list(result_tuple),
    }
