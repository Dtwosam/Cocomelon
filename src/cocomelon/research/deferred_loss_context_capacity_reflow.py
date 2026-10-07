from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import cast

from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineageStore,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.loss_context_candidate import (
    verify_loss_context_candidate_freeze,
)
from cocomelon.research.loss_context_capacity_reflow import (
    loss_context_capacity_reflow,
)

OUTPUT_FILENAME = "loss-context-capacity-reflow-summary.json"
FREEZE_FILENAME = "loss-context-candidate-freeze.json"
READINESS_FILENAME = "loss-context-account-readiness-report.json"
ALLOWED_SESSION_EXITS = frozenset({"duration_elapsed", "upgrade_requested"})


class DeferredLossContextCapacityReflowError(RuntimeError):
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
        raise DeferredLossContextCapacityReflowError(
            f"{field} is missing or invalid"
        ) from exc
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) for key in raw
    ):
        raise DeferredLossContextCapacityReflowError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], raw)


def _require_file(path: Path, field: str) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise DeferredLossContextCapacityReflowError(
            f"{field} is missing"
        )


def _readiness_gate_open(
    readiness: dict[str, object],
    *,
    candidate_id: str,
) -> bool:
    if readiness.get("candidate_id") != candidate_id:
        raise DeferredLossContextCapacityReflowError(
            "LOSS_CONTEXT_REFLOW_CANDIDATE_MISMATCH"
        )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "promotion_authority",
        "execution_authority",
    ):
        if readiness.get(field) is not False:
            raise DeferredLossContextCapacityReflowError(
                "LOSS_CONTEXT_REFLOW_AUTHORITY_INVALID"
            )
    if readiness.get("capacity_reflow_modeled") is not False:
        raise DeferredLossContextCapacityReflowError(
            "LOSS_CONTEXT_REFLOW_ALREADY_MODELED"
        )
    if (
        readiness.get("capacity_reflow_required_before_strategy_use")
        is not True
    ):
        raise DeferredLossContextCapacityReflowError(
            "LOSS_CONTEXT_REFLOW_REQUIREMENT_MISSING"
        )
    return readiness.get(
        "ready_for_capacity_reflow_investigation"
    ) is True


def rebuild_deferred_loss_context_capacity_reflow(
    state_root: str | Path,
) -> dict[str, object]:
    root = Path(state_root)
    session = _load_object(root / "session-summary.json", "session summary")
    exit_reason = session.get("exit_reason")
    if exit_reason not in ALLOWED_SESSION_EXITS:
        raise DeferredLossContextCapacityReflowError(
            "loss-context reflow requires a clean paper handoff"
        )

    freeze_path = root / FREEZE_FILENAME
    readiness_path = root / READINESS_FILENAME
    _require_file(freeze_path, "loss-context freeze")
    _require_file(readiness_path, "loss-context account readiness")
    freeze = verify_loss_context_candidate_freeze(freeze_path)
    readiness = _load_object(
        readiness_path,
        "loss-context account readiness",
    )

    gate_open = _readiness_gate_open(
        readiness,
        candidate_id=freeze.candidate_id,
    )
    if not gate_open:
        return {
            "candidate_id": freeze.candidate_id,
            "enabled": False,
            "gate_open": False,
            "gate_reason": "fixed_schedule_account_readiness_not_met",
            "release_options": [],
            "research_only": True,
            "descriptive_only": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "promotion_authority": False,
            "execution_authority": False,
            "replacement_entries_modeled": False,
            "replacement_exits_modeled": False,
            "replacement_pnl_modeled": False,
            "deferred_post_handoff_rebuild": True,
            "source_exit_reason": exit_reason,
            "schema_version": 1,
        }

    journal_path = root / "journal.sqlite3"
    facts_path = root / "facts.sqlite3"
    _require_file(journal_path, "journal store")
    _require_file(facts_path, "evaluation fact store")
    for path, field in (
        (root / "opening-opportunities", "opening opportunity store"),
        (root / "opening-lineage", "opening lineage store"),
        (root / "opening-ranks", "opening rank store"),
        (root / "learning-features", "learning feature store"),
    ):
        if not path.is_dir():
            raise DeferredLossContextCapacityReflowError(
                f"{field} is missing"
            )

    opportunities = ContinuousPaperOpeningOpportunityStore(
        root / "opening-opportunities"
    )
    lineages = ContinuousPaperOpeningLineageStore(
        root / "opening-lineage"
    )
    ranks = ContinuousPaperOpeningRankStore(root / "opening-ranks")
    features = LearningFeatureSnapshotStore(root / "learning-features")
    journal = JournalStore(journal_path)
    facts = EvaluationFactStore(facts_path)
    try:
        evaluation = loss_context_capacity_reflow(
            opportunities.iter_records(),
            lineages.iter_records(),
            tuple(journal.iter_trades()),
            features,
            facts,
            ranks,
            freeze=freeze,
            account_readiness=readiness,
        )
    finally:
        facts.close()
        journal.close()

    payload = dict(evaluation.summary)
    payload["release_options"] = [
        asdict(item) for item in evaluation.releases
    ]
    payload["deferred_post_handoff_rebuild"] = True
    payload["source_exit_reason"] = exit_reason
    return payload


def write_deferred_loss_context_capacity_reflow(
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
    payload = rebuild_deferred_loss_context_capacity_reflow(root)
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
