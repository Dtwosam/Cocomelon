from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-corpus-curator.yml")
CAMPAIGN = "Scheduled Genuine Mainnet Evidence Campaign V2"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_curator_is_serialized_read_only_workflow_run_consumer() -> None:
    text = _text()

    assert "workflow_run:" in text
    assert CAMPAIGN in text
    assert "types: [completed]" in text
    assert "actions: read" in text
    assert "contents: read" in text
    assert "group: genuine-mainnet-evidence-v2-corpus" in text
    assert "cancel-in-progress: false" in text
    assert "COCOMELON_EXECUTION_MODE: live" not in text
    assert "testnet" not in text.lower()


def test_curator_verifies_source_before_mutating_corpus() -> None:
    text = _text()

    assert "github.event.workflow_run.id" in text
    assert "github.event.workflow_run.conclusion" in text
    assert "scheduled-genuine-mainnet-evidence-v2-" in text
    assert "source-artifacts.json" in text
    assert "source-artifact.zip" in text
    assert "cocomelon-mainnet-evidence verify" in text
    assert "SOURCE_VERIFY_STATUS" in text
    assert 'SOURCE_CONCLUSION" = "success"' in text
    assert "source_verified" in text


def test_curator_rolls_forward_latest_attested_corpus_idempotently() -> None:
    text = _text()

    assert "v2-mainnet-corpus" in text
    assert "prior-artifacts.json" in text
    assert "prior-corpus.zip" in text
    assert "cocomelon-mainnet-evidence aggregate" in text
    assert "cocomelon-mainnet-evidence progress" in text
    assert "corpus-index.json" in text
    assert "retention-days: 90" in text
    assert "if-no-files-found: error" in text


def test_curator_preserves_rejected_intake_without_corpus_mutation() -> None:
    text = _text()

    assert "v2-mainnet-intake-" in text
    assert "intake-report.json" in text
    assert '"corpus_mutated": False' in text
    assert "if: always()" in text
