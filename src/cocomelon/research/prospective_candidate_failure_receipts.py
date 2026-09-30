from __future__ import annotations

import hashlib
import json
from typing import Final, cast

KIND: Final = "prospective-candidate-first-failure-receipts-v1"
SCHEMA_VERSION: Final = 1
_FAILED_STATE: Final = "failed_closed_block"
_LIFECYCLE_STATES: Final = {
    "collecting",
    "review_ready",
    _FAILED_STATE,
}
_CANDIDATES: Final = (
    "cadence_microstructure",
    "side_conditioned_timing",
)


class ProspectiveCandidateFailureReceiptError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _dict(value: object, code: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ProspectiveCandidateFailureReceiptError(code)
    return cast(dict[str, object], value)


def _int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProspectiveCandidateFailureReceiptError(code)
    return value


def _str(value: object, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProspectiveCandidateFailureReceiptError(code)
    return value


def _failed_block_snapshot(
    blocks_raw: object,
    *,
    label: str,
) -> tuple[dict[str, object], ...]:
    if not isinstance(blocks_raw, (list, tuple)):
        raise ProspectiveCandidateFailureReceiptError(
            "FAILURE_BLOCKS_INVALID"
        )
    output: list[dict[str, object]] = []
    for raw in blocks_raw:
        block = _dict(raw, "FAILURE_BLOCK_INVALID")
        if block.get("closed") is not True:
            continue
        if block.get("passes") is True:
            continue
        output.append(
            {
                "family": label,
                "block_index": block.get("block_index"),
                "start_row": block.get("start_row"),
                "end_row": block.get("end_row"),
                "required_rows": block.get("required_rows"),
                "observed_rows": block.get(
                    "prospective_rows",
                    block.get("paired_rows", block.get("rows")),
                ),
                "candidate_net_return_sum": block.get(
                    "candidate_net_return_sum"
                ),
                "incremental_net_return_sum": block.get(
                    "microstructure_minus_baseline_sum"
                ),
                "selected_minus_actual_pnl": block.get(
                    "selected_minus_actual_pnl"
                ),
                "selected_minus_60s_pnl": block.get(
                    "selected_minus_60s_pnl"
                ),
            }
        )
    return tuple(output)


def _receipt(
    report: dict[str, object],
    *,
    candidate_key: str,
    source_readiness_run_id: int,
    source_readiness_run_attempt: int,
) -> dict[str, object]:
    cadence = _dict(report.get("cadence"), "CADENCE_MANIFEST_INVALID")
    comparison = _dict(
        report.get("comparison"),
        "COMPARISON_MANIFEST_INVALID",
    )
    timing = _dict(report.get("timing"), "TIMING_MANIFEST_INVALID")

    if candidate_key == "cadence_microstructure":
        lifecycle = cadence.get("lifecycle_state")
        if lifecycle != _FAILED_STATE:
            raise ProspectiveCandidateFailureReceiptError(
                "CADENCE_NOT_FAILED"
            )
        components_raw = cadence.get(
            "irrecoverable_failure_components",
            (),
        )
        if not isinstance(components_raw, (list, tuple)):
            raise ProspectiveCandidateFailureReceiptError(
                "CADENCE_FAILURE_COMPONENTS_INVALID"
            )
        blocks = (
            _failed_block_snapshot(
                cadence.get("stability_blocks"),
                label="standalone_stability",
            )
            + _failed_block_snapshot(
                comparison.get("incremental_stability_blocks"),
                label="incremental_parsimony_stability",
            )
        )
        identity = {
            "model_family": _str(
                cadence.get("model_family"),
                "CADENCE_MODEL_FAMILY_INVALID",
            ),
            "prospective_start_ms": cadence.get(
                "prospective_start_ms"
            ),
            "frozen_training_rows_sha256": _str(
                cadence.get("frozen_training_rows_sha256"),
                "CADENCE_TRAINING_DIGEST_INVALID",
            ),
            "prediction_ledger_sha256": _str(
                cadence.get("prediction_ledger_sha256"),
                "CADENCE_PREDICTION_LEDGER_INVALID",
            ),
            "comparison_ledger_sha256": _str(
                cadence.get("comparison_ledger_sha256"),
                "CADENCE_COMPARISON_LEDGER_INVALID",
            ),
        }
    elif candidate_key == "side_conditioned_timing":
        lifecycle = timing.get("lifecycle_state")
        if lifecycle != _FAILED_STATE:
            raise ProspectiveCandidateFailureReceiptError(
                "TIMING_NOT_FAILED"
            )
        components_raw = timing.get(
            "irrecoverable_failure_components",
            (),
        )
        if not isinstance(components_raw, (list, tuple)):
            raise ProspectiveCandidateFailureReceiptError(
                "TIMING_FAILURE_COMPONENTS_INVALID"
            )
        blocks = _failed_block_snapshot(
            timing.get("temporal_blocks"),
            label="temporal_stability",
        )
        identity = {
            "candidate_id": _str(
                timing.get("candidate_id"),
                "TIMING_CANDIDATE_INVALID",
            ),
            "started_at_ms": timing.get("started_at_ms"),
            "timing_ledger_sha256": _str(
                timing.get("timing_ledger_sha256"),
                "TIMING_LEDGER_INVALID",
            ),
        }
    else:
        raise ProspectiveCandidateFailureReceiptError(
            "CANDIDATE_KEY_INVALID"
        )

    components = tuple(str(item) for item in components_raw)
    if not components or not blocks:
        raise ProspectiveCandidateFailureReceiptError(
            "FIRST_FAILURE_EVIDENCE_INCOMPLETE"
        )
    payload = {
        "candidate_key": candidate_key,
        "lifecycle_state": _FAILED_STATE,
        "failure_components": components,
        "source_readiness_run_id": source_readiness_run_id,
        "source_readiness_run_attempt": source_readiness_run_attempt,
        "candidate_identity": identity,
        "failed_closed_blocks": blocks,
    }
    return {**payload, "receipt_id": _sha256(payload)}


def _validate_previous(
    previous: dict[str, object] | None,
) -> tuple[dict[str, object], ...]:
    if previous is None:
        return ()
    if previous.get("kind") != KIND:
        raise ProspectiveCandidateFailureReceiptError(
            "FAILURE_RECEIPT_KIND_INVALID"
        )
    if previous.get("schema_version") != SCHEMA_VERSION:
        raise ProspectiveCandidateFailureReceiptError(
            "FAILURE_RECEIPT_SCHEMA_INVALID"
        )
    entries_raw = previous.get("entries")
    if not isinstance(entries_raw, list):
        raise ProspectiveCandidateFailureReceiptError(
            "FAILURE_RECEIPT_ENTRIES_INVALID"
        )
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in entries_raw:
        entry = _dict(raw, "FAILURE_RECEIPT_ENTRY_INVALID")
        candidate = _str(
            entry.get("candidate_key"),
            "FAILURE_RECEIPT_CANDIDATE_INVALID",
        )
        if candidate not in _CANDIDATES or candidate in seen:
            raise ProspectiveCandidateFailureReceiptError(
                "FAILURE_RECEIPT_CANDIDATE_INVALID"
            )
        receipt_id = _str(
            entry.get("receipt_id"),
            "FAILURE_RECEIPT_ID_INVALID",
        )
        payload = {
            key: value
            for key, value in entry.items()
            if key != "receipt_id"
        }
        if _sha256(payload) != receipt_id:
            raise ProspectiveCandidateFailureReceiptError(
                "FAILURE_RECEIPT_ID_MISMATCH"
            )
        seen.add(candidate)
        entries.append(entry)
    entries.sort(key=lambda item: str(item["candidate_key"]))
    canonical = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "entries": entries,
        "entry_count": len(entries),
    }
    if previous.get("entry_count") != len(entries):
        raise ProspectiveCandidateFailureReceiptError(
            "FAILURE_RECEIPT_COUNT_MISMATCH"
        )
    if previous.get("ledger_sha256") != _sha256(canonical):
        raise ProspectiveCandidateFailureReceiptError(
            "FAILURE_RECEIPT_LEDGER_DIGEST_MISMATCH"
        )
    return tuple(entries)


def update_candidate_failure_receipts(
    readiness_report: dict[str, object],
    *,
    source_readiness_run_id: int,
    source_readiness_run_attempt: int,
    previous: dict[str, object] | None = None,
) -> dict[str, object]:
    if readiness_report.get("kind") != (
        "prospective-trade-quality-readiness-v1"
    ):
        raise ProspectiveCandidateFailureReceiptError(
            "READINESS_KIND_INVALID"
        )
    if readiness_report.get("schema_version") != 1:
        raise ProspectiveCandidateFailureReceiptError(
            "READINESS_SCHEMA_INVALID"
        )
    run_id = _int(
        source_readiness_run_id,
        "READINESS_RUN_ID_INVALID",
    )
    run_attempt = _int(
        source_readiness_run_attempt,
        "READINESS_RUN_ATTEMPT_INVALID",
    )

    cadence = _dict(
        readiness_report.get("cadence"),
        "CADENCE_MANIFEST_INVALID",
    )
    timing = _dict(
        readiness_report.get("timing"),
        "TIMING_MANIFEST_INVALID",
    )
    current_states = {
        "cadence_microstructure": cadence.get("lifecycle_state"),
        "side_conditioned_timing": timing.get("lifecycle_state"),
    }
    if any(
        state not in _LIFECYCLE_STATES
        for state in current_states.values()
    ):
        raise ProspectiveCandidateFailureReceiptError(
            "READINESS_LIFECYCLE_STATE_INVALID"
        )

    previous_entries = _validate_previous(previous)
    entries = {
        str(entry["candidate_key"]): entry
        for entry in previous_entries
    }

    for candidate, entry in tuple(entries.items()):
        if current_states.get(candidate) != _FAILED_STATE:
            raise ProspectiveCandidateFailureReceiptError(
                "FIRST_FAILURE_CANDIDATE_RECOVERED"
            )
        if entry.get("lifecycle_state") != _FAILED_STATE:
            raise ProspectiveCandidateFailureReceiptError(
                "FAILURE_RECEIPT_STATE_INVALID"
            )

    for candidate in _CANDIDATES:
        if current_states.get(candidate) != _FAILED_STATE:
            continue
        if candidate in entries:
            continue
        entries[candidate] = _receipt(
            readiness_report,
            candidate_key=candidate,
            source_readiness_run_id=run_id,
            source_readiness_run_attempt=run_attempt,
        )

    ordered = [
        entries[key]
        for key in sorted(entries)
    ]
    canonical = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "entries": ordered,
        "entry_count": len(ordered),
    }
    return {
        **canonical,
        "ledger_sha256": _sha256(canonical),
    }
