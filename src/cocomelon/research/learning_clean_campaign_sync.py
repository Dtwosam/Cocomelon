from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from cocomelon.research.learning_candidate_package import (
    verify_learning_candidate_package,
)
from cocomelon.research.learning_candidate_predictor import (
    build_learning_candidate_predictor,
)
from cocomelon.research.learning_clean_evidence import (
    LearningCleanEvidenceStore,
    LearningCleanTradeOutcome,
)
from cocomelon.research.learning_clean_validation_spec import (
    verify_learning_clean_validation_spec,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.learning_training_rows import (
    resolve_learning_feature_values,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
)
from cocomelon.research.research_learning_sync import (
    sync_research_campaign_learning,
)

LEARNING_CLEAN_CAMPAIGN_SYNC_SCHEMA_VERSION = 1


class LearningCleanCampaignSyncError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 identity")


@dataclass(frozen=True, slots=True)
class LearningCleanCampaignSyncResult:
    candidate_id: str
    validation_spec_id: str
    candidate_package_id: str
    model_family: str
    upstream_run_id: int
    upstream_run_attempt: int
    upstream_head_sha: str
    upstream_artifact_id: int
    upstream_artifact_digest: str
    source_learning_receipt_id: str
    source_required_candidate_ids: tuple[str, ...]
    source_trade_count: int
    pre_validation_source_trade_count: int
    clean_prediction_ids: tuple[str, ...]
    clean_outcome_ids: tuple[str, ...]
    clean_trade_prediction_count: int
    clean_no_trade_prediction_count: int
    prediction_count_after: int
    settled_outcome_count_after: int
    unsettled_trade_prediction_count_after: int
    clean_evidence_state_digest: str
    paper_only: bool = True
    prospective_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_CLEAN_CAMPAIGN_SYNC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "validation_spec_id",
            "candidate_package_id",
            "source_learning_receipt_id",
            "clean_evidence_state_digest",
        ):
            _require_sha256(getattr(self, field), field)
        if not self.model_family.strip():
            raise ValueError("model_family must not be empty")
        if self.upstream_run_id <= 0 or self.upstream_run_attempt <= 0:
            raise ValueError("upstream run identity must be positive")
        if self.upstream_artifact_id <= 0:
            raise ValueError("upstream_artifact_id must be positive")
        if (
            len(self.upstream_head_sha) != 40
            or any(char not in "0123456789abcdef" for char in self.upstream_head_sha)
        ):
            raise ValueError("upstream_head_sha must be a lowercase commit SHA")
        if not self.upstream_artifact_digest.startswith("sha256:"):
            raise ValueError("upstream_artifact_digest must be sha256-prefixed")
        _require_sha256(
            self.upstream_artifact_digest.removeprefix("sha256:"),
            "upstream_artifact_digest",
        )
        if (
            tuple(sorted(self.source_required_candidate_ids))
            != self.source_required_candidate_ids
            or not self.source_required_candidate_ids
            or len(set(self.source_required_candidate_ids))
            != len(self.source_required_candidate_ids)
        ):
            raise ValueError(
                "source_required_candidate_ids must be unique sorted values"
            )
        for field in (
            "source_trade_count",
            "pre_validation_source_trade_count",
            "clean_trade_prediction_count",
            "clean_no_trade_prediction_count",
            "prediction_count_after",
            "settled_outcome_count_after",
            "unsettled_trade_prediction_count_after",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if self.pre_validation_source_trade_count > self.source_trade_count:
            raise ValueError("pre-validation source count cannot exceed source trades")
        eligible_count = (
            self.source_trade_count - self.pre_validation_source_trade_count
        )
        if len(self.clean_prediction_ids) != eligible_count:
            raise ValueError(
                "every post-validation source trade must map to one clean prediction"
            )
        if len(set(self.clean_prediction_ids)) != len(self.clean_prediction_ids):
            raise ValueError("clean prediction ids must be unique")
        if len(set(self.clean_outcome_ids)) != len(self.clean_outcome_ids):
            raise ValueError("clean outcome ids must be unique")
        for prediction_id in self.clean_prediction_ids:
            _require_sha256(prediction_id, "clean_prediction_id")
        for outcome_id in self.clean_outcome_ids:
            _require_sha256(outcome_id, "clean_outcome_id")
        if (
            self.clean_trade_prediction_count
            + self.clean_no_trade_prediction_count
            != len(self.clean_prediction_ids)
        ):
            raise ValueError("clean prediction counts must reconcile")
        if self.clean_trade_prediction_count != len(self.clean_outcome_ids):
            raise ValueError(
                "every clean trade prediction must carry one settled paper outcome"
            )
        if self.settled_outcome_count_after > self.prediction_count_after:
            raise ValueError("settled outcomes cannot exceed clean predictions")
        if (
            self.unsettled_trade_prediction_count_after
            > self.prediction_count_after
        ):
            raise ValueError("unsettled clean predictions cannot exceed predictions")
        if not self.paper_only or not self.prospective_only or not self.research_only:
            raise ValueError("clean campaign sync must remain prospective paper research")
        if self.promotion_eligible:
            raise ValueError("clean campaign sync cannot authorize promotion")
        if self.execution_ready:
            raise ValueError("clean campaign sync cannot authorize execution")
        if self.schema_version != LEARNING_CLEAN_CAMPAIGN_SYNC_SCHEMA_VERSION:
            raise ValueError("unsupported clean campaign sync schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "validation_spec_id": self.validation_spec_id,
            "candidate_package_id": self.candidate_package_id,
            "model_family": self.model_family,
            "upstream_run_id": self.upstream_run_id,
            "upstream_run_attempt": self.upstream_run_attempt,
            "upstream_head_sha": self.upstream_head_sha,
            "upstream_artifact_id": self.upstream_artifact_id,
            "upstream_artifact_digest": self.upstream_artifact_digest,
            "source_learning_receipt_id": self.source_learning_receipt_id,
            "source_required_candidate_ids": self.source_required_candidate_ids,
            "source_trade_count": self.source_trade_count,
            "pre_validation_source_trade_count": (
                self.pre_validation_source_trade_count
            ),
            "clean_prediction_ids": self.clean_prediction_ids,
            "clean_outcome_ids": self.clean_outcome_ids,
            "clean_trade_prediction_count": self.clean_trade_prediction_count,
            "clean_no_trade_prediction_count": self.clean_no_trade_prediction_count,
            "prediction_count_after": self.prediction_count_after,
            "settled_outcome_count_after": self.settled_outcome_count_after,
            "unsettled_trade_prediction_count_after": (
                self.unsettled_trade_prediction_count_after
            ),
            "clean_evidence_state_digest": self.clean_evidence_state_digest,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def sync_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "sync_id": self.sync_id}


def sync_learning_clean_research_campaign(
    *,
    campaign_root: Path,
    package_root: Path,
    validation_spec_path: Path,
    evidence_root: Path,
    upstream_run_id: int,
    upstream_run_attempt: int,
    upstream_head_sha: str,
    upstream_artifact_id: int,
    upstream_artifact_digest: str,
) -> LearningCleanCampaignSyncResult:
    package = verify_learning_candidate_package(package_root)
    spec = verify_learning_clean_validation_spec(
        validation_spec_path,
        package_root=package_root,
    )
    if package.candidate_id != spec.candidate_id:
        raise LearningCleanCampaignSyncError(
            "LEARNING_CLEAN_CAMPAIGN_CANDIDATE_MISMATCH"
        )
    if package.package_id != spec.candidate_package_id:
        raise LearningCleanCampaignSyncError(
            "LEARNING_CLEAN_CAMPAIGN_PACKAGE_MISMATCH"
        )

    predictor = build_learning_candidate_predictor(
        package_root=package_root,
        validation_spec_path=validation_spec_path,
    )
    clean_store = LearningCleanEvidenceStore(evidence_root, spec=spec)
    clean_store.verify()

    with TemporaryDirectory(prefix="cocomelon-clean-campaign-") as temporary:
        source_state = Path(temporary)
        source_receipt = sync_research_campaign_learning(
            campaign_root,
            state_root=source_state,
            upstream_run_id=upstream_run_id,
            upstream_run_attempt=upstream_run_attempt,
            upstream_head_sha=upstream_head_sha,
            upstream_artifact_id=upstream_artifact_id,
            upstream_artifact_digest=upstream_artifact_digest,
        )
        source_ledger = LearningEvidenceLedger(source_state / "ledger")
        source_features = LearningFeatureSnapshotStore(source_state / "features")
        source_records = source_ledger.iter_records()

        if len(source_records) != source_receipt.learning_record_count:
            raise LearningCleanCampaignSyncError(
                "LEARNING_CLEAN_CAMPAIGN_SOURCE_RECORD_COUNT_MISMATCH"
            )
        if len(source_records) != source_receipt.scanned_trades:
            raise LearningCleanCampaignSyncError(
                "LEARNING_CLEAN_CAMPAIGN_SOURCE_TRADE_COUNT_MISMATCH"
            )

        pre_validation = 0
        predictions = []
        outcomes = []
        prediction_sources: dict[str, str] = {}

        for record in source_records:
            if record.kind is not LearningEvidenceKind.PAPER_EXECUTION:
                raise LearningCleanCampaignSyncError(
                    "LEARNING_CLEAN_CAMPAIGN_SOURCE_KIND_INVALID"
                )
            verified_snapshot = source_features.load(record.feature_snapshot_id)
            if verified_snapshot is None:
                raise LearningCleanCampaignSyncError(
                    "LEARNING_CLEAN_CAMPAIGN_FEATURE_SNAPSHOT_MISSING"
                )
            snapshot = verified_snapshot.snapshot
            if snapshot.as_of_ms < spec.validation_start_ms:
                pre_validation += 1
                continue

            feature_values = resolve_learning_feature_values(
                record,
                predictor.feature_registry,
                feature_store=source_features,
            )
            prediction = predictor.score(
                feature_values=feature_values,
                observed_at_ms=snapshot.as_of_ms,
            )
            previous_source = prediction_sources.get(prediction.prediction_id)
            if previous_source is not None and previous_source != record.record_id:
                raise LearningCleanCampaignSyncError(
                    "LEARNING_CLEAN_CAMPAIGN_DUPLICATE_PREDICTION"
                )
            prediction_sources[prediction.prediction_id] = record.record_id
            clean_store.record_prediction(prediction)
            predictions.append(prediction)

            if not prediction.trade_eligible:
                continue
            if record.net_r is None:
                raise LearningCleanCampaignSyncError(
                    "LEARNING_CLEAN_CAMPAIGN_NET_R_MISSING"
                )
            outcome = LearningCleanTradeOutcome(
                prediction_id=prediction.prediction_id,
                candidate_id=spec.candidate_id,
                validation_spec_id=spec.spec_id,
                candidate_package_id=spec.candidate_package_id,
                source_trade_id=record.source_record_id,
                market=record.market.canonical,
                direction=record.direction.value,
                opened_at_ms=record.opened_at_ms,
                closed_at_ms=record.closed_at_ms,
                net_r=record.net_r,
            )
            clean_store.record_outcome(outcome)
            outcomes.append(outcome)

    clean_store.verify()
    all_predictions = clean_store.iter_predictions()
    all_outcomes = clean_store.iter_outcomes()
    unsettled = clean_store.unsettled_trade_prediction_ids
    prediction_ids = tuple(item.prediction_id for item in predictions)
    outcome_ids = tuple(item.outcome_id for item in outcomes)
    trade_count = sum(1 for item in predictions if item.trade_eligible)

    return LearningCleanCampaignSyncResult(
        candidate_id=spec.candidate_id,
        validation_spec_id=spec.spec_id,
        candidate_package_id=spec.candidate_package_id,
        model_family=spec.model_family,
        upstream_run_id=upstream_run_id,
        upstream_run_attempt=upstream_run_attempt,
        upstream_head_sha=upstream_head_sha,
        upstream_artifact_id=upstream_artifact_id,
        upstream_artifact_digest=upstream_artifact_digest,
        source_learning_receipt_id=source_receipt.receipt_id,
        source_required_candidate_ids=source_receipt.required_candidate_ids,
        source_trade_count=len(source_records),
        pre_validation_source_trade_count=pre_validation,
        clean_prediction_ids=prediction_ids,
        clean_outcome_ids=outcome_ids,
        clean_trade_prediction_count=trade_count,
        clean_no_trade_prediction_count=len(predictions) - trade_count,
        prediction_count_after=len(all_predictions),
        settled_outcome_count_after=len(all_outcomes),
        unsettled_trade_prediction_count_after=len(unsettled),
        clean_evidence_state_digest=clean_store.state_digest,
    )
