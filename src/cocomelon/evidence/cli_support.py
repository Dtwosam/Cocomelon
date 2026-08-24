from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from cocomelon.config import ExecutionMode, Settings
from cocomelon.evidence.contracts import EvidenceRecordingConfig

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


def _run_mainnet_evidence(
    settings: Settings,
    root: Path,
    config: EvidenceRecordingConfig,
) -> Mapping[str, object]:
    from dataclasses import asdict

    from cocomelon.evidence.recording import (
        build_recording_bootstrap,
        run_bounded_recording,
    )
    from cocomelon.hyperliquid.client import InfoClient
    from cocomelon.hyperliquid.ws_client import WsConnection, connect_mainnet_ws
    from cocomelon.recorder import DurableRecorder
    from cocomelon.util.time import utc_now_ms

    reader = InfoClient(settings)
    bootstrap = build_recording_bootstrap(
        reader,
        config,
        now_ms=utc_now_ms,
        code_revision=_resolve_git_head(Path.cwd()),
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
