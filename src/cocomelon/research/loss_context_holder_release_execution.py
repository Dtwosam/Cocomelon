from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Final

from cocomelon.research.continuous_paper_capacity_release_books import (
    CapacityReleaseBookEvidence,
)
from cocomelon.research.correlation_holder_release_execution import (
    correlation_holder_release_execution_summary,
)
from cocomelon.research.loss_context_candidate import (
    LossContextCandidateFreeze,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    CandidateCausedCapacityRelease,
)

ZERO: Final = Decimal("0")
LOSS_CONTEXT_HOLDER_RELEASE_EXECUTION_SCHEMA_VERSION: Final = 1


class LossContextHolderReleaseExecutionError(RuntimeError):
    pass


def _release_key(
    release: CandidateCausedCapacityRelease,
) -> tuple[str, str]:
    return release.opportunity_id, release.release_opening_plan_id


def _evidence_key(
    evidence: CapacityReleaseBookEvidence,
) -> tuple[str, str]:
    return (
        evidence.registration.opportunity_id,
        evidence.release_opening_plan_id,
    )


def _count(payload: dict[str, object], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LossContextHolderReleaseExecutionError(
            f"{field} must be a non-negative integer"
        )
    return value


def _validate_release(
    release: CandidateCausedCapacityRelease,
    freeze: LossContextCandidateFreeze,
) -> None:
    if release.opportunity_timestamp_ms < freeze.prospective_not_before_ms:
        raise LossContextHolderReleaseExecutionError(
            "loss-context release predates prospective boundary"
        )
    if release.release_block_reason != "frozen_loss_context":
        raise LossContextHolderReleaseExecutionError(
            "loss-context release has invalid causal reason"
        )


def loss_context_holder_release_execution_summary(
    releases: tuple[CandidateCausedCapacityRelease, ...],
    evidence: tuple[CapacityReleaseBookEvidence, ...],
    *,
    freeze: LossContextCandidateFreeze,
) -> dict[str, object]:
    release_by_key: dict[
        tuple[str, str],
        CandidateCausedCapacityRelease,
    ] = {}
    for release in releases:
        _validate_release(release, freeze)
        key = _release_key(release)
        if key in release_by_key:
            raise LossContextHolderReleaseExecutionError(
                "duplicate causal release option"
            )
        release_by_key[key] = release

    evidence_by_key: dict[
        tuple[str, str],
        CapacityReleaseBookEvidence,
    ] = {}
    for item in evidence:
        key = _evidence_key(item)
        if key not in release_by_key:
            continue
        if key in evidence_by_key:
            raise LossContextHolderReleaseExecutionError(
                "duplicate captured release execution evidence"
            )
        release = release_by_key[key]
        registration = item.registration
        if (
            registration.opportunity_timestamp_ms
            != release.opportunity_timestamp_ms
            or registration.opportunity_market
            != release.opportunity_market
            or registration.release_market != release.release_market
            or registration.release_correlation_bucket
            != release.release_correlation_bucket
        ):
            raise LossContextHolderReleaseExecutionError(
                "captured release evidence lineage mismatch"
            )
        evidence_by_key[key] = item

    missing_keys = tuple(
        sorted(set(release_by_key) - set(evidence_by_key))
    )
    by_execution_result: Counter[str] = Counter()
    by_release_market: Counter[str] = Counter()
    by_opportunity_market: Counter[str] = Counter()
    release_results: list[dict[str, object]] = []
    full_close_release_options: list[dict[str, object]] = []

    exact_config_records = 0
    unbound_config_records = 0
    config_mismatch_records = 0
    planned = 0
    planning_rejected = 0
    full_fills = 0
    partial_fills = 0
    no_fills = 0
    execution_rejections = 0
    gross_realized_pnl = ZERO
    close_fees = ZERO
    full_close_terminal_contribution = ZERO
    unclosed_quantity = ZERO

    for key in sorted(evidence_by_key):
        release = release_by_key[key]
        item = evidence_by_key[key]
        replay = correlation_holder_release_execution_summary((item,))
        rows = replay.get("release_results")
        if not isinstance(rows, list) or len(rows) != 1:
            raise LossContextHolderReleaseExecutionError(
                "holder release replay did not return exactly one row"
            )
        row = rows[0]
        if not isinstance(row, dict):
            raise LossContextHolderReleaseExecutionError(
                "holder release replay row is invalid"
            )
        option_id = f"{release.opportunity_id}:{release.release_opening_plan_id}"
        enriched = dict(row)
        enriched["release_option_id"] = option_id
        enriched["candidate_id"] = freeze.candidate_id
        release_results.append(enriched)

        exact_config_records += int(
            replay.get("exact_execution_config_records", 0)
        )
        unbound_config_records += int(
            replay.get("unbound_execution_config_records", 0)
        )
        config_mismatch_records += int(
            replay.get("execution_config_mismatch_records", 0)
        )
        planned += _count(replay, "planned_release_exits")
        planning_rejected += int(
            replay.get("planning_rejected_release_exits", 0)
        )
        full_fills += _count(replay, "full_release_fills")
        partial_fills += _count(replay, "partial_release_fills")
        no_fills += _count(replay, "no_release_fills")
        execution_rejections += int(
            replay.get("execution_rejected_release_exits", 0)
        )
        gross_realized_pnl += Decimal(
            str(replay.get("gross_realized_pnl", "0"))
        )
        close_fees += Decimal(str(replay.get("close_fees", "0")))
        full_close_terminal_contribution += Decimal(
            str(
                replay.get(
                    "fully_closed_terminal_contribution",
                    "0",
                )
            )
        )
        unclosed_quantity += Decimal(
            str(replay.get("unclosed_quantity", "0"))
        )

        result = row.get("execution_result")
        if isinstance(result, str):
            by_execution_result[result] += 1
        by_release_market[release.release_market] += 1
        by_opportunity_market[release.opportunity_market] += 1

        if row.get("complete_close") is True:
            terminal = row.get("full_close_terminal_contribution")
            if not isinstance(terminal, str):
                raise LossContextHolderReleaseExecutionError(
                    "full close is missing terminal contribution"
                )
            full_close_release_options.append(
                {
                    "release_option_id": option_id,
                    "opportunity_id": release.opportunity_id,
                    "opportunity_timestamp_ms": (
                        release.opportunity_timestamp_ms
                    ),
                    "opportunity_market": release.opportunity_market,
                    "release_market": release.release_market,
                    "release_correlation_bucket": (
                        release.release_correlation_bucket
                    ),
                    "release_opening_plan_id": (
                        release.release_opening_plan_id
                    ),
                    "full_close_terminal_contribution": terminal,
                    "execution_result": row.get("execution_result"),
                }
            )

    captured = len(evidence_by_key)
    source_complete = len(missing_keys) == 0
    execution_config_complete = (
        captured == exact_config_records
        and unbound_config_records == 0
        and config_mismatch_records == 0
    )
    all_causal_releases_fully_executable = (
        bool(releases)
        and source_complete
        and execution_config_complete
        and full_fills == len(releases)
    )

    return {
        "candidate_id": freeze.candidate_id,
        "dimensions": freeze.dimensions,
        "values": freeze.values,
        "prospective_not_before_ms": freeze.prospective_not_before_ms,
        "research_only": True,
        "descriptive_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
        "claim_scope": (
            "exact_decision_time_execution_of_causally_attributed_"
            "loss_context_holder_releases"
        ),
        "causal_release_options": len(releases),
        "captured_release_books": captured,
        "missing_release_book_records": len(missing_keys),
        "missing_release_option_ids": [
            f"{opportunity_id}:{plan_id}"
            for opportunity_id, plan_id in missing_keys
        ],
        "source_complete": source_complete,
        "exact_execution_config_records": exact_config_records,
        "unbound_execution_config_records": unbound_config_records,
        "execution_config_mismatch_records": config_mismatch_records,
        "execution_config_complete": execution_config_complete,
        "planned_release_exits": planned,
        "planning_rejected_release_exits": planning_rejected,
        "full_release_fills": full_fills,
        "partial_release_fills": partial_fills,
        "no_release_fills": no_fills,
        "execution_rejected_release_exits": execution_rejections,
        "gross_realized_pnl": str(gross_realized_pnl),
        "close_fees": str(close_fees),
        "fully_closed_terminal_contribution": str(
            full_close_terminal_contribution
        ),
        "unclosed_quantity": str(unclosed_quantity),
        "by_execution_result": dict(sorted(by_execution_result.items())),
        "by_release_market": dict(sorted(by_release_market.items())),
        "by_opportunity_market": dict(
            sorted(by_opportunity_market.items())
        ),
        "release_results": sorted(
            release_results,
            key=lambda item: str(item["release_option_id"]),
        ),
        "full_close_release_options": sorted(
            full_close_release_options,
            key=lambda item: str(item["release_option_id"]),
        ),
        "exact_full_close_release_options": len(
            full_close_release_options
        ),
        "ready_for_replacement_entry_investigation": bool(
            full_close_release_options
        ),
        "all_causal_releases_fully_executable": (
            all_causal_releases_fully_executable
        ),
        "replacement_entry_fills_modeled": False,
        "replacement_exits_modeled": False,
        "replacement_pnl_modeled": False,
        "recursive_replacements_modeled": False,
        "schema_version": (
            LOSS_CONTEXT_HOLDER_RELEASE_EXECUTION_SCHEMA_VERSION
        ),
    }
