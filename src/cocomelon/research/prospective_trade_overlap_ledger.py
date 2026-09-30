from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.prospective_prediction_ledger import (
    validate_prediction_ledger,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "cadence-prospective-actual-trade-overlap-ledger-v1"
ZERO: Final = Decimal("0")


class ProspectiveTradeOverlapLedgerError(RuntimeError):
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


def _decimal_string(value: object, *, field: str) -> str:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProspectiveTradeOverlapLedgerError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ProspectiveTradeOverlapLedgerError(
            f"{field} must be finite"
        )
    return str(resolved)


def _required_string(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveTradeOverlapLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveTradeOverlapLedgerError(
            f"{key} must be an integer"
        )
    return value


def _row_identity(
    row: dict[str, object],
) -> tuple[int, str, str, str]:
    return (
        cast(int, row["boundary_ms"]),
        cast(str, row["market"]),
        cast(str, row["direction"]),
        cast(str, row["decision_id"]),
    )


def _canonical_row(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveTradeOverlapLedgerError(
            "overlap row must be an object"
        )
    decision_id = _required_string(raw, "decision_id")
    market = _required_string(raw, "market")
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise ProspectiveTradeOverlapLedgerError(
            "direction must be long or short"
        )
    boundary_ms = _required_int(raw, "boundary_ms")
    opened_at_ms = _required_int(raw, "opened_at_ms")
    closed_at_ms = _required_int(raw, "closed_at_ms")
    if boundary_ms < 0 or opened_at_ms < boundary_ms:
        raise ProspectiveTradeOverlapLedgerError(
            "trade must open at or after cadence boundary"
        )
    if closed_at_ms < opened_at_ms:
        raise ProspectiveTradeOverlapLedgerError(
            "trade close cannot precede open"
        )
    admitted = raw.get("candidate_admitted")
    if not isinstance(admitted, bool):
        raise ProspectiveTradeOverlapLedgerError(
            "candidate_admitted must be boolean"
        )
    actual_net_pnl = Decimal(
        _decimal_string(raw.get("actual_net_pnl"), field="actual_net_pnl")
    )
    candidate_net_pnl = Decimal(
        _decimal_string(
            raw.get("candidate_matched_net_pnl"),
            field="candidate_matched_net_pnl",
        )
    )
    delta = Decimal(
        _decimal_string(
            raw.get("candidate_minus_actual_net_pnl"),
            field="candidate_minus_actual_net_pnl",
        )
    )
    expected_candidate = actual_net_pnl if admitted else ZERO
    if candidate_net_pnl != expected_candidate:
        raise ProspectiveTradeOverlapLedgerError(
            "candidate matched PnL does not match admission"
        )
    if delta != candidate_net_pnl - actual_net_pnl:
        raise ProspectiveTradeOverlapLedgerError(
            "candidate-minus-actual PnL does not reconcile"
        )
    outcome = _required_string(raw, "actual_outcome")
    expected_outcome = (
        "winner"
        if actual_net_pnl > ZERO
        else ("loser" if actual_net_pnl < ZERO else "flat")
    )
    if outcome != expected_outcome:
        raise ProspectiveTradeOverlapLedgerError(
            "actual_outcome does not match actual_net_pnl"
        )
    return {
        "decision_id": decision_id,
        "boundary_ms": boundary_ms,
        "market": market,
        "direction": direction,
        "prediction_net_return": _decimal_string(
            raw.get("prediction_net_return"),
            field="prediction_net_return",
        ),
        "candidate_admitted": admitted,
        "realized_1h_net_return": _decimal_string(
            raw.get("realized_1h_net_return"),
            field="realized_1h_net_return",
        ),
        "trade_id": _required_string(raw, "trade_id"),
        "opened_at_ms": opened_at_ms,
        "closed_at_ms": closed_at_ms,
        "actual_net_pnl": str(actual_net_pnl),
        "actual_net_r": _decimal_string(
            raw.get("actual_net_r"),
            field="actual_net_r",
        ),
        "actual_exit_reason": _required_string(
            raw,
            "actual_exit_reason",
        ),
        "actual_outcome": outcome,
        "candidate_matched_net_pnl": str(candidate_net_pnl),
        "candidate_minus_actual_net_pnl": str(delta),
    }


def _canonical_rows(raw: object) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProspectiveTradeOverlapLedgerError(
            "overlap rows must be a list"
        )
    rows = tuple(_canonical_row(item) for item in raw)
    identities = tuple(_row_identity(row) for row in rows)
    if len(identities) != len(set(identities)):
        raise ProspectiveTradeOverlapLedgerError(
            "duplicate overlap row identity"
        )
    trade_ids = tuple(cast(str, row["trade_id"]) for row in rows)
    if len(trade_ids) != len(set(trade_ids)):
        raise ProspectiveTradeOverlapLedgerError(
            "duplicate trade_id in overlap rows"
        )
    return tuple(sorted(rows, key=_row_identity))


def _rows_sha256(rows: tuple[dict[str, object], ...]) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _ledger_digest_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "ledger_sha256"
    }


def _summary(rows: tuple[dict[str, object], ...]) -> dict[str, object]:
    def subset(
        *,
        direction: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        if direction is None:
            return rows
        return tuple(
            row for row in rows if row["direction"] == direction
        )

    def stats(items: tuple[dict[str, object], ...]) -> dict[str, object]:
        actual = sum(
            (Decimal(cast(str, row["actual_net_pnl"])) for row in items),
            ZERO,
        )
        candidate = sum(
            (
                Decimal(cast(str, row["candidate_matched_net_pnl"]))
                for row in items
            ),
            ZERO,
        )
        blocked_losers = tuple(
            row
            for row in items
            if row["candidate_admitted"] is False
            and Decimal(cast(str, row["actual_net_pnl"])) < ZERO
        )
        blocked_winners = tuple(
            row
            for row in items
            if row["candidate_admitted"] is False
            and Decimal(cast(str, row["actual_net_pnl"])) > ZERO
        )
        admitted_losers = tuple(
            row
            for row in items
            if row["candidate_admitted"] is True
            and Decimal(cast(str, row["actual_net_pnl"])) < ZERO
        )
        admitted_winners = tuple(
            row
            for row in items
            if row["candidate_admitted"] is True
            and Decimal(cast(str, row["actual_net_pnl"])) > ZERO
        )
        avoided = -sum(
            (
                Decimal(cast(str, row["actual_net_pnl"]))
                for row in blocked_losers
            ),
            ZERO,
        )
        sacrificed = sum(
            (
                Decimal(cast(str, row["actual_net_pnl"]))
                for row in blocked_winners
            ),
            ZERO,
        )
        total_winner_pnl = sum(
            (
                Decimal(cast(str, row["actual_net_pnl"]))
                for row in items
                if Decimal(cast(str, row["actual_net_pnl"])) > ZERO
            ),
            ZERO,
        )
        total_loser_pnl_abs = -sum(
            (
                Decimal(cast(str, row["actual_net_pnl"]))
                for row in items
                if Decimal(cast(str, row["actual_net_pnl"])) < ZERO
            ),
            ZERO,
        )
        admitted_winner_pnl = sum(
            (
                Decimal(cast(str, row["actual_net_pnl"]))
                for row in admitted_winners
            ),
            ZERO,
        )
        admitted_loser_pnl_abs = -sum(
            (
                Decimal(cast(str, row["actual_net_pnl"]))
                for row in admitted_losers
            ),
            ZERO,
        )
        return {
            "matched_closed_trades": len(items),
            "candidate_admitted_trades": sum(
                row["candidate_admitted"] is True for row in items
            ),
            "candidate_blocked_trades": sum(
                row["candidate_admitted"] is False for row in items
            ),
            "admitted_winners": len(admitted_winners),
            "admitted_losers": len(admitted_losers),
            "blocked_winners": len(blocked_winners),
            "blocked_losers": len(blocked_losers),
            "actual_net_pnl_sum": str(actual),
            "candidate_matched_net_pnl_sum": str(candidate),
            "candidate_minus_actual_net_pnl_sum": str(
                candidate - actual
            ),
            "blocked_loser_pnl_avoided": str(avoided),
            "blocked_winner_pnl_sacrificed": str(sacrificed),
            "blocked_loss_minus_sacrificed_win": str(
                avoided - sacrificed
            ),
            "actual_winner_pnl_sum": str(total_winner_pnl),
            "actual_loser_pnl_abs_sum": str(total_loser_pnl_abs),
            "admitted_winner_pnl_retained": str(admitted_winner_pnl),
            "admitted_loser_pnl_abs_incurred": str(
                admitted_loser_pnl_abs
            ),
            "loss_avoidance_rate": (
                None
                if total_loser_pnl_abs == ZERO
                else str(avoided / total_loser_pnl_abs)
            ),
            "winner_retention_rate": (
                None
                if total_winner_pnl == ZERO
                else str(admitted_winner_pnl / total_winner_pnl)
            ),
            "trade_block_rate": (
                None
                if not items
                else str(
                    Decimal(len(blocked_losers) + len(blocked_winners))
                    / Decimal(len(items))
                )
            ),
        }

    return {
        "overall": stats(subset()),
        "by_direction": {
            "long": stats(subset(direction="long")),
            "short": stats(subset(direction="short")),
        },
    }


def _trade_map(
    trades: tuple[TradeJournalEntry, ...],
) -> dict[str, TradeJournalEntry]:
    result: dict[str, TradeJournalEntry] = {}
    for trade in trades:
        key = trade.strategy_decision_id
        if key in result:
            raise ProspectiveTradeOverlapLedgerError(
                "multiple closed trades share strategy_decision_id"
            )
        result[key] = trade
    return result


def _current_rows(
    prediction: dict[str, object],
    trades: tuple[TradeJournalEntry, ...],
) -> tuple[dict[str, object], ...]:
    trade_by_decision = _trade_map(trades)
    rows: list[dict[str, object]] = []
    prediction_rows = cast(
        tuple[dict[str, object], ...],
        prediction["rows"],
    )
    for prediction_row in prediction_rows:
        decision_id = cast(str, prediction_row["decision_id"])
        trade = trade_by_decision.get(decision_id)
        if trade is None:
            continue
        if trade.market.canonical != prediction_row["market"]:
            raise ProspectiveTradeOverlapLedgerError(
                "matched trade market does not match prediction row"
            )
        if trade.direction.value != prediction_row["direction"]:
            raise ProspectiveTradeOverlapLedgerError(
                "matched trade direction does not match prediction row"
            )
        boundary_ms = cast(int, prediction_row["boundary_ms"])
        if trade.opened_at_ms < boundary_ms:
            raise ProspectiveTradeOverlapLedgerError(
                "matched trade opened before cadence boundary"
            )
        actual = trade.net_pnl
        admitted = prediction_row["admitted"] is True
        candidate = actual if admitted else ZERO
        rows.append(
            {
                "decision_id": decision_id,
                "boundary_ms": boundary_ms,
                "market": trade.market.canonical,
                "direction": trade.direction.value,
                "prediction_net_return": prediction_row[
                    "prediction_net_return"
                ],
                "candidate_admitted": admitted,
                "realized_1h_net_return": prediction_row[
                    "realized_net_return"
                ],
                "trade_id": trade.trade_id,
                "opened_at_ms": trade.opened_at_ms,
                "closed_at_ms": trade.closed_at_ms,
                "actual_net_pnl": str(actual),
                "actual_net_r": str(trade.net_r),
                "actual_exit_reason": trade.exit_reason,
                "actual_outcome": (
                    "winner"
                    if actual > ZERO
                    else ("loser" if actual < ZERO else "flat")
                ),
                "candidate_matched_net_pnl": str(candidate),
                "candidate_minus_actual_net_pnl": str(
                    candidate - actual
                ),
            }
        )
    return _canonical_rows(rows)


def validate_trade_overlap_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveTradeOverlapLedgerError(
            "trade overlap ledger must be an object"
        )
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveTradeOverlapLedgerError(
            "trade overlap ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveTradeOverlapLedgerError(
            "trade overlap ledger kind is unsupported"
        )
    rows = _canonical_rows(raw.get("rows"))
    if raw.get("row_count") != len(rows):
        raise ProspectiveTradeOverlapLedgerError(
            "trade overlap row_count does not match rows"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveTradeOverlapLedgerError(
            "trade overlap rows digest mismatch"
        )
    if raw.get("summary") != _summary(rows):
        raise ProspectiveTradeOverlapLedgerError(
            "trade overlap summary does not reconcile"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveTradeOverlapLedgerError(
            "trade overlap source_history must be a list"
        )
    expected = _sha256_text(
        _canonical_json(_ledger_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected:
        raise ProspectiveTradeOverlapLedgerError(
            "trade overlap ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_trade_overlap_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveTradeOverlapLedgerError(
            "trade overlap ledger file is invalid"
        ) from exc
    return validate_trade_overlap_ledger(raw)


def update_trade_overlap_ledger(
    prediction_raw: object,
    trades: tuple[TradeJournalEntry, ...],
    *,
    previous: dict[str, object] | None,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_learning_artifact_name: str,
    source_learning_artifact_digest: str,
) -> dict[str, object]:
    if source_paper_run_id <= 0 or source_paper_run_attempt <= 0:
        raise ValueError("source paper run identity must be positive")
    if not source_learning_artifact_name.strip():
        raise ValueError("source learning artifact name must not be empty")
    if not source_learning_artifact_digest.startswith("sha256:"):
        raise ValueError(
            "source learning artifact digest must be sha256-prefixed"
        )
    prediction = validate_prediction_ledger(prediction_raw)
    current_rows = _current_rows(prediction, trades)

    metadata = {
        "model_family": prediction["model_family"],
        "prospective_start_ms": prediction["prospective_start_ms"],
        "cadence_ms": prediction["cadence_ms"],
        "horizon_ms": prediction["horizon_ms"],
        "frozen_training_rows": prediction["frozen_training_rows"],
        "frozen_training_rows_sha256": prediction[
            "frozen_training_rows_sha256"
        ],
    }

    previous_rows: tuple[dict[str, object], ...] = ()
    source_history: list[object] = []
    prior_ledger_sha256: str | None = None
    if previous is not None:
        validated = validate_trade_overlap_ledger(previous)
        for key, value in metadata.items():
            if validated.get(key) != value:
                raise ProspectiveTradeOverlapLedgerError(
                    f"trade overlap metadata drift: {key}"
                )
        previous_rows = cast(
            tuple[dict[str, object], ...],
            validated["rows"],
        )
        current_by_identity = {
            _row_identity(row): row for row in current_rows
        }
        for previous_row in previous_rows:
            current = current_by_identity.get(
                _row_identity(previous_row)
            )
            if current is None:
                raise ProspectiveTradeOverlapLedgerError(
                    "previous matched trade disappeared"
                )
            if current != previous_row:
                raise ProspectiveTradeOverlapLedgerError(
                    "previous matched trade changed"
                )
        raw_history = validated["source_history"]
        if not isinstance(raw_history, list):
            raise ProspectiveTradeOverlapLedgerError(
                "trade overlap source history is invalid"
            )
        source_history = list(raw_history)
        prior_ledger_sha256 = str(validated["ledger_sha256"])

    previous_identities = {
        _row_identity(row) for row in previous_rows
    }
    new_rows = tuple(
        row
        for row in current_rows
        if _row_identity(row) not in previous_identities
    )
    source_history.append(
        {
            "paper_run_id": source_paper_run_id,
            "paper_run_attempt": source_paper_run_attempt,
            "learning_artifact_name": source_learning_artifact_name,
            "learning_artifact_digest": source_learning_artifact_digest,
            "prediction_ledger_sha256": prediction["ledger_sha256"],
            "prediction_row_count": prediction["row_count"],
            "matched_row_count": len(current_rows),
            "new_matched_row_count": len(new_rows),
        }
    )
    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        **metadata,
        "prior_ledger_sha256": prior_ledger_sha256,
        "row_count": len(current_rows),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(new_rows),
        "rows_sha256": _rows_sha256(current_rows),
        "summary": _summary(current_rows),
        "source_history": source_history,
        "rows": current_rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_ledger_digest_payload(payload))
    )
    return payload


def update_trade_overlap_ledger_from_files(
    prediction_ledger_path: str | Path,
    journal_path: str | Path,
    *,
    previous_path: str | Path | None,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_learning_artifact_name: str,
    source_learning_artifact_digest: str,
) -> dict[str, object]:
    prediction_raw = json.loads(
        Path(prediction_ledger_path).read_text(encoding="utf-8")
    )
    previous = (
        None
        if previous_path is None
        else load_trade_overlap_ledger(previous_path)
    )
    journal = JournalStore(journal_path)
    try:
        trades = tuple(journal.iter_trades())
    finally:
        journal.connection.close()
    return update_trade_overlap_ledger(
        prediction_raw,
        trades,
        previous=previous,
        source_paper_run_id=source_paper_run_id,
        source_paper_run_attempt=source_paper_run_attempt,
        source_learning_artifact_name=source_learning_artifact_name,
        source_learning_artifact_digest=source_learning_artifact_digest,
    )
