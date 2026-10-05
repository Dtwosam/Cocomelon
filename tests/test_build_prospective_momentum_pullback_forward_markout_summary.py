from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research.prospective_momentum_pullback_entry import (
    ProspectiveMomentumPullbackEntryState,
)
from scripts import (
    build_prospective_momentum_pullback_forward_markout_summary as builder,
)


def test_build_summary_wires_exact_research_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opportunity_root = tmp_path / "opening-opportunities"
    path_root = tmp_path / "opening-opportunity-paths"
    feature_root = tmp_path / "learning-features"
    for path in (opportunity_root, path_root, feature_root):
        path.mkdir()

    state = ProspectiveMomentumPullbackEntryState(
        frozen_at_ms=1_000,
    )
    state_path = tmp_path / "pullback-state.json"
    state_path.write_text(
        json.dumps(state.payload()),
        encoding="utf-8",
    )

    observed: dict[str, object] = {}

    class OpportunityStore:
        def __init__(self, root: Path) -> None:
            observed["opportunity_root"] = root

        def iter_records(self) -> tuple[str, ...]:
            return ("opportunity",)

    class PathStore:
        def __init__(
            self,
            root: Path,
            *,
            max_path_age_ms: int,
            max_completion_lag_ms: int,
        ) -> None:
            observed["path_root"] = root
            observed["max_path_age_ms"] = max_path_age_ms
            observed["max_completion_lag_ms"] = max_completion_lag_ms

        def iter_paths(self) -> tuple[str, ...]:
            return ("path",)

    class FeatureStore:
        def __init__(self, root: Path) -> None:
            observed["feature_root"] = root

    def fake_summary(
        opportunities: object,
        paths: object,
        features: object,
        candidate: ProspectiveMomentumPullbackEntryState,
    ) -> dict[str, object]:
        observed["opportunities"] = tuple(opportunities)  # type: ignore[arg-type]
        observed["paths"] = tuple(paths)  # type: ignore[arg-type]
        observed["features"] = features
        observed["candidate"] = candidate
        return {
            "candidate_id": candidate.candidate_id,
            "started_at_ms": candidate.started_at_ms,
            "risk_approved_evaluated": 2,
            "integrity_clean": True,
        }

    monkeypatch.setattr(
        builder,
        "ContinuousPaperOpeningOpportunityStore",
        OpportunityStore,
    )
    monkeypatch.setattr(
        builder,
        "ContinuousPaperOpeningOpportunityPathStore",
        PathStore,
    )
    monkeypatch.setattr(
        builder,
        "LearningFeatureSnapshotStore",
        FeatureStore,
    )
    monkeypatch.setattr(
        builder,
        "prospective_momentum_pullback_forward_markout_summary",
        fake_summary,
    )

    result = builder.build_summary(
        opportunity_root,
        path_root,
        feature_root,
        state_path,
    )

    assert result["candidate_id"] == state.candidate_id
    assert observed["opportunity_root"] == opportunity_root
    assert observed["path_root"] == path_root
    assert observed["feature_root"] == feature_root
    assert observed["opportunities"] == ("opportunity",)
    assert observed["paths"] == ("path",)
    assert observed["candidate"] == state
    assert (
        observed["max_path_age_ms"]
        == builder.DEFAULT_MAX_PATH_AGE_MS
    )
    assert (
        observed["max_completion_lag_ms"]
        == builder.DEFAULT_MAX_COMPLETION_LAG_MS
    )


def test_build_summary_fails_closed_when_raw_source_is_missing(
    tmp_path: Path,
) -> None:
    state = ProspectiveMomentumPullbackEntryState(
        frozen_at_ms=1_000,
    )
    state_path = tmp_path / "pullback-state.json"
    state_path.write_text(
        json.dumps(state.payload()),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="opening opportunity source directory is missing",
    ):
        builder.build_summary(
            tmp_path / "missing-opportunities",
            tmp_path / "missing-paths",
            tmp_path / "missing-features",
            state_path,
        )


def test_summary_cli_writes_deterministic_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opportunity_root = tmp_path / "opening-opportunities"
    path_root = tmp_path / "opening-opportunity-paths"
    feature_root = tmp_path / "learning-features"
    state_path = tmp_path / "pullback-state.json"
    output = tmp_path / "summary.json"

    expected = {
        "candidate_id": "candidate",
        "integrity_clean": True,
        "risk_approved_evaluated": 3,
        "started_at_ms": 123,
    }
    monkeypatch.setattr(
        builder,
        "build_summary",
        lambda *_args: expected,
    )

    assert (
        builder.main(
            [
                str(opportunity_root),
                str(path_root),
                str(feature_root),
                str(state_path),
                "--json-out",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8")) == expected
