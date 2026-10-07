from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

from cocomelon.domain.execution import (
    ExecutionAttempt,
    PaperFill,
    PaperOrderPlan,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayRecord,
    SourceRecordKind,
)
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import (
    BaselineReplayPipeline,
    DecisionEpochEngine,
    OpenLifecycleCheckpoint,
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
LOSS_CONTEXT_PAIRED_SHADOW_STATE_SCHEMA_VERSION: Final = 1
LOSS_CONTEXT_PAIRED_SHADOW_STATE_FILENAME: Final = (
    "paired-shadow-state.json"
)

DecisionEngineFactory = Callable[[], DecisionEpochEngine]


def _market_from_canonical(value: str) -> MarketId:
    if ":" not in value:
        return MarketId("", value)
    dex, coin = value.split(":", 1)
    return MarketId(dex, coin)


def _record_payload(record: ReplayRecord) -> dict[str, object]:
    return {
        "record_kind": record.record_kind.value,
        "available_at_ms": record.available_at_ms,
        "source": record.source,
        "schema_version": record.schema_version,
        "market": record.market,
        "exchange_time_ms": record.exchange_time_ms,
        "event_key": record.event_key,
        "payload_json": record.payload_json,
        "event_kind": record.event_kind,
    }


def _record_from_payload(raw: object) -> ReplayRecord:
    if not isinstance(raw, dict):
        raise ValueError("shadow replay record must be an object")
    return ReplayRecord(
        record_kind=SourceRecordKind(str(raw["record_kind"])),
        available_at_ms=int(raw["available_at_ms"]),
        source=str(raw["source"]),
        schema_version=int(raw["schema_version"]),
        market=(
            None
            if raw.get("market") is None
            else str(raw["market"])
        ),
        exchange_time_ms=(
            None
            if raw.get("exchange_time_ms") is None
            else int(raw["exchange_time_ms"])
        ),
        event_key=(
            None
            if raw.get("event_key") is None
            else str(raw["event_key"])
        ),
        payload_json=str(raw["payload_json"]),
        event_kind=(
            None
            if raw.get("event_kind") is None
            else str(raw["event_kind"])
        ),
    )


def _position_action_payload(
    action: PositionAction,
) -> dict[str, object]:
    return {
        "action_type": action.action_type.value,
        "market": action.market.canonical,
        "quantity": (
            None if action.quantity is None else str(action.quantity)
        ),
        "new_stop_price": (
            None
            if action.new_stop_price is None
            else str(action.new_stop_price)
        ),
        "reason_codes": list(action.reason_codes),
        "timestamp_ms": action.timestamp_ms,
    }


def _position_action_from_payload(raw: object) -> PositionAction:
    if not isinstance(raw, dict):
        raise ValueError("shadow position action must be an object")
    reason_codes = raw.get("reason_codes")
    if not isinstance(reason_codes, list) or not all(
        isinstance(value, str) for value in reason_codes
    ):
        raise ValueError("shadow position action reasons are invalid")
    quantity = raw.get("quantity")
    stop = raw.get("new_stop_price")
    return PositionAction(
        action_type=PositionActionType(str(raw["action_type"])),
        market=_market_from_canonical(str(raw["market"])),
        quantity=(
            None if quantity is None else Decimal(str(quantity))
        ),
        new_stop_price=(
            None if stop is None else Decimal(str(stop))
        ),
        reason_codes=tuple(reason_codes),
        timestamp_ms=int(raw["timestamp_ms"]),
    )


def _lifecycle_payload(
    checkpoint: OpenLifecycleCheckpoint,
) -> dict[str, object]:
    return {
        "market": checkpoint.market.canonical,
        "opening_plan_id": checkpoint.opening_plan_id,
        "feature_snapshot_id": checkpoint.feature_snapshot_id,
        "equity_before": str(checkpoint.equity_before),
        "opened_at_ms": checkpoint.opened_at_ms,
        "exit_plan_ids": list(checkpoint.exit_plan_ids),
        "position_actions": [
            _position_action_payload(action)
            for action in checkpoint.position_actions
        ],
        "mark_observations": [
            _record_payload(record)
            for record in checkpoint.mark_observations
        ],
    }


def _lifecycle_from_payload(raw: object) -> OpenLifecycleCheckpoint:
    if not isinstance(raw, dict):
        raise ValueError("shadow lifecycle checkpoint must be an object")
    exit_plan_ids = raw.get("exit_plan_ids")
    actions = raw.get("position_actions")
    marks = raw.get("mark_observations")
    if not isinstance(exit_plan_ids, list) or not all(
        isinstance(value, str) for value in exit_plan_ids
    ):
        raise ValueError("shadow exit plan ids are invalid")
    if not isinstance(actions, list) or not isinstance(marks, list):
        raise ValueError("shadow lifecycle arrays are invalid")
    opened_at = raw.get("opened_at_ms")
    return OpenLifecycleCheckpoint(
        market=_market_from_canonical(str(raw["market"])),
        opening_plan_id=str(raw["opening_plan_id"]),
        feature_snapshot_id=str(raw["feature_snapshot_id"]),
        equity_before=Decimal(str(raw["equity_before"])),
        opened_at_ms=(
            None if opened_at is None else int(opened_at)
        ),
        exit_plan_ids=tuple(exit_plan_ids),
        position_actions=tuple(
            _position_action_from_payload(item) for item in actions
        ),
        mark_observations=tuple(
            _record_from_payload(item) for item in marks
        ),
    )


def _restore_open_lifecycles(
    pipeline: BaselineReplayPipeline,
    execution: PaperExecutionAdapter,
    checkpoints: tuple[OpenLifecycleCheckpoint, ...],
) -> None:
    account_markets = {
        position.market.canonical
        for position in execution.account.positions
    }
    checkpoint_markets = {
        item.market.canonical for item in checkpoints
    }
    if account_markets != checkpoint_markets:
        raise RuntimeError(
            "paired shadow account/lifecycle checkpoint mismatch"
        )

    for checkpoint in checkpoints:
        opening_plan = execution.store.load_plan(
            checkpoint.opening_plan_id
        )
        if opening_plan is None:
            raise RuntimeError(
                "paired shadow opening plan missing during restore"
            )
        opening_attempts, opening_fills = (
            execution.store.load_execution_history(
                opening_plan.plan_id
            )
        )
        filled = tuple(
            attempt
            for attempt in opening_attempts
            if attempt.filled_quantity > ZERO
        )
        if len(filled) != 1:
            raise RuntimeError(
                "paired shadow restore requires one filled opening attempt"
            )
        opening_attempt: ExecutionAttempt = filled[0]
        opening_attempt_fills = tuple(
            fill
            for fill in opening_fills
            if fill.attempt_id == opening_attempt.attempt_id
        )

        exit_plans: list[PaperOrderPlan] = []
        exit_attempts: list[ExecutionAttempt] = []
        exit_fills: list[PaperFill] = []
        for plan_id in checkpoint.exit_plan_ids:
            plan = execution.store.load_plan(plan_id)
            if plan is None:
                raise RuntimeError(
                    "paired shadow exit plan missing during restore"
                )
            exit_plans.append(plan)
            attempts, fills = execution.store.load_execution_history(
                plan_id
            )
            exit_attempts.extend(attempts)
            exit_fills.extend(fills)

        position = next(
            position
            for position in execution.account.positions
            if position.market == checkpoint.market
        )
        funding = execution.store.load_funding_for_market(
            checkpoint.market,
            start_ms=position.opened_at_ms,
        )
        pipeline.restore_open_lifecycle(
            checkpoint,
            opening_plan=opening_plan,
            opening_attempt=opening_attempt,
            opening_fills=opening_attempt_fills,
            exit_plans=tuple(exit_plans),
            exit_attempts=tuple(exit_attempts),
            exit_fills=tuple(exit_fills),
            funding_accruals=funding,
        )


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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


@dataclass(slots=True)
class _LaneOffsets:
    closed_trade_count: int = 0
    risk_evaluations: int = 0
    risk_approvals: int = 0
    risk_rejections: int = 0
    opening_execution_attempts: int = 0
    opening_fills: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "closed_trade_count": self.closed_trade_count,
            "risk_evaluations": self.risk_evaluations,
            "risk_approvals": self.risk_approvals,
            "risk_rejections": self.risk_rejections,
            "opening_execution_attempts": self.opening_execution_attempts,
            "opening_fills": self.opening_fills,
        }

    @classmethod
    def from_payload(cls, raw: object) -> "_LaneOffsets":
        if not isinstance(raw, dict):
            raise ValueError("shadow lane offsets must be an object")
        values: dict[str, int] = {}
        for field in (
            "closed_trade_count",
            "risk_evaluations",
            "risk_approvals",
            "risk_rejections",
            "opening_execution_attempts",
            "opening_fills",
        ):
            value = raw.get(field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(
                    f"shadow lane offset {field} must be an integer"
                )
            if value < 0:
                raise ValueError(
                    f"shadow lane offset {field} must be non-negative"
                )
            values[field] = value
        return cls(**values)


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
