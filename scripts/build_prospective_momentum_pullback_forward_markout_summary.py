from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    DEFAULT_MAX_COMPLETION_LAG_MS,
    DEFAULT_MAX_PATH_AGE_MS,
    ContinuousPaperOpeningOpportunityPathStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_momentum_band_forward_markout import (
    prospective_momentum_pullback_forward_markout_summary,
)
from cocomelon.research.prospective_momentum_pullback_entry import (
    ProspectiveMomentumPullbackEntryState,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-prospective-momentum-pullback-forward-markout-summary",
        description=(
            "Reconstruct the frozen momentum-pullback forward-markout "
            "summary from exact continuous-paper research stores."
        ),
    )
    parser.add_argument("opportunity_root", type=Path)
    parser.add_argument("path_root", type=Path)
    parser.add_argument("feature_root", type=Path)
    parser.add_argument("state_path", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def _require_source(path: Path, *, label: str, directory: bool) -> None:
    exists = path.is_dir() if directory else path.is_file()
    if not exists:
        kind = "directory" if directory else "file"
        raise ValueError(f"{label} {kind} is missing: {path}")


def _load_state(path: Path) -> ProspectiveMomentumPullbackEntryState:
    _require_source(
        path,
        label="momentum-pullback candidate state",
        directory=False,
    )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "momentum-pullback candidate state is invalid"
        ) from exc
    return ProspectiveMomentumPullbackEntryState.from_payload(raw)


def build_summary(
    opportunity_root: Path,
    path_root: Path,
    feature_root: Path,
    state_path: Path,
) -> dict[str, object]:
    for path, label in (
        (opportunity_root, "opening opportunity source"),
        (path_root, "opening opportunity path source"),
        (feature_root, "learning feature source"),
    ):
        _require_source(path, label=label, directory=True)

    state = _load_state(state_path)
    opportunities = ContinuousPaperOpeningOpportunityStore(
        opportunity_root
    )
    paths = ContinuousPaperOpeningOpportunityPathStore(
        path_root,
        max_path_age_ms=DEFAULT_MAX_PATH_AGE_MS,
        max_completion_lag_ms=DEFAULT_MAX_COMPLETION_LAG_MS,
    )
    features = LearningFeatureSnapshotStore(feature_root)
    return prospective_momentum_pullback_forward_markout_summary(
        opportunities.iter_records(),
        paths.iter_paths(),
        features,
        state,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = build_summary(
            args.opportunity_root,
            args.path_root,
            args.feature_root,
            args.state_path,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "candidate_id": summary.get("candidate_id"),
                "started_at_ms": summary.get("started_at_ms"),
                "prospective_opportunities": summary.get(
                    "prospective_opportunities",
                    0,
                ),
                "risk_approved_evaluated": summary.get(
                    "risk_approved_evaluated",
                    0,
                ),
                "integrity_clean": summary.get(
                    "integrity_clean",
                    False,
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
