from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/phase9-selection-audit-archive.yml")
CURATOR = "Verified V2 Mainnet Evidence Corpus Curator"
ARCHIVE_TOOL_REVISION = "0d3c4240bf49987e8ffe16deecddfe18405006ee"
STATE_BRANCH = "phase9-v2-protocol-state"
FINAL_FILE = "phase9-v2-final.json"
ARCHIVE_FILE = "phase9-v2-selection-audits.json"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_archive_workflow_consumes_completed_curator_runs_and_separates_write_job() -> None:
    text = _text()

    assert "workflow_run:" in text
    assert CURATOR in text
    assert "types: [completed]" in text
    assert "build-archive:" in text
    assert "persist-archive:" in text
    build = text.index("build-archive:")
    persist = text.index("persist-archive:")
    assert build < persist
    build_block = text[build:persist]
    persist_block = text[persist:]
    assert "contents: read" in build_block
    assert "actions: read" in build_block
    assert "contents: write" not in build_block
    assert "contents: write" in persist_block
    assert "actions: read" in persist_block


def test_archive_workflow_pins_and_asserts_archive_tool_revision() -> None:
    text = _text()

    assert f"ARCHIVE_TOOL_REVISION: {ARCHIVE_TOOL_REVISION}" in text
    assert f"ref: {ARCHIVE_TOOL_REVISION}" in text
    assert "path: archive-tooling" in text
    assert "git -C archive-tooling rev-parse HEAD" in text
    assert "Archive tooling revision mismatch" in text
    assert "cocomelon.ops.selection_audit_archive" in text
    assert '--archive-tool-revision "$ARCHIVE_TOOL_REVISION"' in text


def test_archive_workflow_checks_final_and_existing_archive_before_source_corpus() -> None:
    text = _text()

    assert STATE_BRANCH in text
    assert FINAL_FILE in text
    assert ARCHIVE_FILE in text
    assert "Inspect durable Phase 9 final and audit archive state" in text
    state_check = text.index("Inspect durable Phase 9 final and audit archive state")
    corpus_fetch = text.index("Fetch exact finalizing curator corpus")
    assert state_check < corpus_fetch
    assert "final_exists=false" in text
    assert "archive_exists=true" in text
    assert "phase9-final-history.json" in text
    assert "Phase 9 final state was previously recorded but is now missing" in text
    assert "phase9-archive-history.json" in text
    assert "Phase 9 selection audit archive was previously recorded but is now missing" in text


def test_archive_workflow_requires_exact_triggering_curator_corpus_when_unarchived() -> None:
    text = _text()

    assert "SOURCE_CURATOR_RUN_ID: ${{ github.event.workflow_run.id }}" in text
    assert "SOURCE_CURATOR_CONCLUSION: ${{ github.event.workflow_run.conclusion }}" in text
    artifacts_endpoint = (
        '"repos/$GITHUB_REPOSITORY/actions/runs/'
        '$SOURCE_CURATOR_RUN_ID/artifacts?per_page=100"'
    )
    assert artifacts_endpoint in text
    assert 'item.get("name") == "v2-mainnet-corpus"' in text
    assert "Finalized Phase 9 run does not contain exactly one current corpus artifact" in text
    assert '"repos/$GITHUB_REPOSITORY/actions/artifacts/$CORPUS_ARTIFACT_ID/zip"' in text
    assert "mainnet-attestation.json" in text
    assert "corpus-index.json" in text


def test_archive_workflow_builds_candidate_before_any_write() -> None:
    text = _text()

    helper = text.index("cocomelon.ops.selection_audit_archive")
    candidate_upload = text.index("Upload durable selection audit archive candidate")
    persist = text.index("persist-archive:")
    assert helper < candidate_upload < persist
    assert "v2-phase9-selection-audit-archive-candidate-${{ github.run_id }}" in text
    assert "retention-days: 7" in text


def test_archive_persistence_is_append_once_and_rechecks_final_id() -> None:
    text = _text()

    assert "phase9_final_id" in text
    assert "archive_id" in text
    assert "Persist append-once Phase 9 selection audit archive" in text
    assert "Durable Phase 9 final changed before archive persistence" in text
    assert "Existing durable selection audit archive_id is invalid" in text
    assert "Durable selection audit archive already exists with identical archive_id" in text
    assert "Refusing to replace existing durable selection audit archive" in text
    assert "Persisted selection audit archive does not match candidate" in text
    assert '-f branch="$PHASE9_STATE_BRANCH"' in text


def test_archive_workflow_is_offline_audit_plumbing_only() -> None:
    text = _text().lower()

    assert "api.hyperliquid.xyz" not in text
    assert "wss://" not in text
    assert "testnet" not in text
    assert "execution_mode: live" not in text
    assert "record-mainnet-evidence" not in text
    assert "run-baseline-replay" not in text
    assert "evaluate-phase9-v2" not in text
    assert "net_r" not in text
    assert "pnl" not in text
