from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research import deferred_full_stack_forward_markout as deferred
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterState,
)


def _write_state_files(root: Path, *, exit_reason: str) -> None:
    (root / "session-summary.json").write_text(
        json.dumps({"exit_reason": exit_reason}),
        encoding="utf-8",
    )
    (root / deferred.COMBINED_STATE_FILENAME).write_text(
        json.dumps(
            ProspectiveCombinedEntryFilterState(
                started_at_ms=1_000,
            ).payload()
        ),
        encoding="utf-8",
    )
    (root / deferred.TWO_STRIKE_STATE_FILENAME).write_text(
        json.dumps(
            ProspectiveTwoStrikeStopFilterState(
                frozen_at_ms=2_000,
            ).payload()
        ),
        encoding="utf-8",
    )
    (root / deferred.MOMENTUM_STATE_FILENAME).write_text(
        json.dumps(
            ProspectiveMomentumBandEntryState(
                frozen_at_ms=3_000,
            ).payload()
        ),
        encoding="utf-8",
    )


def test_deferred_full_stack_markout_rebuild_is_read_only_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_state_files(tmp_path, exit_reason="upgrade_requested")
    roots: dict[str, Path] = {}
    journal_closed = False

    class OpportunityStore:
        def __init__(self, root: Path) -> None:
            roots["opportunities"] = root

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
            roots["paths"] = root
            assert max_path_age_ms == deferred.DEFAULT_MAX_PATH_AGE_MS
            assert (
                max_completion_lag_ms
                == deferred.DEFAULT_MAX_COMPLETION_LAG_MS
            )

        def iter_paths(self) -> tuple[str, ...]:
            return ("path",)

    class FeatureStore:
        def __init__(self, root: Path) -> None:
            roots["features"] = root

    class LineageStore:
        def __init__(self, root: Path) -> None:
            roots["lineages"] = root

        def iter_records(self) -> tuple[str, ...]:
            return ("lineage",)

    class Journal:
        def __init__(self, path: Path) -> None:
            roots["journal"] = path

        def iter_trades(self) -> tuple[str, ...]:
            return ("trade",)

        def close(self) -> None:
            nonlocal journal_closed
            journal_closed = True

    def summary(
        opportunities: object,
        paths: object,
        trades: object,
        feature_store: object,
        combined_state: object,
        two_strike_state: object,
        momentum_state: object,
    ) -> dict[str, object]:
        assert opportunities == ("opportunity",)
        assert paths == ("path",)
        assert trades == ("trade",)
        assert isinstance(feature_store, FeatureStore)
        assert isinstance(
            combined_state,
            ProspectiveCombinedEntryFilterState,
        )
        assert isinstance(
            two_strike_state,
            ProspectiveTwoStrikeStopFilterState,
        )
        assert isinstance(
            momentum_state,
            ProspectiveMomentumBandEntryState,
        )
        return {
            "risk_rejected_rows": [{"opportunity_id": "risk-reject-1"}],
            "risk_rejected_stack_evaluated": 1,
            "risk_rejected_integrity_clean": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }

    monkeypatch.setattr(
        deferred,
        "ContinuousPaperOpeningOpportunityStore",
        OpportunityStore,
    )
    monkeypatch.setattr(
        deferred,
        "ContinuousPaperOpeningOpportunityPathStore",
        PathStore,
    )
    monkeypatch.setattr(
        deferred,
        "LearningFeatureSnapshotStore",
        FeatureStore,
    )
    monkeypatch.setattr(deferred, "JournalStore", Journal)
    monkeypatch.setattr(
        deferred,
        "ContinuousPaperOpeningLineageStore",
        LineageStore,
    )
    monkeypatch.setattr(
        deferred,
        "first_seen_opening_witness_summary",
        lambda opportunities, trades, witnesses, *, overlap_started_at_ms: {
            "kind": "verified-test-witness",
            "links": (opportunities, trades, witnesses),
            "overlap": overlap_started_at_ms,
            "research_readiness_grant": False,
        },
    )
    monkeypatch.setattr(
        deferred,
        "prospective_full_stack_forward_markout_summary",
        summary,
    )

    payload = deferred.rebuild_deferred_full_stack_forward_markout(
        tmp_path
    )

    assert journal_closed is True
    assert roots == {
        "opportunities": tmp_path / "opening-opportunities",
        "paths": tmp_path / "opening-opportunity-paths",
        "features": tmp_path / "learning-features",
        "lineages": tmp_path / "opening-lineage",
        "journal": tmp_path / "journal.sqlite3",
    }
    assert payload["risk_rejected_stack_evaluated"] == 1
    assert payload["risk_rejected_integrity_clean"] is True
    witness = payload["first_seen_opening_witness"]
    assert witness["kind"] == "verified-test-witness"
    assert witness["links"] == [
        ["opportunity"],
        ["trade"],
        ["lineage"],
    ] or witness["links"] == (
        ("opportunity",), ("trade",), ("lineage",)
    )
    assert witness["research_readiness_grant"] is False
    assert payload["deferred_post_handoff_rebuild"] is True
    assert payload["source_exit_reason"] == "upgrade_requested"
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False


def test_deferred_rebuild_rejects_non_upgrade_session(
    tmp_path: Path,
) -> None:
    _write_state_files(tmp_path, exit_reason="duration_elapsed")

    with pytest.raises(
        deferred.DeferredFullStackForwardMarkoutError,
        match="upgrade-requested handoff",
    ):
        deferred.rebuild_deferred_full_stack_forward_markout(tmp_path)


def test_deferred_rebuild_rejects_authority_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_state_files(tmp_path, exit_reason="upgrade_requested")

    class EmptyStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def iter_records(self) -> tuple[object, ...]:
            return ()

        def iter_paths(self) -> tuple[object, ...]:
            return ()

        def iter_trades(self) -> tuple[object, ...]:
            return ()

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        deferred,
        "ContinuousPaperOpeningOpportunityStore",
        EmptyStore,
    )
    monkeypatch.setattr(
        deferred,
        "ContinuousPaperOpeningOpportunityPathStore",
        EmptyStore,
    )
    monkeypatch.setattr(
        deferred,
        "LearningFeatureSnapshotStore",
        EmptyStore,
    )
    monkeypatch.setattr(deferred, "JournalStore", EmptyStore)
    monkeypatch.setattr(
        deferred,
        "prospective_full_stack_forward_markout_summary",
        lambda *_args: {
            "risk_rejected_rows": [],
            "risk_rejected_stack_evaluated": 0,
            "risk_rejected_integrity_clean": True,
            "execution_authority": True,
            "promotion_authority": False,
        },
    )

    with pytest.raises(
        deferred.DeferredFullStackForwardMarkoutError,
        match="execution authority",
    ):
        deferred.rebuild_deferred_full_stack_forward_markout(tmp_path)


def test_deferred_writer_replaces_only_derived_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / deferred.OUTPUT_FILENAME
    target.write_text("stale", encoding="utf-8")
    monkeypatch.setattr(
        deferred,
        "rebuild_deferred_full_stack_forward_markout",
        lambda _root: {
            "risk_rejected_rows": [],
            "risk_rejected_stack_evaluated": 0,
            "risk_rejected_integrity_clean": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "deferred_post_handoff_rebuild": True,
        },
    )

    written = deferred.write_deferred_full_stack_forward_markout(
        tmp_path
    )

    assert written == target
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["deferred_post_handoff_rebuild"] is True
    assert payload["execution_authority"] is False
