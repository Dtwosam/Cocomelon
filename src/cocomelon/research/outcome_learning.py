from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_discovery_freeze import HistoricalDiscoveryFreezeSpec
from cocomelon.research.prospective_context_evidence import (
    PROSPECTIVE_EVIDENCE_CLASS,
    ProspectiveEvidenceConsistencyError,
    ProspectiveEvidenceStore,
    ProspectiveObservation,
    ProspectiveOutcome,
)
from cocomelon.research.prospective_context_report import ProspectiveValidationPlan

ZERO = Decimal("0")
LEARNING_SCHEMA_VERSION = 1


class LearningEvidenceError(RuntimeError):
    pass


class LearningEvidenceKind(StrEnum):
    PROSPECTIVE_PAPER = "prospective_paper"
    PAPER_EXECUTION = "paper_execution"
    LIVE_EXECUTION = "live_execution"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def _require_finite(value: Decimal | None, field: str) -> None:
    if value is not None and not value.is_finite():
        raise ValueError(f"{field} must be finite when present")


def _decimal_payload(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _market_from_canonical(value: str) -> MarketId:
    _require_nonempty(value, "market")
    if ":" not in value:
        return MarketId("", value)
    dex, coin = value.split(":", 1)
    return MarketId(dex, coin)


@dataclass(frozen=True, slots=True)
class LearningEvidenceRecord:
    kind: LearningEvidenceKind
    source_record_id: str
    source_evidence_class: str
    candidate_id: str
    candidate_spec_id: str | None
    campaign_id: str | None
    market: MarketId
    direction: Direction
    opened_at_ms: int
    closed_at_ms: int
    feature_snapshot_id: str
    research_eligible_at_ms: int
    context_state_1h: str | None = None
    gross_return_fraction: Decimal | None = None
    modeled_cost_fraction: Decimal | None = None
    net_return_fraction: Decimal | None = None
    gross_realized_pnl: Decimal | None = None
    entry_fees: Decimal | None = None
    exit_fees: Decimal | None = None
    funding_cash_pnl: Decimal | None = None
    entry_slippage_fraction: Decimal | None = None
    exit_slippage_fraction: Decimal | None = None
    net_pnl: Decimal | None = None
    net_r: Decimal | None = None
    schema_version: int = LEARNING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "source_record_id",
            "source_evidence_class",
            "candidate_id",
            "feature_snapshot_id",
        ):
            _require_nonempty(str(getattr(self, field)), field)
        if self.candidate_spec_id is not None:
            _require_nonempty(self.candidate_spec_id, "candidate_spec_id")
        if self.campaign_id is not None:
            _require_nonempty(self.campaign_id, "campaign_id")
        if self.direction is Direction.NO_TRADE:
            raise ValueError("learning evidence requires a settled directional trade")
        if self.opened_at_ms < 0 or self.closed_at_ms < self.opened_at_ms:
            raise ValueError("learning evidence timestamps are invalid")
        if self.research_eligible_at_ms < self.closed_at_ms:
            raise ValueError("research_eligible_at_ms cannot predate trade close")
        if self.schema_version != LEARNING_SCHEMA_VERSION:
            raise ValueError("unsupported learning evidence schema")

        return_fields = (
            "gross_return_fraction",
            "modeled_cost_fraction",
            "net_return_fraction",
        )
        execution_fields = (
            "gross_realized_pnl",
            "entry_fees",
            "exit_fees",
            "funding_cash_pnl",
            "entry_slippage_fraction",
            "exit_slippage_fraction",
            "net_pnl",
            "net_r",
        )
        for field in (*return_fields, *execution_fields):
            _require_finite(getattr(self, field), field)

        if self.kind is LearningEvidenceKind.PROSPECTIVE_PAPER:
            if self.candidate_spec_id is None or self.campaign_id is None:
                raise ValueError("prospective learning evidence requires campaign identity")
            if not self.context_state_1h:
                raise ValueError("prospective learning evidence requires context_state_1h")
            gross_return = self.gross_return_fraction
            modeled_cost = self.modeled_cost_fraction
            net_return = self.net_return_fraction
            if gross_return is None or modeled_cost is None or net_return is None:
                raise ValueError("prospective learning evidence requires return fractions")
            if any(getattr(self, field) is not None for field in execution_fields):
                raise ValueError("prospective learning evidence cannot contain execution PnL fields")
            if modeled_cost < ZERO:
                raise ValueError("modeled_cost_fraction must be non-negative")
            if net_return != gross_return - modeled_cost:
                raise ValueError("prospective net return must reconcile to modeled cost")
        else:
            if any(getattr(self, field) is not None for field in return_fields):
                raise ValueError("execution learning evidence cannot contain modeled returns")
            if any(getattr(self, field) is None for field in execution_fields):
                raise ValueError("execution learning evidence requires execution PnL fields")
            if self.entry_fees is not None and self.entry_fees < ZERO:
                raise ValueError("entry_fees must be non-negative")
            if self.exit_fees is not None and self.exit_fees < ZERO:
                raise ValueError("exit_fees must be non-negative")

    def identity_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "source_record_id": self.source_record_id,
            "source_evidence_class": self.source_evidence_class,
            "candidate_id": self.candidate_id,
            "candidate_spec_id": self.candidate_spec_id,
            "campaign_id": self.campaign_id,
            "market": self.market.canonical,
            "direction": self.direction.value,
            "opened_at_ms": self.opened_at_ms,
            "closed_at_ms": self.closed_at_ms,
            "feature_snapshot_id": self.feature_snapshot_id,
            "research_eligible_at_ms": self.research_eligible_at_ms,
            "context_state_1h": self.context_state_1h,
            "gross_return_fraction": _decimal_payload(self.gross_return_fraction),
            "modeled_cost_fraction": _decimal_payload(self.modeled_cost_fraction),
            "net_return_fraction": _decimal_payload(self.net_return_fraction),
            "gross_realized_pnl": _decimal_payload(self.gross_realized_pnl),
            "entry_fees": _decimal_payload(self.entry_fees),
            "exit_fees": _decimal_payload(self.exit_fees),
            "funding_cash_pnl": _decimal_payload(self.funding_cash_pnl),
            "entry_slippage_fraction": _decimal_payload(self.entry_slippage_fraction),
            "exit_slippage_fraction": _decimal_payload(self.exit_slippage_fraction),
            "net_pnl": _decimal_payload(self.net_pnl),
            "net_r": _decimal_payload(self.net_r),
            "schema_version": self.schema_version,
        }

    @property
    def record_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class LearningSyncResult:
    scanned_outcomes: int
    created_records: int
    existing_records: int

    def __post_init__(self) -> None:
        if min(self.scanned_outcomes, self.created_records, self.existing_records) < 0:
            raise ValueError("learning sync counts must be non-negative")
        if self.created_records + self.existing_records != self.scanned_outcomes:
            raise ValueError("learning sync counts must reconcile")


class LearningEvidenceLedger:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.records_root = self.root / "records"
        self.records_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _date_path(timestamp_ms: int) -> str:
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date().isoformat()

    def _record_path(self, record: LearningEvidenceRecord) -> Path:
        return (
            self.records_root
            / self._date_path(record.closed_at_ms)
            / f"{record.record_id}.json"
        )

    def record(self, record: LearningEvidenceRecord) -> bool:
        path = self._record_path(record)
        payload = {**record.identity_payload(), "record_id": record.record_id}
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != encoded:
                raise LearningEvidenceError(
                    f"conflicting learning evidence record: {record.record_id}"
                )
            return False
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != encoded:
                    raise LearningEvidenceError(
                        f"conflicting learning evidence record: {record.record_id}"
                    ) from None
                return False
            return True
        finally:
            if temporary.exists():
                temporary.unlink()

    def iter_records(self) -> tuple[LearningEvidenceRecord, ...]:
        records: list[LearningEvidenceRecord] = []
        for path in sorted(self.records_root.glob("*/*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = LearningEvidenceRecord(
                kind=LearningEvidenceKind(str(raw["kind"])),
                source_record_id=str(raw["source_record_id"]),
                source_evidence_class=str(raw["source_evidence_class"]),
                candidate_id=str(raw["candidate_id"]),
                candidate_spec_id=(
                    None
                    if raw.get("candidate_spec_id") is None
                    else str(raw["candidate_spec_id"])
                ),
                campaign_id=(
                    None if raw.get("campaign_id") is None else str(raw["campaign_id"])
                ),
                market=_market_from_canonical(str(raw["market"])),
                direction=Direction(str(raw["direction"])),
                opened_at_ms=int(raw["opened_at_ms"]),
                closed_at_ms=int(raw["closed_at_ms"]),
                feature_snapshot_id=str(raw["feature_snapshot_id"]),
                research_eligible_at_ms=int(raw["research_eligible_at_ms"]),
                context_state_1h=(
                    None
                    if raw.get("context_state_1h") is None
                    else str(raw["context_state_1h"])
                ),
                gross_return_fraction=_optional_decimal(raw.get("gross_return_fraction")),
                modeled_cost_fraction=_optional_decimal(raw.get("modeled_cost_fraction")),
                net_return_fraction=_optional_decimal(raw.get("net_return_fraction")),
                gross_realized_pnl=_optional_decimal(raw.get("gross_realized_pnl")),
                entry_fees=_optional_decimal(raw.get("entry_fees")),
                exit_fees=_optional_decimal(raw.get("exit_fees")),
                funding_cash_pnl=_optional_decimal(raw.get("funding_cash_pnl")),
                entry_slippage_fraction=_optional_decimal(
                    raw.get("entry_slippage_fraction")
                ),
                exit_slippage_fraction=_optional_decimal(
                    raw.get("exit_slippage_fraction")
                ),
                net_pnl=_optional_decimal(raw.get("net_pnl")),
                net_r=_optional_decimal(raw.get("net_r")),
                schema_version=int(raw["schema_version"]),
            )
            if raw.get("record_id") != record.record_id:
                raise LearningEvidenceError(
                    f"learning evidence record identity mismatch: {path.name}"
                )
            records.append(record)
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.closed_at_ms,
                    item.opened_at_ms,
                    item.market.canonical,
                    item.record_id,
                ),
            )
        )

    @property
    def state_digest(self) -> str:
        payload = {
            "schema_version": LEARNING_SCHEMA_VERSION,
            "records": tuple(item.identity_payload() for item in self.iter_records()),
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def eligible_records(self, *, as_of_ms: int) -> tuple[LearningEvidenceRecord, ...]:
        if as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        return tuple(
            item
            for item in self.iter_records()
            if item.research_eligible_at_ms <= as_of_ms
        )

    def quarantined_records(self, *, as_of_ms: int) -> tuple[LearningEvidenceRecord, ...]:
        if as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        return tuple(
            item
            for item in self.iter_records()
            if item.research_eligible_at_ms > as_of_ms
        )


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def prospective_learning_record(
    spec: HistoricalDiscoveryFreezeSpec,
    plan: ProspectiveValidationPlan,
    *,
    campaign_id: str,
    observation: ProspectiveObservation,
    outcome: ProspectiveOutcome,
) -> LearningEvidenceRecord:
    _require_nonempty(campaign_id, "campaign_id")
    if plan.candidate_spec_id != spec.spec_id:
        raise ValueError("validation plan does not match candidate spec")
    if observation.candidate_spec_id != spec.spec_id:
        raise ValueError("observation does not match candidate spec")
    if outcome.candidate_spec_id != spec.spec_id:
        raise ValueError("outcome does not match candidate spec")
    if outcome.observation_id != observation.observation_id:
        raise ValueError("outcome does not match prospective observation")
    if observation.effective_direction not in {Direction.LONG, Direction.SHORT}:
        raise ValueError("prospective learning requires an effective directional trade")
    if outcome.direction is not observation.effective_direction:
        raise ValueError("prospective outcome direction does not match observation")
    if outcome.anchor_end_ms != observation.anchor_end_ms:
        raise ValueError("prospective outcome anchor does not match observation")
    if outcome.target_end_ms != observation.target_end_ms:
        raise ValueError("prospective outcome target does not match observation")

    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PROSPECTIVE_PAPER,
        source_record_id=outcome.outcome_id,
        source_evidence_class=PROSPECTIVE_EVIDENCE_CLASS,
        candidate_id=spec.candidate_id,
        candidate_spec_id=spec.spec_id,
        campaign_id=campaign_id,
        market=outcome.market,
        direction=outcome.direction,
        opened_at_ms=outcome.anchor_end_ms,
        closed_at_ms=outcome.target_end_ms,
        feature_snapshot_id=observation.feature_snapshot_id,
        research_eligible_at_ms=plan.finalization_not_before_ms,
        context_state_1h=observation.context_state_1h,
        gross_return_fraction=outcome.gross_return,
        modeled_cost_fraction=outcome.modeled_cost_fraction,
        net_return_fraction=outcome.net_return,
    )


def execution_learning_record(
    trade: TradeJournalEntry,
    *,
    candidate_id: str,
    kind: LearningEvidenceKind,
    research_eligible_at_ms: int,
    candidate_spec_id: str | None = None,
    campaign_id: str | None = None,
) -> LearningEvidenceRecord:
    _require_nonempty(candidate_id, "candidate_id")
    if kind not in {
        LearningEvidenceKind.PAPER_EXECUTION,
        LearningEvidenceKind.LIVE_EXECUTION,
    }:
        raise ValueError("execution trade requires paper_execution or live_execution kind")
    if kind is LearningEvidenceKind.LIVE_EXECUTION and trade.replay_run_id is not None:
        raise ValueError("live execution evidence cannot come from a replay-backed trade")
    return LearningEvidenceRecord(
        kind=kind,
        source_record_id=trade.trade_id,
        source_evidence_class=trade.evidence_class.value,
        candidate_id=candidate_id,
        candidate_spec_id=candidate_spec_id,
        campaign_id=campaign_id,
        market=trade.market,
        direction=trade.direction,
        opened_at_ms=trade.opened_at_ms,
        closed_at_ms=trade.closed_at_ms,
        feature_snapshot_id=trade.feature_snapshot_id,
        research_eligible_at_ms=research_eligible_at_ms,
        gross_realized_pnl=trade.gross_realized_pnl,
        entry_fees=trade.entry_fees,
        exit_fees=trade.exit_fees,
        funding_cash_pnl=trade.funding_cash_pnl,
        entry_slippage_fraction=trade.entry_slippage_fraction,
        exit_slippage_fraction=trade.exit_slippage_fraction,
        net_pnl=trade.net_pnl,
        net_r=trade.net_r,
    )


def sync_prospective_learning_evidence(
    source: ProspectiveEvidenceStore,
    ledger: LearningEvidenceLedger,
    *,
    spec: HistoricalDiscoveryFreezeSpec,
    plan: ProspectiveValidationPlan,
) -> LearningSyncResult:
    if source.spec.spec_id != spec.spec_id:
        raise ValueError("prospective source store does not match candidate spec")
    campaign_id = source.manifest.campaign_id
    created = 0
    existing = 0
    outcomes = source.iter_outcomes()
    for outcome in outcomes:
        try:
            observation = source.load_observation(outcome.observation_id)
        except ProspectiveEvidenceConsistencyError as exc:
            raise LearningEvidenceError(
                f"invalid prospective observation lineage: {outcome.observation_id}"
            ) from exc
        if observation is None:
            raise LearningEvidenceError(
                f"missing prospective observation lineage: {outcome.observation_id}"
            )
        record = prospective_learning_record(
            spec,
            plan,
            campaign_id=campaign_id,
            observation=observation,
            outcome=outcome,
        )
        if ledger.record(record):
            created += 1
        else:
            existing += 1
    return LearningSyncResult(
        scanned_outcomes=len(outcomes),
        created_records=created,
        existing_records=existing,
    )
