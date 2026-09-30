from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final, cast

from cocomelon.research.prospective_prediction_ledger import (
    _canonical_json,
    _canonical_rows,
    _entry_identity,
    _report_metadata,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "cadence-prospective-model-comparison-ledger-v1"


class ProspectiveComparisonLedgerError(RuntimeError):
    pass


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveComparisonLedgerError(
            f"{key} must be an integer"
        )
    return value


def _required_string(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveComparisonLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _metadata(
    comparison: dict[str, object],
    microstructure: dict[str, object],
    baseline: dict[str, object],
) -> dict[str, object]:
    try:
        micro = _report_metadata(microstructure)
        base = _report_metadata(baseline)
    except RuntimeError as exc:
        raise ProspectiveComparisonLedgerError(str(exc)) from exc

    for key in (
        "prospective_start_ms",
        "cadence_ms",
        "horizon_ms",
        "frozen_training_rows",
        "frozen_training_rows_sha256",
    ):
        if micro.get(key) != base.get(key):
            raise ProspectiveComparisonLedgerError(
                f"paired model metadata mismatch: {key}"
            )

    if comparison.get("research_only") is not True:
        raise ProspectiveComparisonLedgerError(
            "comparison must be research-only"
        )
    if comparison.get("execution_authority") is not False:
        raise ProspectiveComparisonLedgerError(
            "comparison cannot have execution authority"
        )
    if comparison.get("promotion_authority") is not False:
        raise ProspectiveComparisonLedgerError(
            "comparison cannot have promotion authority"
        )

    source_run_id = _required_int(comparison, "source_run_id")
    source_run_attempt = _required_int(
        comparison,
        "source_run_attempt",
    )
    if source_run_id <= 0 or source_run_attempt <= 0:
        raise ProspectiveComparisonLedgerError(
            "source paper run identity must be positive"
        )

    for key in (
        "prospective_start_ms",
        "frozen_training_rows",
        "frozen_training_rows_sha256",
    ):
        if comparison.get(key) != micro.get(key):
            raise ProspectiveComparisonLedgerError(
                f"comparison metadata mismatch: {key}"
            )

    prospective_rows = _required_int(
        comparison,
        "prospective_rows",
    )
    if prospective_rows < 0:
        raise ProspectiveComparisonLedgerError(
            "prospective_rows must be non-negative"
        )

    return {
        "microstructure_model_family": _required_string(
            microstructure,
            "model_family",
        ),
        "baseline_model_family": _required_string(
            baseline,
            "model_family",
        ),
        "prospective_start_ms": micro["prospective_start_ms"],
        "cadence_ms": micro["cadence_ms"],
        "horizon_ms": micro["horizon_ms"],
        "frozen_training_rows": micro["frozen_training_rows"],
        "frozen_training_rows_sha256": micro[
            "frozen_training_rows_sha256"
        ],
        "source_paper_run_id": source_run_id,
        "source_paper_run_attempt": source_run_attempt,
        "prospective_rows": prospective_rows,
    }


def _canonical_paired_rows(
    microstructure: dict[str, object],
    baseline: dict[str, object],
) -> tuple[dict[str, object], ...]:
    try:
        micro_rows = _canonical_rows(
            microstructure.get("scored_rows")
        )
        base_rows = _canonical_rows(baseline.get("scored_rows"))
    except RuntimeError as exc:
        raise ProspectiveComparisonLedgerError(str(exc)) from exc

    micro_by_identity = {
        _entry_identity(row): row
        for row in micro_rows
    }
    base_by_identity = {
        _entry_identity(row): row
        for row in base_rows
    }
    if set(micro_by_identity) != set(base_by_identity):
        raise ProspectiveComparisonLedgerError(
            "paired model row identities differ"
        )

    paired: list[dict[str, object]] = []
    for identity in sorted(micro_by_identity):
        micro = micro_by_identity[identity]
        base = base_by_identity[identity]
        for key in (
            "decision_id",
            "boundary_ms",
            "market",
            "direction",
            "realized_net_return",
        ):
            if micro.get(key) != base.get(key):
                raise ProspectiveComparisonLedgerError(
                    f"paired model row mismatch: {key}"
                )
        paired.append(
            {
                "decision_id": micro["decision_id"],
                "boundary_ms": micro["boundary_ms"],
                "market": micro["market"],
                "direction": micro["direction"],
                "realized_net_return": micro[
                    "realized_net_return"
                ],
                "microstructure_prediction_net_return": micro[
                    "prediction_net_return"
                ],
                "microstructure_admitted": micro["admitted"],
                "baseline_prediction_net_return": base[
                    "prediction_net_return"
                ],
                "baseline_admitted": base["admitted"],
            }
        )
    return tuple(paired)


def _row_identity(
    row: dict[str, object],
) -> tuple[int, str, str, str]:
    return (
        cast(int, row["boundary_ms"]),
        cast(str, row["market"]),
        cast(str, row["direction"]),
        cast(str, row["decision_id"]),
    )


def _canonical_paired_entry(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveComparisonLedgerError(
            "paired ledger row must be an object"
        )
    required = (
        "decision_id",
        "market",
        "direction",
        "realized_net_return",
        "microstructure_prediction_net_return",
        "baseline_prediction_net_return",
    )
    for key in required:
        if not isinstance(raw.get(key), str):
            raise ProspectiveComparisonLedgerError(
                f"paired ledger row {key} must be a string"
            )
    boundary_ms = raw.get("boundary_ms")
    if isinstance(boundary_ms, bool) or not isinstance(
        boundary_ms,
        int,
    ):
        raise ProspectiveComparisonLedgerError(
            "paired ledger row boundary_ms must be an integer"
        )
    if boundary_ms < 0:
        raise ProspectiveComparisonLedgerError(
            "paired ledger row boundary_ms must be non-negative"
        )
    if raw["direction"] not in {"long", "short"}:
        raise ProspectiveComparisonLedgerError(
            "paired ledger row direction must be long or short"
        )
    for key in (
        "microstructure_admitted",
        "baseline_admitted",
    ):
        if not isinstance(raw.get(key), bool):
            raise ProspectiveComparisonLedgerError(
                f"paired ledger row {key} must be boolean"
            )
    return {
        key: raw[key]
        for key in (
            "decision_id",
            "boundary_ms",
            "market",
            "direction",
            "realized_net_return",
            "microstructure_prediction_net_return",
            "microstructure_admitted",
            "baseline_prediction_net_return",
            "baseline_admitted",
        )
    }


def _canonical_ledger_rows(
    raw: object,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProspectiveComparisonLedgerError(
            "paired ledger rows must be a list"
        )
    rows = tuple(
        _canonical_paired_entry(row)
        for row in raw
    )
    identities = tuple(_row_identity(row) for row in rows)
    if len(identities) != len(set(identities)):
        raise ProspectiveComparisonLedgerError(
            "duplicate paired ledger row identity"
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


def validate_comparison_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveComparisonLedgerError(
            "comparison ledger must be an object"
        )
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveComparisonLedgerError(
            "comparison ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveComparisonLedgerError(
            "comparison ledger kind is unsupported"
        )
    rows = _canonical_ledger_rows(raw.get("rows"))
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveComparisonLedgerError(
            "comparison ledger row digest mismatch"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveComparisonLedgerError(
            "comparison ledger source_history must be a list"
        )
    expected = _sha256_text(
        _canonical_json(_ledger_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected:
        raise ProspectiveComparisonLedgerError(
            "comparison ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_comparison_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveComparisonLedgerError(
            "comparison ledger file is invalid"
        ) from exc
    return validate_comparison_ledger(raw)


def update_comparison_ledger(
    comparison: dict[str, object],
    microstructure: dict[str, object],
    baseline: dict[str, object],
    *,
    previous: dict[str, object] | None,
    source_comparison_run_id: int,
    source_comparison_run_attempt: int,
    source_artifact_name: str,
) -> dict[str, object]:
    if source_comparison_run_id <= 0:
        raise ValueError(
            "source comparison run ID must be positive"
        )
    if source_comparison_run_attempt <= 0:
        raise ValueError(
            "source comparison run attempt must be positive"
        )
    if not source_artifact_name.strip():
        raise ValueError("source_artifact_name must not be empty")

    metadata = _metadata(
        comparison,
        microstructure,
        baseline,
    )
    rows = _canonical_paired_rows(
        microstructure,
        baseline,
    )
    if len(rows) != cast(int, metadata["prospective_rows"]):
        raise ProspectiveComparisonLedgerError(
            "paired row count does not match comparison"
        )
    start = cast(int, metadata["prospective_start_ms"])
    if any(
        cast(int, row["boundary_ms"]) < start
        for row in rows
    ):
        raise ProspectiveComparisonLedgerError(
            "pre-freeze row entered comparison ledger"
        )

    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None
    if previous is not None:
        validated = validate_comparison_ledger(previous)
        for key in (
            "microstructure_model_family",
            "baseline_model_family",
            "prospective_start_ms",
            "cadence_ms",
            "horizon_ms",
            "frozen_training_rows",
            "frozen_training_rows_sha256",
        ):
            if validated.get(key) != metadata.get(key):
                raise ProspectiveComparisonLedgerError(
                    f"comparison ledger metadata drift: {key}"
                )
        previous_rows = cast(
            tuple[dict[str, object], ...],
            validated["rows"],
        )
        raw_history = validated["source_history"]
        if not isinstance(raw_history, list):
            raise ProspectiveComparisonLedgerError(
                "comparison ledger source history is invalid"
            )
        history = list(raw_history)
        prior_ledger_sha256 = str(validated["ledger_sha256"])

        current_by_identity = {
            _row_identity(row): row
            for row in rows
        }
        for old in previous_rows:
            identity = _row_identity(old)
            current = current_by_identity.get(identity)
            if current is None:
                raise ProspectiveComparisonLedgerError(
                    "previous paired row disappeared"
                )
            if current != old:
                raise ProspectiveComparisonLedgerError(
                    "previous paired row changed"
                )

    old_identities = {
        _row_identity(row)
        for row in previous_rows
    }
    new_rows = tuple(
        row
        for row in rows
        if _row_identity(row) not in old_identities
    )
    source_digest = _sha256_text(
        _canonical_json(
            {
                "comparison": comparison,
                "microstructure": microstructure,
                "baseline": baseline,
            }
        )
    )
    history.append(
        {
            "comparison_run_id": source_comparison_run_id,
            "comparison_run_attempt": source_comparison_run_attempt,
            "comparison_artifact_name": source_artifact_name,
            "source_payload_sha256": source_digest,
            "source_paper_run_id": metadata[
                "source_paper_run_id"
            ],
            "source_paper_run_attempt": metadata[
                "source_paper_run_attempt"
            ],
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
            else min(
                cast(int, row["boundary_ms"])
                for row in rows
            )
        ),
        "last_boundary_ms": (
            None
            if not rows
            else max(
                cast(int, row["boundary_ms"])
                for row in rows
            )
        ),
        "rows_sha256": _rows_sha256(rows),
        "source_history": history,
        "rows": rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_ledger_digest_payload(payload))
    )
    return payload
