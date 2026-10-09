from __future__ import annotations

import json
import os
from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.journal import AUTHORITATIVE_CONTEXT

SOURCE_NAME: Final = "all-paper-trade-chart-audit.json"
OUTPUT_NAME: Final = "long-entry-loss-attribution.json"
ZERO: Final = Decimal("0")
QUARTER_R: Final = Decimal("0.25")
HALF_R: Final = Decimal("0.5")
CHART_MAX_UNOBSERVED_MS: Final = 300_000
UNKNOWN: Final = "unverified_entry_context"


class LongEntryLossAttributionError(RuntimeError):
    pass


def _obj(raw: object, name: str) -> dict[str, object]:
    if not isinstance(raw, dict) or not all(isinstance(x, str) for x in raw):
        raise LongEntryLossAttributionError(f"{name} must be an object")
    return cast(dict[str, object], raw)


def _int(raw: object, name: str) -> int:
    if type(raw) is not int or raw < 0:
        raise LongEntryLossAttributionError(f"{name} must be a nonnegative integer")
    return raw


def _dec(raw: object, name: str) -> Decimal:
    if not isinstance(raw, str):
        raise LongEntryLossAttributionError(f"{name} must be a decimal string")
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise LongEntryLossAttributionError(f"{name} invalid decimal") from exc
    if not number.is_finite():
        raise LongEntryLossAttributionError(f"{name} nonfinite decimal")
    return number


def _string(raw: object, name: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise LongEntryLossAttributionError(f"{name} must be a nonempty string")
    return raw


def _side(raw: object) -> str:
    if raw not in ("long", "short"):
        raise LongEntryLossAttributionError("trade has invalid direction")
    return str(raw)


def _sum(rows: list[dict[str, object]], field: str) -> Decimal:
    return sum((_dec(row[field], field) for row in rows), ZERO)


def _group(rows: list[dict[str, object]], global_blocks: dict[str, int]) -> dict[str, object]:
    ordered = sorted(rows, key=lambda row: (
        _int(row["closed_at_ms"], "close"), _string(row["trade_id"], "trade id")
    ))
    nets = [ZERO] * 4
    counts = [0] * 4
    for row in ordered:
        block = global_blocks[_string(row["trade_id"], "trade id")]
        nets[block] += _dec(row["net_pnl"], "net")
        counts[block] += 1
    losers = [row for row in ordered if _dec(row["net_pnl"], "net") < ZERO]
    winners = [row for row in ordered if _dec(row["net_pnl"], "net") > ZERO]
    markets = {_string(row["market"], "market") for row in ordered}
    return {
        "trades": len(ordered),
        "losers": len(losers),
        "winners": len(winners),
        "unique_markets": len(markets),
        "net_pnl": str(_sum(ordered, "net_pnl")),
        "net_r": str(_sum(ordered, "net_r")),
        "loser_net_pnl": str(_sum(losers, "net_pnl")),
        "winners_net_pnl": str(_sum(winners, "net_pnl")),
        "fees": str(sum((
            _dec(row["entry_fees"], "entry fees") +
            _dec(row["exit_fees"], "exit fees")
            for row in ordered
        ), ZERO)),
        "funding_cash_pnl": str(_sum(ordered, "funding_cash_pnl")),
        "chronological_global_block_counts": counts,
        "chronological_global_block_net_pnl": [str(x) for x in nets],
        "net_without_best_winner": str(
            _sum(ordered, "net_pnl") -
            max((_dec(row["net_pnl"], "net") for row in winners), default=ZERO)
        ),
    }


def _assess_long_entry_loss_attribution_precise(source: object) -> dict[str, object]:
    """Full-journal diagnostic. Never turn hindsight into a paper entry rule."""
    data = _obj(source, "trade chart audit")
    if data.get("definition") != (
        "entire_closed_paper_journal_with_observed_in_position_mark_charts_v1"
    ):
        raise LongEntryLossAttributionError("unexpected authenticated chart definition")
    if data.get("research_only") is not True or any(
        data.get(key) is not False
        for key in ("execution_authority", "promotion_authority")
    ):
        raise LongEntryLossAttributionError("source must have no execution authority")
    raw_rows = data.get("trades")
    if not isinstance(raw_rows, list):
        raise LongEntryLossAttributionError("closed journal rows missing")
    count = _int(data.get("total_journal_trades"), "journal count")
    if (
        len(raw_rows) != count
        or _int(data.get("trades_included_in_economics"), "economic count") != count
    ):
        raise LongEntryLossAttributionError("closed trade sample incomplete")
    economics = _obj(data.get("economics"), "chart economics")
    overall = _obj(economics.get("overall"), "chart overall")
    verified = _obj(data.get("verified_entry_exit_context"), "entry context audit")
    verified_overall = _obj(verified.get("overall"), "entry context overall")
    if _int(verified.get("trade_count"), "entry context count") != count:
        raise LongEntryLossAttributionError("entry context journal count drift")

    rows: list[dict[str, object]] = []
    ids: set[str] = set()
    verified_count = 0
    for raw in raw_rows:
        row = _obj(raw, "closed journal trade")
        identity = _string(row.get("trade_id"), "trade id")
        if identity in ids:
            raise LongEntryLossAttributionError("duplicated closed trade identity")
        ids.add(identity)
        direction = _side(row.get("side"))
        market = _string(row.get("market"), "market")
        opened = _int(row.get("opened_at_ms"), "open")
        closed = _int(row.get("closed_at_ms"), "close")
        if closed < opened:
            raise LongEntryLossAttributionError("noncausal trade chronology")
        net = _dec(row.get("net_pnl"), "net")
        _dec(row.get("net_r"), "net R")
        gross = _dec(row.get("gross_realized_pnl"), "gross")
        entry_fee = _dec(row.get("entry_fees"), "entry fees")
        exit_fee = _dec(row.get("exit_fees"), "exit fees")
        funding = _dec(row.get("funding_cash_pnl"), "funding")
        if entry_fee < ZERO or exit_fee < ZERO:
            raise LongEntryLossAttributionError("negative booked execution fee")
        # The journal validates each booked trade with the engine's fixed
        # 28-digit context and the exact operation ordering below. Only
        # *aggregation* of booked results uses the wider audit context.
        with localcontext(AUTHORITATIVE_CONTEXT):
            expected_net = gross - entry_fee - exit_fee + funding
        if expected_net != net:
            raise LongEntryLossAttributionError("trade cashflow mismatch")
        context = row.get("entry_context")
        if context is not None:
            original = _obj(context, "at-entry context")
            checks = {
                "trade_id": identity,
                "market": market,
                "direction": direction,
                "opened_at_ms": opened,
                "closed_at_ms": closed,
                "net_pnl": row["net_pnl"],
                "net_r": row["net_r"],
            }
            for key, expected in checks.items():
                if original.get(key) != expected:
                    raise LongEntryLossAttributionError(
                        f"verified at-entry context identity drift: {key}"
                    )
            for key in ("lead_strategy", "rank_band"):
                _string(original.get(key), key)
            verified_count += 1
        if row.get("chart_coverage_complete") is True:
            if (
                row.get("chart_path_present") is not True
                or _int(row.get("chart_mark_count"), "mark count") < 2
                or _int(row.get("chart_known_gap_duration_ms"), "known gap") != 0
                or _int(row.get("chart_longest_unobserved_mark_ms"), "silent gap")
                > CHART_MAX_UNOBSERVED_MS
            ):
                raise LongEntryLossAttributionError(
                    "chart claims complete path without underlying mark coverage"
                )
        rows.append(row)

    total_net = _sum(rows, "net_pnl")
    if (
        total_net != _dec(overall.get("net_pnl"), "chart total net")
        or total_net != _dec(verified_overall.get("net_pnl"), "context total net")
        or _int(overall.get("trades"), "overall trades") != count
        or verified_count != _int(
            verified.get("entry_context_verified_trades"), "verified entry count"
        )
        or count - verified_count != _int(
            verified.get("entry_context_unresolved_trades"), "unresolved entries"
        )
    ):
        raise LongEntryLossAttributionError("source total or attribution parity drift")

    ordered = sorted(rows, key=lambda row: (
        _int(row["closed_at_ms"], "close"), _string(row["trade_id"], "id")
    ))
    # Globally fixed time order; never make each loser cohort choose its own
    # favorable retrospective windows.
    blocks = {
        _string(row["trade_id"], "id"): min(3, 4 * index // max(1, count))
        for index, row in enumerate(ordered)
    }
    by_side: dict[str, list[dict[str, object]]] = {"long": [], "short": []}
    by_setup: dict[str, list[dict[str, object]]] = defaultdict(list)
    loss_buckets: dict[str, dict[str, list[dict[str, object]]]] = {
        "long": defaultdict(list),
        "short": defaultdict(list),
    }
    for row in ordered:
        side = _side(row["side"])
        by_side[side].append(row)
        context = row.get("entry_context")
        lead = UNKNOWN
        rank = UNKNOWN
        if context is not None:
            evidence = _obj(context, "context")
            lead = _string(evidence["lead_strategy"], "lead")
            rank = _string(evidence["rank_band"], "rank")
        by_setup[f"{side} | {lead} | {rank}"].append(row)

        net = _dec(row["net_pnl"], "net")
        gross = _dec(row["gross_realized_pnl"], "gross")
        if net >= ZERO:
            continue
        if gross > ZERO:
            category = "gross_winner_flipped_negative_after_costs"
        elif row.get("chart_coverage_complete") is not True or row.get("mfe_r") is None:
            category = "unknown_favorable_path_or_incomplete_chart"
        else:
            mfe = _dec(row["mfe_r"], "MFE R")
            if mfe < QUARTER_R:
                category = "loss_without_0_25r_favorable_move"
            elif mfe >= HALF_R:
                category = "loss_after_0_5r_favorable_move"
            else:
                category = "loss_after_0_25r_but_below_0_5r"
        loss_buckets[side][category].append(row)

    sides = {side: _group(members, blocks) for side, members in by_side.items()}
    if sum((_dec(x["net_pnl"], "side net") for x in sides.values()), ZERO) != total_net:
        raise LongEntryLossAttributionError("directional PnL does not reconcile")
    by_category = {
        side: {
            category: _group(members, blocks)
            for category, members in sorted(buckets.items())
        }
        for side, buckets in loss_buckets.items()
    }
    for side in ("long", "short"):
        if (
            sum((_int(v["trades"], "category count") for v in by_category[side].values()), 0)
            != _int(sides[side]["losers"], "side losers")
            or sum((
                _dec(v["net_pnl"], "category net")
                for v in by_category[side].values()
            ), ZERO) != _dec(sides[side]["loser_net_pnl"], "side loss")
        ):
            raise LongEntryLossAttributionError("loss categories omit realized losers")

    setups = {
        name: _group(members, blocks)
        for name, members in sorted(by_setup.items())
    }
    if (
        sum((_int(group["trades"], "setup count") for group in setups.values()), 0) != count
        or sum((_dec(group["net_pnl"], "setup net") for group in setups.values()), ZERO)
        != total_net
    ):
        raise LongEntryLossAttributionError("setup cohorts do not cover original trades")

    return {
        "definition": "full_journal_long_short_entry_vs_exit_loss_attribution_v1",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "can_select_entry_filter": False,
        "ready_for_review": False,
        "source_trades": count,
        "verified_entry_context_trades": verified_count,
        "missing_entry_context_trades": count - verified_count,
        "total_realized_closed_net_pnl": str(total_net),
        "by_side": sides,
        "loss_reasons_by_side": by_category,
        "by_entry_strategy_and_rank": setups,
        "chronological_blocks_are_global": True,
        "note": (
            "Descriptive attribution only. Net PnL and R reconcile to the "
            "complete historical journal, including losing or unverified trades. "
            "Gross-positive trades flipped by costs are counted separately; "
            "mark excursions require complete chart coverage and are not fills. "
            "Historical entry groups cannot authorize trade skipping or establish "
            "causality. Frozen prospective full-account paired tests, risk and "
            "drawdown gates are necessary for any entry or exit change."
        ),
    }



def assess_long_entry_loss_attribution(
    source: object,
) -> dict[str, object]:
    """Aggregate unrounded journal decimals before checking cohort parity."""
    with localcontext(prec=96):
        return _assess_long_entry_loss_attribution_precise(source)


def write_long_entry_loss_attribution(state_root: str | Path) -> Path:
    root = Path(state_root)
    try:
        session = _obj(
            json.loads((root / "session-summary.json").read_text(encoding="utf-8")),
            "paper handoff",
        )
        if session.get("exit_reason") not in ("duration_elapsed", "upgrade_requested"):
            raise LongEntryLossAttributionError("paper handoff not complete")
        source = json.loads((root / SOURCE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LongEntryLossAttributionError(
            "missing or invalid authenticated paper evidence"
        ) from exc
    output = assess_long_entry_loss_attribution(source)
    output["source_exit_reason"] = session["exit_reason"]
    destination = root / OUTPUT_NAME
    tmp = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n", encoding="utf-8"
        )
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)
    return destination
