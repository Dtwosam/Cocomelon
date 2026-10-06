from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research import deferred_consecutive_loss_cooldown as deferred
from cocomelon.research.prospective_consecutive_loss_cooldown_shadow import (
    ProspectiveConsecutiveLossCooldownShadowState,
)


def _write_state(root: Path, *, exit_reason: str = "upgrade_requested") -> None:
    (root / "session-summary.json").write_text(
        json.dumps({"exit_reason": exit_reason}),
        encoding="utf-8",
    )
    (root / deferred.STATE_FILENAME).write_text(
        json.dumps(
            ProspectiveConsecutiveLossCooldownShadowState(
                frozen_at_ms=1_000,
            ).payload()
        ),
        encoding="utf-8",
    )


def test_deferred_cooldown_rebuild_uses_persisted_opportunities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_state(tmp_path)
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

    def evaluate(
        opportunities: object,
        paths: object,
        state: object,
        config: object,
    ) -> dict[str, object]:
        assert opportunities == ("opportunity",)
        assert paths == ("path",)
        assert isinstance(
            state,
            ProspectiveConsecutiveLossCooldownShadowState,
        )
        assert config is not None
        return {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "changes_risk_limits": False,
            "candidate_id": state.candidate_id,
            "clean_cooldown_rejections": 10,
            "candidate_eligible_cooldown_rejections": 6,
            "option_results": [],
        }

    monkeypatch.setattr(
        deferred,
        "prospective_consecutive_loss_cooldown_shadow_summary",
        evaluate,
    )

    payload = deferred.rebuild_deferred_consecutive_loss_cooldown(tmp_path)

    assert payload["clean_cooldown_rejections"] == 10
    assert payload["candidate_eligible_cooldown_rejections"] == 6
    assert payload["deferred_post_handoff_rebuild"] is True
    assert payload["source_exit_reason"] == "upgrade_requested"
    assert payload["execution_authority"] is False
    assert payload["changes_risk_limits"] is False
    assert observed["opportunity_root"] == tmp_path / "opening-opportunities"
    assert observed["path_root"] == tmp_path / "opening-opportunity-paths"


def test_deferred_cooldown_rebuild_requires_upgrade_handoff(
    tmp_path: Path,
) -> None:
    _write_state(tmp_path, exit_reason="duration_elapsed")

    with pytest.raises(
        deferred.DeferredConsecutiveLossCooldownError,
        match="upgrade-requested handoff",
    ):
        deferred.rebuild_deferred_consecutive_loss_cooldown(tmp_path)


def test_deferred_cooldown_rebuild_rejects_risk_authority_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_state(tmp_path)

    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def iter_records(self) -> tuple[object, ...]:
            return ()

        def iter_paths(self) -> tuple[object, ...]:
            return ()

    monkeypatch.setattr(
        deferred,
        "ContinuousPaperOpeningOpportunityStore",
        Store,
    )
    monkeypatch.setattr(
        deferred,
        "ContinuousPaperOpeningOpportunityPathStore",
        Store,
    )
    monkeypatch.setattr(
        deferred,
        "prospective_consecutive_loss_cooldown_shadow_summary",
        lambda _opportunities, _paths, state, _config: {
            "execution_authority": False,
            "promotion_authority": False,
            "changes_risk_limits": True,
            "candidate_id": state.candidate_id,
            "option_results": [],
        },
    )

    with pytest.raises(
        deferred.DeferredConsecutiveLossCooldownError,
        match="changed risk authority",
    ):
        deferred.rebuild_deferred_consecutive_loss_cooldown(tmp_path)


def test_deferred_cooldown_write_is_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_state(tmp_path)
    monkeypatch.setattr(
        deferred,
        "rebuild_deferred_consecutive_loss_cooldown",
        lambda _root: {
            "execution_authority": False,
            "promotion_authority": False,
            "changes_risk_limits": False,
            "candidate_id": "candidate",
            "option_results": [],
        },
    )

    target = deferred.write_deferred_consecutive_loss_cooldown(tmp_path)

    assert target == tmp_path / deferred.OUTPUT_FILENAME
    assert json.loads(target.read_text(encoding="utf-8"))["candidate_id"] == (
        "candidate"
    )
    assert not (tmp_path / f".{deferred.OUTPUT_FILENAME}.tmp").exists()
