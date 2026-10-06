from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.execution.store import PaperExecutionStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineageStore,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    ContinuousPaperOpeningOpportunityExitBookStore,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ContinuousPaperReplacementFundingStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_capacity_reflow_exit_fill import (
    evaluate_prospective_capacity_reflow_exit_fill,
)
from cocomelon.research.prospective_capacity_reflow_fill_feasibility import (
    prospective_capacity_reflow_fill_feasibility_summary,
)
from cocomelon.research.prospective_capacity_reflow_realized_pnl import (
    evaluate_prospective_capacity_reflow_realized_pnl,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
    evaluate_prospective_combined_entry_filter,
)
from cocomelon.research.prospective_full_stack_capacity_reflow import (
    prospective_full_stack_capacity_reflow,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
    evaluate_prospective_momentum_band_entry,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterState,
    evaluate_prospective_two_strike_stop_filter,
)

OUTPUT_FILENAME = "prospective-full-stack-capacity-reflow-summary.json"
COMBINED_STATE_FILENAME = "prospective-top10-no-long-trend-state.json"
TWO_STRIKE_STATE_FILENAME = "prospective-two-strike-stop-filter-state.json"
MOMENTUM_STATE_FILENAME = "prospective-momentum-band-entry-state.json"


class DeferredFullStackCapacityReflowError(RuntimeError):
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
        raise DeferredFullStackCapacityReflowError(
            f"{field} is missing or invalid"
        ) from exc
    if not isinstance(raw, dict):
        raise DeferredFullStackCapacityReflowError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], raw)


def _integer(raw: dict[str, object], field: str) -> int:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DeferredFullStackCapacityReflowError(
            f"{field} must be an integer"
        )
    return value


def _open_exit_book_store(
    root: Path,
) -> ContinuousPaperOpeningOpportunityExitBookStore:
    store_root = root / "opening-opportunity-exit-books"
    protocol = _load_object(
        store_root / "protocol.json",
        "exit-book capture protocol",
    )
    horizons_raw = protocol.get("horizons_ms")
    if (
        not isinstance(horizons_raw, list)
        or not horizons_raw
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in horizons_raw
        )
    ):
        raise DeferredFullStackCapacityReflowError(
            "exit-book horizons are invalid"
        )
    return ContinuousPaperOpeningOpportunityExitBookStore(
        store_root,
        capture_started_at_ms=_integer(
            protocol,
            "capture_started_at_ms",
        ),
        horizons_ms=tuple(cast(list[int], horizons_raw)),
        max_capture_lag_ms=_integer(
            protocol,
            "max_capture_lag_ms",
        ),
    )


def _open_funding_store(
    root: Path,
) -> ContinuousPaperReplacementFundingStore:
    store_root = root / "replacement-funding-boundaries"
    protocol = _load_object(
        store_root / "protocol.json",
        "replacement-funding capture protocol",
    )
    return ContinuousPaperReplacementFundingStore(
        store_root,
        capture_started_at_ms=_integer(
            protocol,
            "capture_started_at_ms",
        ),
        max_window_ms=_integer(protocol, "max_window_ms"),
        max_oracle_age_ms=_integer(
            protocol,
            "max_oracle_age_ms",
        ),
        max_funding_capture_lag_ms=_integer(
            protocol,
            "max_funding_capture_lag_ms",
        ),
    )


def _disabled_fill(exc: Exception) -> dict[str, object]:
    return {
        "enabled": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "replacement_entry_fills_modeled": False,
        "error": f"{type(exc).__name__}: {exc}",
    }


def _disabled_exit(error: str) -> dict[str, object]:
    return {
        "enabled": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "replacement_exit_fills_modeled": False,
        "error": error,
    }


def _disabled_pnl(error: str) -> dict[str, object]:
    return {
        "enabled": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "strategy_level_realized_pnl_claimed": False,
        "error": error,
    }


def _require_authority_negative(
    payload: dict[str, object],
    *,
    field: str,
) -> None:
    if payload.get("execution_authority") is not False:
        raise DeferredFullStackCapacityReflowError(
            f"{field} gained execution authority"
        )
    if payload.get("promotion_authority") is not False:
        raise DeferredFullStackCapacityReflowError(
            f"{field} gained promotion authority"
        )


def rebuild_deferred_full_stack_capacity_reflow(
    state_root: str | Path,
) -> dict[str, object]:
    root = Path(state_root)
    session = _load_object(root / "session-summary.json", "session summary")
    if session.get("exit_reason") != "upgrade_requested":
        raise DeferredFullStackCapacityReflowError(
            "deferred rebuild requires an upgrade-requested handoff"
        )

    paper_path = root / "paper.sqlite3"
    facts_path = root / "facts.sqlite3"
    journal_path = root / "journal.sqlite3"
    for path, field in (
        (paper_path, "paper execution store"),
        (facts_path, "evaluation fact store"),
        (journal_path, "journal store"),
    ):
        if not path.is_file() or path.stat().st_size <= 0:
            raise DeferredFullStackCapacityReflowError(
                f"{field} is missing"
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

    config = BaselineReplayConfig().execution
    opportunity_store = ContinuousPaperOpeningOpportunityStore(
        root / "opening-opportunities"
    )
    lineage_store = ContinuousPaperOpeningLineageStore(
        root / "opening-lineage"
    )
    rank_store = ContinuousPaperOpeningRankStore(
        root / "opening-ranks"
    )
    feature_store = LearningFeatureSnapshotStore(
        root / "learning-features"
    )
    exit_book_store = _open_exit_book_store(root)
    funding_store = _open_funding_store(root)
    journal = JournalStore(journal_path)
    facts = EvaluationFactStore(facts_path)
    paper = PaperExecutionStore(paper_path)

    try:
        combined_summary = evaluate_prospective_combined_entry_filter(
            journal,
            facts,
            rank_store,
            combined_state,
        )
        two_strike_summary = evaluate_prospective_two_strike_stop_filter(
            journal,
            two_strike_state,
        )
        momentum_summary = evaluate_prospective_momentum_band_entry(
            journal,
            feature_store,
            momentum_state,
        )

        opportunities = opportunity_store.iter_records()
        evaluation = prospective_full_stack_capacity_reflow(
            opportunities,
            lineage_store.iter_records(),
            tuple(journal.iter_trades()),
            feature_store,
            combined_state,
            two_strike_state,
            momentum_state,
            combined_summary,
            two_strike_summary,
            momentum_summary,
        )

        history_requests = tuple(
            (
                release.release_opening_plan_id,
                release.opportunity_timestamp_ms,
            )
            for release in evaluation.releases
        )
        position_histories = paper.load_position_histories(
            history_requests
        )

        try:
            fill = prospective_capacity_reflow_fill_feasibility_summary(
                opportunities,
                evaluation.releases,
                config,
                position_history_loader=(
                    lambda plan_id, through_ms: position_histories[
                        (plan_id, through_ms)
                    ]
                ),
            )
        except Exception as exc:
            fill = _disabled_fill(exc)
        else:
            fill = dict(fill)
            fill["enabled"] = True
            fill["error"] = None

        if fill.get("enabled") is True:
            try:
                exit_fill = (
                    evaluate_prospective_capacity_reflow_exit_fill(
                        fill,
                        exit_book_store,
                        config,
                    )
                )
            except Exception as exc:
                exit_fill = _disabled_exit(
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                exit_fill = dict(exit_fill)
                exit_fill["enabled"] = True
                exit_fill["error"] = None
        else:
            exit_fill = _disabled_exit(
                "replacement entry fill evidence unavailable"
            )

        if exit_fill.get("enabled") is True:
            try:
                realized_pnl = (
                    evaluate_prospective_capacity_reflow_realized_pnl(
                        exit_fill,
                        funding_store,
                    )
                )
            except Exception as exc:
                realized_pnl = _disabled_pnl(
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                realized_pnl = dict(realized_pnl)
                realized_pnl["enabled"] = True
                realized_pnl["error"] = None
        else:
            realized_pnl = _disabled_pnl(
                "replacement exit-fill evidence unavailable"
            )

        payload = dict(evaluation.summary)
        payload["enabled"] = True
        payload["fill_feasibility"] = fill
        payload["exit_fill"] = exit_fill
        payload["realized_pnl"] = realized_pnl
        payload["replacement_entries_modeled"] = (
            fill.get("enabled") is True
        )
        payload["replacement_exits_modeled"] = (
            exit_fill.get("enabled") is True
        )
        payload["pnl_modeled"] = (
            realized_pnl.get("enabled") is True
        )
        payload["exact_realized_pnl_available"] = (
            realized_pnl.get("exact_realized_pnl_available") is True
        )
        payload["cross_horizon_economics_aggregated"] = False
        payload["strategy_level_realized_pnl_claimed"] = False
        payload["error"] = None
        payload["deferred_post_handoff_rebuild"] = True
        payload["source_exit_reason"] = "upgrade_requested"

        _require_authority_negative(payload, field="capacity reflow")
        _require_authority_negative(fill, field="replacement entry fill")
        _require_authority_negative(exit_fill, field="replacement exit fill")
        _require_authority_negative(realized_pnl, field="realized PnL")
        if payload.get("strategy_level_realized_pnl_claimed") is not False:
            raise DeferredFullStackCapacityReflowError(
                "capacity reflow claimed strategy-level realized PnL"
            )
        return payload
    finally:
        paper.close()
        facts.close()
        journal.close()


def write_deferred_full_stack_capacity_reflow(
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
    payload = rebuild_deferred_full_stack_capacity_reflow(root)
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
