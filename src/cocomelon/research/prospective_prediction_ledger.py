from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = (
    "cadence-microstructure-prospective-prediction-ledger-v1"
)
ZERO: Final = Decimal("0")


class ProspectivePredictionLedgerError(RuntimeError):
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
        raise ProspectivePredictionLedgerError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ProspectivePredictionLedgerError(
            f"{field} must be finite"
        )
    return str(resolved)


def _required_string(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProspectivePredictionLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool):
        raise ProspectivePredictionLedgerError(
            f"{key} must be an integer"
        )
    if not isinstance(value, int):
        raise ProspectivePredictionLedgerError(
            f"{key} must be an integer"
        )
    return value


def _canonical_entry(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectivePredictionLedgerError(
            "scored row must be an object"
        )
    decision_id = _required_string(raw, "decision_id")
    market = _required_string(raw, "market")
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise ProspectivePredictionLedgerError(
            "direction must be long or short"
        )
    boundary_ms = _required_int(raw, "boundary_ms")
    if boundary_ms < 0:
        raise ProspectivePredictionLedgerError(
            "boundary_ms must be non-negative"
        )
    admitted = raw.get("admitted")
    if not isinstance(admitted, bool):
        raise ProspectivePredictionLedgerError(
            "admitted must be boolean"
        )
    prediction = _decimal_string(
        raw.get("prediction_net_return"),
        field="prediction_net_return",
    )
    realized = _decimal_string(
        raw.get("realized_net_return"),
        field="realized_net_return",
    )
    if admitted is not (Decimal(prediction) > ZERO):
        raise ProspectivePredictionLedgerError(
            "admitted does not match prediction sign"
        )
    return {
        "decision_id": decision_id,
        "boundary_ms": boundary_ms,
        "market": market,
        "direction": direction,
        "prediction_net_return": prediction,
        "admitted": admitted,
        "realized_net_return": realized,
    }


def _entry_identity(
    entry: dict[str, object],
) -> tuple[int, str, str, str]:
    return (
        cast(int, entry["boundary_ms"]),
        cast(str, entry["market"]),
        cast(str, entry["direction"]),
        cast(str, entry["decision_id"]),
    )


def _canonical_rows(
    scored_rows: object,
) -> tuple[dict[str, object], ...]:
    if not isinstance(scored_rows, (list, tuple)):
        raise ProspectivePredictionLedgerError(
            "scored_rows must be a list"
        )
    rows = tuple(_canonical_entry(row) for row in scored_rows)
    identities = tuple(_entry_identity(row) for row in rows)
    if len(identities) != len(set(identities)):
        raise ProspectivePredictionLedgerError(
            "duplicate prospective row identity"
        )
    return tuple(
        sorted(
            rows,
            key=_entry_identity,
        )
    )


def _rows_sha256(
    rows: tuple[dict[str, object], ...],
) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _report_metadata(report: dict[str, object]) -> dict[str, object]:
    model_family = _required_string(report, "model_family")
    training_digest = _required_string(
        report,
        "frozen_training_rows_sha256",
    )
    prospective_start_ms = _required_int(
        report,
        "prospective_start_ms",
    )
    cadence_ms = _required_int(report, "cadence_ms")
    horizon_ms = _required_int(report, "horizon_ms")
    training_rows = _required_int(
        report,
        "frozen_training_rows",
    )
    if prospective_start_ms < 0:
        raise ProspectivePredictionLedgerError(
            "prospective_start_ms must be non-negative"
        )
    if cadence_ms <= 0 or horizon_ms <= 0 or training_rows <= 0:
        raise ProspectivePredictionLedgerError(
            "cadence, horizon, and training rows must be positive"
        )
    if report.get("research_only") is not True:
        raise ProspectivePredictionLedgerError(
            "prospective report must be research-only"
        )
    if report.get("execution_authority") is not False:
        raise ProspectivePredictionLedgerError(
            "prospective report cannot have execution authority"
        )
    if report.get("promotion_authority") is not False:
        raise ProspectivePredictionLedgerError(
            "prospective report cannot have promotion authority"
        )
    return {
        "model_family": model_family,
        "prospective_start_ms": prospective_start_ms,
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "frozen_training_rows": training_rows,
        "frozen_training_rows_sha256": training_digest,
    }


def _ledger_digest_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "ledger_sha256"
    }


def validate_prediction_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectivePredictionLedgerError(
            "prediction ledger must be an object"
        )
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectivePredictionLedgerError(
            "prediction ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectivePredictionLedgerError(
            "prediction ledger kind is unsupported"
        )
    rows = _canonical_rows(raw.get("rows"))
    expected_rows_digest = _rows_sha256(rows)
    if raw.get("rows_sha256") != expected_rows_digest:
        raise ProspectivePredictionLedgerError(
            "prediction ledger row digest mismatch"
        )
    source_history = raw.get("source_history")
    if not isinstance(source_history, list):
        raise ProspectivePredictionLedgerError(
            "prediction ledger source_history must be a list"
        )
    expected_ledger_digest = _sha256_text(
        _canonical_json(_ledger_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected_ledger_digest:
        raise ProspectivePredictionLedgerError(
            "prediction ledger digest mismatch"
        )
    return {
        **raw,
        "rows": rows,
    }


def load_prediction_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectivePredictionLedgerError(
            "prediction ledger file is invalid"
        ) from exc
    return validate_prediction_ledger(raw)


def update_prediction_ledger(
    report: dict[str, object],
    *,
    previous: dict[str, object] | None,
    source_audit_run_id: int,
    source_audit_run_attempt: int,
    source_report_artifact_name: str,
) -> dict[str, object]:
    if source_audit_run_id <= 0 or source_audit_run_attempt <= 0:
        raise ValueError("source audit run identity must be positive")
    if not source_report_artifact_name.strip():
        raise ValueError("source_report_artifact_name must not be empty")
    status = report.get("status")
    if status not in {"collecting", "completed"}:
        raise ProspectivePredictionLedgerError(
            "prospective report is not evidence-ready"
        )

    metadata = _report_metadata(report)
    rows = _canonical_rows(report.get("scored_rows"))
    prospective_start_ms = cast(
        int,
        metadata["prospective_start_ms"],
    )
    if any(
        cast(int, row["boundary_ms"]) < prospective_start_ms
        for row in rows
    ):
        raise ProspectivePredictionLedgerError(
            "pre-freeze row entered prospective ledger"
        )

    previous_rows: tuple[dict[str, object], ...] = ()
    source_history: list[object] = []
    prior_ledger_sha256: str | None = None
    if previous is not None:
        validated = validate_prediction_ledger(previous)
        for key, value in metadata.items():
            if validated.get(key) != value:
                raise ProspectivePredictionLedgerError(
                    f"prediction ledger metadata drift: {key}"
                )
        previous_rows = cast(
            tuple[dict[str, object], ...],
            validated["rows"],
        )
        raw_history = validated["source_history"]
        if not isinstance(raw_history, list):
            raise ProspectivePredictionLedgerError(
                "prediction ledger source history is invalid"
            )
        source_history = list(raw_history)
        prior_ledger_sha256 = str(validated["ledger_sha256"])

        current_by_identity = {
            _entry_identity(row): row
            for row in rows
        }
        for previous_row in previous_rows:
            identity = _entry_identity(previous_row)
            current = current_by_identity.get(identity)
            if current is None:
                raise ProspectivePredictionLedgerError(
                    "previous prospective row disappeared"
                )
            if current != previous_row:
                raise ProspectivePredictionLedgerError(
                    "previous prospective row changed"
                )

    previous_identities = {
        _entry_identity(row)
        for row in previous_rows
    }
    new_rows = tuple(
        row
        for row in rows
        if _entry_identity(row) not in previous_identities
    )
    report_digest = _sha256_text(_canonical_json(report))
    source_history.append(
        {
            "audit_run_id": source_audit_run_id,
            "audit_run_attempt": source_audit_run_attempt,
            "report_artifact_name": source_report_artifact_name,
            "report_sha256": report_digest,
            "row_count": len(rows),
            "new_row_count": len(new_rows),
        }
    )
    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        **metadata,
        "prior_ledger_sha256": prior_ledger_sha256,
        "row_count": len(rows),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(new_rows),
        "first_boundary_ms": (
            None
            if not rows
            else min(cast(int, row["boundary_ms"]) for row in rows)
        ),
        "last_boundary_ms": (
            None
            if not rows
            else max(cast(int, row["boundary_ms"]) for row in rows)
        ),
        "rows_sha256": _rows_sha256(rows),
        "source_history": source_history,
        "rows": rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_ledger_digest_payload(payload))
    )
    return payload
