from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-long-trend-carveout-fast-markout-ledger.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_long_trend_carveout_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective LONG+Trend Carveout Fast-Markout Ledger" in source
    assert '"Continuous Mainnet Paper Trader"' in source
    assert 'LEDGER_ISSUE: "802"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**Changes risk limits:**" in source
    assert "**Changes candidate readiness:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_long_trend_carveout_workflow_binds_exact_paper_source() -> None:
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
    assert "prospective-full-stack-forward-markout-summary.json" in source
    assert (
        'candidate_id = '
        '"prospective-top10-two-strike-momentum-no-long-trend-v1"'
        in source
    )
    assert 'row.get("long_trend_carveout_candidate_id")' in source
    assert 'candidate.get("stop_path_overlay")' in source
    assert 'stop_overlay.get("enabled") is True' in source
    assert '"observed_mark_stop_crossing_only"' in source
    assert 'row.get("long_trend_carveout_stop_path")' in source


def test_long_trend_carveout_workflow_restores_append_only_ledger() -> None:
    source = _source()

    assert (
        "prospective-long-trend-carveout-fast-markout-ledger-"
        in source
    )
    assert (
        "prospective-long-trend-carveout-fast-markout-ledger.json"
        in source
    )
    assert (
        "update_prospective_long_trend_carveout_fast_markout_ledger.py"
        in source
    )
    assert "--source-artifact-digest" in source
    assert "--previous" in source
    assert "append-only invariant failure" in source
    assert "Fail closed on ledger drift" in source
    assert (
        "Every previously published terminal row must remain "
        "byte-for-byte equivalent"
        in source
    )


def test_long_trend_carveout_legacy_sources_wait_without_credit() -> None:
    source = _source()
    compact = source.split(
        "      - name: Download compact paper source",
        1,
    )[1].split(
        "      - name: Publish waiting-for-source status",
        1,
    )[0]

    assert 'print("current" if current else "legacy")' in compact
    assert 'if [ "$format_check" != "current" ]; then' in compact
    assert "predates long-trend stop-path lineage" in compact
    assert 'echo "eligible=false"' in compact
    assert "Fail closed on ledger drift" not in compact


def test_long_trend_carveout_gate_cannot_authorize_trading() -> None:
    source = _source()

    assert "ready for execution-shadow investigation" in source
    assert (
        "Passing this gate can authorize only a deeper paper "
        "execution-shadow investigation."
        in source
    )
    assert (
        "It cannot change the live/frozen entry stack, any risk limit, "
        "sizing, candidate readiness, promotion state, or live-order authority."
        in source
    )
    assert ">=10 reopened pure LONG+trend opportunities" in source


def test_long_trend_carveout_status_surfaces_stop_path_survival() -> None:
    source = _source()

    assert "Stop eval" in source
    assert "Stop crossed" in source
    assert "Stop survived" in source
    assert 'stop_path["crossing_fraction"]' in source
    assert 'stop_path["median_time_to_stop_ms"]' in source
    assert "Stop-path survival is descriptive only" in source
    assert "does not model unseen intramillisecond prices" in source
    assert "is not part of the existing investigation gate" in source


def test_long_trend_carveout_non_success_wake_falls_back() -> None:
    source = _source()

    assert (
        'if [ "$EVENT_NAME" = "workflow_run" ] && '
        '[ "$EVENT_CONCLUSION" = "success" ]; then'
        in source
    )
    assert 'resolution_mode="successful_event"' in source
    assert (
        'resolution_mode="latest_successful_after_non_success_wake"'
        in source
    )
    assert (
        "actions/workflows/continuous-paper.yml/runs?"
        "branch=main&status=completed&per_page=50"
        in source
    )
    assert "latest_successful_with_compact_artifact" in source


def test_long_trend_carveout_status_uses_quoted_python_builders() -> None:
    source = _source()
    waiting = source.split(
        "      - name: Publish waiting-for-source status",
        1,
    )[1].split(
        "      - name: Restore previous fast-markout ledger",
        1,
    )[0]
    blocked = source.split(
        "      - name: Publish blocked ledger status",
        1,
    )[1].split(
        "      - name: Fail closed on ledger drift",
        1,
    )[0]
    clean = source.split(
        "      - name: Publish clean ledger status",
        1,
    )[1].split(
        "      - name: Upload fast-markout ledger",
        1,
    )[0]

    assert "python - <<'PY'" in waiting
    assert "python - <<'PY'" in blocked
    assert "python - <<'PY'" in clean
    assert "WAIT_REASON" in waiting
    assert 'os.environ.get("ERROR_TEXT")' in blocked
