from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from cocomelon.domain.execution import ExecutionAttempt, PaperFill, PaperOrderPlan
from cocomelon.domain.market import MarketId
from cocomelon.execution.accounting import (
    PaperAccountState,
    PaperPosition,
    PositionSide,
    RollingPeakCandidate,
)
from cocomelon.execution.funding import FundingAccrual

SCHEMA_VERSION = 1


def _market_from_canonical(value: str) -> MarketId:
    if ":" in value:
        dex = value.split(":", 1)[0]
        return MarketId.from_wire_name(dex, value)
    return MarketId.from_wire_name("", value)


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _position_payload(position: PaperPosition) -> dict[str, object]:
    return {
        "market": position.market.canonical,
        "side": position.side.value,
        "quantity": str(position.quantity),
        "average_entry_price": str(position.average_entry_price),
        "stop_price": str(position.stop_price),
        "opening_plan_id": position.opening_plan_id,
        "opened_at_ms": position.opened_at_ms,
        "updated_at_ms": position.updated_at_ms,
        "initial_risk_decision_id": position.initial_risk_decision_id,
        "correlation_bucket": position.correlation_bucket,
        "cost_buffer_fraction": str(position.cost_buffer_fraction),
        "planned_risk": str(position.planned_risk),
        "cumulative_realized_gross_pnl": str(position.cumulative_realized_gross_pnl),
        "cumulative_fees": str(position.cumulative_fees),
        "cumulative_funding": str(position.cumulative_funding),
        "venue_max_leverage": str(position.venue_max_leverage),
        "latest_mark": None if position.latest_mark is None else str(position.latest_mark),
    }


def _position_from_payload(payload: dict[str, Any]) -> PaperPosition:
    latest_mark = payload.get("latest_mark")
    return PaperPosition(
        market=_market_from_canonical(str(payload["market"])),
        side=PositionSide(str(payload["side"])),
        quantity=Decimal(str(payload["quantity"])),
        average_entry_price=Decimal(str(payload["average_entry_price"])),
        stop_price=Decimal(str(payload["stop_price"])),
        opening_plan_id=str(payload["opening_plan_id"]),
        opened_at_ms=int(payload["opened_at_ms"]),
        updated_at_ms=int(payload["updated_at_ms"]),
        initial_risk_decision_id=str(payload["initial_risk_decision_id"]),
        correlation_bucket=str(payload["correlation_bucket"]),
        cost_buffer_fraction=Decimal(str(payload["cost_buffer_fraction"])),
        planned_risk=Decimal(str(payload["planned_risk"])),
        cumulative_realized_gross_pnl=Decimal(
            str(payload["cumulative_realized_gross_pnl"])
        ),
        cumulative_fees=Decimal(str(payload["cumulative_fees"])),
        cumulative_funding=Decimal(str(payload["cumulative_funding"])),
        venue_max_leverage=Decimal(str(payload["venue_max_leverage"])),
        latest_mark=None if latest_mark is None else Decimal(str(latest_mark)),
    )


def _account_payload(account: PaperAccountState) -> dict[str, object]:
    return {
        "starting_cash": str(account.starting_cash),
        "cash": str(account.cash),
        "positions": [_position_payload(position) for position in account.positions],
        "realized_gross_pnl": str(account.realized_gross_pnl),
        "cumulative_fees": str(account.cumulative_fees),
        "cumulative_funding": str(account.cumulative_funding),
        "unrealized_pnl": str(account.unrealized_pnl),
        "equity": str(account.equity),
        "gross_open_notional": str(account.gross_open_notional),
        "updated_at_ms": account.updated_at_ms,
        "reserved_margin": str(account.reserved_margin),
        "available_margin": str(account.available_margin),
        "daily_realized_pnl": str(account.daily_realized_pnl),
        "day_start_equity": str(account.day_start_equity),
        "day_start_ms": account.day_start_ms,
        "rolling_peak_candidates": [
            {"timestamp_ms": point.timestamp_ms, "equity": str(point.equity)}
            for point in account.rolling_peak_candidates
        ],
        "consecutive_losses": account.consecutive_losses,
        "last_closed_trade_ms": account.last_closed_trade_ms,
    }


def _account_from_payload(payload: dict[str, Any]) -> PaperAccountState:
    return PaperAccountState(
        starting_cash=Decimal(str(payload["starting_cash"])),
        cash=Decimal(str(payload["cash"])),
        positions=tuple(
            _position_from_payload(position) for position in payload["positions"]
        ),
        realized_gross_pnl=Decimal(str(payload["realized_gross_pnl"])),
        cumulative_fees=Decimal(str(payload["cumulative_fees"])),
        cumulative_funding=Decimal(str(payload["cumulative_funding"])),
        unrealized_pnl=Decimal(str(payload["unrealized_pnl"])),
        equity=Decimal(str(payload["equity"])),
        gross_open_notional=Decimal(str(payload["gross_open_notional"])),
        updated_at_ms=int(payload["updated_at_ms"]),
        reserved_margin=Decimal(str(payload["reserved_margin"])),
        available_margin=Decimal(str(payload["available_margin"])),
        daily_realized_pnl=Decimal(str(payload["daily_realized_pnl"])),
        day_start_equity=Decimal(str(payload["day_start_equity"])),
        day_start_ms=int(payload["day_start_ms"]),
        rolling_peak_candidates=tuple(
            RollingPeakCandidate(
                timestamp_ms=int(point["timestamp_ms"]),
                equity=Decimal(str(point["equity"])),
            )
            for point in payload["rolling_peak_candidates"]
        ),
        consecutive_losses=int(payload["consecutive_losses"]),
        last_closed_trade_ms=(
            None
            if payload["last_closed_trade_ms"] is None
            else int(payload["last_closed_trade_ms"])
        ),
    )


def _plan_payload(plan: PaperOrderPlan) -> dict[str, object]:
    return {
        "risk_decision_id": plan.risk_decision_id,
        "strategy_decision_id": plan.strategy_decision_id,
        "market": plan.market.canonical,
        "side": plan.side.value,
        "requested_quantity": str(plan.requested_quantity),
        "order_type": plan.order_type.value,
        "reduce_only": plan.reduce_only,
        "execution_reference_price": str(plan.execution_reference_price),
        "max_slippage_bps": str(plan.max_slippage_bps),
        "stop_price": None if plan.stop_price is None else str(plan.stop_price),
        "approved_notional_ceiling": str(plan.approved_notional_ceiling),
        "created_at_ms": plan.created_at_ms,
        "earliest_execution_ms": plan.earliest_execution_ms,
        "execution_config_version": plan.execution_config_version,
        "instrument_metadata_received_at_ms": plan.instrument_metadata_received_at_ms,
        "approved_risk_amount_ceiling": (
            None
            if plan.approved_risk_amount_ceiling is None
            else str(plan.approved_risk_amount_ceiling)
        ),
        "stop_distance_fraction": (
            None
            if plan.stop_distance_fraction is None
            else str(plan.stop_distance_fraction)
        ),
        "effective_loss_fraction": (
            None
            if plan.effective_loss_fraction is None
            else str(plan.effective_loss_fraction)
        ),
    }


def _attempt_payload(attempt: ExecutionAttempt) -> dict[str, object]:
    return {
        "plan_id": attempt.plan_id,
        "source_event_key": attempt.source_event_key,
        "requested_quantity": str(attempt.requested_quantity),
        "filled_quantity": str(attempt.filled_quantity),
        "average_fill_price": (
            None if attempt.average_fill_price is None else str(attempt.average_fill_price)
        ),
        "gross_fill_notional": str(attempt.gross_fill_notional),
        "fee": str(attempt.fee),
        "unfilled_quantity": str(attempt.unfilled_quantity),
        "result": attempt.result.value,
        "reason_codes": attempt.reason_codes,
        "snapshot_exchange_ms": attempt.snapshot_exchange_ms,
        "snapshot_received_ms": attempt.snapshot_received_ms,
        "attempt_timestamp_ms": attempt.attempt_timestamp_ms,
    }


def _fill_payload(fill: PaperFill) -> dict[str, object]:
    return {
        "plan_id": fill.plan_id,
        "attempt_id": fill.attempt_id,
        "market": fill.market.canonical,
        "side": fill.side.value,
        "price": str(fill.price),
        "quantity": str(fill.quantity),
        "notional": str(fill.notional),
        "taker_fee": str(fill.taker_fee),
        "source_event_key": fill.source_event_key,
        "timestamp_ms": fill.timestamp_ms,
    }


def _funding_payload(accrual: FundingAccrual) -> dict[str, object]:
    return {
        "market": accrual.market.canonical,
        "boundary_ms": accrual.boundary_ms,
        "position_id": accrual.position_id,
        "signed_quantity": str(accrual.signed_quantity),
        "oracle_price": str(accrual.oracle_price),
        "funding_rate": str(accrual.funding_rate),
        "cash_delta": str(accrual.cash_delta),
        "oracle_event_key": accrual.oracle_event_key,
        "funding_source": accrual.funding_source,
        "funding_received_at_ms": accrual.funding_received_at_ms,
    }


@dataclass(frozen=True, slots=True)
class ReconciledPaperState:
    account: PaperAccountState | None
    healthy: bool
    reason_codes: tuple[str, ...]


class PaperExecutionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_order_plans (
                    plan_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_execution_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_fills (
                    fill_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_positions (
                    market TEXT PRIMARY KEY,
                    position_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_position_events (
                    event_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_funding_events (
                    accrual_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    boundary_ms INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(market, boundary_ms, position_id)
                );
                CREATE TABLE IF NOT EXISTS paper_account_state (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    state_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_rolling_peak_candidates (
                    ordinal INTEGER PRIMARY KEY,
                    timestamp_ms INTEGER NOT NULL,
                    equity TEXT NOT NULL
                );
                """.replace(
                    "boundary_ms INTEGER NOT NULL,\n                    payload_json",
                    "boundary_ms INTEGER NOT NULL,\n                    position_id TEXT NOT NULL,\n                    payload_json",
                )
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO paper_meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def close(self) -> None:
        self._conn.close()

    def raw_connection(self) -> sqlite3.Connection:
        return self._conn

    def _put_immutable(
        self,
        table: str,
        id_column: str,
        identifier: str,
        payload_json: str,
        *,
        extra_columns: tuple[str, ...] = (),
        extra_values: tuple[object, ...] = (),
    ) -> None:
        row = self._conn.execute(
            f"SELECT payload_json FROM {table} WHERE {id_column} = ?",
            (identifier,),
        ).fetchone()
        if row is not None:
            if row[0] != payload_json:
                raise ValueError(f"immutable payload mismatch for {table}:{identifier}")
            return
        columns = (id_column, *extra_columns, "payload_json")
        placeholders = ",".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders})",
            (identifier, *extra_values, payload_json),
        )

    def persist_plan(self, plan: PaperOrderPlan) -> None:
        payload = _canonical_json(_plan_payload(plan))
        with self._conn:
            self._put_immutable(
                "paper_order_plans",
                "plan_id",
                plan.plan_id,
                payload,
            )

    def _write_materialized_account(self, account: PaperAccountState) -> None:
        account_json = _canonical_json(_account_payload(account))
        existing = self._conn.execute(
            "SELECT state_id, payload_json FROM paper_account_state WHERE singleton_id = 1"
        ).fetchone()
        if existing is not None and existing[0] == account.state_id and existing[1] != account_json:
            raise ValueError("immutable payload mismatch for paper account state")
        self._conn.execute("DELETE FROM paper_positions")
        for position in account.positions:
            payload = _canonical_json(_position_payload(position))
            self._conn.execute(
                "INSERT INTO paper_positions(market, position_id, payload_json) VALUES (?, ?, ?)",
                (position.market.canonical, position.position_id, payload),
            )
            event_id = f"{account.state_id}:{position.position_id}"
            self._put_immutable(
                "paper_position_events",
                "event_id",
                event_id,
                payload,
                extra_columns=("market",),
                extra_values=(position.market.canonical,),
            )
        self._conn.execute("DELETE FROM paper_rolling_peak_candidates")
        self._conn.executemany(
            "INSERT INTO paper_rolling_peak_candidates(ordinal, timestamp_ms, equity) "
            "VALUES (?, ?, ?)",
            (
                (index, point.timestamp_ms, str(point.equity))
                for index, point in enumerate(account.rolling_peak_candidates)
            ),
        )
        self._conn.execute(
            "INSERT INTO paper_account_state(singleton_id, state_id, payload_json) "
            "VALUES (1, ?, ?) ON CONFLICT(singleton_id) DO UPDATE SET "
            "state_id=excluded.state_id, payload_json=excluded.payload_json",
            (account.state_id, account_json),
        )

    def persist_execution(
        self,
        attempt: ExecutionAttempt,
        fills: tuple[PaperFill, ...],
        account: PaperAccountState,
    ) -> None:
        if any(fill.plan_id != attempt.plan_id for fill in fills):
            raise ValueError("fill plan does not match execution attempt")
        attempt_json = _canonical_json(_attempt_payload(attempt))
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._put_immutable(
                "paper_execution_attempts",
                "attempt_id",
                attempt.attempt_id,
                attempt_json,
                extra_columns=("plan_id",),
                extra_values=(attempt.plan_id,),
            )
            for fill in fills:
                self._put_immutable(
                    "paper_fills",
                    "fill_id",
                    fill.fill_id,
                    _canonical_json(_fill_payload(fill)),
                    extra_columns=("attempt_id", "plan_id"),
                    extra_values=(fill.attempt_id, fill.plan_id),
                )
            self._write_materialized_account(account)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def persist_funding(
        self,
        accrual: FundingAccrual,
        account: PaperAccountState,
    ) -> None:
        payload = _canonical_json(_funding_payload(accrual))
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._put_immutable(
                "paper_funding_events",
                "accrual_id",
                accrual.accrual_id,
                payload,
                extra_columns=("market", "boundary_ms", "position_id"),
                extra_values=(
                    accrual.market.canonical,
                    accrual.boundary_ms,
                    accrual.position_id,
                ),
            )
            self._write_materialized_account(account)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def load_and_reconcile(self) -> ReconciledPaperState:
        row = self._conn.execute(
            "SELECT state_id, payload_json FROM paper_account_state WHERE singleton_id = 1"
        ).fetchone()
        if row is None:
            return ReconciledPaperState(None, True, ())
        try:
            payload = json.loads(row[1])
            if not isinstance(payload, dict):
                raise ValueError("account payload is not an object")
            account = _account_from_payload(payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return ReconciledPaperState(None, False, ("ACCOUNT_STATE_UNREADABLE",))
        if account.state_id != row[0]:
            return ReconciledPaperState(
                account,
                False,
                ("ACCOUNT_STATE_ID_MISMATCH",),
            )

        materialized_rows = self._conn.execute(
            "SELECT market, position_id, payload_json FROM paper_positions ORDER BY market"
        ).fetchall()
        expected = tuple(
            (
                position.market.canonical,
                position.position_id,
                _canonical_json(_position_payload(position)),
            )
            for position in account.positions
        )
        actual = tuple((str(row[0]), str(row[1]), str(row[2])) for row in materialized_rows)
        if actual != expected:
            return ReconciledPaperState(
                account,
                False,
                ("MATERIALIZED_POSITION_MISMATCH",),
            )

        peak_rows = self._conn.execute(
            "SELECT timestamp_ms, equity FROM paper_rolling_peak_candidates ORDER BY ordinal"
        ).fetchall()
        expected_peaks = tuple(
            (point.timestamp_ms, str(point.equity))
            for point in account.rolling_peak_candidates
        )
        actual_peaks = tuple((int(row[0]), str(row[1])) for row in peak_rows)
        if actual_peaks != expected_peaks:
            return ReconciledPaperState(
                account,
                False,
                ("ROLLING_PEAK_STATE_MISMATCH",),
            )
        return ReconciledPaperState(account, True, ())

    def table_counts(self) -> dict[str, int]:
        tables = (
            "paper_meta",
            "paper_order_plans",
            "paper_execution_attempts",
            "paper_fills",
            "paper_positions",
            "paper_position_events",
            "paper_funding_events",
            "paper_account_state",
            "paper_rolling_peak_candidates",
        )
        return {
            table: int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
