from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from cocomelon.research.loss_context_candidate import (
    verify_loss_context_candidate_freeze,
)
from cocomelon.research.loss_context_portfolio_composition import (
    LOSS_CONTEXT_PORTFOLIO_COMPOSITION_SCHEMA_VERSION,
    loss_context_portfolio_composition_summary,
)

OUTPUT_FILENAME = "loss-context-portfolio-composition-summary.json"
FREEZE_FILENAME = "loss-context-candidate-freeze.json"
ACCOUNT_FILENAME = "loss-context-account-readiness-report.json"
ENTRY_FILENAME = "loss-context-replacement-entry-fill-summary.json"
EXIT_FILENAME = "loss-context-replacement-exit-pnl-summary.json"
ALLOWED_SESSION_EXITS = frozenset({"duration_elapsed", "upgrade_requested"})


class DeferredLossContextPortfolioCompositionError(RuntimeError):
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
        raise DeferredLossContextPortfolioCompositionError(
            f"{field} is missing or invalid"
        ) from exc
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) for key in raw
    ):
        raise DeferredLossContextPortfolioCompositionError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], raw)


def _closed_payload(
    *,
    candidate_id: str,
    reason: str,
    source_exit_reason: str,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "enabled": False,
        "gate_open": False,
        "gate_reason": reason,
        "horizons_ms": [],
        "horizon_summaries": {},
        "all_horizons_structurally_composable": False,
        "horizon_selection_performed": False,
        "cross_horizon_economics_aggregated": False,
        "independent_paths_summed_only_for_diagnostics": True,
        "chronological_account_state_replayed": False,
        "recursive_replacements_modeled": False,
        "portfolio_counterfactual_complete": False,
        "strategy_level_realized_pnl_claimed": False,
        "ready_for_chronological_portfolio_replay": False,
        "research_only": True,
        "descriptive_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
        "deferred_post_handoff_rebuild": True,
        "source_exit_reason": source_exit_reason,
        "schema_version": (
            LOSS_CONTEXT_PORTFOLIO_COMPOSITION_SCHEMA_VERSION
        ),
    }


def rebuild_deferred_loss_context_portfolio_composition(
    state_root: str | Path,
) -> dict[str, object]:
    root = Path(state_root)
    session = _load_object(root / "session-summary.json", "session summary")
    exit_reason = session.get("exit_reason")
    if exit_reason not in ALLOWED_SESSION_EXITS:
        raise DeferredLossContextPortfolioCompositionError(
            "loss-context portfolio composition requires a clean paper handoff"
        )
    assert isinstance(exit_reason, str)

    freeze_path = root / FREEZE_FILENAME
    if not freeze_path.is_file() or freeze_path.stat().st_size <= 0:
        raise DeferredLossContextPortfolioCompositionError(
            "loss-context freeze is missing"
        )
    freeze = verify_loss_context_candidate_freeze(freeze_path)

    required = {
        "account": root / ACCOUNT_FILENAME,
        "entry": root / ENTRY_FILENAME,
        "exit": root / EXIT_FILENAME,
    }
    missing = [
        name
        for name, path in required.items()
        if not path.is_file() or path.stat().st_size <= 0
    ]
    if missing:
        return _closed_payload(
            candidate_id=freeze.candidate_id,
            reason="required_upstream_evidence_missing",
            source_exit_reason=exit_reason,
        )

    account = _load_object(required["account"], "account readiness")
    entry = _load_object(required["entry"], "replacement entry")
    exit_pnl = _load_object(required["exit"], "replacement exit pnl")
    if (
        account.get("fixed_schedule_economics_ready") is not True
        or entry.get("ready_for_replacement_exit_investigation") is not True
        or exit_pnl.get(
            "ready_for_portfolio_counterfactual_investigation"
        )
        is not True
        or exit_pnl.get("all_horizons_complete") is not True
    ):
        return _closed_payload(
            candidate_id=freeze.candidate_id,
            reason="upstream_portfolio_investigation_gate_not_ready",
            source_exit_reason=exit_reason,
        )

    payload = loss_context_portfolio_composition_summary(
        account,
        entry,
        exit_pnl,
        freeze=freeze,
    )
    payload = dict(payload)
    payload["enabled"] = True
    payload["deferred_post_handoff_rebuild"] = True
    payload["source_exit_reason"] = exit_reason
    return payload


def write_deferred_loss_context_portfolio_composition(
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
    payload = rebuild_deferred_loss_context_portfolio_composition(
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
