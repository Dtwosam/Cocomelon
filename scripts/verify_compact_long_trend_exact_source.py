"""Audit exact source presence and content before compact LONG-trend packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_long_trend_5m_exit_source import (
    FROZEN_STARTED_AT_MS as FROZEN_FIVE_MINUTE_START_MS,
)
from cocomelon.research.prospective_long_trend_15m_exit_source import (
    FROZEN_STARTED_AT_MS as FROZEN_FIFTEEN_MINUTE_START_MS,
)

# Never select a clean period from observed returns. The already-frozen
# candidate start times, not a retrospectively chosen PnL breakpoint, set
# this exact export boundary for both downstream independent exit studies.
CLEAN_FORWARD_START_MS = min(
    FROZEN_FIVE_MINUTE_START_MS,
    FROZEN_FIFTEEN_MINUTE_START_MS,
)

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
    is_clean = raw.get("risk_rejected_integrity_clean")
    if type(is_clean) is not bool:
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

    # The 5m and 15m original producers already enforce their *independent*
    # frozen start times against risk_rejected_integrity_last_miss_at_ms.
    # This shared compact preflight must use the EARLIEST frozen start.
    # Never rewrite the dirty legacy summary or re-label it globally clean.
    metrics["frozen_forward_scope_start_ms"] = CLEAN_FORWARD_START_MS
    metrics["historic_missing_rank_retained"] = raw.get(
        "risk_rejected_missing_rank"
    )
    metrics["entire_history_integrity_clean"] = is_clean
    if not is_clean:
        last_miss = raw.get("risk_rejected_integrity_last_miss_at_ms")
        metrics["last_integrity_miss_at_ms"] = last_miss
        if type(last_miss) is not int or last_miss < 0:
            return "risk_rejected_integrity_not_clean", metrics
        if last_miss >= CLEAN_FORWARD_START_MS:
            return "risk_rejected_integrity_overlaps_frozen_window", metrics
        metrics["scope"] = "frozen_forward_only_historical_defects_retained"
    else:
        metrics["scope"] = "entire_history"

    # Every row is retained; do not compact away missing-rank, stale,
    # malformed or out-of-order evidence after the frozen boundary. An
    # unavailable rank in that window must fail rather than be inferred.
    eligible_count = 0
    for row in rows:
        if not isinstance(row, dict):
            return "risk_rejected_row_invalid", metrics
        at_ms = row.get("timestamp_ms")
        if type(at_ms) is not int or at_ms < overlap:
            return "risk_rejected_row_timestamp_invalid", metrics
        if at_ms < CLEAN_FORWARD_START_MS:
            continue
        eligible_count += 1
        ordinal = row.get("rank_ordinal")
        rank_age = row.get("rank_age_ms")
        if (
            type(ordinal) is not int
            or ordinal <= 0
            or type(rank_age) is not int
            or rank_age < 0
        ):
            return "frozen_forward_rank_integrity_not_clean", metrics
    metrics["frozen_forward_rank_checked_rows"] = eligible_count
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
