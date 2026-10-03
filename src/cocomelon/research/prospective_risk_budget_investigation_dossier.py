from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Final, cast

from cocomelon.research.prospective_risk_rejected_forward_markout_ledger import (
    validate_risk_rejected_forward_markout_ledger,
)
from cocomelon.research.prospective_risk_rejected_stop_path_ledger import (
    validate_risk_rejected_stop_path_ledger,
)

DOSSIER_SCHEMA_VERSION: Final = 1
DOSSIER_KIND: Final = "prospective-risk-budget-investigation-dossier-v1"
WEEKLY_DRAWDOWN_5M_CANDIDATE_ID: Final = (
    "prospective-weekly-drawdown-stack-admit-5m-v1"
)
WEEKLY_DRAWDOWN_5M_FROZEN_AT_MS: Final = 1_791_057_218_000
WEEKLY_DRAWDOWN_5M_HORIZON_MS: Final = 300_000
WEEKLY_DRAWDOWN_REASON: Final = "weekly_drawdown_lockout"
WEEKLY_DRAWDOWN_5M_REVIEW_ROWS: Final = 20
WEEKLY_DRAWDOWN_5M_MIN_MARKETS: Final = 5
WEEKLY_DRAWDOWN_5M_MIN_LONG: Final = 5
WEEKLY_DRAWDOWN_5M_MIN_SHORT: Final = 5
ZERO: Final = Decimal("0")


class RiskBudgetInvestigationDossierError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_payload(payload: dict[str, object]) -> str:
    stripped = {
        key: value
        for key, value in payload.items()
        if key != "report_sha256"
    }
    return hashlib.sha256(
        _canonical_json(stripped).encode("utf-8")
    ).hexdigest()


def _latest_source_identity(
    ledger: dict[str, object],
    *,
    label: str,
) -> dict[str, object]:
    history = ledger.get("source_history")
    if not isinstance(history, list) or not history:
        raise RiskBudgetInvestigationDossierError(
            f"{label} source history is empty"
        )
    raw = history[-1]
    if not isinstance(raw, dict):
        raise RiskBudgetInvestigationDossierError(
            f"{label} latest source history entry is invalid"
        )
    run_id = raw.get("paper_run_id")
    attempt = raw.get("paper_run_attempt")
    artifact_name = raw.get("artifact_name")
    artifact_digest = raw.get("artifact_digest")
    if (
        isinstance(run_id, bool)
        or not isinstance(run_id, int)
        or run_id <= 0
        or isinstance(attempt, bool)
        or not isinstance(attempt, int)
        or attempt <= 0
        or not isinstance(artifact_name, str)
        or not artifact_name.strip()
        or not isinstance(artifact_digest, str)
        or not artifact_digest.startswith("sha256:")
    ):
        raise RiskBudgetInvestigationDossierError(
            f"{label} latest source identity is invalid"
        )
    return {
        "paper_run_id": run_id,
        "paper_run_attempt": attempt,
        "artifact_name": artifact_name,
        "artifact_digest": artifact_digest,
    }


def _summary(ledger: dict[str, object], *, label: str) -> dict[str, object]:
    raw = ledger.get("summary")
    if not isinstance(raw, dict):
        raise RiskBudgetInvestigationDossierError(
            f"{label} summary is invalid"
        )
    return raw


def _decimal(value: object, *, field: str) -> Decimal:
    if not isinstance(value, str):
        raise RiskBudgetInvestigationDossierError(
            f"{field} must be a decimal string"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise RiskBudgetInvestigationDossierError(
            f"{field} must be a decimal string"
        ) from exc
    if not parsed.is_finite():
        raise RiskBudgetInvestigationDossierError(
            f"{field} must be finite"
        )
    return parsed


def _candidate_rows(
    ledger: dict[str, object],
    *,
    label: str,
) -> tuple[dict[str, object], ...]:
    raw = ledger.get("rows")
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise RiskBudgetInvestigationDossierError(
            f"{label} rows are invalid"
        )
    if not all(isinstance(item, dict) for item in raw):
        raise RiskBudgetInvestigationDossierError(
            f"{label} row is invalid"
        )
    return tuple(cast(dict[str, object], item) for item in raw)


def _weekly_drawdown_return_rows(
    ledger: dict[str, object],
) -> tuple[dict[str, object], ...]:
    selected: list[dict[str, object]] = []
    for row in _candidate_rows(ledger, label="return ledger"):
        timestamp = row.get("timestamp_ms")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or timestamp < WEEKLY_DRAWDOWN_5M_FROZEN_AT_MS
        ):
            continue
        reasons = row.get("baseline_risk_reason_codes")
        if not isinstance(reasons, (list, tuple)):
            raise RiskBudgetInvestigationDossierError(
                "return ledger risk reasons are invalid"
            )
        normalized_reasons = tuple(sorted(set(reasons)))
        if normalized_reasons != (WEEKLY_DRAWDOWN_REASON,):
            continue
        if (
            row.get("baseline_risk_approved") is not False
            or row.get("stack_decision") != "ADMIT"
            or row.get("block_layer") != "none"
        ):
            continue
        markouts = row.get("markouts")
        if not isinstance(markouts, dict):
            raise RiskBudgetInvestigationDossierError(
                "return ledger markouts are invalid"
            )
        markout = markouts.get(str(WEEKLY_DRAWDOWN_5M_HORIZON_MS))
        if not isinstance(markout, dict):
            raise RiskBudgetInvestigationDossierError(
                "5m return markout is missing"
            )
        if markout.get("status") != "settled":
            continue
        directional_return = _decimal(
            markout.get("directional_return"),
            field="5m directional_return",
        )
        opportunity_id = row.get("opportunity_id")
        market = row.get("market")
        direction = row.get("direction")
        if (
            not isinstance(opportunity_id, str)
            or not opportunity_id
            or not isinstance(market, str)
            or not market
            or direction not in {"long", "short"}
        ):
            raise RiskBudgetInvestigationDossierError(
                "return candidate identity is invalid"
            )
        selected.append(
            {
                "opportunity_id": opportunity_id,
                "timestamp_ms": timestamp,
                "market": market,
                "direction": direction,
                "directional_return": directional_return,
            }
        )
    return tuple(
        sorted(
            selected,
            key=lambda item: (
                cast(int, item["timestamp_ms"]),
                cast(str, item["opportunity_id"]),
            ),
        )
    )


def _weekly_drawdown_stop_rows(
    ledger: dict[str, object],
) -> dict[str, dict[str, object]]:
    selected: dict[str, dict[str, object]] = {}
    for row in _candidate_rows(ledger, label="stop ledger"):
        timestamp = row.get("timestamp_ms")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or timestamp < WEEKLY_DRAWDOWN_5M_FROZEN_AT_MS
        ):
            continue
        reasons = row.get("baseline_risk_reason_codes")
        if not isinstance(reasons, (list, tuple)):
            raise RiskBudgetInvestigationDossierError(
                "stop ledger risk reasons are invalid"
            )
        normalized_reasons = tuple(sorted(set(reasons)))
        if normalized_reasons != (WEEKLY_DRAWDOWN_REASON,):
            continue
        if (
            row.get("baseline_risk_approved") is not False
            or row.get("stack_decision") != "ADMIT"
            or row.get("block_layer") != "none"
        ):
            continue
        stop_path = row.get("stop_path")
        if not isinstance(stop_path, dict):
            raise RiskBudgetInvestigationDossierError(
                "stop candidate path is invalid"
            )
        horizons = stop_path.get("horizons")
        if not isinstance(horizons, dict):
            raise RiskBudgetInvestigationDossierError(
                "stop candidate horizons are invalid"
            )
        horizon = horizons.get(str(WEEKLY_DRAWDOWN_5M_HORIZON_MS))
        if not isinstance(horizon, dict):
            raise RiskBudgetInvestigationDossierError(
                "5m stop horizon is missing"
            )
        status = horizon.get("status")
        if status not in {
            "observed_stop_crossing",
            "observed_path_survivor",
        }:
            continue
        opportunity_id = row.get("opportunity_id")
        market = row.get("market")
        direction = row.get("direction")
        if (
            not isinstance(opportunity_id, str)
            or not opportunity_id
            or not isinstance(market, str)
            or not market
            or direction not in {"long", "short"}
        ):
            raise RiskBudgetInvestigationDossierError(
                "stop candidate identity is invalid"
            )
        selected[opportunity_id] = {
            "opportunity_id": opportunity_id,
            "timestamp_ms": timestamp,
            "market": market,
            "direction": direction,
            "stop_status": status,
        }
    return selected


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _return_robustness(
    rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    values = tuple(
        cast(Decimal, row["directional_return"]) for row in rows
    )
    mean_value = _mean(values)
    leave_one = tuple(
        _mean(values[:index] + values[index + 1 :])
        for index in range(len(values))
    )
    leave_one_values = tuple(
        value for value in leave_one if value is not None
    )
    markets = tuple(
        sorted({cast(str, row["market"]) for row in rows})
    )
    leave_market = tuple(
        _mean(
            tuple(
                cast(Decimal, row["directional_return"])
                for row in rows
                if row["market"] != market
            )
        )
        for market in markets
    )
    leave_market_values = tuple(
        value for value in leave_market if value is not None
    )
    return {
        "mean_directional_return": (
            None if mean_value is None else str(mean_value)
        ),
        "leave_one_opportunity_min_mean": (
            None
            if not leave_one_values
            else str(min(leave_one_values))
        ),
        "positive_after_removing_any_one_opportunity": (
            len(leave_one_values) == len(rows)
            and bool(leave_one_values)
            and min(leave_one_values) > ZERO
        ),
        "leave_one_market_min_mean": (
            None
            if not leave_market_values
            else str(min(leave_market_values))
        ),
        "positive_after_removing_any_one_market": (
            len(leave_market_values) == len(markets)
            and bool(leave_market_values)
            and min(leave_market_values) > ZERO
        ),
    }


def _survival_margin(rows: tuple[dict[str, object], ...]) -> int:
    survivors = sum(
        row["stop_status"] == "observed_path_survivor"
        for row in rows
    )
    crossings = sum(
        row["stop_status"] == "observed_stop_crossing"
        for row in rows
    )
    return survivors - crossings


def _stop_robustness(
    rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    survivors = sum(
        row["stop_status"] == "observed_path_survivor"
        for row in rows
    )
    crossings = sum(
        row["stop_status"] == "observed_stop_crossing"
        for row in rows
    )
    leave_one = tuple(
        _survival_margin(rows[:index] + rows[index + 1 :])
        for index in range(len(rows))
    )
    markets = tuple(
        sorted({cast(str, row["market"]) for row in rows})
    )
    leave_market = tuple(
        _survival_margin(
            tuple(row for row in rows if row["market"] != market)
        )
        for market in markets
    )
    return {
        "survivors": survivors,
        "crossings": crossings,
        "survival_margin": survivors - crossings,
        "leave_one_opportunity_min_margin": (
            None if not leave_one else min(leave_one)
        ),
        "survivor_majority_after_removing_any_one_opportunity": (
            bool(leave_one) and min(leave_one) > 0
        ),
        "leave_one_market_min_margin": (
            None if not leave_market else min(leave_market)
        ),
        "survivor_majority_after_removing_any_one_market": (
            bool(leave_market) and min(leave_market) > 0
        ),
    }


def _weekly_drawdown_5m_candidate(
    return_ledger: dict[str, object],
    stop_ledger: dict[str, object],
    *,
    source_aligned: bool,
) -> dict[str, object]:
    returns = _weekly_drawdown_return_rows(return_ledger)
    stops = _weekly_drawdown_stop_rows(stop_ledger)
    paired: list[dict[str, object]] = []
    for return_row in returns:
        opportunity_id = cast(str, return_row["opportunity_id"])
        stop_row = stops.get(opportunity_id)
        if stop_row is None:
            continue
        for field in ("timestamp_ms", "market", "direction"):
            if return_row[field] != stop_row[field]:
                raise RiskBudgetInvestigationDossierError(
                    f"weekly drawdown pair {field} mismatch"
                )
        paired.append({**return_row, "stop_status": stop_row["stop_status"]})
    paired_rows = tuple(paired)
    review = paired_rows[:WEEKLY_DRAWDOWN_5M_REVIEW_ROWS]
    markets = {
        cast(str, row["market"])
        for row in review
    }
    long_count = sum(row["direction"] == "long" for row in review)
    short_count = sum(row["direction"] == "short" for row in review)
    sample_complete = (
        len(review) == WEEKLY_DRAWDOWN_5M_REVIEW_ROWS
        and len(markets) >= WEEKLY_DRAWDOWN_5M_MIN_MARKETS
        and long_count >= WEEKLY_DRAWDOWN_5M_MIN_LONG
        and short_count >= WEEKLY_DRAWDOWN_5M_MIN_SHORT
    )
    returns_robustness = _return_robustness(review)
    stops_robustness = _stop_robustness(review)
    economic_ready = (
        sample_complete
        and returns_robustness[
            "positive_after_removing_any_one_opportunity"
        ]
        is True
        and returns_robustness[
            "positive_after_removing_any_one_market"
        ]
        is True
    )
    stop_ready = (
        sample_complete
        and cast(int, stops_robustness["survival_margin"]) > 0
        and stops_robustness[
            "survivor_majority_after_removing_any_one_opportunity"
        ]
        is True
        and stops_robustness[
            "survivor_majority_after_removing_any_one_market"
        ]
        is True
    )
    ready = source_aligned and economic_ready and stop_ready
    if not source_aligned:
        status = "waiting_for_aligned_sources"
    elif len(review) < WEEKLY_DRAWDOWN_5M_REVIEW_ROWS:
        status = "collecting_frozen_review_cohort"
    elif ready:
        status = "ready_for_execution_shadow_investigation"
    else:
        status = "failed_frozen_review_cohort"

    digest_rows = [
        {
            "opportunity_id": row["opportunity_id"],
            "timestamp_ms": row["timestamp_ms"],
            "market": row["market"],
            "direction": row["direction"],
            "directional_return": str(row["directional_return"]),
            "stop_status": row["stop_status"],
        }
        for row in review
    ]
    review_sha256 = hashlib.sha256(
        _canonical_json(digest_rows).encode("utf-8")
    ).hexdigest()
    return {
        "candidate_id": WEEKLY_DRAWDOWN_5M_CANDIDATE_ID,
        "status": status,
        "frozen_at_ms": WEEKLY_DRAWDOWN_5M_FROZEN_AT_MS,
        "exit_horizon_ms": WEEKLY_DRAWDOWN_5M_HORIZON_MS,
        "risk_reason": WEEKLY_DRAWDOWN_REASON,
        "rule": {
            "baseline_risk_reason_codes": [WEEKLY_DRAWDOWN_REASON],
            "stack_decision": "ADMIT",
            "block_layer": "none",
            "exit_horizon_ms": WEEKLY_DRAWDOWN_5M_HORIZON_MS,
            "review_cohort": (
                f"first_{WEEKLY_DRAWDOWN_5M_REVIEW_ROWS}_paired_"
                "post_freeze_opportunities"
            ),
        },
        "thresholds": {
            "review_rows": WEEKLY_DRAWDOWN_5M_REVIEW_ROWS,
            "min_markets": WEEKLY_DRAWDOWN_5M_MIN_MARKETS,
            "min_long": WEEKLY_DRAWDOWN_5M_MIN_LONG,
            "min_short": WEEKLY_DRAWDOWN_5M_MIN_SHORT,
            "return_mean_positive_after_any_single_opportunity_removed": True,
            "return_mean_positive_after_any_single_market_removed": True,
            "stop_survivor_majority_after_any_single_opportunity_removed": True,
            "stop_survivor_majority_after_any_single_market_removed": True,
        },
        "source_aligned": source_aligned,
        "post_freeze_settled_return_rows": len(returns),
        "post_freeze_paired_evaluable_rows": len(paired_rows),
        "review_rows": len(review),
        "review_market_count": len(markets),
        "review_long_count": long_count,
        "review_short_count": short_count,
        "sample_complete": sample_complete,
        "return_robustness": returns_robustness,
        "stop_robustness": stops_robustness,
        "economic_ready": economic_ready,
        "stop_survival_ready": stop_ready,
        "ready_for_execution_shadow_investigation": ready,
        "review_cohort_sha256": review_sha256,
        "discovery_cohort_reused_for_validation": False,
        "claim_scope": (
            "prospective_5m_markout_and_observed_original_stop_survival_only"
        ),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "changes_execution": False,
        "changes_candidate_readiness": False,
    }


def build_risk_budget_investigation_dossier(
    return_ledger: object,
    stop_ledger: object,
) -> dict[str, object]:
    validated_returns = validate_risk_rejected_forward_markout_ledger(
        return_ledger
    )
    validated_stops = validate_risk_rejected_stop_path_ledger(
        stop_ledger
    )
    return_summary = _summary(validated_returns, label="return ledger")
    stop_summary = _summary(validated_stops, label="stop ledger")

    return_identity = _latest_source_identity(
        validated_returns,
        label="return ledger",
    )
    stop_identity = _latest_source_identity(
        validated_stops,
        label="stop ledger",
    )
    return_overlap = validated_returns.get("overlap_started_at_ms")
    stop_overlap = validated_stops.get("overlap_started_at_ms")
    source_aligned = (
        return_identity == stop_identity
        and return_overlap == stop_overlap
    )

    cumulative_economic_gate = return_summary.get(
        "risk_budget_investigation_readiness"
    )
    cumulative_stop_gate = stop_summary.get(
        "risk_budget_stop_investigation"
    )
    gates_current = isinstance(
        cumulative_economic_gate, dict
    ) and isinstance(cumulative_stop_gate, dict)
    return_integrity = return_summary.get("integrity_clean") is True
    stop_integrity = stop_summary.get("integrity_clean") is True
    integrity_clean = return_integrity and stop_integrity

    return_post = return_summary.get("post_integrity_miss")
    stop_post = stop_summary.get("post_integrity_miss")
    post_boundary_known = (
        isinstance(return_post, dict)
        and isinstance(stop_post, dict)
        and return_post.get("boundary_known") is True
        and stop_post.get("boundary_known") is True
    )
    post_started_at_ms = (
        return_post.get("started_at_ms")
        if isinstance(return_post, dict)
        else None
    )
    stop_post_started_at_ms = (
        stop_post.get("started_at_ms")
        if isinstance(stop_post, dict)
        else None
    )
    post_source_aligned = (
        source_aligned
        and post_boundary_known
        and isinstance(post_started_at_ms, int)
        and not isinstance(post_started_at_ms, bool)
        and post_started_at_ms == stop_post_started_at_ms
    )
    post_economic_gate = (
        return_post.get("risk_budget_investigation_readiness")
        if isinstance(return_post, dict)
        else None
    )
    post_stop_gate = (
        stop_post.get("risk_budget_stop_investigation")
        if isinstance(stop_post, dict)
        else None
    )
    post_gates_current = isinstance(
        post_economic_gate, dict
    ) and isinstance(post_stop_gate, dict)
    if integrity_clean:
        integrity_scope = "cumulative"
        effective_integrity_clean = True
        economic_gate = cumulative_economic_gate
        stop_gate = cumulative_stop_gate
    elif post_source_aligned and post_gates_current:
        integrity_scope = "post_integrity_miss"
        effective_integrity_clean = True
        economic_gate = post_economic_gate
        stop_gate = post_stop_gate
    else:
        integrity_scope = "blocked"
        effective_integrity_clean = False
        economic_gate = cumulative_economic_gate
        stop_gate = cumulative_stop_gate

    economic_by_reason: dict[str, object] = {}
    stop_by_reason: dict[str, object] = {}
    if isinstance(economic_gate, dict):
        raw = economic_gate.get("by_reason")
        if isinstance(raw, dict):
            economic_by_reason = raw
    if isinstance(stop_gate, dict):
        raw = stop_gate.get("by_reason")
        if isinstance(raw, dict):
            stop_by_reason = raw

    reasons = sorted(set(economic_by_reason) | set(stop_by_reason))
    by_reason: dict[str, dict[str, object]] = {}
    ready_reasons: list[str] = []
    for reason in reasons:
        economic = economic_by_reason.get(reason)
        stop = stop_by_reason.get(reason)
        economic_ready = (
            isinstance(economic, dict)
            and economic.get("ready_for_risk_budget_investigation") is True
        )
        stop_ready = (
            isinstance(stop, dict)
            and stop.get(
                "ready_for_risk_budget_stop_investigation"
            )
            is True
        )
        conjunctive_ready = (
            source_aligned
            and gates_current
            and effective_integrity_clean
            and economic_ready
            and stop_ready
        )
        if conjunctive_ready:
            ready_reasons.append(reason)
        by_reason[reason] = {
            "economic_ready": economic_ready,
            "stop_survival_ready": stop_ready,
            "conjunctive_ready_for_investigation": conjunctive_ready,
            "economic_horizons": (
                economic.get("horizons")
                if isinstance(economic, dict)
                else None
            ),
            "stop_survival_horizons": (
                stop.get("horizons")
                if isinstance(stop, dict)
                else None
            ),
        }

    if not gates_current:
        status = "waiting_for_current_gate_format"
    elif not source_aligned:
        status = "waiting_for_aligned_sources"
    elif integrity_clean:
        status = "aligned_evaluated"
    elif post_source_aligned and post_gates_current:
        status = "aligned_post_integrity_evaluated"
    else:
        status = "blocked_by_source_integrity"

    payload: dict[str, object] = {
        "schema_version": DOSSIER_SCHEMA_VERSION,
        "kind": DOSSIER_KIND,
        "status": status,
        "source_aligned": source_aligned,
        "gates_current": gates_current,
        "integrity_clean": integrity_clean,
        "effective_integrity_clean": effective_integrity_clean,
        "integrity_scope": integrity_scope,
        "post_integrity_source_aligned": post_source_aligned,
        "post_integrity_started_at_ms": (
            post_started_at_ms if post_source_aligned else None
        ),
        "return_integrity_clean": return_integrity,
        "stop_integrity_clean": stop_integrity,
        "return_source": return_identity,
        "stop_source": stop_identity,
        "return_overlap_started_at_ms": return_overlap,
        "stop_overlap_started_at_ms": stop_overlap,
        "return_ledger_sha256": validated_returns.get("ledger_sha256"),
        "stop_ledger_sha256": validated_stops.get("ledger_sha256"),
        "ready_reasons": ready_reasons,
        "by_reason": by_reason,
        "weekly_drawdown_5m_candidate": _weekly_drawdown_5m_candidate(
            validated_returns,
            validated_stops,
            source_aligned=source_aligned,
        ),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "changes_execution": False,
        "changes_candidate_readiness": False,
    }
    payload["report_sha256"] = _sha256_payload(payload)
    return payload


def validate_risk_budget_investigation_dossier(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier must be an object"
        )
    if raw.get("schema_version") != DOSSIER_SCHEMA_VERSION:
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier schema is unsupported"
        )
    if raw.get("kind") != DOSSIER_KIND:
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier kind is unsupported"
        )
    if raw.get("status") not in {
        "waiting_for_current_gate_format",
        "waiting_for_aligned_sources",
        "blocked_by_source_integrity",
        "aligned_evaluated",
        "aligned_post_integrity_evaluated",
    }:
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier status is unsupported"
        )
    if (
        raw.get("research_only") is not True
        or raw.get("execution_authority") is not False
        or raw.get("promotion_authority") is not False
        or raw.get("changes_risk_limits") is not False
        or raw.get("changes_execution") is not False
        or raw.get("changes_candidate_readiness") is not False
    ):
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier authority drift"
        )
    candidate = raw.get("weekly_drawdown_5m_candidate")
    if candidate is not None:
        if not isinstance(candidate, dict):
            raise RiskBudgetInvestigationDossierError(
                "weekly drawdown 5m candidate is invalid"
            )
        if (
            candidate.get("candidate_id")
            != WEEKLY_DRAWDOWN_5M_CANDIDATE_ID
            or candidate.get("frozen_at_ms")
            != WEEKLY_DRAWDOWN_5M_FROZEN_AT_MS
            or candidate.get("exit_horizon_ms")
            != WEEKLY_DRAWDOWN_5M_HORIZON_MS
            or candidate.get("research_only") is not True
            or candidate.get("execution_authority") is not False
            or candidate.get("promotion_authority") is not False
            or candidate.get("changes_risk_limits") is not False
            or candidate.get("changes_execution") is not False
            or candidate.get("changes_candidate_readiness") is not False
        ):
            raise RiskBudgetInvestigationDossierError(
                "weekly drawdown 5m candidate authority or freeze drift"
            )

    ready_reasons = raw.get("ready_reasons")
    by_reason = raw.get("by_reason")
    if not isinstance(ready_reasons, list) or not isinstance(by_reason, dict):
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier reason summary is invalid"
        )
    expected = _sha256_payload(cast(dict[str, object], raw))
    if raw.get("report_sha256") != expected:
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier digest mismatch"
        )
    return dict(raw)
