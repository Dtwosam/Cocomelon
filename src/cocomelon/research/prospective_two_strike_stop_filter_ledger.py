from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.prospective_two_strike_stop_filter import (
    EMBARGO_MS,
    STRIKE_THRESHOLD,
    ProspectiveTwoStrikeStopFilterState,
    prospective_two_strike_stop_filter_summary,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "prospective-two-strike-stop-filter-ledger-v1"


class ProspectiveTwoStrikeStopFilterLedgerError(RuntimeError):
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
    if not isinstance(value, str):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            f"{field} must be a string"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            f"{field} must be a decimal"
        ) from exc
    if not parsed.is_finite():
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            f"{field} must be finite"
        )
    return value


def _required_string(
    raw: dict[str, object],
    key: str,
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(
    raw: dict[str, object],
    key: str,
) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            f"{key} must be an integer"
        )
    return value


def _row_identity(
    row: dict[str, object],
) -> tuple[int, int, str]:
    return (
        cast(int, row["opened_at_ms"]),
        cast(int, row["closed_at_ms"]),
        cast(str, row["trade_id"]),
    )


def _canonical_row(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "ledger row must be an object"
        )
    trade_id = _required_string(raw, "trade_id")
    market = _required_string(raw, "market")
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "ledger row direction must be long or short"
        )
    opened_at_ms = _required_int(raw, "opened_at_ms")
    closed_at_ms = _required_int(raw, "closed_at_ms")
    if opened_at_ms < 0 or closed_at_ms < opened_at_ms:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "ledger row timestamps are invalid"
        )
    exit_reason = _required_string(raw, "exit_reason")
    net_pnl = _decimal_string(raw.get("net_pnl"), field="net_pnl")
    net_r = _decimal_string(raw.get("net_r"), field="net_r")
    prior_strikes = _required_int(raw, "prior_strikes")
    if prior_strikes < 0:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "prior_strikes must be non-negative"
        )
    candidate_admitted = raw.get("candidate_admitted")
    if not isinstance(candidate_admitted, bool):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "candidate_admitted must be boolean"
        )
    if candidate_admitted != (prior_strikes < STRIKE_THRESHOLD):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "candidate admission does not match prior strikes"
        )
    return {
        "trade_id": trade_id,
        "market": market,
        "direction": direction,
        "opened_at_ms": opened_at_ms,
        "closed_at_ms": closed_at_ms,
        "exit_reason": exit_reason,
        "net_pnl": net_pnl,
        "net_r": net_r,
        "prior_strikes": prior_strikes,
        "candidate_admitted": candidate_admitted,
    }


def _canonical_rows(
    raw: object,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "ledger rows must be a list"
        )
    rows = tuple(_canonical_row(row) for row in raw)
    identities = tuple(_row_identity(row) for row in rows)
    if len(identities) != len(set(identities)):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "duplicate ledger row identity"
        )
    trade_ids = tuple(cast(str, row["trade_id"]) for row in rows)
    if len(trade_ids) != len(set(trade_ids)):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "duplicate ledger trade id"
        )
    return tuple(sorted(rows, key=_row_identity))


def _rows_sha256(
    rows: tuple[dict[str, object], ...],
) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _digest_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "ledger_sha256"
    }


def _candidate_rows(
    trades: Sequence[TradeJournalEntry],
    state: ProspectiveTwoStrikeStopFilterState,
) -> tuple[
    tuple[dict[str, object], ...],
    dict[str, object],
]:
    values = tuple(trades)
    summary = prospective_two_strike_stop_filter_summary(
        values,
        state,
    )
    raw_strikes = summary.get("decision_prior_strikes")
    if not isinstance(raw_strikes, dict):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "candidate summary is missing decision strikes"
        )

    prospective = tuple(
        sorted(
            (
                trade
                for trade in values
                if trade.opened_at_ms >= state.started_at_ms
            ),
            key=lambda trade: (
                trade.opened_at_ms,
                trade.closed_at_ms,
                trade.trade_id,
            ),
        )
    )
    rows: list[dict[str, object]] = []
    for trade in prospective:
        raw_prior = raw_strikes.get(trade.trade_id)
        if isinstance(raw_prior, bool) or not isinstance(raw_prior, int):
            raise ProspectiveTwoStrikeStopFilterLedgerError(
                "candidate summary is missing a trade strike decision"
            )
        rows.append(
            {
                "trade_id": trade.trade_id,
                "market": trade.market.canonical,
                "direction": trade.direction.value,
                "opened_at_ms": trade.opened_at_ms,
                "closed_at_ms": trade.closed_at_ms,
                "exit_reason": trade.exit_reason,
                "net_pnl": str(trade.net_pnl),
                "net_r": str(trade.net_r),
                "prior_strikes": raw_prior,
                "candidate_admitted": (
                    raw_prior < STRIKE_THRESHOLD
                ),
            }
        )
    canonical = _canonical_rows(tuple(rows))
    if len(canonical) != summary.get("prospective_closed_trades"):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "candidate row count does not match summary"
        )
    admitted = sum(
        row["candidate_admitted"] is True for row in canonical
    )
    if admitted != summary.get("admitted_trades"):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "candidate admitted count does not match summary"
        )
    if len(canonical) - admitted != summary.get("blocked_trades"):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "candidate blocked count does not match summary"
        )
    return canonical, summary


def _summary_snapshot(
    summary: dict[str, object],
) -> dict[str, object]:
    keys = (
        "prospective_closed_trades",
        "admitted_trades",
        "blocked_trades",
        "blocked_wins",
        "blocked_losses",
        "blocked_net_pnl",
        "actual_net_pnl",
        "candidate_net_pnl",
        "delta_net_pnl",
        "actual_net_r",
        "candidate_net_r",
        "delta_net_r",
        "by_direction",
        "blocked_by_market",
        "robustness",
        "readiness",
    )
    return {key: summary[key] for key in keys}


def validate_two_strike_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger must be an object"
        )
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger kind is unsupported"
        )
    candidate_id = _required_string(raw, "candidate_id")
    frozen_at_ms = _required_int(raw, "frozen_at_ms")
    started_at_ms = _required_int(raw, "started_at_ms")
    embargo_ms = _required_int(raw, "embargo_ms")
    if frozen_at_ms < 0:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "frozen_at_ms must be non-negative"
        )
    if embargo_ms != EMBARGO_MS:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger embargo drift"
        )
    if started_at_ms != frozen_at_ms + EMBARGO_MS:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger start does not match freeze"
        )
    rule = raw.get("rule")
    try:
        expected = ProspectiveTwoStrikeStopFilterState(
            frozen_at_ms=frozen_at_ms,
            candidate_id=candidate_id,
        )
    except ValueError as exc:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            str(exc)
        ) from exc
    if rule != expected.payload()["rule"]:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger rule drift"
        )

    rows = _canonical_rows(raw.get("rows"))
    if raw.get("row_count") != len(rows):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger row count mismatch"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger row digest mismatch"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger source history must be a list"
        )
    summary = raw.get("summary")
    if not isinstance(summary, dict):
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger summary must be an object"
        )
    expected_digest = _sha256_text(
        _canonical_json(_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected_digest:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_two_strike_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveTwoStrikeStopFilterLedgerError(
            "two-strike ledger file is invalid"
        ) from exc
    return validate_two_strike_ledger(raw)


def update_two_strike_ledger(
    trades: Sequence[TradeJournalEntry],
    state: ProspectiveTwoStrikeStopFilterState,
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

    rows, candidate_summary = _candidate_rows(trades, state)
    summary = _summary_snapshot(candidate_summary)

    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None
    if previous is not None:
        validated = validate_two_strike_ledger(previous)
        for key, current in (
            ("candidate_id", state.candidate_id),
            ("frozen_at_ms", state.frozen_at_ms),
            ("started_at_ms", state.started_at_ms),
            ("embargo_ms", EMBARGO_MS),
            ("rule", state.payload()["rule"]),
        ):
            if validated.get(key) != current:
                raise ProspectiveTwoStrikeStopFilterLedgerError(
                    f"two-strike ledger metadata drift: {key}"
                )

        raw_history = validated.get("source_history")
        if not isinstance(raw_history, list):
            raise ProspectiveTwoStrikeStopFilterLedgerError(
                "two-strike ledger source history is invalid"
            )
        for item in raw_history:
            if not isinstance(item, dict):
                raise ProspectiveTwoStrikeStopFilterLedgerError(
                    "two-strike ledger source history entry is invalid"
                )
            if (
                item.get("paper_run_id") == source_paper_run_id
                and item.get("paper_run_attempt")
                == source_paper_run_attempt
            ):
                if (
                    item.get("artifact_name")
                    != source_artifact_name
                    or item.get("artifact_digest")
                    != source_artifact_digest
                ):
                    raise ProspectiveTwoStrikeStopFilterLedgerError(
                        "duplicate source run artifact identity drift"
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
            for row in rows
        }
        for old in previous_rows:
            trade_id = cast(str, old["trade_id"])
            current = current_by_id.get(trade_id)
            if current is None:
                raise ProspectiveTwoStrikeStopFilterLedgerError(
                    "previous two-strike trade row disappeared"
                )
            if current != old:
                raise ProspectiveTwoStrikeStopFilterLedgerError(
                    "previous two-strike trade row changed"
                )

    old_ids = {
        cast(str, row["trade_id"])
        for row in previous_rows
    }
    new_rows = tuple(
        row
        for row in rows
        if cast(str, row["trade_id"]) not in old_ids
    )
    history.append(
        {
            "paper_run_id": source_paper_run_id,
            "paper_run_attempt": source_paper_run_attempt,
            "artifact_name": source_artifact_name,
            "artifact_digest": source_artifact_digest,
            "row_count": len(rows),
            "new_row_count": len(new_rows),
            "rows_sha256": _rows_sha256(rows),
        }
    )

    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "candidate_id": state.candidate_id,
        "frozen_at_ms": state.frozen_at_ms,
        "started_at_ms": state.started_at_ms,
        "embargo_ms": EMBARGO_MS,
        "rule": state.payload()["rule"],
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "prior_ledger_sha256": prior_ledger_sha256,
        "row_count": len(rows),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(new_rows),
        "first_opened_at_ms": (
            None
            if not rows
            else min(cast(int, row["opened_at_ms"]) for row in rows)
        ),
        "last_closed_at_ms": (
            None
            if not rows
            else max(cast(int, row["closed_at_ms"]) for row in rows)
        ),
        "rows_sha256": _rows_sha256(rows),
        "source_history": history,
        "summary": summary,
        "rows": rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_digest_payload(payload))
    )
    return payload
