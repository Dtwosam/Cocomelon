"""Regression guard for bounded optional post-handoff research.

These limits cannot replace the exact-state handoff, start a competing worker,
or turn failed/incomplete analyses into profitable evidence.
"""

from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "continuous-paper.yml"
)


def _step(source: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    assert source.count(marker) == 1
    return source.split(marker, 1)[1].split("\n      - name: ", 1)[0]


def test_optional_chart_and_markout_research_have_bounded_worker_occupancy() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    fast_dispatch = source.index("- name: Queue exact successor from fast resume")
    fallback = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    optional_steps = (
        "Audit all closed paper trades and recorded entry-to-exit charts",
        "Rebuild deferred full-stack markouts after handoff",
    )
    for name in optional_steps:
        assert source.index(f"- name: {name}") > fallback > fast_dispatch
        block = _step(source, name)
        assert "continue-on-error: true" in block
        assert "timeout-minutes: 30" in block
        assert "steps.guard.outputs.skip != 'true'" in block
        assert "steps.fast_resume_dispatch.outcome == 'success'" in block
        assert "steps.fallback_resume_dispatch.outcome == 'success'" in block
        assert "shell: bash" in block

    # A timeout remains a failed optional step, and cannot interfere with the
    # trader or the state and successor-creation steps preceding the research.
    trader = _step(source, "Run continuous paper trader")
    assert "timeout-minutes: 30" not in trader
    assert source.index("- name: Pack durable continuous paper state") < fallback
