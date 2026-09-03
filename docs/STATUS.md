# Cocomelon Project Status

**Last updated:** 2026-09-03  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Current verified main merge:** `d5c0cfb9e2914e70c782d3f575211a2295663050`  
**Verified V4 execution runtime:** `0c14c9cfa37c80babc65d050fed6d4465dcb9032`  
**Frozen V4 Phase 9 evaluator:** `efd33f8f89bc11e51c0e4f94591b9d8d1ce5b5ff`  
**Live trading:** **DISABLED**  
**Real baseline edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

## Current production state

The authoritative promotion lane remains frozen **V4 thesis-expiry mainnet evidence**. Market observations are genuine public Hyperliquid mainnet data and execution remains paper/shadow only.

Frozen V4 contract:

- 45-minute entry window (`2700` seconds);
- exact 4-hour maximum position age (`14400` seconds);
- fixed 5h15m total capture (`18900` seconds);
- nominal schedule `37 1,7,13,19 * * *` UTC;
- one acquisition attempt per cohort;
- schedule-triggered economic acquisition only;
- no outcome-conditioned retry, extension, cancellation, or forced admission;
- final admission only for clean transport, complete replay/dataset evidence, no gaps, and flat replay exposure;
- live orders disabled.

Exact frozen identity:

- protocol `v4-thesis-expiry-mainnet`;
- runtime `0c14c9cfa37c80babc65d050fed6d4465dcb9032`;
- replay engine `phase8-v3-thesis-expiry`;
- replay config `phase9-baseline-replay-v3-thesis-expiry`;
- execution config `phase7-v2-4h-thesis-expiry`;
- evaluator `efd33f8f89bc11e51c0e4f94591b9d8d1ce5b5ff`.

Do not change V4 strategy, risk, execution economics, acquisition timing, curator, evaluator, corpus policy, or one-shot policy to improve counts or outcomes. Nominal cron timestamps are not evidence authority; actual run/job/session intervals are.

## Active V4 evidence progress

Latest trusted dashboard counts:

- **11 accepted V4 cohorts**;
- **19 / 100 closed paper trades**;
- **4 / 30 closed-trade days**;
- **1,155 strategy decisions**;
- raw Phase 9 minimums not met;
- economic edge not measured yet;
- live orders disabled.

Protected scheduled V4 run **#21**, run `33754093934`, remains in `acquire-evidence` at this snapshot. Its `Record thesis-expiry genuine public mainnet evidence` step is still in progress. It must finish naturally: never manually dispatch, retry, extend, cancel, or performance-condition it.

Failed, timed-out, incomplete, pre-fix, and diagnostic V4 sources contribute zero economic progress unless the frozen curator independently admits them under the exact V4 protocol.

## Research lane: D-023

Research exists to reject weak ideas faster without contaminating promotion evidence. It is permanently **TOUCHED / NON-PROMOTIONAL**. Governing rule: **candidates may fail fast; candidates may not succeed fast**.

Locked research rules:

- research may not inspect or reconstruct hidden V4 economics;
- research economics may use only source-time intervals proven disjoint from every actual V4 acquisition interval, including failed/diagnostic attempts;
- ambiguous or overlapping batches fail closed as `REJECTED_CONTAMINATION`;
- descendants inherit ancestor touched intervals;
- economic futility cannot reject before **20 closed research trades**;
- `RESEARCH_PROMISING` requires at least **40 closed research trades**, **7 distinct UTC closed-trade days**, and posterior `P(mu > 0) >= 0.80`;
- `RESEARCH_PROMISING` cannot directly produce `CANDIDATE_EDGE`, mutate `v4-mainnet-corpus`, advance Phase 10, or enable live orders;
- a selected challenger must be frozen and begin separate untouched validation only after a **6-hour embargo** beyond the latest inherited touched interval.

Trust chain:

`canonical replay artifact -> verified batch -> immutable attestation -> authenticated checkpoint/report -> atomic research state commit`.

## Research candidate readiness

`scheduled-research-root` is immutably pinned to code revision `721dc98c22c389e3f6f85e382f84e2889fbefe31`. Research run `33753704553` proves that exact revision was checked out and frozen into the candidate image.

The candidate is strategically current. Comparison to production shows no strategy/evaluation source mutation, and `src/cocomelon/strategies/engine.py` has the same blob at the candidate and production lineage: `6d43979c1e9497a57c168a8b78f3fb0b8f5a7a7d`.

Do **not** create or silently repin a descendant merely to absorb infrastructure commits. Create a descendant only for an intentional future strategy mutation while preserving touched lineage.

## Research operations deployed

The control plane includes:

- `.github/workflows/research-campaign-scheduled.yml` — paper-only public-mainnet research acquisition with fixed `1800`-second capture;
- `.github/workflows/research-v4-registry-sync.yml` — trusted non-economic inventory of actual V4 acquisition intervals and completeness;
- `.github/workflows/research-v4-sync-dispatcher.yml` — completed scheduled V4 -> trusted authority-sync bridge;
- `.github/workflows/research-v4-acquisition-gap-observer.yml` — metadata-only acquisition observer;
- `.github/workflows/research-daily-gap-dispatcher.yml` — safe-gap research launcher with one-successful-cohort-per-UTC-day cap;
- `.github/workflows/research-dashboard.yml` — touched/non-promotional research dashboard;
- `.github/workflows/research-dashboard-catchup.yml` — redundant dashboard catch-up.

Research cannot release candidate observations/economics until trusted V4 authority covers the bound research interval and canonical overlap/disjointness checks pass.

### Reliability hardening merged on 2026-09-03

Key recent changes:

- PR #136 fixes candidate-decision diagnostics workspace handling.
- PR #137 aligns research capture to the decision epoch without changing the fixed entry window.
- PR #138 adds research capture timeout headroom while keeping the recorder fixed at 1800 seconds.
- PR #139 gives V4 priority during a running research capture, including a 10-second trusted Actions-metadata watcher and research-only preemption.
- PR #141 (`f26a21da8d59bfa586a834b7ce58ee4dcc47149e`) adds a synchronous V4 recheck immediately before recorder launch.
- PR #142 (`9dc0c53f37227ae2f915015d9be2c3d58f6fdc1e`) isolates post-finalizer dashboard-dispatch write scope.
- PR #145 (`0d2ac2f949e8b950930f2385b88cf0be768de24b`) makes V4 guarding acquisition-aware and retries non-economic authority synchronization until completeness can cover the research interval.
- PR #146 (`5abca9cb38df855aa811a2d8a6b464c5a0c1be9d`) reduces only the safe-gap poll cadence to GitHub Actions' 5-minute floor.
- PR #148 (`48e387d39bf79a8b8de23aab1bdc949c86cfdec2`) refreshes the research dashboard after successful authority synchronization from isolated write scope.
- PR #149 (`6d0b6da32e4ec4a001ab2c45c175b91c25352cb3`) adds completed-scheduled-V4 -> trusted authority-sync dispatch.
- PR #151 (`2300acd546e03dc7cbca28f16fc4b8f68ce513c7`) removes a CI-only async recorder test race; runtime timing is unchanged.
- PR #152 (`64a8f73a6e771ddd27de3587ad44ba0ef3532304`) adds a metadata-only observer for future scheduled V4 `in_progress` events. It polls only Actions run/job state and can wake only the existing safe-gap dispatcher.
- **PR #154**, merge `d5c0cfb9e2914e70c782d3f575211a2295663050`, safely bootstraps that observer onto an already-running scheduled V4 acquisition when the observer file itself lands on `main`. The bootstrap queries only scheduled main-branch V4 run/job metadata, fails closed on ambiguity, and still can wake only `research-daily-gap-dispatcher.yml`; it cannot start, stop, retry, inspect, or alter V4 and cannot launch research directly.

PR #154 verification:

- RED CI `33777273875` failed only because the bootstrap trigger was not yet present;
- exact-head GREEN CI `33777436656`: success;
- PR-context CI `33777589885`: success;
- merge: `d5c0cfb9e2914e70c782d3f575211a2295663050`;
- post-merge main CI `33777785186`: success.

### Live observer bootstrap proof

The PR #154 merge immediately produced **Research V4 Acquisition Gap Observer** run `33777785906` on `main` with event `push`. Its `observe-acquisition` job entered `Dispatch safe-gap gate when V4 acquisition completes` and remains in progress while V4 #21's unique `acquire-evidence` job remains active.

This is the intended state: the observer is attached to #21 without touching the protected V4 workflow. When that acquisition completes, the observer may wake the existing safe-gap dispatcher. The dispatcher then independently rechecks **all** active V4 acquisitions, active research runs, and the current UTC-day success cap before it can dispatch research. A newer protected V4 acquisition therefore still causes a safe skip.

GitHub schedule delivery has shown material drift, including no fresh safe-gap cron run during the observed interval. Cron remains redundant orchestration; actual run/job/session timing remains authority and event-driven wake-ups are preferred where available.

## Research run #8 resolved fail-closed

Research run `33753704553` used old pre-#139 control and overlapped delayed scheduled V4 run `33754093934`.

Canonical resolution:

- research capture completed under the legacy workflow;
- refreshed V4 authority did not cover the bound research interval end;
- `refresh-authority` failed with `fresh V4 authority does not cover bound research interval`, exit `70`;
- candidate observation/touch authorization and research evaluation were skipped;
- no authenticated checkpoint or research economic result was admitted;
- finalizer recovered/rebased trusted authority and published the failed-attempt audit trail;
- audit artifact `9894398717`;
- authoritative registry artifact `9894399329`.

This is the intended fail-closed outcome.

## Research dashboard state

Issue #124 was last refreshed from trusted state at approximately **2026-09-03 15:10 UTC** and remains:

- **TOUCHED / NON-PROMOTIONAL**;
- candidate `scheduled-research-root`;
- state `draft`;
- **0 authenticated checkpoints**;
- no research economic conclusion.

This clean zero-checkpoint baseline matches the authoritative research #8 result. Do not manually edit it to invent progress.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Let protected V4 #21 (`33754093934`) finish naturally; never manually dispatch, retry, extend, cancel, or performance-condition it.
3. Observe live observer run `33777785906`. It should remain attached while #21 acquisition is active and, after the unique `acquire-evidence` completion, may wake `research-daily-gap-dispatcher.yml`.
4. Verify the safe-gap dispatcher rechecks all active V4 acquisitions, active research campaigns, and the UTC-day success cap before any research launch.
5. **Observe the implemented authoritative V4 interval/completeness synchronization path** when V4 #21 completes and on the first subsequent research cohort that reaches a genuine acquisition-free gap.
6. For any launched research cohort, verify acquisition-aware preflight, synchronous pre-recorder guard, mid-capture V4 preemption, fixed 1800-second capture, post-capture authority completeness refresh, canonical disjointness, authenticated evaluation, finalizer publication, and dashboard refresh.
7. Keep `scheduled-research-root` pinned to `721dc98c...` unless strategy code itself intentionally changes.
8. Fix infrastructure defects with RED -> GREEN TDD, but never weaken V4 authority, overlap, completeness, touched-lineage, research authentication, or one-shot gates.
9. Admit only clean, complete, flat frozen-runtime V4 sources through the frozen curator.
10. Let the frozen V4 one-shot determine readiness/economic status only after its immutable criteria are met; do not inspect or infer interim V4 economics.
11. Advance toward Phase 10 only if the authoritative untouched one-shot eventually reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Hard prohibitions

- Do not use Hyperliquid testnet.
- Do not add live wallet/order/transfer/withdrawal behavior to the evidence/research lanes.
- Do not manually retry or extend V4 because of an acquisition/economic outcome.
- Do not import V4 economics/history into research.
- Do not turn `RESEARCH_PROMISING` into direct promotion.
- Do not weaken provenance, overlap, gap, replay-completeness, flat-exposure, attestation, or authentication checks to accumulate trades faster.
- Do not use nominal cron timing as a substitute for actual V4 run/job/session interval authority.

No currently verified result demonstrates repeatable economic edge. `UNMEASURED` is not the same as `NO_EDGE_DEMONSTRATED`.

**LIVE TRADING: DISABLED.**
