# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing Cocomelon across ChatGPT chats. Live GitHub state and authoritative repository docs always outrank this summary.

**Snapshot updated:** 2026-09-21  
**Repository:** `Dtwosam/Cocomelon`  
**Current verified `main` at snapshot:** `31a977ab2fd5fb6398314adf8c7b365e16b303f0`  
**Latest verified development CI:** `35609936635` on PR #235 implementation head — success  
**Venue:** Hyperliquid perpetual futures  
**Observation:** genuine public Hyperliquid mainnet  
**Execution:** paper/shadow only  
**Hyperliquid testnet:** forbidden  
**Live trading:** **DISABLED**  
**Phase 10:** **OFFLINE LEARNING ENGINEERING ACTIVE; PROMOTION/LIVE BLOCKED**

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

Always inspect live `main`, recent Actions runs, open PR/review state, active V4 jobs, and trusted dashboard state before acting. Do not rebuild already-merged work. Use RED -> GREEN TDD for behavior changes and verify exact-head, PR-context, and post-merge CI before claiming integration is green.

The user expects autonomous engineering. Real-money activation is the permanent exception: no live exchange order placement until objective promotion gates pass and the user explicitly authorizes live mode/capital.

---

## 2. Locked safety boundaries

- Hyperliquid testnet is forbidden.
- Runtime observations are public Hyperliquid mainnet only.
- Current/default execution is paper/shadow.
- No wallet/private-key signing, transfer, withdrawal, or private-account execution belongs in research/evidence workflows.
- Strategy cannot bypass independent risk.
- No averaging down, martingale/loss-recovery sizing, or stopless positions.
- `NO_TRADE` is first-class.
- Historical L2/order flow may not be fabricated from candles.
- Research is **TOUCHED / NON-PROMOTIONAL** and cannot directly advance Phase 10 or enable live orders.

---

## 3. Retired V4 baseline

The formerly frozen `v4-baseline-4h-thesis-expiry` was explicitly revealed and retired under D-024.

The 100-trade / 18-day development snapshot was negative:

- gross PnL about `-537.62`;
- net PnL about `-629.91`;
- mean net R about `-0.298`;
- profit factor about `0.44`;
- realized closed-trade maximum drawdown about `7.80%`.

This evidence is permanently **TOUCHED / DEVELOPMENT-ONLY** and cannot become untouched OOS evidence.

Future scheduled V4 acquisition and automatic V4 one-shot evaluation for the retired baseline are disabled. The one acquisition that had already started before retirement, run `35524316366`, finished successfully and naturally without cancellation, retry, extension, backfill, or outcome conditioning. Authority sync/curation accepted its actual interval into the retired touched corpus.

Latest trusted dashboard snapshot recorded:

- 69 accepted V4 cohorts;
- 121 closed paper trades;
- 21 closed-trade days;
- 7,250 strategy decisions;
- economic edge: **RETIRED / TOUCHED — NO EDGE DEMONSTRATED**;
- live orders: **DISABLED**.

Later V4 cohorts are historical/touched only and may not be used to retune the locked r2 thresholds.

---

## 4. Active research frontier — historical two-sided learning

Primary plan: `docs/superpowers/plans/2026-09-21-historical-directional-learning.md`.

D-025 changes the primary architecture from a hand-filtered short-only challenger to a historical, direction-neutral learner.

Target behavior:

- study trustworthy historical market states across the dynamically eligible coin universe;
- reconstruct only features that were known at each historical timestamp;
- label future LONG and SHORT outcomes at predeclared horizons;
- learn side-specific expected net opportunity;
- choose LONG, SHORT, or NO_TRADE from evidence;
- keep eligibility and the independent risk engine as hard veto authorities;
- use chronological train/validation/test partitions plus embargo/walk-forward validation;
- never fabricate missing historical microstructure or leak future information into features.

Phase 9 satisfied its exit condition by honestly demonstrating that the retired V4 baseline did not show edge. **Phase 10 offline learning engineering is active.** Live trading and promotion remain blocked.

Current implementation frontier:

- deterministic bounded candle request windows respect the 5,000-candle ceiling;
- exact-timestamp outcomes record both LONG and SHORT gross returns and omit missing exact targets;
- resumable public-mainnet candle/funding backfill persists raw page envelopes and normalized records;
- source manifests preserve deterministic checksums, request/observed coverage, and gaps;
- funding page boundaries intentionally overlap for authenticated deduplication; conflicting duplicates fail closed;
- `cocomelon-historical-backfill` orchestrates multiple canonical markets/intervals through the existing rate-budgeted `InfoClient`;
- deterministic combined coverage reports preserve source/market/interval provenance;
- no model family or decision threshold is selected yet.

PR #235 implementation head `0b463d515b2f0914a1ff7aae5ddc8682a12b931d` passed CI run `35609936635` with compile, Ruff, strict mypy, full pytest, and research smoke.

### Preserved r2 experiment

`research-r2-short-trend-quality-v1` remains immutable and auditable as a secondary touched short-side hypothesis:

- parent: `scheduled-research-root`;
- strategy revision: `2ce088d69df01f044b0650b811b51015a5edda51`;
- execution max position age: 20 minutes;
- frozen r2-only rule: trend-led SHORT, baseline score 72–81 inclusive;
- trusted state: draft, 0 authenticated checkpoints, 0 closed trades.

The failed r2 attempt from natural campaign `35551385941` remains failed / NOT COUNTED and is never retried or backfilled. PR #228 fixed the shared replay-identity defect for future research, but r2 is no longer the product architecture or the sole gate to learning development.

Trusted research reference at the 2026-09-21 09:58 UTC snapshot:

- `scheduled-research-root`: 13 authenticated checkpoints, 10 closed trades, 7 closed-trade days, touched net PnL about `-37.2371`;
- legacy `research-r1-exit-15m-v1`: 7 checkpoints, 6 trades, 4 days, touched net PnL about `-36.9098`;
- r2: 0 authenticated checkpoints.

None of these results establishes verified edge.

---

## 5. Locked research and promotion gates

For registered touched economic candidates, D-023 fast-failure/promising rules remain intact.

For historical-learning candidates under D-025:

- historical backtests and training results are touched development evidence;
- feature rows may use only information available at the anchor timestamp;
- future observations appear only in explicit labels;
- train/validation/test order is chronological;
- test data cannot tune features, hyperparameters, costs, or decision thresholds;
- walk-forward evaluation is mandatory;
- LONG and SHORT are both available; NO_TRADE remains first-class;
- model output cannot weaken or bypass hard risk limits;
- a promising model must be frozen before any clean future validation begins;
- live promotion still requires all `MASTER_SPEC.md` gates, including >=500 closed mainnet paper trades, >=45 calendar days shadow, positive cost-complete untouched OOS/walk-forward evidence, acceptable drawdown/concentration, clean integrity, and explicit user authorization.

---

## 6. Current control-plane and paper-execution state

The authoritative V4 interval/completeness synchronization path remains in `.github/workflows/research-v4-registry-sync.yml`. Research admission depends on actual authoritative V4 coverage/disjointness, never nominal cron timing.

Recent frontier PRs:

- #205: added the deterministic r2 short-trend quality strategy seam;
- #206: registered and activated r2 as the research challenger default without economic dispatch;
- #207: retired future V4 acquisition/automatic one-shot evaluation for the disclosed failed baseline;
- #208: restored pre-publication and final rollout-verifier enforcement for root+r2;
- #209: made the trusted dashboard retirement-aware;
- #210: made r2 natural research the active execution plan;
- #211: fixed strategy-driven paper stop tightening so the updated stop is materialized atomically and survives restart;
- #212: refreshed the portable handoff to the current r2 frontier;
- #214: advanced the active r2 plan through the verified stop-durability fix;
- #215: fails paper restart reconciliation closed when the deterministic current immutable position event is missing or corrupted;
- #217: regression-locks LONG/SHORT tightened-stop persistence and fail-closed behavior on durable write failure;
- #219: rejects missing/unsupported paper execution store schema versions without rewriting them;
- #220: rejects missing/unsupported journal/replay store schema versions without rewriting them;
- #222: fails paper execution closed when durable order-plan persistence fails;
- #223: validates active-position opening-plan lineage on restart and runtime exit planning;
- #224: fails paper execution closed on funding-idempotency read errors before accounting mutation;
- #226: rejects structurally incomplete supported-version paper and journal/replay stores before migration DDL can silently recreate missing required tables;
- #228: scopes research replay identity uniqueness by candidate and transactionally migrates the legacy global-unique registry so root+r2 can share one authenticated capture replay identity;
- #230: attributes raw candidate-local terminal runner failures to the `evaluate-research` dashboard stage without changing checkpoint accounting;
- #232: authenticates persisted paper execution attempts/fills during restart, reconciles deterministic IDs and fill totals, rejects orphaned/inconsistent history, and enforces fill -> attempt identity at write time.

PR #232 merged as `09e5c93db64ede19ec6ad02ac642defc96176c27`. Post-merge main CI `35596674099` passed compile, Ruff, mypy, full pytest, and research smoke. Research Dashboard refresh `35586218717` remains trusted and renders the failed r2 attempt as `evaluate-research` / NOT COUNTED.

---

## 7. Exact handoff / next action

1. Keep live trading disabled and risk limits unchanged.
2. Use `docs/superpowers/plans/2026-09-21-historical-directional-learning.md` as the primary plan.
3. Preserve retired V4, r1, and r2 evidence as touched/auditable history.
4. Treat the verified Slice B source-acquisition contracts as the immutable input boundary for historical learning.
5. Reconstruct point-in-time candle/funding feature states without synthesizing unavailable L2/order-flow/OI data.
6. Represent historically unavailable fields explicitly and preserve feature provenance.
7. Join features to exact multi-horizon LONG/SHORT outcomes and export versioned analytical training datasets.
8. Establish simple direction-neutral baselines, then compare more complex supervised models only if justified.
9. Use chronological validation/embargo/walk-forward evaluation and cost-aware NO_TRADE calibration.
10. Freeze any promising model/config before new clean validation; never relabel historical development data as untouched.
11. Advance toward live trading only after every locked promotion gate and explicit user authorization.

---

## 8. What not to do

- Do not use Hyperliquid testnet.
- Do not add live wallet/order/transfer/withdrawal behavior.
- Do not manually cancel/retry/extend/backfill protected V4 or research economics to accelerate results.
- Do not relabel touched evidence as untouched.
- Do not weaken provenance, overlap, completeness, replay, attestation, authentication, daily caps, or rollout-verifier gates.
- Do not use nominal scheduler timing as a substitute for actual run/job/session authority.
- Do not trust this file over newer live repository evidence.
