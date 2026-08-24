from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from cocomelon.domain.journal import JournalObservation, ObservationKind, TradeJournalEntry
from cocomelon.domain.replay import ReplayManifest, ReplayRecord, ReplayResult, SourceRecordKind
from cocomelon.journal.store import JournalConsistencyError, JournalStore
from cocomelon.replay.adapters import ReplayRequirements, validate_replay_evidence
from cocomelon.replay.clock import ReplayClock, canonical_record_order
from cocomelon.replay.source import ReplaySource


class ReplayInvariantError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayPipeline:
    on_record: Callable[[ReplayRecord, int], Sequence[JournalObservation]]
    finalize: Callable[[int], Sequence[TradeJournalEntry]]
    requirements: ReplayRequirements = ReplayRequirements()


def replay_run_id(manifest: ReplayManifest, requirements: ReplayRequirements) -> str:
    payload = {
        "manifest_id": manifest.manifest_id,
        "replay_engine_version": manifest.replay_engine_version,
        "requires_l2": requirements.requires_l2,
        "requires_trades": requirements.requires_trades,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _attach_run_id(observation: JournalObservation, run_id: str) -> JournalObservation:
    if observation.replay_run_id is not None and observation.replay_run_id != run_id:
        raise ReplayInvariantError("observation replay_run_id does not match replay run")
    if observation.replay_run_id == run_id:
        return observation
    return replace(observation, replay_run_id=run_id)


def _attach_trade_run_id(trade: TradeJournalEntry, run_id: str) -> TradeJournalEntry:
    if trade.replay_run_id is not None and trade.replay_run_id != run_id:
        raise ReplayInvariantError("trade replay_run_id does not match replay run")
    if trade.replay_run_id == run_id:
        return trade
    return replace(trade, replay_run_id=run_id)


def _prepare_run(journal: JournalStore, manifest_id: str, run_id: str) -> None:
    row = journal.connection.execute(
        "SELECT manifest_id, status FROM replay_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        journal.begin_run(manifest_id, run_id)
        return
    if row[0] != manifest_id:
        raise JournalConsistencyError(f"conflicting replay run: {run_id}")
    if row[1] not in {"running", "finished"}:
        raise JournalConsistencyError(f"invalid replay run state: {run_id}")


def _risk_counts(observations: Sequence[JournalObservation]) -> tuple[int, int]:
    approvals = 0
    rejections = 0
    for observation in observations:
        if observation.kind is not ObservationKind.RISK_DECISION:
            continue
        normalized = {reason.casefold() for reason in observation.reason_codes}
        if "risk_approved" in normalized or "approved" in normalized:
            approvals += 1
        else:
            rejections += 1
    return approvals, rejections


def _latest_account_state(observations: Sequence[JournalObservation]) -> str:
    candidates = tuple(
        observation
        for observation in observations
        if observation.kind is ObservationKind.ACCOUNT_STATE
        and observation.account_state_id is not None
    )
    if not candidates:
        raise ReplayInvariantError("replay produced no final account state observation")
    latest = max(candidates, key=lambda item: (item.timestamp_ms, item.observation_id))
    assert latest.account_state_id is not None
    return latest.account_state_id


class ReplayEngine:
    def __init__(
        self,
        source: ReplaySource,
        journal: JournalStore,
        pipeline: ReplayPipeline,
    ) -> None:
        self.source = source
        self.journal = journal
        self.pipeline = pipeline

    def run(self, manifest: ReplayManifest) -> ReplayResult:
        records = tuple(self.source.iter_records(manifest))
        for record in records:
            if not manifest.start_ms <= record.available_at_ms <= manifest.end_ms:
                raise ReplayInvariantError("replay source emitted record outside manifest window")
        ordered = canonical_record_order(records)
        validate_replay_evidence(manifest, ordered, self.pipeline.requirements)

        run_id = replay_run_id(manifest, self.pipeline.requirements)
        self.journal.record_manifest(manifest)
        _prepare_run(self.journal, manifest.manifest_id, run_id)

        clock = ReplayClock()
        observations: list[JournalObservation] = []
        processed_events = 0
        processed_gaps = 0
        for record in ordered:
            now_ms = clock.advance(record)
            if record.record_kind is SourceRecordKind.DATA_GAP:
                processed_gaps += 1
            else:
                processed_events += 1
            for raw_observation in self.pipeline.on_record(record, now_ms):
                if raw_observation.timestamp_ms > now_ms:
                    raise ReplayInvariantError("replay pipeline emitted future observation")
                observation = _attach_run_id(raw_observation, run_id)
                self.journal.record_observation(observation)
                observations.append(observation)

        trades = tuple(
            _attach_trade_run_id(trade, run_id)
            for trade in self.pipeline.finalize(manifest.end_ms)
        )
        for trade in trades:
            if trade.closed_at_ms > manifest.end_ms:
                raise ReplayInvariantError("replay finalized trade after manifest window")
            self.journal.record_trade(trade)

        risk_approvals, risk_rejections = _risk_counts(observations)
        strategy_decisions = sum(
            observation.kind is ObservationKind.STRATEGY_DECISION
            for observation in observations
        )
        execution_attempts = sum(
            observation.kind is ObservationKind.EXECUTION_ATTEMPT
            for observation in observations
        )
        unique_fill_ids = {
            fill_id
            for trade in trades
            for fill_id in trade.fill_ids
        }
        data_complete = processed_gaps == 0 and not any(
            observation.kind is ObservationKind.FUNDING_GAP for observation in observations
        )
        result = ReplayResult(
            manifest_id=manifest.manifest_id,
            run_id=run_id,
            evidence_class=manifest.evidence_class,
            start_ms=manifest.start_ms,
            end_ms=manifest.end_ms,
            processed_events=processed_events,
            processed_gaps=processed_gaps,
            strategy_decisions=strategy_decisions,
            risk_approvals=risk_approvals,
            risk_rejections=risk_rejections,
            execution_attempts=execution_attempts,
            fills=len(unique_fill_ids),
            opened_positions=len(trades),
            closed_positions=len(trades),
            journal_observations=len(observations),
            closed_trade_ids=tuple(trade.trade_id for trade in trades),
            final_account_state_id=_latest_account_state(observations),
            data_complete=data_complete,
        )
        self.journal.finish_run(result)
        return result
