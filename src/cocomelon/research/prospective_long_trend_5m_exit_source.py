from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, cast

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    OpeningOpportunityExitBookEvidence,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ReplacementFundingBoundaryEvidence,
)

SCHEMA_VERSION: Final = 1
SOURCE_KIND: Final = "prospective-long-trend-5m-exit-source-v1"
CANDIDATE_ID: Final = "prospective-reopened-long-trend-5m-exit-v1"
FROZEN_STARTED_AT_MS: Final = 1_791_103_620_000
EXIT_HORIZON_MS: Final = 300_000
WEEKLY_DRAWDOWN_REASON: Final = "weekly_drawdown_lockout"


class ProspectiveLongTrend5mExitSourceError(RuntimeError):
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


@dataclass(frozen=True, slots=True)
class ProspectiveLongTrend5mExitState:
    started_at_ms: int
    schema_version: int = SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID
    exit_horizon_ms: int = EXIT_HORIZON_MS

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported LONG+trend 5m state schema")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("unsupported LONG+trend 5m candidate")
        if self.exit_horizon_ms != EXIT_HORIZON_MS:
            raise ValueError("unsupported LONG+trend 5m horizon")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "rule": {
                "entry_scope": "weekly_drawdown_only_reopened_pure_long_trend",
                "entry_execution": "captured_request_visible_book_ioc",
                "exit_horizon_ms": self.exit_horizon_ms,
                "exit_execution": "captured_real_l2_reduce_only_ioc",
                "funding_policy": "exact_captured_hourly_boundaries",
                "cross_horizon_selection": "frozen_single_horizon",
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveLongTrend5mExitState:
        if not isinstance(raw, dict):
            raise ProspectiveLongTrend5mExitSourceError(
                "LONG+trend 5m state must be an object"
            )
        expected_rule = {
            "entry_scope": "weekly_drawdown_only_reopened_pure_long_trend",
            "entry_execution": "captured_request_visible_book_ioc",
            "exit_horizon_ms": EXIT_HORIZON_MS,
            "exit_execution": "captured_real_l2_reduce_only_ioc",
            "funding_policy": "exact_captured_hourly_boundaries",
            "cross_horizon_selection": "frozen_single_horizon",
        }
        if raw.get("rule") != expected_rule:
            raise ProspectiveLongTrend5mExitSourceError(
                "LONG+trend 5m rule does not match frozen candidate"
            )
        schema = raw.get("schema_version")
        started = raw.get("started_at_ms")
        candidate = raw.get("candidate_id")
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise ProspectiveLongTrend5mExitSourceError(
                "state schema_version must be an integer"
            )
        if isinstance(started, bool) or not isinstance(started, int):
            raise ProspectiveLongTrend5mExitSourceError(
                "state started_at_ms must be an integer"
            )
        if not isinstance(candidate, str):
            raise ProspectiveLongTrend5mExitSourceError(
                "state candidate_id must be a string"
            )
        try:
            return cls(
                started_at_ms=started,
                schema_version=schema,
                candidate_id=candidate,
            )
        except ValueError as exc:
            raise ProspectiveLongTrend5mExitSourceError(
                str(exc)
            ) from exc


def _opportunity_by_id(
    opportunities: Sequence[ContinuousPaperOpeningOpportunityEvidence],
) -> dict[str, ContinuousPaperOpeningOpportunityEvidence]:
    output: dict[str, ContinuousPaperOpeningOpportunityEvidence] = {}
    for evidence in opportunities:
        existing = output.get(evidence.opportunity_id)
        if existing is not None and existing != evidence:
            raise ProspectiveLongTrend5mExitSourceError(
                "duplicate weekly-drawdown opening opportunity"
            )
        output[evidence.opportunity_id] = evidence
    return output


def _exit_book_by_id(
    exit_books: Sequence[OpeningOpportunityExitBookEvidence],
) -> dict[str, OpeningOpportunityExitBookEvidence]:
    output: dict[str, OpeningOpportunityExitBookEvidence] = {}
    for evidence in exit_books:
        if evidence.horizon_ms != EXIT_HORIZON_MS:
            continue
        existing = output.get(evidence.opportunity_id)
        if existing is not None and existing != evidence:
            raise ProspectiveLongTrend5mExitSourceError(
                "duplicate LONG+trend 5m exit book"
            )
        output[evidence.opportunity_id] = evidence
    return output


def _is_candidate_row(raw: dict[str, object]) -> bool:
    reasons = raw.get("baseline_risk_reason_codes")
    return (
        raw.get("combined_block_reason") == "long_trend"
        and raw.get("stack_decision") == "BLOCK"
        and raw.get("block_layer") == "combined"
        and raw.get("long_trend_carveout_candidate_id")
        == "prospective-top10-two-strike-momentum-no-long-trend-v1"
        and raw.get("long_trend_carveout_decision") == "ADMIT"
        and raw.get("long_trend_carveout_block_layer") == "none"
        and isinstance(reasons, (list, tuple))
        and tuple(reasons) == (WEEKLY_DRAWDOWN_REASON,)
    )


def _five_minute_stop_path(
    raw_row: dict[str, object],
    *,
    opportunity_timestamp_ms: int,
) -> dict[str, object]:
    raw_path = raw_row.get("long_trend_carveout_stop_path")
    if not isinstance(raw_path, dict):
        raise ProspectiveLongTrend5mExitSourceError(
            "candidate stop-path evidence is missing"
        )
    if (
        raw_path.get("claim_scope")
        != "observed_mark_stop_crossing_only"
        or raw_path.get("changes_execution") is not False
        or raw_path.get("changes_risk_limits") is not False
        or raw_path.get("changes_candidate_readiness") is not False
    ):
        raise ProspectiveLongTrend5mExitSourceError(
            "candidate stop-path contract drift"
        )
    raw_horizons = raw_path.get("horizons")
    if not isinstance(raw_horizons, dict):
        raise ProspectiveLongTrend5mExitSourceError(
            "candidate stop-path horizons are missing"
        )
    raw_five = raw_horizons.get(str(EXIT_HORIZON_MS))
    if not isinstance(raw_five, dict):
        raise ProspectiveLongTrend5mExitSourceError(
            "candidate 5m stop-path evidence is missing"
        )
    status = raw_five.get("status")
    supported = {
        "missing_stop",
        "missing_path",
        "unsupported_horizon",
        "markout_pending",
        "markout_stale",
        "no_causal_marks",
        "observed_stop_crossing",
        "observed_path_survivor",
    }
    if not isinstance(status, str) or status not in supported:
        raise ProspectiveLongTrend5mExitSourceError(
            "candidate 5m stop-path status is invalid"
        )
    target_at_ms = raw_five.get("target_at_ms")
    expected_target = opportunity_timestamp_ms + EXIT_HORIZON_MS
    if (
        isinstance(target_at_ms, bool)
        or not isinstance(target_at_ms, int)
        or target_at_ms != expected_target
    ):
        raise ProspectiveLongTrend5mExitSourceError(
            "candidate 5m stop-path target drift"
        )
    observed_mark_count = raw_five.get("observed_mark_count")
    if (
        isinstance(observed_mark_count, bool)
        or not isinstance(observed_mark_count, int)
        or observed_mark_count < 0
    ):
        raise ProspectiveLongTrend5mExitSourceError(
            "candidate 5m stop-path mark count is invalid"
        )
    stop_crossed = raw_five.get("stop_crossed")
    survived = raw_five.get("survived_observed_marks_to_horizon")
    if status == "observed_stop_crossing":
        if stop_crossed is not True or survived is not False:
            raise ProspectiveLongTrend5mExitSourceError(
                "observed stop crossing flags are inconsistent"
            )
    elif status == "observed_path_survivor":
        if stop_crossed is not False or survived is not True:
            raise ProspectiveLongTrend5mExitSourceError(
                "observed stop survivor flags are inconsistent"
            )
    elif stop_crossed is not None or survived is not None:
        raise ProspectiveLongTrend5mExitSourceError(
            "incomplete stop path must not claim crossing or survival"
        )
    return {
        "claim_scope": "observed_mark_stop_crossing_only",
        "status": status,
        "target_at_ms": target_at_ms,
        "observed_mark_count": observed_mark_count,
        "stop_crossed": stop_crossed,
        "first_stop_cross_at_ms": raw_five.get(
            "first_stop_cross_at_ms"
        ),
        "first_stop_cross_mark_px": raw_five.get(
            "first_stop_cross_mark_px"
        ),
        "time_to_stop_ms": raw_five.get("time_to_stop_ms"),
        "survived_observed_marks_to_horizon": survived,
        "unseen_intraperiod_path_complete": False,
    }


def _validated_integrity_boundary(
    full_stack_summary: dict[str, object],
    state: ProspectiveLongTrend5mExitState,
) -> int | None:
    raw_last_miss = full_stack_summary.get(
        "risk_rejected_integrity_last_miss_at_ms"
    )
    if raw_last_miss is not None and (
        isinstance(raw_last_miss, bool)
        or not isinstance(raw_last_miss, int)
        or raw_last_miss < 0
    ):
        raise ProspectiveLongTrend5mExitSourceError(
            "risk-rejected integrity miss boundary is invalid"
        )
    if (
        isinstance(raw_last_miss, int)
        and raw_last_miss >= state.started_at_ms
    ):
        raise ProspectiveLongTrend5mExitSourceError(
            "integrity miss overlaps candidate window"
        )
    if (
        full_stack_summary.get("risk_rejected_integrity_clean") is not True
        and raw_last_miss is None
    ):
        raise ProspectiveLongTrend5mExitSourceError(
            "dirty risk-rejected source lacks integrity boundary"
        )
    return raw_last_miss


def prospective_long_trend_5m_exit_source(
    full_stack_summary: object,
    opportunities: Sequence[ContinuousPaperOpeningOpportunityEvidence],
    exit_books: Sequence[OpeningOpportunityExitBookEvidence],
    funding_records: Sequence[ReplacementFundingBoundaryEvidence],
    execution_config: PaperExecutionConfig,
    state: ProspectiveLongTrend5mExitState,
) -> dict[str, object]:
    if not isinstance(full_stack_summary, dict):
        raise ProspectiveLongTrend5mExitSourceError(
            "full-stack summary must be an object"
        )
    if (
        full_stack_summary.get("enabled") is not True
        or full_stack_summary.get("error") is not None
    ):
        raise ProspectiveLongTrend5mExitSourceError(
            "full-stack summary is not cleanly enabled"
        )
    for key, expected in (
        ("research_only", True),
        ("execution_authority", False),
        ("promotion_authority", False),
        ("changes_readiness_gate", False),
        ("changes_closed_trade_readiness_gate", False),
    ):
        if full_stack_summary.get(key) is not expected:
            raise ProspectiveLongTrend5mExitSourceError(
                f"full-stack summary authority drift: {key}"
            )

    overlap = full_stack_summary.get("overlap_started_at_ms")
    if (
        isinstance(overlap, bool)
        or not isinstance(overlap, int)
        or overlap < 0
    ):
        raise ProspectiveLongTrend5mExitSourceError(
            "full-stack overlap start is invalid"
        )
    if state.started_at_ms < overlap:
        raise ProspectiveLongTrend5mExitSourceError(
            "candidate start predates full-stack overlap"
        )
    last_integrity_miss = _validated_integrity_boundary(
        full_stack_summary,
        state,
    )

    raw_rows = full_stack_summary.get("risk_rejected_rows")
    if not isinstance(raw_rows, list):
        raise ProspectiveLongTrend5mExitSourceError(
            "risk-rejected full-stack rows are missing"
        )

    opportunity_map = _opportunity_by_id(opportunities)
    exit_book_map = _exit_book_by_id(exit_books)
    funding_values = tuple(funding_records)
    exported: list[dict[str, object]] = []
    discovery_excluded = 0
    missing_exit_books = 0

    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise ProspectiveLongTrend5mExitSourceError(
                "risk-rejected full-stack row must be an object"
            )
        if not _is_candidate_row(raw_row):
            continue

        timestamp_ms = raw_row.get("timestamp_ms")
        if (
            isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, int)
            or timestamp_ms < overlap
        ):
            raise ProspectiveLongTrend5mExitSourceError(
                "candidate row timestamp is invalid"
            )
        if timestamp_ms < state.started_at_ms:
            discovery_excluded += 1
            continue

        opportunity_id = raw_row.get("opportunity_id")
        if not isinstance(opportunity_id, str) or not opportunity_id:
            raise ProspectiveLongTrend5mExitSourceError(
                "candidate row is missing opportunity id"
            )
        evidence = opportunity_map.get(opportunity_id)
        if evidence is None:
            raise ProspectiveLongTrend5mExitSourceError(
                "candidate opportunity evidence is missing"
            )
        if (
            evidence.opportunity_timestamp_ms != timestamp_ms
            or evidence.market != raw_row.get("market")
            or evidence.direction != raw_row.get("direction")
            or evidence.direction != "long"
            or evidence.lead_strategy != "trend"
            or evidence.baseline_risk_approved
            or evidence.baseline_risk_reason_codes
            != (WEEKLY_DRAWDOWN_REASON,)
        ):
            raise ProspectiveLongTrend5mExitSourceError(
                "candidate opportunity lineage mismatch"
            )

        stop_path = _five_minute_stop_path(
            raw_row,
            opportunity_timestamp_ms=timestamp_ms,
        )

        exit_book = exit_book_map.get(opportunity_id)
        if exit_book is None:
            missing_exit_books += 1
            end_ms = timestamp_ms + EXIT_HORIZON_MS
        else:
            if (
                exit_book.market != evidence.market
                or exit_book.direction != evidence.direction
                or exit_book.opportunity_timestamp_ms
                != evidence.opportunity_timestamp_ms
                or exit_book.horizon_ms != EXIT_HORIZON_MS
            ):
                raise ProspectiveLongTrend5mExitSourceError(
                    "candidate exit-book lineage mismatch"
                )
            end_ms = exit_book.observed_at_ms + execution_config.latency_ms

        funding = [
            item.to_dict()
            for item in funding_values
            if (
                item.market == evidence.market
                and timestamp_ms < item.boundary_ms <= end_ms
            )
        ]
        funding.sort(
            key=lambda item: (
                cast(int, item["boundary_ms"]),
                cast(str, item["market"]),
            )
        )
        lineage = {
            "opportunity_id": opportunity_id,
            "timestamp_ms": timestamp_ms,
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
            "momentum_decision": raw_row.get("momentum_decision"),
            "momentum_reason": raw_row.get("momentum_reason"),
            "momentum_prior_strikes": raw_row.get(
                "momentum_prior_strikes"
            ),
            "stack_decision": raw_row.get("stack_decision"),
            "block_layer": raw_row.get("block_layer"),
            "long_trend_carveout_candidate_id": raw_row.get(
                "long_trend_carveout_candidate_id"
            ),
            "long_trend_carveout_decision": raw_row.get(
                "long_trend_carveout_decision"
            ),
            "long_trend_carveout_block_layer": raw_row.get(
                "long_trend_carveout_block_layer"
            ),
            "long_trend_carveout_momentum_decision": raw_row.get(
                "long_trend_carveout_momentum_decision"
            ),
            "long_trend_carveout_momentum_reason": raw_row.get(
                "long_trend_carveout_momentum_reason"
            ),
            "baseline_risk_reason_codes": list(
                evidence.baseline_risk_reason_codes
            ),
        }
        exported.append(
            {
                "opportunity_id": opportunity_id,
                "lineage": lineage,
                "opportunity": evidence.to_dict(),
                "stop_path": stop_path,
                "exit_book": (
                    None if exit_book is None else exit_book.to_dict()
                ),
                "funding_evidence": funding,
            }
        )

    exported.sort(
        key=lambda item: (
            cast(
                int,
                cast(dict[str, object], item["lineage"])[
                    "timestamp_ms"
                ],
            ),
            cast(
                str,
                cast(dict[str, object], item["lineage"])["market"],
            ),
            cast(str, item["opportunity_id"]),
        )
    )
    ids = tuple(cast(str, item["opportunity_id"]) for item in exported)
    if len(ids) != len(set(ids)):
        raise ProspectiveLongTrend5mExitSourceError(
            "duplicate candidate source opportunity id"
        )

    config_payload = execution_config_payload(execution_config)
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": SOURCE_KIND,
        "candidate_id": state.candidate_id,
        "candidate_state": state.payload(),
        "started_at_ms": state.started_at_ms,
        "exit_horizon_ms": EXIT_HORIZON_MS,
        "baseline_risk_reason": WEEKLY_DRAWDOWN_REASON,
        "full_stack_overlap_started_at_ms": overlap,
        "pre_candidate_integrity_last_miss_at_ms": last_integrity_miss,
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "discovery_cohort_reused_for_validation": False,
        "cross_horizon_selection_frozen": True,
        "execution_config": config_payload,
        "execution_config_sha256": _sha256(config_payload),
        "source_opportunity_count": len(exported),
        "discovery_opportunities_excluded": discovery_excluded,
        "missing_exit_books": missing_exit_books,
        "funding_evidence_records": sum(
            len(cast(list[object], item["funding_evidence"]))
            for item in exported
        ),
        "opportunities": exported,
    }
    payload["source_sha256"] = _sha256(payload)
    return payload
