"""The original source must outrank optional cadence research in PAPER."""
from __future__ import annotations

from pathlib import Path

from cocomelon.continuous_paper import (
    _cadence_shadow_with_original_source_priority,
)


def test_genuine_v3_capture_does_not_restore_optional_cadence_state() -> None:
    restore_count = 0

    def forbidden_restore():
        nonlocal restore_count
        restore_count += 1
        raise AssertionError("slow optional state restore must not run")

    shadow, reason = _cadence_shadow_with_original_source_priority(
        original_v3_capture_requested=True,
        restore=forbidden_restore,
    )
    assert shadow is None
    assert reason == "cadence_research_disabled_for_original_v3_source_priority"
    assert restore_count == 0


def test_without_v3_capture_original_research_state_restores_normally() -> None:
    shadow = object()
    calls = []

    def restore():
        calls.append("restored")
        return shadow

    result, reason = _cadence_shadow_with_original_source_priority(
        original_v3_capture_requested=False,
        restore=restore,  # type: ignore[arg-type]
    )
    assert result is shadow
    assert reason is None
    assert calls == ["restored"]


def test_actual_paper_runtime_wires_failure_receipt_before_optional_observer() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text()
    assert 'os.environ.get("V3_CAPTURE_ORIGINAL_SOURCE") == "1"' in source
    assert "cadence_shadow, cadence_source_priority_reason = (" in source
    assert "pump.cadence_shadow_error = cadence_source_priority_reason" in source
    assert "cadence_shadow=cadence_shadow," in source
    assert "if pump.cadence_shadow is not None:" in source
    assert "research_cadence_observer_exceeded_latency_budget" in source
    # The actual source recorder remains independent of optional research.
    assert "original_v3_capture=original_v3_capture," in source
    assert "live_orders_enabled: true" not in source
