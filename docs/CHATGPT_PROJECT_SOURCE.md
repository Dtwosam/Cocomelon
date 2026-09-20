# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing Cocomelon across ChatGPT chats. Live GitHub state and authoritative repository docs always outrank this summary.

**Snapshot updated:** 2026-09-20  
**Repository:** `Dtwosam/Cocomelon`  
**Current verified `main` at snapshot:** `58e88327188c6bea0374948ac228de15ff64ed4c`  
**Latest verified main CI:** `35540772886` — success  
**Venue:** Hyperliquid perpetual futures  
**Observation:** genuine public Hyperliquid mainnet  
**Execution:** paper/shadow only  
**Hyperliquid testnet:** forbidden  
**Live trading:** **DISABLED**  
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

Future scheduled V4 acquisition and automatic V4 one-shot evaluation for the retired baseline are disabled. One acquisition that had already started before retirement, run `35524316366`, remains protected and must finish naturally without cancellation, retry, extension, backfill, or outcome conditioning.

Latest trusted dashboard snapshot recorded:

- 68 accepted V4 cohorts;
- 120 closed paper trades;
- 21 closed-trade days;
- 7,145 strategy decisions;
- economic edge: **RETIRED / TOUCHED — NO EDGE DEMONSTRATED**;
- live orders: **DISABLED**.

Later V4 cohorts are historical/touched only and may not be used to retune the locked r2 thresholds.

---

## 4. Active research frontier — r2

Active plan: `docs/superpowers/plans/2026-09-20-r2-natural-research-validation.md`.

Active challenger:

- candidate: `research-r2-short-trend-quality-v1`;
- parent: `scheduled-research-root`;
- strategy revision: `2ce088d69df01f044b0650b811b51015a5edda51`;
- execution max position age: 20 minutes;
- starting paper cash: 10,000;
- only trend-led SHORT decisions with baseline score 72–81 inclusive remain tradable;
- LONG, non-trend, and out-of-band decisions are vetoed to NO_TRADE;
- risk limits are unchanged;
- live orders remain disabled.

R2 was generated from touched V4 development evidence. It is a hypothesis, not proof of edge. Its thresholds are immutable while it gathers new natural research evidence.

Trusted research state at the 2026-09-20 21:06 UTC snapshot:

- `scheduled-research-root`: 12 authenticated checkpoints, 10 closed trades, 7 closed-trade days, touched net PnL about `-37.2371`;
- legacy `research-r1-exit-15m-v1`: 7 checkpoints, 6 trades, 4 days, touched net PnL about `-36.9098`;
- r2: draft, 0 authenticated checkpoints, 0 closed trades.

None of these results establishes verified edge.

---

## 5. Locked research gates

- Candidates may fail fast; candidates may not succeed fast.
- No futility rejection before 20 closed research trades.
- At >=20 closed r2 trades, reject for futility only if `P(mu > 0) < 0.05`.
- `RESEARCH_PROMISING` requires >=40 closed trades, >=7 distinct closed-trade UTC days, `P(mu > 0) >= 0.80`, complete costs, and clean integrity/risk state.
- `RESEARCH_PROMISING` remains TOUCHED / NON-PROMOTIONAL.
- Any future clean validation begins only after candidate freeze, inherited touched-period handling, and the documented six-hour embargo.
- Live promotion still requires every gate in `MASTER_SPEC.md`, including >=500 closed mainnet paper trades and >=45 calendar days of shadow operation.

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
- #226: rejects structurally incomplete supported-version paper and journal/replay stores before migration DDL can silently recreate missing required tables.

PR #226 merged as `58e88327188c6bea0374948ac228de15ff64ed4c`. Post-merge main CI `35540772886` passed compile, Ruff, mypy, full pytest, and research smoke.

---

## 7. Exact handoff / next action

1. Keep Phase 10 and live trading blocked.
2. Let protected pre-retirement V4 run `35524316366` finish naturally.
3. Do not resume retired-baseline V4 acquisition and do not run its automatic one-shot.
4. Observe authoritative V4 interval/completeness synchronization after the protected run resolves.
5. Let the next naturally eligible safe-gap research cohort launch through the existing dispatcher with root + r2. Do not manually dispatch economics merely to accelerate evidence.
6. Require the pre-publication root+r2 rollout verifier and the independent final rollout verifier to pass before an r2 checkpoint is authoritative.
7. Keep r2 immutable. Do not retune its 72–81 SHORT/trend filter from later V4 or r2 outcomes.
8. At 20 r2 trades, apply only the locked futility rule.
9. Do not label r2 `RESEARCH_PROMISING` before 40 trades, 7 days, posterior >=0.80, complete costs, and clean integrity/risk state.
10. Do not create r3 merely in reaction to a few r2 outcomes; require a documented new hypothesis and inherited touched lineage.
11. If r2 becomes `RESEARCH_PROMISING`, freeze it, apply the touched-data embargo, and start a new clean validation sample.
12. Advance toward Phase 10 or live trading only after every locked validation/promotion gate passes.

---

## 8. What not to do

- Do not use Hyperliquid testnet.
- Do not add live wallet/order/transfer/withdrawal behavior.
- Do not manually cancel/retry/extend/backfill protected V4 or research economics to accelerate results.
- Do not relabel touched evidence as untouched.
- Do not weaken provenance, overlap, completeness, replay, attestation, authentication, daily caps, or rollout-verifier gates.
- Do not use nominal scheduler timing as a substitute for actual run/job/session authority.
- Do not trust this file over newer live repository evidence.
