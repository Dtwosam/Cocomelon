from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-corpus-curator.yml")
CAMPAIGN = "Scheduled Genuine Mainnet Evidence Campaign V2"
SELECTION_AUDIT_INTRO_SHA = "70e51d1e897cdafa236dc4ef06787939d2b726b4"
LEDGER_REVISION = "2a9f01d86218dca98d2d84a4ae0e2e28c69975a7"


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
    assert "max(matches" in text
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


def test_reused_global_artifacts_are_bound_to_trusted_curator_run_provenance() -> None:
    text = _text()

    assert "ranked_artifact_candidates" in text
    assert "trusted_curator_run" in text
    assert '"repos/$GITHUB_REPOSITORY/actions/runs/$CANDIDATE_RUN_ID"' in text
    for name in (
        "v2-mainnet-corpus",
        "v2-phase9-evaluation",
        "v2-phase9-frozen-snapshot",
        "v2-phase9-terminal-insufficient",
    ):
        assert name in text
    assert "workflow_run" in text


def test_curator_can_skip_newer_untrusted_artifact_for_older_trusted_candidate() -> None:
    text = _text()

    assert "for CANDIDATE in" in text
    assert "continue" in text
    assert "TRUSTED_ARTIFACT_ID" in text
    assert "TRUSTED_RUN_ID" in text


def test_curator_requires_selection_audit_for_post_introduction_campaigns() -> None:
    text = _text()

    assert f"SELECTION_AUDIT_INTRO_SHA: {SELECTION_AUDIT_INTRO_SHA}" in text
    assert f"EXPECTED_ATTEMPT_LEDGER_REVISION: {LEDGER_REVISION}" in text
    assert 'compare/$SELECTION_AUDIT_INTRO_SHA...$TRIGGER_SHA' in text
    assert "selection_audit_required" in text
    assert "legacy_pre_selection_audit" in text
    assert "cocomelon.ops.selection_audit" in text
    verify = text.index("cocomelon-mainnet-evidence verify")
    selection = text.index("cocomelon.ops.selection_audit")
    aggregate = text.index("cocomelon-mainnet-evidence aggregate")
    assert verify < selection < aggregate


def test_curator_rolls_verified_selection_audit_into_corpus() -> None:
    text = _text()

    assert "selection-audit.json" in text
    assert 'corpus/selection-audits/$SOURCE_RUN_ID.json' in text
    assert '"selection_audit_id"' in text
    assert '"selection_audit_count"' in text
    assert '"selection_audit_required"' in text
    assert '"selection_audit_verified"' in text
    assert "refusing conflicting selection audit" in text.lower()
