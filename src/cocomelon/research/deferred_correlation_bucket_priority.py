from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

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
from cocomelon.research.prospective_correlation_bucket_priority import (
    prospective_correlation_bucket_priority_summary,
)

OUTPUT_FILENAME = "prospective-correlation-bucket-priority-summary.json"
FORWARD_MARKOUT_FILENAME = "prospective-full-stack-forward-markout-summary.json"


class DeferredCorrelationBucketPriorityError(RuntimeError):
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
        raise DeferredCorrelationBucketPriorityError(
            f"{field} is missing or invalid"
        ) from exc
    if not isinstance(raw, dict):
        raise DeferredCorrelationBucketPriorityError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], raw)


def rebuild_deferred_correlation_bucket_priority(
    state_root: str | Path,
) -> dict[str, object]:
    root = Path(state_root)
    session = _load_object(root / "session-summary.json", "session summary")
    if session.get("exit_reason") != "upgrade_requested":
        raise DeferredCorrelationBucketPriorityError(
            "deferred rebuild requires an upgrade-requested handoff"
        )

    forward = _load_object(
        root / FORWARD_MARKOUT_FILENAME,
        "full-stack forward markout",
    )
    if forward.get("deferred_post_handoff_rebuild") is not True:
        raise DeferredCorrelationBucketPriorityError(
            "priority audit requires rebuilt post-handoff markouts"
        )

    opportunity_store = ContinuousPaperOpeningOpportunityStore(
        root / "opening-opportunities"
    )
    lineage_store = ContinuousPaperOpeningLineageStore(
        root / "opening-lineage"
    )
    rank_store = ContinuousPaperOpeningRankStore(root / "opening-ranks")
    journal = JournalStore(root / "journal.sqlite3")
    try:
        payload = prospective_correlation_bucket_priority_summary(
            forward,
            opportunity_store.iter_records(),
            lineage_store.iter_records(),
            tuple(journal.iter_trades()),
            rank_loader=rank_store.load,
        )
    finally:
        journal.close()

    output = dict(payload)
    if output.get("execution_authority") is not False:
        raise DeferredCorrelationBucketPriorityError(
            "priority audit gained execution authority"
        )
    if output.get("changes_risk_limits") is not False:
        raise DeferredCorrelationBucketPriorityError(
            "priority audit gained risk-limit authority"
        )
    if output.get("changes_entry_priority") is not False:
        raise DeferredCorrelationBucketPriorityError(
            "priority audit gained entry-priority authority"
        )
    output["deferred_post_handoff_rebuild"] = True
    output["source_exit_reason"] = "upgrade_requested"
    output["error"] = None
    return output


def write_deferred_correlation_bucket_priority(
    state_root: str | Path,
    *,
    output_path: str | Path | None = None,
) -> Path:
    root = Path(state_root)
    target = root / OUTPUT_FILENAME if output_path is None else Path(output_path)
    payload = rebuild_deferred_correlation_bucket_priority(root)
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
