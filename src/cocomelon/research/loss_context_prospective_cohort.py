"""Immutable forward-only coverage cohort for loss-context research (no trading authority)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from decimal import Decimal
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
from cocomelon.research.loss_streak_context_audit import (
    loss_streak_context_audit,
)

ANCHOR_FILENAME = "loss-context-forward-cohort-anchor.json"
REPORT_FILENAME = "loss-context-forward-cohort-report.json"
SCHEMA_VERSION = 1
MIN_AGE_MS = 72 * 60 * 60 * 1000
MIN_CLOSED_TRADES = 30
MIN_MARKETS = 4
MIN_NON_LOSS_CONTROLS = 6
HANDOFF_EXITS = frozenset({"duration_elapsed", "upgrade_requested"})


class LossContextForwardCohortError(RuntimeError):
    pass


def _canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise LossContextForwardCohortError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _load(path: Path) -> dict[str, object]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), str(path))
    except (OSError, json.JSONDecodeError) as exc:
        raise LossContextForwardCohortError(
            f"invalid or missing forward cohort file: {path}"
        ) from exc


def _preexisting(
    trades: tuple[TradeJournalEntry, ...], cutoff_ms: int,
) -> tuple[TradeJournalEntry, ...]:
    return tuple(
        sorted(
            (trade for trade in trades if trade.closed_at_ms <= cutoff_ms),
            key=lambda trade: (trade.closed_at_ms, trade.trade_id),
        )
    )


def _historical_witness(trades: tuple[TradeJournalEntry, ...]) -> str:
    return _digest(
        tuple(
            {
                "trade_id": trade.trade_id,
                "opened_at_ms": trade.opened_at_ms,
                "closed_at_ms": trade.closed_at_ms,
                "net_pnl": str(trade.net_pnl),
            }
            for trade in trades
        )
    )


def _validate_anchor(anchor: dict[str, object]) -> None:
    expected_fields = {
        "schema_version", "frozen_at_ms", "source_paper_run_id",
        "source_paper_run_attempt", "source_paper_head_sha",
        "source_closed_trade_count", "source_last_closed_at_ms",
        "source_historical_witness", "forward_only",
        "paper_only", "research_only", "execution_authority",
        "promotion_authority", "changes_strategy", "changes_risk_limits",
        "anchor_id",
    }
    if set(anchor) != expected_fields:
        raise LossContextForwardCohortError("forward cohort anchor fields invalid")
    if anchor["schema_version"] != SCHEMA_VERSION:
        raise LossContextForwardCohortError("forward cohort schema unsupported")
    for field in (
        "frozen_at_ms", "source_paper_run_id",
        "source_paper_run_attempt", "source_closed_trade_count",
    ):
        value = anchor[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LossContextForwardCohortError(f"{field} is invalid")
    if anchor["source_paper_run_id"] == 0 or anchor["source_paper_run_attempt"] == 0:
        raise LossContextForwardCohortError("source run identity must be positive")
    last = anchor["source_last_closed_at_ms"]
    if last is not None and (
        isinstance(last, bool) or not isinstance(last, int) or last < 0
        or last > cast(int, anchor["frozen_at_ms"])
    ):
        raise LossContextForwardCohortError("source last closed time invalid")
    for field, length in (
        ("source_paper_head_sha", 40),
        ("source_historical_witness", 64),
        ("anchor_id", 64),
    ):
        value = anchor[field]
        if not isinstance(value, str) or re.fullmatch(
            f"[0-9a-f]{{{length}}}", value
        ) is None:
            raise LossContextForwardCohortError(f"{field} is invalid")
    if (
        anchor["forward_only"] is not True
        or anchor["paper_only"] is not True
        or anchor["research_only"] is not True
    ):
        raise LossContextForwardCohortError("forward research scope invalid")
    for field in (
        "execution_authority", "promotion_authority",
        "changes_strategy", "changes_risk_limits",
    ):
        if anchor[field] is not False:
            raise LossContextForwardCohortError(
                "forward cohort cannot grant strategy/execution authority"
            )
    identity = {key: value for key, value in anchor.items() if key != "anchor_id"}
    if anchor["anchor_id"] != _digest(identity):
        raise LossContextForwardCohortError("forward cohort anchor identity mismatch")


def _verify_witness(
    anchor: dict[str, object], trades: tuple[TradeJournalEntry, ...],
) -> None:
    frozen_at_ms = cast(int, anchor["frozen_at_ms"])
    historical = _preexisting(trades, frozen_at_ms)
    if (
        len(historical) != anchor["source_closed_trade_count"]
        or (historical[-1].closed_at_ms if historical else None)
        != anchor["source_last_closed_at_ms"]
        or _historical_witness(historical) != anchor["source_historical_witness"]
    ):
        raise LossContextForwardCohortError(
            "immutable pre-freeze trade witness changed or disappeared"
        )


def make_anchor(
    trades: tuple[TradeJournalEntry, ...],
    *,
    frozen_at_ms: int,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_paper_head_sha: str,
) -> dict[str, object]:
    if isinstance(frozen_at_ms, bool) or frozen_at_ms <= 0:
        raise LossContextForwardCohortError("freeze time must be positive")
    if any(trade.closed_at_ms > frozen_at_ms for trade in trades):
        raise LossContextForwardCohortError(
            "cannot freeze before an already closed source trade"
        )
    historical = _preexisting(trades, frozen_at_ms)
    identity: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "frozen_at_ms": frozen_at_ms,
        "source_paper_run_id": source_paper_run_id,
        "source_paper_run_attempt": source_paper_run_attempt,
        "source_paper_head_sha": source_paper_head_sha,
        "source_closed_trade_count": len(historical),
        "source_last_closed_at_ms": (
            historical[-1].closed_at_ms if historical else None
        ),
        "source_historical_witness": _historical_witness(historical),
        "forward_only": True,
        "paper_only": True,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
    }
    anchor = {**identity, "anchor_id": _digest(identity)}
    _validate_anchor(anchor)
    return anchor


def load_anchor(
    root: Path, trades: tuple[TradeJournalEntry, ...],
) -> dict[str, object]:
    anchor = _load(root / ANCHOR_FILENAME)
    _validate_anchor(anchor)
    _verify_witness(anchor, trades)
    return anchor


def ensure_anchor(
    root: Path,
    trades: tuple[TradeJournalEntry, ...],
    *,
    frozen_at_ms: int,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_paper_head_sha: str,
) -> tuple[dict[str, object], bool]:
    path = root / ANCHOR_FILENAME
    if path.exists():
        return load_anchor(root, trades), False
    anchor = make_anchor(
        trades,
        frozen_at_ms=frozen_at_ms,
        source_paper_run_id=source_paper_run_id,
        source_paper_run_attempt=source_paper_run_attempt,
        source_paper_head_sha=source_paper_head_sha,
    )
    root.mkdir(parents=True, exist_ok=True)
    encoded = (_canonical(anchor) + "\n").encode("utf-8")
    temporary = root / f".{ANCHOR_FILENAME}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return load_anchor(root, trades), False
    finally:
        temporary.unlink(missing_ok=True)
    return anchor, True


def build_forward_report(
    anchor: dict[str, object],
    trades: tuple[TradeJournalEntry, ...],
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
    *,
    observed_at_ms: int,
) -> dict[str, object]:
    _validate_anchor(anchor)
    _verify_witness(anchor, trades)
    frozen_at_ms = cast(int, anchor["frozen_at_ms"])
    if observed_at_ms < frozen_at_ms:
        raise LossContextForwardCohortError(
            "forward observation predates frozen cohort"
        )
    if any(trade.closed_at_ms > observed_at_ms for trade in trades):
        raise LossContextForwardCohortError(
            "forward observation predates a journal closure"
        )
    cohort = tuple(
        sorted(
            (
                trade for trade in trades
                if trade.opened_at_ms > frozen_at_ms
            ),
            key=lambda trade: (trade.closed_at_ms, trade.trade_id),
        )
    )
    carryover_excluded = sum(
        trade.opened_at_ms <= frozen_at_ms
        and trade.closed_at_ms > frozen_at_ms
        for trade in trades
    )
    audit = loss_streak_context_audit(cohort, facts, features, ranks)
    elapsed_ms = observed_at_ms - frozen_at_ms
    non_loss_trades = sum(trade.net_pnl >= Decimal("0") for trade in cohort)
    distinct_markets = {trade.market.canonical for trade in cohort}
    ready = (
        elapsed_ms >= MIN_AGE_MS
        and len(cohort) >= MIN_CLOSED_TRADES
        and len(distinct_markets) >= MIN_MARKETS
        and non_loss_trades >= MIN_NON_LOSS_CONTROLS
        and audit["baseline_normalization_complete"] is True
    )
    if audit["trade_count"] != len(cohort):
        raise LossContextForwardCohortError(
            "forward audit trade count does not match cohort"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "anchor_id": anchor["anchor_id"],
        "frozen_at_ms": frozen_at_ms,
        "observed_at_ms": observed_at_ms,
        "elapsed_ms": elapsed_ms,
        "minimum_elapsed_ms": MIN_AGE_MS,
        "minimum_closed_trades": MIN_CLOSED_TRADES,
        "minimum_distinct_markets": MIN_MARKETS,
        "minimum_non_loss_controls": MIN_NON_LOSS_CONTROLS,
        "source_closed_trade_count": anchor["source_closed_trade_count"],
        "carryover_excluded_closed_trades": carryover_excluded,
        "forward_closed_trades": len(cohort),
        "forward_market_count": len(distinct_markets),
        "forward_non_loss_control_count": non_loss_trades,
        "forward_net_closed_trade_pnl": str(
            sum((trade.net_pnl for trade in cohort), Decimal("0"))
        ),
        "forward_long_closed_trades": sum(
            trade.direction.value == "long" for trade in cohort
        ),
        "forward_short_closed_trades": sum(
            trade.direction.value == "short" for trade in cohort
        ),
        "forward_baseline_normalization_complete": audit[
            "baseline_normalization_complete"
        ],
        "forward_unresolved_trade_count": audit[
            "baseline_unresolved_trade_count"
        ],
        "forward_unresolved_reason_counts": audit[
            "baseline_unresolved_reason_counts"
        ],
        "forward_qualifying_loss_streaks": audit[
            "qualifying_loss_streak_count"
        ],
        "forward_stable_context_candidates": _object(
            audit["context_filter_stability"], "context_filter_stability"
        )["stable_candidate_count"],
        "ready_for_research_discovery": ready,
        "strategy_promotion_eligible": False,
        "account_profitability_proven": False,
        "paper_only": True,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
    }


def _write_report(path: Path, report: dict[str, object]) -> None:
    data = (_canonical(report) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("anchor", "report"))
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--source-run-id", type=int)
    parser.add_argument("--source-run-attempt", type=int)
    parser.add_argument("--source-head-sha")
    args = parser.parse_args()
    now_ms = int(time.time() * 1000)
    root = args.state_root
    journal = JournalStore(root / "journal.sqlite3")
    try:
        trades = tuple(journal.iter_trades())
    finally:
        journal.close()
    if args.command == "anchor":
        if (
            args.source_run_id is None
            or args.source_run_attempt is None
            or args.source_head_sha is None
        ):
            parser.error("anchor needs the source run ID, attempt, and head SHA")
        anchor, created = ensure_anchor(
            root, trades, frozen_at_ms=now_ms,
            source_paper_run_id=args.source_run_id,
            source_paper_run_attempt=args.source_run_attempt,
            source_paper_head_sha=args.source_head_sha,
        )
        print(_canonical({
            "anchor_id": anchor["anchor_id"],
            "frozen_at_ms": anchor["frozen_at_ms"],
            "created": created, "paper_only": True,
            "execution_authority": False,
        }))
        return 0

    session = _load(root / "session-summary.json")
    if session.get("exit_reason") not in HANDOFF_EXITS:
        raise LossContextForwardCohortError(
            "forward report requires a completed paper handoff"
        )
    anchor = load_anchor(root, trades)
    facts = EvaluationFactStore(root / "facts.sqlite3")
    try:
        report = build_forward_report(
            anchor, trades, facts,
            LearningFeatureSnapshotStore(root / "learning-features"),
            ContinuousPaperOpeningRankStore(root / "opening-ranks"),
            observed_at_ms=now_ms,
        )
    finally:
        facts.close()
    _write_report(root / REPORT_FILENAME, report)
    print(_canonical(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
