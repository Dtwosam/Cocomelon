from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Final, cast

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
)
from cocomelon.research.prospective_capacity_reflow_opportunities import (
    CapacityReleaseOpportunityOption,
    single_position_capacity_release_options,
)
from cocomelon.research.prospective_combined_entry_filter import (
    MAX_ACCEPTED_RANK_AGE_MS,
)

CORRELATION_BUCKET_REASON: Final = "correlation_bucket_exhausted"
HORIZONS_MS: Final = (300_000, 900_000, 3_600_000)
ZERO: Final = Decimal("0")


class ProspectiveCorrelationBucketPriorityError(RuntimeError):
    pass


def _closed_by_plan(
    trades: tuple[TradeJournalEntry, ...],
) -> dict[str, TradeJournalEntry]:
    output: dict[str, TradeJournalEntry] = {}
    for trade in trades:
        existing = output.get(trade.opening_plan_id)
        if existing is not None and existing != trade:
            raise ProspectiveCorrelationBucketPriorityError(
                "duplicate closed-trade opening plan lineage"
            )
        output[trade.opening_plan_id] = trade
    return output


def _active_lineage(
    option: CapacityReleaseOpportunityOption,
    lineages: tuple[ContinuousPaperOpeningLineage, ...],
    closed_by_plan: dict[str, TradeJournalEntry],
) -> ContinuousPaperOpeningLineage | None:
    matches: list[ContinuousPaperOpeningLineage] = []
    for lineage in lineages:
        if lineage.market != option.release_market:
            continue
        if lineage.opened_at_ms > option.opportunity_timestamp_ms:
            continue
        closed = closed_by_plan.get(lineage.opening_plan_id)
        if closed is not None:
            if (
                closed.market.canonical != lineage.market
                or closed.opened_at_ms != lineage.opened_at_ms
            ):
                raise ProspectiveCorrelationBucketPriorityError(
                    "closed trade does not match opening lineage"
                )
            if closed.closed_at_ms < option.opportunity_timestamp_ms:
                continue
        matches.append(lineage)
    if len(matches) > 1:
        raise ProspectiveCorrelationBucketPriorityError(
            "multiple active opening lineages for release market"
        )
    return None if not matches else matches[0]


def _row_reasons(row: dict[str, object]) -> tuple[str, ...]:
    raw = row.get("baseline_risk_reason_codes")
    if not isinstance(raw, (list, tuple)) or not all(
        isinstance(value, str) for value in raw
    ):
        raise ProspectiveCorrelationBucketPriorityError(
            "risk-rejected row reasons are invalid"
        )
    return tuple(raw)


def _row_markouts(row: dict[str, object]) -> dict[str, dict[str, object]]:
    raw = row.get("markouts")
    if not isinstance(raw, dict):
        raise ProspectiveCorrelationBucketPriorityError(
            "risk-rejected row markouts are invalid"
        )
    output: dict[str, dict[str, object]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ProspectiveCorrelationBucketPriorityError(
                "risk-rejected markout entry is invalid"
            )
        output[key] = cast(dict[str, object], value)
    return output


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _group_horizon(
    opportunities: tuple[dict[str, object], ...],
    *,
    horizon_ms: int,
) -> dict[str, object]:
    key = str(horizon_ms)
    grouped: dict[str, list[Decimal]] = {
        "priority_improves": [],
        "priority_not_improved": [],
    }
    for row in opportunities:
        group = (
            "priority_improves"
            if row["newcomer_outranks_any_releasable_holder"] is True
            else "priority_not_improved"
        )
        markouts = row["markouts"]
        assert isinstance(markouts, dict)
        markout = markouts.get(key)
        if not isinstance(markout, dict):
            continue
        raw_return = markout.get("directional_return")
        if markout.get("status") != "settled" or not isinstance(
            raw_return,
            str,
        ):
            continue
        grouped[group].append(Decimal(raw_return))

    payload: dict[str, object] = {"horizon_ms": horizon_ms}
    for group, raw_values in grouped.items():
        values = tuple(raw_values)
        mean = _mean(values)
        payload[group] = {
            "settled": len(values),
            "positive": sum(value > ZERO for value in values),
            "negative": sum(value < ZERO for value in values),
            "flat": sum(value == ZERO for value in values),
            "mean_directional_return": (
                None if mean is None else str(mean)
            ),
            "sum_directional_return": str(sum(values, ZERO)),
        }
    return payload


def prospective_correlation_bucket_priority_summary(
    forward_markout: dict[str, object],
    opportunities: tuple[ContinuousPaperOpeningOpportunityEvidence, ...],
    lineages: tuple[ContinuousPaperOpeningLineage, ...],
    closed_trades: tuple[TradeJournalEntry, ...],
    *,
    rank_loader: Callable[
        [str], ContinuousPaperOpeningRankEvidence | None
    ],
) -> dict[str, object]:
    if forward_markout.get("execution_authority") is not False:
        raise ProspectiveCorrelationBucketPriorityError(
            "forward markout has execution authority"
        )
    raw_rows = forward_markout.get("risk_rejected_rows")
    if not isinstance(raw_rows, list):
        raise ProspectiveCorrelationBucketPriorityError(
            "forward markout is missing risk-rejected rows"
        )

    opportunity_by_id = {
        item.opportunity_id: item
        for item in opportunities
    }
    if len(opportunity_by_id) != len(opportunities):
        raise ProspectiveCorrelationBucketPriorityError(
            "duplicate opening opportunity ids"
        )
    closed_by_plan = _closed_by_plan(closed_trades)

    selected_rows: list[dict[str, object]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise ProspectiveCorrelationBucketPriorityError(
                "risk-rejected row must be an object"
            )
        row = cast(dict[str, object], raw)
        if row.get("stack_decision") != "ADMIT":
            continue
        if CORRELATION_BUCKET_REASON not in _row_reasons(row):
            continue
        opportunity_id = row.get("opportunity_id")
        if not isinstance(opportunity_id, str):
            raise ProspectiveCorrelationBucketPriorityError(
                "risk-rejected row opportunity id is invalid"
            )
        evidence = opportunity_by_id.get(opportunity_id)
        if evidence is None:
            raise ProspectiveCorrelationBucketPriorityError(
                "stack-admitted correlation reject lost opportunity lineage"
            )
        if (
            evidence.market != row.get("market")
            or evidence.direction != row.get("direction")
            or evidence.opportunity_timestamp_ms != row.get("timestamp_ms")
        ):
            raise ProspectiveCorrelationBucketPriorityError(
                "forward markout opportunity lineage mismatch"
            )
        if evidence.rank_ordinal is None or evidence.rank_score is None:
            raise ProspectiveCorrelationBucketPriorityError(
                "priority audit requires newcomer rank evidence"
            )
        if evidence.rank_observed_at_ms is None:
            raise ProspectiveCorrelationBucketPriorityError(
                "priority audit requires newcomer rank timestamp"
            )
        newcomer_rank_age_ms = (
            evidence.opportunity_timestamp_ms
            - evidence.rank_observed_at_ms
        )
        if (
            newcomer_rank_age_ms < 0
            or newcomer_rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS
        ):
            raise ProspectiveCorrelationBucketPriorityError(
                "newcomer rank is stale or from the future"
            )

        release_rows: list[dict[str, object]] = []
        for option in single_position_capacity_release_options(evidence):
            lineage = _active_lineage(
                option,
                lineages,
                closed_by_plan,
            )
            if lineage is None:
                raise ProspectiveCorrelationBucketPriorityError(
                    "releasable holder lineage is missing"
                )
            rank = rank_loader(lineage.opening_plan_id)
            if rank is None:
                raise ProspectiveCorrelationBucketPriorityError(
                    "releasable holder opening rank is missing"
                )
            if (
                rank.market != option.release_market
                or rank.opened_at_ms != lineage.opened_at_ms
            ):
                raise ProspectiveCorrelationBucketPriorityError(
                    "releasable holder rank lineage mismatch"
                )
            if rank.rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
                raise ProspectiveCorrelationBucketPriorityError(
                    "releasable holder opening rank is stale"
                )
            release_rows.append(
                {
                    "release_market": option.release_market,
                    "release_opening_plan_id": lineage.opening_plan_id,
                    "release_opened_at_ms": lineage.opened_at_ms,
                    "release_position_age_ms": (
                        evidence.opportunity_timestamp_ms
                        - lineage.opened_at_ms
                    ),
                    "holder_rank_ordinal": rank.ordinal,
                    "holder_rank_score": str(rank.score),
                    "holder_rank_pool_size": rank.rank_pool_size,
                    "newcomer_rank_advantage": (
                        rank.ordinal - evidence.rank_ordinal
                    ),
                    "newcomer_score_advantage": str(
                        evidence.rank_score - rank.score
                    ),
                    "newcomer_outranks_holder": (
                        evidence.rank_ordinal < rank.ordinal
                    ),
                }
            )

        outranks_any = any(
            item["newcomer_outranks_holder"] is True
            for item in release_rows
        )
        selected_rows.append(
            {
                "opportunity_id": evidence.opportunity_id,
                "timestamp_ms": evidence.opportunity_timestamp_ms,
                "market": evidence.market,
                "direction": evidence.direction,
                "lead_strategy": evidence.lead_strategy,
                "newcomer_rank_ordinal": evidence.rank_ordinal,
                "newcomer_rank_score": str(evidence.rank_score),
                "newcomer_rank_pool_size": evidence.rank_pool_size,
                "releasable_holders": tuple(release_rows),
                "releasable_holder_count": len(release_rows),
                "newcomer_outranks_any_releasable_holder": outranks_any,
                "markouts": _row_markouts(row),
            }
        )

    ordered = tuple(
        sorted(
            selected_rows,
            key=lambda item: (
                cast(int, item["timestamp_ms"]),
                cast(str, item["market"]),
                cast(str, item["opportunity_id"]),
            ),
        )
    )
    release_options = sum(
        cast(int, item["releasable_holder_count"])
        for item in ordered
    )
    return {
        "research_only": True,
        "descriptive_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "changes_entry_priority": False,
        "replacement_execution_modeled": False,
        "replacement_exit_economics_modeled": False,
        "claim_scope": (
            "stack_admitted_correlation_bucket_priority_diagnostic"
        ),
        "stack_admitted_correlation_rejections": len(ordered),
        "releasable_holder_options": release_options,
        "opportunities_with_releasable_holder": sum(
            cast(int, item["releasable_holder_count"]) > 0
            for item in ordered
        ),
        "opportunities_outranking_any_releasable_holder": sum(
            item["newcomer_outranks_any_releasable_holder"] is True
            for item in ordered
        ),
        "by_horizon": {
            str(horizon_ms): _group_horizon(
                ordered,
                horizon_ms=horizon_ms,
            )
            for horizon_ms in HORIZONS_MS
        },
        "opportunities": ordered,
    }
