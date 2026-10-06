from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.loss_streak_context_audit import (
    loss_streak_context_audit,
)

OUTPUT_FILENAME = "loss-streak-context-audit-summary.json"


class DeferredLossStreakContextAuditError(RuntimeError):
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
        raise DeferredLossStreakContextAuditError(
            f"{field} is missing or invalid"
        ) from exc
    if not isinstance(raw, dict):
        raise DeferredLossStreakContextAuditError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], raw)


def rebuild_deferred_loss_streak_context_audit(
    state_root: str | Path,
) -> dict[str, object]:
    root = Path(state_root)
    session = _load_object(root / "session-summary.json", "session summary")
    if session.get("exit_reason") != "upgrade_requested":
        raise DeferredLossStreakContextAuditError(
            "deferred rebuild requires an upgrade-requested handoff"
        )

    journal_path = root / "journal.sqlite3"
    facts_path = root / "facts.sqlite3"
    for path, field in (
        (journal_path, "journal store"),
        (facts_path, "evaluation fact store"),
    ):
        if not path.is_file() or path.stat().st_size <= 0:
            raise DeferredLossStreakContextAuditError(
                f"{field} is missing"
            )

    journal = JournalStore(journal_path)
    facts = EvaluationFactStore(facts_path)
    features = LearningFeatureSnapshotStore(root / "learning-features")
    ranks = ContinuousPaperOpeningRankStore(root / "opening-ranks")
    try:
        payload = loss_streak_context_audit(
            tuple(journal.iter_trades()),
            facts,
            features,
            ranks,
        )
    finally:
        facts.close()
        journal.close()

    output = dict(payload)
    for field in (
        "execution_authority",
        "promotion_authority",
        "changes_strategy",
        "changes_risk_limits",
    ):
        if output.get(field) is not False:
            raise DeferredLossStreakContextAuditError(
                f"loss-streak audit gained authority: {field}"
            )
    output["deferred_post_handoff_rebuild"] = True
    output["source_exit_reason"] = "upgrade_requested"
    output["error"] = None
    return output


def write_deferred_loss_streak_context_audit(
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
    payload = rebuild_deferred_loss_streak_context_audit(root)
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
