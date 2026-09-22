from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from cocomelon.research.historical_archive_clean_checkpoint import (
    ArchiveCleanBlockEconomics,
    ArchiveCleanOperationalCheckpoint,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
)

FINALIZATION_SCHEMA_VERSION = 1
VERDICT_ELIGIBLE = "eligible_for_candidate_review"
VERDICT_FAILED = "validation_failed"


class HistoricalArchiveCleanFinalizationError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ArchiveCleanFinalBlockResult:
    block_index: int
    settled_trade_count: int
    long_trade_count: int
    short_trade_count: int
    gross_return_sum: Decimal
    modeled_cost_sum: Decimal
    net_return_sum: Decimal
    mean_net_return: Decimal | None
    min_required_trades: int
    min_required_mean_net_return: Decimal
    passes_trade_floor: bool
    passes_mean_floor: bool

    def __post_init__(self) -> None:
        if self.block_index < 0:
            raise ValueError("block_index must be non-negative")
        if self.settled_trade_count < 0:
            raise ValueError("settled_trade_count must be non-negative")
        if self.long_trade_count < 0 or self.short_trade_count < 0:
            raise ValueError("direction counts must be non-negative")
        if self.long_trade_count + self.short_trade_count != self.settled_trade_count:
            raise ValueError("direction counts must equal settled_trade_count")
        if self.min_required_trades <= 0:
            raise ValueError("min_required_trades must be positive")
        for field in (
            "gross_return_sum",
            "modeled_cost_sum",
            "net_return_sum",
            "min_required_mean_net_return",
        ):
            if not getattr(self, field).is_finite():
                raise ValueError(f"{field} must be finite")
        if self.modeled_cost_sum < Decimal("0"):
            raise ValueError("modeled_cost_sum must be non-negative")
        if self.net_return_sum != self.gross_return_sum - self.modeled_cost_sum:
            raise ValueError("net_return_sum must equal gross minus modeled cost")
        expected_mean = (
            None
            if self.settled_trade_count == 0
            else self.net_return_sum / Decimal(self.settled_trade_count)
        )
        if self.mean_net_return != expected_mean:
            raise ValueError("mean_net_return must match block totals")
        if self.passes_trade_floor != (
            self.settled_trade_count >= self.min_required_trades
        ):
            raise ValueError("passes_trade_floor must match block count")
        if self.passes_mean_floor != (
            self.mean_net_return is not None
            and self.mean_net_return > self.min_required_mean_net_return
        ):
            raise ValueError("passes_mean_floor must match block mean")

    def to_dict(self) -> dict[str, object]:
        return {
            "block_index": self.block_index,
            "settled_trade_count": self.settled_trade_count,
            "long_trade_count": self.long_trade_count,
            "short_trade_count": self.short_trade_count,
            "gross_return_sum": str(self.gross_return_sum),
            "modeled_cost_sum": str(self.modeled_cost_sum),
            "net_return_sum": str(self.net_return_sum),
            "mean_net_return": (
                None if self.mean_net_return is None else str(self.mean_net_return)
            ),
            "min_required_trades": self.min_required_trades,
            "min_required_mean_net_return": str(
                self.min_required_mean_net_return
            ),
            "passes_trade_floor": self.passes_trade_floor,
            "passes_mean_floor": self.passes_mean_floor,
        }


@dataclass(frozen=True, slots=True)
class ArchiveCleanFinalization:
    validation_spec_id: str
    candidate_id: str
    model_artifact_id: str
    campaign_id: str
    runtime_id: str
    pin_id: str
    checkpoint_id: str
    checkpoint_as_of_ms: int
    finalized_at_ms: int
    validation_start_ms: int
    validation_end_ms: int
    finalization_not_before_ms: int
    expected_anchor_count: int
    captured_anchor_count: int
    missing_anchor_count: int
    capture_coverage: Decimal
    min_capture_coverage: Decimal
    settled_trade_count: int
    min_settled_trades: int
    long_trade_count: int
    short_trade_count: int
    gross_return_sum: Decimal
    modeled_cost_sum: Decimal
    net_return_sum: Decimal
    mean_net_return: Decimal | None
    min_mean_net_return: Decimal
    block_results: tuple[ArchiveCleanFinalBlockResult, ...]
    pending_signal_count: int
    active_position_count: int
    reason_codes: tuple[str, ...]
    verdict: str
    eligible_for_candidate_review: bool
    paper_only: bool = True
    prospective_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = FINALIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "validation_spec_id",
            "candidate_id",
            "model_artifact_id",
            "campaign_id",
            "runtime_id",
            "pin_id",
            "checkpoint_id",
        ):
            _require_sha256(getattr(self, field), field)
        if self.checkpoint_as_of_ms < self.finalization_not_before_ms:
            raise ValueError("checkpoint must cover terminal settlement boundary")
        if self.finalized_at_ms < self.checkpoint_as_of_ms:
            raise ValueError("finalized_at_ms cannot precede checkpoint")
        if self.finalized_at_ms < self.finalization_not_before_ms:
            raise ValueError("finalization is premature")
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.validation_end_ms <= self.validation_start_ms:
            raise ValueError("validation_end_ms must follow validation start")
        if self.finalization_not_before_ms < self.validation_end_ms:
            raise ValueError("terminal boundary must follow validation end")
        if self.expected_anchor_count <= 0:
            raise ValueError("expected_anchor_count must be positive")
        if not 0 <= self.captured_anchor_count <= self.expected_anchor_count:
            raise ValueError("captured_anchor_count out of range")
        if self.missing_anchor_count != (
            self.expected_anchor_count - self.captured_anchor_count
        ):
            raise ValueError("missing_anchor_count mismatch")
        expected_coverage = Decimal(self.captured_anchor_count) / Decimal(
            self.expected_anchor_count
        )
        if self.capture_coverage != expected_coverage:
            raise ValueError("capture_coverage must match anchor counts")
        for field in ("capture_coverage", "min_capture_coverage"):
            value = getattr(self, field)
            if not value.is_finite() or value < Decimal("0") or value > Decimal("1"):
                raise ValueError(f"{field} must be between zero and one")
        if self.settled_trade_count < 0 or self.min_settled_trades <= 0:
            raise ValueError("settled trade counts invalid")
        if self.long_trade_count < 0 or self.short_trade_count < 0:
            raise ValueError("direction counts must be non-negative")
        if self.long_trade_count + self.short_trade_count != self.settled_trade_count:
            raise ValueError("direction counts must equal settled_trade_count")
        for field in (
            "gross_return_sum",
            "modeled_cost_sum",
            "net_return_sum",
            "min_mean_net_return",
        ):
            if not getattr(self, field).is_finite():
                raise ValueError(f"{field} must be finite")
        if self.modeled_cost_sum < Decimal("0"):
            raise ValueError("modeled_cost_sum must be non-negative")
        if self.net_return_sum != self.gross_return_sum - self.modeled_cost_sum:
            raise ValueError("net return sum must equal gross minus modeled cost")
        expected_mean = (
            None
            if self.settled_trade_count == 0
            else self.net_return_sum / Decimal(self.settled_trade_count)
        )
        if self.mean_net_return != expected_mean:
            raise ValueError("mean_net_return must match terminal totals")
        if not self.block_results:
            raise ValueError("block_results must not be empty")
        if tuple(item.block_index for item in self.block_results) != tuple(
            range(len(self.block_results))
        ):
            raise ValueError("block_results must be contiguous and ordered")
        if sum(item.settled_trade_count for item in self.block_results) != (
            self.settled_trade_count
        ):
            raise ValueError("block trade counts must equal terminal count")
        if sum(
            (item.gross_return_sum for item in self.block_results),
            Decimal("0"),
        ) != self.gross_return_sum:
            raise ValueError("block gross totals must equal terminal gross total")
        if sum(
            (item.modeled_cost_sum for item in self.block_results),
            Decimal("0"),
        ) != self.modeled_cost_sum:
            raise ValueError("block cost totals must equal terminal cost total")
        if sum(
            (item.net_return_sum for item in self.block_results),
            Decimal("0"),
        ) != self.net_return_sum:
            raise ValueError("block net totals must equal terminal net total")
        if self.pending_signal_count != 0:
            raise ValueError("finalization requires zero pending signals")
        if self.active_position_count != 0:
            raise ValueError("finalization requires zero active paper positions")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("reason_codes must be sorted unique")
        expected_eligible = not self.reason_codes
        if self.eligible_for_candidate_review != expected_eligible:
            raise ValueError("review eligibility must match failure reasons")
        expected_verdict = VERDICT_ELIGIBLE if expected_eligible else VERDICT_FAILED
        if self.verdict != expected_verdict:
            raise ValueError("verdict must match failure reasons")
        if not self.paper_only or not self.prospective_only:
            raise ValueError("finalization must remain paper/prospective only")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("finalization cannot authorize promotion or execution")
        if self.schema_version != FINALIZATION_SCHEMA_VERSION:
            raise ValueError("unsupported archive clean finalization schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "validation_spec_id": self.validation_spec_id,
            "candidate_id": self.candidate_id,
            "model_artifact_id": self.model_artifact_id,
            "campaign_id": self.campaign_id,
            "runtime_id": self.runtime_id,
            "pin_id": self.pin_id,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_as_of_ms": self.checkpoint_as_of_ms,
            "finalized_at_ms": self.finalized_at_ms,
            "validation_start_ms": self.validation_start_ms,
            "validation_end_ms": self.validation_end_ms,
            "finalization_not_before_ms": self.finalization_not_before_ms,
            "expected_anchor_count": self.expected_anchor_count,
            "captured_anchor_count": self.captured_anchor_count,
            "missing_anchor_count": self.missing_anchor_count,
            "capture_coverage": str(self.capture_coverage),
            "min_capture_coverage": str(self.min_capture_coverage),
            "settled_trade_count": self.settled_trade_count,
            "min_settled_trades": self.min_settled_trades,
            "long_trade_count": self.long_trade_count,
            "short_trade_count": self.short_trade_count,
            "gross_return_sum": str(self.gross_return_sum),
            "modeled_cost_sum": str(self.modeled_cost_sum),
            "net_return_sum": str(self.net_return_sum),
            "mean_net_return": (
                None if self.mean_net_return is None else str(self.mean_net_return)
            ),
            "min_mean_net_return": str(self.min_mean_net_return),
            "block_results": tuple(item.to_dict() for item in self.block_results),
            "pending_signal_count": self.pending_signal_count,
            "active_position_count": self.active_position_count,
            "reason_codes": self.reason_codes,
            "verdict": self.verdict,
            "eligible_for_candidate_review": self.eligible_for_candidate_review,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def finalization_id(self) -> str:
        return _sha256(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "finalization_id": self.finalization_id}


def _verify_checkpoint_lineage(
    spec: HistoricalArchiveCleanValidationSpec,
    *,
    runtime_id: str,
    pin_id: str,
    checkpoint: ArchiveCleanOperationalCheckpoint,
) -> None:
    expected = (
        spec.spec_id,
        spec.candidate_id,
        spec.model_artifact_id,
        runtime_id,
        pin_id,
        spec.first_expected_anchor_ms,
        spec.anchor_interval_ms,
        spec.expected_anchor_count,
        spec.stability_blocks,
        spec.anchors_per_stability_block,
    )
    actual = (
        checkpoint.validation_spec_id,
        checkpoint.candidate_id,
        checkpoint.model_artifact_id,
        checkpoint.runtime_id,
        checkpoint.pin_id,
        checkpoint.first_expected_anchor_ms,
        checkpoint.anchor_interval_ms,
        checkpoint.expected_anchor_count,
        checkpoint.stability_blocks,
        checkpoint.anchors_per_stability_block,
    )
    if actual != expected:
        raise HistoricalArchiveCleanFinalizationError(
            "ARCHIVE_CLEAN_FINALIZATION_LINEAGE_MISMATCH"
        )


def _block_result(
    block: ArchiveCleanBlockEconomics,
    *,
    spec: HistoricalArchiveCleanValidationSpec,
) -> ArchiveCleanFinalBlockResult:
    return ArchiveCleanFinalBlockResult(
        block_index=block.block_index,
        settled_trade_count=block.settled_trade_count,
        long_trade_count=block.long_trade_count,
        short_trade_count=block.short_trade_count,
        gross_return_sum=block.gross_return_sum,
        modeled_cost_sum=block.modeled_cost_sum,
        net_return_sum=block.net_return_sum,
        mean_net_return=block.mean_net_return,
        min_required_trades=spec.min_block_trades,
        min_required_mean_net_return=spec.min_block_mean_net_return,
        passes_trade_floor=block.settled_trade_count >= spec.min_block_trades,
        passes_mean_floor=(
            block.mean_net_return is not None
            and block.mean_net_return > spec.min_block_mean_net_return
        ),
    )


def build_archive_clean_finalization(
    spec: HistoricalArchiveCleanValidationSpec,
    *,
    runtime_id: str,
    pin_id: str,
    checkpoint: ArchiveCleanOperationalCheckpoint,
    finalized_at_ms: int,
) -> ArchiveCleanFinalization:
    _require_sha256(runtime_id, "runtime_id")
    _require_sha256(pin_id, "pin_id")
    _verify_checkpoint_lineage(
        spec,
        runtime_id=runtime_id,
        pin_id=pin_id,
        checkpoint=checkpoint,
    )
    if finalized_at_ms < spec.finalization_not_before_ms:
        raise HistoricalArchiveCleanFinalizationError(
            "ARCHIVE_CLEAN_FINALIZATION_PREMATURE"
        )
    if checkpoint.as_of_ms < spec.finalization_not_before_ms:
        raise HistoricalArchiveCleanFinalizationError(
            "ARCHIVE_CLEAN_FINALIZATION_CHECKPOINT_STALE"
        )
    pending_signal_count = sum(
        len(item.pending_signal_ids)
        for item in checkpoint.pending_observations
    )
    if pending_signal_count:
        raise HistoricalArchiveCleanFinalizationError(
            "ARCHIVE_CLEAN_FINALIZATION_PENDING_SETTLEMENTS"
        )
    active_position_count = len(
        checkpoint.latest_state.active_at(finalized_at_ms).positions
    )
    if active_position_count:
        raise HistoricalArchiveCleanFinalizationError(
            "ARCHIVE_CLEAN_FINALIZATION_ACTIVE_POSITIONS"
        )

    capture_coverage = Decimal(checkpoint.captured_anchor_count) / Decimal(
        spec.expected_anchor_count
    )
    block_results = tuple(
        _block_result(item, spec=spec) for item in checkpoint.block_economics
    )
    long_count = sum(item.long_trade_count for item in block_results)
    short_count = sum(item.short_trade_count for item in block_results)

    reasons: list[str] = []
    if capture_coverage < spec.min_capture_coverage:
        reasons.append("capture_coverage_below_minimum")
    if checkpoint.settled_outcome_count < spec.min_settled_trades:
        reasons.append("settled_trade_count_below_minimum")
    if (
        checkpoint.mean_net_return is None
        or checkpoint.mean_net_return <= spec.min_mean_net_return
    ):
        reasons.append("overall_mean_net_return_not_above_minimum")
    for item in block_results:
        if not item.passes_trade_floor:
            reasons.append(
                f"block_{item.block_index}_trade_count_below_minimum"
            )
        if not item.passes_mean_floor:
            reasons.append(
                f"block_{item.block_index}_mean_net_return_not_above_minimum"
            )
    reason_codes = tuple(sorted(reasons))
    eligible = not reason_codes

    return ArchiveCleanFinalization(
        validation_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        model_artifact_id=spec.model_artifact_id,
        campaign_id=checkpoint.campaign_id,
        runtime_id=runtime_id,
        pin_id=pin_id,
        checkpoint_id=checkpoint.checkpoint_id,
        checkpoint_as_of_ms=checkpoint.as_of_ms,
        finalized_at_ms=finalized_at_ms,
        validation_start_ms=spec.validation_start_ms,
        validation_end_ms=spec.validation_end_ms,
        finalization_not_before_ms=spec.finalization_not_before_ms,
        expected_anchor_count=spec.expected_anchor_count,
        captured_anchor_count=checkpoint.captured_anchor_count,
        missing_anchor_count=(
            spec.expected_anchor_count - checkpoint.captured_anchor_count
        ),
        capture_coverage=capture_coverage,
        min_capture_coverage=spec.min_capture_coverage,
        settled_trade_count=checkpoint.settled_outcome_count,
        min_settled_trades=spec.min_settled_trades,
        long_trade_count=long_count,
        short_trade_count=short_count,
        gross_return_sum=checkpoint.total_gross_return_sum,
        modeled_cost_sum=checkpoint.total_modeled_cost_sum,
        net_return_sum=checkpoint.total_net_return_sum,
        mean_net_return=checkpoint.mean_net_return,
        min_mean_net_return=spec.min_mean_net_return,
        block_results=block_results,
        pending_signal_count=0,
        active_position_count=0,
        reason_codes=reason_codes,
        verdict=VERDICT_ELIGIBLE if eligible else VERDICT_FAILED,
        eligible_for_candidate_review=eligible,
    )


def write_archive_clean_finalization(
    output_root: Path,
    finalization: ArchiveCleanFinalization,
) -> Path:
    path = output_root / "finalization.json"
    payload = (_canonical_json(finalization.to_dict()) + "\n").encode("utf-8")
    output_root.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise HistoricalArchiveCleanFinalizationError(
                "ARCHIVE_CLEAN_FINALIZATION_CONFLICT"
            )
        return path
    temporary = output_root / ".finalization.json.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path
