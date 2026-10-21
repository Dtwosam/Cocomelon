"""Volatility-specific, inactive PAPER lifecycle using the existing execution stack.

No network, venue order endpoint, wallet, ordinary worker or activation authority.
Explicit preparation creates synthetic/review ledgers only; operational restore
requires independently held custody. Cross-store checks detect local mismatches,
not coherent rollback of an entire directory and its local witness together.
Authorization and source admission are deliberately never restored.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from pathlib import Path
from typing import Any

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
    PaperFill,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import (
    ExecutionCostEstimate,
    LiquidityRiskState,
    RiskDecision,
    RiskHealthState,
    RiskLimits,
    RiskRequest,
)
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.openings import paper_liquidation_surrogate
from cocomelon.execution.accounting import (
    PositionSide,
    mark_to_market,
    risk_state_from_paper,
)
from cocomelon.execution.funding import FundingAccrual, funding_cash_delta
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.execution.planner import (
    PlanningRejection,
    plan_opening_order,
    plan_reduce_only_order,
)
from cocomelon.execution.store import _position_from_payload, _position_payload
from cocomelon.features.microstructure import calculate_microstructure_features
from cocomelon.research.volatility_budget import (
    PROTOCOL_SHA256,
    VolatilityBudgetPlan,
    VolatilityBudgetWindow,
    evaluate_volatility_budget,
    exit_reason,
    quantity_for_plan,
)
from cocomelon.risk.engine import evaluate_risk

D = Decimal
HOUR = 3_600_000
DAY = 86_400_000
CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def _received(event: StreamEvent) -> int:
    if event.receive_time.utcoffset() is None or event.receive_time.microsecond % 1000:
        raise ValueError("original receive clock must be timezone-aware exact milliseconds")
    delta = event.receive_time - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000


def _event_payload(event: StreamEvent) -> dict[str, Any]:
    return {
        "kind": event.kind.value,
        "market": asdict(event.market),
        "exchange_time_ms": event.exchange_time_ms,
        "received_ms": _received(event),
        "source": event.source,
        "schema_version": event.schema_version,
        "event_key": event.event_key,
        "payload": dict(event.payload),
    }


def _event_from(value: dict[str, Any]) -> StreamEvent:
    return StreamEvent(
        StreamKind(value["kind"]),
        MarketId(**value["market"]),
        value["exchange_time_ms"],
        datetime.fromtimestamp(value["received_ms"] / 1000, UTC),
        value["schema_version"],
        value["source"],
        value["event_key"],
        {k: None if v is None else D(v) for k, v in value["payload"].items()},
    )


def _plan_payload(plan: VolatilityBudgetPlan) -> dict[str, Any]:
    decision = asdict(plan.decision)
    decision["direction"] = plan.decision.direction.value
    return {
        "decision": decision,
        "entry": plan.entry,
        "target": plan.target,
        "stop": plan.stop,
        "expires_at_ms": plan.expires_at_ms,
        "cost_bps": plan.cost_bps,
        "evidence_digest": plan.evidence_digest,
        "signal_direction": plan.signal_direction.value
        if plan.signal_direction is not None
        else None,
        "sigma28": plan.sigma28,
        "stop_distance_bps": plan.stop_distance_bps,
        "current_eligible": plan.current_eligible,
    }


def _plan_from(value: dict[str, Any]) -> VolatilityBudgetPlan:
    data = dict(value["decision"])
    data["market"] = MarketId(**data["market"])
    data["direction"] = Direction(data["direction"])
    data["score"] = D(data["score"])
    data["invalidation_price"] = (
        None if data["invalidation_price"] is None else D(data["invalidation_price"])
    )
    data["signal_ids"] = tuple(data["signal_ids"])
    data["reason_codes"] = tuple(data["reason_codes"])
    return VolatilityBudgetPlan(
        StrategyDecision(**data),
        None if value["entry"] is None else D(value["entry"]),
        None if value["target"] is None else D(value["target"]),
        None if value["stop"] is None else D(value["stop"]),
        value["expires_at_ms"],
        D(value["cost_bps"]),
        value["evidence_digest"],
        None if value["signal_direction"] is None else Direction(value["signal_direction"]),
        None if value["sigma28"] is None else D(value["sigma28"]),
        None if value["stop_distance_bps"] is None else D(value["stop_distance_bps"]),
        value["current_eligible"],
    )


class _TrialExecution(PaperExecutionAdapter):
    """Only this isolated account accepts verified historical boundary accruals."""

    def apply_boundary_funding(
        self, accrual: FundingAccrual, *, opening_plan_id: str, now_ms: int
    ) -> None:
        if self.store.has_funding_accrual(accrual.accrual_id):
            return
        previous = self.account
        positions = tuple(
            replace(p, cumulative_funding=p.cumulative_funding + accrual.cash_delta)
            if p.opening_plan_id == opening_plan_id
            else p
            for p in previous.positions
        )
        candidate = replace(
            previous,
            cash=previous.cash + accrual.cash_delta,
            positions=positions,
            cumulative_funding=previous.cumulative_funding + accrual.cash_delta,
            daily_realized_pnl=previous.daily_realized_pnl
            + (accrual.cash_delta if accrual.boundary_ms >= previous.day_start_ms else D(0)),
        )
        marks = {p.market: p.latest_mark or p.average_entry_price for p in positions}
        candidate = mark_to_market(candidate, marks, now_ms)
        self.store.persist_funding(accrual, candidate)
        self._account = candidate


class VolatilityPaperTrial:
    """One candidate and one NO_TRADE ledger; authorization never survives restart."""

    def __init__(
        self,
        root: Path,
        *,
        candidate_id: str,
        control_id: str,
        first_entry_ms: int | None,
        startup_ms: int,
        prepare_new: bool = False,
    ) -> None:
        if any(part.is_symlink() for part in (root, *root.parents)):
            raise ValueError("trial root symlink/alias forbidden")
        if not (root / "trial.sqlite").exists() and not prepare_new:
            raise ValueError("original trial history required; explicit preparation only")
        if prepare_new and (root / "trial.sqlite").exists():
            raise ValueError("preparation cannot reset existing trial history")
        if root.is_symlink():
            raise ValueError("trial root symlink/alias forbidden")
        root.mkdir(parents=True, exist_ok=True)
        for name in ("candidate.sqlite", "control.sqlite", "trial.sqlite", ".trial.lock"):
            path = root / name
            if path.is_symlink() or (path.exists() and path.stat().st_nlink != 1):
                raise ValueError("account store symlink/hardlink alias forbidden")
        self._closed = False
        self._lease = os.open(root / ".trial.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(self._lease)
            raise RuntimeError("trial root lease already held") from error
        try:
            accounts = (root / "candidate.sqlite", root / "control.sqlite")
            if not (root / "trial.sqlite").exists() and any(p.exists() for p in accounts):
                raise ValueError("existing account requires its original trial checkpoint")
            if (root / "trial.sqlite").exists() and any(
                not p.exists() or p.stat().st_size == 0 for p in accounts
            ):
                raise ValueError("restore account history missing or empty")
            self._initialize(
                root,
                candidate_id=candidate_id,
                control_id=control_id,
                first_entry_ms=first_entry_ms,
                startup_ms=startup_ms,
            )
        except Exception:
            self._dispose()
            raise

    def _dispose(self) -> None:
        for name in ("candidate", "control", "_db"):
            resource = getattr(self, name, None)
            if resource is not None:
                resource.close()
        fcntl.flock(self._lease, fcntl.LOCK_UN)
        os.close(self._lease)
        self._closed = True

    def _initialize(
        self,
        root: Path,
        *,
        candidate_id: str,
        control_id: str,
        first_entry_ms: int | None,
        startup_ms: int,
    ) -> None:
        if not candidate_id or not control_id or candidate_id == control_id:
            raise ValueError("distinct nonempty account identity required")
        if startup_ms < 0 or (
            first_entry_ms is not None and (first_entry_ms < 0 or first_entry_ms % DAY != 30_000)
        ):
            raise ValueError("invalid trial clock or first-entry boundary")
        root.mkdir(parents=True, exist_ok=True)
        self.entries_authorized = False
        self.source_valid = False
        self.config = PaperExecutionConfig(
            config_version="volatility-budget-paper-v1", max_position_age_ms=DAY
        )
        self._db = sqlite3.connect(root / "trial.sqlite")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY, data TEXT)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS events (ordinal INTEGER PRIMARY KEY, "
            "kind TEXT NOT NULL, time_ms INTEGER NOT NULL, data TEXT NOT NULL)"
        )
        identity = {
            "candidate_id": candidate_id,
            "control_id": control_id,
            "first_entry_ms": first_entry_ms,
            "protocol_sha256": PROTOCOL_SHA256,
        }
        row = self._db.execute("SELECT data FROM checkpoint WHERE id=1").fetchone()
        self._state: dict[str, Any] = (
            json.loads(row[0])
            if row
            else {
                "identity": identity,
                "intents": {},
                "pending": None,
                "active": None,
                "exit": None,
                "boundaries": {},
                "marks": {},
                "book_clocks": {},
                "ingress_received_ms": -1,
                "permanent": False,
                "last_epoch": -1,
                "cooldowns": {},
                "selected_market": None,
                "custody": None,
                "revision": 0,
                "now": startup_ms,
                "faults": [],
                "components": [],
            }
        )
        if self._state["identity"] != identity:
            self._db.close()
            raise ValueError("trial account identity/boundary/protocol mismatch")
        self.candidate = _TrialExecution(
            root / "candidate.sqlite",
            self.config,
            starting_cash=D(10000),
            startup_timestamp_ms=startup_ms,
        )
        self.control = PaperExecutionAdapter(
            root / "control.sqlite",
            self.config,
            starting_cash=D(10000),
            startup_timestamp_ms=startup_ms,
        )
        if not self.candidate.health.healthy_for_new_exposure:
            self._fault("CANDIDATE_STORE_UNHEALTHY")
        if (
            not self.control.health.healthy_for_new_exposure
            or self.control.account.positions
            or self.control.account.cash != D(10000)
            or self.control.store.table_counts()["paper_execution_attempts"]
        ):
            self._fault("CONTROL_ACCOUNT_MISMATCH")
        for adapter in (self.candidate, self.control):
            with adapter.store.raw_connection() as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS volatility_lifecycle_witness "
                    "(id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, digest TEXT NOT NULL)"
                )
        self._validate_custody()
        self._recover()
        self._validate_history()
        self._advance(
            max(
                startup_ms,
                self._state["now"],
                self.candidate.account.updated_at_ms,
                self.control.account.updated_at_ms,
            )
        )
        self._save()

    def _save(self) -> None:
        candidate = getattr(self, "candidate", None)
        control = getattr(self, "control", None)
        if candidate is not None and control is not None:
            self._state["custody"] = {
                "candidate": self._custody(candidate),
                "control": self._custody(control),
            }
        self._state["revision"] += 1
        encoded = _json(self._state)
        # Trial commits first: an account witness ahead of trial is never a normal
        # interrupted save, and therefore detects trial-only rollback. All-local
        # coherent rollback still requires independently held operational custody.
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO checkpoint VALUES (1,?)", (encoded,))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        for adapter in (candidate, control):
            if adapter is not None:
                with adapter.store.raw_connection() as connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO volatility_lifecycle_witness VALUES(1,?,?)",
                        (self._state["revision"], digest),
                    )

    @staticmethod
    def _custody(adapter: PaperExecutionAdapter) -> dict[str, Any]:
        return {
            "time_ms": adapter.account.updated_at_ms,
            "state_id": adapter.account.state_id,
            "counts": adapter.store.table_counts(),
        }

    def _validate_custody(self) -> None:
        witness = self._state["custody"]
        if witness is None:
            return
        expected_digest = hashlib.sha256(_json(self._state).encode()).hexdigest()
        for name in ("candidate", "control"):
            row = (
                getattr(self, name)
                .store.raw_connection()
                .execute("SELECT revision,digest FROM volatility_lifecycle_witness WHERE id=1")
                .fetchone()
            )
            if row is None:
                raise ValueError("account lifecycle custody history missing")
            if row[0] > self._state["revision"]:
                raise ValueError("trial checkpoint rollback behind account custody witness")
            if row[0] == self._state["revision"] and row[1] != expected_digest:
                raise ValueError("trial lifecycle custody digest mismatch")
            current = self._custody(getattr(self, name))
            original = witness[name]
            if current["time_ms"] < original["time_ms"] or any(
                current["counts"].get(table, 0) < count
                for table, count in original["counts"].items()
            ):
                raise ValueError("account/trial custody rollback mismatch")
            if (
                current["time_ms"] == original["time_ms"]
                and current["counts"] == original["counts"]
                and current["state_id"] != original["state_id"]
            ):
                raise ValueError("account/trial custody state mismatch")

    def _record(self, kind: str, now: int, payload: object) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO events(kind,time_ms,data) VALUES (?,?,?)", (kind, now, _json(payload))
            )

    def _fault(self, reason: str) -> None:
        self._state["permanent"] = True
        if reason not in self._state["faults"]:
            self._state["faults"].append(reason)

    def _recover(self) -> None:
        for key, intent in self._state["intents"].items():
            plan_id = intent.get("plan_id")
            if not plan_id:
                continue
            attempts, fills = self.candidate.store.load_execution_history(plan_id)
            if attempts:
                intent["status"] = "attempted"
                if self._state["pending"] == key:
                    self._state["pending"] = None
                if fills and any(
                    p.opening_plan_id == plan_id for p in self.candidate.account.positions
                ):
                    self._state["active"] = key
            elif intent["status"] == "attempting":
                # Uncertain interruption consumes this epoch; an old intent never chases.
                intent["status"] = "interrupted_no_attempt"
                self._state["pending"] = None
        positions = self.candidate.account.positions
        active = self._state["active"]
        if positions and (
            len(positions) != 1
            or active is None
            or self._state["intents"][active].get("plan_id") != positions[0].opening_plan_id
        ):
            self._fault("TRIAL_POSITION_LINEAGE_MISMATCH")
        if active is not None and not positions:
            self._finish_component()
        # Reconcile a funding commit that preceded its checkpoint update.
        for boundary in self._state["boundaries"].values():
            p = _position_from_payload(boundary["position"])
            accruals = self.candidate.store.load_funding_for_market(
                p.market, start_ms=boundary["boundary_ms"]
            )
            for accrual in accruals:
                if (
                    accrual.position_id == p.position_id
                    and accrual.boundary_ms == boundary["boundary_ms"]
                ):
                    boundary["accrual_id"] = accrual.accrual_id
        reduction = self._state["exit"]
        if reduction is not None and reduction.get("plan_id"):
            attempts, _ = self.candidate.store.load_execution_history(reduction["plan_id"])
            if attempts:
                reduction["plan_id"] = None
        self._refresh_components()

    def _validate_history(self) -> None:
        """Cross-store custody rejects deleted or rolled-back account history."""
        intents = {i["plan_id"]: i for i in self._state["intents"].values() if i.get("plan_id")}
        for plan_id, intent in intents.items():
            plan = self.candidate.store.load_plan(plan_id)
            attempts, _ = self.candidate.store.load_execution_history(plan_id)
            if intent["status"] == "attempted" and (plan is None or not attempts):
                raise ValueError("restored attempted intent history missing")
        plans = [
            self.candidate.store.load_plan(str(row[0]))
            for row in self.candidate.store.raw_connection().execute(
                "SELECT plan_id FROM paper_order_plans"
            )
        ]
        gross, fees, funding = D(0), D(0), D(0)
        for opening in (p for p in plans if p is not None and not p.reduce_only):
            if opening.plan_id not in intents:
                raise ValueError("account opening has no original trial intent history")
            _, fills = self.candidate.store.load_execution_history(opening.plan_id)
            if not fills:
                continue
            qty = sum((f.quantity for f in fills), D(0))
            price = sum((f.notional for f in fills), D(0)) / qty
            exits: list[PaperFill] = []
            for plan in plans:
                if (
                    plan
                    and plan.reduce_only
                    and plan.strategy_decision_id == opening.strategy_decision_id
                ):
                    _, leg = self.candidate.store.load_execution_history(plan.plan_id)
                    exits.extend(leg)
            closed = sum((f.quantity for f in exits), D(0))
            remaining = [
                p for p in self.candidate.account.positions if p.opening_plan_id == opening.plan_id
            ]
            if qty - closed != sum((p.quantity for p in remaining), D(0)):
                raise ValueError("restore position/immutable fill history mismatch")
            sign = D(1) if opening.side.value == "buy" else D(-1)
            gross += sum(((f.price - price) * f.quantity * sign for f in exits), D(0))
            fees += sum((f.taker_fee for f in (*fills, *exits)), D(0))
        markets = {p.market for p in plans if p is not None}
        funding = sum(
            (
                a.cash_delta
                for market in markets
                for a in self.candidate.store.load_funding_for_market(market)
            ),
            D(0),
        )
        account = self.candidate.account
        if (
            abs(account.realized_gross_pnl - gross) > D("1e-20")
            or account.cumulative_fees != fees
            or account.cumulative_funding != funding
            or account.cash != account.starting_cash + account.realized_gross_pnl - fees + funding
        ):
            raise ValueError("restore account cash/cost/funding history mismatch")
        for component in self._state["components"]:
            if component["opening_plan_id"] not in intents:
                raise ValueError("completed component lost original intent history")

    def _capture_boundaries(self, now: int) -> None:
        for p in self.candidate.account.positions:
            boundary = (p.opened_at_ms // HOUR + 1) * HOUR
            while boundary <= now:
                key = f"{p.opening_plan_id}:{boundary}"
                if key not in self._state["boundaries"]:
                    oracle = self._state["marks"].get(p.market.canonical)
                    if oracle is not None and not 0 <= boundary - oracle["received_ms"] <= 5000:
                        oracle = None
                    self._state["boundaries"][key] = {
                        "boundary_ms": boundary,
                        "position": _position_payload(p),
                        "oracle": oracle,
                        "accrual_id": None,
                    }
                    if oracle is None:
                        self._fault("BOUNDARY_ORACLE_UNAVAILABLE")
                    self._save()  # Must precede any post-boundary partial/full reduction.
                boundary += HOUR

    def _advance(self, now: int) -> None:
        if now < self._state["now"]:
            self._fault("RUNNER_CLOCK_REGRESSION")
            self._save()
            raise ValueError("runner clock regression")
        self._capture_boundaries(now)
        pending = self._state["pending"]
        if pending is not None:
            intent = self._state["intents"][pending]
            if now >= intent["policy"]["expires_at_ms"]:
                intent["status"] = "expired"
                self._state["pending"] = None
                self._record("expired", now, pending)
        self.candidate.roll_account_day(now)
        if not self.candidate.account.positions:
            self.candidate.mark_account_to_market({}, timestamp_ms=now)
        self.control.roll_account_day(now)
        self.control.mark_account_to_market({}, timestamp_ms=now)
        self._state["now"] = now
        self._latch_time_exit(now)
        if self.candidate.account.equity <= D(9950):
            self._state["permanent"] = True

    def _latch_time_exit(self, now: int) -> None:
        if not self.candidate.account.positions:
            return
        position = self.candidate.account.positions[0]
        if now >= position.opened_at_ms + DAY and self._state["exit"] is None:
            self._state["exit"] = {
                "reason": "max_hold",
                "trigger_ms": position.opened_at_ms + DAY,
                "plan_id": None,
            }

    def tick(self, *, now_ms: int) -> None:
        """Persist time-exit obligation even while no book is available."""
        with localcontext(CONTEXT):
            self._advance(now_ms)
            self._save()

    def set_source_valid(self, valid: bool, *, now_ms: int) -> None:
        self._advance(now_ms)
        self.source_valid = valid
        self._record("source_admission", now_ms, {"valid": valid})
        self._save()

    def record_source_fault(self, reason: str, *, permanent: bool, now_ms: int) -> None:
        self._advance(now_ms)
        self.source_valid = False
        if permanent:
            self._fault(reason)
        self._record("source_fault", now_ms, {"reason": reason, "permanent": permanent})
        self._save()

    def _entry_block(self, market: MarketId, now: int) -> str | None:
        if not self.entries_authorized:
            return "OPERATIONAL_ACTIVATION_NOT_AUTHORIZED"
        if not self.source_valid:
            return "SOURCE_NOT_ADMITTED"
        boundary = self._state["identity"]["first_entry_ms"]
        if boundary is None:
            return "FIRST_ENTRY_BOUNDARY_UNASSIGNED"
        if now < boundary:
            return "BEFORE_FIRST_ENTRY_BOUNDARY"
        if self._state["permanent"]:
            return "PERMANENT_TRIAL_ENTRY_SUSPENSION"
        if self._state["faults"] or not self.candidate.health.healthy_for_new_exposure:
            return "STATE_UNHEALTHY"
        if any(b["accrual_id"] is None for b in self._state["boundaries"].values()):
            return "FUNDING_UNKNOWN"
        if self.candidate.account.positions or self._state["pending"] is not None:
            return "TRIAL_CAPACITY"
        return None

    def _risk(
        self,
        plan: VolatilityBudgetPlan,
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        now: int,
    ) -> tuple[RiskDecision, Decimal]:
        micro = calculate_microstructure_features(book, as_of_ms=now)
        long = plan.decision.direction is Direction.LONG
        reference = micro.best_ask_px if long else micro.best_bid_px
        depth = micro.ask_depth_25bps if long else micro.bid_depth_25bps
        qty = quantity_for_plan(
            plan,
            equity=self.candidate.account.equity,
            executable_entry=reference,
            contra_depth_25bp=depth,
            sz_decimals=instrument.sz_decimals,
            now_ms=now,
            independent_reserve_bps=D(59),
        )
        account, positions = risk_state_from_paper(self.candidate.account)
        # Existing independent risk reserves 25bp each way; include frozen reserve
        # when it is larger, never weaken the native adapter's approval envelope.
        reserve = max(D(".0059"), plan.cost_bps / D(10000))
        request = RiskRequest(
            plan.decision,
            reference,
            "volatility-budget-shared",
            account,
            positions,
            RiskHealthState(
                True,
                True,
                self.candidate.health.healthy_for_new_exposure,
                not self._state["faults"],
                now,
            ),
            ExecutionCostEstimate(D(".0025"), reserve - D(".0034"), D(".0009")),
            LiquidityRiskState(
                depth,
                micro.bid_depth_25bps if long else micro.ask_depth_25bps,
                instrument.venue_max_leverage,
                paper_liquidation_surrogate(
                    reference,
                    plan.decision.direction,
                    paper_max_leverage=D(3),
                    venue_max_leverage=instrument.venue_max_leverage,
                ),
                instrument.minimum_order_notional,
                _received(book),
            ),
            RiskLimits(risk_per_trade=D(".001"), max_visible_depth_fraction=D(".05")),
            now,
        )
        risk = evaluate_risk(request)
        if risk.approved and qty <= 0:
            return replace(
                risk,
                approved=False,
                approved_notional=D(0),
                approved_risk_amount=D(0),
                reason_codes=("FROZEN_QUANTITY_ZERO",),
            ), reference
        if risk.approved:
            notional = min(risk.approved_notional, qty * reference)
            risk = replace(
                risk,
                approved_notional=notional,
                approved_risk_amount=min(
                    risk.approved_risk_amount, notional * (risk.effective_loss_fraction or D(0))
                ),
            )
        return risk, reference

    def evaluate(
        self,
        windows: tuple[VolatilityBudgetWindow, ...],
        instruments: Mapping[MarketId, InstrumentExecutionSpec],
        books: Mapping[MarketId, StreamEvent],
        *,
        now_ms: int,
    ) -> None:
        """Consume one complete daily batch, then select one eligible canonical market.

        Every valid cooldown-admitted crossing advances its own ANYside clock,
        including unselected/ineligible crossings. A late batch is UNKNOWN and
        consumes the daily clock without re-timing a signal or an entry attempt.
        """
        with localcontext(CONTEXT):
            self._advance(now_ms)
            if not windows:
                self._save()
                return
            epoch = windows[0].decision_time_ms
            if any(w.decision_time_ms != epoch for w in windows) or epoch > now_ms:
                raise ValueError("mixed or future decision epoch")
            if len({w.market for w in windows}) != len(windows):
                raise ValueError("duplicate daily market")
            if epoch <= self._state["last_epoch"]:
                return
            self._state["last_epoch"] = epoch
            self._state["selected_market"] = None
            if epoch % DAY != 30_000 or now_ms != epoch:
                self._record("unknown_daily_batch", now_ms, {"decision_ms": epoch})
                self._save()
                return
            selected: VolatilityBudgetPlan | None = None
            for window in sorted(windows, key=lambda w: w.market.canonical):
                plan = evaluate_volatility_budget(window)
                self._record("decision", now_ms, _plan_payload(plan))
                if plan.signal_direction not in (Direction.LONG, Direction.SHORT):
                    continue
                previous = self._state["cooldowns"].get(window.market.canonical)
                if previous is not None and epoch - previous < 72 * HOUR:
                    self._record("cooldown_suppressed", now_ms, window.market.canonical)
                    continue
                self._state["cooldowns"][window.market.canonical] = epoch
                if not plan.current_eligible:
                    continue
                if selected is None:
                    selected = plan
            # Persist every crossing and the one batch selection before any attempt.
            if selected is not None:
                self._state["selected_market"] = selected.decision.market.canonical
                blocked = (
                    "POLICY_EXECUTION_VETO:" + ",".join(selected.decision.reason_codes)
                    if selected.decision.direction is Direction.NO_TRADE
                    else self._entry_block(selected.decision.market, now_ms)
                )
                instrument = instruments.get(selected.decision.market)
                book = books.get(selected.decision.market)
                if blocked is None and (book is None or instrument is None):
                    blocked = "MISSING_BOOK_OR_INSTRUMENT"
                if blocked is None:
                    key = selected.decision.decision_id
                    self._state["intents"][key] = {
                        "policy": _plan_payload(selected),
                        "status": "staged",
                        "plan_id": None,
                        "equity_before": None,
                    }
                    self._state["pending"] = key
                self._record(
                    "entry_selection",
                    now_ms,
                    {
                        "decision_id": selected.decision.decision_id,
                        "blocked": blocked,
                    },
                )
            self._save()

    @staticmethod
    def _valid_context(event: StreamEvent, now: int) -> bool:
        return (
            event.kind is StreamKind.ACTIVE_ASSET_CTX
            and event.source in ("hyperliquid-mainnet-ws", "hyperliquid-mainnet-info")
            and event.schema_version == 1
            and 0 <= now - _received(event) <= 5000
            and (event.exchange_time_ms is None or 0 <= now - event.exchange_time_ms <= 5000)
            and all(
                isinstance(value, Decimal) and value.is_finite() and value > 0
                for value in (event.payload.get("mark_px"), event.payload.get("oracle_px"))
            )
        )

    def _ingress(self, event: StreamEvent, now: int) -> bool:
        """Observe original arrival clocks across all runtime kinds, never reorder them."""
        received = _received(event)
        self._record("source_ingress", now, _event_payload(event))
        previous = self._state["ingress_received_ms"]
        if received < previous:
            self.source_valid = False
            self._fault("SOURCE_RECEIVE_CLOCK_REGRESSION")
            self._save()
            return False
        self._state["ingress_received_ms"] = received
        return True

    def _latch_mark_stop(self, event: StreamEvent, now: int) -> None:
        for position in self.candidate.account.positions:
            if event.market != position.market:
                continue
            price = event.payload["mark_px"]
            assert isinstance(price, Decimal)
            if (position.side is PositionSide.LONG and price <= position.stop_price) or (
                position.side is PositionSide.SHORT and price >= position.stop_price
            ):
                previous = self._state["exit"]
                if previous is None or previous["reason"] != "stop":
                    self._state["exit"] = {
                        **(previous or {}),
                        "reason": "stop",
                        "trigger_ms": min(now, (previous or {}).get("trigger_ms", now)),
                        "plan_id": (previous or {}).get("plan_id"),
                    }
                    self._save()

    def on_mark(self, event: StreamEvent, *, now_ms: int) -> None:
        with localcontext(CONTEXT):
            self._advance(now_ms)
            monotonic = self._ingress(event, now_ms)
            if not self._valid_context(event, now_ms):
                self.source_valid = False
                self._record("invalid_mark", now_ms, event.event_key)
                self._save()
                return
            self._latch_mark_stop(event, now_ms)
            if not monotonic:
                return  # Keep newer oracle/account mark; permanent fault already persisted.
            self._state["marks"][event.market.canonical] = _event_payload(event)
            marks: dict[MarketId, Decimal] = {}
            for position in self.candidate.account.positions:
                row = self._state["marks"].get(position.market.canonical)
                if row is None or not self._valid_context(_event_from(row), now_ms):
                    self.source_valid = False
                    self._record("mark_unavailable", now_ms, position.market.canonical)
                    self._save()
                    return
                marks[position.market] = D(row["payload"]["mark_px"])
            self.candidate.mark_account_to_market(marks, timestamp_ms=now_ms)
            if self.candidate.account.equity <= D(9950):
                self._state["permanent"] = True
            self._record("equity", now_ms, self._equity())
            self._save()

    def on_book(
        self,
        book: StreamEvent,
        instrument: InstrumentExecutionSpec,
        mark_event: StreamEvent | None = None,
        *,
        now_ms: int,
    ) -> None:
        with localcontext(CONTEXT):
            self._advance(now_ms)
            if mark_event is not None:
                self.on_mark(mark_event, now_ms=now_ms)
            self._ingress(book, now_ms)
            if self.candidate.account.positions:
                self._manage(book, instrument, now_ms)
            elif self._state["pending"] is not None:
                self._open(book, instrument, now_ms)
            self._save()

    def _open(self, book: StreamEvent, instrument: InstrumentExecutionSpec, now: int) -> None:
        key = self._state["pending"]
        intent = self._state["intents"][key]
        plan = _plan_from(intent["policy"])
        if now >= plan.expires_at_ms:
            intent["status"] = "expired"
            self._state["pending"] = None
            self._record("expired", now, key)
            return
        if (
            book.market != plan.decision.market
            or _received(book) < plan.decision.timestamp_ms + 250
            or now < plan.decision.timestamp_ms + 250
        ):
            return
        # Pending capacity is our own reservation, not a reason to veto itself.
        self._state["pending"] = None
        blocked = self._entry_block(book.market, now)
        self._state["pending"] = key
        context = self._state["marks"].get(book.market.canonical)
        if blocked is None and (
            context is None or not self._valid_context(_event_from(context), now)
        ):
            blocked = "FRESH_MARK_ORACLE_UNAVAILABLE"
        if blocked:
            intent["status"] = blocked
            self._state["pending"] = None
            return
        if not self._fresh_book(book, instrument, now):
            intent["status"] = "INVALID_EXECUTION_BOOK"
            self._state["pending"] = None
            self._record("execution_book_rejected", now, book.event_key)
            return
        risk, reference = self._risk(plan, instrument, book, now)
        planned = plan_opening_order(
            risk, instrument, self.config, reference, plan.decision.timestamp_ms
        )
        if isinstance(planned, PlanningRejection):
            intent["status"] = planned.reason
            self._state["pending"] = None
            self._record("risk_rejected", now, asdict(risk))
            return
        intent.update(
            status="attempting",
            plan_id=planned.plan_id,
            equity_before=str(self.candidate.account.equity),
        )
        self._save()  # Crash after committed adapter fill must never repeat opening.
        submission = self.candidate.submit_opening(
            risk,
            instrument,
            book,
            reference_price=reference,
            created_at_ms=plan.decision.timestamp_ms,
            attempt_timestamp_ms=now,
        )
        intent["status"] = "attempted"
        self._state["pending"] = None
        if submission.simulation and submission.simulation.fills:
            self._state["active"] = key
        self._record("opening", now, asdict(submission))
        self._record("equity", now, self._equity())

    @staticmethod
    def _fresh_book(book: StreamEvent, instrument: InstrumentExecutionSpec, now: int) -> bool:
        if not (
            book.kind is StreamKind.L2_BOOK
            and book.source == "hyperliquid-mainnet-ws"
            and book.schema_version == 1
            and instrument.market == book.market
            and 0 <= now - _received(book) <= 1000
            and book.exchange_time_ms is not None
            and 0 <= now - book.exchange_time_ms <= 1000
            and 0 <= _received(book) - book.exchange_time_ms <= 1000
        ):
            return False
        try:
            for side in ("bids", "asks"):
                raw = book.payload.get(side)
                if not isinstance(raw, (list, tuple)) or not raw:
                    return False
                if any(not isinstance(level, Mapping) for level in raw):
                    return False
                prices = [level.get("px") for level in raw]
                if any(
                    not isinstance(price, Decimal) or not price.is_finite() or price <= 0
                    for price in prices
                ):
                    return False
                if len(set(prices)) != len(prices):
                    return False
            calculate_microstructure_features(book, as_of_ms=now)
        except (ValueError, TypeError):
            return False
        return True

    def _manage(self, book: StreamEvent, instrument: InstrumentExecutionSpec, now: int) -> None:
        position = self.candidate.account.positions[0]
        if book.market != position.market:
            return
        key = self._state["active"]
        if key is None:
            self._fault("MISSING_FROZEN_POSITION_POLICY")
            return
        plan = _plan_from(self._state["intents"][key]["policy"])
        fresh = self._fresh_book(book, instrument, now)
        micro = calculate_microstructure_features(book, as_of_ms=now) if fresh else None
        executable = (
            None
            if micro is None
            else (micro.best_bid_px if position.side is PositionSide.LONG else micro.best_ask_px)
        )
        reason = exit_reason(
            plan, executable_price=executable, first_fill_ms=position.opened_at_ms, now_ms=now
        )
        row = self._state["marks"].get(position.market.canonical)
        if row is not None and 0 <= now - row["received_ms"] <= 5000:
            mark_price = D(row["payload"].get("mark_px", "NaN"))
            if (
                mark_price.is_finite()
                and mark_price > 0
                and (
                    (position.side is PositionSide.LONG and mark_price <= position.stop_price)
                    or (position.side is PositionSide.SHORT and mark_price >= position.stop_price)
                )
            ):
                reason = "stop"
        previous = self._state["exit"]
        priority = {"stop": 0, "target": 1, "max_hold": 2}
        if reason is not None and (
            previous is None or priority[reason] < priority[previous["reason"]]
        ):
            self._state["exit"] = {
                **(previous or {}),
                "reason": reason,
                "trigger_ms": min(now, (previous or {}).get("trigger_ms", now)),
                "plan_id": (previous or {}).get("plan_id"),
            }
            self._save()
        reduction = self._state["exit"]
        if reduction is None or not fresh or executable is None:
            return
        if reduction.get("plan_id") is None:
            opening = self.candidate.store.load_plan(position.opening_plan_id)
            if opening is None:
                self._fault("MISSING_OPENING_PLAN")
                return
            action = PositionAction(
                PositionActionType.REDUCE,
                position.market,
                position.quantity,
                None,
                ("VOLATILITY_" + reduction["reason"].upper(),),
                now,
            )
            candidate_plan = plan_reduce_only_order(
                position,
                action,
                instrument,
                self.config,
                originating_risk_decision_id=opening.risk_decision_id,
                originating_strategy_decision_id=opening.strategy_decision_id,
                reference_price=executable,
                created_at_ms=now,
            )
            if isinstance(candidate_plan, PlanningRejection):
                self._record("reduction_rejected", now, candidate_plan.reason)
                return
            planned = candidate_plan
            self.candidate._persist_plan(planned)
            reduction["plan_id"] = planned.plan_id
            self._save()  # Persist intent before any attempt; survives a book/feed gap.
        else:
            restored_plan = self.candidate.store.load_plan(reduction["plan_id"])
            if restored_plan is None:
                self._fault("MISSING_DURABLE_REDUCTION")
                return
            planned = restored_plan
            action = PositionAction(
                PositionActionType.REDUCE,
                position.market,
                position.quantity,
                None,
                ("VOLATILITY_" + reduction["reason"].upper(),),
                planned.created_at_ms,
            )
        if _received(book) < planned.earliest_execution_ms or now < planned.earliest_execution_ms:
            return
        # Post-intent, post-latency original fresh books only, including after restart.
        outcome = self.candidate._execute_reduce_only_plan(
            position.market,
            action,
            planned,
            instrument,
            book,
            attempt_timestamp_ms=now,
        )
        reduction["plan_id"] = None
        self._record("management", now, asdict(outcome))
        self._record("equity", now, self._equity())
        if not self.candidate.account.positions:
            self._finish_component()
        if self.candidate.account.equity <= D(9950):
            self._state["permanent"] = True

    def _finish_component(self) -> None:
        key = self._state["active"]
        if key is None:
            return
        intent = self._state["intents"][key]
        opening = self.candidate.store.load_plan(intent["plan_id"])
        if opening is None:
            self._fault("MISSING_OPENING_PLAN")
            return
        _, fills = self.candidate.store.load_execution_history(opening.plan_id)
        if not fills:
            self._fault("MISSING_OPENING_FILLS")
            return
        all_fills = list(fills)
        for (plan_id,) in (
            self.candidate.store.raw_connection()
            .execute("SELECT plan_id FROM paper_order_plans")
            .fetchall()
        ):
            plan = self.candidate.store.load_plan(str(plan_id))
            if (
                plan
                and plan.reduce_only
                and plan.strategy_decision_id == opening.strategy_decision_id
            ):
                _, exits = self.candidate.store.load_execution_history(plan.plan_id)
                all_fills.extend(exits)
        quantity = sum((f.quantity for f in fills), D(0))
        entry = sum((f.notional for f in fills), D(0))
        exit_notional = sum((f.notional for f in all_fills if f.plan_id != opening.plan_id), D(0))
        closed_qty = sum((f.quantity for f in all_fills if f.plan_id != opening.plan_id), D(0))
        if closed_qty != quantity:
            self._fault("COMPONENT_FILL_QUANTITY_MISMATCH")
            return
        gross = exit_notional - entry if opening.side.value == "buy" else entry - exit_notional
        component = {
            "opening_plan_id": opening.plan_id,
            "market": opening.market.canonical,
            "direction": "LONG" if opening.side.value == "buy" else "SHORT",
            "decision_batch_ms": intent["policy"]["decision"]["timestamp_ms"],
            "evidence_digest": intent["policy"]["evidence_digest"],
            "opened_at_ms": min(f.timestamp_ms for f in fills),
            "closed_at_ms": max(f.timestamp_ms for f in all_fills),
            "gross": str(gross),
            "fees": str(sum((f.taker_fee for f in all_fills), D(0))),
            "funding": "0",
            "equity_before": intent["equity_before"],
            "funding_complete": False,
            "exit_reason": (self._state["exit"] or {}).get("reason", "recovered_close"),
        }
        if not any(c["opening_plan_id"] == opening.plan_id for c in self._state["components"]):
            self._state["components"].append(component)
        self._state["active"] = None
        self._state["exit"] = None
        self._refresh_components()
        self._record("component", self._state["now"], component)

    def _refresh_components(self) -> None:
        for component in self._state["components"]:
            relevant = [
                b
                for b in self._state["boundaries"].values()
                if b["position"]["opening_plan_id"] == component["opening_plan_id"]
            ]
            complete = all(b["accrual_id"] is not None for b in relevant)
            market = MarketId.from_wire_name("", component["market"])
            ids = {b["accrual_id"] for b in relevant}
            funding = sum(
                (
                    a.cash_delta
                    for a in self.candidate.store.load_funding_for_market(market)
                    if a.accrual_id in ids
                ),
                D(0),
            )
            component.update(
                funding=str(funding) if complete else None,
                booked_funding=str(funding),
                funding_complete=complete,
                net=str(D(component["gross"]) - D(component["fees"]) + funding)
                if complete
                else None,
            )
        # Funding that arrived after a close may change its loss classification.
        if self._state["components"]:
            losses = 0
            for component in reversed(self._state["components"]):
                if component["net"] is None or D(component["net"]) >= 0:
                    break
                losses += 1
            account = replace(self.candidate.account, consecutive_losses=losses)
            self.candidate.store.persist_account(account)
            self.candidate._account = account

    def apply_funding(self, accrual: FundingAccrual, *, now_ms: int) -> None:
        with localcontext(CONTEXT):
            self._advance(now_ms)
            boundary = next(
                (
                    b
                    for b in self._state["boundaries"].values()
                    if b["boundary_ms"] == accrual.boundary_ms
                    and _position_from_payload(b["position"]).position_id == accrual.position_id
                ),
                None,
            )
            if boundary is None:
                raise ValueError("funding boundary snapshot missing")
            existing = next(
                (
                    a
                    for a in self.candidate.store.load_funding_for_market(
                        accrual.market, start_ms=accrual.boundary_ms
                    )
                    if a.boundary_ms == accrual.boundary_ms
                ),
                None,
            )
            if (
                existing is not None
                and replace(existing, funding_received_at_ms=accrual.funding_received_at_ms)
                != accrual
            ):
                self._fault("CONFLICTING_FUNDING_BOUNDARY")
                self._save()
                raise ValueError("conflicting funding boundary rate")
            position = _position_from_payload(boundary["position"])
            oracle = boundary["oracle"]
            signed = position.quantity if position.side is PositionSide.LONG else -position.quantity
            if (
                oracle is None
                or accrual.market != position.market
                or accrual.signed_quantity != signed
                or accrual.oracle_event_key != oracle["event_key"]
                or accrual.oracle_price != D(oracle["payload"].get("oracle_px", "NaN"))
                or accrual.funding_source != "hyperliquid-mainnet-info"
                or not accrual.boundary_ms <= accrual.funding_received_at_ms <= now_ms
                or accrual.cash_delta
                != funding_cash_delta(signed, accrual.oracle_price, accrual.funding_rate)
            ):
                self._fault("FUNDING_BOUNDARY_MISMATCH")
                self._save()
                raise ValueError("funding boundary provenance mismatch")
            self.candidate.apply_boundary_funding(
                accrual, opening_plan_id=position.opening_plan_id, now_ms=now_ms
            )
            boundary["accrual_id"] = accrual.accrual_id
            self._refresh_components()
            self._record("funding", now_ms, asdict(accrual))
            self._record("equity", now_ms, self._equity())
            if self.candidate.account.equity <= D(9950):
                self._state["permanent"] = True
            self._save()

    def _equity(self) -> dict[str, str]:
        account = self.candidate.account
        return {
            "candidate_equity": str(account.equity),
            "candidate_cash": str(account.cash),
            "gross": str(account.realized_gross_pnl),
            "fees": str(account.cumulative_fees),
            "funding": str(account.cumulative_funding),
            "unrealized": str(account.unrealized_pnl),
            "control_equity": str(self.control.account.equity),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            **self._equity(),
            **self._state["identity"],
            "entries_authorized": self.entries_authorized,
            "source_valid": self.source_valid,
            "now_ms": self._state["now"],
            "last_decision_ms": self._state["last_epoch"],
            "cooldowns": dict(self._state["cooldowns"]),
            "selected_market": self._state["selected_market"],
            "pending": self._state["pending"],
            "exit_reason": (self._state["exit"] or {}).get("reason"),
            "funding_unknown": any(
                b["accrual_id"] is None for b in self._state["boundaries"].values()
            ),
            "permanently_disabled": self._state["permanent"],
            "faults": list(self._state["faults"]),
            "funding_obligations": json.loads(_json(list(self._state["boundaries"].values()))),
            "components": json.loads(_json(self._state["components"])),
            "open_positions": [_position_payload(p) for p in self.candidate.account.positions],
        }

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._save()
        finally:
            self._dispose()
