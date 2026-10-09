"""Research-only after-cost original-paper-journal profitability attribution.

The input is the *complete*, authenticated post-handoff all-trade chart
audit. Missing entry context and incomplete charts never remove losers.
This module does not recommend or simulate skip-only strategy changes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Final, cast

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
    return {
        "trades": len(trades),
        "wins": sum(t.net > ZERO for t in trades),
        "losses": sum(t.net < ZERO for t in trades),
        "gross_realized_pnl": str(gross),
        "fees": str(fees),
        "funding_cash_pnl": str(funding),
        "net_pnl": str(net),
        "net_per_trade": str(net / len(trades)) if trades else None,
        "net_r": str(sum((t.net_r for t in trades), ZERO)),
        "unverified_entry_context_trades": sum(
            not t.verified_context for t in trades
        ),
        "missing_rank_evidence_trades": sum(t.rank_missing for t in trades),
        "incomplete_chart_trades": sum(not t.chart_complete for t in trades),
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


def paper_profitability_scoreboard(raw: object) -> dict[str, object]:
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
        }
