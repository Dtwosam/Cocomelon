from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-learning-cycle.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_learning_cycle_workflow_follows_successful_learning_sync() -> None:
    source = _source()

    assert "Research Autonomous Learning Cycle" in source
    assert 'workflows: ["Research Learning Evidence Sync"]' in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "upstream_run_id:" in source
    assert "github.event.workflow_run.conclusion == 'success'" in source
    assert "github.event.workflow_run.head_branch == 'main'" in source
    assert "github.event_name == 'workflow_dispatch'" in source
    assert 'inputs.upstream_run_id' in source
    assert "\n  schedule:" not in source


def test_learning_cycle_workflow_binds_exact_state_artifact_and_protocol() -> None:
    source = _source()

    assert "research-learning-state" in source
    assert "cocomelon-learning-cycle" in source
    assert "last-sync.json" in source
    assert "readiness.json" in source
    assert "git rev-parse HEAD" in source
    assert "expected-learning-state-digest" in source
    assert "expected-feature-state-digest" in source
    assert "verify_learning_state_lineage" in source
    assert 'sync.get("lineage_sequence") != lineage.sequence' in source
    assert 'sync.get("lineage_entry_id") != lineage.entry_id' in source
    assert 'run.get("id") != int(os.environ["RUN_ID"])' in source
    assert 'run.get("head_sha")' in source


def test_learning_cycle_workflow_remains_research_only() -> None:
    source = _source().lower()

    assert 'cocomelon_execution_mode: paper' in source
    assert 'python -m pip install -e ".[research]"' in source
    assert "api.hyperliquid" not in source
    assert "testnet" not in source
    assert "live_execution" not in source
    assert "promotion_eligible" in source
    assert "cocomelon-learning-experiment " not in source


def test_learning_cycle_artifact_uses_authenticated_upstream_identity() -> None:
    source = _source()
    publish = source.split(
        "- name: Publish immutable learning cycle artifact",
        1,
    )[1]

    assert (
        "research-learning-cycle-${{ steps.state.outputs.run_id }}-"
        "${{ steps.state.outputs.run_attempt }}"
    ) in publish
    assert "github.event.workflow_run.id" not in publish
    assert "github.event.workflow_run.run_attempt" not in publish


def test_learning_cycle_freezes_every_development_qualified_candidate() -> None:
    source = _source()
    freeze = source.split(
        "- name: Freeze development-qualified learning candidates",
        1,
    )[1].split(
        "- name: Render research cycle summary",
        1,
    )[0]

    assert 'for LABEL in baseline tree; do' in freeze
    assert 'FIELD="${LABEL}_qualifies_development"' in freeze
    assert 'cocomelon-learning-candidate-freeze' in freeze
    assert '--experiment-root "learning-cycle/$LABEL"' in freeze
    assert '--output-root "$OUTPUT_ROOT"' in freeze
    assert 'OUTPUT_ROOT="learning-cycle/frozen-candidates/$LABEL"' in freeze
    assert 'FROZEN_AT_MS="$(date +%s%3N)"' in freeze
    assert '--frozen-at-ms "$FROZEN_AT_MS"' in freeze
    assert ".prospective_only == true" in freeze
    assert ".research_only == true" in freeze
    assert ".promotion_eligible == false" in freeze
    assert ".execution_ready == false" in freeze
    assert "winner" not in freeze.lower()


def test_learning_cycle_skips_freeze_when_cycle_is_not_completed() -> None:
    source = _source()
    freeze = source.split(
        "- name: Freeze development-qualified learning candidates",
        1,
    )[1].split(
        "- name: Render research cycle summary",
        1,
    )[0]

    assert "CYCLE_STATUS=\"$(jq -r '.status' learning-cycle/cycle.json)\"" in freeze
    assert 'if [ "$CYCLE_STATUS" != "completed" ]; then' in freeze
    assert 'echo "frozen_count=0" >> "$GITHUB_OUTPUT"' in freeze
