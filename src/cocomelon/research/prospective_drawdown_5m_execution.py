from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import replace
from decimal import Decimal
from typing import Final, cast

from cocomelon.domain.execution import (
    PaperExecutionConfig,
    PositionAction,
    PositionActionType,
)
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
from cocomelon.research.prospective_drawdown_5m_execution_source import (
    CANDIDATE_ID,
    EXIT_HORIZON_MS,
    SOURCE_KIND,
    SOURCE_SCHEMA_VERSION,
    WEEKLY_DRAWDOWN_REASON,
    execution_config_payload,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow import (
    _execution_config_compatible,
    _execution_config_from_payload,
)
from cocomelon.risk.engine import evaluate_risk

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
MIN_EXACT_OPTIONS_FOR_REVIEW: Final = 30
MIN_MARKETS_FOR_REVIEW: Final = 4
MIN_DIRECTION_OPTIONS_FOR_REVIEW: Final = 5
TEMPORAL_BLOCKS: Final = 4
MIN_OPTIONS_PER_FULL_BLOCK: Final = 5


class ProspectiveDrawdown5mExecutionError(RuntimeError):
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


def _neutralize_weekly_drawdown(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> object:
    request = evidence.risk_request_object
    baseline = evaluate_risk(request)
    if (
        baseline.approved
        or baseline.reason_codes != (WEEKLY_DRAWDOWN_REASON,)
    ):
        raise ProspectiveDrawdown5mExecutionError(
            "baseline request is not weekly-drawdown-only"
        )
    account = request.account_state
    peak = account.rolling_7d_peak_equity
    if peak <= ZERO or account.equity <= ZERO or peak < account.equity:
        raise ProspectiveDrawdown5mExecutionError(
            "weekly drawdown state is invalid"
        )
    return replace(
        request,
        account_state=replace(
            account,
            rolling_7d_peak_equity=account.equity,
        ),
    )


def _funding_boundaries(
    *,
    opened_at_ms: int,
    closed_at_ms: int,
) -> tuple[int, ...]:
    if opened_at_ms < 0 or closed_at_ms < opened_at_ms:
        raise ProspectiveDrawdown5mExecutionError(
            "execution timestamps are invalid"
        )
    first = (
        (opened_at_ms // FUNDING_INTERVAL_MS) + 1
    ) * FUNDING_INTERVAL_MS
    if first > closed_at_ms:
        return ()
    return tuple(
        range(first, closed_at_ms + 1, FUNDING_INTERVAL_MS)
    )


def _best_exit_reference(
    evidence: OpeningOpportunityExitBookEvidence,
    side: PositionSide,
) -> Decimal:
    raw = (
        evidence.book_event.payload.get("bids")
        if side is PositionSide.LONG
        else evidence.book_event.payload.get("asks")
    )
    if not isinstance(raw, (tuple, list)) or not raw:
        raise ProspectiveDrawdown5mExecutionError(
            "5m exit book side is empty"
        )
    prices: list[Decimal] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ProspectiveDrawdown5mExecutionError(
                "5m exit book level is invalid"
            )
        try:
            price = Decimal(str(item.get("px")))
        except (ValueError, ArithmeticError) as exc:
            raise ProspectiveDrawdown5mExecutionError(
                "5m exit price is invalid"
            ) from exc
        if not price.is_finite() or price <= ZERO:
            raise ProspectiveDrawdown5mExecutionError(
                "5m exit price is invalid"
            )
        prices.append(price)
    return (
        max(prices)
        if side is PositionSide.LONG
        else min(prices)
    )


def _gross_pnl(
    *,
    side: PositionSide,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    return (
        (exit_price - entry_price) * quantity
        if side is PositionSide.LONG
        else (entry_price - exit_price) * quantity
    )


def _validate_source(
    raw: object,
) -> tuple[
    tuple[dict[str, object], ...],
    dict[tuple[str, int], ReplacementFundingBoundaryEvidence],
    PaperExecutionConfig,
]:
    if not isinstance(raw, dict):
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m source must be an object"
        )
    if raw.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m source schema is unsupported"
        )
    if raw.get("kind") != SOURCE_KIND:
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m source kind is unsupported"
        )
    if raw.get("candidate_id") != CANDIDATE_ID:
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m candidate drift"
        )
    if raw.get("exit_horizon_ms") != EXIT_HORIZON_MS:
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m exit horizon drift"
        )
    if raw.get("baseline_risk_reason") != WEEKLY_DRAWDOWN_REASON:
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m risk reason drift"
        )
    for key, expected in (
        ("research_only", True),
        ("execution_authority", False),
        ("promotion_authority", False),
        ("changes_execution", False),
        ("changes_risk_limits", False),
        ("changes_candidate_readiness", False),
        ("discovery_cohort_reused_for_validation", False),
    ):
        if raw.get(key) is not expected:
            raise ProspectiveDrawdown5mExecutionError(
                f"drawdown 5m source authority drift: {key}"
            )

    source_sha = raw.get("source_sha256")
    if not isinstance(source_sha, str) or len(source_sha) != 64:
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m source digest is invalid"
        )
    digest_payload = {
        key: value
        for key, value in raw.items()
        if key != "source_sha256"
    }
    if _sha256(digest_payload) != source_sha:
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m source digest mismatch"
        )

    config_payload = raw.get("execution_config")
    config_sha = raw.get("execution_config_sha256")
    if (
        not isinstance(config_sha, str)
        or len(config_sha) != 64
        or _sha256(config_payload) != config_sha
    ):
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m execution config digest mismatch"
        )
    try:
        config = _execution_config_from_payload(config_payload)
    except Exception as exc:
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m execution config is invalid"
        ) from exc

    raw_rows = raw.get("opportunities")
    if not isinstance(raw_rows, list):
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m opportunities must be an array"
        )
    if raw.get("source_opportunity_count") != len(raw_rows):
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m source opportunity count mismatch"
        )
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in raw_rows:
        if not isinstance(item, dict):
            raise ProspectiveDrawdown5mExecutionError(
                "drawdown 5m opportunity row is invalid"
            )
        opportunity_id = item.get("opportunity_id")
        if not isinstance(opportunity_id, str) or not opportunity_id:
            raise ProspectiveDrawdown5mExecutionError(
                "drawdown 5m opportunity id is invalid"
            )
        if opportunity_id in seen:
            raise ProspectiveDrawdown5mExecutionError(
                "duplicate drawdown 5m opportunity id"
            )
        seen.add(opportunity_id)
        rows.append(item)

    raw_funding = raw.get("funding_evidence")
    if not isinstance(raw_funding, list):
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m funding evidence must be an array"
        )
    if raw.get("funding_evidence_count") != len(raw_funding):
        raise ProspectiveDrawdown5mExecutionError(
            "drawdown 5m funding count mismatch"
        )
    funding: dict[
        tuple[str, int],
        ReplacementFundingBoundaryEvidence,
    ] = {}
    for item in raw_funding:
        evidence = ReplacementFundingBoundaryEvidence.from_dict(item)
        key = (evidence.market, evidence.boundary_ms)
        if key in funding:
            raise ProspectiveDrawdown5mExecutionError(
                "duplicate drawdown 5m funding evidence"
            )
        funding[key] = evidence

    return tuple(rows), funding, config


def _temporal_summary(
    exact: tuple[tuple[str, str, str, int, Decimal], ...],
) -> dict[str, object]:
    ordered = tuple(
        sorted(exact, key=lambda item: (item[3], item[0]))
    )
    quotient, remainder = divmod(len(ordered), TEMPORAL_BLOCKS)
    blocks: list[dict[str, object]] = []
    start = 0
    for index in range(TEMPORAL_BLOCKS):
        count = quotient + (1 if index < remainder else 0)
        stop = start + count
        block = ordered[start:stop]
        start = stop
        if not block:
            continue
        pnl = sum((item[4] for item in block), ZERO)
        blocks.append(
            {
                "block": index + 1,
                "options": len(block),
                "first_timestamp_ms": block[0][3],
                "last_timestamp_ms": block[-1][3],
                "exact_realized_pnl": str(pnl),
                "positive_pnl": pnl > ZERO,
                "full_block": len(block) >= MIN_OPTIONS_PER_FULL_BLOCK,
            }
        )
    full_blocks = tuple(
        block for block in blocks if block["full_block"] is True
    )
    return {
        "configured_blocks": TEMPORAL_BLOCKS,
        "minimum_options_per_full_block": MIN_OPTIONS_PER_FULL_BLOCK,
        "blocks": blocks,
        "full_blocks": len(full_blocks),
        "positive_full_blocks": sum(
            block["positive_pnl"] is True for block in full_blocks
        ),
        "all_full_blocks_positive": (
            len(full_blocks) == TEMPORAL_BLOCKS
            and all(block["positive_pnl"] is True for block in full_blocks)
        ),
    }


def _readiness(
    exact: tuple[tuple[str, str, str, int, Decimal], ...],
) -> dict[str, object]:
    total = sum((item[4] for item in exact), ZERO)
    positive = tuple(item[4] for item in exact if item[4] > ZERO)
    negative = tuple(item[4] for item in exact if item[4] < ZERO)
    gross_profit = sum(positive, ZERO)
    gross_loss_abs = sum((-value for value in negative), ZERO)
    profit_factor = (
        None
        if gross_loss_abs == ZERO
        else gross_profit / gross_loss_abs
    )
    profit_factor_above_one = (
        (
            profit_factor is not None
            and profit_factor > ONE
        )
        or (
            profit_factor is None
            and gross_profit > ZERO
            and gross_loss_abs == ZERO
        )
    )
    leave_option = tuple(total - item[4] for item in exact)
    by_market: dict[str, Decimal] = defaultdict(lambda: ZERO)
    direction_counts: Counter[str] = Counter()
    for _option_id, market, direction, _timestamp, pnl in exact:
        by_market[market] += pnl
        direction_counts[direction] += 1
    leave_market = tuple(total - value for value in by_market.values())
    temporal = _temporal_summary(exact)
    option_robust = (
        len(leave_option) >= 2 and min(leave_option) > ZERO
    )
    market_robust = (
        len(leave_market) >= 2 and min(leave_market) > ZERO
    )
    checks = {
        "minimum_exact_options": (
            len(exact) >= MIN_EXACT_OPTIONS_FOR_REVIEW
        ),
        "minimum_markets": len(by_market) >= MIN_MARKETS_FOR_REVIEW,
        "minimum_long_options": (
            direction_counts["long"]
            >= MIN_DIRECTION_OPTIONS_FOR_REVIEW
        ),
        "minimum_short_options": (
            direction_counts["short"]
            >= MIN_DIRECTION_OPTIONS_FOR_REVIEW
        ),
        "positive_total_exact_pnl": total > ZERO,
        "profit_factor_above_one": profit_factor_above_one,
        "positive_after_any_single_option_removed": option_robust,
        "positive_after_any_single_market_removed": market_robust,
        "all_four_full_chronological_blocks_positive": (
            temporal["all_full_blocks_positive"] is True
        ),
    }
    return {
        "ready_for_review": all(checks.values()),
        "failed_requirements": [
            name for name, passed in checks.items() if not passed
        ],
        "missing_exact_options": max(
            0,
            MIN_EXACT_OPTIONS_FOR_REVIEW - len(exact),
        ),
        "minimum_exact_options": MIN_EXACT_OPTIONS_FOR_REVIEW,
        "market_count": len(by_market),
        "minimum_markets": MIN_MARKETS_FOR_REVIEW,
        "long_exact_options": direction_counts["long"],
        "short_exact_options": direction_counts["short"],
        "minimum_options_per_direction": (
            MIN_DIRECTION_OPTIONS_FOR_REVIEW
        ),
        "total_exact_realized_pnl": str(total),
        "gross_profit": str(gross_profit),
        "gross_loss_abs": str(gross_loss_abs),
        "profit_factor": (
            None if profit_factor is None else str(profit_factor)
        ),
        "leave_one_option_out_min_pnl": (
            None if not leave_option else str(min(leave_option))
        ),
        "positive_after_any_single_option_removed": option_robust,
        "leave_one_market_out_min_pnl": (
            None if not leave_market else str(min(leave_market))
        ),
        "positive_after_any_single_market_removed": market_robust,
        "temporal": temporal,
    }


def prospective_drawdown_5m_execution_summary(
    source: object,
) -> dict[str, object]:
    rows, funding, config = _validate_source(source)
    results: list[dict[str, object]] = []
    risk_rejections: Counter[str] = Counter()
    entry_results: Counter[str] = Counter()
    exit_results: Counter[str] = Counter()
    incomplete_reasons: Counter[str] = Counter()

    for row in rows:
        opportunity_id = cast(str, row["opportunity_id"])
        lineage = row.get("lineage")
        if not isinstance(lineage, dict):
            raise ProspectiveDrawdown5mExecutionError(
                "drawdown 5m lineage is invalid"
            )
        if (
            lineage.get("stack_decision") != "ADMIT"
            or lineage.get("block_layer") != "none"
            or lineage.get("baseline_risk_reason_codes")
            != [WEEKLY_DRAWDOWN_REASON]
        ):
            raise ProspectiveDrawdown5mExecutionError(
                "drawdown 5m stack lineage drift"
            )

        try:
            evidence = ContinuousPaperOpeningOpportunityEvidence.from_dict(
                row.get("opportunity")
            )
        except Exception as exc:
            raise ProspectiveDrawdown5mExecutionError(
                "drawdown 5m opening evidence is invalid"
            ) from exc
        if (
            evidence.opportunity_id != opportunity_id
            or evidence.opportunity_timestamp_ms
            != lineage.get("timestamp_ms")
            or evidence.market != lineage.get("market")
            or evidence.direction != lineage.get("direction")
            or evidence.lead_strategy != lineage.get("lead_strategy")
            or evidence.baseline_risk_approved
            or evidence.baseline_risk_reason_codes
            != (WEEKLY_DRAWDOWN_REASON,)
        ):
            raise ProspectiveDrawdown5mExecutionError(
                "drawdown 5m opening lineage mismatch"
            )
        try:
            _execution_config_compatible(evidence, config)
        except Exception as exc:
            raise ProspectiveDrawdown5mExecutionError(
                "drawdown 5m execution envelope drift"
            ) from exc

        adjusted_request = _neutralize_weekly_drawdown(evidence)
        risk = evaluate_risk(adjusted_request)
        result: dict[str, object] = {
            "opportunity_id": opportunity_id,
            "timestamp_ms": evidence.opportunity_timestamp_ms,
            "market": evidence.market,
            "direction": evidence.direction,
            "lead_strategy": evidence.lead_strategy,
            "counterfactual_risk_approved": risk.approved,
            "counterfactual_risk_reason_codes": list(risk.reason_codes),
            "entry_planning_approved": False,
            "entry_execution_result": None,
            "entry_fee": None,
            "exit_execution_result": None,
            "exit_fee": None,
            "funding_boundary_count": None,
            "funding_evidence_count": 0,
            "funding_cash_pnl": None,
            "complete_close": False,
            "exact_realized_pnl": None,
            "status": "incomplete",
            "incomplete_reason": None,
        }
        if not risk.approved:
            reason = (
                risk.reason_codes[0]
                if risk.reason_codes
                else "unknown_risk_rejection"
            )
            risk_rejections[reason] += 1
            result["incomplete_reason"] = reason
            incomplete_reasons[reason] += 1
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
            result["incomplete_reason"] = (
                f"entry_planning:{plan.reason}"
            )
            incomplete_reasons[
                cast(str, result["incomplete_reason"])
            ] += 1
            results.append(result)
            continue
        result["entry_planning_approved"] = True

        entry_simulation = simulate_ioc(
            plan,
            evidence.book_event,
            evidence.instrument_object,
            config,
            attempt_timestamp_ms=adjusted_request.timestamp_ms,
        )
        entry_attempt = entry_simulation.attempt
        result["entry_execution_result"] = entry_attempt.result.value
        entry_results[entry_attempt.result.value] += 1
        if (
            not entry_simulation.fills
            or entry_attempt.average_fill_price is None
            or entry_attempt.filled_quantity <= ZERO
        ):
            result["incomplete_reason"] = "entry_no_fill"
            incomplete_reasons["entry_no_fill"] += 1
            results.append(result)
            continue

        entry_price = entry_attempt.average_fill_price
        quantity = entry_attempt.filled_quantity
        entry_fee = entry_attempt.fee
        result["entry_fee"] = str(entry_fee)

        raw_exit = row.get("exit_book")
        if raw_exit is None:
            result["incomplete_reason"] = "missing_exit_book"
            incomplete_reasons["missing_exit_book"] += 1
            results.append(result)
            continue
        try:
            exit_book = OpeningOpportunityExitBookEvidence.from_dict(
                raw_exit
            )
        except Exception as exc:
            raise ProspectiveDrawdown5mExecutionError(
                "drawdown 5m exit book is invalid"
            ) from exc
        if (
            exit_book.opportunity_id != opportunity_id
            or exit_book.market != evidence.market
            or exit_book.direction != evidence.direction
            or exit_book.opportunity_timestamp_ms
            != evidence.opportunity_timestamp_ms
            or exit_book.horizon_ms != EXIT_HORIZON_MS
        ):
            raise ProspectiveDrawdown5mExecutionError(
                "drawdown 5m exit book lineage mismatch"
            )

        side = (
            PositionSide.LONG
            if evidence.direction == "long"
            else PositionSide.SHORT
        )
        if plan.stop_price is None:
            raise ProspectiveDrawdown5mExecutionError(
                "drawdown 5m opening plan stop is missing"
            )
        position = PaperPosition(
            market=plan.market,
            side=side,
            quantity=quantity,
            average_entry_price=entry_price,
            stop_price=plan.stop_price,
            opening_plan_id=plan.plan_id,
            opened_at_ms=entry_attempt.attempt_timestamp_ms,
            updated_at_ms=entry_attempt.attempt_timestamp_ms,
            initial_risk_decision_id=risk.risk_decision_id,
            correlation_bucket=adjusted_request.correlation_bucket,
            cost_buffer_fraction=(
                ZERO
                if plan.cost_buffer_fraction is None
                else plan.cost_buffer_fraction
            ),
            planned_risk=risk.approved_risk_amount,
            cumulative_fees=entry_fee,
            venue_max_leverage=(
                evidence.instrument_object.venue_max_leverage
            ),
            latest_mark=entry_price,
        )
        action = PositionAction(
            action_type=PositionActionType.EXIT_THESIS,
            market=position.market,
            quantity=position.quantity,
            new_stop_price=None,
            reason_codes=("drawdown_fixed_5m_exit",),
            timestamp_ms=exit_book.observed_at_ms,
        )
        reference = _best_exit_reference(exit_book, side)
        exit_plan = plan_reduce_only_order(
            position,
            action,
            exit_book.instrument,
            config,
            originating_risk_decision_id=risk.risk_decision_id,
            originating_strategy_decision_id=(
                adjusted_request.strategy_decision.decision_id
            ),
            reference_price=reference,
            created_at_ms=exit_book.observed_at_ms,
        )
        if isinstance(exit_plan, PlanningRejection):
            reason = f"exit_planning:{exit_plan.reason}"
            result["incomplete_reason"] = reason
            incomplete_reasons[reason] += 1
            results.append(result)
            continue

        exit_simulation = simulate_ioc(
            exit_plan,
            exit_book.book_event,
            exit_book.instrument,
            config,
            attempt_timestamp_ms=(
                exit_book.observed_at_ms + config.latency_ms
            ),
        )
        exit_attempt = exit_simulation.attempt
        result["exit_execution_result"] = exit_attempt.result.value
        result["exit_fee"] = str(exit_attempt.fee)
        exit_results[exit_attempt.result.value] += 1
        complete_close = (
            exit_attempt.filled_quantity == quantity
            and exit_attempt.unfilled_quantity == ZERO
        )
        result["complete_close"] = complete_close
        if not complete_close:
            reason = (
                "exit_no_fill"
                if exit_attempt.filled_quantity == ZERO
                else "exit_partial_fill"
            )
            result["incomplete_reason"] = reason
            incomplete_reasons[reason] += 1
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
        boundaries = _funding_boundaries(
            opened_at_ms=entry_attempt.attempt_timestamp_ms,
            closed_at_ms=exit_attempt.attempt_timestamp_ms,
        )
        result["funding_boundary_count"] = len(boundaries)
        funding_cash = ZERO
        missing_boundaries: list[int] = []
        signed_quantity = (
            quantity if side is PositionSide.LONG else -quantity
        )
        for boundary_ms in boundaries:
            item = funding.get((evidence.market, boundary_ms))
            if item is None:
                missing_boundaries.append(boundary_ms)
                continue
            funding_cash += funding_cash_delta(
                signed_quantity,
                item.oracle_px,
                item.funding_rate,
            )
        result["funding_evidence_count"] = (
            len(boundaries) - len(missing_boundaries)
        )
        if missing_boundaries:
            result["incomplete_reason"] = "funding_evidence_required"
            result["missing_funding_boundaries_ms"] = (
                missing_boundaries
            )
            incomplete_reasons["funding_evidence_required"] += 1
            results.append(result)
            continue

        exact_pnl = gross - entry_fee - exit_attempt.fee + funding_cash
        result["funding_cash_pnl"] = str(funding_cash)
        result["gross_realized_pnl"] = str(gross)
        result["exact_realized_pnl"] = str(exact_pnl)
        result["status"] = "exact"
        result["incomplete_reason"] = None
        results.append(result)

    result_tuple = tuple(
        sorted(
            results,
            key=lambda item: (
                cast(int, item["timestamp_ms"]),
                cast(str, item["opportunity_id"]),
            ),
        )
    )
    exact = tuple(
        (
            cast(str, item["opportunity_id"]),
            cast(str, item["market"]),
            cast(str, item["direction"]),
            cast(int, item["timestamp_ms"]),
            Decimal(cast(str, item["exact_realized_pnl"])),
        )
        for item in result_tuple
        if item["status"] == "exact"
        and isinstance(item["exact_realized_pnl"], str)
    )
    readiness = _readiness(exact)
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "candidate_id": CANDIDATE_ID,
        "baseline_risk_reason": WEEKLY_DRAWDOWN_REASON,
        "exit_horizon_ms": EXIT_HORIZON_MS,
        "execution_config": execution_config_payload(config),
        "source_opportunities": len(rows),
        "counterfactual_risk_approvals": sum(
            item["counterfactual_risk_approved"] is True
            for item in result_tuple
        ),
        "counterfactual_risk_rejections": dict(
            sorted(risk_rejections.items())
        ),
        "entry_fillable_opportunities": sum(
            item["entry_fee"] is not None for item in result_tuple
        ),
        "entry_execution_results": dict(sorted(entry_results.items())),
        "exit_execution_results": dict(sorted(exit_results.items())),
        "exact_realized_pnl_options": len(exact),
        "incomplete_options": len(result_tuple) - len(exact),
        "incomplete_reason_counts": dict(
            sorted(incomplete_reasons.items())
        ),
        "option_results": list(result_tuple),
        "entry_fees_modeled": True,
        "exit_fees_modeled": True,
        "funding_modeled": True,
        "fixed_horizon_only": True,
        "portfolio_counterfactual_complete": False,
        **readiness,
    }
