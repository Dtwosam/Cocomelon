from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.cadence_opportunity_audit import (
    CadenceOpportunityAuditError,
    load_cadence_outcomes,
)
from cocomelon.research.cadence_tree_prospective_baseline import (
    PROSPECTIVE_START_MS,
    evaluate_cadence_tree_prospective_baseline,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("state_path", type=Path)
    parser.add_argument("feature_store_root", type=Path)
    parser.add_argument(
        "--prospective-start-ms",
        type=int,
        default=PROSPECTIVE_START_MS,
    )
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate_cadence_tree_prospective_baseline(
            load_cadence_outcomes(args.state_path),
            LearningFeatureSnapshotStore(args.feature_store_root),
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
        args.json_out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
