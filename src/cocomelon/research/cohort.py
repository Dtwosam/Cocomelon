from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from cocomelon.evaluation.cli_support import freeze_evaluation_dataset_payload
from cocomelon.evaluation.mainnet_evidence import (
    MAINNET_EVIDENCE_KIND,
    verify_mainnet_evidence_cohort_payload,
)
from cocomelon.evidence.cli_support import (
    freeze_baseline_replay_payload,
    run_baseline_replay_payload,
)
from cocomelon.evidence.recording import load_recording_session
from cocomelon.evidence.transport_health import normalize_redundant_record_payload
from cocomelon.replay.source import validate_recording


@dataclass(frozen=True, slots=True)
class ResearchCohortBuildResult:
    output_root: Path
    replay_run_id: str
    start_ms: int
    end_ms: int
    dataset_manifest_id: str


def _read_mapping(path: Path, field: str) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"research cohort {field} is missing: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"research cohort {field} must contain valid JSON") from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ValueError(f"research cohort {field} must be an object")
    return {str(key): value for key, value in raw.items()}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as handle:
        written = handle.write(encoded)
        if written != len(encoded):
            raise OSError(f"short research cohort write: {written} of {len(encoded)} bytes")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _require_sha(value: str, field: str) -> str:
    resolved = value.strip().lower()
    if len(resolved) != 40 or any(char not in "0123456789abcdef" for char in resolved):
        raise ValueError(f"{field} must be a 40-character commit SHA")
    return resolved


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _normalized_record(
    output_root: Path,
    *,
    recording_root: Path,
) -> dict[str, object]:
    raw = _read_mapping(output_root / "record-transport.json", "transport summary")
    record = normalize_redundant_record_payload(raw)
    if record.get("network_access") is not True:
        raise ValueError("research cohort transport summary must declare public network access")
    if record.get("live_orders") is not False:
        raise ValueError("research cohort transport summary must remain live_orders=false")
    if record.get("gap_count") != 0:
        raise ValueError("research cohort transport summary contains a coverage gap")

    session = load_recording_session(recording_root)
    if session is None:
        raise ValueError("research cohort recording session metadata is required")
    if record.get("session_id") != session.session_id:
        raise ValueError("research cohort transport session does not match recording")
    _require_int(record.get("event_count"), "research cohort transport event_count")

    selected = record.get("selected_markets")
    if not isinstance(selected, (list, tuple)) or not all(
        isinstance(item, str) and item.strip() for item in selected
    ):
        raise ValueError("research cohort transport selected_markets is invalid")
    expected_markets = sorted(item.market.canonical for item in session.selected)
    if sorted(selected) != expected_markets:
        raise ValueError("research cohort transport markets do not match recording session")
    return record


def _assert_sibling_layout(recording_root: Path, output_root: Path) -> None:
    expected = (output_root.parent / "recording").resolve()
    if recording_root.resolve() != expected:
        raise ValueError(
            "research cohort recording root must be the output root's recording sibling"
        )


def _assert_replay_eligible(replay: dict[str, object]) -> None:
    if replay.get("network_access") is not False:
        raise ValueError("research cohort replay must be offline")
    if replay.get("live_orders") is not False:
        raise ValueError("research cohort replay must remain live_orders=false")
    if replay.get("data_complete") is not True:
        raise ValueError("research cohort replay must be complete")
    opened = _require_int(replay.get("opened_positions"), "research replay opened_positions")
    closed = _require_int(replay.get("closed_positions"), "research replay closed_positions")
    if opened != closed:
        raise ValueError("research cohort replay must finish flat")


def _assert_dataset_eligible(dataset: dict[str, object]) -> None:
    if dataset.get("network_access") is not False:
        raise ValueError("research cohort dataset freeze must be offline")
    if dataset.get("data_complete") is not True or dataset.get("gap_refs") != []:
        raise ValueError("research cohort dataset must be complete and gap-free")


def build_research_cohort(
    recording_root: str | Path,
    output_root: str | Path,
    starting_cash: Decimal,
    *,
    trigger_head_sha: str,
) -> ResearchCohortBuildResult:
    recording = Path(recording_root)
    output = Path(output_root)
    _assert_sibling_layout(recording, output)
    if not output.is_dir():
        raise ValueError("research cohort output root must already exist")
    trigger_head = _require_sha(trigger_head_sha, "trigger_head_sha")

    segments = validate_recording(recording)
    if not segments:
        raise ValueError("research cohort recording must contain validated segments")
    record = _normalized_record(output, recording_root=recording)
    _write_json(output / "record.json", record)

    freeze = freeze_baseline_replay_payload(
        recording,
        output / "bundle.json",
        starting_cash,
    )
    _write_json(output / "freeze.json", freeze)
    workflow_head = _require_sha(
        _require_string(freeze.get("code_revision"), "research freeze code_revision"),
        "research freeze code_revision",
    )
    (output / "workflow-head.txt").write_text(workflow_head + "\n", encoding="utf-8")
    (output / "trigger-head.txt").write_text(trigger_head + "\n", encoding="utf-8")

    replay = run_baseline_replay_payload(
        output / "bundle.json",
        output / "journal.sqlite3",
        output / "execution.sqlite3",
        output / "facts.sqlite3",
    )
    _assert_replay_eligible(replay)
    _write_json(output / "replay.json", replay)

    run_id = _require_string(replay.get("run_id"), "research replay run_id")
    dataset = freeze_evaluation_dataset_payload(
        output / "journal.sqlite3",
        output / "facts.sqlite3",
        (run_id,),
    )
    _assert_dataset_eligible(dataset)
    _write_json(output / "dataset.json", dataset)

    closed_trade_ids = replay.get("closed_trade_ids")
    if not isinstance(closed_trade_ids, list) or not all(
        isinstance(item, str) and item.strip() for item in closed_trade_ids
    ):
        raise ValueError("research replay closed_trade_ids is invalid")
    summary: dict[str, object] = {
        "checked_out_code_revision": workflow_head,
        "closed_positions": _require_int(
            replay.get("closed_positions"),
            "research replay closed_positions",
        ),
        "closed_trade_count": len(closed_trade_ids),
        "data_complete": True,
        "dataset_manifest_id": _require_string(
            dataset.get("dataset_manifest_id"),
            "research dataset manifest id",
        ),
        "dataset_trade_count": _require_int(
            dataset.get("trade_count"),
            "research dataset trade_count",
        ),
        "economic_claim": "none",
        "evidence_kind": MAINNET_EVIDENCE_KIND,
        "excluded_trade_count": _require_int(
            dataset.get("excluded_trade_count"),
            "research dataset excluded_trade_count",
        ),
        "execution_attempts": _require_int(
            replay.get("execution_attempts"),
            "research replay execution_attempts",
        ),
        "fills": _require_int(replay.get("fills"), "research replay fills"),
        "opened_positions": _require_int(
            replay.get("opened_positions"),
            "research replay opened_positions",
        ),
        "recorded_duplicate_count": _require_int(
            record.get("duplicate_count"),
            "research record duplicate_count",
        ),
        "recorded_event_count": _require_int(
            record.get("event_count"),
            "research record event_count",
        ),
        "recorded_gap_count": _require_int(
            record.get("gap_count"),
            "research record gap_count",
        ),
        "recording_session_id": _require_string(
            record.get("session_id"),
            "research record session_id",
        ),
        "replay_result_digest": _require_string(
            replay.get("result_digest"),
            "research replay result_digest",
        ),
        "replay_run_id": run_id,
        "risk_approvals": _require_int(
            replay.get("risk_approvals"),
            "research replay risk_approvals",
        ),
        "risk_rejections": _require_int(
            replay.get("risk_rejections"),
            "research replay risk_rejections",
        ),
        "selected_markets": list(record["selected_markets"]),
        "strategy_decisions": _require_int(
            replay.get("strategy_decisions"),
            "research replay strategy_decisions",
        ),
        "trigger_head_sha": trigger_head,
        "validated_segment_count": len(segments),
    }
    _write_json(output / "cohort-summary.json", summary)

    verified = verify_mainnet_evidence_cohort_payload(output)
    start_ms = _require_int(verified.get("start_ms"), "verified research cohort start_ms")
    end_ms = _require_int(verified.get("end_ms"), "verified research cohort end_ms")
    if end_ms <= start_ms:
        raise ValueError("verified research cohort interval is invalid")
    return ResearchCohortBuildResult(
        output_root=output,
        replay_run_id=_require_string(verified.get("run_id"), "verified research run_id"),
        start_ms=start_ms,
        end_ms=end_ms,
        dataset_manifest_id=_require_string(
            dataset.get("dataset_manifest_id"),
            "research dataset manifest id",
        ),
    )
