from pathlib import Path

CAMPAIGN = Path(".github/workflows/research-campaign-scheduled.yml")
SYNC = Path(".github/workflows/research-v4-registry-sync.yml")
EXPECTED = "RESEARCH_CANDIDATE_ID: ${{ vars.RESEARCH_CANDIDATE_ID || 'scheduled-research-root' }}"


def test_research_workflows_default_to_canonical_bootstrap_candidate() -> None:
    assert EXPECTED in CAMPAIGN.read_text(encoding="utf-8")
    assert EXPECTED in SYNC.read_text(encoding="utf-8")


def test_research_campaign_defaults_to_r2_entry_quality_challenger() -> None:
    source = CAMPAIGN.read_text(encoding="utf-8")
    expected = (
        "RESEARCH_CHALLENGER_CANDIDATE_ID: "
        "${{ vars.RESEARCH_R2_CHALLENGER_CANDIDATE_ID || 'research-r2-entry-quality-v1' }}"
    )
    assert expected in source
