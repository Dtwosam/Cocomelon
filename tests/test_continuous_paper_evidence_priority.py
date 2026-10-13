"""Prevent expensive post-session rank seals from starving paired-paper evidence."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/continuous-paper.yml")


def _step(source: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    assert source.count(marker) == 1
    chunk = source.split(marker, 1)[1].split("\n      - ", 1)[0]
    return chunk


def test_paired_trend_signed_state_is_uploaded_before_costly_handoff_work() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    paper_end = source.index("      - name: Run continuous paper trader\n")
    paired_upload = source.index(
        "      - name: Upload isolated both-side trend paired-paper evidence\n"
    )
    heavy = source.index(
        "      - name: Seal entire original SHORT rank input features after paper exit\n"
    )
    fast_resume = source.index("      - name: Pack fast continuous paper resume state\n")
    assert paper_end < paired_upload < fast_resume < heavy
    section = _step(
        source, "Upload isolated both-side trend paired-paper evidence"
    )
    assert "always()" in section
    assert (
        "hashFiles('continuous-paper-state/"
        "both-side-trend-paired-shadow-summary.json')" in section
    )
    assert "steps.guard.outputs.skip != 'true'" in section
    assert "continue-on-error: true" in section
    assert "timeout-minutes: 12" in section
    assert "actions/upload-artifact@v7" in section
    assert "continuous-paper-both-side-trend-paired-shadow-" in section
    for artifact in (
        "both-side-trend-paired-shadow-freeze.json",
        "both-side-trend-paired-shadow-summary.json",
        "both-side-trend-paired-shadow-v1",
    ):
        assert artifact in section
    assert "if-no-files-found: error" in section


def test_expensive_rank_sealers_have_independent_finite_deadlines() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "timeout-minutes: 355" in source
    assert "--duration-seconds 14400" in source
    for name, timeout in (
        ("Seal entire original SHORT rank input features after paper exit", 18),
        ("Seal original SHORT rank market context after paper exit", 12),
    ):
        section = _step(source, name)
        assert f"timeout-minutes: {timeout}" in section
        assert "continue-on-error: true" in section
        assert "steps.guard.outputs.skip != 'true'" in section
    assert source.index(
        "      - name: Upload isolated both-side trend paired-paper evidence\n"
    ) < source.index(
        "      - name: Seal original first-seen SHORT rank source after worker exit\n"
    )


def test_worker_handoff_and_no_live_execution_contract_not_weakened() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "cancel-in-progress: false" in source
    assert "Queue exact successor from fast resume" in source
    assert "Upload fast continuous paper resume state" in source
    assert "Fail closed on upgrade handoff source" in source
    assert "exit 75" in source
    assert 'print("- live orders: false")' in source
