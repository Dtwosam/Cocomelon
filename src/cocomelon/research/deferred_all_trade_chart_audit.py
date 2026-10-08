from __future__ import annotations

import html
import json
import os
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.closed_trade_lifecycle_economics import (
    closed_trade_lifecycle_economics,
)
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathStore,
)

REPORT_FILENAME: Final = "all-paper-trade-chart-audit.json"
CHART_FILENAME: Final = "all-paper-trade-charts.html"
MAX_MARKS_PER_TRADE: Final = 144
ZERO: Final = Decimal("0")
_HANDOFF_REASONS: Final = frozenset({"duration_elapsed", "upgrade_requested"})


class AllPaperTradeChartAuditError(RuntimeError):
    pass


def _dec(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AllPaperTradeChartAuditError(f"invalid {field}") from exc
    if not result.is_finite():
        raise AllPaperTradeChartAuditError(f"nonfinite {field}")
    return result


def _compact_marks(marks: object) -> list[list[object]]:
    """Time-ordered, bucketed chart samples retaining local peaks and troughs."""
    if not isinstance(marks, list):
        raise AllPaperTradeChartAuditError("trade marks must be an array")
    samples: list[tuple[int, Decimal]] = []
    for mark in marks:
        if not isinstance(mark, dict):
            raise AllPaperTradeChartAuditError("trade mark invalid")
        timestamp = mark.get("available_at_ms")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise AllPaperTradeChartAuditError("trade mark timestamp invalid")
        px = _dec(mark.get("mark_px"), "mark price")
        if px <= ZERO:
            raise AllPaperTradeChartAuditError("trade mark must be positive")
        samples.append((timestamp, px))
    if len(samples) <= MAX_MARKS_PER_TRADE:
        selected = samples
    else:
        selected = []
        # Up to 36 chronological buckets, each contributing first,
        # local minimum, local maximum and last. Never preserve just a
        # smooth average that hides a stop sweep or reversal.
        buckets = MAX_MARKS_PER_TRADE // 4
        for index in range(buckets):
            lo = len(samples) * index // buckets
            hi = len(samples) * (index + 1) // buckets
            group = samples[lo:hi]
            chosen = {0, len(group) - 1}
            chosen.add(min(range(len(group)), key=lambda x: group[x][1]))
            chosen.add(max(range(len(group)), key=lambda x: group[x][1]))
            selected.extend(group[x] for x in sorted(chosen))
    return [[timestamp, str(px)] for timestamp, px in selected]


def _path_gap_ms(path: dict[str, object], opened: int, closed: int) -> int | None:
    intervals = path.get("known_gap_intervals")
    if not isinstance(intervals, list):
        raise AllPaperTradeChartAuditError("trade path missing gap witness")
    covered: list[tuple[int, int]] = []
    for item in intervals:
        if not isinstance(item, list) or len(item) != 2:
            raise AllPaperTradeChartAuditError("invalid trade path gap")
        a, b = item
        if type(a) is not int or (b is not None and type(b) is not int):
            raise AllPaperTradeChartAuditError("invalid trade path gap times")
        if b is None:
            if a < closed:
                return None
            continue
        if b < a:
            raise AllPaperTradeChartAuditError("reversed trade path gap")
        if a < closed and b > opened:
            covered.append((max(a, opened), min(b, closed)))
    total = 0
    latest = opened
    for a, b in sorted(covered):
        if b > latest:
            total += b - max(latest, a)
            latest = b
    return total


def all_paper_trade_chart_audit(
    trades: Sequence[TradeJournalEntry],
    facts: EvaluationFactStore,
    path_payloads: Sequence[dict[str, object]],
) -> dict[str, object]:
    ordered = tuple(sorted(trades, key=lambda t: (t.closed_at_ms, t.trade_id)))
    if len({t.trade_id for t in ordered}) != len(ordered):
        raise AllPaperTradeChartAuditError("duplicate journal trade IDs")
    paths: dict[str, dict[str, object]] = {}
    for path in path_payloads:
        trade_id = path.get("trade_id")
        if not isinstance(trade_id, str) or trade_id in paths:
            raise AllPaperTradeChartAuditError("duplicate or invalid trade path ID")
        paths[trade_id] = path
    economics = closed_trade_lifecycle_economics(ordered, facts)
    rows: list[dict[str, object]] = []
    missing: list[str] = []
    complete_path_count = 0
    gap_affected = 0
    empty_marks = 0
    cumulative_net = ZERO
    for trade in ordered:
        candidate = paths.get(trade.trade_id)
        compact: list[list[object]] = []
        gap_ms: int | None = None
        complete = False
        if candidate is not None:
            expected = {
                "market": trade.market.canonical,
                "direction": trade.direction.value,
                "opened_at_ms": trade.opened_at_ms,
                "closed_at_ms": trade.closed_at_ms,
                "entry_price": str(trade.entry_price),
                "exit_price": str(trade.exit_price),
            }
            for field, value in expected.items():
                actual = candidate.get(field)
                if field.endswith("_price"):
                    if _dec(actual, field) != Decimal(value):
                        raise AllPaperTradeChartAuditError(
                            f"trade/chart entry-exit mismatch: {field}"
                        )
                elif actual != value:
                    raise AllPaperTradeChartAuditError(
                        f"trade/chart lifecycle mismatch: {field}"
                    )
            compact = _compact_marks(candidate.get("marks"))
            gap_ms = _path_gap_ms(
                candidate, trade.opened_at_ms, trade.closed_at_ms
            )
            complete = (
                candidate.get("path_complete") is True
                and bool(compact)
                and gap_ms == 0
            )
            if gap_ms is None or gap_ms > 0:
                gap_affected += 1
            if not compact:
                empty_marks += 1
            if complete:
                complete_path_count += 1
        else:
            missing.append(trade.trade_id)
        cumulative_net += trade.net_pnl
        rows.append({
            "trade_id": trade.trade_id,
            "market": trade.market.canonical,
            "side": trade.direction.value,
            "opened_at_ms": trade.opened_at_ms,
            "closed_at_ms": trade.closed_at_ms,
            "entry_price": str(trade.entry_price),
            "exit_price": str(trade.exit_price),
            "initial_stop": str(trade.initial_stop),
            "exit_reason": trade.exit_reason,
            "holding_duration_ms": trade.holding_duration_ms,
            "gross_realized_pnl": str(trade.gross_realized_pnl),
            "entry_fees": str(trade.entry_fees),
            "exit_fees": str(trade.exit_fees),
            "funding_cash_pnl": str(trade.funding_cash_pnl),
            "entry_signed_slippage": str(trade.entry_slippage_amount),
            "exit_signed_slippage": str(trade.exit_slippage_amount),
            "net_pnl": str(trade.net_pnl),
            "net_r": str(trade.net_r),
            "cumulative_closed_net_pnl": str(cumulative_net),
            "mfe_r": (
                None if trade.mfe is None or not trade.mfe.complete
                else (None if trade.mfe.r_multiple is None
                      else str(trade.mfe.r_multiple))
            ),
            "mae_r": (
                None if trade.mae is None or not trade.mae.complete
                else (None if trade.mae.r_multiple is None
                      else str(trade.mae.r_multiple))
            ),
            "chart_path_present": candidate is not None,
            "chart_coverage_complete": complete,
            "chart_known_gap_duration_ms": gap_ms,
            "chart_mark_count": (
                0 if candidate is None else len(candidate["marks"])
            ),
            "chart_mark_samples": compact,
        })
    extra = sorted(set(paths) - {t.trade_id for t in ordered})
    if extra:
        raise AllPaperTradeChartAuditError(
            "trade path exists without a journal trade"
        )
    overall = economics["overall"]
    if not isinstance(overall, dict) or _dec(overall["net_pnl"], "net") != cumulative_net:
        raise AllPaperTradeChartAuditError("all-trade net PnL does not reconcile")
    return {
        "definition": "entire_closed_paper_journal_with_observed_in_position_mark_charts_v1",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "backtest_optimized": False,
        "caution": (
            "Only contemporaneously recorded IN-POSITION mark prices are charted. "
            "No pre-entry candles, OHLC wicks, executable stop fills or counterfactual "
            "PnL are implied by mark extrema. Missing early path/context is explicit. "
            "Any strategy change requires a frozen prospective fill-aware comparison."
        ),
        "total_journal_trades": len(ordered),
        "trades_included_in_economics": overall["trades"],
        "complete_chart_paths": complete_path_count,
        "missing_chart_path_trade_ids": missing,
        "incomplete_or_gapped_chart_paths": (
            len(ordered) - len(missing) - complete_path_count
        ),
        "path_gap_affected_trades": gap_affected,
        "path_without_marks_trades": empty_marks,
        "economics": economics,
        "trades": rows,
    }


def render_trade_charts(report: dict[str, object]) -> str:
    rows = report["trades"]
    if not isinstance(rows, list):
        raise AllPaperTradeChartAuditError("trade rows missing")
    safe_json = json.dumps(rows, separators=(",", ":"), ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    headline = html.escape(str(report["total_journal_trades"]))
    # Offline, dependency-free; marks are prices, never theoretical fills.
    return """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Cocomelon — All Closed Paper Trade Charts</title>
<style>body{background:#101725;color:#f1f5f9;font:15px system-ui;margin:24px;max-width:1150px}
h1{font-size:26px}select{background:#1e293b;color:#f8fafc;padding:10px;max-width:100%}
#meta{white-space:pre-wrap;line-height:1.7}svg{width:100%;height:420px;background:#172334;border-radius:12px}
.note{color:#bac7d8} .positive{color:#7dd3a0}.negative{color:#fca5a5}</style>
<h1>Cocomelon · All """ + headline + """ closed paper trades</h1>
<p class="note">Historical research only. Price lines are sampled, recorded
IN-POSITION mark prices—not OHLC candles or executable limit fills.
Incomplete or missing chart evidence is disclosed, never filled in.</p>
<label for="trade">Trade</label> <select id="trade"></select>
<p id="meta"></p><svg id="chart" viewBox="0 0 1000 420"
 role="img" aria-label="Recorded mark price chart"></svg>
<p class="note">Entry = dashed blue, initial stop = dashed red, actual exit = dashed white.
The price path may have gaps; do not infer an executable profit target from a mark high.</p>
<script>const rows = """ + safe_json + """;
const sel=document.getElementById('trade'), meta=document.getElementById('meta'),
 svg=document.getElementById('chart');
function S(tag,attrs){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);
 for(const [k,v] of Object.entries(attrs)) n.setAttribute(k,String(v));svg.appendChild(n);return n;}
rows.forEach((r,i)=>{const o=document.createElement('option');o.value=String(i);
 o.textContent=(i+1)+' · '+r.market+' '+r.side+' · '+r.net_pnl;sel.appendChild(o);});
function render(){svg.replaceChildren();const r=rows[Number(sel.value)||0];if(!r){return;}
 meta.textContent='Trade '+r.trade_id+' | '+r.side.toUpperCase()+' '+r.market+
 ' | realized after-cost PnL $'+r.net_pnl+' ('+r.net_r+'R)'+
 '\\nExit: '+r.exit_reason+' | Gross $'+r.gross_realized_pnl+
 ' | Fees $'+(Number(r.entry_fees)+Number(r.exit_fees)).toFixed(4)+
 ' | Funding $'+r.funding_cash_pnl+
 '\\nPath complete: '+r.chart_coverage_complete+' | Marks: '+r.chart_mark_count+
 ' | Known data gap ms: '+r.chart_known_gap_duration_ms+
 ' | Peak favorable R: '+r.mfe_r+' | Peak adverse R: '+r.mae_r;
 const p=r.chart_mark_samples.map(a=>[Number(a[0]),Number(a[1])]);
 const levels=[Number(r.entry_price),Number(r.initial_stop),Number(r.exit_price)];
 const prices=p.map(a=>a[1]).concat(levels);const lo=Math.min(...prices),hi=Math.max(...prices);
 const span=Math.max(hi-lo,Math.abs(hi)*0.000001);const x0=p.length?p[0][0]:r.opened_at_ms;
 const x1=p.length?p[p.length-1][0]:r.closed_at_ms;
 const x=t=>40+920*(t-x0)/Math.max(1,x1-x0);
 const y=v=>385-335*(v-lo+span*0.08)/(span*1.16);
 const colors=['#60a5fa','#f87171','#f8fafc'];
 levels.forEach((v,i)=>{S('line',{x1:40,x2:960,y1:y(v),y2:y(v),
 stroke:colors[i],'stroke-dasharray':'6 5','stroke-width':1.6});});
 if(p.length) S('polyline',{points:p.map(a=>x(a[0])+','+y(a[1])).join(' '),
 fill:'none',stroke:'#4ade80','stroke-width':2});
 else {const n=S('text',{x:65,y:80,fill:'#fca5a5'});
 n.textContent='No recorded chart path for this trade';}
}sel.addEventListener('change',render);render();</script></html>
"""


def write_deferred_trade_charts(
    state_root: str | Path,
) -> tuple[Path, Path, dict[str, object]]:
    root = Path(state_root)
    session = json.loads((root / "session-summary.json").read_text(encoding="utf-8"))
    if (
        not isinstance(session, dict)
        or session.get("exit_reason") not in _HANDOFF_REASONS
    ):
        raise AllPaperTradeChartAuditError("requires completed paper handoff")
    for filename in ("journal.sqlite3", "facts.sqlite3"):
        store_path = root / filename
        if not store_path.is_file() or store_path.stat().st_size <= 0:
            raise AllPaperTradeChartAuditError(
                f"missing authoritative paper store: {filename}"
            )
    journal = JournalStore(root / "journal.sqlite3")
    facts = EvaluationFactStore(root / "facts.sqlite3")
    try:
        trades = tuple(journal.iter_trades())
        paths = ContinuousPaperTradePathStore(root / "trade-paths").iter_payloads()
        report = all_paper_trade_chart_audit(trades, facts, paths)
    finally:
        facts.close()
        journal.close()
    report["source_exit_reason"] = session["exit_reason"]
    report["deferred_after_successor_dispatch"] = True
    report_path = root / REPORT_FILENAME
    chart_path = root / CHART_FILENAME
    for path, data in (
        (report_path, json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)),
        (chart_path, render_trade_charts(report)),
    ):
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temp.write_text(data + "\n", encoding="utf-8")
        os.replace(temp, path)
    return report_path, chart_path, report
