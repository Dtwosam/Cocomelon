from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cocomelon.evaluation.mainnet_evidence import (
    ATTESTATION_NAME,
    MAINNET_EVIDENCE_KIND,
    aggregate_mainnet_evaluation_evidence,
    freeze_mainnet_evaluation_dataset_payload,
    mainnet_evidence_progress_payload,
    verify_mainnet_evidence_cohort_payload,
)


def _attestation_metadata(journal_path: str | Path) -> tuple[str, int]:
    path = Path(journal_path).parent / ATTESTATION_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("mainnet evidence attestation is unreadable") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("mainnet evidence attestation must be an object")
    attestation_id = raw.get("attestation_id")
    source_count = raw.get("source_count")
    if (
        not isinstance(attestation_id, str)
        or len(attestation_id) != 64
        or any(char not in "0123456789abcdef" for char in attestation_id.lower())
    ):
        raise RuntimeError("mainnet evidence attestation id is invalid")
    if isinstance(source_count, bool) or not isinstance(source_count, int) or source_count <= 0:
        raise RuntimeError("mainnet evidence attestation source count is invalid")
    return attestation_id, source_count


def aggregate_payload(
    journal_path: str | Path,
    facts_path: str | Path,
    source_roots: Sequence[str | Path],
) -> dict[str, object]:
    result = aggregate_mainnet_evaluation_evidence(
        journal_path,
        facts_path,
        source_roots,
    )
    attestation_id, source_count = _attestation_metadata(journal_path)
    return {
        "code_revision": result.code_revision,
        "run_ids": list(result.run_ids),
        "source_count": source_count,
        "trade_count": result.trade_count,
        "observation_count": result.observation_count,
        "decision_fact_count": result.decision_fact_count,
        "equity_fact_count": result.equity_fact_count,
        "journal": str(Path(journal_path)),
        "facts": str(Path(facts_path)),
        "mainnet_attestation_id": attestation_id,
        "evidence_kind": MAINNET_EVIDENCE_KIND,
        "economic_claim": "none",
        "real_evidence_eligible": True,
        "network_access": False,
        "live_orders": False,
    }


def freeze_dataset_payload(
    journal_path: str | Path,
    facts_path: str | Path,
    replay_run_ids: tuple[str, ...],
) -> dict[str, object]:
    return freeze_mainnet_evaluation_dataset_payload(
        journal_path,
        facts_path,
        replay_run_ids,
    )


def verify_payload(source_root: str | Path) -> dict[str, object]:
    return verify_mainnet_evidence_cohort_payload(source_root)


def progress_payload(
    journal_path: str | Path,
    facts_path: str | Path,
) -> dict[str, object]:
    return mainnet_evidence_progress_payload(journal_path, facts_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon-mainnet-evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--source-root", required=True, type=Path)

    progress = subparsers.add_parser("progress")
    progress.add_argument("--journal", required=True, type=Path)
    progress.add_argument("--facts", required=True, type=Path)

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--journal", required=True, type=Path)
    aggregate.add_argument("--facts", required=True, type=Path)
    aggregate.add_argument("--source-root", required=True, action="append", type=Path)

    freeze_dataset = subparsers.add_parser("freeze-dataset")
    freeze_dataset.add_argument("--journal", required=True, type=Path)
    freeze_dataset.add_argument("--facts", required=True, type=Path)
    freeze_dataset.add_argument("--run-id", required=True, action="append")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    payload: dict[str, Any]
    if args.command == "verify":
        payload = verify_payload(args.source_root)
    elif args.command == "progress":
        payload = progress_payload(args.journal, args.facts)
    elif args.command == "aggregate":
        payload = aggregate_payload(
            args.journal,
            args.facts,
            tuple(args.source_root),
        )
    else:
        payload = freeze_dataset_payload(
            args.journal,
            args.facts,
            tuple(args.run_id),
        )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
