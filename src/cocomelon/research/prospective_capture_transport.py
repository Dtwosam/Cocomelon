from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_evidence import (
    MAX_ENTRY_CANDLE_AGE_MS,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)

FROZEN_OBSERVER_SOURCE_REVISION = "0131fccdb09a2b9ba959dd5785ea213a6297f719"

LEGACY_CAPTURE_SCHEDULE_CRON = "3,8,13 * * * *"
LEGACY_CAPTURE_ATTEMPT_MINUTES_UTC = (3, 8, 13)
LEGACY_JOB_TIMEOUT_MINUTES = 10

CAPTURE_SCHEDULE_CRON = "47 * * * *"
CAPTURE_ATTEMPT_MINUTES_UTC = (3,)
CAPTURE_TRANSPORT = "off_peak_prewarm_v1"
PREWARM_MINUTE_UTC = 47
PROTECTED_ATTEMPT_MINUTE_UTC = 3
JOB_TIMEOUT_MINUTES = 30

CONTROL_PLANE_KIND = "prospective-hype-clean-control-plane"
CONTROL_PLANE_SCHEMA_VERSION = 2
LEGACY_CONTROL_PLANE_SCHEMA_VERSION = 1

CONTROL_PLANE_SUPERSESSION_KIND = (
    "prospective-hype-clean-control-plane-supersession"
)
CONTROL_PLANE_SUPERSESSION_REASON = (
    "github_schedule_delivery_unreliable_pre_cutover"
)
CONTROL_PLANE_SUPERSESSION_SCHEMA_VERSION = 1


class ProspectiveCaptureTransportError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _with_control_plane_id(payload: dict[str, object]) -> dict[str, object]:
    resolved = dict(payload)
    resolved["control_plane_id"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return resolved


def _base_control_plane() -> dict[str, object]:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    plan = HYPE_PROSPECTIVE_VALIDATION_V1
    return {
        "kind": CONTROL_PLANE_KIND,
        "candidate_spec_id": spec.spec_id,
        "validation_plan_id": plan.plan_id,
        "observer_source_revision": FROZEN_OBSERVER_SOURCE_REVISION,
        "max_entry_candle_age_ms": MAX_ENTRY_CANDLE_AGE_MS,
        "state_artifact_name": "prospective-hype-clean-state",
        "evidence_root": "artifacts/prospective-hype-clean",
        "concurrency_group": "prospective-hype-clean-observer",
        "cancel_in_progress": False,
        "execution_mode": "paper",
        "api_url": "https://api.hyperliquid.xyz",
        "ws_url": "wss://api.hyperliquid.xyz/ws",
        "contents_permission": "read",
        "actions_permission": "read",
        "artifact_retention_days": 90,
    }


def build_legacy_prospective_hype_control_plane() -> dict[str, object]:
    return _with_control_plane_id(
        {
            **_base_control_plane(),
            "schedule_cron": LEGACY_CAPTURE_SCHEDULE_CRON,
            "attempt_minutes_utc": list(LEGACY_CAPTURE_ATTEMPT_MINUTES_UTC),
            "job_timeout_minutes": LEGACY_JOB_TIMEOUT_MINUTES,
            "schema_version": LEGACY_CONTROL_PLANE_SCHEMA_VERSION,
        }
    )


def build_prospective_hype_control_plane() -> dict[str, object]:
    return _with_control_plane_id(
        {
            **_base_control_plane(),
            "schedule_cron": CAPTURE_SCHEDULE_CRON,
            "attempt_minutes_utc": list(CAPTURE_ATTEMPT_MINUTES_UTC),
            "capture_transport": CAPTURE_TRANSPORT,
            "prewarm_minute_utc": PREWARM_MINUTE_UTC,
            "protected_attempt_minute_utc": PROTECTED_ATTEMPT_MINUTE_UTC,
            "job_timeout_minutes": JOB_TIMEOUT_MINUTES,
            "schema_version": CONTROL_PLANE_SCHEMA_VERSION,
        }
    )


def build_control_plane_supersession(
    *,
    superseded_at_ms: int,
) -> dict[str, object]:
    plan = HYPE_PROSPECTIVE_VALIDATION_V1
    if superseded_at_ms < 0:
        raise ValueError("superseded_at_ms must be non-negative")
    if superseded_at_ms >= plan.validation_start_ms:
        raise ValueError("control-plane supersession must predate validation start")
    legacy = build_legacy_prospective_hype_control_plane()
    replacement = build_prospective_hype_control_plane()
    payload: dict[str, object] = {
        "kind": CONTROL_PLANE_SUPERSESSION_KIND,
        "superseded_control_plane_id": legacy["control_plane_id"],
        "replacement_control_plane_id": replacement["control_plane_id"],
        "reason_code": CONTROL_PLANE_SUPERSESSION_REASON,
        "validation_start_ms": plan.validation_start_ms,
        "superseded_at_ms": superseded_at_ms,
        "observation_count_before": 0,
        "outcome_count_before": 0,
        "schema_version": CONTROL_PLANE_SUPERSESSION_SCHEMA_VERSION,
    }
    payload["supersession_id"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return payload


def verify_control_plane_supersession(
    path: str | Path,
) -> dict[str, object]:
    resolved = Path(path)
    if not resolved.is_file():
        raise ProspectiveCaptureTransportError(
            "CONTROL_PLANE_SUPERSESSION_MISSING"
        )
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveCaptureTransportError(
            "CONTROL_PLANE_SUPERSESSION_INVALID"
        ) from exc
    if not isinstance(raw, dict):
        raise ProspectiveCaptureTransportError(
            "CONTROL_PLANE_SUPERSESSION_INVALID"
        )
    payload = cast(dict[str, object], raw)
    supplied_id = payload.get("supersession_id")
    identity = {
        key: value
        for key, value in payload.items()
        if key != "supersession_id"
    }
    calculated_id = hashlib.sha256(
        _canonical_json(identity).encode("utf-8")
    ).hexdigest()
    if supplied_id != calculated_id:
        raise ProspectiveCaptureTransportError(
            "CONTROL_PLANE_SUPERSESSION_ID_MISMATCH"
        )

    legacy = build_legacy_prospective_hype_control_plane()
    replacement = build_prospective_hype_control_plane()
    plan = HYPE_PROSPECTIVE_VALIDATION_V1
    expected_static = {
        "kind": CONTROL_PLANE_SUPERSESSION_KIND,
        "superseded_control_plane_id": legacy["control_plane_id"],
        "replacement_control_plane_id": replacement["control_plane_id"],
        "reason_code": CONTROL_PLANE_SUPERSESSION_REASON,
        "validation_start_ms": plan.validation_start_ms,
        "observation_count_before": 0,
        "outcome_count_before": 0,
        "schema_version": CONTROL_PLANE_SUPERSESSION_SCHEMA_VERSION,
    }
    for key, value in expected_static.items():
        if payload.get(key) != value:
            raise ProspectiveCaptureTransportError(
                "CONTROL_PLANE_SUPERSESSION_MISMATCH"
            )
    superseded_at_ms = payload.get("superseded_at_ms")
    if (
        isinstance(superseded_at_ms, bool)
        or not isinstance(superseded_at_ms, int)
        or superseded_at_ms < 0
        or superseded_at_ms >= plan.validation_start_ms
    ):
        raise ProspectiveCaptureTransportError(
            "CONTROL_PLANE_SUPERSESSION_TIME_INVALID"
        )
    return payload
