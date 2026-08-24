from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path

from cocomelon.config import ExecutionMode, Settings
from cocomelon.evidence.bundle import (
    freeze_baseline_replay_bundle,
    resolve_code_revision,
    write_baseline_replay_bundle,
)
from cocomelon.evidence.contracts import BaselineReplayConfig, EvidenceRecordingConfig
from cocomelon.evidence.recording import (
    EvidenceInfoReader,
    RecordingBootstrap,
    build_recording_bootstrap,
    load_recording_session,
)
from cocomelon.evidence.resume import build_recording_resume_bootstrap

RecordCommandRunner = Callable[
    [Settings, Path, EvidenceRecordingConfig],
    Mapping[str, object],
]


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


def _run_mainnet_evidence(
    settings: Settings,
    root: Path,
    config: EvidenceRecordingConfig,
) -> Mapping[str, object]:
    from dataclasses import asdict

    from cocomelon.evidence.recording import run_bounded_recording
    from cocomelon.hyperliquid.client import InfoClient
    from cocomelon.hyperliquid.ws_client import WsConnection, connect_mainnet_ws
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

    async def connection_factory() -> WsConnection:
        return await connect_mainnet_ws(settings)

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
