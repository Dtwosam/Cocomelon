# Cocomelon Project Status

**Last updated:** 2026-09-20  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified implementation baseline:** `58e88327188c6bea0374948ac228de15ff64ed4c`  
**Latest verified baseline CI:** run `35540772886` — success  
**Live trading:** **DISABLED**  
**Baseline edge:** **V4 RETIRED / TOUCHED — NO EDGE DEMONSTRATED**  
**Phase 10:** **BLOCKED**

## Current production state

The previously frozen V4 baseline `v4-baseline-4h-thesis-expiry` is retired under D-024. The user-authorized interim reveal permanently made that corpus TOUCHED / DEVELOPMENT-ONLY and showed negative gross and net expectancy. Future scheduled V4 economic acquisition and automatic V4 one-shot evaluation for that baseline are disabled.

The disclosed snapshot is bound to corpus artifact `10497424756` at exactly 100 closed trades / 18 closed-trade UTC days. The recorded development result was approximately:

- gross PnL: `-537.62`;
- net PnL: `-629.91`;
- mean net R: `-0.298`;
- profit factor: `0.44`;
- realized closed-trade maximum drawdown: `7.80%`.

This is failure/development evidence, not untouched OOS evidence and not a promotion claim.

One V4 acquisition that had already started before retirement, run `35524316366`, remains protected and must finish naturally. It is not cancelled, retried, extended, or outcome-conditioned. Its data remains historical/touched and cannot restore promotion eligibility for the retired baseline.

## Trusted V4 dashboard state

Latest trusted Evidence Dashboard snapshot, refreshed **2026-09-20 21:44 UTC**:

- **68 accepted V4 cohorts**;
- **120 closed paper trades**;
- **21 closed-trade days**;
- **7,145 strategy decisions**;
- economic edge: **RETIRED / TOUCHED — NO EDGE DEMONSTRATED**;
- V4 one-shot state: **retired / touched; automatic evaluation disabled**;
- future V4 scheduler state: **retired**;
- live orders: **DISABLED**.

The additional cohorts after the 100-trade reveal are historical/touched observations. They are not a continuation of untouched promotion evidence and are not used to retune the already frozen r2 thresholds.

## Active research frontier

Development now proceeds through D-023/D-024 touched research. Research remains **TOUCHED / NON-PROMOTIONAL**.

Active challenger:

### `research-r2-short-trend-quality-v1`

- registry state on the trusted dashboard: **draft**;
- authenticated checkpoints: **0**;
- closed research trades: **0**;
- parent: `scheduled-research-root`;
- pinned strategy code revision: `2ce088d69df01f044b0650b811b51015a5edda51`;
- execution max position age: **20 minutes**;
- strategy filter: only trend-led SHORT decisions with baseline score **72–81 inclusive** remain tradable;
- all LONG, non-trend, and out-of-band decisions are vetoed to NO_TRADE.

R2 was generated from the deliberately touched 100-trade V4 development sample. Its apparent in-sample subset economics are hypothesis-generation only. R2 must earn its own economics on new natural research cohorts.

The legacy r1 15-minute challenger remains historical research state and is no longer the active campaign default.

### Current root reference

Trusted Research Dashboard snapshot, refreshed **2026-09-20 21:06 UTC**:

- `scheduled-research-root`: **12 authenticated checkpoints**, **10 closed trades**, **7 closed-trade days**, cumulative touched net PnL about `-37.2371`, mean net R about `-0.14895`;
- legacy `research-r1-exit-15m-v1`: **7 checkpoints**, **6 trades**, **4 days**, cumulative touched net PnL about `-36.9098`, mean net R about `-0.24607`;
- r2: **0 authenticated checkpoints**.

None of these research results establishes verified edge.

## Research gates

Locked D-023 rules remain:

- candidates may fail fast; candidates may not succeed fast;
- minimum economic futility sample: **20 closed research trades**;
- reject for futility at >=20 trades if `P(mu > 0) < 0.05`;
- `RESEARCH_PROMISING` requires at least **40 closed research trades**, **7 distinct closed-trade UTC days**, `P(mu > 0) >= 0.80`, complete costs, and no integrity/contamination/hard-risk issues;
- `RESEARCH_PROMISING` is still TOUCHED / NON-PROMOTIONAL;
- any future clean validation begins only after candidate freeze, inherited touched-period handling, and the documented six-hour embargo;
- live promotion still requires every gate in `MASTER_SPEC.md`, including >=500 closed mainnet paper trades and >=45 calendar days of shadow operation.

## Control-plane state

The authoritative V4 interval/completeness synchronization path is implemented in `.github/workflows/research-v4-registry-sync.yml`; research admission continues to rely on actual authoritative coverage/disjointness rather than nominal scheduler timing.

PRs #205–#226 establish the current frontier:

- #205 added the deterministic r2 short-trend quality strategy seam;
- #206 registered and activated r2 as the research challenger default without dispatching economic evidence;
- #207 retired future V4 acquisition/automatic one-shot evaluation for the disclosed failed baseline;
- #208 restored pre-publication and final rollout-verifier enforcement for root+r2;
- #209 made the trusted dashboard one-shot state retirement-aware;
- #210 made r2 natural research the active execution plan and reconciled status with D-024;
- #211 made strategy-driven paper stop tightening update the materialized account atomically and survive restart;
- #212 refreshed the portable project handoff to the current r2 frontier;
- #214 advanced the active r2 plan through the verified stop-durability fix;
- #215 made paper restart reconciliation fail closed when the deterministic current `paper_position_events` record is missing or corrupted;
- #217 regression-locked LONG/SHORT tightened-stop restart durability and durable-write failure behavior;
- #219 made existing paper execution stores reject missing/unsupported schema versions without rewriting persisted metadata;
- #220 made journal/replay stores reject missing/unsupported schema versions without rewriting persisted metadata;
- #222 made durable paper order-plan write failures degrade execution health and block subsequent new exposure;
- #223 validates active-position opening-plan lineage on restart and runtime exit planning, failing closed on missing, unreadable, or tampered lineage;
- #224 makes funding-idempotency read errors degrade execution health before funding accounting can mutate state;
- #226 requires supported-version paper and journal/replay stores to be structurally complete before migration DDL, preventing deleted required tables from being silently recreated.

Post-#226 main CI `35540772886` passed compile, Ruff, mypy, full pytest, and research smoke.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Let the already-running pre-retirement V4 acquisition `35524316366` finish naturally; do not cancel, retry, extend, dispatch, or backfill it.
3. Do not resume scheduled V4 economic acquisition for the retired baseline and do not run its automatic Phase 9 one-shot.
4. Observe the implemented authoritative V4 interval/completeness synchronization path before admitting any subsequent research economics.
5. Let the next naturally eligible safe-gap research cohort launch through the dispatcher with root + `research-r2-short-trend-quality-v1`; do not manually dispatch the economic campaign merely to accelerate evidence.
6. Require `Verify root+challenger rollout contract before authoritative publish` to pass before an r2 checkpoint becomes authoritative.
7. Require the independent final rollout verifier to pass; otherwise the challenger checkpoint is not accepted as validated rollout evidence.
8. Keep r2 immutable while it gathers new research evidence; do not retune 72–81 or the SHORT/trend filters from later V4 outcomes.
9. At 20 closed r2 research trades, apply only the precommitted futility rule.
10. Do not label r2 `RESEARCH_PROMISING` before 40 trades, 7 days, `P(mu > 0) >= 0.80`, complete costs, and clean integrity/risk state.
11. Do not create or activate an r3 challenger merely to react to a handful of r2 outcomes. A future challenger requires a documented new hypothesis and inherited touched lineage.
12. If r2 becomes `RESEARCH_PROMISING`, freeze it, apply the touched-data embargo, and begin a new clean validation sample. The disclosed V4 corpus can never become untouched again.
13. Advance toward Phase 10 or live trading only after every locked clean-validation and promotion gate passes.

## Hard prohibitions

- Do not use Hyperliquid testnet.
- Do not enable live wallet/order/transfer/withdrawal behavior in evidence or research lanes.
- Do not weaken risk limits, provenance, overlap, replay completeness, attestation, authentication, daily research caps, or rollout-verifier gates to accumulate trades faster.
- Do not treat later V4 cohorts as fresh promotion evidence for the retired baseline.
- Do not relabel touched research as untouched OOS evidence.
- Do not use nominal cron timing as a substitute for actual V4 run/job/session interval authority.

**LIVE TRADING: DISABLED.**
