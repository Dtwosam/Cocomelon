from pathlib import Path

CAMPAIGN = Path(".github/workflows/research-campaign-scheduled.yml")
SYNC = Path(".github/workflows/research-v4-registry-sync.yml")
EXPECTED = "RESEARCH_CANDIDATE_ID: ${{ vars.RESEARCH_CANDIDATE_ID || 'scheduled-research-root' }}"


def test_research_workflows_default_to_canonical_bootstrap_candidate() -> None:
    assert EXPECTED in CAMPAIGN.read_text(encoding="utf-8")
    assert EXPECTED in SYNC.read_text(encoding="utf-8")
