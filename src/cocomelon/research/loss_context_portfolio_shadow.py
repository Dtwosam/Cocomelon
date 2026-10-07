from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Sequence

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord
from cocomelon.evidence.lifecycle import BaselineReplayPipeline
from cocomelon.execution.accounting import PaperAccountState
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)
from cocomelon.research.loss_context_portfolio_shadow_entry import (
    LossContextPortfolioShadowEntryFilter,
)

ZERO: Final = Decimal("0")


class LossContextPortfolioShadowPairError(RuntimeError):
    pass


def _realized_net_pnl(account: PaperAccountState) -> Decimal:
    return (
        account.realized_gross_pnl
        - account.cumulative_fees
        + account.cumulative_funding
    )


def _account_payload(account: PaperAccountState) -> dict[str, object]:
    total_account_pnl = account.equity - account.starting_cash
    return {
        "starting_cash": str(account.starting_cash),
        "cash": str(account.cash),
        "equity": str(account.equity),
        "total_account_pnl": str(total_account_pnl),
        "total_return_fraction": str(
            total_account_pnl / account.starting_cash
        ),
        "realized_gross_pnl": str(account.realized_gross_pnl),
        "cumulative_fees": str(account.cumulative_fees),
        "cumulative_funding": str(account.cumulative_funding),
        "realized_net_pnl": str(_realized_net_pnl(account)),
        "unrealized_pnl": str(account.unrealized_pnl),
        "gross_open_notional": str(account.gross_open_notional),
        "reserved_margin": str(account.reserved_margin),
        "available_margin": str(account.available_margin),
        "daily_realized_pnl": str(account.daily_realized_pnl),
        "day_start_equity": str(account.day_start_equity),
        "day_start_ms": account.day_start_ms,
        "rolling_7d_peak_equity": str(account.rolling_7d_peak_equity),
        "consecutive_losses": account.consecutive_losses,
        "last_closed_trade_ms": account.last_closed_trade_ms,
        "open_position_count": len(account.positions),
        "open_position_ids": tuple(
            position.position_id for position in account.positions
        ),
        "state_id": account.state_id,
        "updated_at_ms": account.updated_at_ms,
    }


def _closed_net_pnl(
    trades: dict[str, TradeJournalEntry],
) -> Decimal:
    return sum((trade.net_pnl for trade in trades.values()), ZERO)


@dataclass(slots=True)
class LossContextPortfolioShadowPair:
    freeze: LossContextPortfolioShadowFreeze
    baseline_pipeline: BaselineReplayPipeline
    candidate_pipeline: BaselineReplayPipeline
    baseline_execution: PaperExecutionAdapter
    candidate_execution: PaperExecutionAdapter
    baseline_filter: LossContextPortfolioShadowEntryFilter
    candidate_filter: LossContextPortfolioShadowEntryFilter
    processed_records: int = 0
    last_available_at_ms: int | None = None
    _baseline_closed: dict[str, TradeJournalEntry] = field(
        default_factory=dict
    )
    _candidate_closed: dict[str, TradeJournalEntry] = field(
        default_factory=dict
    )
    _error: str | None = None

    def __post_init__(self) -> None:
        candidate_id = self.freeze.candidate_id
        if self.baseline_filter.freeze.candidate_id != candidate_id:
            raise ValueError("baseline shadow filter candidate mismatch")
        if self.candidate_filter.freeze.candidate_id != candidate_id:
            raise ValueError("candidate shadow filter candidate mismatch")
        if self.baseline_filter.block_matching_context:
            raise ValueError("baseline shadow must not block frozen context")
        if not self.candidate_filter.block_matching_context:
            raise ValueError("candidate shadow must block frozen context")
        if (
            self.baseline_execution.account.starting_cash
            != self.candidate_execution.account.starting_cash
        ):
            raise ValueError("paired shadow starting cash mismatch")

    @property
    def integrity_clean(self) -> bool:
        return self._error is None

    @property
    def error(self) -> str | None:
        return self._error

    def _ensure_healthy(self) -> None:
        if self._error is not None:
            raise LossContextPortfolioShadowPairError(
                "paired shadow is failed closed: " + self._error
            )

    def process(
        self,
        record: ReplayRecord,
        *,
        now_ms: int,
        evaluate_decisions: bool = True,
    ) -> None:
        self._ensure_healthy()
        if now_ms < record.available_at_ms:
            raise ValueError("shadow cannot consume future evidence")
        if (
            self.last_available_at_ms is not None
            and now_ms < self.last_available_at_ms
        ):
            raise ValueError("shadow observation time regressed")
        try:
            self.baseline_pipeline.on_record(
                record,
                now_ms,
                evaluate_decisions=evaluate_decisions,
            )
            self.candidate_pipeline.on_record(
                record,
                now_ms,
                evaluate_decisions=evaluate_decisions,
            )
            for trade in self.baseline_pipeline.finalize(now_ms):
                self._baseline_closed.setdefault(trade.trade_id, trade)
            for trade in self.candidate_pipeline.finalize(now_ms):
                self._candidate_closed.setdefault(trade.trade_id, trade)
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            raise

        self.last_available_at_ms = now_ms
        self.processed_records += 1

    def reconcile_markets(
        self,
        selected_markets: Sequence[MarketId],
    ) -> None:
        self._ensure_healthy()
        try:
            self.baseline_pipeline.reconcile_markets(selected_markets)
            self.candidate_pipeline.reconcile_markets(selected_markets)
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            raise

    def summary_payload(self) -> dict[str, object]:
        baseline_account = self.baseline_execution.account
        candidate_account = self.candidate_execution.account
        baseline = _account_payload(baseline_account)
        candidate = _account_payload(candidate_account)
        baseline_total = (
            baseline_account.equity - baseline_account.starting_cash
        )
        candidate_total = (
            candidate_account.equity - candidate_account.starting_cash
        )
        baseline_realized_net = _realized_net_pnl(baseline_account)
        candidate_realized_net = _realized_net_pnl(candidate_account)
        clean = self.integrity_clean
        return {
            "portfolio_shadow_candidate_id": self.freeze.candidate_id,
            "loss_context_candidate_id": (
                self.freeze.loss_context_candidate_id
            ),
            "prospective_not_before_ms": (
                self.freeze.prospective_not_before_ms
            ),
            "dimensions": self.freeze.dimensions,
            "values": self.freeze.values,
            "processed_records": self.processed_records,
            "last_available_at_ms": self.last_available_at_ms,
            "baseline_closed_trades": len(self._baseline_closed),
            "candidate_closed_trades": len(self._candidate_closed),
            "baseline_closed_trade_net_pnl": str(
                _closed_net_pnl(self._baseline_closed)
            ),
            "candidate_closed_trade_net_pnl": str(
                _closed_net_pnl(self._candidate_closed)
            ),
            "baseline_account": baseline,
            "candidate_account": candidate,
            "candidate_minus_baseline_total_account_pnl": (
                None
                if not clean
                else str(candidate_total - baseline_total)
            ),
            "candidate_minus_baseline_realized_net_pnl": (
                None
                if not clean
                else str(
                    candidate_realized_net - baseline_realized_net
                )
            ),
            "baseline_entry_filter": (
                self.baseline_filter.summary_payload()
            ),
            "candidate_entry_filter": (
                self.candidate_filter.summary_payload()
            ),
            "integrity_clean": clean,
            "economic_comparison_valid": clean,
            "error": self._error,
            "paired_same_record_stream_required": True,
            "independent_account_state_required": True,
            "chronological_account_state_replayed": clean,
            "portfolio_counterfactual_complete": False,
            "ready_for_review": False,
            "shadow_only": True,
            "prospective_only": True,
            "paper_only": True,
            "research_only": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "changes_positions": False,
            "promotion_authority": False,
            "execution_authority": False,
        }
