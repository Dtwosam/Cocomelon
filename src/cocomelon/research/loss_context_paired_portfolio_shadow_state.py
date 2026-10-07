from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.execution import (
    ExecutionAttempt,
    PaperFill,
    PaperOrderPlan,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.evidence.lifecycle import (
    BaselineReplayPipeline,
    OpenLifecycleCheckpoint,
    SessionDecisionActivity,
)
from cocomelon.execution.paper import PaperExecutionAdapter

LOSS_CONTEXT_PAIRED_SHADOW_STATE_SCHEMA_VERSION: Final = 1


class LossContextPairedShadowStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LaneTotals:
    closed_trade_count: int = 0
    risk_evaluations: int = 0
    risk_approvals: int = 0
    risk_rejections: int = 0
    opening_execution_attempts: int = 0
    opening_fills: int = 0

    def __post_init__(self) -> None:
        for field in (
            "closed_trade_count",
            "risk_evaluations",
            "risk_approvals",
            "risk_rejections",
            "opening_execution_attempts",
            "opening_fills",
        ):
            value = getattr(self, field)
            if value < 0:
                raise ValueError(f"{field} must be non-negative")

    def plus_activity(
        self,
        activity: SessionDecisionActivity,
        *,
        closed_trade_count: int,
    ) -> LaneTotals:
        if closed_trade_count < 0:
            raise ValueError("closed_trade_count must be non-negative")
        return LaneTotals(
            closed_trade_count=(
                self.closed_trade_count + closed_trade_count
            ),
            risk_evaluations=(
                self.risk_evaluations + activity.risk_evaluations
            ),
            risk_approvals=(
                self.risk_approvals + activity.risk_approvals
            ),
            risk_rejections=(
                self.risk_rejections + activity.risk_rejections
            ),
            opening_execution_attempts=(
                self.opening_execution_attempts
                + activity.opening_execution_attempts
            ),
            opening_fills=self.opening_fills + activity.opening_fills,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "closed_trade_count": self.closed_trade_count,
            "risk_evaluations": self.risk_evaluations,
            "risk_approvals": self.risk_approvals,
            "risk_rejections": self.risk_rejections,
            "opening_execution_attempts": (
                self.opening_execution_attempts
            ),
            "opening_fills": self.opening_fills,
        }


@dataclass(frozen=True, slots=True)
class RestoredPairedShadowState:
    record_count: int
    last_record_available_at_ms: int | None
    baseline_max_drawdown: Decimal
    candidate_max_drawdown: Decimal
    baseline_totals: LaneTotals
    candidate_totals: LaneTotals
    baseline_admission: dict[str, object]
    candidate_admission: dict[str, object]
    baseline_checkpoints: tuple[OpenLifecycleCheckpoint, ...]
    candidate_checkpoints: tuple[OpenLifecycleCheckpoint, ...]
    baseline_gap_intervals: tuple[tuple[int, int | None], ...]
    candidate_gap_intervals: tuple[tuple[int, int | None], ...]
    baseline_account_updated_at_ms: int
    candidate_account_updated_at_ms: int


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


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise LossContextPairedShadowStateError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise LossContextPairedShadowStateError(
            f"{field} must be an array"
        )
    return tuple(value)


def _nonnegative_int(value: object, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise LossContextPairedShadowStateError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LossContextPairedShadowStateError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise LossContextPairedShadowStateError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise LossContextPairedShadowStateError(
            f"{field} must be finite"
        )
    return result


def _market_from_canonical(value: object) -> MarketId:
    if not isinstance(value, str) or not value:
        raise LossContextPairedShadowStateError(
            "checkpoint market must be a non-empty string"
        )
    if ":" not in value:
        return MarketId("", value)
    dex, _coin = value.split(":", 1)
    return MarketId.from_wire_name(dex, value)


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
    payload = _mapping(raw, "replay record")
    return ReplayRecord(
        record_kind=SourceRecordKind(str(payload["record_kind"])),
        available_at_ms=_nonnegative_int(
            payload.get("available_at_ms"),
            "record available_at_ms",
        ),
        source=str(payload["source"]),
        schema_version=_nonnegative_int(
            payload.get("schema_version"),
            "record schema_version",
        ),
        market=(
            None
            if payload.get("market") is None
            else str(payload["market"])
        ),
        exchange_time_ms=(
            None
            if payload.get("exchange_time_ms") is None
            else _nonnegative_int(
                payload.get("exchange_time_ms"),
                "record exchange_time_ms",
            )
        ),
        event_key=(
            None
            if payload.get("event_key") is None
            else str(payload["event_key"])
        ),
        payload_json=str(payload["payload_json"]),
        event_kind=(
            None
            if payload.get("event_kind") is None
            else str(payload["event_kind"])
        ),
    )


def _action_payload(action: PositionAction) -> dict[str, object]:
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


def _action_from_payload(raw: object) -> PositionAction:
    payload = _mapping(raw, "position action")
    reasons = _sequence(payload.get("reason_codes"), "reason_codes")
    if not all(isinstance(item, str) and item for item in reasons):
        raise LossContextPairedShadowStateError(
            "position action reason_codes are invalid"
        )
    return PositionAction(
        action_type=PositionActionType(str(payload["action_type"])),
        market=_market_from_canonical(payload.get("market")),
        quantity=(
            None
            if payload.get("quantity") is None
            else _decimal(payload.get("quantity"), "quantity")
        ),
        new_stop_price=(
            None
            if payload.get("new_stop_price") is None
            else _decimal(
                payload.get("new_stop_price"),
                "new_stop_price",
            )
        ),
        reason_codes=tuple(cast(tuple[str, ...], reasons)),
        timestamp_ms=_nonnegative_int(
            payload.get("timestamp_ms"),
            "position action timestamp_ms",
        ),
    )


def _checkpoint_payload(
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
            _action_payload(item)
            for item in checkpoint.position_actions
        ],
        "mark_observations": [
            _record_payload(item)
            for item in checkpoint.mark_observations
        ],
    }


def _checkpoint_from_payload(raw: object) -> OpenLifecycleCheckpoint:
    payload = _mapping(raw, "open lifecycle checkpoint")
    exit_plan_ids = _sequence(
        payload.get("exit_plan_ids"),
        "exit_plan_ids",
    )
    if not all(
        isinstance(item, str) and item for item in exit_plan_ids
    ):
        raise LossContextPairedShadowStateError(
            "exit_plan_ids are invalid"
        )
    return OpenLifecycleCheckpoint(
        market=_market_from_canonical(payload.get("market")),
        opening_plan_id=str(payload["opening_plan_id"]),
        feature_snapshot_id=str(payload["feature_snapshot_id"]),
        equity_before=_decimal(
            payload.get("equity_before"),
            "equity_before",
        ),
        opened_at_ms=(
            None
            if payload.get("opened_at_ms") is None
            else _nonnegative_int(
                payload.get("opened_at_ms"),
                "opened_at_ms",
            )
        ),
        exit_plan_ids=tuple(cast(tuple[str, ...], exit_plan_ids)),
        position_actions=tuple(
            _action_from_payload(item)
            for item in _sequence(
                payload.get("position_actions"),
                "position_actions",
            )
        ),
        mark_observations=tuple(
            _record_from_payload(item)
            for item in _sequence(
                payload.get("mark_observations"),
                "mark_observations",
            )
        ),
    )


def _gap_payload(
    intervals: tuple[tuple[int, int | None], ...],
) -> list[list[int | None]]:
    return [
        [started_at_ms, ended_at_ms]
        for started_at_ms, ended_at_ms in intervals
    ]


def _gaps_from_payload(
    value: object,
) -> tuple[tuple[int, int | None], ...]:
    intervals: list[tuple[int, int | None]] = []
    for raw in _sequence(value, "gap_intervals"):
        item = _sequence(raw, "gap interval")
        if len(item) != 2:
            raise LossContextPairedShadowStateError(
                "gap interval must contain two values"
            )
        started_at_ms = _nonnegative_int(
            item[0],
            "gap started_at_ms",
        )
        ended_at_ms = (
            None
            if item[1] is None
            else _nonnegative_int(
                item[1],
                "gap ended_at_ms",
            )
        )
        if ended_at_ms is not None and ended_at_ms < started_at_ms:
            raise LossContextPairedShadowStateError(
                "gap interval end precedes start"
            )
        intervals.append((started_at_ms, ended_at_ms))
    return tuple(intervals)


def _totals_from_payload(value: object) -> LaneTotals:
    payload = _mapping(value, "lane totals")
    return LaneTotals(
        closed_trade_count=_nonnegative_int(
            payload.get("closed_trade_count"),
            "closed_trade_count",
        ),
        risk_evaluations=_nonnegative_int(
            payload.get("risk_evaluations"),
            "risk_evaluations",
        ),
        risk_approvals=_nonnegative_int(
            payload.get("risk_approvals"),
            "risk_approvals",
        ),
        risk_rejections=_nonnegative_int(
            payload.get("risk_rejections"),
            "risk_rejections",
        ),
        opening_execution_attempts=_nonnegative_int(
            payload.get("opening_execution_attempts"),
            "opening_execution_attempts",
        ),
        opening_fills=_nonnegative_int(
            payload.get("opening_fills"),
            "opening_fills",
        ),
    )


def build_paired_shadow_state_payload(
    *,
    candidate_id: str,
    replay_config_digest: str,
    selected_markets: tuple[MarketId, ...],
    record_count: int,
    last_record_available_at_ms: int | None,
    baseline_max_drawdown: Decimal,
    candidate_max_drawdown: Decimal,
    baseline_totals: LaneTotals,
    candidate_totals: LaneTotals,
    baseline_admission: dict[str, object],
    candidate_admission: dict[str, object],
    baseline_pipeline: BaselineReplayPipeline,
    candidate_pipeline: BaselineReplayPipeline,
    baseline_execution: PaperExecutionAdapter,
    candidate_execution: PaperExecutionAdapter,
) -> dict[str, object]:
    if record_count < 0:
        raise ValueError("record_count must be non-negative")
    if last_record_available_at_ms is not None and (
        last_record_available_at_ms < 0
    ):
        raise ValueError(
            "last_record_available_at_ms must be non-negative"
        )
    for value, field in (
        (baseline_max_drawdown, "baseline_max_drawdown"),
        (candidate_max_drawdown, "candidate_max_drawdown"),
    ):
        if not value.is_finite() or value < 0:
            raise ValueError(f"{field} must be non-negative and finite")

    payload: dict[str, object] = {
        "candidate_id": candidate_id,
        "replay_config_digest": replay_config_digest,
        "selected_markets": [
            market.canonical for market in selected_markets
        ],
        "record_count": record_count,
        "last_record_available_at_ms": last_record_available_at_ms,
        "baseline_max_drawdown": str(baseline_max_drawdown),
        "candidate_max_drawdown": str(candidate_max_drawdown),
        "baseline_totals": baseline_totals.to_dict(),
        "candidate_totals": candidate_totals.to_dict(),
        "baseline_admission": baseline_admission,
        "candidate_admission": candidate_admission,
        "baseline_account_updated_at_ms": (
            baseline_execution.account.updated_at_ms
        ),
        "candidate_account_updated_at_ms": (
            candidate_execution.account.updated_at_ms
        ),
        "baseline_open_lifecycles": [
            _checkpoint_payload(item)
            for item in baseline_pipeline.open_lifecycle_checkpoints
        ],
        "candidate_open_lifecycles": [
            _checkpoint_payload(item)
            for item in candidate_pipeline.open_lifecycle_checkpoints
        ],
        "baseline_gap_intervals": _gap_payload(
            baseline_pipeline.known_gap_intervals
        ),
        "candidate_gap_intervals": _gap_payload(
            candidate_pipeline.known_gap_intervals
        ),
        "resume_requires_warmup": True,
        "research_only": True,
        "shadow_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
        "schema_version": LOSS_CONTEXT_PAIRED_SHADOW_STATE_SCHEMA_VERSION,
    }
    return {**payload, "state_digest": _state_digest(payload)}


def write_paired_shadow_state(
    path: str | Path,
    payload: dict[str, object],
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.tmp"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def load_paired_shadow_state(
    path: str | Path,
    *,
    expected_candidate_id: str,
    expected_replay_config_digest: str,
    expected_selected_markets: tuple[MarketId, ...],
) -> RestoredPairedShadowState:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LossContextPairedShadowStateError(
            "paired shadow state is missing or invalid"
        ) from exc
    payload = _mapping(raw, "paired shadow state")
    state_digest = payload.pop("state_digest", None)
    if (
        not isinstance(state_digest, str)
        or state_digest != _state_digest(payload)
    ):
        raise LossContextPairedShadowStateError(
            "paired shadow state digest mismatch"
        )
    if (
        _nonnegative_int(
            payload.get("schema_version"),
            "schema_version",
        )
        != LOSS_CONTEXT_PAIRED_SHADOW_STATE_SCHEMA_VERSION
    ):
        raise LossContextPairedShadowStateError(
            "paired shadow state schema mismatch"
        )
    if payload.get("candidate_id") != expected_candidate_id:
        raise LossContextPairedShadowStateError(
            "paired shadow candidate identity mismatch"
        )
    if (
        payload.get("replay_config_digest")
        != expected_replay_config_digest
    ):
        raise LossContextPairedShadowStateError(
            "paired shadow replay configuration mismatch"
        )
    expected_markets = tuple(
        market.canonical for market in expected_selected_markets
    )
    raw_markets = _sequence(
        payload.get("selected_markets"),
        "selected_markets",
    )
    if tuple(str(item) for item in raw_markets) != expected_markets:
        raise LossContextPairedShadowStateError(
            "paired shadow selected markets mismatch"
        )
    if payload.get("resume_requires_warmup") is not True:
        raise LossContextPairedShadowStateError(
            "paired shadow warmup contract mismatch"
        )
    for field in ("research_only", "shadow_only"):
        if payload.get(field) is not True:
            raise LossContextPairedShadowStateError(
                "paired shadow authority metadata invalid"
            )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "changes_positions",
        "promotion_authority",
        "execution_authority",
    ):
        if payload.get(field) is not False:
            raise LossContextPairedShadowStateError(
                "paired shadow state carries forbidden authority"
            )

    last_raw = payload.get("last_record_available_at_ms")
    last_record_available_at_ms = (
        None
        if last_raw is None
        else _nonnegative_int(
            last_raw,
            "last_record_available_at_ms",
        )
    )
    return RestoredPairedShadowState(
        record_count=_nonnegative_int(
            payload.get("record_count"),
            "record_count",
        ),
        last_record_available_at_ms=last_record_available_at_ms,
        baseline_max_drawdown=_decimal(
            payload.get("baseline_max_drawdown"),
            "baseline_max_drawdown",
        ),
        candidate_max_drawdown=_decimal(
            payload.get("candidate_max_drawdown"),
            "candidate_max_drawdown",
        ),
        baseline_totals=_totals_from_payload(
            payload.get("baseline_totals")
        ),
        candidate_totals=_totals_from_payload(
            payload.get("candidate_totals")
        ),
        baseline_admission=_mapping(
            payload.get("baseline_admission"),
            "baseline_admission",
        ),
        candidate_admission=_mapping(
            payload.get("candidate_admission"),
            "candidate_admission",
        ),
        baseline_checkpoints=tuple(
            _checkpoint_from_payload(item)
            for item in _sequence(
                payload.get("baseline_open_lifecycles"),
                "baseline_open_lifecycles",
            )
        ),
        candidate_checkpoints=tuple(
            _checkpoint_from_payload(item)
            for item in _sequence(
                payload.get("candidate_open_lifecycles"),
                "candidate_open_lifecycles",
            )
        ),
        baseline_gap_intervals=_gaps_from_payload(
            payload.get("baseline_gap_intervals")
        ),
        candidate_gap_intervals=_gaps_from_payload(
            payload.get("candidate_gap_intervals")
        ),
        baseline_account_updated_at_ms=_nonnegative_int(
            payload.get("baseline_account_updated_at_ms"),
            "baseline_account_updated_at_ms",
        ),
        candidate_account_updated_at_ms=_nonnegative_int(
            payload.get("candidate_account_updated_at_ms"),
            "candidate_account_updated_at_ms",
        ),
    )


def restore_lane_from_state(
    pipeline: BaselineReplayPipeline,
    execution: PaperExecutionAdapter,
    *,
    checkpoints: tuple[OpenLifecycleCheckpoint, ...],
    gap_intervals: tuple[tuple[int, int | None], ...],
    expected_account_updated_at_ms: int,
) -> None:
    if execution.account.updated_at_ms != expected_account_updated_at_ms:
        raise LossContextPairedShadowStateError(
            "paired shadow execution/account checkpoint mismatch"
        )
    account_markets = {
        position.market.canonical
        for position in execution.account.positions
    }
    checkpoint_markets = {
        checkpoint.market.canonical for checkpoint in checkpoints
    }
    if account_markets != checkpoint_markets:
        raise LossContextPairedShadowStateError(
            "paired shadow account/open-lifecycle mismatch"
        )

    pipeline.restore_gap_intervals(gap_intervals)
    for checkpoint in checkpoints:
        opening_plan = execution.store.load_plan(
            checkpoint.opening_plan_id
        )
        if opening_plan is None:
            raise LossContextPairedShadowStateError(
                "paired shadow opening plan missing during restore"
            )
        opening_attempts, opening_fills = (
            execution.store.load_execution_history(
                opening_plan.plan_id
            )
        )
        filled_opening_attempts = tuple(
            attempt
            for attempt in opening_attempts
            if attempt.filled_quantity > 0
        )
        if len(filled_opening_attempts) != 1:
            raise LossContextPairedShadowStateError(
                "paired shadow restore requires one opening fill attempt"
            )
        opening_attempt: ExecutionAttempt = filled_opening_attempts[0]
        matched_opening_fills: tuple[PaperFill, ...] = tuple(
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
                raise LossContextPairedShadowStateError(
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
            opening_fills=matched_opening_fills,
            exit_plans=tuple(exit_plans),
            exit_attempts=tuple(exit_attempts),
            exit_fills=tuple(exit_fills),
            funding_accruals=funding,
        )
