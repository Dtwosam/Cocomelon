from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fill_weighted import (
    EVALUABLE_SOURCES,
)
from cocomelon.research.delayed_entry_pair import (
    BASE_DELAY_MS,
    CHALLENGER_DELAY_MS,
)
from cocomelon.research.prospective_side_conditioned_delay import (
    ProspectiveSideConditionedDelayError,
    ProspectiveSideConditionedDelayState,
    _fill_weighted,
    _outcome_map,
    _trade_map,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "prospective-side-conditioned-timing-ledger-v1"
ZERO: Final = Decimal("0")


class ProspectiveTimingLedgerError(RuntimeError):
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
        raise ProspectiveTimingLedgerError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ProspectiveTimingLedgerError(
            f"{field} must be finite"
        )
    return str(resolved)


def extract_prospective_timing_rows(
    journal: JournalStore,
    base_60s_outcomes: tuple[DelayedEntryOutcome, ...],
    challenger_120s_outcomes: tuple[DelayedEntryOutcome, ...],
    state: ProspectiveSideConditionedDelayState,
) -> tuple[tuple[dict[str, object], ...], dict[str, int]]:
    trades = _trade_map(journal)
    base_map = _outcome_map(base_60s_outcomes, label="60s")
    challenger_map = _outcome_map(
        challenger_120s_outcomes,
        label="120s",
    )
    prospective = tuple(
        sorted(
            (
                trade
                for trade in trades.values()
                if trade.opened_at_ms >= state.started_at_ms
            ),
            key=lambda trade: (
                trade.closed_at_ms,
                trade.trade_id,
            ),
        )
    )

    rows: list[dict[str, object]] = []
    missing_60s = 0
    missing_120s = 0
    non_evaluable_60s = 0
    non_evaluable_120s = 0
    lineage_mismatches = 0

    for trade in prospective:
        base = base_map.get(trade.trade_id)
        challenger = challenger_map.get(trade.trade_id)
        if base is None:
            missing_60s += 1
            continue
        if challenger is None:
            missing_120s += 1
            continue
        if base.source not in EVALUABLE_SOURCES:
            non_evaluable_60s += 1
            continue
        if challenger.source not in EVALUABLE_SOURCES:
            non_evaluable_120s += 1
            continue
        try:
            base_item = _fill_weighted(trade, base)
            challenger_item = _fill_weighted(
                trade,
                challenger,
            )
        except ProspectiveSideConditionedDelayError:
            lineage_mismatches += 1
            continue

        selected = (
            challenger_item
            if trade.direction is Direction.LONG
            else base_item
        )
        selected_delay_ms = (
            CHALLENGER_DELAY_MS
            if trade.direction is Direction.LONG
            else BASE_DELAY_MS
        )
        actual = trade.net_pnl
        base_net = base_item.candidate_net_pnl_estimate
        challenger_net = (
            challenger_item.candidate_net_pnl_estimate
        )
        selected_net = selected.candidate_net_pnl_estimate
        rows.append(
            {
                "trade_id": trade.trade_id,
                "market": trade.market.canonical,
                "direction": trade.direction.value,
                "opened_at_ms": trade.opened_at_ms,
                "closed_at_ms": trade.closed_at_ms,
                "actual_net_pnl": str(actual),
                "base_60s_net_pnl": str(base_net),
                "challenger_120s_net_pnl": str(
                    challenger_net
                ),
                "selected_delay_ms": selected_delay_ms,
                "selected_net_pnl": str(selected_net),
                "selected_fill_fraction": str(
                    selected.fill_fraction
                ),
                "selected_minus_actual_pnl": str(
                    selected_net - actual
                ),
                "selected_minus_60s_pnl": str(
                    selected_net - base_net
                ),
            }
        )

    return (
        tuple(rows),
        {
            "prospective_closed_trades": len(prospective),
            "paired_evaluable_trades": len(rows),
            "missing_60s_outcomes": missing_60s,
            "missing_120s_outcomes": missing_120s,
            "non_evaluable_60s": non_evaluable_60s,
            "non_evaluable_120s": non_evaluable_120s,
            "lineage_mismatches": lineage_mismatches,
        },
    )


def _required_string(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveTimingLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveTimingLedgerError(
            f"{key} must be an integer"
        )
    return value


def _canonical_entry(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveTimingLedgerError(
            "timing ledger row must be an object"
        )
    trade_id = _required_string(raw, "trade_id")
    market = _required_string(raw, "market")
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise ProspectiveTimingLedgerError(
            "timing row direction must be long or short"
        )
    opened_at_ms = _required_int(raw, "opened_at_ms")
    closed_at_ms = _required_int(raw, "closed_at_ms")
    selected_delay_ms = _required_int(
        raw,
        "selected_delay_ms",
    )
    if opened_at_ms < 0 or closed_at_ms < opened_at_ms:
        raise ProspectiveTimingLedgerError(
            "timing row timestamps are invalid"
        )
    expected_delay = (
        CHALLENGER_DELAY_MS
        if direction == "long"
        else BASE_DELAY_MS
    )
    if selected_delay_ms != expected_delay:
        raise ProspectiveTimingLedgerError(
            "timing row selected delay violates frozen rule"
        )

    actual = _decimal_string(
        raw.get("actual_net_pnl"),
        field="actual_net_pnl",
    )
    base = _decimal_string(
        raw.get("base_60s_net_pnl"),
        field="base_60s_net_pnl",
    )
    challenger = _decimal_string(
        raw.get("challenger_120s_net_pnl"),
        field="challenger_120s_net_pnl",
    )
    selected = _decimal_string(
        raw.get("selected_net_pnl"),
        field="selected_net_pnl",
    )
    fill = _decimal_string(
        raw.get("selected_fill_fraction"),
        field="selected_fill_fraction",
    )
    minus_actual = _decimal_string(
        raw.get("selected_minus_actual_pnl"),
        field="selected_minus_actual_pnl",
    )
    minus_60s = _decimal_string(
        raw.get("selected_minus_60s_pnl"),
        field="selected_minus_60s_pnl",
    )

    expected_selected = (
        challenger if direction == "long" else base
    )
    if Decimal(selected) != Decimal(expected_selected):
        raise ProspectiveTimingLedgerError(
            "timing row selected PnL violates frozen rule"
        )
    if Decimal(minus_actual) != (
        Decimal(selected) - Decimal(actual)
    ):
        raise ProspectiveTimingLedgerError(
            "timing row delta versus actual is inconsistent"
        )
    if Decimal(minus_60s) != (
        Decimal(selected) - Decimal(base)
    ):
        raise ProspectiveTimingLedgerError(
            "timing row delta versus 60s is inconsistent"
        )
    fill_value = Decimal(fill)
    if fill_value < ZERO or fill_value > Decimal("1"):
        raise ProspectiveTimingLedgerError(
            "timing row fill fraction must be within [0, 1]"
        )

    return {
        "trade_id": trade_id,
        "market": market,
        "direction": direction,
        "opened_at_ms": opened_at_ms,
        "closed_at_ms": closed_at_ms,
        "actual_net_pnl": actual,
        "base_60s_net_pnl": base,
        "challenger_120s_net_pnl": challenger,
        "selected_delay_ms": selected_delay_ms,
        "selected_net_pnl": selected,
        "selected_fill_fraction": fill,
        "selected_minus_actual_pnl": minus_actual,
        "selected_minus_60s_pnl": minus_60s,
    }


def _row_identity(
    row: dict[str, object],
) -> tuple[int, str]:
    return (
        cast(int, row["closed_at_ms"]),
        cast(str, row["trade_id"]),
    )


def _canonical_rows(
    raw: object,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProspectiveTimingLedgerError(
            "timing ledger rows must be a list"
        )
    rows = tuple(_canonical_entry(row) for row in raw)
    identities = tuple(_row_identity(row) for row in rows)
    if len(identities) != len(set(identities)):
        raise ProspectiveTimingLedgerError(
            "duplicate timing ledger row identity"
        )
    return tuple(sorted(rows, key=_row_identity))


def _rows_sha256(
    rows: tuple[dict[str, object], ...],
) -> str:
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


def validate_timing_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveTimingLedgerError(
            "timing ledger must be an object"
        )
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveTimingLedgerError(
            "timing ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveTimingLedgerError(
            "timing ledger kind is unsupported"
        )
    rows = _canonical_rows(raw.get("rows"))
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveTimingLedgerError(
            "timing ledger row digest mismatch"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveTimingLedgerError(
            "timing ledger source_history must be a list"
        )
    expected = _sha256_text(
        _canonical_json(_ledger_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected:
        raise ProspectiveTimingLedgerError(
            "timing ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_timing_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveTimingLedgerError(
            "timing ledger file is invalid"
        ) from exc
    return validate_timing_ledger(raw)


def update_timing_ledger(
    rows: tuple[dict[str, object], ...],
    diagnostics: dict[str, int],
    state: ProspectiveSideConditionedDelayState,
    *,
    previous: dict[str, object] | None,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_timing_artifact_name: str,
) -> dict[str, object]:
    if source_paper_run_id <= 0 or source_paper_run_attempt <= 0:
        raise ValueError("source paper run identity must be positive")
    if not source_timing_artifact_name.strip():
        raise ValueError(
            "source_timing_artifact_name must not be empty"
        )

    canonical = _canonical_rows(rows)
    if any(
        cast(int, row["opened_at_ms"]) < state.started_at_ms
        for row in canonical
    ):
        raise ProspectiveTimingLedgerError(
            "pre-candidate trade entered timing ledger"
        )
    rule = state.payload()["rule"]
    if not isinstance(rule, dict):
        raise ProspectiveTimingLedgerError(
            "timing candidate rule must be an object"
        )
    metadata = {
        "candidate_id": state.candidate_id,
        "started_at_ms": state.started_at_ms,
        "long_delay_ms": rule["long_delay_ms"],
        "short_delay_ms": rule["short_delay_ms"],
        "direction_policy": rule["direction_policy"],
    }

    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None
    if previous is not None:
        validated = validate_timing_ledger(previous)
        for key, value in metadata.items():
            if validated.get(key) != value:
                raise ProspectiveTimingLedgerError(
                    f"timing ledger metadata drift: {key}"
                )
        previous_rows = cast(
            tuple[dict[str, object], ...],
            validated["rows"],
        )
        raw_history = validated["source_history"]
        if not isinstance(raw_history, list):
            raise ProspectiveTimingLedgerError(
                "timing ledger source history is invalid"
            )
        history = list(raw_history)
        prior_ledger_sha256 = str(validated["ledger_sha256"])
        current_by_identity = {
            _row_identity(row): row
            for row in canonical
        }
        for old in previous_rows:
            identity = _row_identity(old)
            current = current_by_identity.get(identity)
            if current is None:
                raise ProspectiveTimingLedgerError(
                    "previous timing row disappeared"
                )
            if current != old:
                raise ProspectiveTimingLedgerError(
                    "previous timing row changed"
                )

    old_identities = {
        _row_identity(row)
        for row in previous_rows
    }
    new_rows = tuple(
        row
        for row in canonical
        if _row_identity(row) not in old_identities
    )
    source_digest = _sha256_text(
        _canonical_json(
            {
                "rows": canonical,
                "diagnostics": diagnostics,
                "state": state.payload(),
            }
        )
    )
    history.append(
        {
            "paper_run_id": source_paper_run_id,
            "paper_run_attempt": source_paper_run_attempt,
            "timing_artifact_name": source_timing_artifact_name,
            "source_payload_sha256": source_digest,
            "row_count": len(canonical),
            "new_row_count": len(new_rows),
            "diagnostics": diagnostics,
        }
    )

    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        **metadata,
        "prior_ledger_sha256": prior_ledger_sha256,
        "row_count": len(canonical),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(new_rows),
        "first_closed_at_ms": (
            None
            if not canonical
            else min(
                cast(int, row["closed_at_ms"])
                for row in canonical
            )
        ),
        "last_closed_at_ms": (
            None
            if not canonical
            else max(
                cast(int, row["closed_at_ms"])
                for row in canonical
            )
        ),
        "rows_sha256": _rows_sha256(canonical),
        "source_history": history,
        "rows": canonical,
        "latest_diagnostics": diagnostics,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_ledger_digest_payload(payload))
    )
    return payload
