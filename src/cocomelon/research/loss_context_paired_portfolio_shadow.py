from __future__ import annotations

import hashlib
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
from cocomelon.research.loss_context_paired_shadow_review import (
    LOSS_CONTEXT_PAIRED_SHADOW_REVIEW_LEDGER_FILENAME,
    append_review_checkpoint,
    review_ledger_receipt,
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


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _state_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


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
    def from_payload(cls, raw: object) -> _LaneOffsets:
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
        self._root = root
        self._state_path = (
            root / LOSS_CONTEXT_PAIRED_SHADOW_STATE_FILENAME
        )
        self._review_ledger_path = (
            root / LOSS_CONTEXT_PAIRED_SHADOW_REVIEW_LEDGER_FILENAME
        )
        self._markets = markets
        baseline_execution_path = root / "baseline-execution.sqlite3"
        candidate_execution_path = root / "candidate-execution.sqlite3"
        state_exists = self._state_path.exists()
        baseline_execution_exists = baseline_execution_path.exists()
        candidate_execution_exists = candidate_execution_path.exists()
        if state_exists and not (
            baseline_execution_exists and candidate_execution_exists
        ):
            raise RuntimeError(
                "paired shadow checkpoint exists without both execution stores"
            )
        if not state_exists and (
            baseline_execution_exists or candidate_execution_exists
        ):
            raise RuntimeError(
                "paired shadow execution store exists without checkpoint"
            )
        self._freeze = freeze
        self._config = replay_config
        self._record_count = 0
        self._last_record_available_at_ms: int | None = None
        self._baseline_max_drawdown = ZERO
        self._candidate_max_drawdown = ZERO
        self._baseline_offsets = _LaneOffsets()
        self._candidate_offsets = _LaneOffsets()
        self._restored_from_checkpoint = False
        self._restore_warmup_required = False

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
            baseline_execution_path,
            replay_config.execution,
            starting_cash=replay_config.starting_cash,
            startup_timestamp_ms=startup_timestamp_ms,
        )
        self._candidate_execution = PaperExecutionAdapter(
            candidate_execution_path,
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
        self._restore_state_if_present()

    @staticmethod
    def _nonnegative_int(raw: object, field: str) -> int:
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError(f"{field} must be a non-negative integer")
        return raw

    @staticmethod
    def _gap_intervals_from_payload(
        raw: object,
    ) -> tuple[tuple[int, int | None], ...]:
        if not isinstance(raw, list):
            raise ValueError("shadow gap intervals must be an array")
        intervals: list[tuple[int, int | None]] = []
        for item in raw:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError("shadow gap interval is invalid")
            started = int(item[0])
            ended = None if item[1] is None else int(item[1])
            if started < 0 or (ended is not None and ended < started):
                raise ValueError("shadow gap interval chronology is invalid")
            intervals.append((started, ended))
        return tuple(intervals)

    @staticmethod
    def _restore_filter_counts(
        filter_: LossContextPortfolioShadowEntryFilter,
        raw: object,
    ) -> None:
        if not isinstance(raw, dict):
            raise ValueError("shadow admission state must be an object")
        for field in (
            "pre_boundary_blocked",
            "matching_context_blocked",
            "admitted_after_boundary",
        ):
            value = raw.get(field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(
                    f"shadow admission {field} must be an integer"
                )
            if value < 0:
                raise ValueError(
                    f"shadow admission {field} must be non-negative"
                )
            setattr(filter_, field, value)
        blocked_by_market = raw.get("matching_context_blocked_by_market")
        if blocked_by_market is None:
            filter_.matching_context_blocked_by_market = {}
        elif not isinstance(blocked_by_market, dict):
            raise ValueError(
                "shadow admission blocked-by-market must be an object"
            )
        else:
            restored: dict[str, int] = {}
            for market, value in blocked_by_market.items():
                if not isinstance(market, str) or not market:
                    raise ValueError(
                        "shadow admission blocked market is invalid"
                    )
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 0
                ):
                    raise ValueError(
                        "shadow admission blocked market count is invalid"
                    )
                restored[market] = value
            if sum(restored.values()) != filter_.matching_context_blocked:
                raise ValueError(
                    "shadow admission blocked market counts do not reconcile"
                )
            filter_.matching_context_blocked_by_market = dict(
                sorted(restored.items())
            )

    def _restore_lane(
        self,
        *,
        raw: object,
        pipeline: BaselineReplayPipeline,
        execution: PaperExecutionAdapter,
    ) -> tuple[_LaneOffsets, Decimal]:
        if not isinstance(raw, dict):
            raise ValueError("shadow lane state must be an object")
        account_state_id = raw.get("account_state_id")
        if (
            not isinstance(account_state_id, str)
            or account_state_id != execution.account.state_id
        ):
            raise RuntimeError(
                "paired shadow durable account state mismatch"
            )
        lifecycle_raw = raw.get("open_lifecycles")
        if not isinstance(lifecycle_raw, list):
            raise ValueError(
                "shadow open_lifecycles must be an array"
            )
        checkpoints = tuple(
            _lifecycle_from_payload(item) for item in lifecycle_raw
        )
        pipeline.restore_gap_intervals(
            self._gap_intervals_from_payload(
                raw.get("known_gap_intervals")
            )
        )
        _restore_open_lifecycles(
            pipeline,
            execution,
            checkpoints,
        )
        max_drawdown = Decimal(str(raw.get("max_drawdown_fraction")))
        if (
            not max_drawdown.is_finite()
            or max_drawdown < ZERO
            or max_drawdown > Decimal("1")
        ):
            raise ValueError(
                "shadow max drawdown must be in [0, 1]"
            )
        return (
            _LaneOffsets.from_payload(raw.get("cumulative_activity")),
            max_drawdown,
        )

    def _restore_state_if_present(self) -> None:
        if not self._state_path.exists():
            return
        try:
            raw = json.loads(
                self._state_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "paired shadow durable state is unreadable"
            ) from exc
        if not isinstance(raw, dict):
            raise ValueError("paired shadow durable state must be an object")
        unsigned = dict(raw)
        state_digest = unsigned.pop("state_digest", None)
        if (
            not isinstance(state_digest, str)
            or state_digest != _state_digest(unsigned)
        ):
            raise RuntimeError(
                "paired shadow durable state digest mismatch"
            )
        raw = unsigned
        if (
            raw.get("schema_version")
            != LOSS_CONTEXT_PAIRED_SHADOW_STATE_SCHEMA_VERSION
        ):
            raise ValueError("paired shadow durable state schema mismatch")
        if raw.get("portfolio_shadow_candidate_id") != self._freeze.candidate_id:
            raise RuntimeError(
                "paired shadow durable candidate identity mismatch"
            )
        if raw.get("replay_config_digest") != self._config.config_digest:
            raise RuntimeError(
                "paired shadow durable replay configuration mismatch"
            )
        selected_markets = raw.get("selected_markets")
        if (
            not isinstance(selected_markets, list)
            or tuple(str(item) for item in selected_markets)
            != tuple(market.canonical for market in self._markets)
        ):
            raise RuntimeError(
                "paired shadow durable selected markets mismatch"
            )
        if raw.get("handoff_safe") is not True:
            raise RuntimeError(
                "paired shadow durable state was not handoff-safe"
            )
        if raw.get("pending_opening_state_persisted") is not False:
            raise RuntimeError(
                "paired shadow pending-opening contract mismatch"
            )
        for field in (
            "research_only",
            "shadow_only",
            "paper_only",
        ):
            if raw.get(field) is not True:
                raise RuntimeError(
                    "paired shadow durable authority mismatch"
                )
        for field in (
            "changes_strategy",
            "changes_risk_limits",
            "changes_positions",
            "promotion_authority",
            "execution_authority",
        ):
            if raw.get(field) is not False:
                raise RuntimeError(
                    "paired shadow durable authority mismatch"
                )

        review_count = raw.get("review_ledger_row_count")
        review_digest = raw.get("review_ledger_latest_row_digest")
        if review_count is None and review_digest is None:
            if (
                self._review_ledger_path.exists()
                and self._review_ledger_path.stat().st_size > 0
            ):
                raise RuntimeError(
                    "paired shadow review ledger exists without receipt"
                )
        elif (
            isinstance(review_count, bool)
            or not isinstance(review_count, int)
            or review_count < 0
            or (
                review_digest is not None
                and not isinstance(review_digest, str)
            )
        ):
            raise RuntimeError(
                "paired shadow review ledger receipt is invalid"
            )
        else:
            receipt = review_ledger_receipt(
                self._review_ledger_path,
                candidate_id=self._freeze.candidate_id,
            )
            if (
                receipt["row_count"] != review_count
                or receipt["latest_row_digest"] != review_digest
            ):
                raise RuntimeError(
                    "paired shadow review ledger receipt mismatch"
                )

        self._record_count = self._nonnegative_int(
            raw.get("record_count"),
            "record_count",
        )
        last = raw.get("last_record_available_at_ms")
        if last is not None:
            self._last_record_available_at_ms = self._nonnegative_int(
                last,
                "last_record_available_at_ms",
            )

        baseline_raw = raw.get("baseline")
        candidate_raw = raw.get("candidate")
        (
            self._baseline_offsets,
            self._baseline_max_drawdown,
        ) = self._restore_lane(
            raw=baseline_raw,
            pipeline=self._baseline,
            execution=self._baseline_execution,
        )
        (
            self._candidate_offsets,
            self._candidate_max_drawdown,
        ) = self._restore_lane(
            raw=candidate_raw,
            pipeline=self._candidate,
            execution=self._candidate_execution,
        )
        if not isinstance(baseline_raw, dict) or not isinstance(
            candidate_raw,
            dict,
        ):
            raise ValueError("shadow lane state must be an object")
        self._restore_filter_counts(
            self._baseline_filter,
            baseline_raw.get("admission"),
        )
        self._restore_filter_counts(
            self._candidate_filter,
            candidate_raw.get("admission"),
        )
        self._restored_from_checkpoint = True
        self._restore_warmup_required = True

    def mark_restore_warmup_complete(self) -> None:
        if not self._restored_from_checkpoint:
            return
        self._restore_warmup_required = False

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
        if evaluate_decisions and self._restore_warmup_required:
            raise RuntimeError(
                "restored paired shadow requires decision-state warmup"
            )
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

    def reconcile_markets(
        self,
        selected_markets: Sequence[MarketId],
    ) -> None:
        markets = tuple(
            sorted(
                selected_markets,
                key=lambda item: item.canonical,
            )
        )
        if not markets:
            raise ValueError("selected_markets must not be empty")
        selected_keys = {market.canonical for market in markets}
        protected_keys = {
            position.market.canonical
            for position in (
                *self._baseline_execution.account.positions,
                *self._candidate_execution.account.positions,
            )
        }
        missing = tuple(sorted(protected_keys - selected_keys))
        if missing:
            raise RuntimeError(
                "paired shadow market reconciliation would drop open "
                "shadow position coverage: "
                + ",".join(missing)
            )
        self._baseline.reconcile_markets(markets)
        self._candidate.reconcile_markets(markets)
        self._markets = markets

    def _lane_state_payload(
        self,
        *,
        pipeline: BaselineReplayPipeline,
        execution: PaperExecutionAdapter,
        snapshot: _LaneSnapshot,
        filter_: LossContextPortfolioShadowEntryFilter,
    ) -> dict[str, object]:
        return {
            "account_state_id": execution.account.state_id,
            "max_drawdown_fraction": str(
                snapshot.max_drawdown_fraction
            ),
            "cumulative_activity": {
                "closed_trade_count": snapshot.closed_trade_count,
                "risk_evaluations": snapshot.risk_evaluations,
                "risk_approvals": snapshot.risk_approvals,
                "risk_rejections": snapshot.risk_rejections,
                "opening_execution_attempts": (
                    snapshot.opening_execution_attempts
                ),
                "opening_fills": snapshot.opening_fills,
            },
            "admission": {
                "pre_boundary_blocked": (
                    filter_.pre_boundary_blocked
                ),
                "matching_context_blocked": (
                    filter_.matching_context_blocked
                ),
                "matching_context_blocked_by_market": dict(
                    sorted(
                        filter_.matching_context_blocked_by_market.items()
                    )
                ),
                "admitted_after_boundary": (
                    filter_.admitted_after_boundary
                ),
            },
            "open_lifecycles": [
                _lifecycle_payload(item)
                for item in pipeline.open_lifecycle_checkpoints
            ],
            "known_gap_intervals": [
                [started_ms, ended_ms]
                for started_ms, ended_ms
                in pipeline.known_gap_intervals
            ],
        }

    def _review_checkpoint_payload(
        self,
        *,
        end_ms: int,
        baseline: _LaneSnapshot,
        candidate: _LaneSnapshot,
    ) -> dict[str, object]:
        return {
            "portfolio_shadow_candidate_id": self._freeze.candidate_id,
            "loss_context_candidate_id": (
                self._freeze.loss_context_candidate_id
            ),
            "prospective_not_before_ms": (
                self._freeze.prospective_not_before_ms
            ),
            "end_ms": end_ms,
            "record_count": self._record_count,
            "last_record_available_at_ms": (
                self._last_record_available_at_ms
            ),
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
            "research_only": True,
            "shadow_only": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "changes_positions": False,
            "promotion_authority": False,
            "execution_authority": False,
        }

    def checkpoint(self, *, end_ms: int) -> dict[str, object]:
        if end_ms < 0:
            raise ValueError("end_ms must be non-negative")
        self.assert_handoff_safe()
        if self._restore_warmup_required:
            raise RuntimeError(
                "paired shadow cannot checkpoint before restore warmup"
            )
        self._update_drawdowns()
        baseline = self._lane_snapshot(
            self._baseline,
            self._baseline_execution,
            max_drawdown=self._baseline_max_drawdown,
            offsets=self._baseline_offsets,
            end_ms=end_ms,
        )
        candidate = self._lane_snapshot(
            self._candidate,
            self._candidate_execution,
            max_drawdown=self._candidate_max_drawdown,
            offsets=self._candidate_offsets,
            end_ms=end_ms,
        )
        # Materialize both current account snapshots even when a lane has
        # made no trade. Otherwise an intentionally empty candidate lane
        # cannot be distinguished from a fresh account after restart.
        self._baseline_execution.store.persist_account(
            self._baseline_execution.account
        )
        self._candidate_execution.store.persist_account(
            self._candidate_execution.account
        )
        review_receipt = append_review_checkpoint(
            self._review_ledger_path,
            self._review_checkpoint_payload(
                end_ms=end_ms,
                baseline=baseline,
                candidate=candidate,
            ),
        )
        payload: dict[str, object] = {
            "portfolio_shadow_candidate_id": self._freeze.candidate_id,
            "loss_context_candidate_id": (
                self._freeze.loss_context_candidate_id
            ),
            "replay_config_digest": self._config.config_digest,
            "selected_markets": [
                market.canonical for market in self._markets
            ],
            "record_count": self._record_count,
            "last_record_available_at_ms": (
                self._last_record_available_at_ms
            ),
            "handoff_safe": True,
            "pending_opening_state_persisted": False,
            "review_ledger_row_count": review_receipt["row_count"],
            "review_ledger_latest_row_digest": (
                review_receipt["latest_row_digest"]
            ),
            "baseline": self._lane_state_payload(
                pipeline=self._baseline,
                execution=self._baseline_execution,
                snapshot=baseline,
                filter_=self._baseline_filter,
            ),
            "candidate": self._lane_state_payload(
                pipeline=self._candidate,
                execution=self._candidate_execution,
                snapshot=candidate,
                filter_=self._candidate_filter,
            ),
            "research_only": True,
            "shadow_only": True,
            "paper_only": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "changes_positions": False,
            "promotion_authority": False,
            "execution_authority": False,
            "schema_version": (
                LOSS_CONTEXT_PAIRED_SHADOW_STATE_SCHEMA_VERSION
            ),
        }
        payload["state_digest"] = _state_digest(payload)
        _write_json_atomic(self._state_path, payload)
        return payload

    def _lane_snapshot(
        self,
        pipeline: BaselineReplayPipeline,
        execution: PaperExecutionAdapter,
        *,
        max_drawdown: Decimal,
        offsets: _LaneOffsets,
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
            closed_trade_count=(
                offsets.closed_trade_count + len(closed)
            ),
            risk_evaluations=(
                offsets.risk_evaluations + activity.risk_evaluations
            ),
            risk_approvals=(
                offsets.risk_approvals + activity.risk_approvals
            ),
            risk_rejections=(
                offsets.risk_rejections + activity.risk_rejections
            ),
            opening_execution_attempts=(
                offsets.opening_execution_attempts
                + activity.opening_execution_attempts
            ),
            opening_fills=(
                offsets.opening_fills + activity.opening_fills
            ),
        )

    def summary_payload(self, *, end_ms: int) -> dict[str, object]:
        if end_ms < 0:
            raise ValueError("end_ms must be non-negative")
        self._update_drawdowns()
        baseline = self._lane_snapshot(
            self._baseline,
            self._baseline_execution,
            max_drawdown=self._baseline_max_drawdown,
            offsets=self._baseline_offsets,
            end_ms=end_ms,
        )
        candidate = self._lane_snapshot(
            self._candidate,
            self._candidate_execution,
            max_drawdown=self._candidate_max_drawdown,
            offsets=self._candidate_offsets,
            end_ms=end_ms,
        )
        review_receipt = review_ledger_receipt(
            self._review_ledger_path,
            candidate_id=self._freeze.candidate_id,
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
            "restored_from_checkpoint": (
                self._restored_from_checkpoint
            ),
            "restore_warmup_required": (
                self._restore_warmup_required
            ),
            "durable_state_checkpoint_exists": (
                self._state_path.exists()
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
            "review_ledger_row_count": review_receipt["row_count"],
            "review_ledger_latest_row_digest": (
                review_receipt["latest_row_digest"]
            ),
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
