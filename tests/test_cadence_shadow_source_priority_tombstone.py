"""Skipped v3 cadence research cannot resurrect stale continuous shadow history."""
from __future__ import annotations

import json
from pathlib import Path

from cocomelon.continuous_paper import (
    CADENCE_SHADOW_SOURCE_PRIORITY_DISCONTINUITY,
    _cadence_shadow_discontinuity_payload,
    _restore_cadence_shadow,
    _write_json_atomic,
)
from cocomelon.domain.market import MarketId
from cocomelon.evidence.contracts import BaselineReplayConfig


def test_source_first_cadence_tombstone_persists_and_fails_research_continuity(
    tmp_path: Path,
) -> None:
    state = tmp_path / "cadence-shadow-state.json"
    # An earlier worker could have produced an otherwise valid old file.
    # Source-priority mode MUST replace it rather than pass it through.
    state.write_text('{"old_cadence_state":"not-current"}', encoding="utf-8")
    payload = _cadence_shadow_discontinuity_payload()
    _write_json_atomic(state, payload)
    assert json.loads(state.read_text()) == payload
    assert payload["continuity_status"] == (
        CADENCE_SHADOW_SOURCE_PRIORITY_DISCONTINUITY
    )
    assert payload["continuity_authenticated"] is False
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False

    resumed = _restore_cadence_shadow(
        state,
        (MarketId("", "BTC"),),
        replay_config=BaselineReplayConfig(),
    )
    summary = resumed.summary_payload()
    assert summary["state_restored"] is False
    assert "cadence_shadow_history_discontinuous_from_original_v3" in str(
        summary["state_restore_error"]
    )
    assert summary["execution_authority"] is False
    assert summary["shadow_only"] is True


def test_source_first_tombstone_never_contains_market_or_prior_evidence() -> None:
    payload = _cadence_shadow_discontinuity_payload()
    assert set(payload) == {
        "schema_version", "continuity_status", "research_only", "shadow_only",
        "execution_authority", "promotion_authority",
        "continuity_authenticated",
    }
    assert "market" not in json.dumps(payload)
    assert "observations" not in json.dumps(payload)
    assert "pnl" not in json.dumps(payload).lower()


def test_actual_v3_paper_checkpoint_writes_research_tombstone_once() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text()
    assert "cadence_source_priority_reason is not None" in source
    assert "cadence_shadow_persisted_revision != -1" in source
    assert "cadence_revision_to_persist = -1" in source
    assert "_cadence_shadow_discontinuity_payload()," in source
    assert "cadence_shadow_persisted_revision = cadence_revision" in source
    assert '"cadence_shadow_history_discontinuous_from_original_v3"' in source
    assert "original_v3_capture=original_v3_capture," in source
