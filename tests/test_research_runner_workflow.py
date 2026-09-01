from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_research_campaign_is_separate_paper_only_and_offset_from_v4() -> None:
    source = _source()
    lowered = source.lower()

    assert "name: Scheduled Research Mainnet Replay Campaign" in source
    assert 'cron: "2 7 * * *"' in source
    assert 'cron: "37 1,7,13,19 * * *"' not in source
    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "cancel-in-progress: false" in source
    assert "record-mainnet-evidence" in source
    assert "from cocomelon.research.cohort import build_research_cohort" in source
    assert "cocomelon-research-runner run-artifact" in source
    assert "research-authoritative-registry" in source

    for forbidden in (
        "evidence-campaign-v4-scheduled",
        "v4-mainnet-corpus",
        "evidence_corpus_curator",
        "phase9_v4_one_shot",
        "candidate_edge",
        "private_key",
        "wallet",
        "withdraw",
        "transfer",
        "send_order",
        "live_order",
    ):
        assert forbidden not in lowered


def test_research_campaign_pins_runtime_to_candidate_code_revision() -> None:
    source = _source()

    assert "Resolve candidate code revision from authoritative registry" in source
    assert "SELECT code_revision FROM research_candidates WHERE candidate_id = ?" in source
    assert 'RESEARCH_CODE_REVISION=' in source
    assert "Checkout candidate code revision" in source
    assert "ref: ${{ env.RESEARCH_CODE_REVISION }}" in source
    assert source.index("Checkout candidate code revision") < source.index("Install Cocomelon")
    assert source.index("Install Cocomelon") < source.index("record-mainnet-evidence")


def test_candidate_checkout_preserves_restored_authoritative_registry() -> None:
    source = _source()
    checkout = source.split("- name: Checkout candidate code revision", 1)[1].split(
        "- name: Install Cocomelon",
        1,
    )[0]

    assert "clean: false" in checkout
    assert "clean: true" not in checkout
    assert source.index("Restore authoritative research registry") < source.index(
        "Checkout candidate code revision"
    )


def test_research_campaign_uses_one_outcome_blind_acquisition_identity() -> None:
    source = _source()
    lowered = source.lower()

    assert source.count("record-mainnet-evidence") == 1
    assert source.count("acquisition-attempt.txt") == 1
    assert "GITHUB_RUN_ID" in source
    assert "GITHUB_RUN_ATTEMPT" in source
    assert "record_runner_attempt_started" in source
    assert "finish_runner_attempt" in source

    for economic_branch in (
        "net_pnl",
        "mean_net_r",
        "posterior_probability",
        "profitable",
        "profitability",
        "pnl >",
        "pnl <",
    ):
        assert economic_branch not in lowered


def test_research_campaign_publishes_audit_state_on_failure() -> None:
    source = _source()

    assert "if: ${{ always() }}" in source
    assert "path: research-campaign/" in source
    assert "research-campaign/state/research.sqlite3" in source
    assert "research-campaign/output/" in source
    assert "research-campaign/diagnostics/" in source
    assert "if-no-files-found: error" in source
    assert "authoritative-registry-unavailable.txt" in source


def test_research_campaign_never_synthesizes_v4_completeness_from_schedule() -> None:
    source = _source()
    lowered = source.lower()

    assert "mark_v4_registry_complete_through" not in source
    assert "record_v4_interval" not in source
    assert "v4 registry completeness" in lowered
    assert "nominal" not in lowered
