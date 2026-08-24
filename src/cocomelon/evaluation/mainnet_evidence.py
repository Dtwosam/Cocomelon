from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cocomelon.evaluation.aggregate import (
    EvidenceAggregationResult,
    aggregate_evaluation_evidence,
)

MAINNET_EVIDENCE_KIND = "genuine_public_hyperliquid_mainnet"
MAINNET_API_URL = "https://api.hyperliquid.xyz"
MAINNET_WS_URL = "wss://api.hyperliquid.xyz/ws"
ATTESTATION_NAME = "mainnet-attestation.json"


class MainnetEvidenceError(RuntimeError):
    pass


def _read_mapping(path: Path, field: str) -> dict[str, Any]:
    if not path.is_file():
        raise MainnetEvidenceError(f"{field} is missing: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MainnetEvidenceError(f"{field} must contain valid JSON") from exc
    if not isinstance(raw, dict):
        raise MainnetEvidenceError(f"{field} must contain a JSON object")
    return {str(key): value for key, value in raw.items()}


def _require_bool(value: object, expected: bool, field: str) -> None:
    if value is not expected:
        raise MainnetEvidenceError(f"{field} must be {str(expected).lower()}")


def _require_zero(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        raise MainnetEvidenceError(f"{field} must be zero")


def _validate_complete_mainnet_cohort(source_root: Path) -> None:
    summary = _read_mapping(source_root / "cohort-summary.json", "cohort summary")
    if summary.get("evidence_kind") != MAINNET_EVIDENCE_KIND:
        raise MainnetEvidenceError("cohort must be genuine public Hyperliquid mainnet evidence")
    if summary.get("economic_claim") != "none":
        raise MainnetEvidenceError("source cohort must not contain an economic claim")
    _require_bool(summary.get("data_complete"), True, "cohort data_complete")
    _require_zero(summary.get("recorded_gap_count"), "cohort recorded_gap_count")
    _require_zero(summary.get("recorded_duplicate_count"), "cohort recorded_duplicate_count")

    record = _read_mapping(source_root / "record.json", "record result")
    _require_bool(record.get("network_access"), True, "record network_access")
    _require_bool(record.get("live_orders"), False, "record live_orders")
    _require_zero(record.get("gap_count"), "record gap_count")
    _require_zero(record.get("duplicate_count"), "record duplicate_count")

    replay = _read_mapping(source_root / "replay.json", "replay result")
    _require_bool(replay.get("network_access"), False, "replay network_access")
    _require_bool(replay.get("live_orders"), False, "replay live_orders")
    _require_bool(replay.get("data_complete"), True, "replay data_complete")

    freeze = _read_mapping(source_root / "freeze.json", "freeze result")
    _require_bool(freeze.get("network_access"), False, "freeze network_access")
    _require_bool(freeze.get("live_orders"), False, "freeze live_orders")

    session = _read_mapping(
        source_root.parent / "recording" / "recording-session.json",
        "recording session",
    )
    if session.get("api_url") != MAINNET_API_URL or session.get("ws_url") != MAINNET_WS_URL:
        raise MainnetEvidenceError("recording session must use public Hyperliquid mainnet")


def aggregate_mainnet_evaluation_evidence(
    target_journal_path: str | Path,
    target_facts_path: str | Path,
    source_roots: Sequence[str | Path],
) -> EvidenceAggregationResult:
    if not source_roots:
        raise MainnetEvidenceError("at least one mainnet source root is required")
    roots = tuple(Path(item).resolve() for item in source_roots)
    for root in roots:
        _validate_complete_mainnet_cohort(root)
    return aggregate_evaluation_evidence(target_journal_path, target_facts_path, roots)
