# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing Cocomelon across ChatGPT chats. Live GitHub state and authoritative repository docs always outrank this summary.

**Snapshot updated:** 2026-09-03  
**Repository:** `Dtwosam/Cocomelon`  
**Current verified `main` at snapshot:** `d1b18f28b5325eec5eb8b4d88a99662d925e68ea`  
**Venue:** Hyperliquid perpetual futures  
**Observation:** genuine public Hyperliquid mainnet  
**Execution:** paper/shadow only  
**Hyperliquid testnet:** forbidden  
**Live trading:** **DISABLED**  
**Real V4 economic edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

---

## 1. Authority and continuation rule

For every continuation, use this order:

1. current explicit user instruction;
2. `AGENTS.md`;
3. `docs/MASTER_SPEC.md`;
4. `docs/DECISIONS.md`;
5. `docs/BUILD_ORDER.md`;
6. active plan/spec under `docs/superpowers/`;
7. `docs/STATUS.md`;
8. this portable bootstrap.

Always inspect live `main`, recent Actions runs, open PRs/review threads, and current dashboard issues before acting. Do not rebuild work already merged. Use RED -> GREEN TDD for behavior changes and verify exact-head CI before guarded merges.

The user expects autonomous engineering. Real-money activation remains the permanent exception: no live exchange order placement until objective promotion gates pass and the user explicitly authorizes live mode/capital.

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
- Never manually dispatch, retry, extend, cancel for outcome reasons, or performance-condition V4 economic acquisition.
- Research is permanently **TOUCHED / NON-PROMOTIONAL** and cannot directly produce `CANDIDATE_EDGE`, mutate `v4-mainnet-corpus`, advance Phase 10, or enable live orders.

---

## 3. Frozen V4 Phase 9 lane

Active protocol: `v4-thesis-expiry-mainnet`.

Frozen acquisition/evaluation identity:

- execution runtime `0c14c9cfa37c80babc65d050fed6d4465dcb9032`;
- replay engine `phase8-v3-thesis-expiry`;
- replay config `phase9-baseline-replay-v3-thesis-expiry`;
- execution config `phase7-v2-4h-thesis-expiry`;
- frozen evaluator `efd33f8f89bc11e51c0e4f94591b9d8d1ce5b5ff`.

Frozen acquisition contract:

- 45-minute entry window;
- exact 4-hour maximum position age;
- fixed 5h15m total capture;
- schedule `37 1,7,13,19 * * *` UTC;
- one acquisition attempt per cohort;
- schedule-only economic acquisition;
- final admission only for clean transport, complete replay/dataset evidence, no gaps, and flat replay exposure.

Do not change V4 strategy/risk/execution/evaluator/curator/corpus/schedule/economics merely to improve counts or outcomes.

### Current V4 progress at this snapshot

Issue #82 was refreshed at **2026-09-03 12:15 UTC**:

- **11 accepted V4 cohorts**;
- **19 / 100 closed paper trades**;
- **4 / 30 closed-trade days**;
- **1,155 strategy decisions**;
- raw Phase 9 minimums: **NO**;
- economic edge: **Not measured yet**;
- live orders: **DISABLED**.

V4 run `33723341721` completed its protected acquisition and offline verification successfully. Curator run `33753694785` admitted it into `v4-mainnet-corpus`, producing corpus artifact `9892695744`.

The next naturally scheduled protected V4 run, `33754093934`, was active when this snapshot was written. Let it finish naturally. Do not manually dispatch, retry, extend, cancel, or performance-condition it.

---

## 4. D-023 dual-lane research

The research lane exists to reject weak ideas faster without contaminating V4 promotion evidence. Governing rule: **candidates may fail fast; candidates may not succeed fast**.

Research economics may use only source-time intervals proven disjoint from every actual V4 acquisition interval, including failed/diagnostic attempts. Ambiguous or overlapping batches fail closed as `REJECTED_CONTAMINATION`. Descendants inherit ancestor touched intervals.

Locked research decision asymmetry:

- economic futility cannot reject before 20 closed research trades;
- `RESEARCH_PROMISING` requires at least 40 closed research trades, at least 7 distinct closed-trade UTC days, and posterior `P(mu > 0) >= 0.80`;
- `RESEARCH_PROMISING` remains non-promotional;
- a selected challenger must be frozen and begin separate untouched validation only after a 6-hour embargo beyond the latest inherited touched interval.

Bootstrap planned risk remains 0.25% per trade (`0.0025`).

### Current research status

Issue #124 currently reports:

- candidate `scheduled-research-root`;
- state `draft`;
- **0 authenticated checkpoints**;
- no research economic conclusion yet.

All research dashboard/report output must remain explicitly **TOUCHED / NON-PROMOTIONAL**.

---

## 5. Research operations now deployed

The research control plane is implemented and operational:

- `.github/workflows/research-campaign-scheduled.yml` — one paper-only public-mainnet research acquisition per workflow run, nominal daily schedule `2 7 * * *` UTC;
- `.github/workflows/research-v4-registry-sync.yml` — trusted, non-economic inventory of actual V4 acquisition intervals/completeness; publishes `research-authoritative-registry`;
- `.github/workflows/research-daily-gap-dispatcher.yml` — catches a missed UTC-day research cohort after V4 completion, refuses while V4/research is active, and caps successful research acquisition to one cohort that UTC day;
- `.github/workflows/research-dashboard.yml` — renders the dedicated touched/non-promotional research issue;
- `.github/workflows/research-dashboard-catchup.yml` — every-five-minute stale detector using Actions metadata only; dispatches the dashboard only when trusted source state is newer and caps catch-up to one prompt attempt per newer source.

Important reliability fixes merged on 2026-09-03:

- **PR #136** recreates the candidate-decision diagnostics workspace before writing its sandbox-policy audit file, fixing the artifact-transfer empty-directory failure from research run `33714348425`;
- **PR #137** aligns only research captures to a fixed decision-relative phase so the first frozen decision remains inside the existing five-minute entry window, without changing that window or V4 timing/economics;
- **PR #138** raises only research `capture-control` timeout headroom to cover the deterministic alignment wait plus the unchanged 30-minute recorder and local freeze/bind/upload overhead;
- **PR #139** closes a time-of-check/time-of-use race between research preflight and delayed V4 schedule delivery. Current `main` now gives trusted `capture-control` read-only Actions visibility, strips `GITHUB_TOKEN` from the recorder subprocess, polls every 10 seconds for a newly active protected V4 workflow, aborts only the research recorder if V4 appears, and fails closed if Actions metadata becomes unavailable. Frozen V4 files and schedules are untouched.

PR #139 verification:

- exact-head push CI `33755384090`: success;
- exact PR-context CI `33755504363`: success;
- post-merge `main` CI `33755628640`: success;
- merge commit `d1b18f28b5325eec5eb8b4d88a99662d925e68ea`.

### Live race audit still unresolved at snapshot

Research run `33753704553` passed the old point-in-time no-active-V4 preflight before delayed V4 run `33754093934` materialized. It was launched from pre-#139 `main`, so it does not contain the new mid-capture watcher.

That run is **audit evidence only at this snapshot**. Let it finish naturally through the existing post-capture V4 authority/disjointness path. Do not manually cancel/retry it, do not assume its final outcome, and do not count it as a checkpoint unless the authenticated research registry actually publishes one.

The deployed #139 watcher applies to subsequent research runs from current `main` and gives V4 priority without modifying or delaying V4 itself.

---

## 6. Exact handoff / next action

1. Keep Phase 10 and live trading blocked.
2. Continue naturally scheduled V4 acquisition unchanged; never manually dispatch/retry/extend/performance-condition V4 cohorts.
3. Let active V4 run `33754093934` finish naturally.
4. Let old-code research run `33753704553` finish naturally through the canonical post-capture V4 authority/disjointness path; do not manually cancel or reinterpret it.
5. For subsequent research runs, preserve #139's mid-capture V4 watcher and fail-closed Actions-metadata behavior; V4 always has priority.
6. Fix future infrastructure defects with RED -> GREEN TDD, but never weaken V4 authority, overlap, completeness, touched-lineage, research authentication, or one-shot gates to force success.
7. Keep research economics and issue #124 permanently **TOUCHED / NON-PROMOTIONAL**.
8. Admit only clean, complete, flat frozen-runtime V4 sources into `v4-mainnet-corpus`.
9. Let the frozen V4 one-shot check readiness after trusted corpus updates; do not inspect interim V4 economics.
10. Advance toward Phase 10 only if the authoritative untouched one-shot eventually reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

---

## 7. What not to do

- Do not use Hyperliquid testnet.
- Do not add live wallet/order/transfer/withdrawal behavior.
- Do not manually retry V4 because a cohort failed or produced an economic outcome.
- Do not import V4 economics/history into research.
- Do not turn research `RESEARCH_PROMISING` into direct promotion.
- Do not weaken provenance, overlap, gap, replay-completeness, flat-exposure, attestation, or authentication checks just to accumulate trades faster.
- Do not use nominal cron timing as a substitute for actual V4 run-state/interval authority; GitHub schedule delivery can drift materially.
- Do not trust this file over newer live repo evidence.
