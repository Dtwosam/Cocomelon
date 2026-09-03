# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing Cocomelon across ChatGPT chats. The live GitHub repository and authoritative repo docs always outrank this summary.

**Snapshot updated:** 2026-09-03  
**Repository:** `Dtwosam/Cocomelon`  
**Current verified `main` at snapshot:** `a2aa9456c119b1b59f3cfb5cf2a96b027e0ee2ef`  
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

The user expects autonomous engineering. Real-money activation remains a permanent exception: no live exchange order placement until objective promotion gates pass and the user explicitly authorizes live mode/capital.

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
- Never manually dispatch, retry, extend, or performance-condition V4 economic acquisition.
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

Issue #82 was refreshed at 2026-09-03 00:13 UTC:

- **9 accepted V4 cohorts**;
- **17 / 100 closed paper trades**;
- **3 / 30 closed-trade days**;
- **945 strategy decisions**;
- raw Phase 9 minimums: **NO**;
- economic edge: **Not measured yet**;
- live orders: **DISABLED**.

V4 run `33687935497` was actively recording the fixed public-mainnet acquisition when this snapshot was written. Let it finish naturally. Do not dispatch or retry V4.

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
- zero authenticated checkpoints;
- no research economic conclusion yet.

All research dashboard/report output must remain explicitly **TOUCHED / NON-PROMOTIONAL**.

---

## 5. Research operations now deployed

The research control plane is implemented and operational:

- `.github/workflows/research-campaign-scheduled.yml` — one paper-only public-mainnet research acquisition per workflow run, nominal daily schedule `2 7 * * *` UTC;
- `.github/workflows/research-v4-registry-sync.yml` — trusted, non-economic inventory of actual V4 acquisition intervals/completeness; publishes `research-authoritative-registry`;
- `.github/workflows/research-daily-gap-dispatcher.yml` — catches a missed UTC-day research cohort after scheduled V4 completion, but refuses while V4/research is active and stops after one successful research cohort that UTC day;
- `.github/workflows/research-dashboard.yml` — renders the dedicated touched/non-promotional research issue;
- `.github/workflows/research-dashboard-catchup.yml` — every-five-minute stale detector using Actions metadata only; dispatches the dashboard only when trusted source state is newer and caps catch-up to one prompt attempt per newer source.

Important reliability fixes already merged include:

- canonical fallback candidate `scheduled-research-root` when `RESEARCH_CANDIDATE_ID` is unset;
- empty GitHub run conclusions no longer corrupt shell field parsing;
- V4 authority sync recognizes both current split-job acquisition artifacts and trusted legacy acquisition artifact layout while keeping economics excluded;
- the authoritative registry/dashboard bootstrap and stale-refresh paths fail closed rather than fabricating state;
- daily research gap recovery is actual-run-state based and outcome-blind except for the one-success-per-UTC-day cap.

Live validation on 2026-09-03:

- last completed research run `33688074006` failed fast at `Refuse research capture while V4 acquisition is active`; candidate build/capture/evaluation were skipped and the audit/fallback authoritative registry was finalized;
- manual validation of `research-daily-gap-dispatcher.yml`, run `33698429640`, saw V4 `33687935497` in progress and exited successfully without dispatching research;
- dashboard catch-up run `33698137288` correctly detected that the latest dashboard already followed trusted research state and no-op'd instead of creating a duplicate refresh;
- main CI `33697969623` passed both full and research jobs after the catch-up retry-cap merge.

---

## 6. Exact handoff / next action

1. Keep Phase 10 and live trading blocked.
2. Continue naturally scheduled V4 acquisition unchanged; never manually dispatch/retry/performance-condition V4 cohorts.
3. Let the currently active V4 acquisition finish naturally.
4. When V4 completes, let `research-daily-gap-dispatcher.yml` decide whether one safe research cohort is still missing for the UTC day. Do not bypass its active-V4/active-research/daily-success guards.
5. If a research campaign starts, inspect its preflight/capture/authority-sync/evaluation path. Fix infrastructure defects with TDD, but never weaken V4 authority, overlap, completeness, touched-lineage, or research authentication gates to force success.
6. Keep research economics and issue #124 permanently **TOUCHED / NON-PROMOTIONAL**.
7. Admit only clean, complete, flat frozen-runtime V4 sources into `v4-mainnet-corpus`.
8. Let the frozen V4 one-shot check readiness after trusted corpus updates; do not inspect interim V4 economics.
9. Advance toward Phase 10 only if the authoritative untouched one-shot eventually reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

---

## 7. What not to do

- Do not use Hyperliquid testnet.
- Do not add live wallet/order/transfer/withdrawal behavior.
- Do not manually retry V4 because a cohort failed or produced an economic outcome.
- Do not import V4 economics/history into research.
- Do not turn research `RESEARCH_PROMISING` into direct promotion.
- Do not weaken provenance, overlap, gap, replay-completeness, flat-exposure, attestation, or authentication checks just to accumulate trades faster.
- Do not trust this file over newer live repo evidence.
