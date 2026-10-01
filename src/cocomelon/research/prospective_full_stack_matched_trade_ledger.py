from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "prospective-full-stack-matched-trade-ledger-v1"
ZERO: Final = Decimal("0")
MIN_TERMINAL_TRADES: Final = 30
MIN_ENTRY_BLOCKED_TRADES: Final = 5
MIN_ENTRY_ADMITTED_TRADES: Final = 10
MIN_TRADES_PER_DIRECTION: Final = 5
MIN_MARKETS: Final = 4


class ProspectiveFullStackMatchedTradeLedgerError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "ledger_sha256"
    }


def _required_int(
    raw: dict[str, object],
    key: str,
) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            f"{key} must be an integer"
        )
    return value


def _required_string(
    raw: dict[str, object],
    key: str,
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveFullStackMatchedTradeLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _decimal_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            f"{field} must be a string"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            f"{field} must be a decimal"
        ) from exc
    if not parsed.is_finite():
        raise ProspectiveFullStackMatchedTradeLedgerError(
            f"{field} must be finite"
        )
    return value


def _validate_authority(summary: dict[str, object]) -> None:
    if summary.get("research_only") is not True:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack summary must be research-only"
        )
    if summary.get("execution_authority") is not False:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack summary must not grant execution authority"
        )
    if summary.get("promotion_authority") is not False:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack summary must not grant promotion authority"
        )
    if summary.get("changes_readiness_gate") is not False:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack summary must not change readiness gates"
        )
    if summary.get("claim_scope") != "matched_trade_contribution_only":
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack summary claim scope drift"
        )
    if summary.get("portfolio_counterfactual") is not False:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack summary cannot claim portfolio PnL"
        )
    if summary.get("replacement_trades_modeled") is not False:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "replacement trades must remain separate"
        )


def _campaign(
    summary: dict[str, object],
) -> dict[str, int]:
    values = {
        "overlap_started_at_ms": _required_int(
            summary,
            "overlap_started_at_ms",
        ),
        "combined_started_at_ms": _required_int(
            summary,
            "combined_started_at_ms",
        ),
        "two_strike_started_at_ms": _required_int(
            summary,
            "two_strike_started_at_ms",
        ),
        "momentum_started_at_ms": _required_int(
            summary,
            "momentum_started_at_ms",
        ),
        "breakeven_started_at_ms": _required_int(
            summary,
            "breakeven_started_at_ms",
        ),
    }
    if any(value < 0 for value in values.values()):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack campaign timestamps must be non-negative"
        )
    if values["overlap_started_at_ms"] != max(
        values["combined_started_at_ms"],
        values["two_strike_started_at_ms"],
        values["momentum_started_at_ms"],
        values["breakeven_started_at_ms"],
    ):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack overlap start does not reconcile"
        )
    return values


def _canonical_row(
    trade: TradeJournalEntry,
    decision: dict[str, object],
) -> dict[str, object] | None:
    entry_decision = decision.get("entry_decision")
    exit_evaluation = decision.get("exit_evaluation")
    if entry_decision not in {"BLOCK", "ADMIT"}:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "entry decision must be BLOCK or ADMIT"
        )
    if exit_evaluation not in {
        "NOT_APPLICABLE",
        "EVALUATED",
        "MISSING",
        "UNEVALUABLE",
    }:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "exit evaluation is invalid"
        )

    if trade.initial_risk_amount <= ZERO:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "trade initial risk must be positive"
        )
    if trade.net_r != trade.net_pnl / trade.initial_risk_amount:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "actual trade net R does not reconcile"
        )

    if entry_decision == "BLOCK":
        if exit_evaluation != "NOT_APPLICABLE":
            raise ProspectiveFullStackMatchedTradeLedgerError(
                "blocked entry cannot have exit evaluation"
            )
        candidate_pnl = _decimal_string(
            decision.get("candidate_net_pnl"),
            field="candidate_net_pnl",
        )
        candidate_r = _decimal_string(
            decision.get("candidate_net_r"),
            field="candidate_net_r",
        )
        if Decimal(candidate_pnl) != ZERO or Decimal(candidate_r) != ZERO:
            raise ProspectiveFullStackMatchedTradeLedgerError(
                "blocked entry candidate economics must be zero"
            )
        breakeven_activated: bool | None = None
        breakeven_triggered: bool | None = None
        breakeven_source: str | None = None
    else:
        if exit_evaluation in {"MISSING", "UNEVALUABLE"}:
            if (
                decision.get("candidate_net_pnl") is not None
                or decision.get("candidate_net_r") is not None
            ):
                raise ProspectiveFullStackMatchedTradeLedgerError(
                    "pending exit cannot carry candidate economics"
                )
            return None
        if exit_evaluation != "EVALUATED":
            raise ProspectiveFullStackMatchedTradeLedgerError(
                "admitted entry must have evaluated or pending exit"
            )
        candidate_pnl = _decimal_string(
            decision.get("candidate_net_pnl"),
            field="candidate_net_pnl",
        )
        candidate_r = _decimal_string(
            decision.get("candidate_net_r"),
            field="candidate_net_r",
        )
        if Decimal(candidate_r) != (
            Decimal(candidate_pnl) / trade.initial_risk_amount
        ):
            raise ProspectiveFullStackMatchedTradeLedgerError(
                "candidate net R does not reconcile"
            )
        activated = decision.get("breakeven_activated")
        triggered = decision.get("breakeven_triggered")
        source = decision.get("breakeven_source")
        if not isinstance(activated, bool) or not isinstance(
            triggered,
            bool,
        ):
            raise ProspectiveFullStackMatchedTradeLedgerError(
                "evaluated breakeven flags must be booleans"
            )
        if not isinstance(source, str) or not source.strip():
            raise ProspectiveFullStackMatchedTradeLedgerError(
                "evaluated breakeven source must be a string"
            )
        breakeven_activated = activated
        breakeven_triggered = triggered
        breakeven_source = source

    entry_candidate_pnl = (
        ZERO
        if entry_decision == "BLOCK"
        else trade.net_pnl
    )
    entry_candidate_r = (
        ZERO
        if entry_decision == "BLOCK"
        else trade.net_r
    )
    return {
        "trade_id": trade.trade_id,
        "opening_plan_id": trade.opening_plan_id,
        "market": trade.market.canonical,
        "direction": trade.direction.value,
        "opened_at_ms": trade.opened_at_ms,
        "closed_at_ms": trade.closed_at_ms,
        "initial_risk_amount": str(trade.initial_risk_amount),
        "actual_net_pnl": str(trade.net_pnl),
        "actual_net_r": str(trade.net_r),
        "entry_decision": entry_decision,
        "exit_evaluation": exit_evaluation,
        "entry_stack_candidate_net_pnl": str(entry_candidate_pnl),
        "entry_stack_candidate_net_r": str(entry_candidate_r),
        "full_stack_candidate_net_pnl": candidate_pnl,
        "full_stack_candidate_net_r": candidate_r,
        "full_stack_delta_net_pnl": str(
            Decimal(candidate_pnl) - trade.net_pnl
        ),
        "full_stack_delta_net_r": str(
            Decimal(candidate_r) - trade.net_r
        ),
        "breakeven_incremental_net_pnl": str(
            Decimal(candidate_pnl) - entry_candidate_pnl
        ),
        "breakeven_incremental_net_r": str(
            Decimal(candidate_r) - entry_candidate_r
        ),
        "breakeven_activated": breakeven_activated,
        "breakeven_triggered": breakeven_triggered,
        "breakeven_source": breakeven_source,
    }


def _terminal_rows(
    trades: Sequence[TradeJournalEntry],
    summary: dict[str, object],
    *,
    overlap_started_at_ms: int,
) -> tuple[tuple[dict[str, object], ...], int]:
    raw_decisions = summary.get("decision_by_trade_id")
    if not isinstance(raw_decisions, dict):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack decision map must be an object"
        )

    prospective = tuple(
        sorted(
            (
                trade
                for trade in trades
                if trade.opened_at_ms >= overlap_started_at_ms
            ),
            key=lambda trade: (
                trade.opened_at_ms,
                trade.closed_at_ms,
                trade.trade_id,
            ),
        )
    )
    ids = tuple(trade.trade_id for trade in prospective)
    if len(ids) != len(set(ids)):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "prospective journal contains duplicate trade ids"
        )

    rows: list[dict[str, object]] = []
    pending = 0
    for trade in prospective:
        raw = raw_decisions.get(trade.trade_id)
        if raw is None:
            pending += 1
            continue
        if not isinstance(raw, dict):
            raise ProspectiveFullStackMatchedTradeLedgerError(
                "full-stack trade decision must be an object"
            )
        row = _canonical_row(trade, raw)
        if row is None:
            pending += 1
            continue
        rows.append(row)

    expected_closed = _required_int(
        summary,
        "closed_trades_since_overlap_start",
    )
    if expected_closed != len(prospective):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack closed-trade count does not reconcile"
        )
    expected_evaluated = _required_int(
        summary,
        "economically_evaluated_trades",
    )
    if expected_evaluated != len(rows):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack evaluated-trade count does not reconcile"
        )
    return tuple(rows), pending


def _rows_sha256(
    rows: tuple[dict[str, object], ...],
) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _cohort(
    rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    actual_pnl = sum(
        (Decimal(cast(str, row["actual_net_pnl"])) for row in rows),
        ZERO,
    )
    actual_r = sum(
        (Decimal(cast(str, row["actual_net_r"])) for row in rows),
        ZERO,
    )
    entry_pnl = sum(
        (
            Decimal(
                cast(str, row["entry_stack_candidate_net_pnl"])
            )
            for row in rows
        ),
        ZERO,
    )
    entry_r = sum(
        (
            Decimal(
                cast(str, row["entry_stack_candidate_net_r"])
            )
            for row in rows
        ),
        ZERO,
    )
    full_pnl = sum(
        (
            Decimal(
                cast(str, row["full_stack_candidate_net_pnl"])
            )
            for row in rows
        ),
        ZERO,
    )
    full_r = sum(
        (
            Decimal(
                cast(str, row["full_stack_candidate_net_r"])
            )
            for row in rows
        ),
        ZERO,
    )
    return {
        "trades": len(rows),
        "entry_blocked_trades": sum(
            row["entry_decision"] == "BLOCK" for row in rows
        ),
        "entry_admitted_trades": sum(
            row["entry_decision"] == "ADMIT" for row in rows
        ),
        "actual_net_pnl": str(actual_pnl),
        "actual_net_r": str(actual_r),
        "entry_stack_candidate_net_pnl": str(entry_pnl),
        "entry_stack_candidate_net_r": str(entry_r),
        "entry_stack_delta_net_pnl": str(entry_pnl - actual_pnl),
        "entry_stack_delta_net_r": str(entry_r - actual_r),
        "full_stack_candidate_net_pnl": str(full_pnl),
        "full_stack_candidate_net_r": str(full_r),
        "full_stack_delta_net_pnl": str(full_pnl - actual_pnl),
        "full_stack_delta_net_r": str(full_r - actual_r),
        "breakeven_incremental_net_pnl": str(full_pnl - entry_pnl),
        "breakeven_incremental_net_r": str(full_r - entry_r),
    }


def _robustness(
    rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    candidate_pnl = tuple(
        Decimal(cast(str, row["full_stack_candidate_net_pnl"]))
        for row in rows
    )
    candidate_r = tuple(
        Decimal(cast(str, row["full_stack_candidate_net_r"]))
        for row in rows
    )
    delta_pnl = tuple(
        Decimal(cast(str, row["full_stack_delta_net_pnl"]))
        for row in rows
    )
    delta_r = tuple(
        Decimal(cast(str, row["full_stack_delta_net_r"]))
        for row in rows
    )
    total_candidate_pnl = sum(candidate_pnl, ZERO)
    total_candidate_r = sum(candidate_r, ZERO)
    total_delta_pnl = sum(delta_pnl, ZERO)
    total_delta_r = sum(delta_r, ZERO)

    leave_trade_candidate_pnl = tuple(
        total_candidate_pnl - value for value in candidate_pnl
    )
    leave_trade_candidate_r = tuple(
        total_candidate_r - value for value in candidate_r
    )
    leave_trade_delta_pnl = tuple(
        total_delta_pnl - value for value in delta_pnl
    )
    leave_trade_delta_r = tuple(
        total_delta_r - value for value in delta_r
    )

    by_market_candidate_pnl: dict[str, Decimal] = {}
    by_market_candidate_r: dict[str, Decimal] = {}
    by_market_delta_pnl: dict[str, Decimal] = {}
    by_market_delta_r: dict[str, Decimal] = {}
    for row in rows:
        market = cast(str, row["market"])
        by_market_candidate_pnl[market] = (
            by_market_candidate_pnl.get(market, ZERO)
            + Decimal(
                cast(str, row["full_stack_candidate_net_pnl"])
            )
        )
        by_market_candidate_r[market] = (
            by_market_candidate_r.get(market, ZERO)
            + Decimal(
                cast(str, row["full_stack_candidate_net_r"])
            )
        )
        by_market_delta_pnl[market] = (
            by_market_delta_pnl.get(market, ZERO)
            + Decimal(cast(str, row["full_stack_delta_net_pnl"]))
        )
        by_market_delta_r[market] = (
            by_market_delta_r.get(market, ZERO)
            + Decimal(cast(str, row["full_stack_delta_net_r"]))
        )

    leave_market_candidate_pnl = tuple(
        total_candidate_pnl - value
        for value in by_market_candidate_pnl.values()
    )
    leave_market_candidate_r = tuple(
        total_candidate_r - value
        for value in by_market_candidate_r.values()
    )
    leave_market_delta_pnl = tuple(
        total_delta_pnl - value
        for value in by_market_delta_pnl.values()
    )
    leave_market_delta_r = tuple(
        total_delta_r - value
        for value in by_market_delta_r.values()
    )

    return {
        "market_count": len(by_market_candidate_pnl),
        "candidate_leave_one_trade_out_min_pnl": (
            None
            if not leave_trade_candidate_pnl
            else str(min(leave_trade_candidate_pnl))
        ),
        "candidate_leave_one_trade_out_min_r": (
            None
            if not leave_trade_candidate_r
            else str(min(leave_trade_candidate_r))
        ),
        "candidate_positive_after_removing_any_one_trade": (
            len(rows) >= 2
            and min(leave_trade_candidate_pnl, default=ZERO) > ZERO
            and min(leave_trade_candidate_r, default=ZERO) > ZERO
        ),
        "candidate_leave_one_market_out_min_pnl": (
            None
            if not leave_market_candidate_pnl
            else str(min(leave_market_candidate_pnl))
        ),
        "candidate_leave_one_market_out_min_r": (
            None
            if not leave_market_candidate_r
            else str(min(leave_market_candidate_r))
        ),
        "candidate_positive_after_removing_any_one_market": (
            len(by_market_candidate_pnl) >= 2
            and min(leave_market_candidate_pnl, default=ZERO) > ZERO
            and min(leave_market_candidate_r, default=ZERO) > ZERO
        ),
        "delta_leave_one_trade_out_min_pnl": (
            None
            if not leave_trade_delta_pnl
            else str(min(leave_trade_delta_pnl))
        ),
        "delta_leave_one_trade_out_min_r": (
            None
            if not leave_trade_delta_r
            else str(min(leave_trade_delta_r))
        ),
        "delta_positive_after_removing_any_one_trade": (
            len(rows) >= 2
            and min(leave_trade_delta_pnl, default=ZERO) > ZERO
            and min(leave_trade_delta_r, default=ZERO) > ZERO
        ),
        "delta_leave_one_market_out_min_pnl": (
            None
            if not leave_market_delta_pnl
            else str(min(leave_market_delta_pnl))
        ),
        "delta_leave_one_market_out_min_r": (
            None
            if not leave_market_delta_r
            else str(min(leave_market_delta_r))
        ),
        "delta_positive_after_removing_any_one_market": (
            len(by_market_delta_pnl) >= 2
            and min(leave_market_delta_pnl, default=ZERO) > ZERO
            and min(leave_market_delta_r, default=ZERO) > ZERO
        ),
    }


def _summary(
    rows: tuple[dict[str, object], ...],
    *,
    pending_trade_count: int,
) -> dict[str, object]:
    overall = _cohort(rows)
    by_direction = {
        direction.value: _cohort(
            tuple(
                row
                for row in rows
                if row["direction"] == direction.value
            )
        )
        for direction in (Direction.LONG, Direction.SHORT)
    }
    markets = sorted({cast(str, row["market"]) for row in rows})
    by_market = {
        market: _cohort(
            tuple(row for row in rows if row["market"] == market)
        )
        for market in markets
    }
    robustness = _robustness(rows)

    candidate_pnl = Decimal(
        cast(str, overall["full_stack_candidate_net_pnl"])
    )
    candidate_r = Decimal(
        cast(str, overall["full_stack_candidate_net_r"])
    )
    delta_pnl = Decimal(
        cast(str, overall["full_stack_delta_net_pnl"])
    )
    delta_r = Decimal(
        cast(str, overall["full_stack_delta_net_r"])
    )
    long_count = cast(
        int,
        by_direction["long"]["trades"],
    )
    short_count = cast(
        int,
        by_direction["short"]["trades"],
    )
    blocked = cast(int, overall["entry_blocked_trades"])
    admitted = cast(int, overall["entry_admitted_trades"])
    market_count = len(markets)

    sample_complete = (
        len(rows) >= MIN_TERMINAL_TRADES
        and blocked >= MIN_ENTRY_BLOCKED_TRADES
        and admitted >= MIN_ENTRY_ADMITTED_TRADES
        and long_count >= MIN_TRADES_PER_DIRECTION
        and short_count >= MIN_TRADES_PER_DIRECTION
        and market_count >= MIN_MARKETS
    )
    integrity_complete = pending_trade_count == 0
    candidate_profitable = candidate_pnl > ZERO and candidate_r > ZERO
    improvement_positive = delta_pnl > ZERO and delta_r > ZERO
    candidate_trade_robust = (
        robustness[
            "candidate_positive_after_removing_any_one_trade"
        ]
        is True
    )
    candidate_market_robust = (
        robustness[
            "candidate_positive_after_removing_any_one_market"
        ]
        is True
    )
    delta_trade_robust = (
        robustness["delta_positive_after_removing_any_one_trade"]
        is True
    )
    delta_market_robust = (
        robustness["delta_positive_after_removing_any_one_market"]
        is True
    )

    return {
        "overall": overall,
        "by_direction": by_direction,
        "by_market": by_market,
        "robustness": robustness,
        "review_readiness": {
            "sample_complete": sample_complete,
            "integrity_complete": integrity_complete,
            "candidate_profitable": candidate_profitable,
            "improvement_positive": improvement_positive,
            "candidate_single_trade_robust": candidate_trade_robust,
            "candidate_single_market_robust": candidate_market_robust,
            "delta_single_trade_robust": delta_trade_robust,
            "delta_single_market_robust": delta_market_robust,
            "ready_for_evidence_review": (
                sample_complete
                and integrity_complete
                and candidate_profitable
                and improvement_positive
                and candidate_trade_robust
                and candidate_market_robust
                and delta_trade_robust
                and delta_market_robust
            ),
            "min_terminal_trades": MIN_TERMINAL_TRADES,
            "min_entry_blocked_trades": MIN_ENTRY_BLOCKED_TRADES,
            "min_entry_admitted_trades": MIN_ENTRY_ADMITTED_TRADES,
            "min_trades_per_direction": MIN_TRADES_PER_DIRECTION,
            "min_markets": MIN_MARKETS,
            "missing_terminal_trades": max(
                0,
                MIN_TERMINAL_TRADES - len(rows),
            ),
            "missing_entry_blocked_trades": max(
                0,
                MIN_ENTRY_BLOCKED_TRADES - blocked,
            ),
            "missing_entry_admitted_trades": max(
                0,
                MIN_ENTRY_ADMITTED_TRADES - admitted,
            ),
            "missing_long_trades": max(
                0,
                MIN_TRADES_PER_DIRECTION - long_count,
            ),
            "missing_short_trades": max(
                0,
                MIN_TRADES_PER_DIRECTION - short_count,
            ),
            "missing_markets": max(0, MIN_MARKETS - market_count),
            "pending_trade_count": pending_trade_count,
            "changes_execution": False,
            "changes_readiness_gate": False,
        },
    }


def validate_full_stack_matched_trade_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack matched-trade ledger must be an object"
        )
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack matched-trade ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack matched-trade ledger kind is unsupported"
        )
    campaign = raw.get("campaign")
    if not isinstance(campaign, dict):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack ledger campaign must be an object"
        )
    normalized_campaign = {
        key: _required_int(campaign, key)
        for key in (
            "overlap_started_at_ms",
            "combined_started_at_ms",
            "two_strike_started_at_ms",
            "momentum_started_at_ms",
            "breakeven_started_at_ms",
        )
    }
    if normalized_campaign["overlap_started_at_ms"] != max(
        normalized_campaign["combined_started_at_ms"],
        normalized_campaign["two_strike_started_at_ms"],
        normalized_campaign["momentum_started_at_ms"],
        normalized_campaign["breakeven_started_at_ms"],
    ):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "ledger campaign start does not reconcile"
        )
    raw_rows = raw.get("rows")
    if not isinstance(raw_rows, (list, tuple)):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack ledger rows must be a list"
        )
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise ProspectiveFullStackMatchedTradeLedgerError(
                "full-stack ledger row must be an object"
            )
        trade_id = _required_string(raw_row, "trade_id")
        if trade_id in seen:
            raise ProspectiveFullStackMatchedTradeLedgerError(
                "full-stack ledger contains duplicate trade ids"
            )
        seen.add(trade_id)
        rows.append(dict(raw_row))
    row_tuple = tuple(rows)
    if raw.get("row_count") != len(row_tuple):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack ledger row count mismatch"
        )
    if raw.get("rows_sha256") != _rows_sha256(row_tuple):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack ledger row digest mismatch"
        )
    pending = raw.get("pending_trade_count")
    if isinstance(pending, bool) or not isinstance(pending, int) or pending < 0:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "pending trade count is invalid"
        )
    if raw.get("summary") != _summary(
        row_tuple,
        pending_trade_count=pending,
    ):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack ledger summary does not reconcile"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack ledger source history must be a list"
        )
    expected = _sha256_text(_canonical_json(_digest_payload(raw)))
    if raw.get("ledger_sha256") != expected:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack ledger digest mismatch"
        )
    return {**raw, "rows": row_tuple}


def load_full_stack_matched_trade_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveFullStackMatchedTradeLedgerError(
            "full-stack matched-trade ledger file is invalid"
        ) from exc
    return validate_full_stack_matched_trade_ledger(raw)


def update_full_stack_matched_trade_ledger(
    trades: Sequence[TradeJournalEntry],
    full_stack_summary: dict[str, object],
    *,
    previous: dict[str, object] | None,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_artifact_name: str,
    source_artifact_digest: str,
) -> dict[str, object]:
    if source_paper_run_id <= 0 or source_paper_run_attempt <= 0:
        raise ValueError("source paper run identity must be positive")
    if not source_artifact_name.strip():
        raise ValueError("source artifact name must not be empty")
    if not source_artifact_digest.startswith("sha256:"):
        raise ValueError("source artifact digest must be sha256")

    _validate_authority(full_stack_summary)
    campaign = _campaign(full_stack_summary)
    current_rows, pending = _terminal_rows(
        trades,
        full_stack_summary,
        overlap_started_at_ms=campaign["overlap_started_at_ms"],
    )

    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None
    if previous is not None:
        validated = validate_full_stack_matched_trade_ledger(previous)
        if validated.get("campaign") != campaign:
            raise ProspectiveFullStackMatchedTradeLedgerError(
                "full-stack campaign identity drift"
            )
        raw_history = validated.get("source_history")
        if not isinstance(raw_history, list):
            raise ProspectiveFullStackMatchedTradeLedgerError(
                "previous source history is invalid"
            )
        for item in raw_history:
            if not isinstance(item, dict):
                raise ProspectiveFullStackMatchedTradeLedgerError(
                    "previous source history entry is invalid"
                )
            if (
                item.get("paper_run_id") == source_paper_run_id
                and item.get("paper_run_attempt")
                == source_paper_run_attempt
            ):
                if (
                    item.get("artifact_name") != source_artifact_name
                    or item.get("artifact_digest")
                    != source_artifact_digest
                ):
                    raise ProspectiveFullStackMatchedTradeLedgerError(
                        "duplicate source artifact identity drift"
                    )
                return validated
        previous_rows = cast(
            tuple[dict[str, object], ...],
            validated["rows"],
        )
        history = list(raw_history)
        prior_ledger_sha256 = cast(
            str,
            validated["ledger_sha256"],
        )
        current_by_id = {
            cast(str, row["trade_id"]): row
            for row in current_rows
        }
        for old in previous_rows:
            trade_id = cast(str, old["trade_id"])
            current = current_by_id.get(trade_id)
            if current is None:
                raise ProspectiveFullStackMatchedTradeLedgerError(
                    "previous terminal full-stack row disappeared"
                )
            if current != old:
                raise ProspectiveFullStackMatchedTradeLedgerError(
                    "previous terminal full-stack row changed"
                )

    old_ids = {
        cast(str, row["trade_id"]) for row in previous_rows
    }
    new_rows = tuple(
        row
        for row in current_rows
        if cast(str, row["trade_id"]) not in old_ids
    )
    history.append(
        {
            "paper_run_id": source_paper_run_id,
            "paper_run_attempt": source_paper_run_attempt,
            "artifact_name": source_artifact_name,
            "artifact_digest": source_artifact_digest,
            "row_count": len(current_rows),
            "new_row_count": len(new_rows),
            "pending_trade_count": pending,
            "rows_sha256": _rows_sha256(current_rows),
        }
    )
    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_readiness_gate": False,
        "claim_scope": "matched_trade_contribution_only",
        "portfolio_counterfactual": False,
        "replacement_trades_modeled": False,
        "campaign": campaign,
        "prior_ledger_sha256": prior_ledger_sha256,
        "row_count": len(current_rows),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(new_rows),
        "pending_trade_count": pending,
        "rows_sha256": _rows_sha256(current_rows),
        "source_history": history,
        "summary": _summary(
            current_rows,
            pending_trade_count=pending,
        ),
        "rows": current_rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_digest_payload(payload))
    )
    return payload
