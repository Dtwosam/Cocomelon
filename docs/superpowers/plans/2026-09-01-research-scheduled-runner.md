# Scheduled Research Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable, scheduled research-only runner that processes genuine mainnet replay cohorts through the existing authenticated research evaluator while failing closed on incomplete V4 interval provenance and preserving every failed attempt.

**Architecture:** Keep all research economics in the existing `evaluate_research_checkpoint()` path. Add a small runner layer that verifies an authoritative genuine-mainnet cohort, derives the **actual** replay interval from that artifact, checks candidate/code/config identity plus V4 registry completeness before releasing economics, records an immutable attempt ledger, and invokes the canonical evaluator exactly once. A dedicated runner CLI and GitHub Actions workflow orchestrate research-only acquisition/replay/checkpointing without importing or mutating V4 corpus/curator/one-shot code.

**Tech Stack:** Python 3.12 stdlib (`argparse`, `dataclasses`, `hashlib`, `json`, `sqlite3`, `pathlib`), existing Cocomelon evidence/replay/research modules, GitHub Actions, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-31-dual-lane-sequential-research-design.md`

## Global Constraints

- Frozen V4 strategy, risk, execution, acquisition schedule, curator, corpus, one-shot evaluator, and performance blindness remain unchanged.
- Before V4 is terminal, research economics require source intervals provably disjoint from every actual V4 acquisition session and an authoritative V4 completeness watermark through the research interval.
- Scheduler drift is governed by actual recorded/replay timestamps, never nominal cron windows.
- Research output is always **TOUCHED / NON-PROMOTIONAL** and cannot produce `CANDIDATE_EDGE` or advance Phase 10.
- Research remains paper/shadow only; `live_orders` must remain false and no private-key/wallet/order-sending surface is added.
- A transport/infrastructure retry must use a new attempt/batch identity; failed attempts remain durable. Economic losses never authorize retry or deletion.
- The runner composes existing genuine-mainnet cohort verification and `evaluate_research_checkpoint()`; it does not duplicate economic calculations.

---

### Task 1: Durable research runner attempt ledger

**Files:**
- Create: `src/cocomelon/research/runner_history.py`
- Test: `tests/test_research_runner_history.py`

**Interfaces:**
- Produces `ResearchRunnerAttempt`, `record_runner_attempt_started()`, `finish_runner_attempt()`, and `load_runner_attempts()`.
- Attempt identity fields: `attempt_id`, `candidate_id`, `batch_id`, `source_id`, `artifact_root`, optional actual `start_ms`/`end_ms`, `status`, optional `report_id`, optional `error_type`/`error_message`.

- [ ] **Step 1: Write failing ledger tests**

Prove start rows are append-only, a completed row cannot be rewritten to a different result, failed rows remain queryable, and a retry requires a distinct `attempt_id` and `batch_id`.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_research_runner_history.py -q`
Expected: FAIL because `cocomelon.research.runner_history` does not exist.

- [ ] **Step 3: Implement minimal SQLite ledger**

Create `research_runner_attempts` lazily on the research registry connection. Use immutable identity columns plus one terminal update from `running` to `succeeded`, `failed`, or `contaminated`. Reject any duplicate identity with different content and reject terminal rewrites.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_research_runner_history.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: persist research runner attempts`.

---

### Task 2: Artifact-authoritative one-shot runner

**Files:**
- Create: `src/cocomelon/research/runner.py`
- Test: `tests/test_research_runner.py`

**Interfaces:**
- Produces `ResearchRunnerRequest(attempt_id, candidate_id, batch_id, source_id, artifact_root)` and `run_research_artifact_attempt(registry, request) -> ResearchRunnerResult`.
- Consumes `verify_research_batch_artifact()` and `evaluate_research_checkpoint()`.

- [ ] **Step 1: Write failing orchestration tests**

Use the genuine research-artifact test helper to prove:
- actual artifact interval, not caller/cron time, is used for V4 disjointness;
- V4 completeness must extend through artifact `end_ms` before economics are evaluated;
- overlapping actual V4 interval records a `contaminated` attempt and transitions via the canonical evaluator path;
- candidate `code_revision` and `config_digest` must match the verified artifact before checkpoint release;
- successful attempt stores the returned authenticated report ID;
- arbitrary evaluator errors are stored as failed attempts and re-raised;
- the same attempt cannot be outcome-conditioned rerun.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_research_runner.py -q`
Expected: FAIL because runner is absent.

- [ ] **Step 3: Implement minimal runner**

Record the attempt before verification. Verify the genuine-mainnet artifact to obtain actual interval/code/config. Load candidate and require exact code/config identity. Call `registry.assert_batch_disjoint_from_v4(verified.interval)` as a preflight, then invoke `evaluate_research_checkpoint()` with exactly one `ResearchArtifactBatch`. On success persist `report_id`; on `ResearchContaminationError` persist `contaminated`; on other exceptions persist `failed` and re-raise. Never inspect V4 economics.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_research_runner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: run authenticated research artifact attempts`.

---

### Task 3: Isolated runner CLI

**Files:**
- Create: `src/cocomelon/research_runner_cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_research_runner_cli.py`

**Interfaces:**
- Adds `cocomelon-research-runner = "cocomelon.research_runner_cli:main"`.
- Command `run-artifact` requires `--registry`, `--attempt-id`, `--candidate-id`, `--batch-id`, `--source-id`, `--artifact-root`.
- Command `attempts` exposes non-economic attempt/provenance history only.

- [ ] **Step 1: Write failing CLI tests**

Verify deterministic JSON, structured errors, missing registry failure, successful report ID output, and help/source contain no V4 curator/corpus/one-shot, private key, wallet, transfer, or live-order option.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_research_runner_cli.py -q`
Expected: FAIL because the CLI is absent.

- [ ] **Step 3: Implement CLI**

Use `argparse`; all writes go through `ResearchRegistry` and Task 2. Catch `OSError`, `ValueError`, SQLite/research registry errors, and research artifact errors into JSON stderr with exit code 2.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_research_runner_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: expose isolated research runner cli`.

---

### Task 4: Research cohort builder for the existing paper replay pipeline

**Files:**
- Create: `src/cocomelon/research/cohort.py`
- Test: `tests/test_research_cohort.py`

**Interfaces:**
- Produces `build_research_cohort(recording_root, output_root, starting_cash, trigger_head_sha) -> ResearchCohortBuildResult`.
- Reuses `validate_recording()`, `freeze_baseline_replay_payload()`, `run_baseline_replay_payload()`, and evaluation dataset freeze helpers; emits the same genuine-mainnet cohort files required by `verify_mainnet_evidence_cohort_payload()`.

- [ ] **Step 1: Write failing cohort tests**

Using a compact genuine recording fixture, prove the output is accepted by `verify_mainnet_evidence_cohort_payload()` and `verify_research_batch_artifact()`, replay metadata says `network_access=false` and `live_orders=false`, actual manifest interval comes from recording timestamps, and the cohort fails if the replay finishes non-flat/incomplete.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_research_cohort.py -q`
Expected: FAIL because the research cohort builder is absent.

- [ ] **Step 3: Implement cohort builder**

Factor only research-side composition around existing production evidence helpers. Do not change V4 workflow or baseline pipeline semantics. Copy/normalize the recording transport summary into the canonical cohort files, build/replay/freeze offline, create a `cohort-summary.json` with `economic_claim="none"`, and validate the finished cohort before returning it.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_research_cohort.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: build genuine research replay cohorts`.

---

### Task 5: Outcome-blind scheduled research workflow

**Files:**
- Create: `.github/workflows/research-campaign-scheduled.yml`
- Create: `tests/test_research_runner_workflow.py`

**Interfaces:**
- Dedicated research workflow only; does not call/reuse `evidence-campaign-v4-scheduled.yml` or any V4 curator/one-shot workflow.
- Acquires public mainnet data in paper mode, builds a research cohort offline, runs the research runner against a restored authoritative research registry, uploads the attempt/cohort/registry/status artifacts, and never retries based on economics.

- [ ] **Step 1: Write failing static workflow tests**

Assert the workflow:
- is research-named and separate from all V4 workflows;
- declares `COCOMELON_EXECUTION_MODE: paper`;
- has no private key, wallet, transfer, withdrawal, live order, `v4-mainnet-corpus`, V4 curator, or V4 one-shot references;
- has `cancel-in-progress: false` and exactly one acquisition attempt per workflow run;
- publishes cohort + registry even on failure so failed attempts remain auditable;
- runs `cocomelon-research-runner`, not the V4 evaluator;
- never branches/retries based on PnL, mean R, posterior, or profitability.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_research_runner_workflow.py -q`
Expected: FAIL because workflow is absent.

- [ ] **Step 3: Implement workflow conservatively**

Use a daily schedule that is operationally offset from the frozen V4 cron but treat the schedule only as orchestration: actual artifact intervals remain authoritative and the runner fails closed unless the restored V4 interval registry is complete through them. The workflow must not synthesize completeness from nominal cron. If authoritative registry state is unavailable, it uploads diagnostics and exits non-zero without economics.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_research_runner_workflow.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `ci: schedule isolated research replay campaign`.

---

### Task 6: Cross-lane isolation, status handoff, and full verification

**Files:**
- Create: `tests/test_research_runner_isolation.py`
- Modify: `docs/STATUS.md`

**Interfaces:**
- Locks the runner boundary and records the new exact project handoff.

- [ ] **Step 1: Add isolation regressions**

Prove runner/cohort/CLI/workflow source cannot import or mutate V4 corpus/curator/one-shot modules, cannot read hidden V4 economic fields, cannot expose a live-order surface, and research status remains `TOUCHED / NON-PROMOTIONAL` after a scheduled runner checkpoint.

- [ ] **Step 2: Run focused GREEN**

Run: `python -m pytest tests/test_research_runner*.py tests/test_research_cohort.py -q`
Expected: PASS.

- [ ] **Step 3: Update `docs/STATUS.md`**

Record PR #120 merged status, runner implementation boundary, exact fail-closed V4 registry requirement, persistent failed-attempt audit trail, paper-only workflow, and unchanged Phase 10/live block.

- [ ] **Step 4: Run complete verification**

Run:
- `python -m compileall -q src tests scripts`
- `python -m ruff check src tests scripts`
- `python -m mypy src`
- `python -m pytest -q`
- `python -m pytest tests/test_replay_compaction.py tests/test_parquet_replay_source.py -q`

Expected: all pass.

- [ ] **Step 5: Audit branch diff**

Require zero changes to existing V4 workflow/strategy/risk/execution/curator/corpus/one-shot files before opening the PR.
