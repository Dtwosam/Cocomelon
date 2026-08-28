# Cocomelon Project Status

**Last updated:** 2026-08-28  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified V4 execution runtime:** `28db668048a83da7f7b1ba92ae2cf50aa980cb6e`  
**V4 acquisition activation merge:** `2c224a304f4c35d50b511338390e8f7ac4b6550b`  
**Frozen V4 Phase 9 evaluator:** `0b7b126d19306679c029807b2e2e86d614fb8847`  
**Live trading:** **DISABLED**  
**Real baseline edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

## Current production state

The active evidence protocol is **V4 thesis-expiry mainnet evidence**. It uses genuine public Hyperliquid mainnet data with paper execution only.

The frozen V4 acquisition contract is:

- fixed **45-minute entry window** (`2700` seconds);
- exact **4-hour maximum position age** (`14400` seconds);
- fixed **5h15m total capture** (`18900` seconds);
- **4 scheduled cohorts per day** at `37 1,7,13,19 * * *` UTC;
- one acquisition attempt per cohort;
- no PnL-, equity-, profitability-, or outcome-conditioned retry or extension;
- no forced close solely to make a cohort admissible;
- final cohort admission requires clean transport, complete replay/dataset evidence, empty gap refs, and flat replay exposure;
- live orders remain disabled.

Exact V4 evidence identity:

- protocol `v4-thesis-expiry-mainnet`;
- runtime `28db668048a83da7f7b1ba92ae2cf50aa980cb6e`;
- replay engine `phase8-v3-thesis-expiry`;
- replay config `phase9-baseline-replay-v3-thesis-expiry`;
- execution config `phase7-v2-4h-thesis-expiry`.

V3 scheduled acquisition is retired. Its workflow remains manual-only for frozen audit/reproduction and cannot compete with V4 scheduled evidence.

## Active V4 evidence progress

At the V4 activation boundary:

- **0 accepted V4 cohorts**;
- **0 / 100 closed paper trades**;
- **0 / 30 closed-trade days**;
- **no V4 economic edge claim**;
- **live orders disabled**.

No V4 scheduled cohort had completed at the time this status revision was prepared. Rejected or incomplete recordings remain diagnostic only and never advance the economic gate.

## V4 acquisition and isolated curator

`.github/workflows/evidence-campaign-v4-scheduled.yml` is the active acquisition workflow. It is paper-only, mainnet-only, fixed-duration, and pinned to the immutable V4 runtime.

`.github/workflows/evidence-corpus-curator-v4.yml` is the only V4 admission path. It:

1. accepts only completed exact V4 campaign sources;
2. verifies repository/workflow provenance before trusting artifacts;
3. requires the exact V4 runtime/replay/config/execution identity;
4. fails closed on incomplete replay, incomplete dataset, gaps, or open exposure;
5. writes only `v4-mainnet-corpus`;
6. never imports V3 or V2 corpus evidence;
7. never uses interim economic outcomes for admission decisions.

## V4 Phase 9 evaluator handoff

PR #106 merged the V4 evaluator at `0b7b126d19306679c029807b2e2e86d614fb8847` after exact PR CI passed.

The V4 evaluator uses distinct immutable identities:

- snapshot `v4-phase9-frozen-snapshot`;
- evaluation `v4-phase9-evaluation`;
- candidate `v4-baseline-fixed`.

It requires the exact V4 `protocol.json`, copies and hashes that protocol into the frozen snapshot, binds the canonical protocol digest, and rejects incompatible source/snapshot identity rather than silently reinterpreting evidence.

The statistical engine and `EvaluationPolicy()` are unchanged. V4 changes lifecycle provenance and artifact identity only; it does not relax Phase 9 promotion thresholds.

## Immutable V4 one-shot boundary

`.github/workflows/phase9-v4-one-shot.yml` is the V4 one-shot handoff. It consumes only a successful exact `Verified V4 Mainnet Evidence Corpus Curator` run and pins evaluator revision `0b7b126d19306679c029807b2e2e86d614fb8847`.

The one-shot workflow:

1. verifies the triggering curator provenance;
2. downloads exactly one trusted `v4-mainnet-corpus` artifact from that curator;
3. prepares a local-only frozen V4 snapshot with no exchange/network/live arguments;
4. preserves the locked fixed-window readiness logic;
5. persists a permanent append-once freeze lock to `phase9-v4-protocol-state/phase9-v4-freeze.json` before economic evaluation;
6. refuses to select a replacement OOS corpus after the freeze exists;
7. emits a readiness-only terminal insufficient result if the fixed protocol reaches its terminal boundary without enough evidence;
8. otherwise evaluates exactly the frozen snapshot once and persists the final state to `phase9-v4-protocol-state/phase9-v4-final.json`;
9. keeps preparation/evaluation jobs read-only, with narrow write permission isolated to state persistence;
10. records `network_access: false` and `live_orders: false` in immutable state.

## Evidence dashboard

Issue #82 remains the canonical human-readable tracker:

`https://github.com/Dtwosam/Cocomelon/issues/82`

The dashboard now treats **V4 as active** and V3/V2 as historical. Historical counts are never added to V4 progress.

Routine dashboard output exposes operational/provenance state only. Before an immutable V4 final result exists, **Economic edge remains `Not measured yet`**. It does not expose interim PnL, final equity, mean net R, win rate, profit factor, bootstrap values, or other tuning-sensitive economic fields.

After a valid append-once V4 final state exists, the dashboard may expose only the high-level terminal/evaluated verdict after verifying canonical IDs, freeze binding, one-shot identity, snapshot identity, offline-only semantics, and exact V4 evaluation identity.

## Historical V3 evidence

V3 is retained for audit/history only and does not advance V4 readiness.

Current trusted V3 state remains:

- **0 accepted V3 cohorts**;
- **0 closed paper trades**;
- **0 closed-trade days**;
- no V3 economic edge claim.

The frozen historical V3 runtime is `f8f84200dbc8b6fb262c5f6f99993b40714357be`; its Phase 9 evaluator is `39c2f6a57c0b2db9929fa4050e4c1f47e55f55ed`.

## Historical V2 evidence

The final trusted V2 corpus remains preserved for audit/history only:

- **3 accepted genuine-mainnet V2 cohorts**;
- **45 strategy decisions**;
- **0 closed paper trades**;
- **0 closed-trade days**;
- last trusted corpus artifact ID `9621177153`;
- no demonstrated economic edge.

V2 evidence is never counted toward V4 readiness.

## Locked economic gate

Before any Phase 10 promotion, genuine untouched V4 evidence must satisfy at least:

- 100 untouched OOS closed trades;
- 30 OOS covered closed-trade days;
- 3 eligible walk-forward windows;
- 20 trades per eligible walk-forward window;
- 20 trades per score bucket;
- at least 60% positive eligible walk-forward windows;
- 95% bootstrap confidence;
- 5-day day-block bootstrap;
- 2,000 bootstrap resamples;
- 6-hour split embargo;
- sampled `NO_TRADE` horizons of 1 hour and 4 hours.

`CANDIDATE_EDGE` additionally requires positive untouched-test mean net R, a bootstrap lower confidence bound above zero, stable positive walk-forward behavior, market positive-PnL concentration no greater than 35%, and seven-day concentration no greater than 50%.

## Locked safety/product invariants

- Hyperliquid testnet is forbidden.
- Market observation is Hyperliquid mainnet only.
- Default/current execution is paper/shadow.
- No live exchange adapter is enabled or authorized.
- No wallet/private-key signing, transfer, withdrawal, or private-account execution path is part of the evidence campaign.
- Strategy cannot size positions or send orders; independent risk has final veto.
- `NO_TRADE` remains first-class.
- No averaging down, martingale, or stopless positions.
- No historical L2/order flow may be fabricated from candles.
- Real-money activation requires explicit later authorization after every promotion gate passes.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Let scheduled V4 cohorts collect genuine mainnet paper evidence under the fixed thesis-expiry contract.
3. Admit only clean, complete, flat V4 cohorts into `v4-mainnet-corpus`.
4. Let the V4 one-shot workflow check fixed-protocol readiness after trusted corpus updates.
5. Once the fixed terminal boundary is reached, permit exactly one readiness-only insufficient result or one frozen untouched evaluation; never retest on newer data after a final state exists.
6. Advance toward Phase 10 only if the immutable V4 one-shot result reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Profitability and live-trading status

**REAL BASELINE EDGE: UNMEASURED.**

No currently verified result demonstrates repeatable economic edge. `UNMEASURED` is not the same as `NO_EDGE_DEMONSTRATED`.

**LIVE TRADING: DISABLED.**
