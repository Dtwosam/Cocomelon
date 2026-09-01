# Research Status Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, read-only research status surface that shows authenticated candidate checkpoint history and economics while permanently labeling all outputs `TOUCHED / NON-PROMOTIONAL` and never consuming V4 hidden economics.

**Architecture:** A focused `cocomelon.research.dashboard` read model will read only `ResearchRegistry`, re-authenticate every persisted checkpoint through the existing report authenticator, order checkpoint history by canonical admitted research-batch end time, and return a JSON-safe snapshot. A separate renderer will produce compact Markdown from the same snapshot, and a dedicated `cocomelon-research-status` CLI will expose JSON or Markdown without modifying the existing research control CLI.

**Tech Stack:** Python 3.12, SQLite, existing research registry/report authentication, argparse, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-31-dual-lane-sequential-research-design.md`

## Global Constraints

- Research output is always **TOUCHED / NON-PROMOTIONAL**.
- Research status must never merge metrics with V4 validation counts or present research profitability as verified economic edge.
- The status path reads only the research registry and must not consume V4 economic artifacts, curator output, or `v4-mainnet-corpus`.
- Any unauthenticated or non-reproducible checkpoint report fails closed instead of being displayed.
- Hyperliquid testnet remains forbidden and live trading remains disabled.
- This slice is read-only: no candidate, batch, report, V4-registry, or execution state mutation.

---

### Task 1: Authenticated research status snapshot

**Files:**
- Create: `src/cocomelon/research/dashboard.py`
- Test: `tests/test_research_dashboard.py`

**Interfaces:**
- Consumes: `ResearchRegistry`; `assert_checkpoint_report_backed_by_observations(connection, candidate_id, report_id, payload, state)`.
- Produces: `build_research_status(registry: ResearchRegistry) -> dict[str, object]`.

- [ ] **Step 1: Write failing snapshot tests**

Cover an empty registry, a draft candidate with no reports, a candidate with genuine canonical research artifacts/checkpoints, chronological checkpoint ordering by admitted batch `end_ms`, and a directly persisted fabricated report that must raise `ResearchRegistryError` rather than appear in status.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python -m pytest tests/test_research_dashboard.py -q`

Expected: FAIL because `cocomelon.research.dashboard` does not exist.

- [ ] **Step 3: Implement the minimal authenticated read model**

Implement helpers that expose:

```python
RESEARCH_STATUS_LABEL = "TOUCHED / NON-PROMOTIONAL"


def build_research_status(registry: ResearchRegistry) -> dict[str, object]:
    ...
```

The snapshot contains a top-level `label`, aggregate candidate-state counts, and a `candidates` list sorted by `candidate_id`. Each candidate entry includes immutable identity/lineage, state, touched/source provenance, and an ordered `checkpoints` list. Every checkpoint is re-authenticated before inclusion. Determine checkpoint chronology from the maximum `end_ms` of the report's canonical `batch_ids`; never use report hash ordering or wall-clock time.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_research_dashboard.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the read model**

Commit message: `feat: add authenticated research status snapshot`

---

### Task 2: Markdown research dashboard renderer

**Files:**
- Modify: `src/cocomelon/research/dashboard.py`
- Test: `tests/test_research_dashboard.py`

**Interfaces:**
- Consumes: the exact snapshot returned by `build_research_status`.
- Produces: `render_research_status_markdown(snapshot: dict[str, object]) -> str`.

- [ ] **Step 1: Write failing renderer tests**

Require the first visible heading to identify the research surface, require `TOUCHED / NON-PROMOTIONAL` near the top, require an explicit statement that research results are not promotion/verified-edge evidence, render candidate state/trades/days/net PnL/mean net R/posterior, and render chronological checkpoint history without any V4 validation count.

- [ ] **Step 2: Run renderer tests and confirm RED**

Run: `python -m pytest tests/test_research_dashboard.py -q`

Expected: FAIL because the renderer is absent.

- [ ] **Step 3: Implement deterministic Markdown rendering**

Render one compact candidate summary table followed by per-candidate checkpoint history. Use only fields already present in the authenticated snapshot. Render missing economics as `—`; do not calculate new economics in the presentation layer.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_research_dashboard.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the renderer**

Commit message: `feat: render touched research dashboard`

---

### Task 3: Dedicated read-only status CLI

**Files:**
- Create: `src/cocomelon/research_dashboard_cli.py`
- Modify: `pyproject.toml`
- Create: `tests/test_research_dashboard_cli.py`

**Interfaces:**
- Consumes: `build_research_status()` and `render_research_status_markdown()`.
- Produces: console entry point `cocomelon-research-status`; CLI arguments `--registry PATH` and `--format {json,markdown}` with `markdown` as the default.

- [ ] **Step 1: Write failing CLI tests**

Test JSON output, Markdown output, invalid-registry/report failures, and verify the command has no mutation subcommands or live-order options.

- [ ] **Step 2: Run CLI tests and confirm RED**

Run: `python -m pytest tests/test_research_dashboard_cli.py -q`

Expected: FAIL because the CLI module/entry point does not exist.

- [ ] **Step 3: Implement the CLI**

The command opens `ResearchRegistry`, builds the authenticated snapshot, writes exactly one output format to stdout, writes errors to stderr, returns non-zero on `OSError`, `ValueError`, JSON errors, or `ResearchRegistryError`, and always closes the registry. It exposes no candidate/batch/state mutation command.

- [ ] **Step 4: Run CLI tests and confirm GREEN**

Run: `python -m pytest tests/test_research_dashboard_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the CLI**

Commit message: `feat: add research status cli`

---

### Task 4: Isolation and full verification

**Files:**
- Create: `tests/test_research_dashboard_isolation.py`
- Modify: `docs/STATUS.md`

**Interfaces:**
- Consumes: completed status snapshot/renderer/CLI.
- Produces: regression evidence that the status surface cannot consume V4 hidden economics or mutate research state.

- [ ] **Step 1: Write isolation tests**

Assert dashboard and CLI source do not import V4 dashboard/curator/evaluator modules, do not contain `v4-mainnet-corpus`, and do not expose live-order or write-state operations. Create a registry, snapshot it, render it, and assert all research-control table row counts/states are unchanged.

- [ ] **Step 2: Run focused isolation tests**

Run: `python -m pytest tests/test_research_dashboard.py tests/test_research_dashboard_cli.py tests/test_research_dashboard_isolation.py -q`

Expected: PASS after implementation.

- [ ] **Step 3: Run repository verification**

Run:

```bash
python -m compileall -q src tests scripts
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
```

Expected: all green.

- [ ] **Step 4: Update project status**

Record that the read-only research status surface is implemented, explicitly retain `TOUCHED / NON-PROMOTIONAL`, Phase 10 blocked, real baseline edge unmeasured, live trading disabled, and identify the scheduled/replay research runner as the next D-023 rollout slice.

- [ ] **Step 5: Commit documentation and open a focused PR**

Commit message: `docs: record research status surface`

PR must not modify frozen V4 workflow/strategy/risk/execution/curator/corpus/one-shot files.
