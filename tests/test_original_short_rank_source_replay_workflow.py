"""A replayable rank-source audit must remain a read-only, exact-worker verifier."""

from pathlib import Path

WORKFLOW = Path(".github/workflows/original-short-rank-source-audit.yml")


def test_source_audit_accepts_explicit_exact_completed_worker_replay() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "source_run_id:" in source
    assert "source_run_attempt:" in source
    assert "required: true" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in source
    assert "github.event.workflow_run.head_branch == 'main'" in source
    assert '[[ ! "$SOURCE_RUN_ID" =~ ^[1-9][0-9]*$' in source
    assert '"$SOURCE_RUN_ATTEMPT" =~ ^[1-9][0-9]*$' in source
    assert "repos/$GITHUB_REPOSITORY/actions/runs/$SOURCE_RUN_ID" in source
    assert 'source-run-id "$SOURCE_RUN_ID"' in source
    assert 'source-run-attempt "$SOURCE_RUN_ATTEMPT"' in source


def test_source_audit_bootstraps_only_known_three_archive_worker() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert '"38234626351"' not in source  # constant in GitHub expression, not fake JSON
    assert "'38234626351'" in source
    assert "push:" in source
    assert '      - ".github/workflows/original-short-rank-source-audit.yml"' in source
    assert "    branches:\n      - main\n    paths:" in source
    assert "Continuous Mainnet Paper Trader" in source
    for expected in (
        "continuous-paper-first-seen-short-rank-$SOURCE_RUN_ID-$attempt",
        "continuous-paper-first-seen-short-rank-full-inputs-$SOURCE_RUN_ID-$attempt",
        "continuous-paper-first-seen-short-rank-market-context-$SOURCE_RUN_ID-$attempt",
    ):
        assert expected in source


def test_source_audit_publishes_correct_source_identity_not_trigger_identity() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    for name in (
        "original-first-seen-short-rank-context-audit-",
        "original-first-seen-short-rank-coarse-score-audit-",
        "original-first-seen-short-rank-handoff-audit-",
        "original-first-seen-short-rank-audit-",
    ):
        assert (
            name + "${{ env.SOURCE_RUN_ID }}-${{ env.SOURCE_RUN_ATTEMPT }}"
        ) in source
    assert (
        "name: original-first-seen-short-rank-context-audit-"
        "${{ github.event.workflow_run.id }}"
    ) not in source


def test_source_audit_remains_read_only_and_not_promotion() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "  actions: read" in source
    assert "  contents: read" in source
    assert "actions: write" not in source
    assert "issues: write" not in source
    assert "gh workflow run" not in source
    assert "python -m scripts.audit_paper_short_rank_market_context" in source
    assert "original_mainnet_market_stream_and_gaps_authenticated" not in source
    assert "full account risk-matched after-cost edge: NOT PROVEN" in source
    assert "live order authority: FALSE" in source
