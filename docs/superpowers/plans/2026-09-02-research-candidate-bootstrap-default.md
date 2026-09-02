# Research Candidate Bootstrap Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the scheduled research authority sync and campaign start safely when the optional `RESEARCH_CANDIDATE_ID` repository variable is unset.

**Architecture:** Keep the repository variable as an override, but give both trusted research workflows the canonical bootstrap identity `scheduled-research-root` as an expression-level fallback. This changes only research bootstrap configuration; it does not alter V4 strategy, risk, acquisition timing, replay economics, promotion rules, or live-trading state.

**Tech Stack:** GitHub Actions YAML, pytest workflow-source regression tests.

**Spec:** `docs/superpowers/specs/2026-08-31-dual-lane-sequential-research-design.md`

## Global Constraints

- Frozen V4 strategy/risk/execution/curator/corpus/one-shot economics behavior must not change.
- Research remains paper/shadow only and permanently `TOUCHED / NON-PROMOTIONAL`.
- No wallet, private-key, transfer, withdrawal, testnet, or live-order capability is introduced.
- Preserve `RESEARCH_CANDIDATE_ID` as an operator override.
- Canonical fallback candidate ID is `scheduled-research-root`, matching the existing bootstrap tests.

---

### Task 1: Default the research bootstrap candidate safely

**Files:**
- Create: `tests/test_research_candidate_workflow_defaults.py`
- Modify: `.github/workflows/research-v4-registry-sync.yml`
- Modify: `.github/workflows/research-campaign-scheduled.yml`

**Interfaces:**
- Consumes: GitHub Actions repository variable `vars.RESEARCH_CANDIDATE_ID` when configured.
- Produces: workflow environment `RESEARCH_CANDIDATE_ID` that always resolves to a non-empty canonical candidate identity.

- [ ] **Step 1: Write the failing regression test**

```python
from pathlib import Path

CAMPAIGN = Path(".github/workflows/research-campaign-scheduled.yml")
SYNC = Path(".github/workflows/research-v4-registry-sync.yml")
EXPECTED = "RESEARCH_CANDIDATE_ID: ${{ vars.RESEARCH_CANDIDATE_ID || 'scheduled-research-root' }}"


def test_research_workflows_default_to_canonical_bootstrap_candidate() -> None:
    assert EXPECTED in CAMPAIGN.read_text(encoding="utf-8")
    assert EXPECTED in SYNC.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run CI to verify RED**

Run the pull-request CI for the test-only commit.

Expected: the new test fails because both workflows currently use `${{ vars.RESEARCH_CANDIDATE_ID }}` without a fallback.

- [ ] **Step 3: Implement the minimal workflow change**

In both workflow-level `env:` blocks, replace:

```yaml
RESEARCH_CANDIDATE_ID: ${{ vars.RESEARCH_CANDIDATE_ID }}
```

with:

```yaml
RESEARCH_CANDIDATE_ID: ${{ vars.RESEARCH_CANDIDATE_ID || 'scheduled-research-root' }}
```

Update any existing source-level regression assertion that intentionally pins the old expression so it expects the fallback form.

- [ ] **Step 4: Run CI to verify GREEN**

Expected: research tests and full CI pass with no V4 behavioral changes.

- [ ] **Step 5: Merge and operationally verify**

Merge the exact tested head, rerun the failed `Research V4 Acquisition Authority Sync`, verify that it publishes `research-authoritative-registry`, and confirm the Research Dashboard can consume the resulting trusted registry.
