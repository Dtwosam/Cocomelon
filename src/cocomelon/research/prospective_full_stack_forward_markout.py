from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Final, cast

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
from cocomelon.research.prospective_momentum_band_forward_markout import (
    FORWARD_HORIZONS_MS,
    MAX_MARK_LAG_MS,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    STRIKE_THRESHOLD,
    ProspectiveTwoStrikeStopFilterState,
    prospective_two_strike_prior_strikes_at,
)

ZERO: Final = Decimal("0")
MIN_SETTLED_PER_HORIZON: Final = 20
MIN_ADMIT_SETTLED_PER_HORIZON: Final = 5
MIN_BLOCK_SETTLED_PER_HORIZON: Final = 5
MIN_LONG_SETTLED_PER_HORIZON: Final = 5
MIN_SHORT_SETTLED_PER_HORIZON: Final = 5
MIN_MARKETS_PER_HORIZON: Final = 4
LONG_TREND_CARVEOUT_CANDIDATE_ID: Final = (
    "prospective-top10-two-strike-momentum-no-long-trend-v1"
)
MOMENTUM_INTEGRITY_REASONS: Final = frozenset(
    {
        "missing_feature_fail_open",
        "incomplete_feature_fail_open",
    }
)


class ProspectiveFullStackForwardMarkoutError(RuntimeError):
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
            raise ProspectiveFullStackForwardMarkoutError(
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
        raise ProspectiveFullStackForwardMarkoutError(
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
        raise ProspectiveFullStackForwardMarkoutError(
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


def _stop_path_overlay(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    path: ContinuousPaperOpeningOpportunityPath | None,
    markouts: dict[str, dict[str, object]],
) -> dict[str, object]:
    request = evidence.risk_request_object
    stop = request.strategy_decision.invalidation_price
    entry = request.entry_reference_price
    if stop is not None:
        if not stop.is_finite() or stop <= ZERO:
            raise ProspectiveFullStackForwardMarkoutError(
                "opening opportunity stop must be positive and finite"
            )
        if (
            request.strategy_decision.direction is Direction.LONG
            and stop >= entry
        ):
            raise ProspectiveFullStackForwardMarkoutError(
                "long opening opportunity stop must be below entry"
            )
        if (
            request.strategy_decision.direction is Direction.SHORT
            and stop <= entry
        ):
            raise ProspectiveFullStackForwardMarkoutError(
                "short opening opportunity stop must be above entry"
            )

    horizons: dict[str, dict[str, object]] = {}
    for horizon_ms in FORWARD_HORIZONS_MS:
        key = str(horizon_ms)
        target_at_ms = evidence.opportunity_timestamp_ms + horizon_ms
        markout = markouts[key]
        markout_status = markout.get("status")
        if stop is None:
            horizons[key] = {
                "status": "missing_stop",
                "target_at_ms": target_at_ms,
                "observed_mark_count": 0,
                "stop_crossed": None,
                "first_stop_cross_at_ms": None,
                "first_stop_cross_mark_px": None,
                "time_to_stop_ms": None,
                "survived_observed_marks_to_horizon": None,
            }
            continue
        if path is None:
            horizons[key] = {
                "status": "missing_path",
                "target_at_ms": target_at_ms,
                "observed_mark_count": 0,
                "stop_crossed": None,
                "first_stop_cross_at_ms": None,
                "first_stop_cross_mark_px": None,
                "time_to_stop_ms": None,
                "survived_observed_marks_to_horizon": None,
            }
            continue
        if horizon_ms > path.max_path_age_ms:
            horizons[key] = {
                "status": "unsupported_horizon",
                "target_at_ms": target_at_ms,
                "observed_mark_count": 0,
                "stop_crossed": None,
                "first_stop_cross_at_ms": None,
                "first_stop_cross_mark_px": None,
                "time_to_stop_ms": None,
                "survived_observed_marks_to_horizon": None,
            }
            continue
        if markout_status != "settled":
            horizons[key] = {
                "status": f"markout_{markout_status}",
                "target_at_ms": target_at_ms,
                "observed_mark_count": 0,
                "stop_crossed": None,
                "first_stop_cross_at_ms": None,
                "first_stop_cross_mark_px": None,
                "time_to_stop_ms": None,
                "survived_observed_marks_to_horizon": None,
            }
            continue

        causal_marks = tuple(
            item
            for item in path.marks
            if (
                evidence.opportunity_timestamp_ms
                < item.observed_at_ms
                <= target_at_ms
            )
        )
        if not causal_marks:
            horizons[key] = {
                "status": "no_causal_marks",
                "target_at_ms": target_at_ms,
                "observed_mark_count": 0,
                "stop_crossed": None,
                "first_stop_cross_at_ms": None,
                "first_stop_cross_mark_px": None,
                "time_to_stop_ms": None,
                "survived_observed_marks_to_horizon": None,
            }
            continue

        first_cross = next(
            (
                item
                for item in causal_marks
                if (
                    item.mark_px <= stop
                    if evidence.direction == "long"
                    else item.mark_px >= stop
                )
            ),
            None,
        )
        crossed = first_cross is not None
        horizons[key] = {
            "status": (
                "observed_stop_crossing"
                if crossed
                else "observed_path_survivor"
            ),
            "target_at_ms": target_at_ms,
            "observed_mark_count": len(causal_marks),
            "stop_crossed": crossed,
            "first_stop_cross_at_ms": (
                None
                if first_cross is None
                else first_cross.observed_at_ms
            ),
            "first_stop_cross_mark_px": (
                None
                if first_cross is None
                else str(first_cross.mark_px)
            ),
            "time_to_stop_ms": (
                None
                if first_cross is None
                else (
                    first_cross.observed_at_ms
                    - evidence.opportunity_timestamp_ms
                )
            ),
            "survived_observed_marks_to_horizon": not crossed,
        }

    return {
        "claim_scope": "observed_mark_stop_crossing_only",
        "original_stop_price": None if stop is None else str(stop),
        "entry_reference_price": str(entry),
        "horizons": horizons,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
    }


def _spread(
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
        decision = row.get("stack_decision")
        market = row.get("market")
        if (
            markout.get("status") != "settled"
            or not isinstance(raw_return, str)
            or decision not in {"ADMIT", "BLOCK"}
            or not isinstance(market, str)
        ):
            continue
        settled.append((decision, market, Decimal(raw_return)))

    full = _spread(settled)
    leave_one = tuple(
        candidate
        for index in range(len(settled))
        if (
            candidate := _spread(
                settled[:index] + settled[index + 1 :]
            )
        )
        is not None
    )
    markets = tuple(
        sorted({market for _decision, market, _value in settled})
    )
    leave_market = tuple(
        candidate
        for market in markets
        if (
            candidate := _spread(
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


def _horizon_summary(
    rows: tuple[dict[str, object], ...],
    *,
    horizon_ms: int,
    integrity_clean: bool,
) -> dict[str, object]:
    key = str(horizon_ms)
    decisions: dict[str, dict[str, object]] = {}
    settled_counts: dict[str, int] = {}
    settled_all: list[tuple[dict[str, object], Decimal]] = []
    for decision in ("ADMIT", "BLOCK"):
        values: list[Decimal] = []
        statuses: Counter[str] = Counter()
        by_direction: Counter[str] = Counter()
        markets: set[str] = set()
        for row in rows:
            if row["stack_decision"] != decision:
                continue
            markouts = row["markouts"]
            assert isinstance(markouts, dict)
            markout = markouts[key]
            assert isinstance(markout, dict)
            status = markout["status"]
            assert isinstance(status, str)
            statuses[status] += 1
            if status != "settled":
                continue
            raw = markout["directional_return"]
            if not isinstance(raw, str):
                raise ProspectiveFullStackForwardMarkoutError(
                    "settled markout is missing directional return"
                )
            value = Decimal(raw)
            values.append(value)
            settled_all.append((row, value))
            direction = row["direction"]
            market = row["market"]
            assert isinstance(direction, str)
            assert isinstance(market, str)
            by_direction[direction] += 1
            markets.add(market)
        mean_value = _mean(tuple(values))
        settled_counts[decision] = len(values)
        decisions[decision.lower()] = {
            "opportunities": sum(
                1 for row in rows if row["stack_decision"] == decision
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
            "settled_by_direction": dict(sorted(by_direction.items())),
            "market_count": len(markets),
        }

    robustness = _spread_robustness(rows, horizon_key=key)
    admit = decisions["admit"]
    block = decisions["block"]
    long_settled = sum(
        1
        for row, _value in settled_all
        if row["direction"] == Direction.LONG.value
    )
    short_settled = sum(
        1
        for row, _value in settled_all
        if row["direction"] == Direction.SHORT.value
    )
    markets = {
        row["market"]
        for row, _value in settled_all
        if isinstance(row["market"], str)
    }
    raw_admit_mean = admit["mean_directional_return"]
    raw_block_mean = block["mean_directional_return"]
    separation_positive = (
        isinstance(raw_admit_mean, str)
        and isinstance(raw_block_mean, str)
        and Decimal(raw_admit_mean) > ZERO
        and Decimal(raw_block_mean) < ZERO
        and Decimal(raw_admit_mean) - Decimal(raw_block_mean) > ZERO
    )
    sample_complete = (
        len(settled_all) >= MIN_SETTLED_PER_HORIZON
        and settled_counts["ADMIT"] >= MIN_ADMIT_SETTLED_PER_HORIZON
        and settled_counts["BLOCK"] >= MIN_BLOCK_SETTLED_PER_HORIZON
        and long_settled >= MIN_LONG_SETTLED_PER_HORIZON
        and short_settled >= MIN_SHORT_SETTLED_PER_HORIZON
        and len(markets) >= MIN_MARKETS_PER_HORIZON
    )
    opportunity_robust = (
        robustness["positive_after_removing_any_one_opportunity"]
        is True
    )
    market_robust = (
        robustness["positive_after_removing_any_one_market"]
        is True
    )
    return {
        "horizon_ms": horizon_ms,
        "admit": admit,
        "block": block,
        "settled_opportunities": len(settled_all),
        "long_settled": long_settled,
        "short_settled": short_settled,
        "market_count": len(markets),
        "spread_robustness": robustness,
        "review_readiness": {
            "sample_complete": sample_complete,
            "integrity_clean": integrity_clean,
            "separation_positive": separation_positive,
            "single_opportunity_robust": opportunity_robust,
            "single_market_robust": market_robust,
            "ready_for_early_evidence_review": (
                sample_complete
                and integrity_clean
                and separation_positive
                and opportunity_robust
                and market_robust
            ),
            "changes_closed_trade_readiness_gate": False,
        },
    }


def _risk_rejected_horizon_summary(
    rows: tuple[dict[str, object], ...],
    *,
    horizon_ms: int,
) -> dict[str, object]:
    base = _horizon_summary(
        rows,
        horizon_ms=horizon_ms,
        integrity_clean=True,
    )
    key = str(horizon_ms)
    reason_values: dict[str, list[Decimal]] = {}
    reason_opportunities: Counter[str] = Counter()
    reason_settled: Counter[str] = Counter()
    for row in rows:
        reasons = row.get("baseline_risk_reason_codes")
        if not isinstance(reasons, tuple):
            raise ProspectiveFullStackForwardMarkoutError(
                "risk-rejected row reasons must be a tuple"
            )
        for reason in reasons:
            if not isinstance(reason, str):
                raise ProspectiveFullStackForwardMarkoutError(
                    "risk-rejected reason must be a string"
                )
            reason_opportunities[reason] += 1
        markouts = row.get("markouts")
        if not isinstance(markouts, dict):
            continue
        markout = markouts.get(key)
        if not isinstance(markout, dict):
            continue
        raw_return = markout.get("directional_return")
        if markout.get("status") != "settled" or not isinstance(
            raw_return,
            str,
        ):
            continue
        value = Decimal(raw_return)
        for reason in reasons:
            reason_values.setdefault(reason, []).append(value)
            reason_settled[reason] += 1

    by_reason: dict[str, dict[str, object]] = {}
    for reason in sorted(reason_opportunities):
        values = tuple(reason_values.get(reason, ()))
        mean_value = _mean(values)
        by_reason[reason] = {
            "opportunities": reason_opportunities[reason],
            "settled": reason_settled[reason],
            "positive": sum(value > ZERO for value in values),
            "negative": sum(value < ZERO for value in values),
            "flat": sum(value == ZERO for value in values),
            "mean_directional_return": (
                None if mean_value is None else str(mean_value)
            ),
            "sum_directional_return": str(sum(values, ZERO)),
        }

    return {
        "horizon_ms": horizon_ms,
        "admit": base["admit"],
        "block": base["block"],
        "settled_opportunities": base["settled_opportunities"],
        "long_settled": base["long_settled"],
        "short_settled": base["short_settled"],
        "market_count": base["market_count"],
        "spread_robustness": base["spread_robustness"],
        "by_risk_reason": by_reason,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
    }


def _long_trend_carveout_rows(
    rows: Sequence[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    projected: list[dict[str, object]] = []
    for row in rows:
        decision = row.get("long_trend_carveout_decision")
        layer = row.get("long_trend_carveout_block_layer")
        if decision not in {"ADMIT", "BLOCK"}:
            continue
        if not isinstance(layer, str) or not layer:
            raise ProspectiveFullStackForwardMarkoutError(
                "long-trend carveout block layer is invalid"
            )
        item = dict(row)
        item["stack_decision"] = decision
        item["block_layer"] = layer
        projected.append(item)
    return tuple(projected)


def _long_trend_carveout_summary(
    rows: Sequence[dict[str, object]],
    *,
    integrity_clean: bool,
    momentum_integrity_misses: int,
) -> dict[str, object]:
    projected = _long_trend_carveout_rows(rows)
    decisions = Counter(
        str(row["stack_decision"]) for row in projected
    )
    layers = Counter(str(row["block_layer"]) for row in projected)
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "candidate_id": LONG_TREND_CARVEOUT_CANDIDATE_ID,
        "rule": {
            "remove_combined_long_trend_veto": True,
            "max_admitted_ordinal": 10,
            "preserve_two_strike_filter": True,
            "preserve_momentum_filter": True,
        },
        "stop_path_overlay": {
            "enabled": True,
            "claim_scope": "observed_mark_stop_crossing_only",
            "changes_execution": False,
            "changes_risk_limits": False,
            "changes_candidate_readiness": False,
        },
        "evaluated": len(projected),
        "admitted": decisions["ADMIT"],
        "blocked": decisions["BLOCK"],
        "block_layer_counts": dict(sorted(layers.items())),
        "momentum_feature_integrity_misses": (
            momentum_integrity_misses
        ),
        "integrity_clean": integrity_clean,
        "horizons": {
            str(horizon_ms): _horizon_summary(
                projected,
                horizon_ms=horizon_ms,
                integrity_clean=integrity_clean,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        },
    }


def _post_integrity_miss_summary(
    rows: Sequence[dict[str, object]],
    *,
    overlap_started_at_ms: int,
    last_miss_at_ms: int | None,
    long_trend_carveout: bool = False,
) -> dict[str, object]:
    started_at_ms = (
        overlap_started_at_ms
        if last_miss_at_ms is None
        else last_miss_at_ms + 1
    )
    clean_rows = tuple(
        row
        for row in rows
        if cast(int, row["timestamp_ms"]) >= started_at_ms
    )
    evaluated_rows = (
        _long_trend_carveout_rows(clean_rows)
        if long_trend_carveout
        else clean_rows
    )
    decisions = Counter(
        str(row["stack_decision"]) for row in evaluated_rows
    )
    layers = Counter(str(row["block_layer"]) for row in evaluated_rows)
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "boundary_known": True,
        "last_miss_at_ms": last_miss_at_ms,
        "started_at_ms": started_at_ms,
        "evaluated": len(evaluated_rows),
        "admitted": decisions["ADMIT"],
        "blocked": decisions["BLOCK"],
        "block_layer_counts": dict(sorted(layers.items())),
        "horizons": {
            str(horizon_ms): _horizon_summary(
                evaluated_rows,
                horizon_ms=horizon_ms,
                integrity_clean=True,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        },
    }


def prospective_full_stack_forward_markout_summary(
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
    momentum_feature_integrity_misses = 0
    integrity_last_miss_at_ms: int | None = None
    long_trend_carveout_momentum_last_miss_at_ms: int | None = None
    risk_rejected_missing_rank = 0
    risk_rejected_stale_rank = 0
    risk_rejected_momentum_feature_integrity_misses = 0
    journal_future_close_exposure_opportunities = 0
    risk_rejected_journal_future_close_exposure_opportunities = 0
    risk_rejected_integrity_last_miss_at_ms: int | None = None
    long_trend_carveout_momentum_integrity_misses = 0
    risk_rejected_long_trend_carveout_momentum_integrity_misses = 0
    carveout_momentum_last_miss_at_ms: (
        int | None
    ) = None
    risk_rejected_reason_counts: Counter[str] = Counter()
    block_layer_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    risk_rejected_block_layer_counts: Counter[str] = Counter()
    risk_rejected_decision_counts: Counter[str] = Counter()
    rows: list[dict[str, object]] = []
    risk_rejected_rows: list[dict[str, object]] = []

    for evidence in prospective:
        risk_approved = evidence.baseline_risk_approved

        # The journal contains only finalized trades, not an independently
        # replayable open-event stream. A trade finalized AFTER this
        # opportunity cannot prove that its opening was present in an
        # earlier historical journal snapshot. Reconstructing strike and
        # momentum decisions from its now-known opening can shift previously
        # terminal research rows across worker handoffs. Keep all original
        # economic rows, but mark that research cohort unfit for promotion.
        future_close_exposure = any(
            trade.opened_at_ms >= overlap_start
            and trade.opened_at_ms < evidence.opportunity_timestamp_ms
            and trade.closed_at_ms > evidence.opportunity_timestamp_ms
            and trade.market.canonical == evidence.market
            and trade.direction.value == evidence.direction
            for trade in ordered_trades
        )
        if future_close_exposure:
            if risk_approved:
                journal_future_close_exposure_opportunities += 1
                integrity_last_miss_at_ms = max(
                    evidence.opportunity_timestamp_ms,
                    integrity_last_miss_at_ms
                    if integrity_last_miss_at_ms is not None
                    else evidence.opportunity_timestamp_ms,
                )
            else:
                risk_rejected_journal_future_close_exposure_opportunities += 1
                risk_rejected_integrity_last_miss_at_ms = max(
                    evidence.opportunity_timestamp_ms,
                    risk_rejected_integrity_last_miss_at_ms
                    if risk_rejected_integrity_last_miss_at_ms is not None
                    else evidence.opportunity_timestamp_ms,
                )
        if not risk_approved:
            baseline_risk_rejected += 1
            risk_rejected_reason_counts.update(
                evidence.baseline_risk_reason_codes
            )

        observed_at = evidence.rank_observed_at_ms
        ordinal = evidence.rank_ordinal
        if observed_at is None or ordinal is None:
            if risk_approved:
                missing_rank += 1
                integrity_last_miss_at_ms = max(
                    evidence.opportunity_timestamp_ms,
                    integrity_last_miss_at_ms
                    if integrity_last_miss_at_ms is not None
                    else evidence.opportunity_timestamp_ms,
                )
            else:
                risk_rejected_missing_rank += 1
                risk_rejected_integrity_last_miss_at_ms = max(
                    evidence.opportunity_timestamp_ms,
                    risk_rejected_integrity_last_miss_at_ms
                    if risk_rejected_integrity_last_miss_at_ms is not None
                    else evidence.opportunity_timestamp_ms,
                )
            continue
        rank_age_ms = evidence.opportunity_timestamp_ms - observed_at
        if rank_age_ms < 0:
            raise ProspectiveFullStackForwardMarkoutError(
                "opening opportunity rank is from the future"
            )
        if rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            if risk_approved:
                stale_rank += 1
                integrity_last_miss_at_ms = max(
                    evidence.opportunity_timestamp_ms,
                    integrity_last_miss_at_ms
                    if integrity_last_miss_at_ms is not None
                    else evidence.opportunity_timestamp_ms,
                )
            else:
                risk_rejected_stale_rank += 1
                risk_rejected_integrity_last_miss_at_ms = max(
                    evidence.opportunity_timestamp_ms,
                    risk_rejected_integrity_last_miss_at_ms
                    if risk_rejected_integrity_last_miss_at_ms is not None
                    else evidence.opportunity_timestamp_ms,
                )
            continue

        request = evidence.risk_request_object
        direction = request.strategy_decision.direction
        if direction is Direction.NO_TRADE:
            raise ProspectiveFullStackForwardMarkoutError(
                "opening opportunity direction cannot be no-trade"
            )
        if (
            request.strategy_decision.market.canonical != evidence.market
            or direction.value != evidence.direction
            or request.strategy_decision.feature_snapshot_id
            != evidence.feature_snapshot_id
        ):
            raise ProspectiveFullStackForwardMarkoutError(
                "opening opportunity decision lineage mismatch"
            )

        # Only terminal trades known by this opportunity's clock may
        # participate in retrospective reconstruction. Later-finalized
        # trades can carry earlier openings, but those openings were not
        # recorded in the *terminal-only* journal when first observed.
        # See future_close_exposure: if that uncertainty exists, research
        # stays dirty even after rebuilding the same conservative result.
        decision_time_closed_trades = tuple(
            trade
            for trade in ordered_trades
            if trade.closed_at_ms <= evidence.opportunity_timestamp_ms
        )

        combined_reason = prospective_combined_block_reason(
            direction=direction,
            lead_strategy=evidence.lead_strategy,
            ordinal=ordinal,
        )
        prior_two_strikes = prospective_two_strike_prior_strikes_at(
            decision_time_closed_trades,
            two_strike_state,
            market=evidence.market,
            direction=direction,
            timestamp_ms=evidence.opportunity_timestamp_ms,
        )

        momentum_detail: dict[str, object] | None = None
        momentum_reason: str | None = None
        momentum_decision: str | None = None
        if combined_reason is not None:
            stack_decision = "BLOCK"
            block_layer = "combined"
        elif prior_two_strikes >= STRIKE_THRESHOLD:
            stack_decision = "BLOCK"
            block_layer = "two_strike"
        else:
            momentum_detail = prospective_momentum_band_opportunity_decision(
                decision_time_closed_trades,
                feature_store,
                momentum_state,
                market=request.strategy_decision.market,
                direction=direction,
                timestamp_ms=evidence.opportunity_timestamp_ms,
                feature_snapshot_id=evidence.feature_snapshot_id,
            )
            raw_reason = momentum_detail.get("reason")
            raw_decision = momentum_detail.get("decision")
            if raw_reason in MOMENTUM_INTEGRITY_REASONS:
                if risk_approved:
                    momentum_feature_integrity_misses += 1
                    integrity_last_miss_at_ms = max(
                        evidence.opportunity_timestamp_ms,
                        integrity_last_miss_at_ms
                        if integrity_last_miss_at_ms is not None
                        else evidence.opportunity_timestamp_ms,
                    )
                else:
                    risk_rejected_momentum_feature_integrity_misses += 1
                    risk_rejected_integrity_last_miss_at_ms = max(
                        evidence.opportunity_timestamp_ms,
                        risk_rejected_integrity_last_miss_at_ms
                        if risk_rejected_integrity_last_miss_at_ms is not None
                        else evidence.opportunity_timestamp_ms,
                    )
                continue
            if raw_decision not in {"ADMIT", "BLOCK"}:
                raise ProspectiveFullStackForwardMarkoutError(
                    "momentum opportunity decision is invalid"
                )
            if not isinstance(raw_reason, str):
                raise ProspectiveFullStackForwardMarkoutError(
                    "momentum opportunity reason must be a string"
                )
            momentum_reason = raw_reason
            momentum_decision = raw_decision
            if raw_decision == "BLOCK":
                stack_decision = "BLOCK"
                block_layer = "momentum"
            else:
                stack_decision = "ADMIT"
                block_layer = "none"

        carveout_momentum_detail = momentum_detail
        carveout_momentum_reason = momentum_reason
        carveout_momentum_decision = momentum_decision
        carveout_decision: str | None
        carveout_block_layer: str | None
        if combined_reason == "long_trend":
            if prior_two_strikes >= STRIKE_THRESHOLD:
                carveout_decision = "BLOCK"
                carveout_block_layer = "two_strike"
            else:
                carveout_momentum_detail = (
                    prospective_momentum_band_opportunity_decision(
                        decision_time_closed_trades,
                        feature_store,
                        momentum_state,
                        market=request.strategy_decision.market,
                        direction=direction,
                        timestamp_ms=evidence.opportunity_timestamp_ms,
                        feature_snapshot_id=evidence.feature_snapshot_id,
                    )
                )
                carveout_raw_reason = carveout_momentum_detail.get(
                    "reason"
                )
                carveout_raw_decision = carveout_momentum_detail.get(
                    "decision"
                )
                if carveout_raw_reason in MOMENTUM_INTEGRITY_REASONS:
                    if risk_approved:
                        long_trend_carveout_momentum_integrity_misses += 1
                        long_trend_carveout_momentum_last_miss_at_ms = max(
                            evidence.opportunity_timestamp_ms,
                            (
                                long_trend_carveout_momentum_last_miss_at_ms
                                if long_trend_carveout_momentum_last_miss_at_ms
                                is not None
                                else evidence.opportunity_timestamp_ms
                            ),
                        )
                    else:
                        risk_rejected_long_trend_carveout_momentum_integrity_misses += 1
                        carveout_momentum_last_miss_at_ms = max(
                            evidence.opportunity_timestamp_ms,
                            (
                                carveout_momentum_last_miss_at_ms
                                if carveout_momentum_last_miss_at_ms
                                is not None
                                else evidence.opportunity_timestamp_ms
                            ),
                        )
                    carveout_decision = None
                    carveout_block_layer = None
                    carveout_momentum_reason = (
                        str(carveout_raw_reason)
                    )
                    carveout_momentum_decision = None
                else:
                    if carveout_raw_decision not in {
                        "ADMIT",
                        "BLOCK",
                    }:
                        raise ProspectiveFullStackForwardMarkoutError(
                            "long-trend carveout momentum decision is invalid"
                        )
                    if not isinstance(carveout_raw_reason, str):
                        raise ProspectiveFullStackForwardMarkoutError(
                            "long-trend carveout momentum reason must be a string"
                        )
                    carveout_momentum_reason = carveout_raw_reason
                    carveout_momentum_decision = (
                        carveout_raw_decision
                    )
                    if carveout_raw_decision == "BLOCK":
                        carveout_decision = "BLOCK"
                        carveout_block_layer = "momentum"
                    else:
                        carveout_decision = "ADMIT"
                        carveout_block_layer = "none"
        elif combined_reason is not None:
            carveout_decision = "BLOCK"
            carveout_block_layer = "rank_above_10"
        else:
            carveout_decision = stack_decision
            carveout_block_layer = block_layer

        if risk_approved:
            decision_counts[stack_decision] += 1
            block_layer_counts[block_layer] += 1
        else:
            risk_rejected_decision_counts[stack_decision] += 1
            risk_rejected_block_layer_counts[block_layer] += 1
        path = path_by_id.get(evidence.opportunity_id)
        markouts = {
            str(horizon_ms): _markout(
                evidence,
                path,
                horizon_ms=horizon_ms,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        }
        stop_path = _stop_path_overlay(
            evidence,
            path,
            markouts,
        )
        row = {
            "opportunity_id": evidence.opportunity_id,
            "timestamp_ms": evidence.opportunity_timestamp_ms,
            "market": evidence.market,
            "direction": evidence.direction,
            "lead_strategy": evidence.lead_strategy,
            "rank_ordinal": ordinal,
            "rank_age_ms": rank_age_ms,
            "baseline_risk_approved": risk_approved,
            "baseline_risk_reason_codes": (
                evidence.baseline_risk_reason_codes
            ),
            "combined_block_reason": combined_reason,
            "two_strike_prior_strikes": prior_two_strikes,
            "momentum_decision": momentum_decision,
            "momentum_reason": momentum_reason,
            "momentum_prior_strikes": (
                None
                if momentum_detail is None
                else momentum_detail.get("prior_strikes")
            ),
            "signed_return_1h": (
                None
                if momentum_detail is None
                else momentum_detail.get("signed_return_1h")
            ),
            "signed_day_return": (
                None
                if momentum_detail is None
                else momentum_detail.get("signed_day_return")
            ),
            "stack_decision": stack_decision,
            "block_layer": block_layer,
            "long_trend_carveout_candidate_id": (
                LONG_TREND_CARVEOUT_CANDIDATE_ID
            ),
            "long_trend_carveout_decision": carveout_decision,
            "long_trend_carveout_block_layer": (
                carveout_block_layer
            ),
            "long_trend_carveout_momentum_decision": (
                carveout_momentum_decision
            ),
            "long_trend_carveout_momentum_reason": (
                carveout_momentum_reason
            ),
            "long_trend_carveout_momentum_prior_strikes": (
                None
                if carveout_momentum_detail is None
                else carveout_momentum_detail.get("prior_strikes")
            ),
            "long_trend_carveout_signed_return_1h": (
                None
                if carveout_momentum_detail is None
                else carveout_momentum_detail.get("signed_return_1h")
            ),
            "long_trend_carveout_signed_day_return": (
                None
                if carveout_momentum_detail is None
                else carveout_momentum_detail.get("signed_day_return")
            ),
            "long_trend_carveout_stop_path": stop_path,
            "markouts": markouts,
        }
        if risk_approved:
            rows.append(row)
        else:
            risk_rejected_rows.append(row)

    row_values = tuple(rows)
    risk_rejected_row_values = tuple(risk_rejected_rows)
    integrity_clean = (
        missing_rank == 0
        and stale_rank == 0
        and momentum_feature_integrity_misses == 0
        and journal_future_close_exposure_opportunities == 0
    )
    horizons = {
        str(horizon_ms): _horizon_summary(
            row_values,
            horizon_ms=horizon_ms,
            integrity_clean=integrity_clean,
        )
        for horizon_ms in FORWARD_HORIZONS_MS
    }
    risk_rejected_integrity_clean = (
        risk_rejected_missing_rank == 0
        and risk_rejected_stale_rank == 0
        and risk_rejected_momentum_feature_integrity_misses == 0
        and risk_rejected_journal_future_close_exposure_opportunities == 0
    )
    risk_rejected_horizons = {
        str(horizon_ms): _risk_rejected_horizon_summary(
            risk_rejected_row_values,
            horizon_ms=horizon_ms,
        )
        for horizon_ms in FORWARD_HORIZONS_MS
    }
    long_trend_carveout_integrity_clean = (
        integrity_clean
        and long_trend_carveout_momentum_integrity_misses == 0
    )
    risk_rejected_long_trend_carveout_integrity_clean = (
        risk_rejected_integrity_clean
        and risk_rejected_long_trend_carveout_momentum_integrity_misses
        == 0
    )
    long_trend_carveout_integrity_last_miss_at_ms = (
        integrity_last_miss_at_ms
    )
    if (
        long_trend_carveout_momentum_last_miss_at_ms is not None
        and (
            long_trend_carveout_integrity_last_miss_at_ms is None
            or long_trend_carveout_momentum_last_miss_at_ms
            > long_trend_carveout_integrity_last_miss_at_ms
        )
    ):
        long_trend_carveout_integrity_last_miss_at_ms = (
            long_trend_carveout_momentum_last_miss_at_ms
        )
    post_integrity_miss = _post_integrity_miss_summary(
        row_values,
        overlap_started_at_ms=overlap_start,
        last_miss_at_ms=integrity_last_miss_at_ms,
    )
    long_trend_carveout_post_integrity_miss = (
        _post_integrity_miss_summary(
            row_values,
            overlap_started_at_ms=overlap_start,
            last_miss_at_ms=(
                long_trend_carveout_integrity_last_miss_at_ms
            ),
            long_trend_carveout=True,
        )
    )
    carveout_integrity_last_miss_at_ms = (
        risk_rejected_integrity_last_miss_at_ms
    )
    if (
        carveout_momentum_last_miss_at_ms
        is not None
        and (
            carveout_integrity_last_miss_at_ms
            is None
            or (
                carveout_momentum_last_miss_at_ms
                > carveout_integrity_last_miss_at_ms
            )
        )
    ):
        carveout_integrity_last_miss_at_ms = (
            carveout_momentum_last_miss_at_ms
        )
    long_trend_carveout = _long_trend_carveout_summary(
        row_values,
        integrity_clean=long_trend_carveout_integrity_clean,
        momentum_integrity_misses=(
            long_trend_carveout_momentum_integrity_misses
        ),
    )
    risk_rejected_long_trend_carveout = (
        _long_trend_carveout_summary(
            risk_rejected_row_values,
            integrity_clean=(
                risk_rejected_long_trend_carveout_integrity_clean
            ),
            momentum_integrity_misses=(
                risk_rejected_long_trend_carveout_momentum_integrity_misses
            ),
        )
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "candidate_stack": (
            "combined+two_strike+momentum"
        ),
        "overlap_started_at_ms": overlap_start,
        "combined_started_at_ms": combined_state.started_at_ms,
        "two_strike_started_at_ms": two_strike_state.started_at_ms,
        "momentum_started_at_ms": momentum_state.started_at_ms,
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "prospective_opportunities": len(prospective),
        "baseline_risk_rejected": baseline_risk_rejected,
        "risk_rejected_stack_evaluated": len(
            risk_rejected_row_values
        ),
        "risk_rejected_stack_admitted": (
            risk_rejected_decision_counts["ADMIT"]
        ),
        "risk_rejected_stack_blocked": (
            risk_rejected_decision_counts["BLOCK"]
        ),
        "risk_rejected_reason_counts": dict(
            sorted(risk_rejected_reason_counts.items())
        ),
        "risk_rejected_block_layer_counts": dict(
            sorted(risk_rejected_block_layer_counts.items())
        ),
        "risk_rejected_missing_rank": risk_rejected_missing_rank,
        "risk_rejected_stale_rank": risk_rejected_stale_rank,
        "risk_rejected_momentum_feature_integrity_misses": (
            risk_rejected_momentum_feature_integrity_misses
        ),
        "risk_rejected_journal_future_close_exposure_opportunities": (
            risk_rejected_journal_future_close_exposure_opportunities
        ),
        "risk_rejected_integrity_clean": (
            risk_rejected_integrity_clean
        ),
        "risk_rejected_integrity_last_miss_at_ms": (
            risk_rejected_integrity_last_miss_at_ms
        ),
        "risk_rejected_long_trend_carveout_integrity_last_miss_at_ms": (
            carveout_integrity_last_miss_at_ms
        ),
        "risk_rejected_horizons": risk_rejected_horizons,
        "risk_rejected_long_trend_carveout": (
            risk_rejected_long_trend_carveout
        ),
        "risk_rejected_rows": list(risk_rejected_row_values),
        "missing_rank": missing_rank,
        "stale_rank": stale_rank,
        "momentum_feature_integrity_misses": (
            momentum_feature_integrity_misses
        ),
        "stack_risk_approved_evaluated": len(row_values),
        "stack_admitted": decision_counts["ADMIT"],
        "stack_blocked": decision_counts["BLOCK"],
        "block_layer_counts": dict(sorted(block_layer_counts.items())),
        "integrity_clean": integrity_clean,
        "journal_future_close_exposure_opportunities": (
            journal_future_close_exposure_opportunities
        ),
        "journal_asof_provenance": "closed_trades_only_no_original_open_event_witness",
        "integrity_last_miss_at_ms": integrity_last_miss_at_ms,
        "post_integrity_miss": post_integrity_miss,
        "long_trend_carveout_integrity_last_miss_at_ms": (
            long_trend_carveout_integrity_last_miss_at_ms
        ),
        "long_trend_carveout_post_integrity_miss": (
            long_trend_carveout_post_integrity_miss
        ),
        "long_trend_carveout": long_trend_carveout,
        "horizons": horizons,
        "rows": list(row_values),
    }
