# Phase 9 V3 Evaluation Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit, immutable V3-to-Phase-9 evaluation boundary that preserves the locked 47-day one-shot/OOS statistical policy while binding snapshots and evaluations to the repaired V3 lifecycle-aware evidence protocol.

**Architecture:** Keep the existing V2 public commands and artifact identities unchanged. Generalize the Phase 9 snapshot/evaluation plumbing behind protocol-specific wrappers, then add V3 wrappers that require the exact V3 corpus `protocol.json`, copy and hash that protocol into the frozen snapshot, use distinct V3 snapshot/evaluation/candidate identities, and expose separate local-only CLI commands. No strategy, risk, execution, or promotion thresholds change.

**Tech Stack:** Python 3.12, argparse, pytest, GitHub Actions CI.

**Spec:** `docs/STATUS.md`

## Global Constraints

- Hyperliquid mainnet evidence only; no testnet inputs.
- Paper/shadow execution only; live orders remain disabled.
- V3 source protocol must equal `v3-lifecycle-aware-mainnet` with runtime `f8f84200dbc8b6fb262c5f6f99993b40714357be`, entry window 2700 seconds, capture window 14400 seconds, replay engine `phase8-v2-lifecycle-aware`, and config `phase9-baseline-replay-v2-lifecycle-aware`.
- Locked Phase 9 policy remains unchanged: 100 OOS closed trades, 30 closed-trade days, 3 eligible walk-forward windows, 20 trades/window, 20 trades/score bucket, 60% positive eligible windows, 95% bootstrap confidence, 5-day blocks, 2,000 resamples, 6-hour embargo, and NO_TRADE horizons 1h/4h.
- V2 snapshot/evaluation commands and identities remain backward compatible.
- V3 and V2 artifacts must never share names or protocol identities.

---

### Task 1: Lock the V3 handoff contract with tests

**Files:**
- Create: `tests/test_mainnet_phase9_v3.py`
- Modify: `tests/test_mainnet_evidence_cli.py`

**Interfaces:**
- Consumes: existing Phase 9 snapshot/evaluation helpers and CLI parser.
- Produces: executable contract for exact V3 corpus provenance, distinct V3 identities, and local-only CLI commands.

- [ ] **Step 1: Write failing tests for exact V3 protocol validation**

Add tests that require the V3 helper to reject missing/mismatched `protocol.json` and accept only the exact frozen V3 protocol fields.

- [ ] **Step 2: Write failing CLI tests**

Require `prepare-phase9-v3 --corpus-root --out-root` and `evaluate-phase9-v3 --snapshot-root`, with the same forbidden network/live/testnet options as V2.

- [ ] **Step 3: Run CI and confirm RED**

Expected: only the new V3 tests/CLI assertions fail because V3 functions/commands do not exist yet.

### Task 2: Implement protocol-specific Phase 9 snapshot/evaluation plumbing

**Files:**
- Modify: `src/cocomelon/evaluation/mainnet_phase9.py`

**Interfaces:**
- Consumes: `EvaluationPolicy`, current dataset/split/walk-forward/evaluation helpers.
- Produces: `prepare_phase9_v3_snapshot(corpus_root, out_root)` and `evaluate_phase9_v3_snapshot(snapshot_root)` while preserving `prepare_phase9_v2_snapshot` and `evaluate_phase9_v2_snapshot` behavior.

- [ ] **Step 1: Introduce immutable V3 protocol constants**

Define exact source protocol fields plus distinct names `v3-phase9-frozen-snapshot`, `v3-phase9-evaluation`, and `v3-baseline-fixed`.

- [ ] **Step 2: Generalize internal snapshot construction**

Parameterize only identity/provenance fields. Keep the existing dataset selection, 47-day split, readiness logic, cost stress profiles, and `EvaluationPolicy()` unchanged.

- [ ] **Step 3: Bind V3 source provenance**

Before snapshot creation, require exact `protocol.json`; copy it into the snapshot; include it in file hashes; record its canonical digest and protocol name in `snapshot.json`.

- [ ] **Step 4: Bind V3 evaluation provenance**

Require V3 snapshot name/protocol digest before evaluating; emit `v3-phase9-evaluation` while calling the same locked economic engine/policy.

- [ ] **Step 5: Preserve V2 outputs byte-for-field compatible where semantics matter**

V2 commands keep their artifact names, candidate name, and no new required source `protocol.json`.

### Task 3: Expose V3 local-only CLI commands

**Files:**
- Modify: `src/cocomelon/mainnet_cli.py`
- Modify: `tests/test_mainnet_evidence_cli.py`

**Interfaces:**
- Consumes: `prepare_phase9_v3_snapshot`, `evaluate_phase9_v3_snapshot`.
- Produces: `cocomelon-mainnet-evidence prepare-phase9-v3` and `evaluate-phase9-v3`.

- [ ] **Step 1: Add parser commands with only filesystem arguments**
- [ ] **Step 2: Dispatch explicitly by command name; do not use a catch-all evaluation branch**
- [ ] **Step 3: Verify forbidden network/live/testnet flags remain rejected**

### Task 4: Verify, review, merge, then pin activation separately

**Files:**
- No production workflow changes in the core evaluator PR.

**Interfaces:**
- Produces: immutable evaluator revision that a later V3 curator/workflow activation can pin.

- [ ] **Step 1: Run compile, Ruff, mypy, full pytest, and research tests**
- [ ] **Step 2: Review the PR for any V2 behavior drift or gate weakening**
- [ ] **Step 3: Merge only after exact PR CI is green**
- [ ] **Step 4: Create a second activation change that pins the V3 evaluation handoff to the merged evaluator SHA before any V3 one-shot artifact can be produced**
