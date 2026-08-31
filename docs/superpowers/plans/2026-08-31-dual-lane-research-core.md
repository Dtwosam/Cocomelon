# Dual-Lane Research Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the persistent, deterministic core that lets Cocomelon reject weak research candidates quickly without contaminating the frozen V4 promotion experiment.

**Architecture:** Add a focused `cocomelon.research` package rather than modifying the frozen V4 evaluator. The package owns candidate lineage/touched intervals, a SQLite control registry, V4 source-window contamination guards, a deterministic Bayesian sequential triage engine, checkpoint reporting, and frozen-challenger cutover validation. Existing evaluation/trade-domain types remain authoritative for trade economics.

**Tech Stack:** Python 3.12 stdlib (`dataclasses`, `enum`, `hashlib`, `json`, `math`, `random`, `sqlite3`), existing Cocomelon domain/evaluation types, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-31-dual-lane-sequential-research-design.md`

## Global Constraints

- Active V4 strategy, risk, execution, schedule, curator, corpus, evaluator, and performance blindness remain unchanged.
- Research economics cannot consume source intervals intersecting any actual V4 acquisition interval while V4 is blind.
- Candidate descendants inherit the normalized union of every ancestor touched interval.
- Economic futility cannot fire before 20 closed trades.
- `RESEARCH_PROMISING` requires at least 40 closed trades, 7 distinct UTC closed-trade days, and `P(mu > 0 | observations) >= 0.80`.
- Futility uses `StudentT(nu=5, loc=mu, scale=sigma)`, `mu ~ Normal(0, 0.5)`, `sigma ~ HalfNormal(1.0)`, with deterministic fixed-seed posterior estimation.
- Clean validation must begin after candidate freeze and at least 6 hours after the latest inherited touched interval.
- Research remains paper/shadow only; no live-order path is added.
- No new third-party dependency is required for the core.

---

### Task 1: Research contracts and interval algebra

**Files:**
- Create: `src/cocomelon/research/__init__.py`
- Create: `src/cocomelon/research/contracts.py`
- Test: `tests/test_research_contracts.py`

**Interfaces:**
- Produces `TimeInterval`, `ResearchCandidateState`, `ResearchCheckpointState`, `ResearchCandidateManifest`, `ResearchBatch`, `normalize_intervals()`, `intervals_overlap()`, and `validation_cutover_allowed()`.

- [ ] **Step 1: Write failing contract tests**

Cover canonical interval normalization, overlap semantics (`[start,end)`), immutable candidate identity validation, same-family parent/ancestor requirements, and the 6-hour validation embargo.

```python
from cocomelon.research.contracts import TimeInterval, normalize_intervals


def test_normalize_intervals_merges_touching_ranges() -> None:
    assert normalize_intervals((TimeInterval(10, 20), TimeInterval(20, 30))) == (
        TimeInterval(10, 30),
    )
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_research_contracts.py -q`
Expected: FAIL because `cocomelon.research.contracts` does not exist.

- [ ] **Step 3: Implement minimal immutable contracts**

`TimeInterval` validates `0 <= start_ms < end_ms` and uses half-open overlap. Candidate manifests require non-empty IDs/digests/revisions, parent `None` only for a root, and ordered unique ancestors. `validation_cutover_allowed()` returns false unless validation starts after freeze and `latest_touched_end_ms + 21_600_000`.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_research_contracts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -am "feat: add research candidate contracts"`

---

### Task 2: Persistent research/V4 interval registry

**Files:**
- Create: `src/cocomelon/research/registry.py`
- Test: `tests/test_research_registry.py`

**Interfaces:**
- Consumes Task 1 contracts.
- Produces `ResearchRegistry(path)`, `create_candidate()`, `record_v4_interval()`, `record_batch()`, `effective_touched_intervals()`, `assert_batch_disjoint_from_v4()`, `mark_candidate_terminal()`, and `freeze_candidate()`.

- [ ] **Step 1: Write failing persistence/lineage tests**

Tests must prove:
- child effective touched intervals include parent + grandparent intervals;
- cross-family parents and cycles fail closed;
- a research interval intersecting any registered V4 interval raises `ResearchContaminationError`;
- disjoint intervals are accepted;
- terminal candidate state cannot be reset by deleting/omitting observations;
- frozen challenger cutover enforces inherited touched intervals + 6-hour embargo.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_research_registry.py -q`
Expected: FAIL because registry is absent.

- [ ] **Step 3: Implement SQLite schema and transactions**

Use SQLite control tables for `candidates`, `touched_intervals`, `v4_intervals`, `research_batches`, and `candidate_state_events`. Enable foreign keys. Candidate creation is append-only by ID; terminal state events cannot transition back to researching. Interval reads return canonical normalized unions.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_research_registry.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -am "feat: persist research lineage and contamination state"`

---

### Task 3: Deterministic Bayesian sequential triage

**Files:**
- Create: `src/cocomelon/research/sequential.py`
- Test: `tests/test_research_sequential.py`

**Interfaces:**
- Produces `SequentialResearchPolicy`, `posterior_probability_positive(net_r_values) -> Decimal`, and `evaluate_checkpoint(...) -> ResearchCheckpoint`.

- [ ] **Step 1: Write failing statistical-state tests**

Tests must prove:
- no economic decision before 20 trades;
- strongly negative samples cross the `< 0.05` futility threshold;
- positive samples cannot become promising before 40 trades or 7 days;
- sufficiently positive 40+ trade / 7+ day samples can become `RESEARCH_PROMISING`;
- identical ordered observations produce bit-for-bit identical posterior output;
- hard risk/integrity failure overrides economic state.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_research_sequential.py -q`
Expected: FAIL because sequential engine is absent.

- [ ] **Step 3: Implement fixed-seed importance sampling**

Use only stdlib. Draw a fixed number of prior samples from `mu ~ Normal(0, 0.5)` and `sigma ~ HalfNormal(1.0)` with a constant seed. Weight each sample by the Student-t (`nu=5`) log-likelihood of ordered net-R observations, normalize with log-sum-exp, and return the posterior probability mass with `mu > 0` as a quantized `Decimal`. Constants live in `SequentialResearchPolicy` and are part of its deterministic policy digest.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_research_sequential.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -am "feat: add deterministic sequential research triage"`

---

### Task 4: Research checkpoint evaluator and reporting

**Files:**
- Create: `src/cocomelon/research/evaluator.py`
- Test: `tests/test_research_evaluator.py`

**Interfaces:**
- Consumes `TradeEvaluationSample` from `cocomelon.domain.evaluation`, registry state, and Task 3 policy.
- Produces `ResearchCheckpointReport` and `evaluate_research_checkpoint()`.

- [ ] **Step 1: Write failing report tests**

Construct `TradeEvaluationSample` fixtures and verify reports include candidate/provenance identity, closed-trade counts/days, net PnL, mean net R, fees, funding, slippage, long/short counts, market concentration, checkpoint state, and the explicit label `TOUCHED / NON-PROMOTIONAL`.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_research_evaluator.py -q`
Expected: FAIL because evaluator is absent.

- [ ] **Step 3: Implement evaluator**

Before any economics are computed, call the registry contamination guard for every research batch. Aggregate only admitted touched samples. Use the sequential engine for state. Reports must not contain any V4 corpus/evaluator mutation capability.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_research_evaluator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -am "feat: evaluate touched research checkpoints"`

---

### Task 5: Research CLI and challenger freeze boundary

**Files:**
- Create: `src/cocomelon/research_cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_research_cli.py`

**Interfaces:**
- Adds console entry point `cocomelon-research = "cocomelon.research_cli:main"`.
- Commands: `init-registry`, `register-v4-interval`, `create-candidate`, `record-batch`, `checkpoint`, `freeze-candidate`, `validate-cutover`.

- [ ] **Step 1: Write failing CLI tests**

Verify JSON-only deterministic output, non-zero exits for contamination/invalid lineage/invalid cutover, and no live-related command or flag exists.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_research_cli.py -q`
Expected: FAIL because CLI is absent.

- [ ] **Step 3: Implement CLI**

Use `argparse`; all writes go through `ResearchRegistry`. `checkpoint` reads a JSON dataset of canonical research trade samples and emits one report. `freeze-candidate` persists immutable freeze metadata; `validate-cutover` checks the inherited touched set and embargo.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_research_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -am "feat: expose isolated research control CLI"`

---

### Task 6: Cross-lane isolation regression suite

**Files:**
- Create: `tests/test_dual_lane_isolation.py`

**Interfaces:**
- Integration-only; no new production API.

- [ ] **Step 1: Write integration tests**

Prove:
- V4-overlapping intervals cannot produce research economics;
- failed/diagnostic V4 intervals count for overlap blocking;
- descendant touched history survives multiple candidate generations;
- positive research state cannot produce `EdgeEvidenceStatus.CANDIDATE_EDGE`;
- no research module imports V4 corpus curator mutation functions;
- `live_orders` is never introduced by research APIs.

- [ ] **Step 2: Run targeted integration suite**

Run: `python -m pytest tests/test_dual_lane_isolation.py -q`
Expected: PASS.

- [ ] **Step 3: Run full verification**

Run:
- `python -m compileall -q src tests scripts`
- `python -m ruff check src tests scripts`
- `python -m mypy src`
- `python -m pytest -q`

Expected: all commands exit 0.

- [ ] **Step 4: Commit**

`git commit -am "test: prove dual-lane isolation invariants"`

---

## Follow-up implementation slice

After this core merges, create a separate plan/PR for:

1. automated ingestion of authoritative V4 acquisition intervals from trusted campaign provenance;
2. a research-only source/replay runner that selects only allowed pre-V4 or provably disjoint source periods;
3. durable research-registry artifact curation across GitHub Actions runs;
4. a separate research dashboard labeled `TOUCHED / NON-PROMOTIONAL`;
5. scheduled daily research checkpoints that never compete with or mutate V4.

This split keeps the first PR small enough to review and proves the safety/statistical core before automation can consume it.
