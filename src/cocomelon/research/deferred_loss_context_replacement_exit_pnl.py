from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    ContinuousPaperOpeningOpportunityExitBookStore,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ContinuousPaperReplacementFundingStore,
)
from cocomelon.research.loss_context_candidate import (
    verify_loss_context_candidate_freeze,
)
from cocomelon.research.loss_context_replacement_exit_pnl import (
    loss_context_replacement_exit_pnl_summary,
)

OUTPUT_FILENAME = "loss-context-replacement-exit-pnl-summary.json"
FREEZE_FILENAME = "loss-context-candidate-freeze.json"
ENTRY_FILENAME = "loss-context-replacement-entry-fill-summary.json"
ALLOWED_SESSION_EXITS = frozenset({"duration_elapsed", "upgrade_requested"})


class DeferredLossContextReplacementExitPnlError(RuntimeError):
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
        raise DeferredLossContextReplacementExitPnlError(
            f"{field} is missing or invalid"
        ) from exc
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) for key in raw
    ):
        raise DeferredLossContextReplacementExitPnlError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], raw)


def _integer(
    payload: dict[str, object],
    field: str,
) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DeferredLossContextReplacementExitPnlError(
            f"{field} must be a non-negative integer"
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
        raise DeferredLossContextReplacementExitPnlError(
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


def _validate_entry_gate(
    entry: dict[str, object],
    *,
    candidate_id: str,
) -> bool:
    if entry.get("candidate_id") != candidate_id:
        raise DeferredLossContextReplacementExitPnlError(
            "LOSS_CONTEXT_EXIT_CANDIDATE_MISMATCH"
        )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "changes_positions",
        "promotion_authority",
        "execution_authority",
    ):
        if entry.get(field) is not False:
            raise DeferredLossContextReplacementExitPnlError(
                "LOSS_CONTEXT_EXIT_AUTHORITY_INVALID"
            )
    if entry.get("replacement_entry_fills_modeled") is not True:
        return False
    if entry.get("replacement_exits_modeled") is not False:
        raise DeferredLossContextReplacementExitPnlError(
            "LOSS_CONTEXT_EXIT_ALREADY_MODELED"
        )
    if entry.get("replacement_pnl_modeled") is not False:
        raise DeferredLossContextReplacementExitPnlError(
            "LOSS_CONTEXT_EXIT_PNL_ALREADY_MODELED"
        )
    return (
        entry.get("enabled") is True
        and entry.get("gate_open") is True
        and entry.get("ready_for_replacement_exit_investigation") is True
    )


def rebuild_deferred_loss_context_replacement_exit_pnl(
    state_root: str | Path,
) -> dict[str, object]:
    root = Path(state_root)
    session = _load_object(root / "session-summary.json", "session summary")
    exit_reason = session.get("exit_reason")
    if exit_reason not in ALLOWED_SESSION_EXITS:
        raise DeferredLossContextReplacementExitPnlError(
            "loss-context replacement exit requires a clean paper handoff"
        )

    freeze_path = root / FREEZE_FILENAME
    entry_path = root / ENTRY_FILENAME
    if not freeze_path.is_file() or freeze_path.stat().st_size <= 0:
        raise DeferredLossContextReplacementExitPnlError(
            "loss-context freeze is missing"
        )
    if not entry_path.is_file() or entry_path.stat().st_size <= 0:
        raise DeferredLossContextReplacementExitPnlError(
            "loss-context replacement entry evidence is missing"
        )

    freeze = verify_loss_context_candidate_freeze(freeze_path)
    entry = _load_object(
        entry_path,
        "loss-context replacement entry evidence",
    )
    gate_open = _validate_entry_gate(
        entry,
        candidate_id=freeze.candidate_id,
    )
    if not gate_open:
        return {
            "candidate_id": freeze.candidate_id,
            "enabled": False,
            "gate_open": False,
            "gate_reason": "replacement_entry_fill_not_ready",
            "horizons_ms": [],
            "horizon_reviews": {},
            "all_horizons_complete": False,
            "all_horizons_positive": False,
            "ready_for_portfolio_counterfactual_investigation": False,
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

    try:
        exit_books = _open_exit_book_store(root)
        funding = _open_funding_store(root)
    except DeferredLossContextReplacementExitPnlError as exc:
        return {
            "candidate_id": freeze.candidate_id,
            "enabled": False,
            "gate_open": True,
            "gate_reason": "exit_or_funding_capture_unavailable",
            "error": f"{type(exc).__name__}: {exc}",
            "horizons_ms": [],
            "horizon_reviews": {},
            "all_horizons_complete": False,
            "all_horizons_positive": False,
            "ready_for_portfolio_counterfactual_investigation": False,
            "research_only": True,
            "descriptive_only": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "changes_positions": False,
            "promotion_authority": False,
            "execution_authority": False,
            "replacement_entry_fills_modeled": True,
            "replacement_exits_modeled": False,
            "replacement_pnl_modeled": False,
            "recursive_replacements_modeled": False,
            "deferred_post_handoff_rebuild": True,
            "source_exit_reason": exit_reason,
            "schema_version": 1,
        }

    payload = loss_context_replacement_exit_pnl_summary(
        entry,
        exit_books.iter_records(),
        funding.iter_records(),
        freeze=freeze,
        config=BaselineReplayConfig().execution,
        horizons_ms=exit_books.horizons_ms,
    )
    payload = dict(payload)
    payload["enabled"] = True
    payload["gate_open"] = True
    payload["deferred_post_handoff_rebuild"] = True
    payload["source_exit_reason"] = exit_reason
    return payload


def write_deferred_loss_context_replacement_exit_pnl(
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
    payload = rebuild_deferred_loss_context_replacement_exit_pnl(
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
