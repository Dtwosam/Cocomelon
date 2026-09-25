from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_shadow_evidence import (
    LearningShadowEvidenceStore,
    learning_shadow_execution_from_payload,
    open_verified_learning_shadow_evidence_store,
)


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


def _add_lineage_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--shadow-admission", required=True, type=Path)
    parser.add_argument("--review-decision", required=True, type=Path)
    parser.add_argument("--review-dossier", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--validation-spec", required=True, type=Path)
    parser.add_argument("--validation-score", required=True, type=Path)
    parser.add_argument("--finalization", required=True, type=Path)
    parser.add_argument("--clean-evidence-root", required=True, type=Path)
    parser.add_argument("--shadow-evidence-root", required=True, type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-learning-shadow-evidence",
        description=(
            "Append or verify post-review cost-complete paper executions for "
            "one admitted learned shadow candidate"
        ),
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    record = subparsers.add_parser("record-execution")
    _add_lineage_args(record)
    record.add_argument("--record-json", required=True, type=Path)

    verify = subparsers.add_parser("verify")
    _add_lineage_args(verify)
    return parser


def _store(args: argparse.Namespace) -> LearningShadowEvidenceStore:
    return open_verified_learning_shadow_evidence_store(
        args.shadow_evidence_root,
        shadow_admission_path=args.shadow_admission,
        review_decision_path=args.review_decision,
        review_dossier_path=args.review_dossier,
        package_root=args.package_root,
        validation_spec_path=args.validation_spec,
        validation_score_path=args.validation_score,
        finalization_path=args.finalization,
        clean_evidence_root=args.clean_evidence_root,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = _store(args)
        created: bool | None = None
        if args.action == "record-execution":
            raw = json.loads(args.record_json.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not all(
                isinstance(key, str) for key in raw
            ):
                raise ValueError("shadow execution payload must be a JSON object")
            record = learning_shadow_execution_from_payload(raw)
            created = store.record_execution(record)
        store.verify()
        records = store.iter_records()
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    payload: dict[str, object] = {
        "command": "learning-shadow-evidence",
        "action": args.action,
        "shadow_admission_id": store.admission.shadow_admission_id,
        "candidate_id": store.admission.candidate_id,
        "closed_paper_trade_count": len(records),
        "shadow_evidence_state_digest": store.state_digest,
        "minimum_closed_mainnet_paper_trades": (
            store.admission.minimum_closed_mainnet_paper_trades
        ),
        "paper_only": True,
        "research_only": True,
        "promotion_eligible": False,
        "execution_ready": False,
        "live_promotion_authorized": False,
    }
    if created is not None:
        payload["created"] = created
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
