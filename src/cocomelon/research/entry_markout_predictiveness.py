from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathStore,
)
from cocomelon.research.entry_markout import (
    ENTRY_MARKOUT_HORIZONS_MS,
    MAX_ENTRY_MARKOUT_OBSERVATION_LAG_MS,
)

ZERO: Final = Decimal("0")
MIN_OBSERVATIONS_PER_HORIZON: Final = 30
MIN_FAVORABLE_PER_HORIZON: Final = 10
MIN_ADVERSE_PER_HORIZON: Final = 10


class EntryMarkoutPredictivenessError(RuntimeError):
    pass


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EntryMarkoutPredictivenessError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise EntryMarkoutPredictivenessError(
            f"{field} must be finite"
        )
    return resolved


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EntryMarkoutPredictivenessError(
            f"{field} must be an integer"
        )
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EntryMarkoutPredictivenessError(
            f"{field} must be a non-empty string"
        )
    return value


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise EntryMarkoutPredictivenessError(
            "duplicate journal trade id"
        )
    return by_id


def _verify_path_identity(
    raw: Mapping[str, object],
    trade: TradeJournalEntry,
) -> None:
    expected = {
        "trade_id": trade.trade_id,
        "market": trade.market.canonical,
        "direction": trade.direction.value,
        "opened_at_ms": trade.opened_at_ms,
        "closed_at_ms": trade.closed_at_ms,
        "entry_price": str(trade.entry_price),
        "initial_risk_amount": str(trade.initial_risk_amount),
        "filled_quantity": str(trade.filled_quantity),
    }
    actual = {
        "trade_id": raw.get("trade_id"),
        "market": raw.get("market"),
        "direction": raw.get("direction"),
        "opened_at_ms": raw.get("opened_at_ms"),
        "closed_at_ms": raw.get("closed_at_ms"),
        "entry_price": raw.get("entry_price"),
        "initial_risk_amount": raw.get("initial_risk_amount"),
        "filled_quantity": raw.get("filled_quantity"),
    }
    if actual != expected:
        raise EntryMarkoutPredictivenessError(
            "markout predictiveness path identity mismatch"
        )


def _marks(
    raw: Mapping[str, object],
) -> tuple[tuple[int, Decimal], ...]:
    value = raw.get("marks")
    if not isinstance(value, list):
        raise EntryMarkoutPredictivenessError(
            "trade path marks must be an array"
        )
    output: list[tuple[int, Decimal]] = []
    previous: int | None = None
    for item in value:
        if not isinstance(item, dict):
            raise EntryMarkoutPredictivenessError(
                "trade path mark must be an object"
            )
        timestamp_ms = _integer(
            item.get("available_at_ms"),
            "available_at_ms",
        )
        mark_px = _decimal(item.get("mark_px"), "mark_px")
        if mark_px <= ZERO:
            raise EntryMarkoutPredictivenessError(
                "trade path mark_px must be positive"
            )
        if previous is not None and timestamp_ms < previous:
            raise EntryMarkoutPredictivenessError(
                "trade path marks must be ordered"
            )
        previous = timestamp_ms
        output.append((timestamp_ms, mark_px))
    return tuple(output)


def _markout_r(
    trade: TradeJournalEntry,
    *,
    horizon_ms: int,
    marks: tuple[tuple[int, Decimal], ...],
) -> Decimal | None:
    target_ms = trade.opened_at_ms + horizon_ms
    if trade.closed_at_ms < target_ms:
        return None
    chosen: tuple[int, Decimal] | None = None
    for timestamp_ms, mark_px in marks:
        if timestamp_ms >= target_ms:
            chosen = (timestamp_ms, mark_px)
            break
    if chosen is None:
        return None
    timestamp_ms, mark_px = chosen
    if timestamp_ms > trade.closed_at_ms:
        return None
    if (
        timestamp_ms - target_ms
        > MAX_ENTRY_MARKOUT_OBSERVATION_LAG_MS
    ):
        return None
    signed_move = (
        mark_px - trade.entry_price
        if trade.direction.value == "long"
        else trade.entry_price - mark_px
    )
    return (
        signed_move
        * trade.filled_quantity
        / trade.initial_risk_amount
    )


def _bucket(value: Decimal) -> str:
    if value > ZERO:
        return "favorable"
    if value < ZERO:
        return "adverse"
    return "flat"


def _group_summary(
    trades: Sequence[TradeJournalEntry],
) -> dict[str, object]:
    items = tuple(trades)
    count = len(items)
    net_pnl = sum((trade.net_pnl for trade in items), ZERO)
    final_r = sum((trade.net_r for trade in items), ZERO)
    return {
        "trades": count,
        "wins": sum(1 for trade in items if trade.net_pnl > ZERO),
        "losses": sum(1 for trade in items if trade.net_pnl < ZERO),
        "flat": sum(1 for trade in items if trade.net_pnl == ZERO),
        "win_rate": (
            None
            if count == 0
            else str(
                Decimal(
                    sum(
                        1
                        for trade in items
                        if trade.net_pnl > ZERO
                    )
                )
                / Decimal(count)
            )
        ),
        "net_pnl": str(net_pnl),
        "mean_final_net_r": (
            None if count == 0 else str(final_r / Decimal(count))
        ),
    }


def entry_markout_predictiveness(
    journal: JournalStore,
    path_store: ContinuousPaperTradePathStore,
) -> dict[str, object]:
    trades = _trade_map(journal)
    paths = path_store.iter_payloads()
    by_horizon: dict[int, dict[str, list[TradeJournalEntry]]] = {
        horizon: {
            "favorable": [],
            "adverse": [],
            "flat": [],
        }
        for horizon in ENTRY_MARKOUT_HORIZONS_MS
    }
    incomplete_paths = 0
    missing_journal_trade = 0
    censored_by_horizon = {
        horizon: 0 for horizon in ENTRY_MARKOUT_HORIZONS_MS
    }
    stale_or_missing_by_horizon = {
        horizon: 0 for horizon in ENTRY_MARKOUT_HORIZONS_MS
    }

    for raw in paths:
        trade_id = _string(raw.get("trade_id"), "trade_id")
        trade = trades.get(trade_id)
        if trade is None:
            missing_journal_trade += 1
            continue
        _verify_path_identity(raw, trade)
        if raw.get("path_complete") is not True:
            incomplete_paths += 1
            continue
        marks = _marks(raw)
        for horizon_ms in ENTRY_MARKOUT_HORIZONS_MS:
            target_ms = trade.opened_at_ms + horizon_ms
            if trade.closed_at_ms < target_ms:
                censored_by_horizon[horizon_ms] += 1
                continue
            markout_r = _markout_r(
                trade,
                horizon_ms=horizon_ms,
                marks=marks,
            )
            if markout_r is None:
                stale_or_missing_by_horizon[horizon_ms] += 1
                continue
            by_horizon[horizon_ms][_bucket(markout_r)].append(
                trade
            )

    horizon_payload: dict[str, dict[str, object]] = {}
    all_ready = True
    for horizon_ms in ENTRY_MARKOUT_HORIZONS_MS:
        groups = by_horizon[horizon_ms]
        favorable = tuple(groups["favorable"])
        adverse = tuple(groups["adverse"])
        flat = tuple(groups["flat"])
        total = len(favorable) + len(adverse) + len(flat)
        nonflat = len(favorable) + len(adverse)
        sign_correct = (
            sum(1 for trade in favorable if trade.net_pnl > ZERO)
            + sum(1 for trade in adverse if trade.net_pnl < ZERO)
        )
        missing_total = max(
            0,
            MIN_OBSERVATIONS_PER_HORIZON - total,
        )
        missing_favorable = max(
            0,
            MIN_FAVORABLE_PER_HORIZON - len(favorable),
        )
        missing_adverse = max(
            0,
            MIN_ADVERSE_PER_HORIZON - len(adverse),
        )
        ready = (
            missing_total == 0
            and missing_favorable == 0
            and missing_adverse == 0
        )
        all_ready = all_ready and ready
        horizon_payload[str(horizon_ms)] = {
            "observations": total,
            "nonflat_observations": nonflat,
            "sign_correct_final_outcomes": sign_correct,
            "sign_accuracy": (
                None
                if nonflat == 0
                else str(
                    Decimal(sign_correct)
                    / Decimal(nonflat)
                )
            ),
            "favorable": _group_summary(favorable),
            "adverse": _group_summary(adverse),
            "flat": _group_summary(flat),
            "censored_before_horizon": (
                censored_by_horizon[horizon_ms]
            ),
            "stale_or_missing_mark": (
                stale_or_missing_by_horizon[horizon_ms]
            ),
            "readiness": {
                "ready_for_review": ready,
                "min_observations": (
                    MIN_OBSERVATIONS_PER_HORIZON
                ),
                "min_favorable": MIN_FAVORABLE_PER_HORIZON,
                "min_adverse": MIN_ADVERSE_PER_HORIZON,
                "missing_observations": missing_total,
                "missing_favorable": missing_favorable,
                "missing_adverse": missing_adverse,
            },
        }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": (
            "early_markout_sign_vs_final_closed_trade_outcome"
        ),
        "complete_path_records": len(paths) - incomplete_paths,
        "incomplete_paths_skipped": incomplete_paths,
        "missing_journal_trade": missing_journal_trade,
        "max_observation_lag_ms": (
            MAX_ENTRY_MARKOUT_OBSERVATION_LAG_MS
        ),
        "all_horizons_ready_for_review": all_ready,
        "by_horizon_ms": horizon_payload,
    }
