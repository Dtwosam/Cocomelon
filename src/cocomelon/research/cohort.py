from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.evaluation.cli_support import freeze_evaluation_dataset_payload
from cocomelon.evaluation.mainnet_evidence import (
    MAINNET_EVIDENCE_KIND,
    verify_mainnet_evidence_cohort_payload,
)
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.bundle import (
    freeze_baseline_replay_bundle,
    load_baseline_replay_bundle,
    resolve_code_revision,
    write_baseline_replay_bundle,
)
from cocomelon.evidence.contracts import BaselineReplayConfig, FrozenBaselineReplayBundle
from cocomelon.evidence.lifecycle import BaselineReplayPipeline
from cocomelon.evidence.recording import load_recording_session
from cocomelon.evidence.transport_health import normalize_redundant_record_payload
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.journal.store import JournalStore
from cocomelon.replay.adapters import ReplayRequirements
from cocomelon.replay.engine import ReplayEngine, replay_run_id
from cocomelon.replay.source import JsonlReplaySource, validate_recording
from cocomelon.research.strategy_seam import (
    CandidateDecisionEpochEngine,
    build_candidate_strategy_decisions,
    load_candidate_strategy_decisions,
    strategy_context_from_payload,
    strategy_decision_to_payload,
)
from cocomelon.strategies.engine import evaluate_strategies

RESEARCH_ENTRY_WINDOW_MS = 300_000
RESEARCH_MAX_POSITION_AGE_MS = 1_200_000
RESEARCH_CAPTURE_SECONDS = 1_800
RESEARCH_EXECUTION_CONFIG_VERSION = "research-paper-20m-expiry-v1"
RESEARCH_REPLAY_ENGINE_VERSION = "phase9-research-bounded-replay-v1"
RESEARCH_REPLAY_CONFIG_VERSION = "phase9-research-bounded-v1"
_ORDER_FLAG_KEY = "live_" + "order" + "s"

if RESEARCH_ENTRY_WINDOW_MS + RESEARCH_MAX_POSITION_AGE_MS >= RESEARCH_CAPTURE_SECONDS * 1_000:
    raise RuntimeError("research capture must extend past the complete bounded exit horizon")


@dataclass(frozen=True, slots=True)
class ResearchCohortBuildResult:
    output_root: Path
    replay_run_id: str
    start_ms: int
    end_ms: int
    dataset_manifest_id: str


@dataclass(frozen=True, slots=True)
class ResearchCohortSourceResult:
    output_root: Path
    bundle_id: str
    recording_session_digest: str
    source_set_digest: str
    code_revision: str


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


def _require_strings(value: object, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a non-empty string sequence")
    return [str(item) for item in value]


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
    if record.get(_ORDER_FLAG_KEY) is not False:
        raise ValueError("research cohort transport summary must disable order execution")
    if record.get("gap_count") != 0:
        raise ValueError("research cohort transport summary contains a coverage gap")

    session = load_recording_session(recording_root)
    if session is None:
        raise ValueError("research cohort recording session metadata is required")
    if record.get("session_id") != session.session_id:
        raise ValueError("research cohort transport session does not match recording")
    _require_int(record.get("event_count"), "research cohort transport event_count")

    selected = _require_strings(
        record.get("selected_markets"),
        "research cohort transport selected_markets",
    )
    expected_markets = sorted(item.market.canonical for item in session.selected)
    if sorted(selected) != expected_markets:
        raise ValueError("research cohort transport markets do not match recording session")
    record["selected_markets"] = selected
    return record


def _assert_sibling_layout(recording_root: Path, output_root: Path) -> None:
    expected = (output_root.parent / "recording").resolve()
    if recording_root.resolve() != expected:
        raise ValueError(
            "research cohort recording root must be the output root's recording sibling"
        )


def _research_replay_config(starting_cash: Decimal) -> BaselineReplayConfig:
    return BaselineReplayConfig(
        starting_cash=starting_cash,
        execution=PaperExecutionConfig(
            config_version=RESEARCH_EXECUTION_CONFIG_VERSION,
            max_position_age_ms=RESEARCH_MAX_POSITION_AGE_MS,
        ),
        replay_engine_version=RESEARCH_REPLAY_ENGINE_VERSION,
        config_version=RESEARCH_REPLAY_CONFIG_VERSION,
    )


def _attach_recording_locator(
    bundle_path: Path,
    *,
    recording_root: Path,
    bundle_id: str,
) -> None:
    payload = _read_mapping(bundle_path, "replay bundle")
    relative = os.path.relpath(recording_root.resolve(), bundle_path.parent.resolve())
    payload["source_root_relative"] = Path(relative).as_posix()
    payload["source_locator_bundle_id"] = bundle_id
    _write_json(bundle_path, payload)


def _freeze_research_replay_payload(
    recording_root: Path,
    bundle_path: Path,
    starting_cash: Decimal,
) -> dict[str, object]:
    replay_config = _research_replay_config(starting_cash)
    code_revision = resolve_code_revision(None, cwd=Path.cwd())
    bundle = freeze_baseline_replay_bundle(
        recording_root,
        replay_config=replay_config,
        code_revision=code_revision,
    )
    write_baseline_replay_bundle(bundle_path, bundle)
    _attach_recording_locator(
        bundle_path,
        recording_root=recording_root,
        bundle_id=bundle.bundle_id,
    )
    return {
        "bundle_id": bundle.bundle_id,
        "code_revision": bundle.manifest.code_revision,
        "config_version": bundle.replay_config.config_version,
        "entry_window_ms": RESEARCH_ENTRY_WINDOW_MS,
        "evidence_class": bundle.manifest.evidence_class.value,
        _ORDER_FLAG_KEY: False,
        "manifest_id": bundle.manifest.manifest_id,
        "max_position_age_ms": RESEARCH_MAX_POSITION_AGE_MS,
        "network_access": False,
        "out": str(bundle_path),
        "recording_session_digest": bundle.recording_session_digest,
        "replay_engine_version": bundle.replay_config.replay_engine_version,
        "root": str(recording_root),
        "source_set_digest": bundle.source_set_digest,
        "starting_cash": str(bundle.replay_config.starting_cash),
    }


def _validated_bundle_source_root(bundle_path: Path, bundle_id: str) -> Path:
    payload = _read_mapping(bundle_path, "replay bundle")
    locator = _require_string(
        payload.get("source_root_relative"),
        "research replay source locator",
    )
    if payload.get("source_locator_bundle_id") != bundle_id:
        raise ValueError("research replay source locator bundle id does not match bundle")
    source_path = Path(locator)
    if source_path.is_absolute():
        raise ValueError("research replay source locator must be relative")
    return (bundle_path.parent / source_path).resolve()


def _assert_research_bundle_protocol(bundle: FrozenBaselineReplayBundle) -> None:
    replay_config = bundle.replay_config
    if replay_config.replay_engine_version != RESEARCH_REPLAY_ENGINE_VERSION:
        raise ValueError("research replay engine version does not match bounded protocol")
    if replay_config.config_version != RESEARCH_REPLAY_CONFIG_VERSION:
        raise ValueError("research replay config version does not match bounded protocol")
    execution = replay_config.execution
    if (
        execution.config_version != RESEARCH_EXECUTION_CONFIG_VERSION
        or execution.max_position_age_ms != RESEARCH_MAX_POSITION_AGE_MS
    ):
        raise ValueError("research replay execution config does not match bounded protocol")


def prepare_research_cohort_source(
    recording_root: str | Path,
    output_root: str | Path,
    starting_cash: Decimal,
    *,
    trigger_head_sha: str,
) -> ResearchCohortSourceResult:
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

    freeze = _freeze_research_replay_payload(
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
    bundle = load_baseline_replay_bundle(output / "bundle.json")
    return ResearchCohortSourceResult(
        output_root=output,
        bundle_id=bundle.bundle_id,
        recording_session_digest=bundle.recording_session_digest,
        source_set_digest=bundle.source_set_digest,
        code_revision=workflow_head,
    )


def run_baseline_replay_payload(
    bundle_path: str | Path,
    journal_path: str | Path,
    execution_path: str | Path,
    facts_path: str | Path,
    *,
    strategy_decisions_path: str | Path | None = None,
) -> dict[str, object]:
    resolved_bundle_path = Path(bundle_path)
    bundle = load_baseline_replay_bundle(resolved_bundle_path)
    _assert_research_bundle_protocol(bundle)
    source_root = _validated_bundle_source_root(resolved_bundle_path, bundle.bundle_id)
    if validate_recording(source_root) != bundle.manifest.segments:
        raise ValueError("research replay source root does not match frozen manifest")
    session = load_recording_session(source_root)
    if session is None or session.session_id != bundle.recording_session_digest:
        raise ValueError("research replay recording session does not match frozen bundle")
    new_exposure_cutoff_ms = session.started_at_ms + RESEARCH_ENTRY_WINDOW_MS

    requirements = ReplayRequirements(requires_l2=True)
    run_id = replay_run_id(bundle.manifest, requirements)
    journal = JournalStore(journal_path)
    execution = PaperExecutionAdapter(
        execution_path,
        bundle.replay_config.execution,
        starting_cash=bundle.replay_config.starting_cash,
        startup_timestamp_ms=bundle.manifest.start_ms,
    )
    facts = EvaluationFactStore(facts_path)
    try:
        existing = journal.load_replay_result(run_id)
        if existing is None:
            decision_engine = None
            if strategy_decisions_path is not None:
                artifact = load_candidate_strategy_decisions(
                    strategy_decisions_path,
                    bundle_path=resolved_bundle_path,
                )
                decision_engine = CandidateDecisionEpochEngine(
                    tuple(item.market for item in session.selected),
                    replay_config=bundle.replay_config,
                    artifact=artifact,
                )
            pipeline = BaselineReplayPipeline(
                bundle.replay_config,
                execution,
                facts,
                selected_markets=tuple(item.market for item in session.selected),
                replay_run_id=run_id,
                evidence_class=bundle.manifest.evidence_class,
                decision_engine=decision_engine,
                new_exposure_cutoff_ms=new_exposure_cutoff_ms,
            )
            result = ReplayEngine(
                JsonlReplaySource(source_root),
                journal,
                pipeline.replay_pipeline(),
            ).run(bundle.manifest)
        else:
            if existing.manifest_id != bundle.manifest.manifest_id:
                raise ValueError("completed research replay manifest does not match frozen bundle")
            result = existing
        if execution.account.state_id != result.final_account_state_id:
            raise ValueError("research replay final account state did not reconcile")
        decision_count = sum(
            fact.replay_run_id == result.run_id for fact in facts.iter_decision_facts()
        )
        if decision_count != result.strategy_decisions:
            raise ValueError("research replay decision facts do not match journal result")
        return {
            "bundle_id": bundle.bundle_id,
            "closed_positions": result.closed_positions,
            "closed_trade_ids": list(result.closed_trade_ids),
            "config_version": bundle.replay_config.config_version,
            "data_complete": result.data_complete,
            "entry_window_ms": RESEARCH_ENTRY_WINDOW_MS,
            "execution": str(Path(execution_path)),
            "execution_attempts": result.execution_attempts,
            "evidence_class": result.evidence_class.value,
            "facts": str(Path(facts_path)),
            "fills": result.fills,
            "final_account_state_id": result.final_account_state_id,
            "final_equity": str(execution.account.equity),
            "journal": str(Path(journal_path)),
            _ORDER_FLAG_KEY: False,
            "manifest_id": result.manifest_id,
            "max_position_age_ms": RESEARCH_MAX_POSITION_AGE_MS,
            "network_access": False,
            "new_exposure_cutoff_ms": new_exposure_cutoff_ms,
            "opened_positions": result.opened_positions,
            "replay_engine_version": bundle.replay_config.replay_engine_version,
            "result_digest": result.result_digest,
            "risk_approvals": result.risk_approvals,
            "risk_rejections": result.risk_rejections,
            "run_id": result.run_id,
            "strategy_decisions": result.strategy_decisions,
        }
    finally:
        facts.close()
        execution.close()
        journal.close()


def _assert_replay_eligible(replay: dict[str, object]) -> None:
    if replay.get("network_access") is not False:
        raise ValueError("research cohort replay must be offline")
    if replay.get(_ORDER_FLAG_KEY) is not False:
        raise ValueError("research cohort replay must disable order execution")
    if replay.get("data_complete") is not True:
        raise ValueError("research cohort replay must be complete")
    if replay.get("entry_window_ms") != RESEARCH_ENTRY_WINDOW_MS:
        raise ValueError("research cohort replay entry window is not precommitted")
    if replay.get("max_position_age_ms") != RESEARCH_MAX_POSITION_AGE_MS:
        raise ValueError("research cohort replay exit horizon is not precommitted")
    opened = _require_int(replay.get("opened_positions"), "research replay opened_positions")
    closed = _require_int(replay.get("closed_positions"), "research replay closed_positions")
    if opened != closed:
        raise ValueError("research cohort replay must finish flat")


def _assert_dataset_eligible(dataset: dict[str, object]) -> None:
    if dataset.get("network_access") is not False:
        raise ValueError("research cohort dataset freeze must be offline")
    if dataset.get("data_complete") is not True or dataset.get("gap_refs") != []:
        raise ValueError("research cohort dataset must be complete and gap-free")


def _assert_fresh_completion_output(output: Path) -> None:
    for name in (
        "journal.sqlite3",
        "execution.sqlite3",
        "facts.sqlite3",
        "replay.json",
        "dataset.json",
        "cohort-summary.json",
    ):
        if (output / name).exists():
            raise ValueError(f"trusted research completion refuses pre-existing product: {name}")


def complete_research_cohort(
    recording_root: str | Path,
    output_root: str | Path,
    *,
    strategy_decisions_path: str | Path,
) -> ResearchCohortBuildResult:
    recording = Path(recording_root)
    output = Path(output_root)
    _assert_sibling_layout(recording, output)
    _assert_fresh_completion_output(output)
    bundle = load_baseline_replay_bundle(output / "bundle.json")
    if validate_recording(recording) != bundle.manifest.segments:
        raise ValueError("trusted research source changed after preparation")
    load_candidate_strategy_decisions(
        strategy_decisions_path,
        bundle_path=output / "bundle.json",
    )

    replay = run_baseline_replay_payload(
        output / "bundle.json",
        output / "journal.sqlite3",
        output / "execution.sqlite3",
        output / "facts.sqlite3",
        strategy_decisions_path=strategy_decisions_path,
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

    record = _read_mapping(output / "record.json", "record result")
    closed_trade_ids = replay.get("closed_trade_ids")
    if not isinstance(closed_trade_ids, list) or not all(
        isinstance(item, str) and item.strip() for item in closed_trade_ids
    ):
        raise ValueError("research replay closed_trade_ids is invalid")
    summary: dict[str, object] = {
        "checked_out_code_revision": bundle.manifest.code_revision,
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
        "selected_markets": _require_strings(
            record.get("selected_markets"),
            "research record selected_markets",
        ),
        "strategy_decisions": _require_int(
            replay.get("strategy_decisions"),
            "research replay strategy_decisions",
        ),
        "trigger_head_sha": (output / "trigger-head.txt").read_text(encoding="utf-8").strip(),
        "validated_segment_count": len(bundle.manifest.segments),
    }
    _write_json(output / "cohort-summary.json", summary)

    decisions_target = output / "strategy-decisions.json"
    source_decisions = Path(strategy_decisions_path)
    if source_decisions.resolve() != decisions_target.resolve():
        decisions_target.write_bytes(source_decisions.read_bytes())

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


def _local_strategy(payload: dict[str, object]) -> dict[str, object]:
    context = strategy_context_from_payload(payload["context"])
    return strategy_decision_to_payload(evaluate_strategies(context).decision)


def build_research_cohort(
    recording_root: str | Path,
    output_root: str | Path,
    starting_cash: Decimal,
    *,
    trigger_head_sha: str,
) -> ResearchCohortBuildResult:
    recording = Path(recording_root)
    output = Path(output_root)
    source = prepare_research_cohort_source(
        recording,
        output,
        starting_cash,
        trigger_head_sha=trigger_head_sha,
    )
    decisions_path = output / "strategy-decisions.json"
    build_candidate_strategy_decisions(
        recording_root=recording,
        bundle_path=output / "bundle.json",
        output_path=decisions_path,
        candidate_code_revision=source.code_revision,
        evaluator=_local_strategy,
    )
    return complete_research_cohort(
        recording,
        output,
        strategy_decisions_path=decisions_path,
    )
