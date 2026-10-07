from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayRecord
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import (
    BaselineReplayPipeline,
    DecisionEpochEngine,
)
from cocomelon.execution.accounting import PaperAccountState
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)
from cocomelon.research.loss_context_portfolio_shadow_entry import (
    LossContextPortfolioShadowEntryFilter,
    RankOrdinalProvider,
)

ZERO: Final = Decimal("0")
LOSS_CONTEXT_PAIRED_SHADOW_SCHEMA_VERSION: Final = 1

DecisionEngineFactory = Callable[[], DecisionEpochEngine]


@dataclass(frozen=True, slots=True)
class _LaneSnapshot:
    equity: Decimal
    realized_net_pnl: Decimal
    total_account_pnl: Decimal
    daily_realized_pnl: Decimal
    rolling_7d_peak_equity: Decimal
    current_drawdown_fraction: Decimal
    max_drawdown_fraction: Decimal
    consecutive_losses: int
    open_position_count: int
    gross_open_notional: Decimal
    available_margin: Decimal
    closed_trade_count: int
    risk_evaluations: int
    risk_approvals: int
    risk_rejections: int
    opening_execution_attempts: int
    opening_fills: int

    def to_dict(self) -> dict[str, object]:
        return {
            "equity": str(self.equity),
            "realized_net_pnl": str(self.realized_net_pnl),
            "total_account_pnl": str(self.total_account_pnl),
            "daily_realized_pnl": str(self.daily_realized_pnl),
            "rolling_7d_peak_equity": str(self.rolling_7d_peak_equity),
            "current_drawdown_fraction": str(
                self.current_drawdown_fraction
            ),
            "max_drawdown_fraction": str(self.max_drawdown_fraction),
            "consecutive_losses": self.consecutive_losses,
            "open_position_count": self.open_position_count,
            "gross_open_notional": str(self.gross_open_notional),
            "available_margin": str(self.available_margin),
            "closed_trade_count": self.closed_trade_count,
            "risk_evaluations": self.risk_evaluations,
            "risk_approvals": self.risk_approvals,
            "risk_rejections": self.risk_rejections,
            "opening_execution_attempts": (
                self.opening_execution_attempts
            ),
            "opening_fills": self.opening_fills,
        }


class LossContextPairedPortfolioShadow:
    """Run paired baseline/candidate paper accounts on the same evidence stream.

    The two lanes use identical replay configuration, market evidence, strategy
    logic, risk engine, execution model, position management, fees and funding.
    The only intentional difference is the D-049 opening-admission filter.
    """

    def __init__(
        self,
        *,
        freeze: LossContextPortfolioShadowFreeze,
        replay_config: BaselineReplayConfig,
        selected_markets: Sequence[MarketId],
        state_root: str | Path,
        startup_timestamp_ms: int,
        rank_ordinal_provider: RankOrdinalProvider | None = None,
        decision_engine_factory: DecisionEngineFactory | None = None,
    ) -> None:
        if startup_timestamp_ms < 0:
            raise ValueError("startup_timestamp_ms must be non-negative")
        markets = tuple(
            sorted(selected_markets, key=lambda item: item.canonical)
        )
        if not markets:
            raise ValueError("selected_markets must not be empty")
        if len({item.canonical for item in markets}) != len(markets):
            raise ValueError("selected_markets must not contain duplicates")

        root = Path(state_root)
        root.mkdir(parents=True, exist_ok=True)
        self._freeze = freeze
        self._config = replay_config
        self._record_count = 0
        self._last_record_available_at_ms: int | None = None
        self._baseline_max_drawdown = ZERO
        self._candidate_max_drawdown = ZERO

        self._baseline_filter = LossContextPortfolioShadowEntryFilter(
            freeze,
            block_matching_context=False,
            rank_ordinal_provider=rank_ordinal_provider,
        )
        self._candidate_filter = LossContextPortfolioShadowEntryFilter(
            freeze,
            block_matching_context=True,
            rank_ordinal_provider=rank_ordinal_provider,
        )

        self._baseline_execution = PaperExecutionAdapter(
            root / "baseline-execution.sqlite3",
            replay_config.execution,
            starting_cash=replay_config.starting_cash,
            startup_timestamp_ms=startup_timestamp_ms,
        )
        self._candidate_execution = PaperExecutionAdapter(
            root / "candidate-execution.sqlite3",
            replay_config.execution,
            starting_cash=replay_config.starting_cash,
            startup_timestamp_ms=startup_timestamp_ms,
        )
        self._baseline_facts = EvaluationFactStore(
            root / "baseline-facts.sqlite3"
        )
        self._candidate_facts = EvaluationFactStore(
            root / "candidate-facts.sqlite3"
        )

        baseline_engine = (
            None
            if decision_engine_factory is None
            else decision_engine_factory()
        )
        candidate_engine = (
            None
            if decision_engine_factory is None
            else decision_engine_factory()
        )
        self._baseline = BaselineReplayPipeline(
            replay_config,
            self._baseline_execution,
            self._baseline_facts,
            selected_markets=markets,
            replay_run_id=f"{freeze.candidate_id}:baseline",
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            decision_engine=baseline_engine,
            opening_candidate_filter=self._baseline_filter,
        )
        self._candidate = BaselineReplayPipeline(
            replay_config,
            self._candidate_execution,
            self._candidate_facts,
            selected_markets=markets,
            replay_run_id=f"{freeze.candidate_id}:candidate",
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            decision_engine=candidate_engine,
            opening_candidate_filter=self._candidate_filter,
        )

    @staticmethod
    def _drawdown(account: PaperAccountState) -> Decimal:
        peak = account.rolling_7d_peak_equity
        if peak <= ZERO:
            return ZERO
        return max(ZERO, (peak - account.equity) / peak)

    def _update_drawdowns(self) -> None:
        self._baseline_max_drawdown = max(
            self._baseline_max_drawdown,
            self._drawdown(self._baseline_execution.account),
        )
        self._candidate_max_drawdown = max(
            self._candidate_max_drawdown,
            self._drawdown(self._candidate_execution.account),
        )

    def on_record(
        self,
        record: ReplayRecord,
        now_ms: int,
        *,
        evaluate_decisions: bool = True,
    ) -> None:
        if self._last_record_available_at_ms is not None and (
            record.available_at_ms < self._last_record_available_at_ms
        ):
            raise ValueError(
                "paired shadow records must be consumed chronologically"
            )
        self._baseline.on_record(
            record,
            now_ms,
            evaluate_decisions=evaluate_decisions,
        )
        self._candidate.on_record(
            record,
            now_ms,
            evaluate_decisions=evaluate_decisions,
        )
        self._record_count += 1
        self._last_record_available_at_ms = record.available_at_ms
        self._update_drawdowns()

    @property
    def baseline_pending_opening_markets(self) -> tuple[MarketId, ...]:
        return self._baseline.pending_opening_markets

    @property
    def candidate_pending_opening_markets(self) -> tuple[MarketId, ...]:
        return self._candidate.pending_opening_markets

    @property
    def handoff_safe(self) -> bool:
        return (
            not self.baseline_pending_opening_markets
            and not self.candidate_pending_opening_markets
        )

    def assert_handoff_safe(self) -> None:
        if self.handoff_safe:
            return
        baseline = ",".join(
            market.canonical
            for market in self.baseline_pending_opening_markets
        )
        candidate = ",".join(
            market.canonical
            for market in self.candidate_pending_opening_markets
        )
        raise RuntimeError(
            "paired shadow handoff would drop pending openings; "
            f"baseline={baseline or 'none'}; "
            f"candidate={candidate or 'none'}"
        )

    def _lane_snapshot(
        self,
        pipeline: BaselineReplayPipeline,
        execution: PaperExecutionAdapter,
        *,
        max_drawdown: Decimal,
        end_ms: int,
    ) -> _LaneSnapshot:
        account = execution.account
        activity = pipeline.session_decision_activity
        closed = pipeline.finalize(end_ms)
        realized_net = (
            account.realized_gross_pnl
            - account.cumulative_fees
            + account.cumulative_funding
        )
        return _LaneSnapshot(
            equity=account.equity,
            realized_net_pnl=realized_net,
            total_account_pnl=account.equity - account.starting_cash,
            daily_realized_pnl=account.daily_realized_pnl,
            rolling_7d_peak_equity=account.rolling_7d_peak_equity,
            current_drawdown_fraction=self._drawdown(account),
            max_drawdown_fraction=max_drawdown,
            consecutive_losses=account.consecutive_losses,
            open_position_count=len(account.positions),
            gross_open_notional=account.gross_open_notional,
            available_margin=account.available_margin,
            closed_trade_count=len(closed),
            risk_evaluations=activity.risk_evaluations,
            risk_approvals=activity.risk_approvals,
            risk_rejections=activity.risk_rejections,
            opening_execution_attempts=(
                activity.opening_execution_attempts
            ),
            opening_fills=activity.opening_fills,
        )

    def summary_payload(self, *, end_ms: int) -> dict[str, object]:
        if end_ms < 0:
            raise ValueError("end_ms must be non-negative")
        self._update_drawdowns()
        baseline = self._lane_snapshot(
            self._baseline,
            self._baseline_execution,
            max_drawdown=self._baseline_max_drawdown,
            end_ms=end_ms,
        )
        candidate = self._lane_snapshot(
            self._candidate,
            self._candidate_execution,
            max_drawdown=self._candidate_max_drawdown,
            end_ms=end_ms,
        )
        return {
            "portfolio_shadow_candidate_id": self._freeze.candidate_id,
            "loss_context_candidate_id": (
                self._freeze.loss_context_candidate_id
            ),
            "dimensions": self._freeze.dimensions,
            "values": self._freeze.values,
            "prospective_not_before_ms": (
                self._freeze.prospective_not_before_ms
            ),
            "record_count": self._record_count,
            "last_record_available_at_ms": (
                self._last_record_available_at_ms
            ),
            "baseline_pending_opening_markets": tuple(
                market.canonical
                for market in self.baseline_pending_opening_markets
            ),
            "candidate_pending_opening_markets": tuple(
                market.canonical
                for market in self.candidate_pending_opening_markets
            ),
            "handoff_safe": self.handoff_safe,
            "pending_opening_state_persisted": False,
            "baseline": baseline.to_dict(),
            "candidate": candidate.to_dict(),
            "candidate_minus_baseline_equity": str(
                candidate.equity - baseline.equity
            ),
            "candidate_minus_baseline_total_account_pnl": str(
                candidate.total_account_pnl
                - baseline.total_account_pnl
            ),
            "candidate_minus_baseline_realized_net_pnl": str(
                candidate.realized_net_pnl - baseline.realized_net_pnl
            ),
            "candidate_minus_baseline_max_drawdown_fraction": str(
                candidate.max_drawdown_fraction
                - baseline.max_drawdown_fraction
            ),
            "baseline_admission": self._baseline_filter.summary_payload(),
            "candidate_admission": self._candidate_filter.summary_payload(),
            "paired_same_evidence_stream_required": True,
            "paired_same_strategy_required": True,
            "paired_same_risk_required": True,
            "paired_same_execution_required": True,
            "candidate_difference_is_opening_admission_only": True,
            "horizon_selection_performed": False,
            "handoff_requires_no_pending_openings": True,
            "research_only": True,
            "shadow_only": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "changes_positions": False,
            "promotion_authority": False,
            "execution_authority": False,
            "schema_version": LOSS_CONTEXT_PAIRED_SHADOW_SCHEMA_VERSION,
        }

    def close(self) -> None:
        self._baseline_facts.close()
        self._candidate_facts.close()
        self._baseline_execution.close()
        self._candidate_execution.close()
