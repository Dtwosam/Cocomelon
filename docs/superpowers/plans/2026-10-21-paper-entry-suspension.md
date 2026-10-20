# Ordinary PAPER entry suspension implementation plan

> For agentic workers: use test-driven implementation with independent safety review. This plan implements the owner's October 21 capital-preservation mandate.

**Goal:** Block new ordinary PAPER exposure while preserving actual position management and account continuity.

**Architecture:** Reuse the existing lifecycle cutoff at zero, with a guard at the PAPER adapter's opening boundary. One immutable ordinary-account policy records suspension provenance in the already archived state root. Missing, invalid or unwritable policy evidence never grants entry authority and never disables protective management.

**Tech stack:** Python 3.12, existing SQLite execution/accounting, pytest.

**Spec:** This document's scope and required behavior summarize the current owner mandate. A prepared release is not an active-worker suspension. Do not merge/deploy if the natural transition or runtime safety gates remain unverified.

## Constraints and review focus

- Ordinary account only; shared research adapter defaults and LIVE safeguards remain unchanged.
- No hot patch, worker stop/restart/duplication, forced close, account reset, risk/source changes or workflow roll.
- Keep strategy decisions available for thesis exits and tighter invalidations.
- Pending entry candidates, direct opening submissions, same-book reentry/flips and restoration cannot bypass the gate.
- Partial reductions and reduce-only latency retries remain functional; gate errors cannot set execution health false.
- Preserve original policy provenance through a complete state-root archive/restore. Unsupported older binaries cannot be assumed to enforce a new policy.

## Task 1 — Persist the immutable ordinary policy

Files: new `src/cocomelon/paper_entry_suspension.py`, new `tests/test_paper_entry_suspension.py`.

- [x] Write and run failing tests for missing/legacy state, valid successor restore, malformed/false/future state and write failure.
- [x] Implement `load_entry_suspension(state_root, *, timestamp_ms, worker_run_id=None, worker_head_sha=None)` returning an immutable suspended policy and explicit durability/error diagnostic.
- [x] Preserve invalid bytes and continue in-memory suspension. No resume API or configuration flag.
- [x] Run policy tests; retain failing-first and passing evidence.

## Task 2 — Enforce at entry boundaries; preserve real exits

Files: `src/cocomelon/execution/paper.py`, `src/cocomelon/continuous_paper.py`, new `tests/test_paper_entry_suspension_integration.py`.

- [x] Write real-component tests first: stop/thesis/emergency reductions, pending candidate, same-book flip, partial fill/retry and genuine SQLite/lifecycle restoration.
- [x] Add optional `entries_suspended=False` to the shared PAPER adapter. Reject opening requests with `PAPER_ENTRIES_SUSPENDED` before plan/fill creation; do not change execution health or reduction methods.
- [x] Load the ordinary policy before ingestion, always pass suspended state to the ordinary adapter, and pass the existing zero cutoff to the ordinary lifecycle pipeline.
- [x] Expose session opening-attempt/fill/block and pending-reduction counts for verification. Do not call historical entries post-suspension activity.
- [x] Run real integration and existing execution/lifecycle/continuous tests.

## Task 3 — Prove runtime adoption separately from code readiness

Files: `src/cocomelon/continuous_paper.py`, `scripts/render_continuous_paper_live_status.py`, related status tests and bounded operational documentation.

- [x] Write failing tests for honest policy acknowledgement, scoped counters and legacy/unavailable diagnostics.
- [x] Include policy/effective clock/origin/durability and actual enforcement counters in operational heartbeat and session summary; render legacy absence as unverified.
- [x] Do not alter account checkpoint schema, raw market evidence or archive/restore workflows. Full-root archives already include the new small file.
- [x] Independently review real test coverage and state/worker continuity risks.
- [x] Run compile, Ruff, mypy and full local pytest. Focused 166 pass; full local run: 5,725 pass, one skip and one unchanged macOS directory-unlink exception mismatch. No code workaround or exclusion was added.
- [ ] Pass exact-head GitHub test/research CI before any merge; link the immutable CI result in the PR.
- [x] Prepare natural-transition instructions. Existing transient pending-reduction intent is not exactly restored; require zero authenticated pending state or independent recovery proof.
- [ ] Publish the prepared PR; keep it unmerged while operational adoption is unverified. Never claim ACTIVE from tests or a file.

## Economic boundary

The existing selector-optimization branch stays shelved. No profitable strategy is claimed. After this safety slice, admit a new mechanism only on genuinely new accessible evidence; otherwise no strategy test, collector or selector follows.
