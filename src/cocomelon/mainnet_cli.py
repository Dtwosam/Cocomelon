from __future__ import annotations

import argparse
import json
import os
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
from cocomelon.evaluation.mainnet_phase9 import (
    evaluate_phase9_v2_snapshot,
    prepare_phase9_v2_snapshot,
)
from cocomelon.evaluation.mainnet_phase9_v3 import (
    evaluate_phase9_v3_snapshot,
    prepare_phase9_v3_snapshot,
)
from cocomelon.evaluation.mainnet_phase9_v4 import (
    evaluate_phase9_v4_snapshot,
    prepare_phase9_v4_snapshot,
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


def _workflow_run_head_sha_from_event() -> str | None:
    raw_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if not raw_path:
        return None
    try:
        payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("GitHub event payload is unreadable") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub event payload must be an object")
    workflow_run = payload.get("workflow_run")
    if workflow_run is None:
        return None
    if not isinstance(workflow_run, dict):
        raise RuntimeError("GitHub workflow_run event payload is invalid")
    head_sha = workflow_run.get("head_sha")
    if (
        not isinstance(head_sha, str)
        or len(head_sha) != 40
        or any(char not in "0123456789abcdef" for char in head_sha)
    ):
        raise RuntimeError("GitHub workflow_run head sha is invalid")
    return head_sha


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
    payload = verify_mainnet_evidence_cohort_payload(source_root)
    authoritative_head = _workflow_run_head_sha_from_event()
    if authoritative_head is not None and payload.get("trigger_head_sha") != authoritative_head:
        raise RuntimeError(
            "mainnet evidence trigger head does not match authoritative workflow run head"
        )
    return payload


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

    prepare_phase9_v2 = subparsers.add_parser("prepare-phase9-v2")
    prepare_phase9_v2.add_argument("--corpus-root", required=True, type=Path)
    prepare_phase9_v2.add_argument("--out-root", required=True, type=Path)

    evaluate_phase9_v2 = subparsers.add_parser("evaluate-phase9-v2")
    evaluate_phase9_v2.add_argument("--snapshot-root", required=True, type=Path)

    prepare_phase9_v3 = subparsers.add_parser("prepare-phase9-v3")
    prepare_phase9_v3.add_argument("--corpus-root", required=True, type=Path)
    prepare_phase9_v3.add_argument("--out-root", required=True, type=Path)

    evaluate_phase9_v3 = subparsers.add_parser("evaluate-phase9-v3")
    evaluate_phase9_v3.add_argument("--snapshot-root", required=True, type=Path)

    prepare_phase9_v4 = subparsers.add_parser("prepare-phase9-v4")
    prepare_phase9_v4.add_argument("--corpus-root", required=True, type=Path)
    prepare_phase9_v4.add_argument("--out-root", required=True, type=Path)

    evaluate_phase9_v4 = subparsers.add_parser("evaluate-phase9-v4")
    evaluate_phase9_v4.add_argument("--snapshot-root", required=True, type=Path)
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
    elif args.command == "freeze-dataset":
        payload = freeze_dataset_payload(
            args.journal,
            args.facts,
            tuple(args.run_id),
        )
    elif args.command == "prepare-phase9-v2":
        payload = prepare_phase9_v2_snapshot(args.corpus_root, args.out_root)
    elif args.command == "evaluate-phase9-v2":
        payload = evaluate_phase9_v2_snapshot(args.snapshot_root)
    elif args.command == "prepare-phase9-v3":
        payload = prepare_phase9_v3_snapshot(args.corpus_root, args.out_root)
    elif args.command == "evaluate-phase9-v3":
        payload = evaluate_phase9_v3_snapshot(args.snapshot_root)
    elif args.command == "prepare-phase9-v4":
        payload = prepare_phase9_v4_snapshot(args.corpus_root, args.out_root)
    elif args.command == "evaluate-phase9-v4":
        payload = evaluate_phase9_v4_snapshot(args.snapshot_root)
    else:
        raise RuntimeError(f"unsupported mainnet evidence command: {args.command}")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
