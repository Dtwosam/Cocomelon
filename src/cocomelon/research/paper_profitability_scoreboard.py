"""Research-only after-cost original-paper-journal profitability attribution.

The input is the *complete*, authenticated post-handoff all-trade chart
audit. Missing entry context and incomplete charts never remove losers.
This module does not recommend or simulate skip-only strategy changes.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Final, cast

from cocomelon.domain.journal import AUTHORITATIVE_CONTEXT
from cocomelon.research.prospective_short_breakout_rank import (
    MIN_FUTURE as SHORT_MIN_FUTURE,
)
from cocomelon.research.prospective_short_breakout_rank import (
    ProspectiveShortBreakoutRankState,
)
from cocomelon.research.prospective_trend_outside_top10 import (
    MIN_CLOSED as TREND_MIN_CLOSED,
)
from cocomelon.research.prospective_trend_outside_top10 import (
    ProspectiveTrendOutsideTop10State,
)

ZERO: Final = Decimal("0")
# The completed 176-close authenticated original audit contains 16
# nonzero per-trade residuals, maximum abs 5E-27. Preserve those actual
# booked sub-cent residuals, but prevent compensating material distortions
# from laundering strategy/rank cohort PnL through a zero whole-journal sum.
MAX_PER_TRADE_NET_CASH_RESIDUAL: Final = Decimal("1E-18")
UNVERIFIED: Final = "UNVERIFIED_ENTRY_CONTEXT"
# Pre-registered on 2026-10-11 before its trial start; the 9 historical
# losing mean-reversion trades are DISCOVERY only, never prospective rows.
MEAN_REVERSION_DISCOVERY_FREEZE_MS: Final = 1_791_720_000_000  # Oct 11 12:00 UTC
MEAN_REVERSION_EMBARGO_MS: Final = 6 * 3_600_000
MEAN_REVERSION_FIXED_OPENING_DAY_MS: Final = 24 * 3_600_000
MEAN_REVERSION_FIXED_OPENING_WEEK_MS: Final = 7 * MEAN_REVERSION_FIXED_OPENING_DAY_MS
MEAN_REVERSION_FORWARD_START_MS: Final = (
    MEAN_REVERSION_DISCOVERY_FREEZE_MS + MEAN_REVERSION_EMBARGO_MS
)


class PaperProfitabilityScoreboardError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _Trade:
    trade_id: str
    market: str
    side: str
    opened_at_ms: int
    closed_at_ms: int
    lead_strategy: str
    rank_band: str
    exit_reason: str
    verified_context: bool
    original_decision_source_match: bool
    rank_missing: bool
    chart_complete: bool
    gross: Decimal
    fees: Decimal
    funding: Decimal
    net: Decimal
    net_r: Decimal
    net_cash_residual: Decimal


def _object(raw: object, label: str) -> dict[str, object]:
    if not isinstance(raw, dict) or any(not isinstance(k, str) for k in raw):
        raise PaperProfitabilityScoreboardError(f"{label} must be an object")
    return cast(dict[str, object], raw)


def _integer(raw: object, label: str) -> int:
    if type(raw) is not int or raw < 0:
        raise PaperProfitabilityScoreboardError(
            f"{label} must be a non-negative integer"
        )
    return raw


def _number(raw: object, label: str) -> Decimal:
    if not isinstance(raw, str):
        raise PaperProfitabilityScoreboardError(
            f"{label} must be a booked decimal string"
        )
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise PaperProfitabilityScoreboardError(
            f"{label} must be a decimal"
        ) from exc
    if not value.is_finite():
        raise PaperProfitabilityScoreboardError(f"{label} must be finite")
    return value


def _text(raw: object, label: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise PaperProfitabilityScoreboardError(f"{label} must be nonempty text")
    return raw


def _verified_chart_complete_claim(row: dict[str, object], chart: bool) -> None:
    """Validate necessary independent chart witnesses, not a synthetic exit.

    The source chart auditor establishes complete-path status from the full
    contemporaneous mark sequence. This downstream booked-PnL report must not
    trust a flipped coverage label without its recorded supporting witnesses.
    Passing the checks is necessary, never proof of executable exit coverage
    or an independently authenticated input artifact.
    """
    present = row.get("chart_path_present")
    if type(present) is not bool:
        raise PaperProfitabilityScoreboardError(
            "original chart path presence witness must be boolean"
        )
    mark_count = _integer(
        row.get("chart_mark_count"), "original chart mark count"
    )
    samples = row.get("chart_mark_samples")
    if not isinstance(samples, list) or len(samples) > 144 or any(
        not isinstance(sample, list)
        or len(sample) != 2
        or type(sample[0]) is not int
        or sample[0] < 0
        or not isinstance(sample[1], str)
        or not sample[1]
        for sample in samples
    ):
        raise PaperProfitabilityScoreboardError(
            "original compact mark sample witness malformed"
        )
    times = [sample[0] for sample in samples]
    if any(later < earlier for earlier, later in zip(times, times[1:], strict=False)):
        raise PaperProfitabilityScoreboardError(
            "original compact mark sample chronology invalid"
        )
    if len(samples) > mark_count:
        raise PaperProfitabilityScoreboardError(
            "original compact samples exceed recorded raw marks"
        )
    gap_raw = row.get("chart_known_gap_duration_ms")
    gap_ms = (
        None if gap_raw is None else
        _integer(gap_raw, "original chart known gap duration")
    )
    longest_raw = row.get("chart_longest_unobserved_mark_ms")
    longest_ms = (
        None if longest_raw is None else
        _integer(longest_raw, "original chart longest unobserved mark interval")
    )
    before = _integer(
        row.get("chart_unresolved_gap_starts_before_entry"),
        "original chart unresolved pre-entry gap count",
    )
    during = _integer(
        row.get("chart_unresolved_gap_starts_during_position"),
        "original chart unresolved in-position gap count",
    )
    silent = row.get("chart_silent_gap_intervals_ms")
    if not isinstance(silent, list) or any(
        not isinstance(item, list)
        or len(item) != 2
        or any(type(value) is not int or value < 0 for value in item)
        or item[1] < item[0]
        for item in silent
    ):
        raise PaperProfitabilityScoreboardError(
            "original chart silent gap intervals malformed"
        )
    if chart and not (
        present
        and mark_count >= 2
        and len(samples) >= 2
        and times[0] < times[-1]
        and gap_ms == 0
        and longest_ms is not None
        and longest_ms <= 300_000
        and before == 0
        and during == 0
        and not silent
    ):
        raise PaperProfitabilityScoreboardError(
            "claimed complete original price path contradicts recorded "
            "mark or known-gap witnesses"
        )
    if not present and (
        mark_count != 0 or samples or gap_ms is not None
        or longest_ms is not None or before != 0 or during != 0 or silent
    ):
        raise PaperProfitabilityScoreboardError(
            "missing original price path contradicts recorded witnesses"
        )


def _trade(raw: object) -> _Trade:
    row = _object(raw, "original trade")
    trade_id = _text(row.get("trade_id"), "trade ID")
    market = _text(row.get("market"), "market")
    side = _text(row.get("side"), "side")
    if side not in {"long", "short"}:
        raise PaperProfitabilityScoreboardError("unsupported original trade side")
    opened = _integer(row.get("opened_at_ms"), "opened_at_ms")
    closed = _integer(row.get("closed_at_ms"), "closed_at_ms")
    if closed < opened:
        raise PaperProfitabilityScoreboardError("trade closed before opening")
    # Exit reasons are only known after an actual original trade exits.
    # NEVER use this downstream attribution as an entry-time feature.
    exit_reason = _text(row.get("exit_reason"), "original booked exit reason")
    gross = _number(row.get("gross_realized_pnl"), "gross realized PnL")
    entry_fee = _number(row.get("entry_fees"), "entry fee")
    exit_fee = _number(row.get("exit_fees"), "exit fee")
    if entry_fee < ZERO or exit_fee < ZERO:
        raise PaperProfitabilityScoreboardError("negative execution fee")
    funding = _number(row.get("funding_cash_pnl"), "funding")
    net = _number(row.get("net_pnl"), "booked net PnL")
    net_cash_residual = net - gross + entry_fee + exit_fee - funding
    if abs(net_cash_residual) > MAX_PER_TRADE_NET_CASH_RESIDUAL:
        raise PaperProfitabilityScoreboardError(
            "per-trade booked net cashflow residual exceeds "
            "authenticated source precision bound"
        )
    net_r = _number(row.get("net_r"), "booked net R")
    planned_risk = _number(
        row.get("initial_risk_amount"), "original immutable planned risk"
    )
    if planned_risk <= ZERO:
        raise PaperProfitabilityScoreboardError(
            "original immutable planned risk must be positive"
        )
    # The authentic journal uses exactly this Decimal context. Do not
    # derive or infer the risk denominator from a supplied R multiple.
    with localcontext(AUTHORITATIVE_CONTEXT):
        if net / planned_risk != net_r:
            raise PaperProfitabilityScoreboardError(
                "original booked net-R contradicts booked cash and "
                "immutable planned risk"
            )
    chart = row.get("chart_coverage_complete")
    if type(chart) is not bool:
        raise PaperProfitabilityScoreboardError(
            "chart completeness must be recorded"
        )
    _verified_chart_complete_claim(row, chart)
    context_raw = row.get("entry_context")
    lead, rank = UNVERIFIED, UNVERIFIED
    if context_raw is not None:
        context = _object(context_raw, "verified entry context")
        for field, expected in (
            ("trade_id", trade_id),
            ("market", market),
            ("direction", side),
            ("opened_at_ms", opened),
            ("closed_at_ms", closed),
        ):
            if context.get(field) != expected:
                raise PaperProfitabilityScoreboardError(
                    f"entry context trade lineage mismatch: {field}"
                )
        if _number(context.get("net_pnl"), "context net PnL") != net:
            raise PaperProfitabilityScoreboardError(
                "entry context net PnL differs from booked journal"
            )
        lead = _text(context.get("lead_strategy"), "lead strategy")
        rank = _text(context.get("rank_band"), "entry rank band")
    original_source = row.get("original_first_seen_opportunity")
    original_source_match = False
    if original_source is not None:
        original = _object(original_source, "first-seen opportunity source")
        status = _text(original.get("status"), "first-seen opportunity status")
        if status not in {
            "matched", "missing", "ambiguous", "contradictory_or_stale"
        }:
            raise PaperProfitabilityScoreboardError(
                "unsupported original opportunity source status"
            )
        if (
            original.get("source_phase") != (
                "original_paper_opening_opportunity_after_risk_evaluation"
            )
            or original.get("independently_archived_before_trade") is not False
            or original.get("online_filter_state_certified") is not False
            or original.get("promotion_authority") is not False
        ):
            raise PaperProfitabilityScoreboardError(
                "invalid original first-seen source authority"
            )
        if status == "matched":
            if context_raw is None:
                raise PaperProfitabilityScoreboardError(
                    "matched original decision has no verified trade context"
                )
            original_identity: dict[str, object] = {
                "market": market,
                "direction": side,
                "lead_strategy": lead,
                "strategy_decision_id": row.get("strategy_decision_id"),
                "feature_snapshot_id": row.get("feature_snapshot_id"),
                "risk_decision_id": row.get("risk_decision_id"),
            }
            for key, original_value in original_identity.items():
                if not isinstance(original_value, str) or not original_value or (
                    original.get(key) != original_value
                ):
                    raise PaperProfitabilityScoreboardError(
                        f"original opportunity lineage mismatch: {key}"
                    )
            timestamp = _integer(
                original.get("opportunity_timestamp_ms"),
                "original opportunity decision time",
            )
            if (
                original.get("baseline_risk_approved") is not True
                or timestamp > opened
                or opened - timestamp > 300_000
            ):
                raise PaperProfitabilityScoreboardError(
                    "original opportunity approval or decision clock mismatch"
                )
            original_source_match = True
        else:
            if any(
                original.get(key) is not None
                for key in (
                    "market", "direction", "lead_strategy",
                    "strategy_decision_id", "feature_snapshot_id",
                    "risk_decision_id", "opportunity_timestamp_ms",
                    "baseline_risk_approved",
                )
            ):
                raise PaperProfitabilityScoreboardError(
                    "uncertain original source claims matching decision"
                )
    return _Trade(
        trade_id=trade_id,
        market=market,
        side=side,
        opened_at_ms=opened,
        closed_at_ms=closed,
        lead_strategy=lead,
        rank_band=rank,
        exit_reason=exit_reason,
        verified_context=context_raw is not None,
        original_decision_source_match=original_source_match,
        rank_missing=rank in {"missing", UNVERIFIED},
        chart_complete=chart,
        gross=gross,
        fees=entry_fee + exit_fee,
        funding=funding,
        net=net,
        net_r=net_r,
        net_cash_residual=net_cash_residual,
    )


def _metrics(trades: list[_Trade]) -> dict[str, object]:
    gross = sum((t.gross for t in trades), ZERO)
    fees = sum((t.fees for t in trades), ZERO)
    funding = sum((t.funding for t in trades), ZERO)
    net = sum((t.net for t in trades), ZERO)
    booked_cost_drag = gross - net
    expected_cost_drag = fees - funding
    all_fees_refunded_same_fills = net + fees
    required_fee_fraction = (
        max(-net, ZERO) / fees if trades and fees > ZERO else None
    )
    gross_positive = [t for t in trades if t.gross > ZERO]
    flipped = [t for t in gross_positive if t.net <= ZERO]
    return {
        "trades": len(trades),
        "wins": sum(t.net > ZERO for t in trades),
        "losses": sum(t.net < ZERO for t in trades),
        "gross_realized_pnl": str(gross),
        "fees": str(fees),
        "funding_cash_pnl": str(funding),
        "net_pnl": str(net),
        "same_fill_all_recorded_fees_refunded_net_pnl": str(
            all_fees_refunded_same_fills
        ),
        "same_fill_fee_refund_fraction_needed_for_zero_net": (
            None if required_fee_fraction is None
            else str(required_fee_fraction)
        ),
        "same_fill_all_fee_refund_still_net_negative": (
            all_fees_refunded_same_fills < ZERO if trades else None
        ),
        "same_fill_additional_gross_needed_even_after_full_fee_refund": str(
            max(-all_fees_refunded_same_fills, ZERO)
        ),
        "fee_refund_bound_semantics": (
            "arithmetic_same_original_fills_not_executable_or_new_equity"
        ),
        "gross_positive_trades": len(gross_positive),
        "gross_positive_net_nonpositive_trades": len(flipped),
        "gross_positive_net_negative_trades": sum(
            trade.net < ZERO for trade in flipped
        ),
        "gross_nonpositive_net_positive_trades": sum(
            trade.gross <= ZERO and trade.net > ZERO for trade in trades
        ),
        "gross_positive_flipped_booked_gross_pnl": str(
            sum((trade.gross for trade in flipped), ZERO)
        ),
        "gross_positive_flipped_booked_net_pnl": str(
            sum((trade.net for trade in flipped), ZERO)
        ),
        "gross_positive_flipped_recorded_fees": str(
            sum((trade.fees for trade in flipped), ZERO)
        ),
        "gross_positive_flipped_funding_cash_pnl": str(
            sum((trade.funding for trade in flipped), ZERO)
        ),
        "recorded_fees_minus_funding_cash": str(expected_cost_drag),
        "gross_minus_booked_net_pnl": str(booked_cost_drag),
        "booked_net_cash_reconciliation_residual": str(
            net - gross + fees - funding
        ),
        "per_trade_nonzero_net_cash_residual_count": sum(
            trade.net_cash_residual != ZERO for trade in trades
        ),
        "per_trade_max_abs_net_cash_residual": str(
            max(
                (abs(trade.net_cash_residual) for trade in trades),
                default=ZERO,
            )
        ),
        "per_trade_residual_precision_bound": str(
            MAX_PER_TRADE_NET_CASH_RESIDUAL
        ),
        "net_per_trade": str(net / len(trades)) if trades else None,
        "net_r": str(sum((t.net_r for t in trades), ZERO)),
        "unverified_entry_context_trades": sum(
            not t.verified_context for t in trades
        ),
        "missing_rank_evidence_trades": sum(t.rank_missing for t in trades),
        "incomplete_chart_trades": sum(not t.chart_complete for t in trades),
    }


def _original_chart_coverage_economics(
    cohort: list[_Trade],
) -> dict[str, object]:
    """Partition *every* executed original close by witnessed chart quality.

    Actual booked dollars/R remain attributable when prices are missing;
    missing mark paths cannot validate an exit replay or be imputed as fills.
    The partition is never a counterfactual replacement trading strategy.
    """
    complete = [trade for trade in cohort if trade.chart_complete]
    incomplete = [trade for trade in cohort if not trade.chart_complete]
    if len(complete) + len(incomplete) != len(cohort):
        raise PaperProfitabilityScoreboardError(
            "original chart coverage partition incomplete"
        )
    return {
        "source": "original_completed_in_position_mark_chart_coverage",
        "whole_original_cohort": _metrics(cohort),
        "complete_observed_path_original_closes": _metrics(complete),
        "incomplete_or_missing_path_original_closes": _metrics(incomplete),
        "all_original_closes_preserved": True,
        "unknown_or_missing_paths_are_not_filled": True,
        "chart_coverage_is_random_or_causal": False,
        "counterfactual_exit_cashflow_simulated": False,
        "ready_for_strategy_promotion": False,
        "promotion_authority": False,
        "execution_authority": False,
    }


def _short_breakout_top3_robustness(
    trades: list[_Trade],
) -> dict[str, object]:
    """PREDECLARED rank hypothesis, never a trade-skip account simulation.

    The current frozen prospective SHORT breakout-rank experiment motivates
    an explicit top-three comparison on the original *entire* closed paper
    journal. This retrospective slice cannot satisfy promotion authority.
    Chronological halves follow the entire journal, not hand-picked dates
    from favorable SHORT breakout winners.
    """
    candidates = [
        trade
        for trade in trades
        if trade.side == "short" and trade.lead_strategy == "breakout"
    ]
    top3 = [trade for trade in candidates if trade.rank_band == "top3"]
    other = [trade for trade in candidates if trade.rank_band != "top3"]
    total = sum((t.net for t in top3), ZERO)
    market_names = sorted({t.market for t in top3})
    largest_positive = tuple(t.net for t in top3 if t.net > ZERO)
    leave_trade = tuple(total - trade.net for trade in top3)
    leave_market = tuple(
        total - sum((t.net for t in top3 if t.market == market), ZERO)
        for market in market_names
    )
    half = len(trades) // 2
    first_ids = {t.trade_id for t in trades[:half]}
    first = [t for t in top3 if t.trade_id in first_ids]
    second = [t for t in top3 if t.trade_id not in first_ids]
    first_metrics = _metrics(first)
    second_metrics = _metrics(second)
    min_trade = min(leave_trade) if len(top3) >= 2 else None
    min_market = min(leave_market) if len(market_names) >= 2 else None
    gross_win = sum(largest_positive, ZERO)
    largest_winner_share = (
        None
        if not largest_positive or gross_win <= ZERO
        else max(largest_positive) / gross_win
    )

    # Descriptive adequacy threshold for hypothesis prioritization only.
    # Never reclassify a strategy ready for promotion on these counts.
    descriptive_floor = (
        len(top3) >= 24
        and len(market_names) >= 6
        and len(first) >= 8
        and len(second) >= 8
    )
    return {
        "hypothesis": "frozen-short-breakout-top3-rank-v1",
        "kind": "executed-original-journal-retrospective-only",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_candidate_readiness": False,
        "whole_journal_trades": len(trades),
        "whole_journal_net_pnl": _metrics(trades)["net_pnl"],
        "short_breakout_all_rank_bands": _metrics(candidates),
        "short_breakout_top3": _metrics(top3),
        "short_breakout_other_bands_including_missing": _metrics(other),
        "short_breakout_other_rank_missing_trades": sum(
            t.rank_missing for t in other
        ),
        "top3_distinct_markets": len(market_names),
        "top3_min_net_after_leaving_one_trade_out": (
            None if min_trade is None else str(min_trade)
        ),
        "top3_min_net_after_leaving_one_market_out": (
            None if min_market is None else str(min_market)
        ),
        "top3_largest_winner_share_of_positive_net": (
            None if largest_winner_share is None
            else str(largest_winner_share)
        ),
        "top3_global_chronological_first_half": first_metrics,
        "top3_global_chronological_second_half": second_metrics,
        "descriptive_minimum_trades": 24,
        "descriptive_minimum_markets": 6,
        "descriptive_minimum_trades_per_global_half": 8,
        "meets_descriptive_sample_floor": descriptive_floor,
        "ready_for_strategy_promotion": False,
        "forward_net_edge_verified": False,
        "counterfactual_account_pnl_estimated": False,
    }


def _forward_rank_robustness(
    cohort: list[_Trade], whole_forward: list[_Trade]
) -> dict[str, object]:
    """Stress an executed original cohort; never simulate skipped fills.

    Chronological halves are fixed by EVERY original post-embargo opening,
    not by choosing favorable dates or splitting the selected rank cohort.
    """
    markets = sorted({trade.market for trade in cohort})
    total_net = sum((trade.net for trade in cohort), ZERO)
    total_r = sum((trade.net_r for trade in cohort), ZERO)
    leave_trade_dollars = [total_net - trade.net for trade in cohort]
    leave_trade_r = [total_r - trade.net_r for trade in cohort]
    leave_market_dollars = [
        total_net - sum(
            (trade.net for trade in cohort if trade.market == market), ZERO
        )
        for market in markets
    ]
    leave_market_r = [
        total_r - sum(
            (trade.net_r for trade in cohort if trade.market == market), ZERO
        )
        for market in markets
    ]
    ordered = sorted(
        whole_forward, key=lambda trade: (trade.opened_at_ms, trade.trade_id)
    )
    first_ids = {trade.trade_id for trade in ordered[:len(ordered) // 2]}
    winners = [trade.net for trade in cohort if trade.net > ZERO]
    positive_total = sum(winners, ZERO)
    return {
        "cohort_original_closes": len(cohort),
        "distinct_original_markets": len(markets),
        "whole_forward_chronology": "original_opened_at_ms_then_trade_id",
        "global_forward_first_half": _metrics(
            [trade for trade in cohort if trade.trade_id in first_ids]
        ),
        "global_forward_second_half": _metrics(
            [trade for trade in cohort if trade.trade_id not in first_ids]
        ),
        "min_net_pnl_leaving_one_trade_out": (
            str(min(leave_trade_dollars)) if len(cohort) >= 2 else None
        ),
        "min_net_r_leaving_one_trade_out": (
            str(min(leave_trade_r)) if len(cohort) >= 2 else None
        ),
        "min_net_pnl_leaving_one_market_out": (
            str(min(leave_market_dollars)) if len(markets) >= 2 else None
        ),
        "min_net_r_leaving_one_market_out": (
            str(min(leave_market_r)) if len(markets) >= 2 else None
        ),
        "largest_winner_share_of_positive_net": (
            str(max(winners) / positive_total) if winners else None
        ),
        "independent_forward_edge_verified": False,
        "counterfactual_cashflow_simulated": False,
        "promotion_authority": False,
        "execution_authority": False,
    }


def _forward_side_economics(rows: list[_Trade]) -> dict[str, object]:
    """Split actual booked closes without dropping either trade direction.

    Zero-observation sides remain explicit; these are original executed
    returns, not a matched replacement account or an online rank verdict.
    """
    return {
        side: _metrics([trade for trade in rows if trade.side == side])
        for side in ("long", "short")
    }


def _frozen_forward_hypothesis_economics(
    trades: list[_Trade],
    *,
    short_rank_state: object | None,
    trend_outside_state: object | None,
) -> dict[str, object]:
    """Score pre-existing immutable hypotheses only after their actual embargo.

    No strategy simulation is made from closed trades, even if a cohort is
    profitable. Missing frozen state disables its forward readout instead
    of incorrectly treating all old historical trades as prospective.
    """
    hypotheses: dict[str, object] = {}
    for hypothesis, raw_state in (
        ("short_breakout_rank4plus_skip", short_rank_state),
        ("trend_outside_top10_both_sides_skip", trend_outside_state),
    ):
        if raw_state is None:
            hypotheses[hypothesis] = {
                "source_status": "missing_frozen_state",
                "frozen_state_verified": False,
                "forward_trade_count": 0,
                "ready_for_review": False,
                "promotion_authority": False,
                "execution_authority": False,
            }
            continue

        state: (
            ProspectiveShortBreakoutRankState
            | ProspectiveTrendOutsideTop10State
        )
        if hypothesis == "short_breakout_rank4plus_skip":
            state = ProspectiveShortBreakoutRankState.from_payload(raw_state)
            min_future = SHORT_MIN_FUTURE
        else:
            state = ProspectiveTrendOutsideTop10State.from_payload(raw_state)
            min_future = TREND_MIN_CLOSED
        forward = [
            trade for trade in trades
            if trade.opened_at_ms >= state.started_at_ms
        ]
        if hypothesis == "short_breakout_rank4plus_skip":
            target = [
                trade for trade in forward
                if trade.side == "short" and trade.lead_strategy == "breakout"
            ]
            preferred = [t for t in target if t.rank_band == "top3"]
            disfavored = [
                t for t in target
                if t.rank_band in {"top10", "outside10"}
            ]
        else:
            target = [
                trade for trade in forward
                if trade.lead_strategy == "trend"
            ]
            preferred = [
                t for t in target
                if t.rank_band in {"top3", "top10"}
            ]
            disfavored = [
                t for t in target if t.rank_band == "outside10"
            ]
        unresolved = [
            t for t in target
            if t.rank_band not in {"top3", "top10", "outside10"}
        ]
        if len(preferred) + len(disfavored) + len(unresolved) != len(target):
            raise PaperProfitabilityScoreboardError(
                "frozen forward cohort partition incomplete"
            )
        encoded = json.dumps(
            state.payload(),
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        hypotheses[hypothesis] = {
            "source_status": "immutable_freeze_verified",
            "frozen_state_verified": True,
            "frozen_candidate_id": state.candidate_id,
            "frozen_at_ms": state.frozen_at_ms,
            "post_embargo_started_at_ms": state.started_at_ms,
            "frozen_state_sha256": hashlib.sha256(encoded).hexdigest(),
            "minimum_original_forward_closed_trades_for_context": min_future,
            "sufficient_original_forward_trade_count": (
                len(forward) >= min_future
            ),
            "forward_trade_count": len(forward),
            "original_forward_whole_journal": _metrics(forward),
            "original_forward_whole_exit_mechanisms": (
                _original_booked_exit_mechanisms(forward)
            ),
            "original_forward_hypothesis_context": _metrics(target),
            "original_forward_hypothesis_exit_mechanisms": (
                _original_booked_exit_mechanisms(target)
            ),
            "original_forward_hypothesis_chart_coverage_economics": (
                _original_chart_coverage_economics(target)
            ),
            "original_forward_hypothesis_context_by_side": (
                _forward_side_economics(target)
            ),
            "preferred_rank_attributed_original_closes": _metrics(preferred),
            "preferred_original_exit_mechanisms": (
                _original_booked_exit_mechanisms(preferred)
            ),
            "preferred_original_chart_coverage_economics": (
                _original_chart_coverage_economics(preferred)
            ),
            "preferred_rank_attributed_original_closes_by_side": (
                _forward_side_economics(preferred)
            ),
            "disfavored_rank_attributed_original_closes": _metrics(disfavored),
            "disfavored_original_exit_mechanisms": (
                _original_booked_exit_mechanisms(disfavored)
            ),
            "disfavored_original_chart_coverage_economics": (
                _original_chart_coverage_economics(disfavored)
            ),
            "disfavored_rank_attributed_original_closes_by_side": (
                _forward_side_economics(disfavored)
            ),
            "unresolved_rank_original_closes": _metrics(unresolved),
            "unresolved_original_exit_mechanisms": (
                _original_booked_exit_mechanisms(unresolved)
            ),
            "unresolved_original_chart_coverage_economics": (
                _original_chart_coverage_economics(unresolved)
            ),
            "unresolved_rank_original_closes_by_side": (
                _forward_side_economics(unresolved)
            ),
            "original_forward_preferred_rank_robustness": (
                _forward_rank_robustness(preferred, forward)
            ),
            "original_forward_disfavored_rank_robustness": (
                _forward_rank_robustness(disfavored, forward)
            ),
            "original_forward_unverified_entry_context_count": sum(
                not t.verified_context for t in forward
            ),
            "rank_freshness_independently_reverified": False,
            "candidate_skip_cashflow_simulated": False,
            "matched_independent_paper_account_trial": False,
            "ready_for_review": False,
            "promotion_authority": False,
            "execution_authority": False,
        }
    return {
        "kind": "frozen-before-entry-original-booked-forward-diagnostics-v1",
        "research_only": True,
        "changes_strategy": False,
        "changes_candidate_readiness": False,
        "execution_authority": False,
        "promotion_authority": False,
        "original_whole_journal_trades": len(trades),
        "original_whole_journal_net_pnl": _metrics(trades)["net_pnl"],
        "context_provenance": (
            "posttrade_verified_entry_context_not_independent_online_receipt"
        ),
        "forward_set_membership_rule": (
            "original_trade_open_timestamp_ge_frozen_at_plus_embargo"
        ),
        "no_claim_of_counterfactual_account_returns": True,
        "hypotheses": hypotheses,
    }


def _cohorts(
    rows: list[_Trade], dimensions: tuple[str, ...]
) -> list[dict[str, object]]:
    buckets: dict[tuple[str, ...], list[_Trade]] = defaultdict(list)
    for trade in rows:
        keys = tuple(cast(str, getattr(trade, key)) for key in dimensions)
        buckets[keys].append(trade)
    result: list[dict[str, object]] = []
    for keys, members in buckets.items():
        result.append({
            "cohort": dict(zip(dimensions, keys, strict=True)),
            **_metrics(members),
        })
    # Loss concentrations first, with deterministic tie-breaking.
    return sorted(
        result,
        key=lambda item: (
            _number(item["net_pnl"], "cohort net PnL"),
            str(item["cohort"]),
        ),
    )


def _original_booked_exit_mechanisms(
    cohort: list[_Trade],
) -> dict[str, object]:
    """Actual closed-trade loss attribution, NEVER an entry-time filter.

    Exit reason is an actual post-entry result. These partitions cannot
    estimate trading the same openings with different fills, fees, exposure
    or capital reuse and do not grant strategy/exit promotion authority.
    """
    return {
        "source": "actual_original_post_exit_reason_and_booked_cashflow",
        "whole_original_cohort": _metrics(cohort),
        "by_exit_reason": _cohorts(cohort, ("exit_reason",)),
        "by_side_and_exit_reason": _cohorts(
            cohort, ("side", "exit_reason")
        ),
        "by_strategy_and_exit_reason": _cohorts(
            cohort, ("lead_strategy", "exit_reason")
        ),
        "by_side_strategy_and_exit_reason": _cohorts(
            cohort, ("side", "lead_strategy", "exit_reason")
        ),
        "by_exit_reason_with_original_chart_coverage": [
            {
                "exit_reason": reason,
                **_original_chart_coverage_economics([
                    trade for trade in cohort if trade.exit_reason == reason
                ]),
            }
            for reason in sorted({trade.exit_reason for trade in cohort})
        ],
        "exit_reason_known_only_after_original_entry": True,
        "all_original_closes_included": True,
        "counterfactual_exit_or_skip_account_simulated": False,
        "suitable_as_entry_filter": False,
        "ready_for_review": False,
        "promotion_authority": False,
        "execution_authority": False,
    }



def _predeclared_mean_reversion_abstention(
    trades: list[_Trade],
    *,
    source_handoff_ended_at_ms: int | None = None,
    source_handoff_open_positions: int | None = None,
) -> dict[str, object]:
    """Forward-only original-booked skip arithmetic, NEVER an account replay.

    The prior 9/9 realized losing mean-reversion originals selected this
    hypothesis. No trade that opened before the fixed embargo endpoint can
    count as validation, even when it closes afterwards. The source's
    verified decision context is joined AFTER the original trade, so it
    cannot certify online filter-state or capital displacement.
    """
    forward = [
        trade for trade in trades
        if trade.opened_at_ms >= MEAN_REVERSION_FORWARD_START_MS
    ]
    # Missing/unverified original entry contexts never receive skip credit.
    avoided = [
        trade for trade in forward
        if (
            trade.verified_context
            and trade.original_decision_source_match
            and trade.lead_strategy == "mean_reversion"
        )
    ]
    retained = [
        trade for trade in forward
        if not (
            trade.verified_context
            and trade.original_decision_source_match
            and trade.lead_strategy == "mean_reversion"
        )
    ]
    original_cash = sum((trade.net for trade in forward), ZERO)
    original_r = sum((trade.net_r for trade in forward), ZERO)
    avoided_cash = sum((trade.net for trade in avoided), ZERO)
    avoided_r = sum((trade.net_r for trade in avoided), ZERO)
    retained_cash = sum((trade.net for trade in retained), ZERO)
    retained_r = sum((trade.net_r for trade in retained), ZERO)
    if (
        len(avoided) + len(retained) != len(forward)
        or original_cash != retained_cash + avoided_cash
        or original_r != retained_r + avoided_r
    ):
        raise PaperProfitabilityScoreboardError(
            "forward mean-reversion original cash/R partition mismatch"
        )
    market_cash: dict[str, Decimal] = {}
    market_r: dict[str, Decimal] = {}
    for trade in avoided:
        market_cash[trade.market] = market_cash.get(trade.market, ZERO) + trade.net
        market_r[trade.market] = market_r.get(trade.market, ZERO) + trade.net_r
    delta_cash = -avoided_cash
    delta_r = -avoided_r
    # A leave-out cannot simulate what risk/capital would have replaced a
    # skipped position with. It only probes concentration of signed cash/R.
    leave_trade_cash = [
        delta_cash + trade.net for trade in avoided
    ]
    leave_trade_r = [
        delta_r + trade.net_r for trade in avoided
    ]
    leave_market_cash = [
        delta_cash + pnl for pnl in market_cash.values()
    ]
    leave_market_r = [
        delta_r + pnl for pnl in market_r.values()
    ]
    # The closing journal is ordered by EXIT. Stability cohorts must
    # instead follow the *original opportunity opening time*.
    opening_order = sorted(
        forward, key=lambda t: (t.opened_at_ms, t.trade_id)
    )
    midpoint = len(opening_order) // 2
    first_ids = {trade.trade_id for trade in opening_order[:midpoint]}
    first_avoided = [t for t in avoided if t.trade_id in first_ids]
    second_avoided = [t for t in avoided if t.trade_id not in first_ids]

    # Neither the number of currently closed trades nor the last close may
    # choose temporal split boundaries. Predeclare fixed 24-hour bins from
    # the six-hour-embargo endpoint; bins remain stable when closes arrive.
    by_open_day: dict[int, list[_Trade]] = {}
    for trade in opening_order:
        day = (
            trade.opened_at_ms - MEAN_REVERSION_FORWARD_START_MS
        ) // MEAN_REVERSION_FIXED_OPENING_DAY_MS
        by_open_day.setdefault(day, []).append(trade)
    days = sorted(set(by_open_day).union({0, 1}))
    known_handoff = (
        source_handoff_ended_at_ms is not None
        and source_handoff_open_positions is not None
    )
    all_exposure_settled = (
        known_handoff and source_handoff_open_positions == 0
    )
    blocks: list[dict[str, object]] = []
    for day in days:
        members = by_open_day.get(day, [])
        matching_avoided = [
            t for t in members
            if t.verified_context
            and t.original_decision_source_match
            and t.lead_strategy == "mean_reversion"
        ]
        member_original_cash = sum((t.net for t in members), ZERO)
        member_original_r = sum((t.net_r for t in members), ZERO)
        omitted_cash = sum((t.net for t in matching_avoided), ZERO)
        omitted_r = sum((t.net_r for t in matching_avoided), ZERO)
        window_start = (
            MEAN_REVERSION_FORWARD_START_MS
            + day * MEAN_REVERSION_FIXED_OPENING_DAY_MS
        )
        window_end_exclusive = (
            window_start + MEAN_REVERSION_FIXED_OPENING_DAY_MS
        )
        completed_window = (
            all_exposure_settled
            and source_handoff_ended_at_ms is not None
            and source_handoff_ended_at_ms >= window_end_exclusive
        )
        blocks.append({
            "opening_day_index": day,
            "opened_at_ms_ge": window_start,
            "opened_at_ms_lt": window_end_exclusive,
            "observed_original_closed_trades": len(members),
            "closed_origins_only_no_evidence_of_unclosed_fills": True,
            "avoided_verified_mean_reversion": _metrics(matching_avoided),
            "original_booked_net_cash": str(member_original_cash),
            "original_booked_net_r": str(member_original_r),
            "zero_replacement_net_cash": str(
                member_original_cash - omitted_cash
            ),
            "zero_replacement_net_r": str(
                member_original_r - omitted_r
            ),
            "naive_skip_delta_cash": str(-omitted_cash),
            "naive_skip_delta_r": str(-omitted_r),
            "source_observation_window_mature": completed_window,
            "capital_reallocation_modeled": False,
            "promotion_authority": False,
        })
    first_two = blocks[:2]  # Always opening days 0 and 1, never best days.
    fixed_days_sampled = (
        len(first_two) == 2
        and all(
            b["source_observation_window_mature"] is True
            and _integer(
                _object(
                    b["avoided_verified_mean_reversion"],
                    "fixed opening-day avoided cohort",
                ).get("trades"),
                "fixed opening-day avoided count",
            ) >= 3
            for b in first_two
        )
    )
    first_two_positive = (
        fixed_days_sampled
        and all(
            Decimal(str(b["naive_skip_delta_cash"])) > ZERO
            and Decimal(str(b["naive_skip_delta_r"])) > ZERO
            for b in first_two
        )
    )

    # Mean-reversion opened only nine times in the discovery cohort. The
    # frozen two-day splits are transparent diagnostics but an arbitrary
    # >=3-trades-per-day maturity floor would make an otherwise promising
    # 40+ close/12+ MR forward study practically unreviewable. The actual
    # temporal sample gate uses *first two consecutive 7-day windows*.
    by_open_week: dict[int, list[_Trade]] = {}
    for trade in opening_order:
        week = (
            trade.opened_at_ms - MEAN_REVERSION_FORWARD_START_MS
        ) // MEAN_REVERSION_FIXED_OPENING_WEEK_MS
        by_open_week.setdefault(week, []).append(trade)
    weeks = sorted(set(by_open_week).union({0, 1}))
    week_blocks: list[dict[str, object]] = []
    for week in weeks:
        members = by_open_week.get(week, [])
        matching_avoided = [
            t for t in members
            if t.verified_context
            and t.original_decision_source_match
            and t.lead_strategy == "mean_reversion"
        ]
        week_original_cash = sum((t.net for t in members), ZERO)
        week_original_r = sum((t.net_r for t in members), ZERO)
        omitted_cash = sum((t.net for t in matching_avoided), ZERO)
        omitted_r = sum((t.net_r for t in matching_avoided), ZERO)
        window_start = (
            MEAN_REVERSION_FORWARD_START_MS
            + week * MEAN_REVERSION_FIXED_OPENING_WEEK_MS
        )
        window_end = window_start + MEAN_REVERSION_FIXED_OPENING_WEEK_MS
        week_blocks.append({
            "opening_week_index": week,
            "opened_at_ms_ge": window_start,
            "opened_at_ms_lt": window_end,
            "observed_original_closed_trades": len(members),
            "avoided_verified_mean_reversion": _metrics(matching_avoided),
            "original_booked_net_cash": str(week_original_cash),
            "original_booked_net_r": str(week_original_r),
            "zero_replacement_net_cash": str(week_original_cash - omitted_cash),
            "zero_replacement_net_r": str(week_original_r - omitted_r),
            "naive_skip_delta_cash": str(-omitted_cash),
            "naive_skip_delta_r": str(-omitted_r),
            "source_observation_window_mature": (
                all_exposure_settled
                and source_handoff_ended_at_ms is not None
                and source_handoff_ended_at_ms >= window_end
            ),
            "unclosed_trades_not_claimed_absent_without_zero_exposure": True,
            "capital_reallocation_modeled": False,
            "promotion_authority": False,
        })
    fixed_weeks_sampled = all(
        block["source_observation_window_mature"] is True
        and _integer(
            _object(
                block["avoided_verified_mean_reversion"],
                "fixed opening-week avoided cohort",
            ).get("trades"),
            "fixed opening-week avoided count",
        ) >= 3
        for block in week_blocks[:2]
    )
    fixed_weeks_improved = (
        fixed_weeks_sampled
        and all(
            Decimal(str(block["naive_skip_delta_cash"])) > ZERO
            and Decimal(str(block["naive_skip_delta_r"])) > ZERO
            for block in week_blocks[:2]
        )
    )
    descriptive_floor = (
        len(forward) >= 40
        and len(avoided) >= 12
        and len(market_cash) >= 6
        and fixed_weeks_sampled
        and all(t.verified_context for t in forward)
        and all(t.original_decision_source_match for t in forward)
    )
    return {
        "hypothesis_id": "discovery-mean-reversion-abstain-after-cost-v1",
        "kind": "forward-original-booked-trade-contribution-only",
        "fixed_discovery_freeze_ms": MEAN_REVERSION_DISCOVERY_FREEZE_MS,
        "embargo_ms": MEAN_REVERSION_EMBARGO_MS,
        "forward_started_at_ms": MEAN_REVERSION_FORWARD_START_MS,
        "fixed_opening_window_ms": MEAN_REVERSION_FIXED_OPENING_DAY_MS,
        "fixed_stability_window_ms": MEAN_REVERSION_FIXED_OPENING_WEEK_MS,
        "fixed_opening_windows_start_at_embargo_end": True,
        "closed_only_right_censoring_explicit": True,
        "source_handoff_ended_at_ms": source_handoff_ended_at_ms,
        "source_handoff_open_positions": source_handoff_open_positions,
        "source_handoff_exposure_zero_and_end_known": all_exposure_settled,
        "inclusion_rule": "original_trade_opened_at_ms_ge_fixed_forward_start",
        "rule": "skip_only_verified_mean_reversion_lead",
        "discovery_period_pnl_never_scored": True,
        "source": "authenticated_completed_original_journal_with_posttrade_entry_context",
        "independent_online_filter_state_certified": False,
        "requires_first_seen_original_decision_join": True,
        "independent_archive_receipt_certified": False,
        "trading_replacements_modeled": False,
        "capital_reallocation_modeled": False,
        "full_account_trial": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_positions": False,
        "changes_risk_limits": False,
        "research_readiness_grant": False,
        "ready_for_strategy_promotion": False,
        "forward_original_closed_trades": len(forward),
        "original_forward_net_cash": str(original_cash),
        "original_forward_net_r": str(original_r),
        "forward_unverified_entry_contexts_retained": sum(
            not trade.verified_context for trade in retained
        ),
        "forward_original_decision_matches": sum(
            trade.original_decision_source_match for trade in forward
        ),
        "forward_mean_reversion_without_first_seen_match_retained": sum(
            trade.verified_context
            and trade.lead_strategy == "mean_reversion"
            and not trade.original_decision_source_match
            for trade in retained
        ),
        "verified_mean_reversion_avoided": _metrics(avoided),
        "retained_original_closes": _metrics(retained),
        "naive_zero_replacement_candidate_net_cash": str(retained_cash),
        "naive_zero_replacement_candidate_net_r": str(retained_r),
        "naive_zero_replacement_delta_net_cash": str(delta_cash),
        "naive_zero_replacement_delta_net_r": str(delta_r),
        "arithmetic_candidate_positive_both_cash_and_r": (
            bool(forward) and retained_cash > ZERO and retained_r > ZERO
        ),
        "arithmetic_improvement_positive_both_cash_and_r": (
            bool(avoided) and delta_cash > ZERO and delta_r > ZERO
        ),
        "avoided_market_count": len(market_cash),
        "leave_one_avoided_trade_min_delta_cash": (
            str(min(leave_trade_cash)) if len(avoided) >= 2 else None
        ),
        "leave_one_avoided_trade_min_delta_r": (
            str(min(leave_trade_r)) if len(avoided) >= 2 else None
        ),
        "leave_one_avoided_market_min_delta_cash": (
            str(min(leave_market_cash)) if len(market_cash) >= 2 else None
        ),
        "leave_one_avoided_market_min_delta_r": (
            str(min(leave_market_r)) if len(market_cash) >= 2 else None
        ),
        "fixed_24h_original_opening_windows": blocks,
        "fixed_7d_original_opening_windows": week_blocks,
        "first_two_fixed_7d_windows_have_mature_sample": fixed_weeks_sampled,
        "first_two_fixed_7d_naive_skip_improves_cash_and_r": fixed_weeks_improved,
        "first_two_fixed_24h_windows_have_mature_sample": fixed_days_sampled,
        "first_two_fixed_24h_naive_skip_improves_cash_and_r": first_two_positive,
        "chronological_count_halves_dynamic_not_fixed_stability": True,
        "chronological_forward_halves_avoided": [
            {
                "half": 1,
                "total_original_closes": midpoint,
                "avoided": _metrics(first_avoided),
            },
            {
                "half": 2,
                "total_original_closes": len(forward) - midpoint,
                "avoided": _metrics(second_avoided),
            },
        ],
        "descriptive_sample_floor_met_not_promotion": descriptive_floor,
        "warning": (
            "Only new post-embargo originals with a matching first-seen "
            "original approved decision and verified entry context are "
            "counted as skipped. The skip is "
            "zero replacement cash, not a causal matched capital-constrained "
            "account. Verified posttrade context is not independently "
            "archived decision-time observation. Prior 9 losing trades are "
            "discovery only and never validation. Closed-only cohorts are "
            "right-censored until the authenticated handoff end and zero "
            "open positions establish observed window maturity. Fixed "
            "opening-time day/week windows are descriptive, not a full-account "
            "replacement simulation. No trade authority."
        ),
    }


def paper_profitability_scoreboard(
    raw: object,
    *,
    short_rank_freeze: object | None = None,
    trend_outside_freeze: object | None = None,
) -> dict[str, object]:
    """Attribute **every** original closed trade without selecting winners.

    The caller must separately verify the source Actions artifact run,
    attempt and SHA-256. A locally supplied JSON file is not authentication.
    """
    with localcontext(prec=96):
        audit = _object(raw, "full closed-trade audit")
        for flag, expected in (
            ("research_only", True),
            ("execution_authority", False),
            ("promotion_authority", False),
            ("changes_strategy", False),
            ("changes_risk_limits", False),
            ("deferred_after_successor_dispatch", True),
        ):
            if audit.get(flag) is not expected:
                raise PaperProfitabilityScoreboardError(
                    f"untrusted audit control: {flag}"
                )
        if audit.get("source_exit_reason") not in {
            "duration_elapsed", "upgrade_requested"
        }:
            raise PaperProfitabilityScoreboardError(
                "source requires completed handoff"
            )
        if audit.get("definition") != (
            "entire_closed_paper_journal_with_observed_in_position_mark_charts_v1"
        ):
            raise PaperProfitabilityScoreboardError(
                "not a complete original paper-journal audit"
            )
        source_rows = audit.get("trades")
        if not isinstance(source_rows, list):
            raise PaperProfitabilityScoreboardError("original trades absent")
        trades = [_trade(item) for item in source_rows]
        if len({trade.trade_id for trade in trades}) != len(trades):
            raise PaperProfitabilityScoreboardError(
                "duplicate original journal trade ID"
            )
        if trades != sorted(
            trades, key=lambda t: (t.closed_at_ms, t.trade_id)
        ):
            raise PaperProfitabilityScoreboardError(
                "original trades out of closed-journal chronology"
            )
        count = _integer(
            audit.get("total_journal_trades"), "total journal trade count"
        )
        if (
            len(trades) != count
            or audit.get("trades_included_in_economics") != count
        ):
            raise PaperProfitabilityScoreboardError(
                "cannot silently exclude an original closed trade"
            )
        original = _object(
            _object(audit.get("economics"), "economics").get("overall"),
            "original whole-journal economics",
        )
        overall = _metrics(trades)
        for source, calculated in (
            ("trades", count),
            ("gross_realized_pnl", overall["gross_realized_pnl"]),
            ("fees", overall["fees"]),
            ("funding_cash_pnl", overall["funding_cash_pnl"]),
            ("net_pnl", overall["net_pnl"]),
        ):
            if source == "trades":
                if original.get(source) != calculated:
                    raise PaperProfitabilityScoreboardError(
                        "whole-journal count does not reconcile"
                    )
            elif _number(original.get(source), source) != _number(
                calculated, f"calculated {source}"
            ):
                raise PaperProfitabilityScoreboardError(
                    f"whole-journal {source} does not reconcile"
                )
        residual = (
            _number(overall["net_pnl"], "net")
            - _number(overall["gross_realized_pnl"], "gross")
            + _number(overall["fees"], "fees")
            - _number(overall["funding_cash_pnl"], "funding")
        )
        # Booked Decimal amounts can differ at sub-cent precision: preserve
        # the actual published reconciliation residue rather than rewritting
        # booked original trade PnL to an assumed formula.
        if _number(
            original.get("net_reconciliation_residual"),
            "original net reconciliation residual",
        ) != residual:
            raise PaperProfitabilityScoreboardError(
                "whole-journal booked cash reconciliation residue mismatch"
            )
        handoff_ended_raw = audit.get("source_handoff_ended_at_ms")
        handoff_open_raw = audit.get("source_handoff_open_positions")
        handoff_ended: int | None = (
            None if handoff_ended_raw is None
            else _integer(handoff_ended_raw, "source handoff end")
        )
        handoff_open: int | None = (
            None if handoff_open_raw is None
            else _integer(handoff_open_raw, "source handoff open positions")
        )
        if handoff_ended is not None and any(
            trade.closed_at_ms > handoff_ended for trade in trades
        ):
            raise PaperProfitabilityScoreboardError(
                "original booked close exceeds source handoff end"
            )
        entry = _object(
            audit.get("verified_entry_exit_context"), "entry context audit"
        )
        unresolved = _integer(
            overall["unverified_entry_context_trades"],
            "unverified original entry contexts",
        )
        if (
            entry.get("entry_context_verified_trades")
            != count - unresolved
            or entry.get("entry_context_unresolved_trades") != unresolved
        ):
            raise PaperProfitabilityScoreboardError(
                "verified entry context counts do not reconcile"
            )
        # Quartiles are global chronological original-trade blocks, never
        # re-chosen for favorable strategy outcomes.
        blocks: list[dict[str, object]] = []
        for i in range(4):
            members = [
                trade for j, trade in enumerate(trades)
                if min(3, 4 * j // max(1, count)) == i
            ]
            blocks.append({"quartile": i + 1, **_metrics(members)})
        return {
            "schema_version": 1,
            "kind": "entire-original-paper-profitability-attribution",
            "source_exit_reason": audit["source_exit_reason"],
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "ready_for_strategy_promotion": False,
            "source_authentication": "caller_must_verify_github_artifact_run_attempt_digest",
            "caution": (
                "Retrospective executed paper-trade cohort attribution only. "
                "Not a skipped-trade replacement-account simulation, not "
                "proof of forecast skill or a profitable trading rule. "
                "All original losses and missing entry contexts remain included."
            ),
            "overall": overall,
            "original_booked_exit_mechanisms": (
                _original_booked_exit_mechanisms(trades)
            ),
            "original_chart_coverage_economics": (
                _original_chart_coverage_economics(trades)
            ),
            "strategy_chart_coverage_economics": [
                {
                    "lead_strategy": strategy,
                    **_original_chart_coverage_economics(
                        [trade for trade in trades if trade.lead_strategy == strategy]
                    ),
                }
                for strategy in sorted({trade.lead_strategy for trade in trades})
            ],
            "side_strategy_chart_coverage_economics": [
                {
                    "side": side,
                    "lead_strategy": strategy,
                    **_original_chart_coverage_economics([
                        trade for trade in trades
                        if (trade.side, trade.lead_strategy) == (side, strategy)
                    ]),
                }
                for side, strategy in sorted({
                    (trade.side, trade.lead_strategy) for trade in trades
                })
            ],
            "chronological_quartiles": blocks,
            "chronological_quartile_chart_coverage_economics": [
                {
                    "quartile": i + 1,
                    **_original_chart_coverage_economics([
                        trade for index, trade in enumerate(trades)
                        if min(3, 4 * index // max(1, count)) == i
                    ]),
                }
                for i in range(4)
            ],
            "side_cohorts": _cohorts(trades, ("side",)),
            "strategy_cohorts": _cohorts(trades, ("lead_strategy",)),
            "market_cohorts": _cohorts(trades, ("market",)),
            "exit_reason_cohorts": _cohorts(trades, ("exit_reason",)),
            "side_exit_reason_cohorts": _cohorts(
                trades, ("side", "exit_reason")
            ),
            "strategy_exit_reason_cohorts": _cohorts(
                trades, ("lead_strategy", "exit_reason")
            ),
            "side_strategy_exit_reason_cohorts": _cohorts(
                trades, ("side", "lead_strategy", "exit_reason")
            ),
            "side_strategy_cohorts": _cohorts(
                trades, ("side", "lead_strategy")
            ),
            "side_strategy_rank_cohorts": _cohorts(
                trades, ("side", "lead_strategy", "rank_band")
            ),
            "short_breakout_top3_robustness": (
                _short_breakout_top3_robustness(trades)
            ),
            "prospective_mean_reversion_abstention_contributions": (
                _predeclared_mean_reversion_abstention(
                    trades,
                    source_handoff_ended_at_ms=handoff_ended,
                    source_handoff_open_positions=handoff_open,
                )
            ),
            "frozen_hypotheses_original_forward_economics": (
                _frozen_forward_hypothesis_economics(
                    trades,
                    short_rank_state=short_rank_freeze,
                    trend_outside_state=trend_outside_freeze,
                )
            ),
        }
