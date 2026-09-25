from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_clean_evidence import (
    LearningCleanEvidenceStore,
    parse_learning_clean_outcome_payload,
    parse_learning_clean_prediction_payload,
)
from cocomelon.research.learning_clean_validation_spec import (
    verify_learning_clean_validation_spec,
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


def _json_value(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("input JSON must be a readable JSON value") from exc


def _add_store_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--validation-spec", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-learning-clean-evidence",
        description=(
            "Append or verify spec-bound clean paper evidence for one frozen "
            "learning candidate"
        ),
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    prediction = subparsers.add_parser("record-prediction")
    _add_store_args(prediction)
    prediction.add_argument("--input-json", required=True, type=Path)

    outcome = subparsers.add_parser("record-outcome")
    _add_store_args(outcome)
    outcome.add_argument("--input-json", required=True, type=Path)

    verify = subparsers.add_parser("verify")
    _add_store_args(verify)
    return parser


def _store(args: argparse.Namespace) -> LearningCleanEvidenceStore:
    spec = verify_learning_clean_validation_spec(
        args.validation_spec,
        package_root=args.package_root,
    )
    return LearningCleanEvidenceStore(args.evidence_root, spec=spec)


def _summary(
    store: LearningCleanEvidenceStore,
    *,
    action: str,
    path: Path | None = None,
    receipt_id: str | None = None,
) -> dict[str, object]:
    store.verify()
    predictions = store.iter_predictions()
    outcomes = store.iter_outcomes()
    payload: dict[str, object] = {
        "command": "learning-clean-evidence",
        "action": action,
        "candidate_id": store.spec.candidate_id,
        "validation_spec_id": store.spec.spec_id,
        "candidate_package_id": store.spec.candidate_package_id,
        "prediction_count": len(predictions),
        "settled_outcome_count": len(outcomes),
        "unsettled_trade_prediction_count": len(
            store.unsettled_trade_prediction_ids
        ),
        "clean_evidence_state_digest": store.state_digest,
        "paper_only": True,
        "prospective_only": True,
        "research_only": True,
        "promotion_eligible": False,
        "execution_ready": False,
    }
    if path is not None:
        payload["path"] = str(path)
    if receipt_id is not None:
        payload["receipt_id"] = receipt_id
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = _store(args)
        if args.action == "record-prediction":
            prediction = parse_learning_clean_prediction_payload(
                _json_value(args.input_json)
            )
            path = store.record_prediction(prediction)
            payload = _summary(
                store,
                action=args.action,
                path=path,
                receipt_id=prediction.prediction_id,
            )
        elif args.action == "record-outcome":
            outcome = parse_learning_clean_outcome_payload(
                _json_value(args.input_json)
            )
            path = store.record_outcome(outcome)
            payload = _summary(
                store,
                action=args.action,
                path=path,
                receipt_id=outcome.outcome_id,
            )
        else:
            payload = _summary(store, action=args.action)
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
