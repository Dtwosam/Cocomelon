# Single-Capture Research Fan-Out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse one authenticated daily research mainnet capture for the canonical root candidate plus at most one explicitly registered challenger, while keeping candidate economics/provenance independent and preserving all V4 isolation, daily-capture, promotion, and live-order gates.

**Architecture:** Split trusted observation preparation from candidate replay materialization. The capture stage validates the recording once and writes a candidate-neutral `capture-source.json`; each candidate later freezes its own replay bundle from that unchanged recording and its immutable registry execution config. Candidate evaluation is serialized against the authoritative registry so each candidate re-bases latest state before touching/evaluating the shared interval, preventing lost updates while allowing the challenger to fail without invalidating the root candidate.

**Tech Stack:** Python 3.12, SQLite, GitHub Actions, pytest, Ruff, mypy, Docker-isolated strategy worker.

**Spec:** `docs/superpowers/specs/2026-08-31-dual-lane-sequential-research-design.md`

## Global Constraints

- Research remains permanently **TOUCHED / NON-PROMOTIONAL**.
- Locked rule: **candidates may fail fast; candidates may not succeed fast.**
- Keep exactly one scheduled research observation capture attempt per eligible UTC day; fan-out must not invoke `record-mainnet-evidence` more than once.
- Research observations must remain disjoint from every actual protected V4 acquisition interval while V4 is blind.
- Preserve the existing post-capture authoritative V4 synchronization and fail closed if completeness through the shared research interval cannot be proven.
- Root candidate remains `RESEARCH_CANDIDATE_ID` with fallback `scheduled-research-root`.
- Optional challenger is explicitly configured through `RESEARCH_CHALLENGER_CANDIDATE_ID`; empty means root-only behavior.
- Fan-out cardinality is capped at two candidates: root plus one distinct challenger.
- Every evaluated candidate must already exist in the authoritative research registry and keep immutable candidate ID, family/lineage, code revision, config digest, execution config, and risk config.
- Candidate build/runtime must not receive authoritative registry contents or GitHub Actions credentials.
- Candidate strategy execution remains Docker-isolated with `--network none`, read-only root filesystem, all capabilities dropped, and no-new-privileges.
- Candidate replay/evaluation uses paper execution only and must finish flat, complete, and gap-free.
- Shared source contributes at most one UTC research day per candidate; sharing observations never creates extra capture days.
- Challenger failure must remain auditable but must not discard, retry, or invalidate a successful root checkpoint.
- No touched research artifact may enter `v4-mainnet-corpus`, advance Phase 10, establish verified edge, or enable live orders.
- No Hyperliquid testnet.

---

### Task 1: Candidate-neutral capture source contract

**Files:**
- Modify: `src/cocomelon/research/cohort.py`
- Create: `tests/test_research_capture_source_fanout.py`

**Interfaces:**
- Produces: `prepare_research_capture_source(recording_root, output_root, *, trigger_head_sha) -> ResearchCaptureSourceResult`
- Produces: `materialize_research_candidate_source(recording_root, output_root, *, capture_source_path, candidate) -> ResearchCohortSourceResult`
- Preserves: `prepare_research_cohort_source(...)` as a compatibility wrapper for existing tests/tools.

- [ ] **Step 1: Write failing tests for candidate-neutral source preparation**

```python
def test_capture_source_has_no_candidate_config_and_is_stable_across_candidates(...):
    source = prepare_research_capture_source(...)
    payload = json.loads((output_root / "capture-source.json").read_text())
    assert "config_digest" not in payload
    assert "candidate_id" not in payload
    assert payload["recording_session_digest"] == source.recording_session_digest
    assert payload["source_set_digest"] == source.source_set_digest
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pytest tests/test_research_capture_source_fanout.py -q`

Expected: fail because the new capture-source API does not exist.

- [ ] **Step 3: Implement minimal neutral source preparation**

Validate the recording and transport exactly once, persist canonical `record.json`, derive the recording interval/session/source-set digests without persisting any candidate replay config, and write `capture-source.json` atomically.

- [ ] **Step 4: Add failing candidate materialization tests**

```python
def test_two_candidates_materialize_from_identical_source_with_distinct_configs(...):
    root = materialize_research_candidate_source(..., candidate=root_candidate)
    challenger = materialize_research_candidate_source(..., candidate=challenger_candidate)
    assert root.recording_session_digest == challenger.recording_session_digest
    assert root.source_set_digest == challenger.source_set_digest
    assert load_baseline_replay_bundle(root_output / "bundle.json").replay_config.config_digest != load_baseline_replay_bundle(challenger_output / "bundle.json").replay_config.config_digest
```

- [ ] **Step 5: Run RED, implement materialization, then run GREEN**

Materialization must revalidate the recording against `capture-source.json`, load the candidate execution config through `research_replay_config_from_candidate`, freeze `bundle.json`, write `freeze.json`, and reject any interval/session/source-set mismatch.

Run: `pytest tests/test_research_capture_source_fanout.py tests/test_research_candidate_execution_binding.py -q`

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/cocomelon/research/cohort.py tests/test_research_capture_source_fanout.py
git commit -m "feat: separate research capture source from candidate replay"
```

### Task 2: Deterministic fan-out candidate contract

**Files:**
- Create: `src/cocomelon/research/fanout.py`
- Create: `tests/test_research_fanout.py`

**Interfaces:**
- Produces: `ResearchFanoutCandidate` with `candidate_id`, `code_revision`, `attempt_id`, `batch_id`, `source_id`, and `required`.
- Produces: `resolve_research_fanout(registry, *, root_candidate_id, challenger_candidate_id, run_id, run_attempt) -> tuple[ResearchFanoutCandidate, ...]`.

- [ ] **Step 1: Write RED tests**

Cover root-only fallback, root+challenger ordering, duplicate candidate rejection, missing challenger rejection, invalid revision rejection, and exact per-candidate attempt/batch identities.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_research_fanout.py -q`

- [ ] **Step 3: Implement minimal resolver**

Return root first with `required=True`; optional challenger second with `required=False`. Reject more than one challenger by construction and reject `challenger == root`. Load both candidate manifests from the authoritative registry and preserve their immutable revisions.

- [ ] **Step 4: Verify GREEN and commit**

Run: `pytest tests/test_research_fanout.py -q`

```bash
git add src/cocomelon/research/fanout.py tests/test_research_fanout.py
git commit -m "feat: resolve bounded research candidate fanout"
```

### Task 3: Workflow fan-out over one capture

**Files:**
- Modify: `.github/workflows/research-campaign-scheduled.yml`
- Modify: `tests/test_research_runner_workflow.py`
- Modify: `tests/test_research_observation_trust.py`
- Create: `tests/test_research_single_capture_fanout_workflow.py`

**Interfaces:**
- `prepare-control` emits a compact JSON matrix for one or two registered candidates.
- `candidate-build` builds one frozen image per candidate before capture.
- `capture-control` invokes `record-mainnet-evidence` exactly once and writes only the neutral source contract.
- `refresh-authority` proves the one shared interval is covered and V4-disjoint, but does not attach candidate economics.
- `evaluate-research` is a matrix with `max-parallel: 1`; each matrix entry re-bases latest authoritative state, records that candidate's touch, materializes its replay bundle, runs its frozen image, completes replay, evaluates the candidate-specific attempt, and publishes the updated registry.

- [ ] **Step 1: Write RED workflow assertions**

Require:

```python
assert source.count("record-mainnet-evidence") == 1
assert "RESEARCH_CHALLENGER_CANDIDATE_ID" in source
assert "max-parallel: 1" in evaluation
assert "capture-source.json" in capture
assert "materialize_research_candidate_source" in evaluation
assert "continue-on-error: ${{ !matrix.required }}" in evaluation
assert "--network none" in evaluation
```

Also assert candidate build/evaluation artifacts are namespaced by candidate ID and that no candidate job receives `GH_TOKEN` or the authoritative SQLite registry before trusted evaluation control owns it.

- [ ] **Step 2: Run workflow tests and verify RED**

Run: `pytest tests/test_research_single_capture_fanout_workflow.py tests/test_research_runner_workflow.py tests/test_research_observation_trust.py -q`

- [ ] **Step 3: Wire root+optional-challenger fan-out**

Use `RESEARCH_CHALLENGER_CANDIDATE_ID: ${{ vars.RESEARCH_CHALLENGER_CANDIDATE_ID }}`. Resolve the candidate matrix from the restored registry before candidate code checkout. Persist runner-attempt rows for every fan-out candidate before any candidate build. Build all candidate images before the recorder starts. Keep exactly one acquisition attempt and one shared source ID. Use candidate-specific attempt/batch IDs while preserving the shared source ID.

- [ ] **Step 4: Move candidate replay materialization downstream of V4 authority refresh**

The capture job writes `capture-source.json` only. Each serialized evaluation job downloads the same capture artifact and its candidate image, re-bases current authoritative registry state, reasserts V4 disjointness, records the touch for `matrix.candidate_id`, materializes the candidate-specific bundle, executes the strategy sandbox, completes the cohort, and runs `cocomelon-research-runner` with candidate-specific identities.

- [ ] **Step 5: Make challenger failure non-fatal without hiding it**

Set job-level `continue-on-error: ${{ !matrix.required }}`. Always upload candidate-specific evaluated/audit artifacts. The root matrix row remains required. Finalization re-bases the latest authoritative registry artifact and marks any still-running/evaluating attempts failed without downgrading terminal successful attempts.

- [ ] **Step 6: Run GREEN**

Run:

```bash
python -m compileall -q src tests scripts
python -m ruff check src tests scripts
python -m mypy src
python -m pytest tests/test_research_single_capture_fanout_workflow.py tests/test_research_runner_workflow.py tests/test_research_observation_trust.py tests/test_research_capture_source_fanout.py tests/test_research_fanout.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/research-campaign-scheduled.yml tests/test_research_runner_workflow.py tests/test_research_observation_trust.py tests/test_research_single_capture_fanout_workflow.py
git commit -m "feat: fan out one research capture across candidates"
```

### Task 4: Full regression, review, and rollout safety

**Files:**
- Modify only if a test reveals a concrete defect.

- [ ] **Step 1: Run full CI-equivalent verification**

```bash
python -m compileall -q src tests scripts
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
python -m pytest tests/test_replay_compaction.py tests/test_parquet_replay_source.py -q
```

- [ ] **Step 2: Verify diff invariants**

Confirm one recorder invocation, no V4 workflow changes, no live-order capability, no testnet, no weakened overlap/completeness/daily-success gates, and no candidate economics in the neutral source manifest.

- [ ] **Step 3: Open PR and require green PR-context CI**

- [ ] **Step 4: Merge exact reviewed head only after CI is green**

- [ ] **Step 5: Verify post-merge main CI**

Do not manually dispatch research on the same UTC day if a successful research campaign already exists; the existing duplicate-success guard remains authoritative.
