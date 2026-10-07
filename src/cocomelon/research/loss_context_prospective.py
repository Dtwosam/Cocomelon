from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

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

ZERO: Final = Decimal("0")
LOSS_CONTEXT_PROSPECTIVE_SCHEMA_VERSION = 1
MIN_MATCHING_OUTCOMES = 30
MIN_MATCHING_MARKETS = 4
MIN_BENEFICIAL_SHARE = Decimal("0.60")
PROSPECTIVE_BLOCK_COUNT = 3
MIN_BLOCK_ROWS = 5
MIN_BLOCK_BENEFICIAL_SHARE = Decimal("0.55")


class LossContextProspectiveError(RuntimeError):
    pass


def _context_values(
    row: dict[str, object],
    dimensions: tuple[str, ...],
) -> tuple[str, ...]:
    try:
        return tuple(str(row[dimension]) for dimension in dimensions)
    except KeyError as exc:
        raise LossContextProspectiveError(
            f"future row missing context field: {exc.args[0]}"
        ) from exc


def _delta(row: dict[str, object]) -> Decimal:
    return -Decimal(str(row["net_pnl"]))


def _total_delta(
    rows: tuple[dict[str, object], ...],
) -> Decimal:
    return sum((_delta(row) for row in rows), ZERO)


def _beneficial_share(
    rows: tuple[dict[str, object], ...],
) -> Decimal | None:
    if not rows:
        return None
    return Decimal(sum(_delta(row) > ZERO for row in rows)) / Decimal(
        len(rows)
    )


def _leave_one_trade_min_delta(
    rows: tuple[dict[str, object], ...],
) -> Decimal | None:
    if len(rows) < 2:
        return None
    total = _total_delta(rows)
    return min(total - _delta(row) for row in rows)


def _leave_one_market_min_delta(
    rows: tuple[dict[str, object], ...],
) -> Decimal | None:
    by_market: dict[str, Decimal] = {}
    for row in rows:
        market = str(row["market"])
        by_market[market] = by_market.get(market, ZERO) + _delta(row)
    if len(by_market) < 2:
        return None
    total = sum(by_market.values(), ZERO)
    return min(total - value for value in by_market.values())


def _blocks(
    rows: tuple[dict[str, object], ...],
) -> tuple[tuple[dict[str, object], ...], ...]:
    if not rows:
        return ()
    timestamps = tuple(
        sorted({int(str(row["opened_at_ms"])) for row in rows})
    )
    resolved = min(PROSPECTIVE_BLOCK_COUNT, len(timestamps))
    blocks: list[tuple[dict[str, object], ...]] = []
    for index in range(resolved):
        start = (len(timestamps) * index) // resolved
        end = (len(timestamps) * (index + 1)) // resolved
        selected = set(timestamps[start:end])
        if selected:
            blocks.append(
                tuple(
                    row
                    for row in rows
                    if int(str(row["opened_at_ms"])) in selected
                )
            )
    return tuple(blocks)


@dataclass(frozen=True, slots=True)
class LossContextProspectiveReport:
    candidate_id: str
    dimensions: tuple[str, ...]
    values: tuple[str, ...]
    prospective_not_before_ms: int
    future_trade_count: int
    future_resolved_trade_count: int
    future_unresolved_trade_count: int
    future_unresolved_reason_counts: dict[str, int]
    source_complete: bool
    matching_outcomes: int
    matching_markets: int
    beneficial_outcomes: int
    harmful_outcomes: int
    flat_outcomes: int
    beneficial_share: Decimal | None
    total_filter_delta_pnl: Decimal
    mean_filter_delta_pnl: Decimal | None
    leave_one_trade_min_delta_pnl: Decimal | None
    leave_one_market_min_delta_pnl: Decimal | None
    first_matching_opened_at_ms: int | None
    last_matching_opened_at_ms: int | None
    prospective_block_rows: tuple[int, ...]
    prospective_block_beneficial_shares: tuple[Decimal | None, ...]
    prospective_block_filter_delta_pnl: tuple[Decimal, ...]
    prospective_blocks_consistent: int
    ready_for_review: bool
    prospective_only: bool = True
    paper_only: bool = True
    research_only: bool = True
    changes_strategy: bool = False
    changes_risk_limits: bool = False
    promotion_authority: bool = False
    execution_authority: bool = False
    schema_version: int = LOSS_CONTEXT_PROSPECTIVE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "dimensions": self.dimensions,
            "values": self.values,
            "prospective_not_before_ms": self.prospective_not_before_ms,
            "future_trade_count": self.future_trade_count,
            "future_resolved_trade_count": self.future_resolved_trade_count,
            "future_unresolved_trade_count": self.future_unresolved_trade_count,
            "future_unresolved_reason_counts": dict(
                sorted(self.future_unresolved_reason_counts.items())
            ),
            "source_complete": self.source_complete,
            "matching_outcomes": self.matching_outcomes,
            "matching_markets": self.matching_markets,
            "beneficial_outcomes": self.beneficial_outcomes,
            "harmful_outcomes": self.harmful_outcomes,
            "flat_outcomes": self.flat_outcomes,
            "beneficial_share": (
                None
                if self.beneficial_share is None
                else str(self.beneficial_share)
            ),
            "total_filter_delta_pnl": str(self.total_filter_delta_pnl),
            "mean_filter_delta_pnl": (
                None
                if self.mean_filter_delta_pnl is None
                else str(self.mean_filter_delta_pnl)
            ),
            "leave_one_trade_min_delta_pnl": (
                None
                if self.leave_one_trade_min_delta_pnl is None
                else str(self.leave_one_trade_min_delta_pnl)
            ),
            "leave_one_market_min_delta_pnl": (
                None
                if self.leave_one_market_min_delta_pnl is None
                else str(self.leave_one_market_min_delta_pnl)
            ),
            "first_matching_opened_at_ms": self.first_matching_opened_at_ms,
            "last_matching_opened_at_ms": self.last_matching_opened_at_ms,
            "prospective_block_rows": self.prospective_block_rows,
            "prospective_block_beneficial_shares": tuple(
                None if value is None else str(value)
                for value in self.prospective_block_beneficial_shares
            ),
            "prospective_block_filter_delta_pnl": tuple(
                str(value)
                for value in self.prospective_block_filter_delta_pnl
            ),
            "prospective_blocks_consistent": (
                self.prospective_blocks_consistent
            ),
            "ready_for_review": self.ready_for_review,
            "minimum_matching_outcomes": MIN_MATCHING_OUTCOMES,
            "minimum_matching_markets": MIN_MATCHING_MARKETS,
            "minimum_beneficial_share": str(MIN_BENEFICIAL_SHARE),
            "prospective_block_count_required": PROSPECTIVE_BLOCK_COUNT,
            "minimum_block_rows": MIN_BLOCK_ROWS,
            "minimum_block_beneficial_share": str(
                MIN_BLOCK_BENEFICIAL_SHARE
            ),
            "counterfactual_filter_delta_definition": (
                "negative_of_realized_net_pnl_for_matching_trade"
            ),
            "prospective_only": self.prospective_only,
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "changes_strategy": self.changes_strategy,
            "changes_risk_limits": self.changes_risk_limits,
            "promotion_authority": self.promotion_authority,
            "execution_authority": self.execution_authority,
            "schema_version": self.schema_version,
        }


def build_loss_context_prospective_report(
    rows: tuple[dict[str, object], ...],
    freeze: LossContextCandidateFreeze,
    *,
    future_trade_count: int | None = None,
    unresolved_reason_counts: dict[str, int] | None = None,
) -> LossContextProspectiveReport:
    future_rows = tuple(
        sorted(
            (
                row
                for row in rows
                if int(str(row["opened_at_ms"]))
                >= freeze.prospective_not_before_ms
            ),
            key=lambda row: (
                int(str(row["opened_at_ms"])),
                str(row["trade_id"]),
            ),
        )
    )
    matching = tuple(
        row
        for row in future_rows
        if _context_values(row, freeze.dimensions) == freeze.values
    )
    reasons = (
        {}
        if unresolved_reason_counts is None
        else dict(unresolved_reason_counts)
    )
    unresolved_count = sum(reasons.values())
    observed_future_trade_count = (
        len(future_rows) + unresolved_count
        if future_trade_count is None
        else future_trade_count
    )
    if observed_future_trade_count < len(future_rows) + unresolved_count:
        raise LossContextProspectiveError(
            "future_trade_count is smaller than resolved plus unresolved"
        )

    total = _total_delta(matching)
    beneficial = sum(_delta(row) > ZERO for row in matching)
    harmful = sum(_delta(row) < ZERO for row in matching)
    flat = len(matching) - beneficial - harmful
    share = _beneficial_share(matching)
    mean = None if not matching else total / Decimal(len(matching))
    loo_trade = _leave_one_trade_min_delta(matching)
    loo_market = _leave_one_market_min_delta(matching)
    blocks = _blocks(matching)
    block_rows = tuple(len(block) for block in blocks)
    block_shares = tuple(_beneficial_share(block) for block in blocks)
    block_deltas = tuple(_total_delta(block) for block in blocks)
    consistent = sum(
        len(block) >= MIN_BLOCK_ROWS
        and block_share is not None
        and block_share >= MIN_BLOCK_BENEFICIAL_SHARE
        and block_delta > ZERO
        for block, block_share, block_delta in zip(
            blocks,
            block_shares,
            block_deltas,
            strict=True,
        )
    )
    markets = len({str(row["market"]) for row in matching})
    ready = (
        unresolved_count == 0
        and len(matching) >= MIN_MATCHING_OUTCOMES
        and markets >= MIN_MATCHING_MARKETS
        and share is not None
        and share >= MIN_BENEFICIAL_SHARE
        and total > ZERO
        and mean is not None
        and mean > ZERO
        and loo_trade is not None
        and loo_trade > ZERO
        and loo_market is not None
        and loo_market > ZERO
        and len(blocks) == PROSPECTIVE_BLOCK_COUNT
        and consistent == PROSPECTIVE_BLOCK_COUNT
    )
    first = (
        None
        if not matching
        else int(str(matching[0]["opened_at_ms"]))
    )
    last = (
        None
        if not matching
        else int(str(matching[-1]["opened_at_ms"]))
    )
    return LossContextProspectiveReport(
        candidate_id=freeze.candidate_id,
        dimensions=freeze.dimensions,
        values=freeze.values,
        prospective_not_before_ms=freeze.prospective_not_before_ms,
        future_trade_count=observed_future_trade_count,
        future_resolved_trade_count=len(future_rows),
        future_unresolved_trade_count=unresolved_count,
        future_unresolved_reason_counts=reasons,
        source_complete=unresolved_count == 0,
        matching_outcomes=len(matching),
        matching_markets=markets,
        beneficial_outcomes=beneficial,
        harmful_outcomes=harmful,
        flat_outcomes=flat,
        beneficial_share=share,
        total_filter_delta_pnl=total,
        mean_filter_delta_pnl=mean,
        leave_one_trade_min_delta_pnl=loo_trade,
        leave_one_market_min_delta_pnl=loo_market,
        first_matching_opened_at_ms=first,
        last_matching_opened_at_ms=last,
        prospective_block_rows=block_rows,
        prospective_block_beneficial_shares=block_shares,
        prospective_block_filter_delta_pnl=block_deltas,
        prospective_blocks_consistent=consistent,
        ready_for_review=ready,
    )


def score_loss_context_candidate_state(
    *,
    state_root: str | Path,
    freeze_path: str | Path,
) -> LossContextProspectiveReport:
    root = Path(state_root)
    freeze = verify_loss_context_candidate_freeze(freeze_path)
    journal = JournalStore(root / "journal.sqlite3")
    facts = EvaluationFactStore(root / "facts.sqlite3")
    features = LearningFeatureSnapshotStore(root / "learning-features")
    ranks = ContinuousPaperOpeningRankStore(root / "opening-ranks")
    rows: list[dict[str, object]] = []
    unresolved: Counter[str] = Counter()
    future_trade_count = 0
    try:
        for trade in journal.iter_trades():
            if trade.opened_at_ms < freeze.prospective_not_before_ms:
                continue
            future_trade_count += 1
            row, reason = try_resolve_entry_context_row(
                trade,
                facts,
                features,
                ranks,
            )
            if row is None:
                unresolved[reason or "unresolved"] += 1
                continue
            rows.append(row)
    finally:
        facts.close()
        journal.close()

    return build_loss_context_prospective_report(
        tuple(rows),
        freeze,
        future_trade_count=future_trade_count,
        unresolved_reason_counts=dict(unresolved),
    )
