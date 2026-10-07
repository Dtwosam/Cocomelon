from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.loss_context_candidate import (
    LossContextCandidateFreeze,
    verify_loss_context_candidate_freeze,
)
from cocomelon.research.loss_streak_context_audit import (
    try_resolve_entry_context_row,
)
from cocomelon.research.prospective_filter_economic_readiness import (
    prospective_filter_economic_readiness,
)

LOSS_CONTEXT_ACCOUNT_READINESS_SCHEMA_VERSION = 1


class LossContextAccountReadinessError(RuntimeError):
    pass


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise LossContextAccountReadinessError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LossContextAccountReadinessError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LossContextAccountReadinessError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise LossContextAccountReadinessError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise LossContextAccountReadinessError(f"{field} must be finite")
    return result


def _context_values(
    row: dict[str, object],
    dimensions: tuple[str, ...],
) -> tuple[str, ...]:
    try:
        return tuple(str(row[dimension]) for dimension in dimensions)
    except KeyError as exc:
        raise LossContextAccountReadinessError(
            f"resolved row missing context field: {exc.args[0]}"
        ) from exc


def _validate_prospective_report(
    report: dict[str, object],
    freeze: LossContextCandidateFreeze,
) -> None:
    if report.get("candidate_id") != freeze.candidate_id:
        raise LossContextAccountReadinessError(
            "LOSS_CONTEXT_PROSPECTIVE_CANDIDATE_MISMATCH"
        )
    if report.get("prospective_only") is not True:
        raise LossContextAccountReadinessError(
            "LOSS_CONTEXT_PROSPECTIVE_SCOPE_INVALID"
        )
    if report.get("paper_only") is not True:
        raise LossContextAccountReadinessError(
            "LOSS_CONTEXT_PROSPECTIVE_SCOPE_INVALID"
        )
    if report.get("research_only") is not True:
        raise LossContextAccountReadinessError(
            "LOSS_CONTEXT_PROSPECTIVE_AUTHORITY_INVALID"
        )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "promotion_authority",
        "execution_authority",
    ):
        if report.get(field) is not False:
            raise LossContextAccountReadinessError(
                "LOSS_CONTEXT_PROSPECTIVE_AUTHORITY_INVALID"
            )


def loss_context_account_readiness(
    items: Sequence[tuple[TradeJournalEntry, bool]],
    *,
    freeze: LossContextCandidateFreeze,
    prospective_report: dict[str, object],
    unresolved_reason_counts: dict[str, int] | None = None,
) -> dict[str, object]:
    _validate_prospective_report(prospective_report, freeze)
    values = tuple(items)
    trade_ids = tuple(trade.trade_id for trade, _blocked in values)
    if len(set(trade_ids)) != len(trade_ids):
        raise LossContextAccountReadinessError(
            "loss-context account economics contain duplicate trade ids"
        )

    reasons = (
        {}
        if unresolved_reason_counts is None
        else dict(sorted(unresolved_reason_counts.items()))
    )
    unresolved_count = sum(reasons.values())
    blocked = sum(blocked for _trade, blocked in values)
    allowed = len(values) - blocked

    expected_resolved = _integer(
        prospective_report.get("future_resolved_trade_count"),
        "future_resolved_trade_count",
    )
    expected_unresolved = _integer(
        prospective_report.get("future_unresolved_trade_count"),
        "future_unresolved_trade_count",
    )
    expected_matching = _integer(
        prospective_report.get("matching_outcomes"),
        "matching_outcomes",
    )
    if len(values) != expected_resolved:
        raise LossContextAccountReadinessError(
            "LOSS_CONTEXT_RESOLVED_TRADE_COUNT_MISMATCH"
        )
    if unresolved_count != expected_unresolved:
        raise LossContextAccountReadinessError(
            "LOSS_CONTEXT_UNRESOLVED_TRADE_COUNT_MISMATCH"
        )
    if blocked != expected_matching:
        raise LossContextAccountReadinessError(
            "LOSS_CONTEXT_MATCHING_TRADE_COUNT_MISMATCH"
        )

    economics = prospective_filter_economic_readiness(values)
    expected_delta = _decimal(
        prospective_report.get("total_filter_delta_pnl"),
        "total_filter_delta_pnl",
    )
    observed_delta = _decimal(
        economics.get("delta_net_pnl"),
        "fixed_schedule delta_net_pnl",
    )
    if observed_delta != expected_delta:
        raise LossContextAccountReadinessError(
            "LOSS_CONTEXT_FILTER_DELTA_MISMATCH"
        )
    prospective_ready = prospective_report.get("ready_for_review") is True
    source_complete = (
        prospective_report.get("source_complete") is True
        and unresolved_count == 0
    )
    economics_ready = economics.get("economics_ready") is True
    ready_for_capacity_reflow_investigation = (
        prospective_ready
        and source_complete
        and economics_ready
    )

    by_direction: dict[str, dict[str, int]] = {}
    for trade, is_blocked in values:
        direction = trade.direction.value
        bucket = by_direction.setdefault(
            direction,
            {"trades": 0, "blocked": 0, "allowed": 0},
        )
        bucket["trades"] += 1
        bucket["blocked" if is_blocked else "allowed"] += 1

    return {
        "candidate_id": freeze.candidate_id,
        "dimensions": freeze.dimensions,
        "values": freeze.values,
        "prospective_not_before_ms": freeze.prospective_not_before_ms,
        "future_resolved_trade_count": len(values),
        "future_unresolved_trade_count": unresolved_count,
        "future_unresolved_reason_counts": reasons,
        "source_complete": source_complete,
        "blocked_trades": blocked,
        "allowed_trades": allowed,
        "by_direction": dict(sorted(by_direction.items())),
        "prospective_filter_review_ready": prospective_ready,
        "fixed_schedule_economics": economics,
        "fixed_schedule_economics_ready": economics_ready,
        "ready_for_capacity_reflow_investigation": (
            ready_for_capacity_reflow_investigation
        ),
        "capacity_reflow_modeled": False,
        "recursive_replacements_modeled": False,
        "capacity_reflow_required_before_strategy_use": True,
        "direction_only_filter_allowed": False,
        "prospective_only": True,
        "paper_only": True,
        "research_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "promotion_authority": False,
        "execution_authority": False,
        "schema_version": LOSS_CONTEXT_ACCOUNT_READINESS_SCHEMA_VERSION,
    }


def score_loss_context_account_readiness_state(
    *,
    state_root: str | Path,
    freeze_path: str | Path,
    prospective_report_path: str | Path,
) -> dict[str, object]:
    root = Path(state_root)
    freeze = verify_loss_context_candidate_freeze(freeze_path)
    try:
        raw = json.loads(
            Path(prospective_report_path).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LossContextAccountReadinessError(
            "loss-context prospective report is missing or invalid"
        ) from exc
    prospective = _mapping(raw, "loss-context prospective report")
    _validate_prospective_report(prospective, freeze)

    journal = JournalStore(root / "journal.sqlite3")
    facts = EvaluationFactStore(root / "facts.sqlite3")
    features = LearningFeatureSnapshotStore(root / "learning-features")
    ranks = ContinuousPaperOpeningRankStore(root / "opening-ranks")
    items: list[tuple[TradeJournalEntry, bool]] = []
    unresolved: Counter[str] = Counter()
    try:
        for trade in journal.iter_trades():
            if trade.opened_at_ms < freeze.prospective_not_before_ms:
                continue
            row, reason = try_resolve_entry_context_row(
                trade,
                facts,
                features,
                ranks,
            )
            if row is None:
                unresolved[reason or "unresolved"] += 1
                continue
            blocked = (
                _context_values(row, freeze.dimensions)
                == freeze.values
            )
            items.append((trade, blocked))
    finally:
        facts.close()
        journal.close()

    return loss_context_account_readiness(
        tuple(items),
        freeze=freeze,
        prospective_report=prospective,
        unresolved_reason_counts=dict(unresolved),
    )
