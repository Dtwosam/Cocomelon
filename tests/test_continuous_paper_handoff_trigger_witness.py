"""Handoff exit attribution must not become economic or execution authority.

At the 2026-10-18 rollover, an authenticated predecessor had exit 143
and an upgrade-stop file. That marker alone cannot distinguish the opted-in
main-push watcher from the unconditional 4h15m session-overrun watchdog.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

WORKFLOW = Path(".github/workflows/continuous-paper.yml")


def _runtime() -> str:
    source = WORKFLOW.read_text(encoding="utf-8")
    return source.split("- name: Run continuous paper trader", 1)[1].split(
        "- name: Upload anonymous PAPER trader failure receipt", 1
    )[0]


def _classification_case() -> str:
    runtime = _runtime()
    branch = runtime.split('case "$replacement_run" in', 1)[1]
    return dedent('case "$replacement_run" in' + branch.split(
        "\n            esac", 1
    )[0] + "\n            esac")


@pytest.mark.parametrize(("replacement", "expected"), [
    ("session-overrun-watchdog", "session-overrun-watchdog"),
    ("39120486505", "opt-in-main-push"),
    ("", "unclassified"),
    ("invalid GitHub text", "unclassified"),
    ("145ad234", "unclassified"),
    ("main; rm -rf /", "unclassified"),
])
def test_bounded_handoff_cause_is_only_from_known_trigger(
    replacement: str, expected: str,
) -> None:
    script = _classification_case() + '\nprintf "%s" "$handoff_trigger"\n'
    run = subprocess.run(
        ["bash", "-c", script], check=True, capture_output=True,
        text=True, env={**os.environ, "replacement_run": replacement},
    )
    assert run.stdout == expected
    assert run.stderr == ""


def test_original_stop_signal_and_safety_watchdog_are_untouched() -> None:
    runtime = _runtime()
    assert 'PAPER_ROLL_ON_MAIN_PUSH: ${{ vars.PAPER_ROLL_ON_MAIN_PUSH' in runtime
    assert 'if [ "${PAPER_ROLL_ON_MAIN_PUSH:-false}" = "true" ]; then' in runtime
    assert 'request_runtime_handoff "$trader_pid" "$replacement_run"' in runtime
    assert 'request_runtime_handoff "$trader_pid" "session-overrun-watchdog"' in runtime
    assert "sleep 15300" in runtime
    assert "kill -INT" in runtime
    assert "kill -TERM" in runtime
    marker = runtime.index("> /tmp/continuous-paper-handoff-trigger || true")
    stop = runtime.index("touch /tmp/continuous-paper-upgrade-requested")
    assert marker < stop
    assert "handoff_trigger=none-observed" not in runtime
    assert 'handoff_trigger="none-observed"' in runtime


def test_terminal_failure_receipt_reports_cause_without_inventing_success() -> None:
    runtime = _runtime()
    assert "handoff_trigger=" in runtime
    assert "case \"$(cat /tmp/continuous-paper-handoff-trigger)\" in" in runtime
    assert 'printf \'handoff_trigger=%s\\n\' "$handoff_trigger"' in runtime
    assert '"stop request cause: $handoff_trigger (diagnostic only)"' in runtime
    assert '"original_account_verified=not_inferred"' in runtime or (
        "original_account_verified=not_inferred" in runtime
    )
    assert "after_cost_profit_verified=false" in runtime
    assert "live_authority=false" in runtime
    assert "exit \"$exit_code\"" in runtime
    # Never let a missing reason field infer a routine main-push upgrade.
    assert 'handoff_trigger="unclassified"' in runtime
