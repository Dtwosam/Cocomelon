# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing Cocomelon across ChatGPT chats. Live GitHub state and authoritative repository docs always outrank this summary.

**Snapshot updated:** 2026-09-03  
**Repository:** `Dtwosam/Cocomelon`  
**Current verified `main` at snapshot:** `64a8f73a6e771ddd27de3587ad44ba0ef3532304`  
**Venue:** Hyperliquid perpetual futures  
**Observation:** genuine public Hyperliquid mainnet  
**Execution:** paper/shadow only  
**Hyperliquid testnet:** forbidden  
**Live trading:** **DISABLED**  
**Real V4 economic edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

---

## 1. Authority and continuation rule

Use this order:

1. current explicit user instruction;
2. `AGENTS.md`;
3. `docs/MASTER_SPEC.md`;
4. `docs/DECISIONS.md`;
5. `docs/BUILD_ORDER.md`;
6. active plan/spec under `docs/superpowers/`;
7. `docs/STATUS.md`;
8. this portable bootstrap.

Always inspect live `main`, recent Actions runs, open PR/review state, active V4 jobs, and current dashboard issues before acting. Do not rebuild already-merged work. Use RED -> GREEN TDD for behavior changes and verify exact-head, PR-context, and post-merge CI before claiming integration is green.

The user expects autonomous engineering. Real-money activation is the permanent exception: no live exchange order placement until objective promotion gates pass and the user explicitly authorizes live mode/capital.

---

## 2. Locked safety and economic boundaries

- Hyperliquid testnet is forbidden.
- Runtime market observations are public Hyperliquid mainnet only.
- Current/default execution is paper/shadow.
- No wallet/private-key signing, transfer, withdrawal, or private-account execution path belongs in V4/research evidence workflows.
- Strategy cannot bypass independent risk.
- No averaging down, martingale/loss-recovery sizing, or stopless positions.
- `NO_TRADE` is first-class.
- Historical L2/order flow may not be fabricated from candles.
- V4 interim economics remain hidden until the immutable one-shot protocol permits an authoritative result.
- Never manually dispatch, retry, extend, cancel, or performance-condition V4 economic acquisition.
- Research is permanently **TOUCHED / NON-PROMOTIONAL** and cannot directly produce `CANDIDATE_EDGE`, mutate `v4-mainnet-corpus`, advance Phase 10, or enable live orders.

---

## 3. Frozen V4 Phase 9 lane

Active protocol: `v4-thesis-expiry-mainnet`.

Frozen identity:

- execution runtime `0c14c9cfa37c80babc65d050fed6d4465dcb9032`;
- replay engine `phase8-v3-thesis-expiry`;
- replay config `phase9-baseline-replay-v3-thesis-expiry`;
- execution config `phase7-v2-4h-thesis-expiry`;
- frozen evaluator `efd33f8f89bc11e51c0e4f94591b9d8d1ce5b5ff`.

Frozen acquisition contract:

- 45-minute entry window;
- exact 4-hour maximum position age;
- fixed 5h15m total capture;
- nominal schedule `37 1,7,13,19 * * *` UTC;
- one acquisition attempt per cohort;
- schedule-only economic acquisition;
- final admission only for clean transport, complete replay/dataset evidence, no gaps, and flat replay exposure.

Do not change V4 strategy/risk/execution/evaluator/curator/corpus/schedule/economics merely to improve counts or outcomes. Nominal cron delivery is not authority; actual run/job/session intervals are.

### Current V4 progress

Latest trusted dashboard counts:

- **11 accepted V4 cohorts**;
- **19 / 100 closed paper trades**;
- **4 / 30 closed-trade days**;
- **1,155 strategy decisions**;
- raw Phase 9 minimums: **NO**;
- economic edge: **Not measured yet**;
- live orders: **DISABLED**.

Scheduled V4 run `33723341721` completed successfully and curator run `33753694785` admitted it into `v4-mainnet-corpus` artifact `9892695744`.

Protected V4 run **#21**, `33754093934`, is still in `acquire-evidence` at this snapshot, with `Record thesis-expiry genuine public mainnet evidence` in progress. Let it finish naturally. Never manually dispatch/retry/extend/cancel/performance-condition it.

---

## 4. D-023 dual-lane research

The research lane exists to reject weak ideas faster without contaminating V4 promotion evidence. Governing rule: **candidates may fail fast; candidates may not succeed fast**.

Research economics may use only source-time intervals proven disjoint from every actual V4 acquisition interval, including failed/diagnostic attempts. Ambiguous or overlapping batches fail closed as `REJECTED_CONTAMINATION`. Descendants inherit ancestor touched intervals.

Locked asymmetry:

- economic futility cannot reject before 20 closed research trades;
- `RESEARCH_PROMISING` requires at least 40 closed research trades, at least 7 distinct closed-trade UTC days, and posterior `P(mu > 0) >= 0.80`;
- `RESEARCH_PROMISING` remains non-promotional;
- a selected challenger must be frozen and begin separate untouched validation only after a 6-hour embargo beyond the latest inherited touched interval.

Research checkpoints must come through the canonical authenticated artifact/attestation/state path. No research result can directly become V4 promotion evidence.

### Current research status

Issue #124 was refreshed from trusted state at approximately `2026-09-03 15:10 UTC` and currently reports:

- candidate `scheduled-research-root`;
- state `draft`;
- **0 authenticated checkpoints**;
- no research economic conclusion.

The clean zero-checkpoint baseline matches the authoritative research #8 result. All research output remains explicitly **TOUCHED / NON-PROMOTIONAL**.

### Research candidate revision

`scheduled-research-root` is immutably pinned to `721dc98c22c389e3f6f85e382f84e2889fbefe31`. Candidate-build logs from research run `33753704553` show that exact revision was checked out and frozen into the candidate image.

A compare from `721dc98c...` to verified main `64a8f73a...` contains no changes under `src/cocomelon/strategies` or the strategy-evaluation domain/feature path. The actual strategy engine blob `src/cocomelon/strategies/engine.py` is identical at both revisions (`6d43979c1e9497a57c168a8b78f3fb0b8f5a7a7d`). Do not create or silently repin a descendant merely for infrastructure drift; create a descendant only for an intentional future strategy mutation, preserving touched lineage.

---

## 5. Research operations deployed

Control plane:

- `.github/workflows/research-campaign-scheduled.yml` — fixed 1800-second paper-only public-mainnet research capture;
- `.github/workflows/research-v4-registry-sync.yml` — trusted non-economic inventory of actual V4 acquisition intervals/completeness; publishes `research-authoritative-registry`;
- `.github/workflows/research-v4-sync-dispatcher.yml` — data-less completed-V4 bridge that API-dispatches the trusted authority sync for completed scheduled main-branch V4 runs;
- `.github/workflows/research-v4-acquisition-gap-observer.yml` — metadata-only **prospective** observer that watches future scheduled V4 `acquire-evidence` jobs and wakes the existing safe-gap dispatcher within roughly one minute after physical acquisition ends;
- `.github/workflows/research-daily-gap-dispatcher.yml` — safe-gap launcher with one-successful-cohort-per-UTC-day cap;
- `.github/workflows/research-dashboard.yml` — dedicated touched/non-promotional dashboard;
- `.github/workflows/research-dashboard-catchup.yml` — redundant stale-state catch-up.

Important reliability changes merged on 2026-09-03:

- **PR #136** fixes candidate-decision diagnostics directory transfer.
- **PR #137** aligns research capture to the decision epoch without changing the fixed entry window.
- **PR #138** adds research capture timeout headroom while keeping the recorder fixed at 1800 seconds.
- **PR #139** adds mid-capture V4 priority: trusted control polls Actions metadata every 10 seconds, strips the Actions token from the recorder subprocess, aborts only the research recorder if protected V4 acquisition appears, and fails closed on metadata loss.
- **PR #141** (`f26a21da8d59bfa586a834b7ce58ee4dcc47149e`) adds a synchronous V4 check immediately before recorder launch.
- **PR #142** (`9dc0c53f37227ae2f915015d9be2c3d58f6fdc1e`) isolates `actions: write` in a post-finalizer dashboard-dispatch job so future terminal research publications refresh issue #124 directly.
- **PR #145** (`0d2ac2f949e8b950930f2385b88cf0be768de24b`) makes the safe-gap guard acquisition-aware. It checks the actual V4 `acquire-evidence` job: verification-only V4 no longer unnecessarily blocks research, but missing/ambiguous/unavailable acquisition metadata fails closed. Post-capture authority refresh may retry non-economic synchronization, with retry extraction cleanup, while candidate observation remains behind completeness/disjointness.
- **PR #146** (`5abca9cb38df855aa811a2d8a6b464c5a0c1be9d`) reduces only the safe-gap dispatcher poll from 15 minutes to **5 minutes**. Capture duration and every V4/provenance/economic gate are unchanged.
- **PR #148** (`48e387d39bf79a8b8de23aab1bdc949c86cfdec2`) dispatches a trusted research-dashboard refresh after successful V4 authority synchronization from a separate no-checkout `actions: write` job; the authority publisher remains read-only.
- **PR #149** (`6d0b6da32e4ec4a001ab2c45c175b91c25352cb3`) adds an event-driven V4-completion -> trusted authority-sync bridge. It reacts only to completed scheduled V4 runs on `main`, intentionally includes failed runs because their acquisition intervals still matter, excludes manual V4 runs, uses `contents: none`, and preserves trusted sync identity by API-dispatching `research-v4-registry-sync.yml` as `workflow_dispatch`.
- **PR #151** (`2300acd546e03dc7cbca28f16fc4b8f68ce513c7`) removes a CI-only async recorder test race; production recorder/runtime timing is unchanged.
- **PR #152** (`64a8f73a6e771ddd27de3587ad44ba0ef3532304`) adds the metadata-only V4 acquisition-gap observer. It sees only Actions job/run state, fails closed on ambiguity, and can wake only `research-daily-gap-dispatcher.yml`, which re-applies all V4/research/daily-success gates before any research dispatch. It was merged after V4 #21 had already emitted its `in_progress` event, so it applies naturally to later scheduled V4 runs rather than retroactively attaching to #21.

Verified integration:

- PR #151 exact-head CI `33771441769`: success.
- PR #151 PR-context CI `33771542570`: success.
- PR #151 post-merge main CI `33771640553`: success.
- PR #152 exact-head CI `33772056693`: success.
- PR #152 PR-context CI `33772166298`: success.
- PR #152 post-merge main CI `33772264990`: success.

GitHub schedule delivery has shown material drift. The five-minute safe-gap dispatcher did not produce a fresh schedule run during the live observation window even while other schedules were delivered, so cron is only redundant orchestration. Actual run/job/session timing remains authority. Production now prefers event-driven wake-ups: acquisition-end observer -> safe-gap gate, and completed V4 -> trusted authority sync -> dashboard refresh.

---

## 6. Research run #8 resolved

Research run `33753704553` passed an old point-in-time no-active-V4 preflight before delayed scheduled V4 run `33754093934` materialized. It used pre-#139 control and therefore completed its legacy capture.

The canonical authority path still failed closed correctly:

- refreshed V4 completeness did not cover the bound research interval;
- `refresh-authority` failed with **`fresh V4 authority does not cover bound research interval`**, exit **70**;
- candidate observation/touch authorization and evaluation were skipped;
- **no authenticated checkpoint** and no research economics were admitted;
- finalizer rebased trusted authority, terminalized the failed attempt, and published the audit/registry;
- audit artifact `9894398717`;
- authoritative registry artifact `9894399329`.

This run is closed audit evidence, not an unresolved experiment and not a research checkpoint.

---

## 7. Exact handoff / next action

1. Keep Phase 10 and live trading blocked.
2. Let active protected V4 run `33754093934` finish naturally.
3. Do not retrofit the newly deployed acquisition-gap observer into already-running V4 #21. Observe the existing completion and redundant fallback paths for that run.
4. On the next scheduled V4 run after PR #152, verify `research-v4-acquisition-gap-observer.yml` starts from the V4 `in_progress` event and wakes the existing safe-gap dispatcher after the unique `acquire-evidence` job completes.
5. **Observe the implemented authoritative V4 interval/completeness synchronization path** when V4 #21 completes and on the first subsequent research cohort that reaches a genuine acquisition-free gap.
6. For a launched research cohort, verify acquisition-aware preflight, synchronous pre-recorder recheck, mid-capture V4 preemption, fixed 1800-second capture, post-capture authority completeness refresh, canonical disjointness, authenticated evaluation, finalizer publication, and dashboard refresh.
7. Keep `scheduled-research-root` pinned to `721dc98c...` unless strategy code itself intentionally changes; infrastructure-only commits do not justify a descendant.
8. Fix future infrastructure defects with RED -> GREEN TDD, but never weaken V4 authority, overlap, completeness, touched-lineage, research authentication, or one-shot gates.
9. Keep research permanently **TOUCHED / NON-PROMOTIONAL**.
10. Admit only clean, complete, flat frozen-runtime V4 sources into `v4-mainnet-corpus`.
11. Let the frozen V4 one-shot check readiness after trusted corpus updates; do not inspect interim V4 economics.
12. Advance toward Phase 10 only if the authoritative untouched one-shot eventually reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

---

## 8. What not to do

- Do not use Hyperliquid testnet.
- Do not add live wallet/order/transfer/withdrawal behavior.
- Do not manually retry/extend/cancel V4 because a cohort failed or produced an economic outcome.
- Do not import V4 economics/history into research.
- Do not turn research `RESEARCH_PROMISING` into direct promotion.
- Do not weaken provenance, overlap, gap, replay-completeness, flat-exposure, attestation, or authentication checks to accumulate trades faster.
- Do not use nominal cron timing as a substitute for actual V4 run/job/session authority.
- Do not trust this file over newer live repository evidence.
