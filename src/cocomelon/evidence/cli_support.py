from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import time
from collections.abc import Awaitable, Callable, Mapping
from decimal import Decimal
from pathlib import Path

from cocomelon.config import ExecutionMode, Settings
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.bundle import (
    freeze_baseline_replay_bundle,
    load_baseline_replay_bundle,
    resolve_code_revision,
    write_baseline_replay_bundle,
)
from cocomelon.evidence.contracts import BaselineReplayConfig, EvidenceRecordingConfig
from cocomelon.evidence.lifecycle import BaselineReplayPipeline
from cocomelon.evidence.recording import (
    EvidenceInfoReader,
    RecordingBootstrap,
    build_recording_bootstrap,
    load_recording_session,
)
from cocomelon.evidence.resume import build_recording_resume_bootstrap
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.hyperliquid.ws_client import WsConnection, connect_mainnet_ws
from cocomelon.journal.store import JournalStore
from cocomelon.replay.adapters import ReplayRequirements
from cocomelon.replay.engine import ReplayEngine, replay_run_id
from cocomelon.replay.source import JsonlReplaySource, validate_recording

RecordCommandRunner = Callable[
    [Settings, Path, EvidenceRecordingConfig],
    Mapping[str, object],
]
WsConnector = Callable[[Settings], Awaitable[WsConnection]]
AsyncSleep = Callable[[float], Awaitable[None]]
SOURCE_ROOT_FIELD = "source_root_relative"
SOURCE_LOCATOR_BUNDLE_ID_FIELD = "source_locator_bundle_id"
WS_CONNECT_SPACING_ENV = "COCOMELON_WS_CONNECT_SPACING_SECONDS"


def _resolve_git_head(cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise RuntimeError("unable to resolve recorder code revision") from exc
    revision = completed.stdout.strip()
    if completed.returncode != 0 or not revision:
        raise RuntimeError("unable to resolve recorder code revision")
    return revision


def _recording_bootstrap_for_root(
    reader: EvidenceInfoReader,
    root: Path,
    config: EvidenceRecordingConfig,
    *,
    now_ms: Callable[[], int],
    code_revision: str,
) -> RecordingBootstrap:
    existing = load_recording_session(root)
    if existing is not None:
        if existing.recorder_code_revision != code_revision:
            raise ValueError("recording session code revision does not match current revision")
        return build_recording_resume_bootstrap(
            reader,
            config,
            existing,
            now_ms=now_ms,
        )
    if root.exists() and any(root.iterdir()):
        raise ValueError("recording session metadata missing for populated root")
    return build_recording_bootstrap(
        reader,
        config,
        now_ms=now_ms,
        code_revision=code_revision,
    )


def _ws_connect_spacing_seconds(environ: Mapping[str, str] | None = None) -> float:
    source = os.environ if environ is None else environ
    raw = source.get(WS_CONNECT_SPACING_ENV, "0").strip()
    try:
        spacing = float(raw)
    except ValueError as exc:
        raise ValueError("websocket connect spacing must be a finite non-negative number") from exc
    if not math.isfinite(spacing) or spacing < 0:
        raise ValueError("websocket connect spacing must be a finite non-negative number")
    return spacing


def _build_spaced_mainnet_connection_factory(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
    connect: WsConnector = connect_mainnet_ws,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: AsyncSleep = asyncio.sleep,
) -> Callable[[], Awaitable[WsConnection]]:
    spacing = _ws_connect_spacing_seconds(environ)
    if spacing == 0:
        async def direct_connection_factory() -> WsConnection:
            return await connect(settings)

        return direct_connection_factory

    lock = asyncio.Lock()
    last_start: float | None = None

    async def spaced_connection_factory() -> WsConnection:
        nonlocal last_start
        async with lock:
            now = monotonic()
            if last_start is not None:
                delay = last_start + spacing - now
                if delay > 0:
                    await sleep(delay)
            last_start = monotonic()
            return await connect(settings)

    return spaced_connection_factory


def _run_mainnet_evidence(
    settings: Settings,
    root: Path,
    config: EvidenceRecordingConfig,
) -> Mapping[str, object]:
    from dataclasses import asdict

    from cocomelon.evidence.recording import run_bounded_recording
    from cocomelon.hyperliquid.client import InfoClient
    from cocomelon.recorder import DurableRecorder
    from cocomelon.util.time import utc_now_ms

    code_revision = _resolve_git_head(Path.cwd())
    reader = InfoClient(settings)
    bootstrap = _recording_bootstrap_for_root(
        reader,
        root,
        config,
        now_ms=utc_now_ms,
        code_revision=code_revision,
    )
    recorder = DurableRecorder(
        root,
        max_records=config.max_records,
        max_bytes=config.max_bytes,
    )
    connection_factory = _build_spaced_mainnet_connection_factory(settings)

    summary = asyncio.run(
        run_bounded_recording(
            bootstrap=bootstrap,
            reader=reader,
            connection_factory=connection_factory,
            recorder=recorder,
            config=config,
        )
    )
    return asdict(summary)


def record_mainnet_evidence_payload(
    settings: Settings,
    *,
    root: str | Path,
    seconds: int,
    deep_limit: int,
    runner: RecordCommandRunner = _run_mainnet_evidence,
) -> dict[str, object]:
    if settings.execution_mode is not ExecutionMode.PAPER:
        raise ValueError("record-mainnet-evidence is available only in paper mode")
    config = EvidenceRecordingConfig(
        duration_seconds=seconds,
        deep_limit=deep_limit,
        api_url=settings.api_url,
        ws_url=settings.ws_url,
    )
    result = dict(runner(settings, Path(root), config))
    if result.get("live_orders") is not False:
        raise ValueError("evidence recording runner must remain live_orders=false")
    if result.get("network_access") is not True:
        raise ValueError("evidence recording runner must declare public network access")
    return result


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _attach_source_locator(
    bundle_path: Path,
    recording_root: Path,
    *,
    bundle_id: str,
) -> None:
    try:
        raw = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("written baseline replay bundle is unreadable") from exc
    if not isinstance(raw, dict):
        raise ValueError("written baseline replay bundle must be an object")
    relative = os.path.relpath(recording_root.resolve(), bundle_path.parent.resolve())
    raw[SOURCE_ROOT_FIELD] = Path(relative).as_posix()
    raw[SOURCE_LOCATOR_BUNDLE_ID_FIELD] = bundle_id
    encoded = _canonical_json_bytes(raw)
    temporary = bundle_path.with_name(f".{bundle_path.name}.locator.tmp")
    with temporary.open("wb") as handle:
        written = handle.write(encoded)
        if written != len(encoded):
            raise OSError(f"short replay bundle locator write: {written} of {len(encoded)} bytes")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, bundle_path)


def freeze_baseline_replay_payload(
    root: str | Path,
    out: str | Path,
    starting_cash: Decimal,
) -> dict[str, object]:
    recording_root = Path(root)
    output_path = Path(out)
    replay_config = BaselineReplayConfig(starting_cash=starting_cash)
    code_revision = resolve_code_revision(None, cwd=Path.cwd())
    bundle = freeze_baseline_replay_bundle(
        recording_root,
        replay_config=replay_config,
        code_revision=code_revision,
    )
    write_baseline_replay_bundle(output_path, bundle)
    _attach_source_locator(output_path, recording_root, bundle_id=bundle.bundle_id)
    return {
        "bundle_id": bundle.bundle_id,
        "manifest_id": bundle.manifest.manifest_id,
        "evidence_class": bundle.manifest.evidence_class.value,
        "recording_session_digest": bundle.recording_session_digest,
        "source_set_digest": bundle.source_set_digest,
        "code_revision": bundle.manifest.code_revision,
        "starting_cash": str(bundle.replay_config.starting_cash),
        "root": str(recording_root),
        "out": str(output_path),
        "network_access": False,
        "live_orders": False,
    }


def _bundle_source_root(bundle_path: Path, bundle_id: str) -> Path:
    try:
        raw = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("baseline replay bundle must contain valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("baseline replay bundle must be an object")

    locator = raw.get(SOURCE_ROOT_FIELD)
    locator_bundle_id = raw.get(SOURCE_LOCATOR_BUNDLE_ID_FIELD)
    if locator is None:
        candidate = bundle_path.parent.resolve()
    else:
        if not isinstance(locator, str) or not locator.strip():
            raise ValueError("baseline replay source locator must be a non-empty string")
        if locator_bundle_id != bundle_id:
            raise ValueError("baseline replay source locator bundle id does not match bundle")
        source_path = Path(locator)
        if source_path.is_absolute():
            raise ValueError("baseline replay source locator must be relative")
        candidate = (bundle_path.parent / source_path).resolve()
    return candidate


def _validated_bundle_source_root(
    bundle_path: Path,
    bundle_id: str,
    manifest_segments: object,
) -> Path:
    source_root = _bundle_source_root(bundle_path, bundle_id)
    actual_segments = validate_recording(source_root)
    if actual_segments != manifest_segments:
        raise ValueError("baseline replay source root does not match frozen manifest")
    return source_root


def _completed_replay_is_consistent(
    result_run_id: str,
    strategy_decisions: int,
    final_account_state_id: str,
    *,
    execution: PaperExecutionAdapter,
    facts: EvaluationFactStore,
) -> None:
    if execution.account.state_id != final_account_state_id:
        raise ValueError("completed replay execution state does not match journal result")
    decision_count = sum(
        fact.replay_run_id == result_run_id
        for fact in facts.iter_decision_facts()
    )
    if decision_count != strategy_decisions:
        raise ValueError("completed replay decision facts do not match journal result")


def run_baseline_replay_payload(
    bundle_path: str | Path,
    journal_path: str | Path,
    execution_path: str | Path,
    facts_path: str | Path,
) -> dict[str, object]:
    resolved_bundle_path = Path(bundle_path)
    bundle = load_baseline_replay_bundle(resolved_bundle_path)
    source_root = _validated_bundle_source_root(
        resolved_bundle_path,
        bundle.bundle_id,
        bundle.manifest.segments,
    )
    session = load_recording_session(source_root)
    if session is None or session.session_id != bundle.recording_session_digest:
        raise ValueError("baseline replay recording session does not match frozen bundle")

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
        if existing is not None:
            if existing.manifest_id != bundle.manifest.manifest_id:
                raise ValueError("completed replay manifest does not match frozen bundle")
            _completed_replay_is_consistent(
                existing.run_id,
                existing.strategy_decisions,
                existing.final_account_state_id,
                execution=execution,
                facts=facts,
            )
            result = existing
        else:
            pipeline = BaselineReplayPipeline(
                bundle.replay_config,
                execution,
                facts,
                selected_markets=tuple(item.market for item in session.selected),
                replay_run_id=run_id,
                evidence_class=bundle.manifest.evidence_class,
            )
            result = ReplayEngine(
                JsonlReplaySource(source_root),
                journal,
                pipeline.replay_pipeline(),
            ).run(bundle.manifest)
            if execution.account.state_id != result.final_account_state_id:
                raise ValueError("baseline replay final account state did not reconcile")

        return {
            "bundle_id": bundle.bundle_id,
            "manifest_id": result.manifest_id,
            "run_id": result.run_id,
            "result_digest": result.result_digest,
            "evidence_class": result.evidence_class.value,
            "strategy_decisions": result.strategy_decisions,
            "risk_approvals": result.risk_approvals,
            "risk_rejections": result.risk_rejections,
            "execution_attempts": result.execution_attempts,
            "fills": result.fills,
            "opened_positions": result.opened_positions,
            "closed_positions": result.closed_positions,
            "closed_trade_ids": list(result.closed_trade_ids),
            "final_account_state_id": result.final_account_state_id,
            "final_equity": str(execution.account.equity),
            "data_complete": result.data_complete,
            "journal": str(Path(journal_path)),
            "execution": str(Path(execution_path)),
            "facts": str(Path(facts_path)),
            "network_access": False,
            "live_orders": False,
        }
    finally:
        facts.close()
        execution.close()
        journal.close()
