from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-corpus-curator-v4.yml")
CAMPAIGN = "Scheduled Genuine Mainnet Evidence Campaign V4"
PINNED_CODE = "0c14c9cfa37c80babc65d050fed6d4465dcb9032"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v4_curator_consumes_only_completed_v4_campaigns() -> None:
    text = _text()
    assert "name: Verified V4 Mainnet Evidence Corpus Curator" in text
    assert "workflow_run:" in text
    assert CAMPAIGN in text
    assert "types: [completed]" in text
    assert "actions: read" in text
    assert "contents: read" in text
    assert "group: genuine-mainnet-evidence-v4-corpus" in text
    assert "cancel-in-progress: false" in text
    assert "COCOMELON_EXECUTION_MODE: live" not in text
    assert "testnet" not in text.lower()


def test_v4_curator_is_pinned_and_verifies_before_mutation() -> None:
    text = _text()
    assert f"ref: {PINNED_CODE}" in text
    assert f"V4_CODE_REVISION: {PINNED_CODE}" in text
    assert "github.event.workflow_run.id" in text
    assert "github.event.workflow_run.conclusion" in text
    assert "scheduled-genuine-mainnet-evidence-v4-" in text
    assert "cocomelon-mainnet-evidence verify" in text
    assert text.index("cocomelon-mainnet-evidence verify") < text.index(
        "mkdir -p corpus/sources/$SOURCE_RUN_ID"
    )


def test_v4_curator_keeps_corpus_isolated_from_v2_v3() -> None:
    text = _text()
    assert "v4-mainnet-corpus" in text
    assert "v4-mainnet-intake-" in text
    assert '"protocol": "v4-thesis-expiry-mainnet"' in text
    assert '"replay_engine_version": "phase8-v3-thesis-expiry"' in text
    assert '"config_version": "phase9-baseline-replay-v3-thesis-expiry"' in text
    assert '"execution_config_version": "phase7-v2-4h-thesis-expiry"' in text
    assert '"entry_window_seconds": 2700' in text
    assert '"capture_window_seconds": 18900' in text
    assert '"max_position_age_seconds": 14400' in text
    assert f'"pinned_code_revision": "{PINNED_CODE}"' in text
    assert "v2-mainnet-corpus" not in text
    assert "v3-mainnet-corpus" not in text


def test_v4_curator_rebuilds_attested_corpus() -> None:
    text = _text()
    assert "cocomelon-mainnet-evidence aggregate" in text
    assert "cocomelon-mainnet-evidence progress" in text
    assert "corpus-index.json" in text
    assert "progress.json" in text
    assert "mainnet-attestation.json" in text
    assert "retention-days: 90" in text
    assert "if-no-files-found: error" in text


def test_v4_curator_rejected_runs_cannot_mutate_corpus() -> None:
    text = _text()
    assert "SOURCE_CONCLUSION: ${{ github.event.workflow_run.conclusion }}" in text
    assert 'if [ "$SOURCE_CONCLUSION" != "success" ]; then' in text
    assert '"corpus_mutated": False' in text
    assert 'echo "corpus_ready=false" >> "$GITHUB_OUTPUT"' in text
    rejected = text.index('if [ "$SOURCE_CONCLUSION" != "success" ]; then')
    mutation = text.index("mkdir -p corpus/sources/$SOURCE_RUN_ID")
    assert rejected < mutation


def test_v4_curator_failed_sources_expose_only_non_economic_diagnostics() -> None:
    text = _text()
    rejected = text.index('if [ "$SOURCE_CONCLUSION" != "success" ]; then')
    exit_rejected = text.index("exit 0", rejected)
    block = text[rejected:exit_rejected]
    assert "eligibility-probe.json" in block
    assert '"diagnostic_status"' in block
    assert '"economic_ineligibility_reasons"' in block
    assert '"replay_data_complete"' in block
    assert '"dataset_data_complete"' in block
    assert '"dataset_gap_refs_empty"' in block
    assert '"flat_replay"' in block
    assert '"network_access": False' in block
    assert '"live_orders": False' in block
    forbidden = (
        "final_equity",
        "realized_pnl",
        "unrealized_pnl",
        "profit_factor",
        "mean_net_r",
        "win_rate",
        "bootstrap",
    )
    lowered = block.lower()
    assert all(field not in lowered for field in forbidden)


def test_v4_curator_binds_prior_corpus_to_exact_trusted_producer() -> None:
    text = _text()
    assert "Verified V4 Mainnet Evidence Corpus Curator" in text
    assert ".github/workflows/evidence-corpus-curator-v4.yml" in text
    assert "TRUSTED_PRIOR_ARTIFACT_ID" in text
    assert "CANDIDATE_RUN_ID" in text
    assert 'repos/$GITHUB_REPOSITORY/actions/runs/$CANDIDATE_RUN_ID' in text
