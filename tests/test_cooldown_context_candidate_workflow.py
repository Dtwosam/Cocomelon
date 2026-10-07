from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/continuous-paper.yml")


def test_cooldown_candidate_research_tail_stays_after_handoff() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    fast_dispatch = source.index("- name: Queue exact successor from fast resume")
    durable_upload = source.index("- name: Upload durable continuous paper state")
    rebuild = source.index("- name: Rebuild deferred cooldown evidence after handoff")
    selection = source.index("- name: Build cooldown context selection record")
    restore = source.index("- name: Restore immutable cooldown context freeze")
    freeze = source.index("- name: Freeze selected cooldown context prospectively")
    prospective = source.index(
        "- name: Score frozen cooldown context on future evidence"
    )
    upload = source.index("- name: Upload immutable cooldown context candidate")

    assert (
        fast_dispatch
        < durable_upload
        < rebuild
        < selection
        < restore
        < freeze
        < prospective
        < upload
    )


def test_cooldown_candidate_artifact_is_research_only_and_restored_safely() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "continuous-paper-cooldown-context-candidate" in source
    assert "cooldown-context-candidate-freeze.json" in source
    assert "cooldown-context-prospective-report.json" in source
    assert "verify_cooldown_context_candidate_freeze" in source
    assert 'run.get("path") == ".github/workflows/continuous-paper.yml"' in source
    assert 'run.get("conclusion") in {"success", "failure"}' in source
    assert "source_paper_run_id" in source or "--source-paper-run-id" in source
    assert "--source-paper-run-attempt" in source
    assert "--source-paper-head-sha" in source
    assert "prospective not-before ms" in source
    assert "ready for review / changes risk limits / execution" in source
    assert "RESEARCH ONLY / NO STRATEGY OR RISK CHANGE" in source


def test_cooldown_candidate_freezes_once_and_does_not_rewrite_context() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    freeze_at = source.index("- name: Freeze selected cooldown context prospectively")
    prospective_at = source.index(
        "- name: Score frozen cooldown context on future evidence"
    )
    block = source[freeze_at:prospective_at]

    assert 'if [ -s "$freeze_path" ]; then' in block
    assert 'echo "created=false"' in block
    assert "selected_candidate" in block
    assert "cocomelon-cooldown-context-freeze" in block
    assert "date +%s%3N" in block


def test_new_cooldown_candidate_code_wakes_continuous_paper() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert '"src/cocomelon/research/cooldown_context_candidate.py"' in source
    assert '"src/cocomelon/research/cooldown_context_prospective.py"' in source
    assert '"src/cocomelon/cooldown_context_candidate_cli.py"' in source
    assert '"src/cocomelon/cooldown_context_prospective_cli.py"' in source
