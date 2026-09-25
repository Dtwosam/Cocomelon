from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from cocomelon.research.learning_cycle import MIN_TRAIN_ROWS, VALIDATION_ROWS


class LearningDashboardError(RuntimeError):
    pass


def _mapping(path: Path, field: str) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LearningDashboardError(f"{field.upper()}_MISSING") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningDashboardError(f"{field.upper()}_INVALID") from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise LearningDashboardError(f"{field.upper()}_INVALID")
    return cast(dict[str, object], raw)


def _integer(payload: dict[str, object], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningDashboardError(f"{field.upper()}_INVALID")
    return value


def _positive_integer(payload: dict[str, object], field: str) -> int:
    value = _integer(payload, field)
    if value <= 0:
        raise LearningDashboardError(f"{field.upper()}_INVALID")
    return value


def _boolean(payload: dict[str, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise LearningDashboardError(f"{field.upper()}_INVALID")
    return value


def _string(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise LearningDashboardError(f"{field.upper()}_INVALID")
    return value


def _sha256(payload: dict[str, object], field: str) -> str:
    value = _string(payload, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise LearningDashboardError(f"{field.upper()}_INVALID")
    return value


def _authority(payload: dict[str, object], field: str) -> None:
    if _boolean(payload, "research_only") is not True:
        raise LearningDashboardError(f"{field.upper()}_RESEARCH_AUTHORITY_INVALID")
    if _boolean(payload, "promotion_eligible") is not False:
        raise LearningDashboardError("PROMOTION_AUTHORITY_FORBIDDEN")
    if _boolean(payload, "execution_ready") is not False:
        raise LearningDashboardError("EXECUTION_AUTHORITY_FORBIDDEN")


def _cycle_state(
    *,
    cycle_status: str,
    structurally_ready: bool,
    train_shortfall: int,
    validation_shortfall: int,
) -> str:
    if cycle_status == "completed":
        return "research_cycle_completed"
    if not structurally_ready:
        return "waiting_for_structural_readiness"
    if train_shortfall > 0 or validation_shortfall > 0:
        return "waiting_for_capacity"
    return "waiting_for_cycle_completion"


def build_learning_operations_status(
    state_root: str | Path,
    *,
    cycle_root: str | Path | None = None,
) -> dict[str, object]:
    state = Path(state_root)
    sync = _mapping(state / "last-sync.json", "last_sync")
    readiness = _mapping(state / "readiness.json", "readiness")

    if sync.get("command") != "research-learning-sync":
        raise LearningDashboardError("LAST_SYNC_COMMAND_INVALID")
    if readiness.get("command") != "learning-readiness":
        raise LearningDashboardError("READINESS_COMMAND_INVALID")
    if readiness.get("evidence_kind") != "paper_execution":
        raise LearningDashboardError("READINESS_EVIDENCE_KIND_INVALID")
    _authority(sync, "last_sync")
    _authority(readiness, "readiness")

    learning_digest = _sha256(sync, "learning_state_digest")
    feature_digest = _sha256(sync, "feature_state_digest")
    if _sha256(readiness, "ledger_state_digest") != learning_digest:
        raise LearningDashboardError("LEARNING_STATE_DIGEST_MISMATCH")
    readiness_feature_digest = _string(readiness, "feature_store_state_digest")
    if readiness_feature_digest != feature_digest:
        raise LearningDashboardError("FEATURE_STATE_DIGEST_MISMATCH")

    learning_record_count = _integer(sync, "learning_record_count")
    feature_snapshot_count = _integer(sync, "feature_snapshot_count")
    eligible_record_count = _integer(readiness, "eligible_record_count")
    quarantined_record_count = _integer(readiness, "quarantined_record_count")
    feature_complete_record_count = _integer(
        readiness,
        "feature_complete_record_count",
    )
    blocked_record_count = _integer(readiness, "blocked_record_count")
    structurally_ready = _boolean(readiness, "structurally_ready")
    upstream_run_id = _positive_integer(sync, "upstream_run_id")
    created_records = _integer(sync, "created_records")
    receipt_id = _sha256(sync, "receipt_id")

    cycle_status = "not_published"
    settled_train_record_count: int | None = None
    validation_record_count: int | None = None
    train_shortfall: int | None = None
    validation_shortfall: int | None = None
    cycle_id: str | None = None

    if cycle_root is not None:
        cycle = _mapping(Path(cycle_root) / "cycle.json", "cycle")
        _authority(cycle, "cycle")
        if _sha256(cycle, "learning_state_digest") != learning_digest:
            raise LearningDashboardError("CYCLE_LEARNING_STATE_DIGEST_MISMATCH")
        if _sha256(cycle, "feature_state_digest") != feature_digest:
            raise LearningDashboardError("CYCLE_FEATURE_STATE_DIGEST_MISMATCH")
        cycle_status = _string(cycle, "status")
        if cycle_status not in {"not_ready", "completed"}:
            raise LearningDashboardError("CYCLE_STATUS_INVALID")
        settled_train_record_count = _integer(
            cycle,
            "settled_train_record_count",
        )
        validation_record_count = _integer(cycle, "validation_record_count")
        train_shortfall = max(0, MIN_TRAIN_ROWS - settled_train_record_count)
        validation_shortfall = max(
            0,
            VALIDATION_ROWS - validation_record_count,
        )
        cycle_id = _sha256(cycle, "cycle_id")
        state_name = _cycle_state(
            cycle_status=cycle_status,
            structurally_ready=structurally_ready,
            train_shortfall=train_shortfall,
            validation_shortfall=validation_shortfall,
        )
    elif learning_record_count == 0:
        state_name = "waiting_for_authenticated_evidence"
    else:
        state_name = "waiting_for_cycle"

    return {
        "state": state_name,
        "upstream_run_id": upstream_run_id,
        "created_records_last_sync": created_records,
        "learning_record_count": learning_record_count,
        "feature_snapshot_count": feature_snapshot_count,
        "eligible_record_count": eligible_record_count,
        "quarantined_record_count": quarantined_record_count,
        "feature_complete_record_count": feature_complete_record_count,
        "blocked_record_count": blocked_record_count,
        "structurally_ready": structurally_ready,
        "target_train_records": MIN_TRAIN_ROWS,
        "target_validation_records": VALIDATION_ROWS,
        "cycle_status": cycle_status,
        "settled_train_record_count": settled_train_record_count,
        "validation_record_count": validation_record_count,
        "train_record_shortfall": train_shortfall,
        "validation_record_shortfall": validation_shortfall,
        "learning_state_digest": learning_digest,
        "feature_state_digest": feature_digest,
        "sync_receipt_id": receipt_id,
        "cycle_id": cycle_id,
        "research_only": True,
        "promotion_eligible": False,
        "execution_ready": False,
    }


def render_learning_operations_markdown(status: dict[str, object]) -> str:
    lines = [
        "## Continuous Learning Operations",
        "",
        "**RESEARCH ONLY / NO EXECUTION**",
        "",
        f"- State: `{status['state']}`",
        (
            "- Cumulative authenticated paper records: "
            f"{status['learning_record_count']}"
        ),
        f"- Authenticated feature snapshots: {status['feature_snapshot_count']}",
        f"- Eligible records: {status['eligible_record_count']}",
        f"- Quarantined records: {status['quarantined_record_count']}",
        f"- Feature-complete records: {status['feature_complete_record_count']}",
        f"- Blocked records: {status['blocked_record_count']}",
        (
            "- Structural readiness: "
            + ("ready" if status["structurally_ready"] else "not ready")
        ),
        f"- Latest source campaign run: {status['upstream_run_id']}",
        f"- New records in latest sync: {status['created_records_last_sync']}",
        f"- Autonomous cycle: `{status['cycle_status']}`",
    ]
    settled = status.get("settled_train_record_count")
    validation = status.get("validation_record_count")
    if isinstance(settled, int) and isinstance(validation, int):
        lines.extend(
            [
                (
                    "- Settled chronological train capacity: "
                    f"{settled} / {status['target_train_records']}"
                ),
                (
                    "- Chronological validation capacity: "
                    f"{validation} / {status['target_validation_records']}"
                ),
            ]
        )
    else:
        lines.append(
            "- Chronological capacity: awaiting the next autonomous cycle receipt"
        )
    lines.extend(
        [
            "",
            (
                "This section is operational provenance only. It exposes no "
                "profit/loss or protected prospective-campaign economics and "
                "cannot authorize promotion or execution."
            ),
            "",
        ]
    )
    return "\n".join(lines)
