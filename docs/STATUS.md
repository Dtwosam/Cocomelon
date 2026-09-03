# Cocomelon Project Status

**Last updated:** 2026-09-03  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Current verified main merge:** `6d0b6da32e4ec4a001ab2c45c175b91c25352cb3`  
**Verified V4 execution runtime:** `0c14c9cfa37c80babc65d050fed6d4465dcb9032`  
**Frozen V4 Phase 9 evaluator:** `efd33f8f89bc11e51c0e4f94591b9d8d1ce5b5ff`  
**Live trading:** **DISABLED**  
**Real baseline edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

## Current production state

The active authoritative evidence protocol remains **V4 thesis-expiry mainnet evidence**. Runtime observations are genuine public Hyperliquid mainnet data and execution remains paper/shadow only.

The frozen V4 acquisition contract is unchanged:

- fixed **45-minute entry window** (`2700` seconds);
- exact **4-hour maximum position age** (`14400` seconds);
- fixed **5h15m total capture** (`18900` seconds);
- nominal schedule `37 1,7,13,19 * * *` UTC;
- one acquisition attempt per cohort;
- schedule-triggered economic acquisition only;
- no outcome-conditioned retry, extension, cancellation, or forced admission;
- final cohort admission requires clean transport, complete replay/dataset evidence, no gaps, and flat replay exposure;
- live orders remain disabled.

Exact V4 identity:

- protocol `v4-thesis-expiry-mainnet`;
- runtime `0c14c9cfa37c80babc65d050fed6d4465dcb9032`;
- replay engine `phase8-v3-thesis-expiry`;
- replay config `phase9-baseline-replay-v3-thesis-expiry`;
- execution config `phase7-v2-4h-thesis-expiry`;
- frozen evaluator `efd33f8f89bc11e51c0e4f94591b9d8d1ce5b5ff`.

Do not change V4 strategy, risk, execution economics, acquisition timing, curator, evaluator, or one-shot policy to improve counts or outcomes. GitHub cron timestamps are scheduling requests, not evidence authority; actual run/job/session intervals are authoritative.

## Active V4 evidence progress

The latest trusted dashboard counts remain:

- **11 accepted V4 cohorts**;
- **19 / 100 closed paper trades**;
- **4 / 30 closed-trade days**;
- **1,155 strategy decisions**;
- **raw Phase 9 minimums not met**;
- **economic edge not measured yet**;
- **live orders disabled**.

Scheduled V4 run `33723341721` completed protected acquisition and verification successfully, and curator run `33753694785` admitted it to `v4-mainnet-corpus` as artifact `9892695744`.

Protected V4 run **#21**, run `33754093934`, is still in the `acquire-evidence` job at this snapshot. Its `Record thesis-expiry genuine public mainnet evidence` step remains in progress. It must finish naturally: do not manually dispatch, retry, extend, cancel, or performance-condition it.

Failed, timed-out, incomplete, pre-fix, and diagnostic V4 sources contribute zero economic progress unless the frozen curator independently admits them under the exact V4 protocol.

## Frozen V4 correctness history

The active corrected runtime incorporates only pre-admission correctness/provenance repairs; it does not represent strategy tuning.

- PR #109 removed an invalid whole-account equity equality during overlapping positions while preserving trade-local fill/fee/funding reconciliation.
- PR #113 split fixed acquisition and offline verification into independent job time budgets so a full 5h15 capture does not consume the replay budget.
- PR #114 canonicalized only bounded post-hour funding timestamp jitter (`<= 1000 ms`) for reconciliation while preserving original source timestamps/provenance.
- PRs #115/#116 prospectively repinned the still-empty V4 protocol/evaluator boundary to runtime `0c14c9c...` and evaluator `efd33f8f...` before the first accepted cohort.

The immutable V4 one-shot remains the only economic promotion path. No research result can replace it.

## Dual-lane research decision

Decision **D-023** provides a parallel research lane for faster rejection of weak ideas without contaminating V4 promotion evidence. Governing rule: **candidates may fail fast; candidates may not succeed fast**.

Research is permanently **TOUCHED / NON-PROMOTIONAL**:

- research may not inspect or reconstruct hidden V4 economics;
- research economics may use only source-time intervals proven disjoint from every actual V4 acquisition interval, including failed/diagnostic attempts;
- ambiguous or overlapping batches fail closed as `REJECTED_CONTAMINATION`;
- candidate descendants inherit ancestor touched intervals;
- economic futility cannot reject before **20 closed research trades**;
- `RESEARCH_PROMISING` requires at least **40 closed research trades**, **7 distinct UTC closed-trade days**, and posterior `P(mu > 0) >= 0.80`;
- `RESEARCH_PROMISING` cannot produce `CANDIDATE_EDGE`, mutate `v4-mainnet-corpus`, advance Phase 10, or enable live orders;
- a selected challenger must be frozen and begin separate untouched validation only after a **6-hour embargo** beyond the latest inherited touched interval.

The research trust chain remains:

`canonical replay artifact -> verified batch -> immutable attestation -> authenticated checkpoint/report -> atomic research state commit`.

## Research operations now deployed

The implemented research control plane consists of:

- `.github/workflows/research-campaign-scheduled.yml` — paper-only public-mainnet research acquisition with fixed `1800`-second capture;
- `.github/workflows/research-v4-registry-sync.yml` — trusted non-economic inventory of actual V4 acquisition intervals and completeness, publishing `research-authoritative-registry`;
- `.github/workflows/research-v4-sync-dispatcher.yml` — data-less V4-completion bridge that API-dispatches the trusted authority sync for completed scheduled main-branch V4 runs, including failed runs whose acquisition intervals still matter;
- `.github/workflows/research-daily-gap-dispatcher.yml` — opportunistically launches at most one successful research cohort per UTC day when no V4 acquisition or research campaign is active;
- `.github/workflows/research-dashboard.yml` — renders the touched/non-promotional research status issue;
- `.github/workflows/research-dashboard-catchup.yml` — redundant stale-source catch-up for dashboard observability.

The authoritative V4 interval/completeness synchronization path is **implemented**. Research cannot release candidate observations/economics until trusted V4 authority covers the bound research interval and canonical overlap checks pass.

### Reliability hardening merged on 2026-09-03

- **PR #136** recreates the candidate-decision diagnostics workspace before sandbox-policy output.
- **PR #137** aligns only research capture to the decision epoch while preserving the existing fixed entry window.
- **PR #138** adds research capture-control timeout headroom without changing the fixed 30-minute recorder.
- **PR #139** gives V4 priority during an already-running research capture: trusted control polls Actions metadata every 10 seconds, strips the Actions token from the recorder subprocess, kills only the research recorder if a protected V4 acquisition appears, and fails closed on metadata loss.
- **PR #141**, merge `f26a21da8d59bfa586a834b7ce58ee4dcc47149e`, adds a synchronous V4 recheck immediately before recorder launch, closing the candidate-build-to-recorder TOCTOU gap.
- **PR #142**, merge `9dc0c53f37227ae2f915015d9be2c3d58f6fdc1e`, isolates `actions: write` into a post-finalizer dashboard-dispatch job so future terminal research publications refresh issue #124 directly without granting the finalizer write scope.
- **PR #145**, merge `0d2ac2f949e8b950930f2385b88cf0be768de24b`, adds acquisition-aware V4 guarding. Research blocks on the actual V4 `acquire-evidence` job rather than the whole verification workflow; missing/ambiguous/unavailable acquisition metadata still fails closed. Post-capture authority refresh can retry non-economic synchronization while candidate observation remains blocked behind completeness/disjointness. Retry extraction state is cleared before subsequent authority downloads.
- **PR #146**, merge `5abca9cb38df855aa811a2d8a6b464c5a0c1be9d`, lowers only the safe-gap dispatcher poll from 15 minutes to **5 minutes**. The research capture remains 1800 seconds and every V4 preflight/watcher/provenance/economic gate remains unchanged.
- **PR #148**, merge `48e387d39bf79a8b8de23aab1bdc949c86cfdec2`, makes a successful authoritative V4 registry sync request a research-dashboard refresh from a separate data-less `actions: write` job. The sync publisher itself remains read-only; existing workflow-run and scheduled dashboard paths remain redundant fallbacks.
- **PR #149**, merge `6d0b6da32e4ec4a001ab2c45c175b91c25352cb3`, adds an event-driven V4-completion authority-sync dispatcher. Completed **scheduled** V4 runs on `main` trigger an API `workflow_dispatch` of the existing trusted sync, regardless of V4 conclusion, because failed acquisition attempts also matter for research interval authority. Manual V4 runs are excluded. The bridge has `contents: none`, no checkout or data access, deduplicates against an already-active sync, and leaves the frozen V4 workflow untouched.

PR #148 exact-head CI `33767848741`, PR-context CI `33767988476`, and post-merge main CI `33768116378` were green. PR #149 exact-head CI `33768651695`, PR-context CI `33768741732`, and post-merge main CI `33768857608` were green.

### GitHub schedule-delivery observation

Repository history confirms that nominal cron time cannot be treated as precise orchestration. For example, scheduled V4-authority sync runs `33751403165` and `33754001901` were delivered materially later than their nominal cron windows, and high-frequency dashboard catch-up run `33750524968` also arrived with substantial delay. This does not change evidence authority: actual run/job/session intervals remain canonical. It is the reason the production reliability path now prefers event-driven V4 completion -> trusted sync -> dashboard refresh while retaining cron paths only as redundant fallbacks.

## Research run #8 resolved fail-closed

Research run `33753704553` was launched from old pre-#139 code after a point-in-time no-active-V4 check. Delayed scheduled V4 run `33754093934` subsequently materialized and overlapped its source interval.

The canonical post-capture authority path resolved the race correctly:

- research capture itself completed under the old workflow;
- refreshed V4 authority did **not** cover the bound research interval end;
- `refresh-authority` failed with **`fresh V4 authority does not cover bound research interval`**, exit **70**;
- candidate observation/touch authorization and `evaluate-research` were skipped;
- no authenticated checkpoint or research economic result was admitted;
- the finalizer recovered/rebased trusted authority, terminalized the attempt as failed, and published the audit trail;
- audit artifact: `9894398717`;
- authoritative registry artifact: `9894399329`.

This is the intended fail-closed outcome: overlapping/insufficiently-authorized evidence did not become research economics.

## Research dashboard state

Issue #124 remains explicitly **TOUCHED / NON-PROMOTIONAL** and currently shows:

- candidate `scheduled-research-root`;
- state `draft`;
- **0 authenticated checkpoints**;
- no research economic conclusion.

Its visible timestamp is stale relative to the latest authority publications, but its zero-checkpoint semantics match the authoritative #8 result. PR #142 fixes direct post-finalizer refresh for future terminal research runs, and PR #148 adds direct post-sync refresh; the scheduled/hourly catch-up paths remain redundant observability fallbacks.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Let protected V4 run `33754093934` finish naturally; never manually dispatch, retry, extend, cancel, or performance-condition V4 acquisition.
3. **Observe the implemented authoritative V4 interval/completeness synchronization path** when V4 #21 completes and on the first subsequent research cohort that reaches a genuine acquisition-free gap.
4. Verify the event-driven chain: completed scheduled V4 -> `research-v4-sync-dispatcher` -> trusted `research-v4-registry-sync` via `workflow_dispatch` -> isolated dashboard refresh. A failed scheduled V4 run must still refresh interval authority; a manual V4 run must not become economic or research authority.
5. Observe the deployed 5-minute `research-daily-gap-dispatcher` behavior: while `acquire-evidence` is active it must skip; after physical V4 acquisition completes it may launch one research cohort only if no research run is active and no successful cohort exists for that UTC day. Do not infer safety from nominal cron delivery.
6. For any launched research cohort, verify the acquisition-aware preflight, synchronous pre-recorder guard, mid-capture V4 preemption, fixed 1800-second capture, post-capture completeness refresh, canonical disjointness gate, authenticated evaluation, finalizer publication, and direct dashboard dispatch.
7. Fix infrastructure defects with RED -> GREEN TDD, but never weaken V4 authority, overlap, completeness, touched-lineage, research authentication, or one-shot gates to force success.
8. Admit only clean, complete, flat frozen-runtime V4 sources through the frozen curator.
9. Let the frozen V4 one-shot determine readiness/economic status only after its immutable criteria are met; do not inspect or infer interim V4 economics.
10. Advance toward Phase 10 only if the authoritative untouched one-shot eventually reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

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
