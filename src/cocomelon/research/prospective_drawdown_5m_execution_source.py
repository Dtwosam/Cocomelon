from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol, cast

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
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    execution_config_payload,
)

STATE_SCHEMA_VERSION: Final = 1
SOURCE_SCHEMA_VERSION: Final = 1
CANDIDATE_ID: Final = "weekly-drawdown-stack-admit-fixed-5m-v1"
SOURCE_KIND: Final = "prospective-drawdown-5m-execution-source-v1"
EXIT_HORIZON_MS: Final = 5 * 60 * 1_000
WEEKLY_DRAWDOWN_REASON: Final = "weekly_drawdown_lockout"


class ProspectiveDrawdown5mExecutionSourceError(RuntimeError):
    pass


class _OpportunityLike(Protocol):
    opportunity_id: str
    opportunity_timestamp_ms: int
    market: str
    direction: str
    lead_strategy: str
    baseline_risk_approved: bool
    baseline_risk_reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]: ...


class _ExitBookLike(Protocol):
    opportunity_id: str
    opportunity_timestamp_ms: int
    market: str
    direction: str
    horizon_ms: int
    target_at_ms: int
    observed_at_ms: int

    def to_dict(self) -> dict[str, object]: ...


class _FundingLike(Protocol):
    market: str
    boundary_ms: int

    def to_dict(self) -> dict[str, object]: ...


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


@dataclass(frozen=True, slots=True)
class ProspectiveDrawdown5mExecutionState:
    started_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID
    exit_horizon_ms: int = EXIT_HORIZON_MS

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("unsupported drawdown 5m state schema")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("unsupported drawdown 5m candidate")
        if self.exit_horizon_ms != EXIT_HORIZON_MS:
            raise ValueError("unsupported drawdown 5m exit horizon")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "exit_horizon_ms": self.exit_horizon_ms,
            "rule": {
                "baseline_risk_reason": WEEKLY_DRAWDOWN_REASON,
                "entry_policy": "frozen_full_stack_admit",
                "risk_policy": "neutralize_weekly_drawdown_only",
                "exit_policy": "real_l2_reduce_only_ioc_at_fixed_5m",
                "funding_policy": "exact_captured_hourly_boundaries",
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveDrawdown5mExecutionState:
        if not isinstance(raw, dict):
            raise ProspectiveDrawdown5mExecutionSourceError(
                "drawdown 5m state must be an object"
            )
        expected_rule = {
            "baseline_risk_reason": WEEKLY_DRAWDOWN_REASON,
            "entry_policy": "frozen_full_stack_admit",
            "risk_policy": "neutralize_weekly_drawdown_only",
            "exit_policy": "real_l2_reduce_only_ioc_at_fixed_5m",
            "funding_policy": "exact_captured_hourly_boundaries",
        }
        if raw.get("rule") != expected_rule:
            raise ProspectiveDrawdown5mExecutionSourceError(
                "drawdown 5m frozen rule drift"
            )
        schema = raw.get("schema_version")
        started = raw.get("started_at_ms")
        candidate = raw.get("candidate_id")
        horizon = raw.get("exit_horizon_ms")
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise ProspectiveDrawdown5mExecutionSourceError(
                "drawdown 5m state schema must be an integer"
            )
        if isinstance(started, bool) or not isinstance(started, int):
            raise ProspectiveDrawdown5mExecutionSourceError(
                "drawdown 5m state start must be an integer"
            )
        if not isinstance(candidate, str):
            raise ProspectiveDrawdown5mExecutionSourceError(
                "drawdown 5m candidate id must be a string"
            )
        if isinstance(horizon, bool) or not isinstance(horizon, int):
            raise ProspectiveDrawdown5mExecutionSourceError(
                "drawdown 5m horizon must be an integer"
            )
        try:
            return cls(
                started_at_ms=started,
                schema_version=schema,
                candidate_id=candidate,
                exit_horizon_ms=horizon,
            )
        except ValueError as exc:
            raise ProspectiveDrawdown5mExecutionSourceError(str(exc)) from exc


def _is_weekly_stack_admit(row: dict[str, object]) -> bool:
    reasons = row.get("baseline_risk_reason_codes")
    return (
        row.get("baseline_risk_approved") is False
        and row.get("stack_decision") == "ADMIT"
        and row.get("block_layer") == "none"
        and isinstance(reasons, (list, tuple))
        and tuple(reasons) == (WEEKLY_DRAWDOWN_REASON,)
    )


def _opportunity_map(
    values: Sequence[_OpportunityLike],
) -> dict[str, _OpportunityLike]:
    output: dict[str, _OpportunityLike] = {}
    for value in values:
        existing = output.get(value.opportunity_id)
        if existing is not None and existing != value:
            raise ProspectiveDrawdown5mExecutionSourceError(
                "duplicate opening opportunity evidence"
            )
        output[value.opportunity_id] = value
    return output


def _exit_book_map(
    values: Sequence[_ExitBookLike],
) -> dict[str, _ExitBookLike]:
    output: dict[str, _ExitBookLike] = {}
    for value in values:
        if value.horizon_ms != EXIT_HORIZON_MS:
            continue
        existing = output.get(value.opportunity_id)
        if existing is not None and existing != value:
            raise ProspectiveDrawdown5mExecutionSourceError(
                "duplicate 5m exit book evidence"
            )
        output[value.opportunity_id] = value
    return output


def prospective_drawdown_5m_execution_source(
    full_stack_summary: object,
    opportunities: Sequence[
        ContinuousPaperOpeningOpportunityEvidence
    ] | Sequence[_OpportunityLike],
    exit_books: Sequence[
        OpeningOpportunityExitBookEvidence
    ] | Sequence[_ExitBookLike],
    funding_records: Sequence[
        ReplacementFundingBoundaryEvidence
    ] | Sequence[_FundingLike],
    execution_config: PaperExecutionConfig,
    state: ProspectiveDrawdown5mExecutionState,
) -> dict[str, object]:
    if not isinstance(full_stack_summary, dict):
        raise ProspectiveDrawdown5mExecutionSourceError(
            "full-stack summary must be an object"
        )
    if (
        full_stack_summary.get("enabled") is not True
        or full_stack_summary.get("error") is not None
    ):
        raise ProspectiveDrawdown5mExecutionSourceError(
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
            raise ProspectiveDrawdown5mExecutionSourceError(
                f"full-stack authority drift: {key}"
            )

    raw_rows = full_stack_summary.get("risk_rejected_rows")
    if not isinstance(raw_rows, list):
        raise ProspectiveDrawdown5mExecutionSourceError(
            "risk-rejected full-stack rows are missing"
        )
    opportunity_map = _opportunity_map(
        cast(Sequence[_OpportunityLike], opportunities)
    )
    exit_map = _exit_book_map(
        cast(Sequence[_ExitBookLike], exit_books)
    )

    exported: list[dict[str, object]] = []
    discovery_rows_excluded = 0
    missing_exit_books = 0
    selected_markets: set[str] = set()

    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise ProspectiveDrawdown5mExecutionSourceError(
                "risk-rejected full-stack row must be an object"
            )
        if not _is_weekly_stack_admit(raw_row):
            continue
        timestamp_ms = raw_row.get("timestamp_ms")
        opportunity_id = raw_row.get("opportunity_id")
        if (
            isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, int)
            or timestamp_ms < 0
            or not isinstance(opportunity_id, str)
            or not opportunity_id
        ):
            raise ProspectiveDrawdown5mExecutionSourceError(
                "eligible full-stack row identity is invalid"
            )
        if timestamp_ms < state.started_at_ms:
            discovery_rows_excluded += 1
            continue

        evidence = opportunity_map.get(opportunity_id)
        if evidence is None:
            raise ProspectiveDrawdown5mExecutionSourceError(
                "opening opportunity evidence is missing"
            )
        if (
            evidence.opportunity_timestamp_ms != timestamp_ms
            or evidence.market != raw_row.get("market")
            or evidence.direction != raw_row.get("direction")
            or evidence.lead_strategy != raw_row.get("lead_strategy")
            or evidence.baseline_risk_approved
            or evidence.baseline_risk_reason_codes
            != (WEEKLY_DRAWDOWN_REASON,)
        ):
            raise ProspectiveDrawdown5mExecutionSourceError(
                "opening opportunity lineage mismatch"
            )

        exit_book = exit_map.get(opportunity_id)
        if exit_book is None:
            missing_exit_books += 1
        elif (
            exit_book.opportunity_timestamp_ms != timestamp_ms
            or exit_book.market != evidence.market
            or exit_book.direction != evidence.direction
            or exit_book.target_at_ms != timestamp_ms + EXIT_HORIZON_MS
            or exit_book.observed_at_ms < exit_book.target_at_ms
        ):
            raise ProspectiveDrawdown5mExecutionSourceError(
                "5m exit book lineage mismatch"
            )

        selected_markets.add(evidence.market)
        exported.append(
            {
                "opportunity_id": opportunity_id,
                "lineage": {
                    "timestamp_ms": timestamp_ms,
                    "market": raw_row.get("market"),
                    "direction": raw_row.get("direction"),
                    "lead_strategy": raw_row.get("lead_strategy"),
                    "rank_ordinal": raw_row.get("rank_ordinal"),
                    "rank_age_ms": raw_row.get("rank_age_ms"),
                    "baseline_risk_reason_codes": list(
                        cast(
                            list[str] | tuple[str, ...],
                            raw_row[
                                "baseline_risk_reason_codes"
                            ],
                        )
                    ),
                    "stack_decision": "ADMIT",
                    "block_layer": "none",
                },
                "opportunity": evidence.to_dict(),
                "exit_book": (
                    None if exit_book is None else exit_book.to_dict()
                ),
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
            cast(str, item["opportunity_id"]),
        )
    )
    ids = tuple(cast(str, item["opportunity_id"]) for item in exported)
    if len(ids) != len(set(ids)):
        raise ProspectiveDrawdown5mExecutionSourceError(
            "duplicate exported opportunity id"
        )

    selected_funding = [
        value.to_dict()
        for value in funding_records
        if value.market in selected_markets
    ]
    selected_funding.sort(
        key=lambda item: (
            cast(int, item["boundary_ms"]),
            cast(str, item["market"]),
        )
    )

    config_payload = execution_config_payload(execution_config)
    payload: dict[str, object] = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "kind": SOURCE_KIND,
        "candidate_id": CANDIDATE_ID,
        "started_at_ms": state.started_at_ms,
        "exit_horizon_ms": EXIT_HORIZON_MS,
        "baseline_risk_reason": WEEKLY_DRAWDOWN_REASON,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "discovery_cohort_reused_for_validation": False,
        "execution_config": config_payload,
        "execution_config_sha256": _sha256(config_payload),
        "source_opportunity_count": len(exported),
        "discovery_rows_excluded": discovery_rows_excluded,
        "missing_exit_books": missing_exit_books,
        "funding_evidence_count": len(selected_funding),
        "opportunities": exported,
        "funding_evidence": selected_funding,
    }
    payload["source_sha256"] = _sha256(payload)
    return payload
