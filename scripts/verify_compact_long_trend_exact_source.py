"""Audit exact source presence and content before compact LONG-trend packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path

REQUIRED_FILES = (
    "prospective-full-stack-forward-markout-summary.json",
    "prospective-long-trend-execution-shadow-source.json",
)
REQUIRED_DIRS = (
    "opening-opportunities/records",
    "opening-opportunity-exit-books/records",
    "replacement-funding-boundaries/records",
)

LONG_TREND_KIND = "prospective-long-trend-carveout-execution-shadow-source-v2"
LONG_TREND_CANDIDATE = "prospective-top10-two-strike-momentum-no-long-trend-v1"


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_object(path: Path) -> dict[str, object]:
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError("payload must be a JSON object")
    return content


def _check_summary(raw: dict[str, object]) -> tuple[str | None, dict[str, object]]:
    rows = raw.get("risk_rejected_rows")
    evaluated = raw.get("risk_rejected_stack_evaluated")
    metrics = {
        "risk_rejected_integrity_clean": raw.get("risk_rejected_integrity_clean"),
        "risk_rejected_missing_rank": raw.get("risk_rejected_missing_rank"),
        "risk_rejected_stack_evaluated": evaluated,
        "risk_rejected_row_count": len(rows) if isinstance(rows, list) else None,
    }
    for key, expected in (
        ("enabled", True),
        ("error", None),
        ("research_only", True),
        ("execution_authority", False),
        ("promotion_authority", False),
        ("changes_readiness_gate", False),
        ("changes_closed_trade_readiness_gate", False),
    ):
        if raw.get(key) is not expected:
            return f"full_stack_{key}_invalid", metrics
    if raw.get("risk_rejected_integrity_clean") is not True:
        return "risk_rejected_integrity_not_clean", metrics
    if (
        not isinstance(rows, list)
        or type(evaluated) is not int
        or evaluated != len(rows)
    ):
        return "risk_rejected_row_count_mismatch", metrics
    overlap = raw.get("overlap_started_at_ms")
    if type(overlap) is not int or overlap < 0:
        return "full_stack_overlap_invalid", metrics
    return None, metrics


def _check_long_source(raw: dict[str, object]) -> tuple[str | None, dict[str, object]]:
    opportunities = raw.get("opportunities")
    count = raw.get("source_opportunity_count")
    metrics = {
        "source_opportunity_count": count,
        "source_record_count": (
            len(opportunities) if isinstance(opportunities, list) else None
        ),
        "missing_forward_paths": raw.get("missing_forward_paths"),
    }
    for key, expected in (
        ("schema_version", 2),
        ("kind", LONG_TREND_KIND),
        ("candidate_id", LONG_TREND_CANDIDATE),
        ("baseline_risk_reason", "weekly_drawdown_lockout"),
        ("enabled", True),
        ("error", None),
        ("research_only", True),
        ("execution_authority", False),
        ("promotion_authority", False),
        ("changes_execution", False),
        ("changes_risk_limits", False),
        ("changes_candidate_readiness", False),
        ("durable_gate_required", True),
    ):
        if raw.get(key) != expected or (
            isinstance(expected, bool) and type(raw.get(key)) is not bool
        ):
            return f"long_source_{key}_invalid", metrics
    if type(count) is not int or not isinstance(opportunities, list):
        return "long_source_record_count_invalid", metrics
    if count != len(opportunities):
        return "long_source_record_count_mismatch", metrics
    overlap = raw.get("overlap_started_at_ms")
    if type(overlap) is not int or overlap < 0:
        return "long_source_overlap_invalid", metrics
    config = raw.get("execution_config")
    config_digest = raw.get("execution_config_sha256")
    if not isinstance(config, dict) or not isinstance(config_digest, str):
        return "execution_config_lineage_missing", metrics
    try:
        if _sha256(config) != config_digest:
            return "execution_config_digest_mismatch", metrics
        payload = dict(raw)
        source_digest = payload.pop("source_sha256", None)
        # The live producer appends these two display/status fields after
        # computing its source_sha256 over the authoritative source payload.
        payload.pop("enabled", None)
        payload.pop("error", None)
        if not isinstance(source_digest, str) or _sha256(payload) != source_digest:
            return "long_source_digest_mismatch", metrics
    except (TypeError, ValueError):
        return "long_source_digest_invalid_json", metrics
    return None, metrics


def verify_source(root: Path) -> dict[str, object]:
    records: list[dict[str, object]] = []
    objects: dict[str, dict[str, object]] = {}
    for name in REQUIRED_FILES:
        candidate = root / name
        size = candidate.stat().st_size if candidate.is_file() else 0
        present = size > 0
        reason: str | None = None if present else "missing_or_empty"
        metrics: dict[str, object] = {}
        if present:
            try:
                payload = _read_object(candidate)
                objects[name] = payload
                if name == REQUIRED_FILES[0]:
                    reason, metrics = _check_summary(payload)
                else:
                    reason, metrics = _check_long_source(payload)
            except (OSError, ValueError, json.JSONDecodeError):
                reason = "unreadable_json_object"
        records.append(
            {
                "path": name,
                "type": "file",
                "present": present,
                "valid": present and reason is None,
                "reason": reason,
                "size_bytes": size,
                "metrics": metrics,
            }
        )
    summary = objects.get(REQUIRED_FILES[0])
    source = objects.get(REQUIRED_FILES[1])
    if (
        summary is not None
        and source is not None
        and summary.get("overlap_started_at_ms")
        != source.get("overlap_started_at_ms")
        and records[1]["valid"] is True
    ):
        records[1]["valid"] = False
        records[1]["reason"] = "source_summary_overlap_mismatch"
    for name in REQUIRED_DIRS:
        present = (root / name).is_dir()
        records.append(
            {
                "path": name,
                "type": "directory",
                "present": present,
                "valid": present,
                "reason": None if present else "missing_directory",
            }
        )
    return {
        "schema_version": 2,
        "kind": "compact-long-trend-exact-source-preflight",
        "source_run_id": os.getenv("GITHUB_RUN_ID", ""),
        "source_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", ""),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready": all(row["valid"] is True for row in records),
        "inputs": records,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--json-out", required=True, type=Path)
    args = parser.parse_args(argv)
    report = verify_source(args.state_root)
    args.json_out.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    if report["ready"] is not True:
        for item in report["inputs"]:
            if item["valid"] is not True:
                print(
                    "::error::unusable authenticated LONG-trend input: "
                    f"{item['type']} {item['path']} "
                    f"reason={item['reason']}"
                )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
