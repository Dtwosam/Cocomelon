from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    DEFAULT_MAX_COMPLETION_LAG_MS,
    DEFAULT_MAX_PATH_AGE_MS,
    ContinuousPaperOpeningOpportunityPathStore,
)
from cocomelon.research.prospective_consecutive_loss_cooldown_shadow import (
    CANDIDATE_ID,
    ProspectiveConsecutiveLossCooldownShadowState,
    prospective_consecutive_loss_cooldown_shadow_summary,
)

OUTPUT_FILENAME = "prospective-consecutive-loss-cooldown-shadow-summary.json"
STATE_FILENAME = "prospective-consecutive-loss-cooldown-shadow-state.json"


class DeferredConsecutiveLossCooldownError(RuntimeError):
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
        raise DeferredConsecutiveLossCooldownError(
            f"{field} is missing or invalid"
        ) from exc
    if not isinstance(raw, dict):
        raise DeferredConsecutiveLossCooldownError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], raw)


def rebuild_deferred_consecutive_loss_cooldown(
    state_root: str | Path,
) -> dict[str, object]:
    root = Path(state_root)
    session = _load_object(root / "session-summary.json", "session summary")
    if session.get("exit_reason") != "upgrade_requested":
        raise DeferredConsecutiveLossCooldownError(
            "deferred rebuild requires an upgrade-requested handoff"
        )

    state = ProspectiveConsecutiveLossCooldownShadowState.from_payload(
        _load_object(root / STATE_FILENAME, "cooldown shadow state")
    )
    opportunity_store = ContinuousPaperOpeningOpportunityStore(
        root / "opening-opportunities"
    )
    path_store = ContinuousPaperOpeningOpportunityPathStore(
        root / "opening-opportunity-paths",
        max_path_age_ms=DEFAULT_MAX_PATH_AGE_MS,
        max_completion_lag_ms=DEFAULT_MAX_COMPLETION_LAG_MS,
    )
    payload = prospective_consecutive_loss_cooldown_shadow_summary(
        opportunity_store.iter_records(),
        path_store.iter_paths(),
        state,
        BaselineReplayConfig().execution,
    )
    output = dict(payload)
    if output.get("candidate_id") != CANDIDATE_ID:
        raise DeferredConsecutiveLossCooldownError(
            "rebuilt cooldown summary candidate drift"
        )
    if output.get("execution_authority") is not False:
        raise DeferredConsecutiveLossCooldownError(
            "rebuilt cooldown summary gained execution authority"
        )
    if output.get("promotion_authority") is not False:
        raise DeferredConsecutiveLossCooldownError(
            "rebuilt cooldown summary gained promotion authority"
        )
    if output.get("changes_risk_limits") is not False:
        raise DeferredConsecutiveLossCooldownError(
            "rebuilt cooldown summary changed risk authority"
        )
    option_results = output.get("option_results")
    if not isinstance(option_results, list):
        raise DeferredConsecutiveLossCooldownError(
            "rebuilt cooldown summary is missing option results"
        )
    output["deferred_post_handoff_rebuild"] = True
    output["source_exit_reason"] = "upgrade_requested"
    output["error"] = None
    return output


def write_deferred_consecutive_loss_cooldown(
    state_root: str | Path,
    *,
    output_path: str | Path | None = None,
) -> Path:
    root = Path(state_root)
    target = root / OUTPUT_FILENAME if output_path is None else Path(output_path)
    payload = rebuild_deferred_consecutive_loss_cooldown(root)
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
