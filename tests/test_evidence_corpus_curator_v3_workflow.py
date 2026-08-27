from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-corpus-curator-v3.yml")
CAMPAIGN = "Scheduled Genuine Mainnet Evidence Campaign V3"
PINNED_CODE = "f21ad7be581bc662127e75f832cd8fcbf4f5f93b"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v3_curator_consumes_only_completed_v3_campaigns() -> None:
    text = _text()

    assert "name: Verified V3 Mainnet Evidence Corpus Curator" in text
    assert "workflow_run:" in text
    assert CAMPAIGN in text
    assert "types: [completed]" in text
    assert "actions: read" in text
    assert "contents: read" in text
    assert "group: genuine-mainnet-evidence-v3-corpus" in text
    assert "cancel-in-progress: false" in text
    assert "COCOMELON_EXECUTION_MODE: live" not in text
    assert "testnet" not in text.lower()


def test_v3_curator_is_pinned_and_verifies_before_corpus_mutation() -> None:
    text = _text()

    assert f"ref: {PINNED_CODE}" in text
    assert "github.event.workflow_run.id" in text
    assert "github.event.workflow_run.conclusion" in text
    assert "scheduled-genuine-mainnet-evidence-v3-" in text
    assert "source-artifact.zip" in text
    assert "cocomelon-mainnet-evidence verify" in text
    verify = text.index("cocomelon-mainnet-evidence verify")
    mutation = text.index("mkdir -p corpus/sources/$SOURCE_RUN_ID")
    assert verify < mutation


def test_v3_curator_keeps_v3_corpus_isolated_from_v2() -> None:
    text = _text()

    assert "v3-mainnet-corpus" in text
    assert "v3-mainnet-intake-" in text
    assert '"protocol": "v3-lifecycle-aware-mainnet"' in text
    assert '"replay_engine_version": "phase8-v2-lifecycle-aware"' in text
    assert '"entry_window_seconds": 2700' in text
    assert '"capture_window_seconds": 5400' in text
    assert "v2-mainnet-corpus" not in text
    assert "prepare-phase9-v2" not in text
    assert "evaluate-phase9-v2" not in text


def test_v3_curator_rebuilds_aggregate_from_attested_sources() -> None:
    text = _text()

    assert "cocomelon-mainnet-evidence aggregate" in text
    assert "cocomelon-mainnet-evidence progress" in text
    assert "corpus-index.json" in text
    assert "progress.json" in text
    assert "mainnet-attestation.json" in text
    assert "retention-days: 90" in text
    assert "if-no-files-found: error" in text


def test_v3_curator_rejected_runs_cannot_mutate_corpus() -> None:
    text = _text()

    assert "SOURCE_CONCLUSION: ${{ github.event.workflow_run.conclusion }}" in text
    assert 'if [ "$SOURCE_CONCLUSION" != "success" ]; then' in text
    assert '"corpus_mutated": False' in text
    assert "exit 0" in text
    rejected = text.index('if [ "$SOURCE_CONCLUSION" != "success" ]; then')
    mutation = text.index("mkdir -p corpus/sources/$SOURCE_RUN_ID")
    assert rejected < mutation


def test_v3_curator_binds_prior_corpus_to_trusted_curator_producer() -> None:
    text = _text()

    assert "Verified V3 Mainnet Evidence Corpus Curator" in text
    assert ".github/workflows/evidence-corpus-curator-v3.yml" in text
    assert "TRUSTED_PRIOR_ARTIFACT_ID" in text
    assert "CANDIDATE_RUN_ID" in text
    assert 'repos/$GITHUB_REPOSITORY/actions/runs/$CANDIDATE_RUN_ID' in text
