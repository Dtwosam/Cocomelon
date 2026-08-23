from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

from cocomelon.domain.journal import JournalEvent, JournalEventType, TradeSummary
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction


class JournalConflictError(RuntimeError):
    pass


class JournalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> JournalStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS journal_events (
                journal_event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                occurred_at_ms INTEGER NOT NULL,
                schema_version INTEGER NOT NULL,
                code_version TEXT NOT NULL,
                config_snapshot_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                decision_id TEXT,
                market_dex TEXT,
                market_coin TEXT
            );

            CREATE INDEX IF NOT EXISTS journal_events_decision_idx
            ON journal_events(decision_id, occurred_at_ms, journal_event_id);

            CREATE TABLE IF NOT EXISTS trade_summaries (
                trade_id TEXT PRIMARY KEY,
                decision_id TEXT NOT NULL,
                risk_decision_id TEXT NOT NULL,
                opening_plan_id TEXT NOT NULL,
                replay_run_id TEXT NOT NULL,
                market_dex TEXT NOT NULL,
                market_coin TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_timestamp_ms INTEGER NOT NULL,
                exit_timestamp_ms INTEGER NOT NULL,
                entry_price TEXT NOT NULL,
                exit_price TEXT NOT NULL,
                quantity TEXT NOT NULL,
                initial_stop_price TEXT NOT NULL,
                approved_risk_amount TEXT NOT NULL,
                maximum_actual_notional TEXT NOT NULL,
                gross_pnl TEXT NOT NULL,
                fees TEXT NOT NULL,
                funding TEXT NOT NULL,
                entry_slippage TEXT NOT NULL,
                exit_slippage TEXT NOT NULL,
                net_pnl TEXT NOT NULL,
                mfe_pnl TEXT NOT NULL,
                mae_pnl TEXT NOT NULL,
                exit_reason TEXT NOT NULL,
                reason_trace_json TEXT NOT NULL,
                equity_before TEXT NOT NULL,
                equity_after TEXT NOT NULL
            );
            """
        )
        self._connection.commit()

    def append_event(self, event: JournalEvent) -> None:
        with self._connection:
            self._append_event_in_transaction(event)

    def _append_event_in_transaction(self, event: JournalEvent) -> None:
        existing = self._connection.execute(
            "SELECT * FROM journal_events WHERE journal_event_id = ?",
            (event.journal_event_id,),
        ).fetchone()
        if existing is not None:
            if self._event_from_row(existing) != event:
                raise JournalConflictError(
                    f"journal_event_id conflict for {event.journal_event_id}"
                )
            return

        self._connection.execute(
            """
            INSERT INTO journal_events (
                journal_event_id, event_type, occurred_at_ms, schema_version,
                code_version, config_snapshot_id, payload_json, payload_sha256,
                decision_id, market_dex, market_coin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.journal_event_id,
                event.event_type.value,
                event.occurred_at_ms,
                event.schema_version,
                event.code_version,
                event.config_snapshot_id,
                event.payload_json,
                event.payload_sha256,
                event.decision_id,
                None if event.market is None else event.market.dex,
                None if event.market is None else event.market.coin,
            ),
        )

    def load_events(self, *, decision_id: str | None = None) -> tuple[JournalEvent, ...]:
        if decision_id is None:
            rows = self._connection.execute(
                "SELECT * FROM journal_events ORDER BY occurred_at_ms, journal_event_id"
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM journal_events
                WHERE decision_id = ?
                ORDER BY occurred_at_ms, journal_event_id
                """,
                (decision_id,),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def upsert_trade_summary(self, summary: TradeSummary) -> None:
        with self._connection:
            self._upsert_trade_summary_in_transaction(summary)

    def _upsert_trade_summary_in_transaction(self, summary: TradeSummary) -> None:
        existing = self._connection.execute(
            "SELECT * FROM trade_summaries WHERE trade_id = ?",
            (summary.trade_id,),
        ).fetchone()
        if existing is not None:
            if self._summary_from_row(existing) != summary:
                raise JournalConflictError(f"trade_id conflict for {summary.trade_id}")
            return

        self._connection.execute(
            """
            INSERT INTO trade_summaries (
                trade_id, decision_id, risk_decision_id, opening_plan_id, replay_run_id,
                market_dex, market_coin, direction, entry_timestamp_ms, exit_timestamp_ms,
                entry_price, exit_price, quantity, initial_stop_price, approved_risk_amount,
                maximum_actual_notional, gross_pnl, fees, funding, entry_slippage,
                exit_slippage, net_pnl, mfe_pnl, mae_pnl, exit_reason, reason_trace_json,
                equity_before, equity_after
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                summary.trade_id,
                summary.decision_id,
                summary.risk_decision_id,
                summary.opening_plan_id,
                summary.replay_run_id,
                summary.market.dex,
                summary.market.coin,
                summary.direction.value,
                summary.entry_timestamp_ms,
                summary.exit_timestamp_ms,
                str(summary.entry_price),
                str(summary.exit_price),
                str(summary.quantity),
                str(summary.initial_stop_price),
                str(summary.approved_risk_amount),
                str(summary.maximum_actual_notional),
                str(summary.gross_pnl),
                str(summary.fees),
                str(summary.funding),
                str(summary.entry_slippage),
                str(summary.exit_slippage),
                str(summary.net_pnl),
                str(summary.mfe_pnl),
                str(summary.mae_pnl),
                summary.exit_reason,
                json.dumps(summary.reason_trace, separators=(",", ":")),
                str(summary.equity_before),
                str(summary.equity_after),
            ),
        )

    def load_trade_summary(self, trade_id: str) -> TradeSummary | None:
        row = self._connection.execute(
            "SELECT * FROM trade_summaries WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
        return None if row is None else self._summary_from_row(row)

    def commit_trade_close(
        self,
        event: JournalEvent,
        summary: TradeSummary,
        *,
        after_event_write: Callable[[], None] | None = None,
    ) -> None:
        try:
            self._connection.execute("BEGIN")
            self._append_event_in_transaction(event)
            if after_event_write is not None:
                after_event_write()
            self._upsert_trade_summary_in_transaction(summary)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    @staticmethod
    def _event_from_row(row: tuple[object, ...]) -> JournalEvent:
        (
            journal_event_id,
            event_type,
            occurred_at_ms,
            schema_version,
            code_version,
            config_snapshot_id,
            payload_json,
            payload_sha256,
            decision_id,
            market_dex,
            market_coin,
        ) = row
        market = None
        if market_coin is not None:
            assert isinstance(market_dex, str)
            assert isinstance(market_coin, str)
            market = MarketId(dex=market_dex, coin=market_coin)
        return JournalEvent(
            journal_event_id=str(journal_event_id),
            event_type=JournalEventType(str(event_type)),
            occurred_at_ms=int(str(occurred_at_ms)),
            schema_version=int(str(schema_version)),
            code_version=str(code_version),
            config_snapshot_id=str(config_snapshot_id),
            payload_json=str(payload_json),
            payload_sha256=str(payload_sha256),
            decision_id=None if decision_id is None else str(decision_id),
            market=market,
        )

    @staticmethod
    def _summary_from_row(row: tuple[object, ...]) -> TradeSummary:
        from decimal import Decimal

        (
            trade_id,
            decision_id,
            risk_decision_id,
            opening_plan_id,
            replay_run_id,
            market_dex,
            market_coin,
            direction,
            entry_timestamp_ms,
            exit_timestamp_ms,
            entry_price,
            exit_price,
            quantity,
            initial_stop_price,
            approved_risk_amount,
            maximum_actual_notional,
            gross_pnl,
            fees,
            funding,
            entry_slippage,
            exit_slippage,
            net_pnl,
            mfe_pnl,
            mae_pnl,
            exit_reason,
            reason_trace_json,
            equity_before,
            equity_after,
        ) = row
        assert isinstance(market_dex, str)
        assert isinstance(market_coin, str)
        reasons_raw = json.loads(str(reason_trace_json))
        if not isinstance(reasons_raw, list) or not all(
            isinstance(item, str) for item in reasons_raw
        ):
            raise ValueError("stored reason_trace_json is invalid")
        return TradeSummary(
            trade_id=str(trade_id),
            decision_id=str(decision_id),
            risk_decision_id=str(risk_decision_id),
            opening_plan_id=str(opening_plan_id),
            replay_run_id=str(replay_run_id),
            market=MarketId(dex=market_dex, coin=market_coin),
            direction=Direction(str(direction)),
            entry_timestamp_ms=int(str(entry_timestamp_ms)),
            exit_timestamp_ms=int(str(exit_timestamp_ms)),
            entry_price=Decimal(str(entry_price)),
            exit_price=Decimal(str(exit_price)),
            quantity=Decimal(str(quantity)),
            initial_stop_price=Decimal(str(initial_stop_price)),
            approved_risk_amount=Decimal(str(approved_risk_amount)),
            maximum_actual_notional=Decimal(str(maximum_actual_notional)),
            gross_pnl=Decimal(str(gross_pnl)),
            fees=Decimal(str(fees)),
            funding=Decimal(str(funding)),
            entry_slippage=Decimal(str(entry_slippage)),
            exit_slippage=Decimal(str(exit_slippage)),
            net_pnl=Decimal(str(net_pnl)),
            mfe_pnl=Decimal(str(mfe_pnl)),
            mae_pnl=Decimal(str(mae_pnl)),
            exit_reason=str(exit_reason),
            reason_trace=tuple(reasons_raw),
            equity_before=Decimal(str(equity_before)),
            equity_after=Decimal(str(equity_after)),
        )
