from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    SourceRecordKind,
    SourceSegment,
)
from cocomelon.domain.risk import RiskLimits
from cocomelon.evidence.contracts import (
    BaselineReplayConfig,
    FrozenBaselineReplayBundle,
    canonical_contract_payload,
)
from cocomelon.evidence.recording import load_recording_session
from cocomelon.replay.manifest import build_replay_manifest
from cocomelon.replay.source import JsonlReplaySource, validate_recording
from cocomelon.scanner.eligibility import EligibilityConfig


def _source_set_digest(segments: tuple[SourceSegment, ...]) -> str:
    encoded = json.dumps(
        [segment.canonical_payload() for segment in segments],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _config_snapshot(
    replay_config: BaselineReplayConfig,
    recording_session_digest: str,
) -> dict[str, object]:
    return {
        "replay_config": canonical_contract_payload(replay_config),
        "recording_session_digest": recording_session_digest,
    }


def _manifest(
    segments: tuple[SourceSegment, ...],
    *,
    replay_config: BaselineReplayConfig,
    recording_session_digest: str,
    code_revision: str,
    start_ms: int,
    end_ms: int,
    gap_refs: tuple[str, ...],
) -> ReplayManifest:
    return build_replay_manifest(
        segments,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=start_ms,
        end_ms=end_ms,
        code_revision=code_revision,
        config_snapshot=_config_snapshot(replay_config, recording_session_digest),
        feature_version=replay_config.feature_version,
        strategy_version=replay_config.strategy_version,
        risk_version=replay_config.risk_version,
        execution_config=replay_config.execution,
        gap_refs=gap_refs,
        replay_engine_version=replay_config.replay_engine_version,
    )


def freeze_baseline_replay_bundle(
    recording_root: str | Path,
    *,
    replay_config: BaselineReplayConfig,
    code_revision: str,
) -> FrozenBaselineReplayBundle:
    root = Path(recording_root)
    session = load_recording_session(root)
    if session is None:
        raise ValueError("recording session metadata is required to freeze a replay bundle")

    segments = validate_recording(root)
    start_ms = min(item.first_available_at_ms for item in segments)
    end_ms = max(item.last_available_at_ms for item in segments)
    provisional = _manifest(
        segments,
        replay_config=replay_config,
        recording_session_digest=session.session_id,
        code_revision=code_revision,
        start_ms=start_ms,
        end_ms=end_ms,
        gap_refs=(),
    )
    gap_refs = tuple(
        sorted(
            {
                record.event_key
                for record in JsonlReplaySource(root).iter_records(provisional)
                if record.record_kind is SourceRecordKind.DATA_GAP
                and record.event_key is not None
            }
        )
    )
    manifest = _manifest(
        segments,
        replay_config=replay_config,
        recording_session_digest=session.session_id,
        code_revision=code_revision,
        start_ms=start_ms,
        end_ms=end_ms,
        gap_refs=gap_refs,
    )
    return FrozenBaselineReplayBundle(
        manifest=manifest,
        replay_config=replay_config,
        recording_session_digest=session.session_id,
        source_set_digest=_source_set_digest(segments),
    )


def resolve_code_revision(explicit: str | None, *, cwd: Path) -> str:
    if explicit is not None:
        revision = explicit.strip().lower()
    else:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise RuntimeError("unable to resolve code revision") from exc
        revision = completed.stdout.strip().lower()
        if completed.returncode != 0:
            raise RuntimeError("unable to resolve code revision")
    if len(revision) not in {40, 64} or any(char not in "0123456789abcdef" for char in revision):
        raise RuntimeError("unable to resolve exact code revision")
    return revision


def _manifest_payload(manifest: ReplayManifest) -> dict[str, object]:
    return {
        "evidence_class": manifest.evidence_class.value,
        "start_ms": manifest.start_ms,
        "end_ms": manifest.end_ms,
        "segments": [item.canonical_payload() for item in manifest.segments],
        "gap_refs": list(manifest.gap_refs),
        "code_revision": manifest.code_revision,
        "config_digest": manifest.config_digest,
        "feature_version": manifest.feature_version,
        "strategy_version": manifest.strategy_version,
        "risk_version": manifest.risk_version,
        "execution_config_version": manifest.execution_config_version,
        "fee_schedule_id": manifest.fee_schedule_id,
        "replay_engine_version": manifest.replay_engine_version,
        "dataset_manifest_id": manifest.dataset_manifest_id,
        "schema_version": manifest.schema_version,
        "manifest_id": manifest.manifest_id,
    }


def _bundle_payload(bundle: FrozenBaselineReplayBundle) -> dict[str, object]:
    return {
        "schema_version": bundle.schema_version,
        "bundle_id": bundle.bundle_id,
        "manifest": _manifest_payload(bundle.manifest),
        "replay_config": canonical_contract_payload(bundle.replay_config),
        "recording_session_digest": bundle.recording_session_digest,
        "source_set_digest": bundle.source_set_digest,
    }


def write_baseline_replay_bundle(
    path: str | Path,
    bundle: FrozenBaselineReplayBundle,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            _bundle_payload(bundle),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    temporary = target.with_name(f".{target.name}.tmp")
    with temporary.open("wb") as handle:
        written = handle.write(encoded)
        if written != len(encoded):
            raise OSError(f"short replay bundle write: {written} of {len(encoded)} bytes")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a canonical decimal string")
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal") from exc
    if not resolved.is_finite():
        raise ValueError(f"{field} must be finite")
    return resolved


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a string array")
    return tuple(value)


def _source_segment(value: object) -> SourceSegment:
    raw = _mapping(value, "source segment")
    return SourceSegment(
        relative_path=_string(raw.get("relative_path"), "relative_path"),
        partition=_string(raw.get("partition"), "partition"),
        sha256=_string(raw.get("sha256"), "sha256"),
        byte_count=_integer(raw.get("byte_count"), "byte_count"),
        row_count=_integer(raw.get("row_count"), "row_count"),
        schema_version=_integer(raw.get("schema_version"), "schema_version"),
        first_available_at_ms=_integer(
            raw.get("first_available_at_ms"),
            "first_available_at_ms",
        ),
        last_available_at_ms=_integer(
            raw.get("last_available_at_ms"),
            "last_available_at_ms",
        ),
    )


def _replay_manifest(value: object) -> ReplayManifest:
    raw = _mapping(value, "manifest")
    segments_raw = raw.get("segments")
    if not isinstance(segments_raw, list):
        raise ValueError("segments must be an array")
    try:
        evidence_class = EvidenceClass(_string(raw.get("evidence_class"), "evidence_class"))
    except ValueError as exc:
        raise ValueError("unsupported evidence_class") from exc
    manifest = ReplayManifest(
        evidence_class=evidence_class,
        start_ms=_integer(raw.get("start_ms"), "start_ms"),
        end_ms=_integer(raw.get("end_ms"), "end_ms"),
        segments=tuple(_source_segment(item) for item in segments_raw),
        gap_refs=_string_list(raw.get("gap_refs"), "gap_refs"),
        code_revision=_string(raw.get("code_revision"), "code_revision"),
        config_digest=_string(raw.get("config_digest"), "config_digest"),
        feature_version=_string(raw.get("feature_version"), "feature_version"),
        strategy_version=_string(raw.get("strategy_version"), "strategy_version"),
        risk_version=_string(raw.get("risk_version"), "risk_version"),
        execution_config_version=_optional_string(
            raw.get("execution_config_version"),
            "execution_config_version",
        ),
        fee_schedule_id=_optional_string(raw.get("fee_schedule_id"), "fee_schedule_id"),
        replay_engine_version=_string(
            raw.get("replay_engine_version"),
            "replay_engine_version",
        ),
        dataset_manifest_id=_optional_string(
            raw.get("dataset_manifest_id"),
            "dataset_manifest_id",
        ),
        schema_version=_integer(raw.get("schema_version"), "schema_version"),
    )
    if raw.get("manifest_id") != manifest.manifest_id:
        raise ValueError("serialized manifest_id does not match manifest")
    return manifest


def _risk_limits(value: object) -> RiskLimits:
    raw = _mapping(value, "risk_limits")
    return RiskLimits(
        risk_per_trade=_decimal(raw.get("risk_per_trade"), "risk_per_trade"),
        max_open_risk=_decimal(raw.get("max_open_risk"), "max_open_risk"),
        daily_loss_limit=_decimal(raw.get("daily_loss_limit"), "daily_loss_limit"),
        weekly_drawdown_limit=_decimal(
            raw.get("weekly_drawdown_limit"),
            "weekly_drawdown_limit",
        ),
        consecutive_loss_cooldown=_integer(
            raw.get("consecutive_loss_cooldown"),
            "consecutive_loss_cooldown",
        ),
        cooldown_ms=_integer(raw.get("cooldown_ms"), "cooldown_ms"),
        correlation_bucket_risk_limit=_decimal(
            raw.get("correlation_bucket_risk_limit"),
            "correlation_bucket_risk_limit",
        ),
        max_gross_leverage=_decimal(raw.get("max_gross_leverage"), "max_gross_leverage"),
        max_available_margin_fraction=_decimal(
            raw.get("max_available_margin_fraction"),
            "max_available_margin_fraction",
        ),
        max_visible_depth_fraction=_decimal(
            raw.get("max_visible_depth_fraction"),
            "max_visible_depth_fraction",
        ),
        min_liquidation_stop_multiple=_decimal(
            raw.get("min_liquidation_stop_multiple"),
            "min_liquidation_stop_multiple",
        ),
        max_state_age_ms=_integer(raw.get("max_state_age_ms"), "max_state_age_ms"),
    )


def _eligibility(value: object) -> EligibilityConfig:
    raw = _mapping(value, "eligibility")
    return EligibilityConfig(
        max_context_age_ms=_integer(raw.get("max_context_age_ms"), "max_context_age_ms"),
        volume_quantile=_decimal(raw.get("volume_quantile"), "volume_quantile"),
        oi_quantile=_decimal(raw.get("oi_quantile"), "oi_quantile"),
        absolute_min_day_notional_volume=_decimal(
            raw.get("absolute_min_day_notional_volume"),
            "absolute_min_day_notional_volume",
        ),
        absolute_min_open_interest=_decimal(
            raw.get("absolute_min_open_interest"),
            "absolute_min_open_interest",
        ),
        max_book_age_ms=_integer(raw.get("max_book_age_ms"), "max_book_age_ms"),
        hard_max_spread_bps=_decimal(raw.get("hard_max_spread_bps"), "hard_max_spread_bps"),
        spread_quantile=_decimal(raw.get("spread_quantile"), "spread_quantile"),
        depth_quantile=_decimal(raw.get("depth_quantile"), "depth_quantile"),
        absolute_min_side_depth=_decimal(
            raw.get("absolute_min_side_depth"),
            "absolute_min_side_depth",
        ),
    )


def _execution(value: object) -> PaperExecutionConfig:
    raw = _mapping(value, "execution")
    return PaperExecutionConfig(
        config_version=_string(raw.get("config_version"), "config_version"),
        latency_ms=_integer(raw.get("latency_ms"), "latency_ms"),
        max_book_age_ms=_integer(raw.get("max_book_age_ms"), "max_book_age_ms"),
        max_asset_ctx_age_ms=_integer(
            raw.get("max_asset_ctx_age_ms"),
            "max_asset_ctx_age_ms",
        ),
        funding_reconciliation_grace_ms=_integer(
            raw.get("funding_reconciliation_grace_ms"),
            "funding_reconciliation_grace_ms",
        ),
        max_ioc_slippage_bps=_decimal(
            raw.get("max_ioc_slippage_bps"),
            "max_ioc_slippage_bps",
        ),
        taker_fee_rate=_decimal(raw.get("taker_fee_rate"), "taker_fee_rate"),
        fee_schedule_id=_string(raw.get("fee_schedule_id"), "fee_schedule_id"),
        native_perp_min_notional=_decimal(
            raw.get("native_perp_min_notional"),
            "native_perp_min_notional",
        ),
        paper_max_gross_leverage=_decimal(
            raw.get("paper_max_gross_leverage"),
            "paper_max_gross_leverage",
        ),
    )


def _replay_config(value: object) -> BaselineReplayConfig:
    raw = _mapping(value, "replay_config")
    return BaselineReplayConfig(
        starting_cash=_decimal(raw.get("starting_cash"), "starting_cash"),
        decision_interval=_string(raw.get("decision_interval"), "decision_interval"),
        decision_grace_ms=_integer(raw.get("decision_grace_ms"), "decision_grace_ms"),
        microstructure_window_ms=_integer(
            raw.get("microstructure_window_ms"),
            "microstructure_window_ms",
        ),
        correlation_bucket=_string(raw.get("correlation_bucket"), "correlation_bucket"),
        risk_limits=_risk_limits(raw.get("risk_limits")),
        eligibility=_eligibility(raw.get("eligibility")),
        execution=_execution(raw.get("execution")),
        liquidation_policy_id=_string(
            raw.get("liquidation_policy_id"),
            "liquidation_policy_id",
        ),
        feature_version=_string(raw.get("feature_version"), "feature_version"),
        strategy_version=_string(raw.get("strategy_version"), "strategy_version"),
        risk_version=_string(raw.get("risk_version"), "risk_version"),
        replay_engine_version=_string(
            raw.get("replay_engine_version"),
            "replay_engine_version",
        ),
        config_version=_string(raw.get("config_version"), "config_version"),
    )


def load_baseline_replay_bundle(path: str | Path) -> FrozenBaselineReplayBundle:
    bundle_path = Path(path)
    if not bundle_path.is_file():
        raise ValueError("baseline replay bundle must be an existing file")
    try:
        decoded: object = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("baseline replay bundle must contain valid JSON") from exc
    raw = _mapping(decoded, "baseline replay bundle")
    bundle = FrozenBaselineReplayBundle(
        manifest=_replay_manifest(raw.get("manifest")),
        replay_config=_replay_config(raw.get("replay_config")),
        recording_session_digest=_string(
            raw.get("recording_session_digest"),
            "recording_session_digest",
        ),
        source_set_digest=_string(raw.get("source_set_digest"), "source_set_digest"),
        schema_version=_integer(raw.get("schema_version"), "schema_version"),
    )
    if raw.get("bundle_id") != bundle.bundle_id:
        raise ValueError("serialized bundle_id does not match bundle")
    return bundle
