from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.execution.store import PaperExecutionStore
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.deferred_loss_context_holder_release_execution import (
    loss_context_release_options_from_payload,
)
from cocomelon.research.loss_context_candidate import (
    verify_loss_context_candidate_freeze,
)
from cocomelon.research.loss_context_replacement_entry_fill import (
    loss_context_replacement_entry_fill_summary,
)

OUTPUT_FILENAME = "loss-context-replacement-entry-fill-summary.json"
FREEZE_FILENAME = "loss-context-candidate-freeze.json"
REFLOW_FILENAME = "loss-context-capacity-reflow-summary.json"
HOLDER_FILENAME = "loss-context-holder-release-execution-summary.json"
ALLOWED_SESSION_EXITS = frozenset({"duration_elapsed", "upgrade_requested"})


class DeferredLossContextReplacementEntryFillError(RuntimeError):
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
        raise DeferredLossContextReplacementEntryFillError(
            f"{field} is missing or invalid"
        ) from exc
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) for key in raw
    ):
        raise DeferredLossContextReplacementEntryFillError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], raw)


def _require_file(path: Path, field: str) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise DeferredLossContextReplacementEntryFillError(
            f"{field} is missing"
        )


def _validate_holder_gate(
    holder: dict[str, object],
    *,
    candidate_id: str,
) -> bool:
    if holder.get("candidate_id") != candidate_id:
        raise DeferredLossContextReplacementEntryFillError(
            "LOSS_CONTEXT_ENTRY_CANDIDATE_MISMATCH"
        )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "changes_positions",
        "promotion_authority",
        "execution_authority",
    ):
        if holder.get(field) is not False:
            raise DeferredLossContextReplacementEntryFillError(
                "LOSS_CONTEXT_ENTRY_AUTHORITY_INVALID"
            )
    if holder.get("replacement_entry_fills_modeled") is not False:
        raise DeferredLossContextReplacementEntryFillError(
            "LOSS_CONTEXT_ENTRY_ALREADY_MODELED"
        )
    return (
        holder.get("enabled") is True
        and holder.get("gate_open") is True
        and holder.get("ready_for_replacement_entry_investigation") is True
    )


def rebuild_deferred_loss_context_replacement_entry_fill(
    state_root: str | Path,
) -> dict[str, object]:
    root = Path(state_root)
    session = _load_object(root / "session-summary.json", "session summary")
    exit_reason = session.get("exit_reason")
    if exit_reason not in ALLOWED_SESSION_EXITS:
        raise DeferredLossContextReplacementEntryFillError(
            "loss-context replacement entry requires a clean paper handoff"
        )

    freeze_path = root / FREEZE_FILENAME
    reflow_path = root / REFLOW_FILENAME
    holder_path = root / HOLDER_FILENAME
    for path, field in (
        (freeze_path, "loss-context freeze"),
        (reflow_path, "loss-context capacity reflow"),
        (holder_path, "loss-context holder release execution"),
        (root / "paper.sqlite3", "paper execution store"),
    ):
        _require_file(path, field)
    if not (root / "opening-opportunities").is_dir():
        raise DeferredLossContextReplacementEntryFillError(
            "opening opportunity store is missing"
        )

    freeze = verify_loss_context_candidate_freeze(freeze_path)
    reflow = _load_object(
        reflow_path,
        "loss-context capacity reflow",
    )
    holder = _load_object(
        holder_path,
        "loss-context holder release execution",
    )
    if reflow.get("candidate_id") != freeze.candidate_id:
        raise DeferredLossContextReplacementEntryFillError(
            "LOSS_CONTEXT_ENTRY_REFLOW_CANDIDATE_MISMATCH"
        )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "promotion_authority",
        "execution_authority",
    ):
        if reflow.get(field) is not False:
            raise DeferredLossContextReplacementEntryFillError(
                "LOSS_CONTEXT_ENTRY_REFLOW_AUTHORITY_INVALID"
            )

    releases = loss_context_release_options_from_payload(reflow)
    gate_open = _validate_holder_gate(
        holder,
        candidate_id=freeze.candidate_id,
    )
    if not gate_open:
        return {
            "candidate_id": freeze.candidate_id,
            "enabled": False,
            "gate_open": False,
            "gate_reason": "exact_holder_release_not_ready",
            "holder_full_close_release_options": 0,
            "entry_replayed_options": 0,
            "fillable_options": 0,
            "fillable_release_option_ids": [],
            "option_results": [],
            "ready_for_replacement_exit_investigation": False,
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

    opportunity_store = ContinuousPaperOpeningOpportunityStore(
        root / "opening-opportunities"
    )
    paper = PaperExecutionStore(root / "paper.sqlite3")
    try:
        payload = loss_context_replacement_entry_fill_summary(
            opportunity_store.iter_records(),
            releases,
            holder,
            freeze=freeze,
            config=BaselineReplayConfig().execution,
            position_history_loader=(
                lambda plan_id, through_ms: paper.load_position_history(
                    plan_id,
                    through_ms=through_ms,
                )
            ),
        )
    finally:
        paper.close()

    payload = dict(payload)
    payload["enabled"] = True
    payload["gate_open"] = True
    payload["deferred_post_handoff_rebuild"] = True
    payload["source_exit_reason"] = exit_reason
    return payload


def write_deferred_loss_context_replacement_entry_fill(
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
    payload = rebuild_deferred_loss_context_replacement_entry_fill(
        state_root
    )
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
