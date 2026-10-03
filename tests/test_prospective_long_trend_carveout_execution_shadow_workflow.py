from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-long-trend-execution-shadow.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_long_trend_execution_shadow_workflow_is_research_only() -> None:
    source = _source()

    assert r'\\n      - "' not in source
    assert (
        '      - ".github/workflows/prospective-long-trend-execution-shadow.yml"\n'
        '      - "src/cocomelon/research/'
        'prospective_long_trend_carveout_execution_shadow.py"\n'
        '      - "scripts/evaluate_prospective_long_trend_execution_shadow.py"'
        in source
    )
    assert "Prospective LONG+Trend Execution Shadow" in source
    assert 'SHADOW_ISSUE: "828"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**Changes risk limits:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_long_trend_execution_shadow_binds_exact_paper_source() -> None:
    source = _source()

    assert (
        'run.get("path") != ".github/workflows/continuous-paper.yml"'
        in source
    )
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert (
        'expected_name="continuous-paper-learning-source-'
        '$candidate_run_id-$candidate_attempt"'
        in source
    )
    assert "source artifact digest is missing or invalid" in source
    assert "prospective-long-trend-execution-shadow-source.json" in source


def test_long_trend_execution_shadow_legacy_source_waits() -> None:
    source = _source()
    compact = source.split(
        "      - name: Download compact execution-shadow source",
        1,
    )[1].split(
        "      - name: Publish waiting-for-source status",
        1,
    )[0]

    assert 'print("current" if current else "legacy")' in compact
    assert 'if [ "$format_check" != "current" ]; then' in compact
    assert 'echo "eligible=false"' in compact
    assert "incompatible execution-shadow format" in compact


def test_long_trend_execution_shadow_wait_status_preserves_metadata() -> None:
    source = _source()
    waiting = source.split(
        "      - name: Publish waiting-for-source status",
        1,
    )[1].split(
        "      - name: Evaluate captured execution shadow",
        1,
    )[0]

    assert "python - <<'PY'" in waiting
    assert "SOURCE_RUN_ID" in waiting
    assert "SOURCE_RUN_ATTEMPT" in waiting
    assert "SOURCE_RESOLUTION" in waiting
    assert "WAIT_REASON" in waiting
    assert "<<EOF" not in waiting


def test_long_trend_execution_shadow_reuses_frozen_execution_path() -> None:
    source = _source()

    assert "evaluate_prospective_long_trend_execution_shadow.py" in source
    assert "counterfactual risk approvals" in source
    assert "planning approvals / rejections" in source
    assert "execution results" in source
    assert "Fee-adjusted forward markouts" in source
    assert "visible-book IOC" in source
    assert "Other risk vetoes remain active" in source


def test_long_trend_execution_shadow_uploads_deterministic_summary() -> None:
    source = _source()

    assert "prospective-long-trend-execution-shadow-summary.json" in source
    assert (
        "prospective-long-trend-execution-shadow-${{ github.run_id }}-"
        "${{ github.run_attempt }}"
        in source
    )
    assert "retention-days: 90" in source
