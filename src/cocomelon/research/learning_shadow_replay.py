from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evidence.bundle import load_baseline_replay_bundle
from cocomelon.journal.store import JournalStore
from cocomelon.research.cohort import run_baseline_replay_payload
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.learning_shadow_evidence import (
    SHADOW_SOURCE_EVIDENCE_CLASS,
    LearningShadowEvidenceStore,
    open_verified_learning_shadow_evidence_store,
)
from cocomelon.research.learning_shadow_strategy import (
    LearningShadowStrategyEvaluator,
    build_learning_shadow_strategy_evaluator,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceRecord,
)
from cocomelon.research.strategy_seam import (
    StrategyEvaluator,
    build_candidate_strategy_decisions,
    load_candidate_strategy_decisions,
    strategy_context_from_payload,
    strategy_decision_to_payload,
)

LEARNING_SHADOW_REPLAY_SCHEMA_VERSION = 1


class LearningShadowReplayError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 identity")


def _require_git_sha(value: str, field: str) -> None:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase 40-character git SHA")


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningShadowReplayError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningShadowReplayError(f"{field} must be a non-negative integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningShadowReplayError(f"{field} must be boolean")
    return value


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningShadowReplayError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _write_consistent(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LearningShadowReplayError(
                f"LEARNING_SHADOW_REPLAY_CONFLICT:{path.name}"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True, slots=True)
class LearningShadowReplayReceipt:
    shadow_admission_id: str
    candidate_id: str
    runtime_code_revision: str
    source_bundle_id: str
    source_manifest_id: str
    recording_session_digest: str
    source_set_digest: str
    candidate_decisions_sha256: str
    contexts_digest: str
    replay_run_id: str
    replay_result_digest: str
    shadow_campaign_id: str
    closed_trade_ids: tuple[str, ...]
    created_shadow_records: int
    existing_shadow_records: int
    feature_snapshot_count: int
    feature_snapshot_state_digest: str
    shadow_evidence_state_digest: str
    evidence_eligible_at_ms: int
    paper_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    live_promotion_authorized: bool = False
    schema_version: int = LEARNING_SHADOW_REPLAY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "shadow_admission_id",
            "candidate_id",
            "recording_session_digest",
            "source_set_digest",
            "candidate_decisions_sha256",
            "contexts_digest",
            "replay_result_digest",
            "shadow_campaign_id",
            "feature_snapshot_state_digest",
            "shadow_evidence_state_digest",
        ):
            _require_sha256(getattr(self, field), field)
        _require_git_sha(self.runtime_code_revision, "runtime_code_revision")
        if not self.source_bundle_id.strip():
            raise ValueError("source_bundle_id must not be empty")
        if not self.source_manifest_id.strip():
            raise ValueError("source_manifest_id must not be empty")
        if not self.replay_run_id.strip():
            raise ValueError("replay_run_id must not be empty")
        if len(set(self.closed_trade_ids)) != len(self.closed_trade_ids):
            raise ValueError("closed trade ids must be unique")
        if any(not item.strip() for item in self.closed_trade_ids):
            raise ValueError("closed trade ids must not be empty")
        if min(
            self.created_shadow_records,
            self.existing_shadow_records,
            self.feature_snapshot_count,
            self.evidence_eligible_at_ms,
        ) < 0:
            raise ValueError("shadow replay counts/timestamp must be non-negative")
        if (
            self.created_shadow_records + self.existing_shadow_records
            != len(self.closed_trade_ids)
        ):
            raise ValueError("shadow replay evidence counts must reconcile")
        if not self.paper_only or not self.research_only:
            raise ValueError("shadow replay must remain paper research")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("shadow replay cannot authorize promotion or execution")
        if self.live_promotion_authorized:
            raise ValueError("shadow replay cannot authorize live capital")
        if self.schema_version != LEARNING_SHADOW_REPLAY_SCHEMA_VERSION:
            raise ValueError("unsupported learning shadow replay schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "shadow_admission_id": self.shadow_admission_id,
            "candidate_id": self.candidate_id,
            "runtime_code_revision": self.runtime_code_revision,
            "source_bundle_id": self.source_bundle_id,
            "source_manifest_id": self.source_manifest_id,
            "recording_session_digest": self.recording_session_digest,
            "source_set_digest": self.source_set_digest,
            "candidate_decisions_sha256": self.candidate_decisions_sha256,
            "contexts_digest": self.contexts_digest,
            "replay_run_id": self.replay_run_id,
            "replay_result_digest": self.replay_result_digest,
            "shadow_campaign_id": self.shadow_campaign_id,
            "closed_trade_ids": self.closed_trade_ids,
            "created_shadow_records": self.created_shadow_records,
            "existing_shadow_records": self.existing_shadow_records,
            "feature_snapshot_count": self.feature_snapshot_count,
            "feature_snapshot_state_digest": self.feature_snapshot_state_digest,
            "shadow_evidence_state_digest": self.shadow_evidence_state_digest,
            "evidence_eligible_at_ms": self.evidence_eligible_at_ms,
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "live_promotion_authorized": self.live_promotion_authorized,
            "schema_version": self.schema_version,
        }

    @property
    def receipt_id(self) -> str:
        return _sha256_bytes(
            _canonical_json(self.identity_payload()).encode("utf-8")
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_id": self.receipt_id}


def _strategy_evaluator(
    evaluator: LearningShadowStrategyEvaluator,
) -> StrategyEvaluator:
    def evaluate(request: dict[str, object]) -> dict[str, object]:
        context = strategy_context_from_payload(request.get("context"))
        decision = evaluator.evaluate(context)
        return strategy_decision_to_payload(decision)

    return evaluate


def _shadow_record(
    trade: TradeJournalEntry,
    *,
    store: LearningShadowEvidenceStore,
    shadow_campaign_id: str,
    evidence_eligible_at_ms: int,
) -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id=trade.trade_id,
        source_evidence_class=SHADOW_SOURCE_EVIDENCE_CLASS,
        candidate_id=store.admission.candidate_id,
        candidate_spec_id=store.admission.shadow_admission_id,
        campaign_id=shadow_campaign_id,
        market=trade.market,
        direction=trade.direction,
        opened_at_ms=trade.opened_at_ms,
        closed_at_ms=trade.closed_at_ms,
        feature_snapshot_id=trade.feature_snapshot_id,
        research_eligible_at_ms=evidence_eligible_at_ms,
        gross_realized_pnl=trade.gross_realized_pnl,
        entry_fees=trade.entry_fees,
        exit_fees=trade.exit_fees,
        funding_cash_pnl=trade.funding_cash_pnl,
        entry_slippage_fraction=trade.entry_slippage_fraction,
        exit_slippage_fraction=trade.exit_slippage_fraction,
        net_pnl=trade.net_pnl,
        net_r=trade.net_r,
    )


def _shadow_campaign_id(
    *,
    shadow_admission_id: str,
    source_bundle_id: str,
    candidate_decisions_sha256: str,
    replay_result_digest: str,
) -> str:
    return _sha256_bytes(
        _canonical_json(
            {
                "shadow_admission_id": shadow_admission_id,
                "source_bundle_id": source_bundle_id,
                "candidate_decisions_sha256": candidate_decisions_sha256,
                "replay_result_digest": replay_result_digest,
            }
        ).encode("utf-8")
    )


def run_learning_shadow_replay(
    *,
    recording_root: Path,
    bundle_path: Path,
    output_root: Path,
    shadow_evidence_root: Path,
    shadow_admission_path: Path,
    review_decision_path: Path,
    review_dossier_path: Path,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    finalization_path: Path,
    clean_evidence_root: Path,
    runtime_code_revision: str,
    evidence_eligible_at_ms: int,
) -> LearningShadowReplayReceipt:
    _require_git_sha(runtime_code_revision, "runtime_code_revision")
    if evidence_eligible_at_ms < 0:
        raise ValueError("evidence_eligible_at_ms must be non-negative")

    output_root.mkdir(parents=True, exist_ok=True)
    store = open_verified_learning_shadow_evidence_store(
        shadow_evidence_root,
        shadow_admission_path=shadow_admission_path,
        review_decision_path=review_decision_path,
        review_dossier_path=review_dossier_path,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        finalization_path=finalization_path,
        clean_evidence_root=clean_evidence_root,
    )
    evaluator = build_learning_shadow_strategy_evaluator(
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        shadow_admission_path=shadow_admission_path,
        review_decision_path=review_decision_path,
        review_dossier_path=review_dossier_path,
        validation_score_path=validation_score_path,
        finalization_path=finalization_path,
        clean_evidence_root=clean_evidence_root,
    )

    bundle = load_baseline_replay_bundle(bundle_path)
    decisions_path = output_root / "strategy-decisions.json"
    artifact = build_candidate_strategy_decisions(
        recording_root=recording_root,
        bundle_path=bundle_path,
        output_path=decisions_path,
        candidate_code_revision=runtime_code_revision,
        evaluator=_strategy_evaluator(evaluator),
    )
    decision_bytes = decisions_path.read_bytes()
    candidate_decisions_sha256 = _sha256_bytes(decision_bytes)

    journal_path = output_root / "journal.sqlite3"
    execution_path = output_root / "execution.sqlite3"
    facts_path = output_root / "facts.sqlite3"
    features_path = output_root / "learning-features"
    replay = run_baseline_replay_payload(
        bundle_path,
        journal_path,
        execution_path,
        facts_path,
        strategy_decisions_path=decisions_path,
        feature_store_path=features_path,
    )
    replay_bytes = (_canonical_json(replay) + "\n").encode("utf-8")
    _write_consistent(output_root / "replay.json", replay_bytes)

    replay_run_id = _string(replay.get("run_id"), "shadow replay run_id")
    replay_result_digest = _string(
        replay.get("result_digest"),
        "shadow replay result_digest",
    )
    _require_sha256(replay_result_digest, "replay_result_digest")
    closed_trade_ids_raw = replay.get("closed_trade_ids")
    if not isinstance(closed_trade_ids_raw, list) or not all(
        isinstance(item, str) and item.strip() for item in closed_trade_ids_raw
    ):
        raise LearningShadowReplayError("shadow replay closed_trade_ids are invalid")
    closed_trade_ids = tuple(cast(list[str], closed_trade_ids_raw))

    feature_store = LearningFeatureSnapshotStore(features_path)
    if replay.get("feature_snapshot_count") != len(feature_store.iter_verified()):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_FEATURE_COUNT_MISMATCH"
        )
    if replay.get("feature_snapshot_state_digest") != feature_store.state_digest:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_FEATURE_DIGEST_MISMATCH"
        )

    shadow_campaign_id = _shadow_campaign_id(
        shadow_admission_id=store.admission.shadow_admission_id,
        source_bundle_id=bundle.bundle_id,
        candidate_decisions_sha256=candidate_decisions_sha256,
        replay_result_digest=replay_result_digest,
    )

    journal = JournalStore(journal_path)
    try:
        trades = tuple(journal.iter_trades())
    finally:
        journal.close()
    actual_ids = tuple(trade.trade_id for trade in trades)
    if set(actual_ids) != set(closed_trade_ids) or len(actual_ids) != len(closed_trade_ids):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_JOURNAL_TRADE_MISMATCH"
        )

    created = 0
    existing = 0
    for trade in trades:
        if trade.replay_run_id != replay_run_id:
            raise LearningShadowReplayError(
                "LEARNING_SHADOW_REPLAY_RUN_ID_MISMATCH"
            )
        if evidence_eligible_at_ms < trade.closed_at_ms:
            raise LearningShadowReplayError(
                "LEARNING_SHADOW_REPLAY_EVIDENCE_ELIGIBILITY_PREMATURE"
            )
        verified = feature_store.load(trade.feature_snapshot_id)
        if verified is None:
            raise LearningShadowReplayError(
                "LEARNING_SHADOW_REPLAY_TRADE_FEATURE_MISSING"
            )
        snapshot = verified.snapshot
        if snapshot.market != trade.market:
            raise LearningShadowReplayError(
                "LEARNING_SHADOW_REPLAY_TRADE_FEATURE_MARKET_MISMATCH"
            )
        if (
            snapshot.as_of_ms > trade.opened_at_ms
            or snapshot.source_received_at_ms > trade.opened_at_ms
        ):
            raise LearningShadowReplayError(
                "LEARNING_SHADOW_REPLAY_TRADE_FEATURE_AFTER_OPEN"
            )
        record = _shadow_record(
            trade,
            store=store,
            shadow_campaign_id=shadow_campaign_id,
            evidence_eligible_at_ms=evidence_eligible_at_ms,
        )
        if store.record_execution(record):
            created += 1
        else:
            existing += 1

    store.verify()
    receipt = LearningShadowReplayReceipt(
        shadow_admission_id=store.admission.shadow_admission_id,
        candidate_id=store.admission.candidate_id,
        runtime_code_revision=runtime_code_revision,
        source_bundle_id=bundle.bundle_id,
        source_manifest_id=bundle.manifest.manifest_id,
        recording_session_digest=artifact.recording_session_digest,
        source_set_digest=artifact.source_set_digest,
        candidate_decisions_sha256=candidate_decisions_sha256,
        contexts_digest=artifact.contexts_digest,
        replay_run_id=replay_run_id,
        replay_result_digest=replay_result_digest,
        shadow_campaign_id=shadow_campaign_id,
        closed_trade_ids=tuple(sorted(closed_trade_ids)),
        created_shadow_records=created,
        existing_shadow_records=existing,
        feature_snapshot_count=len(feature_store.iter_verified()),
        feature_snapshot_state_digest=feature_store.state_digest,
        shadow_evidence_state_digest=store.state_digest,
        evidence_eligible_at_ms=evidence_eligible_at_ms,
    )
    _write_consistent(
        output_root / "shadow-replay-receipt.json",
        (_canonical_json(receipt.to_dict()) + "\n").encode("utf-8"),
    )
    return receipt

def _receipt_from_payload(raw: dict[str, object]) -> LearningShadowReplayReceipt:
    raw_trade_ids = raw.get("closed_trade_ids")
    if not isinstance(raw_trade_ids, list) or not all(
        isinstance(item, str) for item in raw_trade_ids
    ):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_TRADE_IDS_INVALID"
        )
    try:
        receipt = LearningShadowReplayReceipt(
            shadow_admission_id=_string(
                raw.get("shadow_admission_id"),
                "shadow_admission_id",
            ),
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            runtime_code_revision=_string(
                raw.get("runtime_code_revision"),
                "runtime_code_revision",
            ),
            source_bundle_id=_string(
                raw.get("source_bundle_id"),
                "source_bundle_id",
            ),
            source_manifest_id=_string(
                raw.get("source_manifest_id"),
                "source_manifest_id",
            ),
            recording_session_digest=_string(
                raw.get("recording_session_digest"),
                "recording_session_digest",
            ),
            source_set_digest=_string(
                raw.get("source_set_digest"),
                "source_set_digest",
            ),
            candidate_decisions_sha256=_string(
                raw.get("candidate_decisions_sha256"),
                "candidate_decisions_sha256",
            ),
            contexts_digest=_string(
                raw.get("contexts_digest"),
                "contexts_digest",
            ),
            replay_run_id=_string(raw.get("replay_run_id"), "replay_run_id"),
            replay_result_digest=_string(
                raw.get("replay_result_digest"),
                "replay_result_digest",
            ),
            shadow_campaign_id=_string(
                raw.get("shadow_campaign_id"),
                "shadow_campaign_id",
            ),
            closed_trade_ids=tuple(raw_trade_ids),
            created_shadow_records=_integer(
                raw.get("created_shadow_records"),
                "created_shadow_records",
            ),
            existing_shadow_records=_integer(
                raw.get("existing_shadow_records"),
                "existing_shadow_records",
            ),
            feature_snapshot_count=_integer(
                raw.get("feature_snapshot_count"),
                "feature_snapshot_count",
            ),
            feature_snapshot_state_digest=_string(
                raw.get("feature_snapshot_state_digest"),
                "feature_snapshot_state_digest",
            ),
            shadow_evidence_state_digest=_string(
                raw.get("shadow_evidence_state_digest"),
                "shadow_evidence_state_digest",
            ),
            evidence_eligible_at_ms=_integer(
                raw.get("evidence_eligible_at_ms"),
                "evidence_eligible_at_ms",
            ),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
            research_only=_boolean(raw.get("research_only"), "research_only"),
            promotion_eligible=_boolean(
                raw.get("promotion_eligible"),
                "promotion_eligible",
            ),
            execution_ready=_boolean(
                raw.get("execution_ready"),
                "execution_ready",
            ),
            live_promotion_authorized=_boolean(
                raw.get("live_promotion_authorized"),
                "live_promotion_authorized",
            ),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except ValueError as exc:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_INVALID"
        ) from exc
    if raw.get("receipt_id") != receipt.receipt_id:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_ID_MISMATCH"
        )
    return receipt


def load_learning_shadow_replay_receipt(
    path: Path,
) -> LearningShadowReplayReceipt:
    try:
        stored = path.read_bytes()
        raw = _mapping(
            json.loads(stored),
            "learning shadow replay receipt",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_INVALID"
        ) from exc
    receipt = _receipt_from_payload(raw)
    canonical = (_canonical_json(receipt.to_dict()) + "\n").encode("utf-8")
    if stored != canonical:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_NON_CANONICAL"
        )
    return receipt


def verify_learning_shadow_replay_receipt(
    path: Path,
    *,
    bundle_path: Path,
    output_root: Path,
    shadow_evidence_root: Path,
    shadow_admission_path: Path,
    review_decision_path: Path,
    review_dossier_path: Path,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    finalization_path: Path,
    clean_evidence_root: Path,
) -> LearningShadowReplayReceipt:
    receipt = load_learning_shadow_replay_receipt(path)
    bundle = load_baseline_replay_bundle(bundle_path)
    if (
        receipt.source_bundle_id != bundle.bundle_id
        or receipt.source_manifest_id != bundle.manifest.manifest_id
    ):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_BUNDLE_MISMATCH"
        )

    decisions_path = output_root / "strategy-decisions.json"
    decisions = load_candidate_strategy_decisions(
        decisions_path,
        bundle_path=bundle_path,
    )
    if _sha256_bytes(decisions_path.read_bytes()) != receipt.candidate_decisions_sha256:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_DECISION_DIGEST_MISMATCH"
        )
    if decisions.candidate_code_revision != receipt.runtime_code_revision:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_CODE_REVISION_MISMATCH"
        )
    if (
        decisions.recording_session_digest != receipt.recording_session_digest
        or decisions.source_set_digest != receipt.source_set_digest
        or decisions.contexts_digest != receipt.contexts_digest
    ):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_DECISION_LINEAGE_MISMATCH"
        )

    try:
        replay_bytes = (output_root / "replay.json").read_bytes()
        replay = _mapping(
            json.loads(replay_bytes),
            "learning shadow replay payload",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_REPLAY_INVALID"
        ) from exc
    if replay_bytes != (_canonical_json(replay) + "\n").encode("utf-8"):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_REPLAY_NON_CANONICAL"
        )
    if _string(replay.get("run_id"), "replay run_id") != receipt.replay_run_id:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_RUN_ID_MISMATCH"
        )
    if (
        _string(replay.get("result_digest"), "replay result_digest")
        != receipt.replay_result_digest
    ):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_RESULT_DIGEST_MISMATCH"
        )
    raw_closed = replay.get("closed_trade_ids")
    if not isinstance(raw_closed, list) or not all(
        isinstance(item, str) for item in raw_closed
    ):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_REPLAY_TRADES_INVALID"
        )
    if tuple(sorted(raw_closed)) != receipt.closed_trade_ids:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_REPLAY_TRADES_MISMATCH"
        )

    feature_store = LearningFeatureSnapshotStore(
        output_root / "learning-features"
    )
    features = feature_store.iter_verified()
    if (
        len(features) != receipt.feature_snapshot_count
        or feature_store.state_digest != receipt.feature_snapshot_state_digest
    ):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_FEATURE_STATE_MISMATCH"
        )

    journal = JournalStore(output_root / "journal.sqlite3")
    try:
        trades = tuple(journal.iter_trades())
    finally:
        journal.close()
    if tuple(sorted(trade.trade_id for trade in trades)) != receipt.closed_trade_ids:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_JOURNAL_MISMATCH"
        )
    if any(trade.replay_run_id != receipt.replay_run_id for trade in trades):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_JOURNAL_RUN_MISMATCH"
        )
    if any(
        receipt.evidence_eligible_at_ms < trade.closed_at_ms for trade in trades
    ):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_ELIGIBILITY_MISMATCH"
        )

    store = open_verified_learning_shadow_evidence_store(
        shadow_evidence_root,
        shadow_admission_path=shadow_admission_path,
        review_decision_path=review_decision_path,
        review_dossier_path=review_dossier_path,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        finalization_path=finalization_path,
        clean_evidence_root=clean_evidence_root,
    )
    if store.admission.shadow_admission_id != receipt.shadow_admission_id:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_ADMISSION_MISMATCH"
        )
    if store.admission.candidate_id != receipt.candidate_id:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_CANDIDATE_MISMATCH"
        )
    expected_campaign_id = _shadow_campaign_id(
        shadow_admission_id=receipt.shadow_admission_id,
        source_bundle_id=receipt.source_bundle_id,
        candidate_decisions_sha256=receipt.candidate_decisions_sha256,
        replay_result_digest=receipt.replay_result_digest,
    )
    if expected_campaign_id != receipt.shadow_campaign_id:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_CAMPAIGN_ID_MISMATCH"
        )
    campaign_records = tuple(
        record
        for record in store.iter_records()
        if record.campaign_id == receipt.shadow_campaign_id
    )
    if tuple(sorted(record.source_record_id for record in campaign_records)) != (
        receipt.closed_trade_ids
    ):
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_EVIDENCE_TRADES_MISMATCH"
        )
    if store.state_digest != receipt.shadow_evidence_state_digest:
        raise LearningShadowReplayError(
            "LEARNING_SHADOW_REPLAY_RECEIPT_EVIDENCE_STATE_MISMATCH"
        )
    return receipt

