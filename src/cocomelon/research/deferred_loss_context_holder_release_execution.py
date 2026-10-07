from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from cocomelon.research.continuous_paper_capacity_release_books import (
    CapacityReleaseBookEvidence,
    CapacityReleaseBookStore,
)
from cocomelon.research.loss_context_candidate import (
    verify_loss_context_candidate_freeze,
)
from cocomelon.research.loss_context_holder_release_execution import (
    loss_context_holder_release_execution_summary,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    CandidateCausedCapacityRelease,
)

OUTPUT_FILENAME = "loss-context-holder-release-execution-summary.json"
FREEZE_FILENAME = "loss-context-candidate-freeze.json"
REFLOW_FILENAME = "loss-context-capacity-reflow-summary.json"
ALLOWED_SESSION_EXITS = frozenset({"duration_elapsed", "upgrade_requested"})


class DeferredLossContextHolderReleaseExecutionError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _load_object(path: Path, field: str) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeferredLossContextHolderReleaseExecutionError(
            f"{field} is missing or invalid"
        ) from exc
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) for key in raw
    ):
        raise DeferredLossContextHolderReleaseExecutionError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], raw)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DeferredLossContextHolderReleaseExecutionError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DeferredLossContextHolderReleaseExecutionError(
            f"{field} must be a non-negative integer"
        )
    return value


def loss_context_release_options_from_payload(
    reflow: dict[str, object],
) -> tuple[CandidateCausedCapacityRelease, ...]:
    raw = reflow.get("release_options")
    if not isinstance(raw, list):
        raise DeferredLossContextHolderReleaseExecutionError(
            "loss-context reflow release_options must be an array"
        )
    releases: list[CandidateCausedCapacityRelease] = []
    for item in raw:
        if not isinstance(item, dict):
            raise DeferredLossContextHolderReleaseExecutionError(
                "loss-context reflow release option must be an object"
            )
        releases.append(
            CandidateCausedCapacityRelease(
                opportunity_id=_string(
                    item.get("opportunity_id"),
                    "opportunity_id",
                ),
                opportunity_timestamp_ms=_integer(
                    item.get("opportunity_timestamp_ms"),
                    "opportunity_timestamp_ms",
                ),
                opportunity_market=_string(
                    item.get("opportunity_market"),
                    "opportunity_market",
                ),
                release_market=_string(
                    item.get("release_market"),
                    "release_market",
                ),
                release_correlation_bucket=_string(
                    item.get("release_correlation_bucket"),
                    "release_correlation_bucket",
                ),
                release_opening_plan_id=_string(
                    item.get("release_opening_plan_id"),
                    "release_opening_plan_id",
                ),
                release_block_reason=_string(
                    item.get("release_block_reason"),
                    "release_block_reason",
                ),
            )
        )
    return tuple(releases)


def _capacity_release_records(
    root: Path,
) -> tuple[CapacityReleaseBookEvidence, ...]:
    store_root = root / "capacity-release-books"
    protocol_path = store_root / "protocol.json"
    if not protocol_path.is_file():
        return ()
    protocol = _load_object(
        protocol_path,
        "capacity release protocol",
    )
    store = CapacityReleaseBookStore(
        store_root,
        capture_started_at_ms=_integer(
            protocol.get("capture_started_at_ms"),
            "capture_started_at_ms",
        ),
        latency_ms=_integer(
            protocol.get("latency_ms"),
            "latency_ms",
        ),
        max_book_age_ms=_integer(
            protocol.get("max_book_age_ms"),
            "max_book_age_ms",
        ),
    )
    return store.iter_records()


def rebuild_deferred_loss_context_holder_release_execution(
    state_root: str | Path,
) -> dict[str, object]:
    root = Path(state_root)
    session = _load_object(root / "session-summary.json", "session summary")
    exit_reason = session.get("exit_reason")
    if exit_reason not in ALLOWED_SESSION_EXITS:
        raise DeferredLossContextHolderReleaseExecutionError(
            "loss-context holder release requires a clean paper handoff"
        )

    freeze_path = root / FREEZE_FILENAME
    reflow_path = root / REFLOW_FILENAME
    if not freeze_path.is_file() or freeze_path.stat().st_size <= 0:
        raise DeferredLossContextHolderReleaseExecutionError(
            "loss-context freeze is missing"
        )
    if not reflow_path.is_file() or reflow_path.stat().st_size <= 0:
        raise DeferredLossContextHolderReleaseExecutionError(
            "loss-context capacity reflow is missing"
        )

    freeze = verify_loss_context_candidate_freeze(freeze_path)
    reflow = _load_object(
        reflow_path,
        "loss-context capacity reflow",
    )
    if reflow.get("candidate_id") != freeze.candidate_id:
        raise DeferredLossContextHolderReleaseExecutionError(
            "LOSS_CONTEXT_HOLDER_RELEASE_CANDIDATE_MISMATCH"
        )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "promotion_authority",
        "execution_authority",
    ):
        if reflow.get(field) is not False:
            raise DeferredLossContextHolderReleaseExecutionError(
                "LOSS_CONTEXT_HOLDER_RELEASE_AUTHORITY_INVALID"
            )
    if reflow.get("replacement_entries_modeled") is not False:
        raise DeferredLossContextHolderReleaseExecutionError(
            "loss-context reflow already modeled replacement entries"
        )

    releases = loss_context_release_options_from_payload(reflow)
    expected = reflow.get("candidate_blocked_release_options")
    if not isinstance(expected, int) or isinstance(expected, bool):
        if reflow.get("enabled") is True:
            raise DeferredLossContextHolderReleaseExecutionError(
                "loss-context reflow release count is invalid"
            )
    elif expected != len(releases):
        raise DeferredLossContextHolderReleaseExecutionError(
            "loss-context reflow release count mismatch"
        )

    gate_open = (
        reflow.get("enabled") is True
        and reflow.get("gate_open") is True
        and reflow.get("integrity_clean") is True
        and reflow.get("ready_for_replacement_fill_investigation") is True
    )
    if not gate_open:
        return {
            "candidate_id": freeze.candidate_id,
            "enabled": False,
            "gate_open": False,
            "gate_reason": "causal_capacity_release_not_ready",
            "causal_release_options": len(releases),
            "captured_release_books": 0,
            "missing_release_book_records": len(releases),
            "full_close_release_options": [],
            "exact_full_close_release_options": 0,
            "ready_for_replacement_entry_investigation": False,
            "research_only": True,
            "descriptive_only": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "changes_positions": False,
            "promotion_authority": False,
            "execution_authority": False,
            "replacement_entry_fills_modeled": False,
            "replacement_exits_modeled": False,
            "replacement_pnl_modeled": False,
            "recursive_replacements_modeled": False,
            "deferred_post_handoff_rebuild": True,
            "source_exit_reason": exit_reason,
            "schema_version": 1,
        }

    payload = loss_context_holder_release_execution_summary(
        releases,
        _capacity_release_records(root),
        freeze=freeze,
    )
    payload = dict(payload)
    payload["enabled"] = True
    payload["gate_open"] = True
    payload["deferred_post_handoff_rebuild"] = True
    payload["source_exit_reason"] = exit_reason
    return payload


def write_deferred_loss_context_holder_release_execution(
    state_root: str | Path,
    *,
    output_path: str | Path | None = None,
) -> Path:
    root = Path(state_root)
    target = (
        root / OUTPUT_FILENAME
        if output_path is None
        else Path(output_path)
    )
    payload = rebuild_deferred_loss_context_holder_release_execution(root)
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
