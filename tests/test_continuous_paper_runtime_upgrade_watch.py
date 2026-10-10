"""Actual source-file tokens must reach the running paper worker upgrade watch.

A previous giant shell `git diff ... -- <paths>` concatenated two Python
paths into a single impossible argument. The main-push bootstrap sees an
active worker and correctly skips a duplicate; therefore the genuine active
worker's runtime watch MUST still recognize changes to research producers.
"""
from __future__ import annotations

import shlex
from pathlib import Path


WATCH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "continuous-paper.yml"
)


def _watched_paths() -> tuple[str, ...]:
    text = WATCH.read_text(encoding="utf-8")
    command = 'git diff --name-only "$GITHUB_SHA" FETCH_HEAD --'
    assert text.count(command) == 1
    after = text.split(command, 1)[1]
    # End at the closing command substitution, before the heartbeat routing.
    assert '\n                )' in after
    shell_paths = after.split('\n                )', 1)[0]
    return tuple(shlex.split(shell_paths.replace("\\\n", " ")))


def test_original_terminal_source_changes_each_have_a_distinct_watch_token() -> None:
    paths = _watched_paths()
    required = (
        "src/cocomelon/research/terminal_journal_asof.py",
        "src/cocomelon/research/prospective_full_stack_forward_markout.py",
        "src/cocomelon/research/first_seen_opening_witness.py",
        "src/cocomelon/research/opportunity_inventory_witness.py",
        "src/cocomelon/research/deferred_full_stack_forward_markout.py",
        "scripts/rebuild_deferred_full_stack_forward_markout.py",
    )
    for path in required:
        assert paths.count(path) == 1, (
            "runtime handoff watch must have exactly one actual path token: "
            + path
        )
        assert (WATCH.parents[2] / path).is_file()


def test_runtime_watch_rejects_accidentally_concatenated_source_paths() -> None:
    paths = _watched_paths()
    assert not any(".pysrc/" in item for item in paths)
    assert not any(".pyscripts/" in item for item in paths)
    assert not any(".py.github/" in item for item in paths)
