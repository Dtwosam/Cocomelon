from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Final, cast

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
)
from cocomelon.research.prospective_full_stack_forward_markout import (
    LONG_TREND_CARVEOUT_CANDIDATE_ID,
)

SCHEMA_VERSION: Final = 2
SOURCE_KIND: Final = (
    "prospective-long-trend-carveout-execution-shadow-source-v2"
)
LEGACY_SOURCE_KIND: Final = (
    "prospective-long-trend-carveout-execution-shadow-source-v1"
)
WEEKLY_DRAWDOWN_REASON: Final = "weekly_drawdown_lockout"


class ProspectiveLongTrendExecutionShadowSourceError(RuntimeError):
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


def execution_config_payload(
    config: PaperExecutionConfig,
) -> dict[str, object]:
    return {
        "config_version": config.config_version,
        "latency_ms": config.latency_ms,
        "max_book_age_ms": config.max_book_age_ms,
        "max_asset_ctx_age_ms": config.max_asset_ctx_age_ms,
        "max_position_age_ms": config.max_position_age_ms,
        "funding_reconciliation_grace_ms": (
            config.funding_reconciliation_grace_ms
        ),
        "max_ioc_slippage_bps": str(config.max_ioc_slippage_bps),
        "taker_fee_rate": str(config.taker_fee_rate),
        "fee_schedule_id": config.fee_schedule_id,
        "native_perp_min_notional": str(
            config.native_perp_min_notional
        ),
        "paper_max_gross_leverage": str(
            config.paper_max_gross_leverage
        ),
    }


def _path_by_id(
    paths: Sequence[ContinuousPaperOpeningOpportunityPath],
) -> dict[str, ContinuousPaperOpeningOpportunityPath]:
    output: dict[str, ContinuousPaperOpeningOpportunityPath] = {}
    for path in paths:
        existing = output.get(path.opportunity_id)
        if existing is not None and existing != path:
            raise ProspectiveLongTrendExecutionShadowSourceError(
                "duplicate long-trend opportunity path"
            )
        output[path.opportunity_id] = path
    return output


def _opportunity_by_id(
    opportunities: Sequence[ContinuousPaperOpeningOpportunityEvidence],
) -> dict[str, ContinuousPaperOpeningOpportunityEvidence]:
    output: dict[str, ContinuousPaperOpeningOpportunityEvidence] = {}
    for evidence in opportunities:
        existing = output.get(evidence.opportunity_id)
        if existing is not None and existing != evidence:
            raise ProspectiveLongTrendExecutionShadowSourceError(
                "duplicate long-trend opening opportunity"
            )
        output[evidence.opportunity_id] = evidence
    return output


def _is_reopened_weekly_long_trend(row: dict[str, object]) -> bool:
    reasons = row.get("baseline_risk_reason_codes")
    return (
        row.get("combined_block_reason") == "long_trend"
        and row.get("stack_decision") == "BLOCK"
        and row.get("block_layer") == "combined"
        and row.get("long_trend_carveout_candidate_id")
        == LONG_TREND_CARVEOUT_CANDIDATE_ID
        and row.get("long_trend_carveout_decision") == "ADMIT"
        and row.get("long_trend_carveout_block_layer") == "none"
        and isinstance(reasons, (list, tuple))
        and tuple(reasons) == (WEEKLY_DRAWDOWN_REASON,)
    )


def prospective_long_trend_execution_shadow_source(
    full_stack_summary: object,
    opportunities: Sequence[ContinuousPaperOpeningOpportunityEvidence],
    paths: Sequence[ContinuousPaperOpeningOpportunityPath],
    execution_config: PaperExecutionConfig,
) -> dict[str, object]:
    if not isinstance(full_stack_summary, dict):
        raise ProspectiveLongTrendExecutionShadowSourceError(
            "full-stack summary must be an object"
        )
    if full_stack_summary.get("enabled") is not True:
        raise ProspectiveLongTrendExecutionShadowSourceError(
            "full-stack summary is not cleanly enabled"
        )
    if full_stack_summary.get("error") is not None:
        raise ProspectiveLongTrendExecutionShadowSourceError(
            "full-stack summary contains an error"
        )
    if (
        full_stack_summary.get("research_only") is not True
        or full_stack_summary.get("execution_authority") is not False
        or full_stack_summary.get("promotion_authority") is not False
        or full_stack_summary.get("changes_readiness_gate") is not False
        or full_stack_summary.get("changes_closed_trade_readiness_gate")
        is not False
    ):
        raise ProspectiveLongTrendExecutionShadowSourceError(
            "full-stack summary authority drift"
        )

    overlap_started_at_ms = full_stack_summary.get(
        "overlap_started_at_ms"
    )
    if (
        isinstance(overlap_started_at_ms, bool)
        or not isinstance(overlap_started_at_ms, int)
        or overlap_started_at_ms < 0
    ):
        raise ProspectiveLongTrendExecutionShadowSourceError(
            "full-stack overlap start is invalid"
        )

    raw_rows = full_stack_summary.get("risk_rejected_rows")
    if not isinstance(raw_rows, list):
        raise ProspectiveLongTrendExecutionShadowSourceError(
            "risk-rejected full-stack rows are missing"
        )

    opportunity_map = _opportunity_by_id(opportunities)
    path_map = _path_by_id(paths)
    exported: list[dict[str, object]] = []
    missing_opportunities = 0
    missing_paths = 0

    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise ProspectiveLongTrendExecutionShadowSourceError(
                "risk-rejected full-stack row must be an object"
            )
        if not _is_reopened_weekly_long_trend(raw_row):
            continue

        opportunity_id = raw_row.get("opportunity_id")
        if not isinstance(opportunity_id, str) or not opportunity_id:
            raise ProspectiveLongTrendExecutionShadowSourceError(
                "reopened long-trend row is missing opportunity id"
            )
        evidence = opportunity_map.get(opportunity_id)
        if evidence is None:
            raise ProspectiveLongTrendExecutionShadowSourceError(
                "reopened long-trend opportunity evidence is missing"
            )
        if (
            evidence.opportunity_timestamp_ms < overlap_started_at_ms
            or evidence.direction != "long"
            or evidence.lead_strategy != "trend"
            or evidence.baseline_risk_approved
            or evidence.baseline_risk_reason_codes
            != (WEEKLY_DRAWDOWN_REASON,)
        ):
            raise ProspectiveLongTrendExecutionShadowSourceError(
                "reopened long-trend opportunity lineage mismatch"
            )

        path = path_map.get(opportunity_id)
        if path is None:
            missing_paths += 1
        elif (
            path.market != evidence.market
            or path.direction != evidence.direction
            or path.opportunity_timestamp_ms
            != evidence.opportunity_timestamp_ms
        ):
            raise ProspectiveLongTrendExecutionShadowSourceError(
                "reopened long-trend path lineage mismatch"
            )

        row_lineage = {
            "opportunity_id": opportunity_id,
            "timestamp_ms": raw_row.get("timestamp_ms"),
            "market": raw_row.get("market"),
            "direction": raw_row.get("direction"),
            "lead_strategy": raw_row.get("lead_strategy"),
            "rank_ordinal": raw_row.get("rank_ordinal"),
            "rank_age_ms": raw_row.get("rank_age_ms"),
            "combined_block_reason": raw_row.get(
                "combined_block_reason"
            ),
            "two_strike_prior_strikes": raw_row.get(
                "two_strike_prior_strikes"
            ),
            "long_trend_carveout_momentum_decision": raw_row.get(
                "long_trend_carveout_momentum_decision"
            ),
            "long_trend_carveout_momentum_reason": raw_row.get(
                "long_trend_carveout_momentum_reason"
            ),
            "long_trend_carveout_decision": raw_row.get(
                "long_trend_carveout_decision"
            ),
            "long_trend_carveout_block_layer": raw_row.get(
                "long_trend_carveout_block_layer"
            ),
        }
        exported.append(
            {
                "opportunity_id": opportunity_id,
                "lineage": row_lineage,
                "opportunity": evidence.to_dict(),
                "path": None if path is None else path.to_dict(),
            }
        )

    exported.sort(
        key=lambda item: (
            cast(
                int,
                cast(dict[str, object], item["opportunity"])[
                    "opportunity_timestamp_ms"
                ],
            ),
            cast(
                str,
                cast(dict[str, object], item["opportunity"])[
                    "market"
                ],
            ),
            cast(str, item["opportunity_id"]),
        )
    )
    row_ids = tuple(cast(str, item["opportunity_id"]) for item in exported)
    if len(row_ids) != len(set(row_ids)):
        raise ProspectiveLongTrendExecutionShadowSourceError(
            "duplicate execution-shadow source opportunity id"
        )

    config_payload = execution_config_payload(execution_config)
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": SOURCE_KIND,
        "candidate_id": LONG_TREND_CARVEOUT_CANDIDATE_ID,
        "overlap_started_at_ms": overlap_started_at_ms,
        "baseline_risk_reason": WEEKLY_DRAWDOWN_REASON,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "durable_gate_required": True,
        "durable_gate_source": (
            "prospective-long-trend-carveout-fast-markout-ledger"
        ),
        "execution_config": config_payload,
        "execution_config_sha256": _sha256(config_payload),
        "source_opportunity_count": len(exported),
        "missing_opportunity_evidence": missing_opportunities,
        "missing_forward_paths": missing_paths,
        "opportunities": exported,
    }
    payload["source_sha256"] = _sha256(payload)
    return payload
