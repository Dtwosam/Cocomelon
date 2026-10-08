from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowCandidateError,
    verify_loss_context_portfolio_shadow_freeze,
)
from cocomelon.research.prospective_trend_outside_top10 import (
    ProspectiveTrendOutsideTop10State,
)
from cocomelon.research.targeted_trend_paired_freeze import (
    SOURCE_AUDIT_RAW_SHA256,
    SOURCE_LAST_CLOSED_AT_MS,
    SOURCE_UNRESOLVED_LEGACY_FEATURES,
    TargetedTrendPairedFreezeError,
    activate_targeted_trend_paired_freeze,
    targeted_trend_paired_freeze,
)


def _hypothesis() -> ProspectiveTrendOutsideTop10State:
    return ProspectiveTrendOutsideTop10State(
        frozen_at_ms=SOURCE_LAST_CLOSED_AT_MS + 2_000
    )


def test_targeted_trend_freeze_matches_frozen_d087_entry_hypothesis() -> None:
    state = _hypothesis()
    freeze = targeted_trend_paired_freeze(state)
    assert freeze.dimensions == ("lead_strategy", "rank_band")
    assert freeze.values == ("trend", "outside10")
    assert freeze.frozen_at_ms == state.frozen_at_ms
    assert freeze.prospective_not_before_ms == state.started_at_ms
    assert freeze.prospective_not_before_ms == (
        state.frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
    )
    assert freeze.source_max_timestamp_ms == SOURCE_LAST_CLOSED_AT_MS
    assert freeze.source_composition_digest != freeze.loss_context_candidate_id
    assert len(SOURCE_AUDIT_RAW_SHA256) == 64
    assert SOURCE_UNRESOLVED_LEGACY_FEATURES == 7
    assert freeze.horizon_selection_performed is False
    assert freeze.execution_authority is False
    assert freeze.promotion_authority is False
    assert freeze.changes_strategy is False
    assert freeze.changes_positions is False
    assert freeze.changes_risk_limits is False
    assert freeze.research_only is True
    assert freeze.candidate_id == targeted_trend_paired_freeze(state).candidate_id


def test_targeted_trend_freeze_rejects_historical_reuse() -> None:
    state = ProspectiveTrendOutsideTop10State(
        frozen_at_ms=SOURCE_LAST_CLOSED_AT_MS - 1
    )
    with pytest.raises(
        TargetedTrendPairedFreezeError,
        match="predates discovery audit",
    ):
        targeted_trend_paired_freeze(state)


def test_targeted_freeze_persists_and_survives_worker_handoff(tmp_path: Path) -> None:
    file = tmp_path / "targeted-trend-rank-paired-portfolio-freeze.json"
    paired_state = tmp_path / "shadow" / "paired-shadow-state.json"
    state = _hypothesis()
    first, created = activate_targeted_trend_paired_freeze(
        file, state, paired_state_path=paired_state
    )
    assert created is True
    assert verify_loss_context_portfolio_shadow_freeze(file) == first
    payload = json.loads(file.read_text(encoding="utf-8"))
    assert payload["prospective_not_before_ms"] == state.started_at_ms
    assert payload["values"] == ["trend", "outside10"]
    newer = ProspectiveTrendOutsideTop10State(
        frozen_at_ms=state.frozen_at_ms + 3_600_000
    )
    second, created_again = activate_targeted_trend_paired_freeze(
        file, newer, paired_state_path=paired_state
    )
    assert created_again is False
    assert second == first
    assert second.frozen_at_ms == state.frozen_at_ms


def test_targeted_freeze_never_overwrites_other_paired_identity(
    tmp_path: Path,
) -> None:
    file = tmp_path / "targeted-freeze.json"
    paired_state = tmp_path / "shadow" / "paired-shadow-state.json"
    paired_state.parent.mkdir()
    paired_state.write_text("{}", encoding="utf-8")
    with pytest.raises(
        TargetedTrendPairedFreezeError,
        match="without its original frozen identity",
    ):
        activate_targeted_trend_paired_freeze(
            file, _hypothesis(), paired_state_path=paired_state
        )
    assert not file.exists()


def test_targeted_freeze_detects_tampered_original_file(tmp_path: Path) -> None:
    file = tmp_path / "targeted-freeze.json"
    paired_state = tmp_path / "shadow" / "paired-shadow-state.json"
    _, _ = activate_targeted_trend_paired_freeze(
        file, _hypothesis(), paired_state_path=paired_state
    )
    raw = json.loads(file.read_text(encoding="utf-8"))
    raw["dimensions"] = ["direction", "rank_band"]
    file.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(LossContextPortfolioShadowCandidateError):
        activate_targeted_trend_paired_freeze(
            file, _hypothesis(), paired_state_path=paired_state
        )


def test_legacy_composition_gate_remains_independent() -> None:
    workflow = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    helper = Path(
        "src/cocomelon/research/targeted_trend_paired_freeze.py"
    ).read_text(encoding="utf-8")
    assert 'TARGETED_TREND_PAIRED_SHADOW_FREEZE_FILENAME' in source
    assert "targeted-trend-rank-paired-portfolio-freeze.json" in workflow
    assert "activate_targeted_trend_paired_freeze(" in source
    assert "LossContextPairedShadowRuntime(" in source
    assert "prospective_trend_outside_top10_restore_error is None" in source
    assert "loss_context_paired_shadow_restore_error" in source
    assert '      - "src/cocomelon/research/targeted_trend_paired_freeze.py"\n' in workflow
    assert workflow.count(
        "src/cocomelon/research/targeted_trend_paired_freeze.py"
    ) >= 2
    assert "loss-context-portfolio-shadow-freeze.json" in workflow
    assert "ready_for_chronological_portfolio_replay" in workflow
    assert "legacy_loss_context_freeze_path" in source
    assert "targeted_trend_freeze_path" in source
    assert "source_audit_raw_sha256" in helper
    assert "no_legacy_composition_gate_credit" in helper
    assert "historical_feature_coverage_complete" in helper
    assert 'research_only=True' in helper or '"research_only": True' in helper
