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
UNVERIFIED: Final = "UNVERIFIED_ENTRY_CONTEXT"


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
    verified_context: bool
    rank_missing: bool
    chart_complete: bool
    gross: Decimal
    fees: Decimal
    funding: Decimal
    net: Decimal
    net_r: Decimal


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
    gross = _number(row.get("gross_realized_pnl"), "gross realized PnL")
    entry_fee = _number(row.get("entry_fees"), "entry fee")
    exit_fee = _number(row.get("exit_fees"), "exit fee")
    if entry_fee < ZERO or exit_fee < ZERO:
        raise PaperProfitabilityScoreboardError("negative execution fee")
    funding = _number(row.get("funding_cash_pnl"), "funding")
    net = _number(row.get("net_pnl"), "booked net PnL")
    net_r = _number(row.get("net_r"), "booked net R")
    chart = row.get("chart_coverage_complete")
    if type(chart) is not bool:
        raise PaperProfitabilityScoreboardError(
            "chart completeness must be recorded"
        )
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
    return _Trade(
        trade_id=trade_id,
        market=market,
        side=side,
        opened_at_ms=opened,
        closed_at_ms=closed,
        lead_strategy=lead,
        rank_band=rank,
        verified_context=context_raw is not None,
        rank_missing=rank in {"missing", UNVERIFIED},
        chart_complete=chart,
        gross=gross,
        fees=entry_fee + exit_fee,
        funding=funding,
        net=net,
        net_r=net_r,
    )


def _metrics(trades: list[_Trade]) -> dict[str, object]:
    gross = sum((t.gross for t in trades), ZERO)
    fees = sum((t.fees for t in trades), ZERO)
    funding = sum((t.funding for t in trades), ZERO)
    net = sum((t.net for t in trades), ZERO)
    booked_cost_drag = gross - net
    expected_cost_drag = fees - funding
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
        "net_per_trade": str(net / len(trades)) if trades else None,
        "net_r": str(sum((t.net_r for t in trades), ZERO)),
        "unverified_entry_context_trades": sum(
            not t.verified_context for t in trades
        ),
        "missing_rank_evidence_trades": sum(t.rank_missing for t in trades),
        "incomplete_chart_trades": sum(not t.chart_complete for t in trades),
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
            "original_forward_hypothesis_context": _metrics(target),
            "original_forward_hypothesis_context_by_side": (
                _forward_side_economics(target)
            ),
            "preferred_rank_attributed_original_closes": _metrics(preferred),
            "preferred_rank_attributed_original_closes_by_side": (
                _forward_side_economics(preferred)
            ),
            "disfavored_rank_attributed_original_closes": _metrics(disfavored),
            "disfavored_rank_attributed_original_closes_by_side": (
                _forward_side_economics(disfavored)
            ),
            "unresolved_rank_original_closes": _metrics(unresolved),
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
            "chronological_quartiles": blocks,
            "side_cohorts": _cohorts(trades, ("side",)),
            "strategy_cohorts": _cohorts(trades, ("lead_strategy",)),
            "market_cohorts": _cohorts(trades, ("market",)),
            "side_strategy_cohorts": _cohorts(
                trades, ("side", "lead_strategy")
            ),
            "side_strategy_rank_cohorts": _cohorts(
                trades, ("side", "lead_strategy", "rank_band")
            ),
            "short_breakout_top3_robustness": (
                _short_breakout_top3_robustness(trades)
            ),
            "frozen_hypotheses_original_forward_economics": (
                _frozen_forward_hypothesis_economics(
                    trades,
                    short_rank_state=short_rank_freeze,
                    trend_outside_state=trend_outside_freeze,
                )
            ),
        }
