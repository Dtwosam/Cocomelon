from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

QUALITY_FILENAME: Final = (
    "prospective-early-vs-late-trailing-chart-integrity.json"
)
CHART_REPORT_FILENAME: Final = "all-paper-trade-chart-audit.json"
EXIT_REPORT_FILENAME: Final = "prospective-early-vs-late-trailing-comparison.json"
ZERO: Final = Decimal("0")


class DeferredEarlyExitChartIntegrityError(RuntimeError):
    pass


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(k, str) for k in value
    ):
        raise DeferredEarlyExitChartIntegrityError(
            f"{name} must be an object"
        )
    return cast(dict[str, object], value)


def _int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise DeferredEarlyExitChartIntegrityError(
            f"{name} must be a non-negative integer"
        )
    return value


def _dec(value: object, name: str) -> Decimal:
    if not isinstance(value, str):
        raise DeferredEarlyExitChartIntegrityError(
            f"{name} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise DeferredEarlyExitChartIntegrityError(
            f"{name} must be a decimal"
        ) from exc
    if not result.is_finite():
        raise DeferredEarlyExitChartIntegrityError(
            f"{name} must be finite"
        )
    return result


def _side(value: object) -> str:
    if value not in ("long", "short"):
        raise DeferredEarlyExitChartIntegrityError(
            "invalid verified trade direction"
        )
    return str(value)


def assess_early_exit_chart_integrity(
    exit_report: object,
    chart_report: object,
) -> dict[str, object]:
    """Post-handoff evidence gate; NEVER rescore or cherry-pick clean trades.

    Frozen IOC observers score complete forward original-paper positions.
    Market-data gaps during those positions invalidate any apparent
    research advantage, even if some hypothetical IOC fills were visible.
    Missing or gapped trades remain in the original full-sample economics.
    """
    exits = _object(exit_report, "paired exit report")
    charts = _object(chart_report, "all-trade chart report")
    if exits.get("research_only") is not True or any(
        exits.get(key) is not False
        for key in ("execution_authority", "promotion_authority")
    ):
        raise DeferredEarlyExitChartIntegrityError(
            "paired exit evidence has execution authority"
        )
    if charts.get("research_only") is not True or any(
        charts.get(key) is not False
        for key in ("execution_authority", "promotion_authority")
    ):
        raise DeferredEarlyExitChartIntegrityError(
            "chart evidence has execution authority"
        )
    if exits.get("definition") != (
        "frozen_plus_0_5r_early_vs_plus_1r_late_visible_book_ioc"
    ):
        raise DeferredEarlyExitChartIntegrityError(
            "unrecognized frozen early/late rule comparison"
        )
    if charts.get("definition") != (
        "entire_closed_paper_journal_with_observed_in_position_mark_charts_v1"
    ):
        raise DeferredEarlyExitChartIntegrityError(
            "unrecognized closed-trade chart provenance"
        )
    original_rows = charts.get("trades")
    if not isinstance(original_rows, list):
        raise DeferredEarlyExitChartIntegrityError(
            "all-trade chart rows missing"
        )
    count = _int(charts.get("total_journal_trades"), "journal trade count")
    reviewed = _int(
        charts.get("trades_included_in_economics"),
        "reviewed journal trade count",
    )
    if len(original_rows) != count or reviewed != count:
        raise DeferredEarlyExitChartIntegrityError(
            "closed-trade chart economic sample is incomplete"
        )
    rows: dict[str, dict[str, object]] = {}
    journal_net = ZERO
    for raw in original_rows:
        item = _object(raw, "chart trade row")
        trade_id = item.get("trade_id")
        if not isinstance(trade_id, str) or not trade_id or trade_id in rows:
            raise DeferredEarlyExitChartIntegrityError(
                "chart trade identity missing or duplicated"
            )
        _side(item.get("side"))
        journal_net += _dec(item.get("net_pnl"), "chart trade net PnL")
        rows[trade_id] = item
    chart_economics = _object(
        charts.get("economics"), "all-trade economics"
    )
    chart_overall = _object(
        chart_economics.get("overall"), "chart overall economics"
    )
    if journal_net != _dec(
        chart_overall.get("net_pnl"), "all-trade net PnL"
    ):
        raise DeferredEarlyExitChartIntegrityError(
            "all-trade chart journal PnL mismatch"
        )
    selected = exits.get("matched_trade_ids")
    if not isinstance(selected, list) or not all(
        isinstance(i, str) and i for i in selected
    ):
        raise DeferredEarlyExitChartIntegrityError(
            "paired matched trade ids missing"
        )
    if len(selected) != len(set(selected)):
        raise DeferredEarlyExitChartIntegrityError(
            "paired matched trade ids duplicated"
        )
    matches = _int(exits.get("matched_trade_count"), "matched exit trades")
    if len(selected) != matches:
        raise DeferredEarlyExitChartIntegrityError(
            "paired exit matched count mismatch"
        )
    frozen_ms = _int(
        exits.get("common_scoring_start_ms"), "frozen paired exit start"
    )
    # A clean chart on only the convenient matched IOC outcomes is not
    # evidence that the *entire* frozen original-paper population was clean.
    # Reconstruct the denominator from the independent complete journal.
    forward_rows: dict[str, dict[str, object]] = {}
    forward_net_pnl = ZERO
    forward_net_r = ZERO
    for trade_id, item in rows.items():
        opened_ms = _int(item.get("opened_at_ms"), "original trade opening")
        closed_ms = _int(item.get("closed_at_ms"), "original trade close")
        if closed_ms < opened_ms:
            raise DeferredEarlyExitChartIntegrityError(
                "original journal trade lifecycle is invalid"
            )
        if opened_ms < frozen_ms:
            continue
        forward_rows[trade_id] = item
        forward_net_pnl += _dec(item.get("net_pnl"), "forward original net PnL")
        forward_net_r += _dec(item.get("net_r"), "forward original net R")
    claimed_forward = _int(
        exits.get("future_original_closed_trades"),
        "frozen full original-paper forward trade count",
    )
    if claimed_forward != len(forward_rows):
        raise DeferredEarlyExitChartIntegrityError(
            "paired exit forward original sample does not reconcile to journal"
        )
    unmatched_forward = sorted(set(forward_rows) - set(selected))
    overall = _object(exits.get("overall"), "paired exit economics")
    side = _object(exits.get("by_direction"), "paired exit sides")
    if _int(overall.get("matched_trades"), "economic matches") != matches:
        raise DeferredEarlyExitChartIntegrityError(
            "paired exit economic count mismatch"
        )
    total_pnl = ZERO
    total_r = ZERO
    actual_by_side: dict[str, tuple[int, Decimal, Decimal]] = {
        "long": (0, ZERO, ZERO),
        "short": (0, ZERO, ZERO),
    }
    missing: list[str] = []
    gapped: list[str] = []
    incomplete: list[str] = []
    clean: list[str] = []
    for trade_id in selected:
        matched_row = rows.get(trade_id)
        if matched_row is None:
            missing.append(trade_id)
            continue
        opened_ms = _int(matched_row.get("opened_at_ms"), "trade opening")
        closed_ms = _int(matched_row.get("closed_at_ms"), "trade close")
        if closed_ms < opened_ms or opened_ms < frozen_ms:
            raise DeferredEarlyExitChartIntegrityError(
                "matched trade outside frozen forward interval"
            )
        direction = _side(matched_row.get("side"))
        pnl = _dec(matched_row.get("net_pnl"), "original net PnL")
        net_r = _dec(matched_row.get("net_r"), "original net R")
        total_pnl += pnl
        total_r += net_r
        bucket = actual_by_side[direction]
        actual_by_side[direction] = (
            bucket[0] + 1,
            bucket[1] + pnl,
            bucket[2] + net_r,
        )
        if matched_row.get("chart_path_present") is not True:
            missing.append(trade_id)
        elif (
            matched_row.get("chart_known_gap_duration_ms") is None
            or _int(
                matched_row.get("chart_known_gap_duration_ms"),
                "known gap duration",
            ) != 0
        ):
            gapped.append(trade_id)
        elif (
            matched_row.get("chart_coverage_complete") is not True
            or _int(matched_row.get("chart_mark_count"), "chart mark count") < 2
        ):
            incomplete.append(trade_id)
        else:
            clean.append(trade_id)
    if missing and any(trade_id not in rows for trade_id in missing):
        # Even the source journal itself lacks a paired original trade.
        raise DeferredEarlyExitChartIntegrityError(
            "paired exit refers to trade outside closed journal"
        )
    if (
        total_pnl != _dec(overall.get("original_net_pnl"), "paired original PnL")
        or total_r != _dec(overall.get("original_net_r"), "paired original R")
    ):
        raise DeferredEarlyExitChartIntegrityError(
            "paired original economics contradict verified journal"
        )
    if set(side) != {"long", "short"}:
        raise DeferredEarlyExitChartIntegrityError(
            "paired exit direction cohorts missing"
        )
    for direction, (side_count, pnl, net_r) in actual_by_side.items():
        baseline = _object(side[direction], f"{direction} paired side")
        if (
            _int(baseline.get("matched_trades"), "side count") != side_count
            or _dec(baseline.get("original_net_pnl"), "side pnl") != pnl
            or _dec(baseline.get("original_net_r"), "side R") != net_r
        ):
            raise DeferredEarlyExitChartIntegrityError(
                f"{direction} paired exit journal economics mismatch"
            )
    all_clean = (
        bool(matches)
        and not unmatched_forward
        and len(clean) == matches
        and matches == len(forward_rows)
    )
    return {
        "definition": "forward_matched_exit_chart_coverage_gate_v1",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "independent_portfolio_trial": False,
        "paired_start_ms": frozen_ms,
        "total_original_forward_trades": len(forward_rows),
        "matched_forward_trades": matches,
        "unmatched_original_forward_trade_ids": unmatched_forward,
        "verified_clean_chart_trades": len(clean),
        "missing_chart_trade_ids": sorted(missing),
        "known_data_gap_trade_ids": sorted(gapped),
        "incomplete_chart_trade_ids": sorted(incomplete),
        "chart_integrity_complete": all_clean,
        "unfiltered_original_net_pnl": str(forward_net_pnl),
        "unfiltered_original_net_r": str(forward_net_r),
        "matched_original_net_pnl": str(total_pnl),
        "matched_original_net_r": str(total_r),
        "original_exit_economic_screen_passes": (
            exits.get("economic_screen_passes") is True
        ),
        "economic_screen_with_chart_integrity": (
            exits.get("economic_screen_passes") is True and all_clean
        ),
        "ready_for_review": False,
        "caution": (
            "Full original forward cohort is retained, including unmatched " 
            "IOC outcomes; subset-only charts cannot claim completeness. "
            "No profits are re-estimated from mark extrema. Missing, incomplete "
            "or gapped charts disqualify claims of clean execution comparisons. "
            "Even all-clean matched-exit research does not replay portfolio "
            "capital availability, later entries, margin or drawdown."
        ),
    }


def rebuild_deferred_early_exit_chart_integrity(
    state_root: str | Path,
) -> Path:
    root = Path(state_root)
    def read(name: str) -> object:
        try:
            return json.loads((root / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeferredEarlyExitChartIntegrityError(
                f"missing or corrupt source: {name}"
            ) from exc

    session = _object(read("session-summary.json"), "session handoff")
    if session.get("exit_reason") not in (
        "duration_elapsed", "upgrade_requested"
    ):
        raise DeferredEarlyExitChartIntegrityError(
            "only completed paper worker can score closed positions"
        )
    evidence = assess_early_exit_chart_integrity(
        read(EXIT_REPORT_FILENAME), read(CHART_REPORT_FILENAME)
    )
    evidence["source_exit_reason"] = session["exit_reason"]
    destination = root / QUALITY_FILENAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        evidence, sort_keys=True, separators=(",", ":"), allow_nan=False
    ) + "\n"
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.tmp"
    )
    try:
        temporary.write_text(serialized, encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
