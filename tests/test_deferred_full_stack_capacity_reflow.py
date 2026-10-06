from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.research import deferred_full_stack_capacity_reflow as deferred
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterState,
)


def _write_required_state(root: Path, *, exit_reason: str) -> None:
    (root / "session-summary.json").write_text(
        json.dumps(
            {
                "exit_reason": exit_reason,
                "started_at_ms": 1_000,
            }
        ),
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
    for name in ("paper.sqlite3", "facts.sqlite3", "journal.sqlite3"):
        (root / name).write_bytes(b"x")


def test_deferred_capacity_reflow_uses_persisted_exact_economics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_required_state(tmp_path, exit_reason="upgrade_requested")
    closed: list[str] = []
    observed: dict[str, object] = {}

    class OpportunityStore:
        def __init__(self, root: Path) -> None:
            observed["opportunity_root"] = root

        def iter_records(self) -> tuple[str, ...]:
            return ("opportunity",)

    class LineageStore:
        def __init__(self, root: Path) -> None:
            observed["lineage_root"] = root

        def iter_records(self) -> tuple[str, ...]:
            return ("lineage",)

    class RankStore:
        def __init__(self, root: Path) -> None:
            observed["rank_root"] = root

    class FeatureStore:
        def __init__(self, root: Path) -> None:
            observed["feature_root"] = root

    class Journal:
        def __init__(self, path: Path) -> None:
            observed["journal_path"] = path

        def iter_trades(self) -> tuple[str, ...]:
            return ("trade",)

        def close(self) -> None:
            closed.append("journal")

    class Facts:
        def __init__(self, path: Path) -> None:
            observed["facts_path"] = path

        def close(self) -> None:
            closed.append("facts")

    class Paper:
        def __init__(self, path: Path) -> None:
            observed["paper_path"] = path

        def load_position_histories(
            self,
            requests: tuple[tuple[str, int], ...],
        ) -> dict[tuple[str, int], tuple[str, ...]]:
            observed["position_history_requests"] = requests
            return {
                request: ("position-history",)
                for request in requests
            }

        def close(self) -> None:
            closed.append("paper")

    monkeypatch.setattr(
        deferred,
        "ContinuousPaperOpeningOpportunityStore",
        OpportunityStore,
    )
    monkeypatch.setattr(
        deferred,
        "ContinuousPaperOpeningLineageStore",
        LineageStore,
    )
    monkeypatch.setattr(
        deferred,
        "ContinuousPaperOpeningRankStore",
        RankStore,
    )
    monkeypatch.setattr(
        deferred,
        "LearningFeatureSnapshotStore",
        FeatureStore,
    )
    monkeypatch.setattr(deferred, "JournalStore", Journal)
    monkeypatch.setattr(deferred, "EvaluationFactStore", Facts)
    monkeypatch.setattr(deferred, "PaperExecutionStore", Paper)
    monkeypatch.setattr(
        deferred,
        "_open_exit_book_store",
        lambda _root: "exit-book-store",
    )
    monkeypatch.setattr(
        deferred,
        "_open_funding_store",
        lambda _root: "funding-store",
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_combined_entry_filter",
        lambda journal, facts, ranks, state: {
            "decision_block_reason_by_trade_id": {"t": None}
        },
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_two_strike_stop_filter",
        lambda journal, state: {
            "decision_prior_strikes": {"t": 0}
        },
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_momentum_band_entry",
        lambda journal, features, state: {
            "decision_details": {
                "t": {"decision": "ADMIT", "reason": "inside_band"}
            }
        },
    )

    release = SimpleNamespace(
        opportunity_id="release-1",
        release_opening_plan_id="plan-a",
        opportunity_timestamp_ms=8_000,
    )

    def evaluate(
        opportunities: object,
        lineages: object,
        trades: object,
        features: object,
        combined_state: object,
        two_state: object,
        momentum_state: object,
        combined: object,
        two: object,
        momentum: object,
    ) -> SimpleNamespace:
        assert opportunities == ("opportunity",)
        assert lineages == ("lineage",)
        assert trades == ("trade",)
        return SimpleNamespace(
            releases=(release,),
            summary={
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "baseline_capacity_rejections": 9,
                "candidate_capacity_release_opportunities": 3,
                "integrity_clean": True,
            },
        )

    monkeypatch.setattr(
        deferred,
        "prospective_full_stack_capacity_reflow",
        evaluate,
    )

    def fill(
        opportunities: object,
        releases: object,
        config: object,
        *,
        position_history_loader: object,
    ) -> dict[str, object]:
        assert opportunities == ("opportunity",)
        assert releases == (release,)
        loader = position_history_loader
        assert callable(loader)
        assert loader("plan-a", 8_000) == ("position-history",)
        return {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "replacement_entry_fills_modeled": True,
            "exact_fill_evidence": True,
        }

    monkeypatch.setattr(
        deferred,
        "prospective_capacity_reflow_fill_feasibility_summary",
        fill,
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_capacity_reflow_exit_fill",
        lambda fill_payload, exit_store, config: {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "replacement_entry_fills_modeled": True,
            "replacement_exit_fills_modeled": True,
            "cross_horizon_economics_aggregated": False,
        },
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_capacity_reflow_realized_pnl",
        lambda exit_payload, funding_store: {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "strategy_level_realized_pnl_claimed": False,
            "exact_realized_pnl_available": True,
        },
    )

    payload = deferred.rebuild_deferred_full_stack_capacity_reflow(
        tmp_path
    )

    assert payload["baseline_capacity_rejections"] == 9
    assert payload["candidate_capacity_release_opportunities"] == 3
    assert payload["replacement_entries_modeled"] is True
    assert payload["replacement_exits_modeled"] is True
    assert payload["pnl_modeled"] is True
    assert payload["exact_realized_pnl_available"] is True
    assert payload["cross_horizon_economics_aggregated"] is False
    assert payload["strategy_level_realized_pnl_claimed"] is False
    assert payload["deferred_post_handoff_rebuild"] is True
    assert payload["source_exit_reason"] == "upgrade_requested"
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert observed["position_history_requests"] == (("plan-a", 8_000),)
    assert sorted(closed) == ["facts", "journal", "paper"]


def test_deferred_capacity_reflow_preserves_fail_open_economic_layers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_required_state(tmp_path, exit_reason="upgrade_requested")

    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def iter_records(self) -> tuple[object, ...]:
            return ()

        def iter_trades(self) -> tuple[object, ...]:
            return ()

        def close(self) -> None:
            pass

        def load_position_histories(
            self,
            requests: tuple[tuple[str, int], ...],
        ) -> dict[tuple[str, int], tuple[object, ...]]:
            return {request: () for request in requests}

    for name in (
        "ContinuousPaperOpeningOpportunityStore",
        "ContinuousPaperOpeningLineageStore",
        "ContinuousPaperOpeningRankStore",
        "LearningFeatureSnapshotStore",
        "JournalStore",
        "EvaluationFactStore",
        "PaperExecutionStore",
    ):
        monkeypatch.setattr(deferred, name, Store)
    monkeypatch.setattr(
        deferred,
        "_open_exit_book_store",
        lambda _root: Store(),
    )
    monkeypatch.setattr(
        deferred,
        "_open_funding_store",
        lambda _root: Store(),
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_combined_entry_filter",
        lambda *_args: {"decision_block_reason_by_trade_id": {}},
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_two_strike_stop_filter",
        lambda *_args: {"decision_prior_strikes": {}},
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_momentum_band_entry",
        lambda *_args: {"decision_details": {}},
    )
    monkeypatch.setattr(
        deferred,
        "prospective_full_stack_capacity_reflow",
        lambda *_args: SimpleNamespace(
            releases=(),
            summary={
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "baseline_capacity_rejections": 0,
                "candidate_capacity_release_opportunities": 0,
                "integrity_clean": True,
            },
        ),
    )
    monkeypatch.setattr(
        deferred,
        "prospective_capacity_reflow_fill_feasibility_summary",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("no exact position history")
        ),
    )

    payload = deferred.rebuild_deferred_full_stack_capacity_reflow(
        tmp_path
    )

    assert payload["enabled"] is True
    assert payload["fill_feasibility"]["enabled"] is False
    assert payload["replacement_entries_modeled"] is False
    assert payload["replacement_exits_modeled"] is False
    assert payload["pnl_modeled"] is False
    assert payload["exact_realized_pnl_available"] is False
    assert payload["execution_authority"] is False


def test_deferred_capacity_reflow_rejects_authority_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_required_state(tmp_path, exit_reason="upgrade_requested")

    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def iter_records(self) -> tuple[object, ...]:
            return ()

        def iter_trades(self) -> tuple[object, ...]:
            return ()

        def close(self) -> None:
            pass

    for name in (
        "ContinuousPaperOpeningOpportunityStore",
        "ContinuousPaperOpeningLineageStore",
        "ContinuousPaperOpeningRankStore",
        "LearningFeatureSnapshotStore",
        "JournalStore",
        "EvaluationFactStore",
        "PaperExecutionStore",
    ):
        monkeypatch.setattr(deferred, name, Store)
    monkeypatch.setattr(
        deferred,
        "_open_exit_book_store",
        lambda _root: Store(),
    )
    monkeypatch.setattr(
        deferred,
        "_open_funding_store",
        lambda _root: Store(),
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_combined_entry_filter",
        lambda *_args: {"decision_block_reason_by_trade_id": {}},
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_two_strike_stop_filter",
        lambda *_args: {"decision_prior_strikes": {}},
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_momentum_band_entry",
        lambda *_args: {"decision_details": {}},
    )
    monkeypatch.setattr(
        deferred,
        "prospective_full_stack_capacity_reflow",
        lambda *_args: SimpleNamespace(
            releases=(),
            summary={
                "research_only": True,
                "execution_authority": True,
                "promotion_authority": False,
                "baseline_capacity_rejections": 0,
                "candidate_capacity_release_opportunities": 0,
                "integrity_clean": True,
            },
        ),
    )
    monkeypatch.setattr(
        deferred,
        "prospective_capacity_reflow_fill_feasibility_summary",
        lambda *_args, **_kwargs: {
            "execution_authority": False,
            "promotion_authority": False,
        },
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_capacity_reflow_exit_fill",
        lambda *_args: {
            "execution_authority": False,
            "promotion_authority": False,
        },
    )
    monkeypatch.setattr(
        deferred,
        "evaluate_prospective_capacity_reflow_realized_pnl",
        lambda *_args: {
            "execution_authority": False,
            "promotion_authority": False,
            "exact_realized_pnl_available": False,
        },
    )

    with pytest.raises(
        deferred.DeferredFullStackCapacityReflowError,
        match="execution authority",
    ):
        deferred.rebuild_deferred_full_stack_capacity_reflow(tmp_path)


def test_deferred_capacity_reflow_requires_upgrade_handoff(
    tmp_path: Path,
) -> None:
    _write_required_state(tmp_path, exit_reason="duration_elapsed")

    with pytest.raises(
        deferred.DeferredFullStackCapacityReflowError,
        match="upgrade-requested handoff",
    ):
        deferred.rebuild_deferred_full_stack_capacity_reflow(tmp_path)
