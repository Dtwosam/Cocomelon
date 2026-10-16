"""Optional observer runtime failures cannot resurrect old research state."""
from __future__ import annotations

import json
from pathlib import Path

from cocomelon.continuous_paper import (
    CADENCE_SHADOW_RUNTIME_FAILURE_DISCONTINUITY,
    CADENCE_SHADOW_SOURCE_PRIORITY_DISCONTINUITY,
    _cadence_shadow_discontinuity_payload,
    _restore_cadence_shadow,
    _write_json_atomic,
)
from cocomelon.domain.market import MarketId
from cocomelon.evidence.contracts import BaselineReplayConfig


def test_source_and_runtime_discontinuity_markers_are_distinct_and_negative(
    tmp_path: Path,
) -> None:
    previous = tmp_path / "cadence-shadow-state.json"
    previous.write_text('{"valid_prior_research":"stale"}')
    for runtime_failure, reason, error in (
        (
            False, CADENCE_SHADOW_SOURCE_PRIORITY_DISCONTINUITY,
            "cadence_shadow_history_discontinuous_from_original_v3",
        ),
        (
            True, CADENCE_SHADOW_RUNTIME_FAILURE_DISCONTINUITY,
            "cadence_shadow_history_discontinuous_after_runtime_failure",
        ),
    ):
        payload = _cadence_shadow_discontinuity_payload(
            runtime_failure=runtime_failure,
        )
        _write_json_atomic(previous, payload)
        assert json.loads(previous.read_text()) == payload
        assert payload["continuity_status"] == reason
        assert payload["continuity_authenticated"] is False
        assert payload["execution_authority"] is False
        assert payload["promotion_authority"] is False
        assert "valid_prior_research" not in previous.read_text()
        shadow = _restore_cadence_shadow(
            previous, (MarketId("", "BTC"),),
            replay_config=BaselineReplayConfig(),
        )
        observed = shadow.summary_payload()
        assert observed["state_restored"] is False
        assert error in str(observed["state_restore_error"])
        assert observed["execution_authority"] is False


def test_failure_after_one_slow_observation_tombstones_before_handoff() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text()
    assert "research_cadence_observer_exceeded_latency_budget" in source
    assert "if elapsed_ms >= MAX_OPTIONAL_CADENCE_OBSERVE_MS:" in source
    assert "pump.cadence_shadow_error is not None" in source
    assert "cadence_source_priority_reason is None" in source
    assert "_cadence_shadow_discontinuity_payload(" in source
    assert "cadence_revision_to_persist = -1" in source
    assert "cadence_shadow_persisted_revision = cadence_revision" in source
    assert '"continuity_authenticated": False' in source
    assert "original_v3_capture=original_v3_capture," in source
