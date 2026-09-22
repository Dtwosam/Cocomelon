from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.config import ExecutionMode, Settings
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.research.historical_archive_clean_evidence import (
    ArchiveCleanEvidenceStore,
)
from cocomelon.research.historical_archive_clean_observer import (
    ArchiveCleanPublicReader,
    ArchiveCleanSourceCaptureStore,
    load_archive_clean_frozen_runtime,
    run_archive_clean_observer_cycle,
)
from cocomelon.util.time import utc_now_ms


def _emit(payload: dict[str, object], *, stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        file=target,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-archive-clean-observer",
        description=(
            "Run one PAPER-only prospective clean-validation cycle for the "
            "frozen archive candidate"
        ),
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    return parser


def archive_clean_observer_payload(
    settings: Settings,
    *,
    output_root: Path,
    root: Path,
    reader: ArchiveCleanPublicReader | None = None,
    clock_ms: Callable[[], int] = utc_now_ms,
) -> dict[str, object]:
    if settings.execution_mode is not ExecutionMode.PAPER:
        raise ValueError("archive clean observer requires paper execution mode")

    runtime = load_archive_clean_frozen_runtime(output_root)
    spec = runtime.spec
    artifact = runtime.artifact
    evidence_store = ArchiveCleanEvidenceStore(root, spec=spec)
    source_store = ArchiveCleanSourceCaptureStore(root / "sources")
    source = reader or InfoClient(settings)
    result = run_archive_clean_observer_cycle(
        source,
        artifact=artifact,
        spec=spec,
        evidence_store=evidence_store,
        source_store=source_store,
        clock_ms=clock_ms,
    )
    anchors = evidence_store.iter_anchors()
    outcomes = evidence_store.iter_outcomes()
    return {
        "command": "historical-archive-clean-observer",
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "paper_only": True,
        "prospective_only": True,
        "promotion_eligible": False,
        "execution_ready": False,
        "candidate_id": spec.candidate_id,
        "model_artifact_id": spec.model_artifact_id,
        "model_payload_sha256": spec.model_payload_sha256,
        "validation_spec_id": spec.spec_id,
        "campaign_id": evidence_store.manifest.campaign_id,
        "evidence_class": spec.validation_evidence_class,
        "validation_start_ms": spec.validation_start_ms,
        "validation_end_ms": spec.validation_end_ms,
        "finalization_not_before_ms": spec.finalization_not_before_ms,
        "cycle": {
            "status": result.status,
            "cycle_started_ms": result.cycle_started_ms,
            "anchor_end_ms": result.anchor_end_ms,
            "observation_id": result.observation_id,
            "settled_outcome_ids": result.settled_outcome_ids,
            "missing_settlement_signal_ids": (
                result.missing_settlement_signal_ids
            ),
            "capture_coverage": result.capture_coverage,
            "expected_elapsed_anchor_count": (
                result.expected_elapsed_anchor_count
            ),
            "captured_elapsed_anchor_count": (
                result.captured_elapsed_anchor_count
            ),
        },
        "anchor_observation_count": len(anchors),
        "settled_outcome_count": len(outcomes),
        "root": str(root),
        "source_root": str(root / "sources"),
        "output_root": str(output_root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = archive_clean_observer_payload(
            Settings.from_env(),
            output_root=args.output_root,
            root=args.root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
