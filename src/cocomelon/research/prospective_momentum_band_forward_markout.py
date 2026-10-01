from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_combined_entry_filter import (
    MAX_ACCEPTED_RANK_AGE_MS,
    ProspectiveCombinedEntryFilterState,
    prospective_combined_block_reason,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
    prospective_momentum_band_opportunity_decision,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    STRIKE_THRESHOLD,
    ProspectiveTwoStrikeStopFilterState,
    prospective_two_strike_prior_strikes_at,
)

FORWARD_HORIZONS_MS: Final = (
    5 * 60 * 1_000,
    15 * 60 * 1_000,
    60 * 60 * 1_000,
)
MAX_MARK_LAG_MS: Final = 120_000
ZERO: Final = Decimal("0")
MOMENTUM_INTEGRITY_REASONS: Final = frozenset(
    {
        "missing_feature_fail_open",
        "incomplete_feature_fail_open",
    }
)


class ProspectiveMomentumBandForwardMarkoutError(RuntimeError):
    pass


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _path_map(
    paths: Sequence[ContinuousPaperOpeningOpportunityPath],
) -> dict[str, ContinuousPaperOpeningOpportunityPath]:
    output: dict[str, ContinuousPaperOpeningOpportunityPath] = {}
    for path in paths:
        if path.opportunity_id in output:
            raise ProspectiveMomentumBandForwardMarkoutError(
                "duplicate opening-opportunity forward path"
            )
        output[path.opportunity_id] = path
    return output


def _markout(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    path: ContinuousPaperOpeningOpportunityPath | None,
    *,
    horizon_ms: int,
) -> dict[str, object]:
    target_at_ms = evidence.opportunity_timestamp_ms + horizon_ms
    if path is None:
        return {
            "status": "missing_path",
            "target_at_ms": target_at_ms,
            "observed_at_ms": None,
            "observation_lag_ms": None,
            "mark_px": None,
            "directional_return": None,
        }
    if (
        path.market != evidence.market
        or path.direction != evidence.direction
        or path.opportunity_timestamp_ms
        != evidence.opportunity_timestamp_ms
    ):
        raise ProspectiveMomentumBandForwardMarkoutError(
            "opening-opportunity path lineage mismatch"
        )
    if horizon_ms > path.max_path_age_ms:
        return {
            "status": "unsupported_horizon",
            "target_at_ms": target_at_ms,
            "observed_at_ms": None,
            "observation_lag_ms": None,
            "mark_px": None,
            "directional_return": None,
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
            "target_at_ms": target_at_ms,
            "observed_at_ms": None,
            "observation_lag_ms": None,
            "mark_px": None,
            "directional_return": None,
        }
    lag_ms = mark.observed_at_ms - target_at_ms
    if lag_ms > MAX_MARK_LAG_MS:
        return {
            "status": "stale",
            "target_at_ms": target_at_ms,
            "observed_at_ms": mark.observed_at_ms,
            "observation_lag_ms": lag_ms,
            "mark_px": str(mark.mark_px),
            "directional_return": None,
        }

    request = evidence.risk_request_object
    entry = request.entry_reference_price
    direction = request.strategy_decision.direction
    if direction is Direction.LONG:
        signed = (mark.mark_px - entry) / entry
    elif direction is Direction.SHORT:
        signed = (entry - mark.mark_px) / entry
    else:
        raise ProspectiveMomentumBandForwardMarkoutError(
            "opening opportunity direction cannot be no-trade"
        )
    return {
        "status": "settled",
        "target_at_ms": target_at_ms,
        "observed_at_ms": mark.observed_at_ms,
        "observation_lag_ms": lag_ms,
        "mark_px": str(mark.mark_px),
        "directional_return": str(signed),
    }


def _spread_robustness(
    rows: tuple[dict[str, object], ...],
    *,
    horizon_key: str,
) -> dict[str, object]:
    settled: list[tuple[str, str, Decimal]] = []
    for row in rows:
        markouts = row.get("markouts")
        if not isinstance(markouts, dict):
            continue
        markout = markouts.get(horizon_key)
        if not isinstance(markout, dict):
            continue
        raw_return = markout.get("directional_return")
        if markout.get("status") != "settled" or not isinstance(
            raw_return,
            str,
        ):
            continue
        decision = row.get("momentum_decision")
        market = row.get("market")
        if decision not in {"ADMIT", "BLOCK"} or not isinstance(
            market,
            str,
        ):
            continue
        settled.append((decision, market, Decimal(raw_return)))

    def spread(
        values: Sequence[tuple[str, str, Decimal]],
    ) -> Decimal | None:
        admits = tuple(
            value
            for decision, _market, value in values
            if decision == "ADMIT"
        )
        blocks = tuple(
            value
            for decision, _market, value in values
            if decision == "BLOCK"
        )
        admit_mean = _mean(admits)
        block_mean = _mean(blocks)
        if admit_mean is None or block_mean is None:
            return None
        return admit_mean - block_mean

    full = spread(settled)
    leave_one = tuple(
        candidate
        for index in range(len(settled))
        if (
            candidate := spread(
                settled[:index] + settled[index + 1 :]
            )
        )
        is not None
    )
    markets = tuple(sorted({market for _d, market, _r in settled}))
    leave_market = tuple(
        candidate
        for market in markets
        if (
            candidate := spread(
                tuple(
                    item for item in settled if item[1] != market
                )
            )
        )
        is not None
    )
    return {
        "settled_opportunities": len(settled),
        "market_count": len(markets),
        "admit_minus_block_mean_return": (
            None if full is None else str(full)
        ),
        "leave_one_opportunity_min_spread": (
            None if not leave_one else str(min(leave_one))
        ),
        "positive_after_removing_any_one_opportunity": (
            len(leave_one) == len(settled)
            and bool(leave_one)
            and min(leave_one) > ZERO
        ),
        "leave_one_market_min_spread": (
            None if not leave_market else str(min(leave_market))
        ),
        "positive_after_removing_any_one_market": (
            len(leave_market) == len(markets)
            and bool(leave_market)
            and min(leave_market) > ZERO
        ),
    }


def prospective_momentum_band_forward_markout_summary(
    opportunities: Sequence[
        ContinuousPaperOpeningOpportunityEvidence
    ],
    paths: Sequence[ContinuousPaperOpeningOpportunityPath],
    closed_trades: Sequence[TradeJournalEntry],
    feature_store: LearningFeatureSnapshotStore,
    combined_state: ProspectiveCombinedEntryFilterState,
    two_strike_state: ProspectiveTwoStrikeStopFilterState,
    momentum_state: ProspectiveMomentumBandEntryState,
) -> dict[str, object]:
    overlap_start = max(
        combined_state.started_at_ms,
        two_strike_state.started_at_ms,
        momentum_state.started_at_ms,
    )
    path_by_id = _path_map(paths)
    ordered_trades = tuple(closed_trades)
    prospective = tuple(
        sorted(
            (
                evidence
                for evidence in opportunities
                if evidence.opportunity_timestamp_ms >= overlap_start
            ),
            key=lambda item: (
                item.opportunity_timestamp_ms,
                item.market,
                item.opportunity_id,
            ),
        )
    )

    baseline_risk_rejected = 0
    missing_rank = 0
    stale_rank = 0
    base_combined_blocked = 0
    base_two_strike_blocked = 0
    momentum_feature_integrity_misses = 0
    decision_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    rows: list[dict[str, object]] = []

    for evidence in prospective:
        if not evidence.baseline_risk_approved:
            baseline_risk_rejected += 1
            continue

        observed_at = evidence.rank_observed_at_ms
        ordinal = evidence.rank_ordinal
        if observed_at is None or ordinal is None:
            missing_rank += 1
            continue
        rank_age_ms = evidence.opportunity_timestamp_ms - observed_at
        if rank_age_ms < 0:
            raise ProspectiveMomentumBandForwardMarkoutError(
                "opening opportunity rank is from the future"
            )
        if rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            stale_rank += 1
            continue

        request = evidence.risk_request_object
        direction = request.strategy_decision.direction
        if direction is Direction.NO_TRADE:
            raise ProspectiveMomentumBandForwardMarkoutError(
                "opening opportunity direction cannot be no-trade"
            )
        if (
            request.strategy_decision.market.canonical != evidence.market
            or direction.value != evidence.direction
            or request.strategy_decision.feature_snapshot_id
            != evidence.feature_snapshot_id
        ):
            raise ProspectiveMomentumBandForwardMarkoutError(
                "opening opportunity decision lineage mismatch"
            )

        combined_reason = prospective_combined_block_reason(
            direction=direction,
            lead_strategy=evidence.lead_strategy,
            ordinal=ordinal,
        )
        if combined_reason is not None:
            base_combined_blocked += 1
            continue

        prior_two_strikes = prospective_two_strike_prior_strikes_at(
            ordered_trades,
            two_strike_state,
            market=evidence.market,
            direction=direction,
            timestamp_ms=evidence.opportunity_timestamp_ms,
        )
        if prior_two_strikes >= STRIKE_THRESHOLD:
            base_two_strike_blocked += 1
            continue

        momentum_detail = prospective_momentum_band_opportunity_decision(
            ordered_trades,
            feature_store,
            momentum_state,
            market=request.strategy_decision.market,
            direction=direction,
            timestamp_ms=evidence.opportunity_timestamp_ms,
            feature_snapshot_id=evidence.feature_snapshot_id,
        )
        reason = momentum_detail.get("reason")
        decision = momentum_detail.get("decision")
        if reason in MOMENTUM_INTEGRITY_REASONS:
            momentum_feature_integrity_misses += 1
            continue
        if decision not in {"ADMIT", "BLOCK"}:
            raise ProspectiveMomentumBandForwardMarkoutError(
                "momentum opportunity decision is invalid"
            )
        if not isinstance(reason, str):
            raise ProspectiveMomentumBandForwardMarkoutError(
                "momentum opportunity reason must be a string"
            )
        decision_counts[decision] += 1
        reason_counts[reason] += 1

        path = path_by_id.get(evidence.opportunity_id)
        markouts = {
            str(horizon_ms): _markout(
                evidence,
                path,
                horizon_ms=horizon_ms,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        }
        rows.append(
            {
                "opportunity_id": evidence.opportunity_id,
                "timestamp_ms": evidence.opportunity_timestamp_ms,
                "market": evidence.market,
                "direction": evidence.direction,
                "lead_strategy": evidence.lead_strategy,
                "rank_ordinal": ordinal,
                "rank_age_ms": rank_age_ms,
                "two_strike_prior_strikes": prior_two_strikes,
                "momentum_decision": decision,
                "momentum_reason": reason,
                "momentum_prior_strikes": momentum_detail.get(
                    "prior_strikes"
                ),
                "signed_return_1h": momentum_detail.get(
                    "signed_return_1h"
                ),
                "signed_day_return": momentum_detail.get(
                    "signed_day_return"
                ),
                "markouts": markouts,
            }
        )

    row_values = tuple(rows)
    horizon_summary: dict[str, dict[str, object]] = {}
    for horizon_ms in FORWARD_HORIZONS_MS:
        key = str(horizon_ms)
        decisions: dict[str, dict[str, object]] = {}
        for decision in ("ADMIT", "BLOCK"):
            values: list[Decimal] = []
            statuses: Counter[str] = Counter()
            by_direction: Counter[str] = Counter()
            for row in row_values:
                if row["momentum_decision"] != decision:
                    continue
                row_markouts = row["markouts"]
                assert isinstance(row_markouts, dict)
                markout = row_markouts[key]
                assert isinstance(markout, dict)
                status = markout["status"]
                assert isinstance(status, str)
                statuses[status] += 1
                if status != "settled":
                    continue
                raw = markout["directional_return"]
                if not isinstance(raw, str):
                    raise ProspectiveMomentumBandForwardMarkoutError(
                        "settled markout is missing directional return"
                    )
                values.append(Decimal(raw))
                row_direction = row["direction"]
                assert isinstance(row_direction, str)
                by_direction[row_direction] += 1
            mean_value = _mean(tuple(values))
            decisions[decision.lower()] = {
                "opportunities": sum(
                    1
                    for row in row_values
                    if row["momentum_decision"] == decision
                ),
                "settled": len(values),
                "positive": sum(value > ZERO for value in values),
                "negative": sum(value < ZERO for value in values),
                "flat": sum(value == ZERO for value in values),
                "mean_directional_return": (
                    None if mean_value is None else str(mean_value)
                ),
                "sum_directional_return": str(sum(values, ZERO)),
                "status_counts": dict(sorted(statuses.items())),
                "settled_by_direction": dict(
                    sorted(by_direction.items())
                ),
            }
        horizon_summary[key] = {
            "horizon_ms": horizon_ms,
            "admit": decisions["admit"],
            "block": decisions["block"],
            "spread_robustness": _spread_robustness(
                row_values,
                horizon_key=key,
            ),
        }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "candidate_id": momentum_state.candidate_id,
        "overlap_started_at_ms": overlap_start,
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "prospective_opportunities": len(prospective),
        "baseline_risk_rejected": baseline_risk_rejected,
        "missing_rank": missing_rank,
        "stale_rank": stale_rank,
        "base_combined_blocked": base_combined_blocked,
        "base_two_strike_blocked": base_two_strike_blocked,
        "momentum_feature_integrity_misses": (
            momentum_feature_integrity_misses
        ),
        "base_stack_risk_approved_evaluated": len(row_values),
        "momentum_admitted": decision_counts["ADMIT"],
        "momentum_blocked": decision_counts["BLOCK"],
        "momentum_reason_counts": dict(sorted(reason_counts.items())),
        "integrity_clean": (
            missing_rank == 0
            and stale_rank == 0
            and momentum_feature_integrity_misses == 0
        ),
        "horizons": horizon_summary,
        "rows": list(row_values),
    }
