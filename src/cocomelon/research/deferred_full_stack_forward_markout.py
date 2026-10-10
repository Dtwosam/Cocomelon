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
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    DEFAULT_MAX_COMPLETION_LAG_MS,
    DEFAULT_MAX_PATH_AGE_MS,
    ContinuousPaperOpeningOpportunityPathStore,
)
from cocomelon.research.first_seen_opening_witness import (
    first_seen_opening_witness_summary,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.opportunity_inventory_witness import (
    OpportunityInventoryWitnessStore,
    original_inventory_overlap_audit,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.research.prospective_full_stack_forward_markout import (
    prospective_full_stack_forward_markout_summary,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterState,
)

OUTPUT_FILENAME = "prospective-full-stack-forward-markout-summary.json"
COMBINED_STATE_FILENAME = "prospective-top10-no-long-trend-state.json"
TWO_STRIKE_STATE_FILENAME = "prospective-two-strike-stop-filter-state.json"
MOMENTUM_STATE_FILENAME = "prospective-momentum-band-entry-state.json"


class DeferredFullStackForwardMarkoutError(RuntimeError):
    pass


def _load_object(path: Path, field: str) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeferredFullStackForwardMarkoutError(
            f"{field} is missing or invalid"
        ) from exc
    if not isinstance(raw, dict):
        raise DeferredFullStackForwardMarkoutError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], raw)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def rebuild_deferred_full_stack_forward_markout(
    state_root: str | Path,
) -> dict[str, object]:
    root = Path(state_root)
    session = _load_object(root / "session-summary.json", "session summary")
    if session.get("exit_reason") != "upgrade_requested":
        raise DeferredFullStackForwardMarkoutError(
            "deferred rebuild requires an upgrade-requested handoff"
        )

    combined_state = ProspectiveCombinedEntryFilterState.from_payload(
        _load_object(
            root / COMBINED_STATE_FILENAME,
            "combined entry-filter state",
        )
    )
    two_strike_state = ProspectiveTwoStrikeStopFilterState.from_payload(
        _load_object(
            root / TWO_STRIKE_STATE_FILENAME,
            "two-strike state",
        )
    )
    momentum_state = ProspectiveMomentumBandEntryState.from_payload(
        _load_object(
            root / MOMENTUM_STATE_FILENAME,
            "momentum-band state",
        )
    )

    opportunity_store = ContinuousPaperOpeningOpportunityStore(
        root / "opening-opportunities"
    )
    path_store = ContinuousPaperOpeningOpportunityPathStore(
        root / "opening-opportunity-paths",
        max_path_age_ms=DEFAULT_MAX_PATH_AGE_MS,
        max_completion_lag_ms=DEFAULT_MAX_COMPLETION_LAG_MS,
    )
    feature_store = LearningFeatureSnapshotStore(root / "learning-features")
    lineage_store = ContinuousPaperOpeningLineageStore(root / "opening-lineage")
    inventory_store = OpportunityInventoryWitnessStore(
        root / "opening-opportunity-inventory"
    )
    journal = JournalStore(root / "journal.sqlite3")
    try:
        opportunities = opportunity_store.iter_records()
        closed_trades = tuple(journal.iter_trades())
        payload = prospective_full_stack_forward_markout_summary(
            opportunities,
            path_store.iter_paths(),
            closed_trades,
            feature_store,
            combined_state,
            two_strike_state,
            momentum_state,
        )
        overlap_start = max(
            combined_state.started_at_ms,
            two_strike_state.started_at_ms,
            momentum_state.started_at_ms,
        )
        witness = first_seen_opening_witness_summary(
            opportunities,
            closed_trades,
            lineage_store.iter_records(),
            overlap_started_at_ms=overlap_start,
        )
        inventory_witness = original_inventory_overlap_audit(
            opportunities,
            closed_trades,
            inventory_store.iter_records(),
            overlap_started_at_ms=overlap_start,
        )
    finally:
        journal.close()

    output = dict(payload)
    output["first_seen_opening_witness"] = witness
    output["original_open_inventory_witness"] = inventory_witness
    rows = output.get("risk_rejected_rows")
    evaluated = output.get("risk_rejected_stack_evaluated")
    integrity = output.get("risk_rejected_integrity_clean")
    if (
        not isinstance(rows, list)
        or isinstance(evaluated, bool)
        or not isinstance(evaluated, int)
        or evaluated != len(rows)
        or not isinstance(integrity, bool)
    ):
        raise DeferredFullStackForwardMarkoutError(
            "rebuilt summary is missing current risk-rejected evidence"
        )
    if output.get("execution_authority") is not False:
        raise DeferredFullStackForwardMarkoutError(
            "rebuilt summary gained execution authority"
        )
    if output.get("promotion_authority") is not False:
        raise DeferredFullStackForwardMarkoutError(
            "rebuilt summary gained promotion authority"
        )
    output["enabled"] = True
    output["error"] = None
    output["deferred_post_handoff_rebuild"] = True
    output["source_exit_reason"] = "upgrade_requested"
    return output


def write_deferred_full_stack_forward_markout(
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
    payload = rebuild_deferred_full_stack_forward_markout(root)
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
