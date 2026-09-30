from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.cadence_microstructure_prospective import (
    PROSPECTIVE_START_MS,
    evaluate_cadence_microstructure_prospective,
)
from cocomelon.research.cadence_opportunity_audit import (
    CadenceOpportunityAuditError,
    load_cadence_outcomes,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate-cadence-microstructure-prospective",
        description=(
            "Evaluate the frozen microstructure cadence tree only on "
            "post-freeze settled opportunities."
        ),
    )
    parser.add_argument("state_path", type=Path)
    parser.add_argument("feature_store_root", type=Path)
    parser.add_argument(
        "--prospective-start-ms",
        type=int,
        default=PROSPECTIVE_START_MS,
    )
    parser.add_argument("--json-out", type=Path)
    return parser


def evaluate_state(
    state_path: Path,
    feature_store_root: Path,
    *,
    prospective_start_ms: int,
) -> dict[str, object]:
    outcomes = load_cadence_outcomes(state_path)
    return evaluate_cadence_microstructure_prospective(
        outcomes,
        LearningFeatureSnapshotStore(feature_store_root),
        prospective_start_ms=prospective_start_ms,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = evaluate_state(
            args.state_path,
            args.feature_store_root,
            prospective_start_ms=args.prospective_start_ms,
        )
    except CadenceOpportunityAuditError as exc:
        raise SystemExit(str(exc)) from exc
    encoded = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
