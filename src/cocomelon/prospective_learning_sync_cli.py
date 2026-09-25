from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.outcome_learning import (
    LearningEvidenceLedger,
    sync_prospective_learning_evidence,
)
from cocomelon.research.prospective_context_evidence import ProspectiveEvidenceStore
from cocomelon.research.prospective_hype_campaign import resolve_prospective_hype_campaign


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
        prog="cocomelon-prospective-learning-sync",
        description=(
            "Copy settled prospective HYPE outcomes into the append-only learning ledger "
            "without making them research-eligible before campaign finalization"
        ),
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--learning-root", required=True, type=Path)
    parser.add_argument("--campaign", choices=("v1", "v2", "v3"), default="v3")
    return parser


def prospective_learning_sync_payload(
    *,
    source_root: Path,
    learning_root: Path,
    campaign: str = "v3",
) -> dict[str, object]:
    resolved = resolve_prospective_hype_campaign(campaign)
    source = ProspectiveEvidenceStore(source_root, spec=resolved.spec)
    ledger = LearningEvidenceLedger(learning_root)
    result = sync_prospective_learning_evidence(
        source,
        ledger,
        spec=resolved.spec,
        plan=resolved.plan,
    )
    records = ledger.iter_records()
    return {
        "command": "prospective-learning-sync",
        "campaign_version": resolved.version,
        "campaign_id": source.manifest.campaign_id,
        "candidate_id": resolved.spec.candidate_id,
        "candidate_spec_id": resolved.spec.spec_id,
        "research_eligible_at_ms": resolved.plan.finalization_not_before_ms,
        "scanned_outcomes": result.scanned_outcomes,
        "created_records": result.created_records,
        "existing_records": result.existing_records,
        "learning_record_count": len(records),
        "learning_state_digest": ledger.state_digest,
        "source_root": str(source_root),
        "learning_root": str(learning_root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = prospective_learning_sync_payload(
            source_root=args.source_root,
            learning_root=args.learning_root,
            campaign=args.campaign,
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
