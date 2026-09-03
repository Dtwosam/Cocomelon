# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing Cocomelon across ChatGPT chats. Live GitHub state and authoritative repository docs always outrank this summary.

**Snapshot updated:** 2026-09-03  
**Repository:** `Dtwosam/Cocomelon`  
**Current verified `main` at snapshot:** `d5c0cfb9e2914e70c782d3f575211a2295663050`  
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

Latest trusted dashboard counts:

- **11 accepted V4 cohorts**;
- **19 / 100 closed paper trades**;
- **4 / 30 closed-trade days**;
- **1,155 strategy decisions**;
- raw Phase 9 minimums: **NO**;
- economic edge: **Not measured yet**;
- live orders: **DISABLED**.

Protected V4 run **#21**, `33754093934`, remains in `acquire-evidence` at this snapshot, with `Record thesis-expiry genuine public mainnet evidence` in progress. Let it finish naturally. Never manually dispatch/retry/extend/cancel/performance-condition it.

---

## 4. D-023 dual-lane research

Research is permanently **TOUCHED / NON-PROMOTIONAL**. Governing rule: **candidates may fail fast; candidates may not succeed fast**.

Research economics may use only source-time intervals proven disjoint from every actual V4 acquisition interval, including failed/diagnostic attempts. Ambiguous or overlapping batches fail closed as `REJECTED_CONTAMINATION`. Descendants inherit ancestor touched intervals.

Locked thresholds:

- futility rejection cannot occur before 20 closed research trades;
- `RESEARCH_PROMISING` requires at least 40 closed research trades, 7 distinct UTC closed-trade days, and posterior `P(mu > 0) >= 0.80`;
- `RESEARCH_PROMISING` remains non-promotional;
- any selected challenger must be frozen and begin separate untouched validation only after a 6-hour embargo beyond its latest inherited touched interval.

Canonical trust path:

`canonical replay artifact -> verified batch -> immutable attestation -> authenticated checkpoint/report -> atomic research state commit`.

### Current research baseline

Issue #124 was last refreshed from trusted state at approximately **2026-09-03 15:10 UTC** and reports:

- candidate `scheduled-research-root`;
- state `draft`;
- **0 authenticated checkpoints**;
- no research economic conclusion;
- explicit **TOUCHED / NON-PROMOTIONAL** status.

This matches the authoritative fail-closed research #8 result.

### Candidate revision

`scheduled-research-root` is immutably pinned to `721dc98c22c389e3f6f85e382f84e2889fbefe31`. Candidate-build logs from research run `33753704553` show that exact revision was checked out and frozen into the candidate image.

Its strategy is current: `src/cocomelon/strategies/engine.py` has identical blob `6d43979c1e9497a57c168a8b78f3fb0b8f5a7a7d` at the candidate and current production lineage. Infrastructure-only drift is not a reason to create or silently repin a descendant.

---

## 5. Research operations deployed

Control plane:

- `.github/workflows/research-campaign-scheduled.yml` — fixed 1800-second public-mainnet paper research capture;
- `.github/workflows/research-v4-registry-sync.yml` — trusted non-economic V4 interval/completeness inventory;
- `.github/workflows/research-v4-sync-dispatcher.yml` — completed scheduled V4 -> trusted authority-sync bridge;
- `.github/workflows/research-v4-acquisition-gap-observer.yml` — metadata-only acquisition-end observer;
- `.github/workflows/research-daily-gap-dispatcher.yml` — safe-gap launcher with one-successful-cohort-per-UTC-day cap;
- `.github/workflows/research-dashboard.yml` — touched/non-promotional dashboard;
- `.github/workflows/research-dashboard-catchup.yml` — redundant observability fallback.

Important recent reliability changes:

- PRs #136/#137/#138 harden research diagnostics, decision-epoch alignment, and capture timeout headroom without changing candidate economics.
- PR #139 adds mid-capture V4 priority and research-only preemption.
- PR #141 (`f26a21da8d59bfa586a834b7ce58ee4dcc47149e`) adds the synchronous pre-recorder V4 gate.
- PR #142 (`9dc0c53f37227ae2f915015d9be2c3d58f6fdc1e`) isolates post-finalizer dashboard write scope.
- PR #145 (`0d2ac2f949e8b950930f2385b88cf0be768de24b`) makes safe-gap gating acquisition-aware and keeps candidate observation blocked behind refreshed authority completeness/disjointness.
- PR #146 (`5abca9cb38df855aa811a2d8a6b464c5a0c1be9d`) moves safe-gap polling to the 5-minute Actions floor without changing the fixed 1800-second capture.
- PR #148 (`48e387d39bf79a8b8de23aab1bdc949c86cfdec2`) refreshes the research dashboard after trusted authority sync.
- PR #149 (`6d0b6da32e4ec4a001ab2c45c175b91c25352cb3`) dispatches trusted authority synchronization after completed scheduled V4 runs.
- PR #151 (`2300acd546e03dc7cbca28f16fc4b8f68ce513c7`) fixes a CI-only recorder-test race; runtime is unchanged.
- PR #152 (`64a8f73a6e771ddd27de3587ad44ba0ef3532304`) adds the metadata-only acquisition-gap observer for future scheduled V4 `in_progress` events.
- **PR #154** (`d5c0cfb9e2914e70c782d3f575211a2295663050`) adds a self-bootstrap path restricted to pushes of the observer workflow file on `main`. It discovers only scheduled main-branch V4 run/job metadata, fails closed on ambiguity, and can only wake `research-daily-gap-dispatcher.yml`. It never starts/stops/retries V4, never sees V4 economics, and never dispatches research directly.

PR #154 verification:

- RED CI `33777273875`: expected missing-bootstrap failure only;
- exact-head CI `33777436656`: success;
- PR-context CI `33777589885`: success;
- merge `d5c0cfb9e2914e70c782d3f575211a2295663050`;
- post-merge main CI `33777785186`: success.

### Live #21 observer attachment

PR #154's merge immediately triggered **Research V4 Acquisition Gap Observer** run `33777785906` via the new `push` path. The run entered its `observe-acquisition` wait step and remains active while V4 #21's `acquire-evidence` job remains active.

This is a metadata-only attachment. When the unique #21 acquisition completes, the observer may wake `research-daily-gap-dispatcher.yml`. That dispatcher independently rechecks all active V4 acquisitions, active research campaigns, and the current UTC-day success cap before it can dispatch research. If a new protected V4 acquisition exists, the wake-up safely becomes a skip.

GitHub cron delivery has shown material drift, including no fresh five-minute safe-gap run during the observed window. Cron is therefore a redundant fallback, not timing authority.

---

## 6. Research run #8 resolved

Research run `33753704553` used pre-#139 control and overlapped delayed scheduled V4 run `33754093934`.

Canonical resolution:

- refreshed V4 completeness did not cover the bound research interval;
- `refresh-authority` failed with `fresh V4 authority does not cover bound research interval`, exit `70`;
- candidate observation/touch authorization and evaluation were skipped;
- **no authenticated checkpoint** and no research economics were admitted;
- finalizer rebased trusted authority and published the audit/registry;
- audit artifact `9894398717`;
- authoritative registry artifact `9894399329`.

This run is closed fail-closed audit evidence, not a research checkpoint.

---

## 7. Exact handoff / next action

1. Keep Phase 10 and live trading blocked.
2. Let protected V4 #21 (`33754093934`) finish naturally.
3. Observe live observer `33777785906`; it should stay attached while #21 acquisition is active and may wake the safe-gap dispatcher after the unique acquisition job completes.
4. Verify the safe-gap dispatcher rechecks all active V4 acquisitions, active research, and the UTC-day success cap before any research launch.
5. **Observe the implemented authoritative V4 interval/completeness synchronization path** when #21 completes and on the first subsequent research cohort that reaches a genuine acquisition-free gap.
6. For a launched research cohort, verify acquisition-aware preflight, synchronous pre-recorder recheck, mid-capture V4 preemption, fixed 1800-second capture, post-capture authority completeness refresh, canonical disjointness, authenticated evaluation, finalizer publication, and dashboard refresh.
7. Keep `scheduled-research-root` pinned to `721dc98c...` unless strategy code itself intentionally changes.
8. Fix future infrastructure defects with RED -> GREEN TDD, but never weaken V4 authority, overlap, completeness, touched-lineage, research authentication, or one-shot gates.
9. Keep research permanently **TOUCHED / NON-PROMOTIONAL**.
10. Admit only clean, complete, flat frozen-runtime V4 sources into `v4-mainnet-corpus`.
11. Let the frozen V4 one-shot check readiness only after trusted corpus updates; do not inspect interim V4 economics.
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
