# Cocomelon Project Status

**Last updated:** 2026-08-28  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified V3 execution runtime:** `f8f84200dbc8b6fb262c5f6f99993b40714357be`  
**Frozen V3 Phase 9 evaluator:** `39c2f6a57c0b2db9929fa4050e4c1f47e55f55ed`  
**Live trading:** **DISABLED**  
**Real baseline edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

## Current production state

The active evidence-acquisition protocol is **V3 lifecycle-aware mainnet evidence**. It uses genuine public Hyperliquid mainnet data and paper execution only. The opportunity window is fixed at 45 minutes and the total capture is fixed at four hours, leaving 3 hours 15 minutes for closeout-only observation. No PnL, final equity, profitability, or edge value can alter acquisition length, retry, admission, corpus selection, or the one-shot evaluation boundary.

The active V3 acquisition contract is:

- **45-minute entry window** (`2700` seconds);
- **4-hour total capture** (`14400` seconds);
- **3h15m closeout-only observation** after the entry cutoff;
- **4 scheduled cohorts per day** at `37 1,7,13,19 * * *` UTC;
- one acquisition attempt per cohort;
- hard failure if evidence is incomplete, gapped, unverifiable, or still exposed at the endpoint;
- no forced close solely to make a cohort admissible;
- no performance-based retry or retrospective extension;
- execution runtime pinned to `f8f84200dbc8b6fb262c5f6f99993b40714357be`.

The longer lifecycle was frozen before any V3 cohort had been accepted, so no accepted V3 economic evidence is mixed across lifecycle definitions.

## Execution defect repaired before V3 evidence acceptance

Rejected Campaign V3 evidence exposed a paper-execution defect in reduce-only stop handling. A position had crossed its stop, but every new book update recreated the exit plan and reset modeled latency, causing repeated `LATENCY_NOT_ELAPSED` rejection instead of allowing the pending stop intent to mature.

PR #88 fixed this by retaining a latency-blocked reduce-only intent and retrying the same order plan on later L2 updates. Once modeled latency has elapsed, the normal IOC simulation can run. The pending intent is cleared after the first real IOC attempt. The repair did not bypass latency or loosen any signal, stop, risk, sizing, evidence-admission, or live-order rule.

Verification for the repair:

- RED CI `33170601237` reproduced the plan-ID reset;
- GREEN CI `33170853723` passed compile, Ruff, mypy, full pytest, and research tests;
- exact PR CI `33170921370` passed;
- PR #88 merged at `f8f84200dbc8b6fb262c5f6f99993b40714357be`.

PR #89 then activated the repaired four-hour V3 acquisition protocol and merged at `1dbd6164ce3f4bd3e6cebd94fe41074dcb2d80c0`. Post-merge main CI `33171533333` passed.

## Active V3 evidence progress

V3 starts from a clean lifecycle-aware protocol boundary and does not inherit V2 counts.

Current accepted V3 evidence remains:

- **0 accepted V3 cohorts**;
- **0 / 100 closed paper trades**;
- **0 / 30 closed-trade days**;
- **0 V3 strategy decisions in accepted corpus**;
- **no economic edge claim**;
- **live orders disabled**.

A trusted `v3-mainnet-corpus` has not yet been established under the repaired four-hour protocol. Rejected recordings remain diagnostic evidence only and do not advance the economic gate.

## Historical V2 evidence

The final trusted V2 corpus remains preserved for audit/history only:

- **3 accepted genuine-mainnet V2 cohorts**;
- **45 strategy decisions**;
- **0 closed paper trades**;
- **0 closed-trade days**;
- last trusted corpus artifact ID `9621177153`;
- no demonstrated economic edge;
- live orders disabled.

V2 evidence is never counted as V3 readiness because the lifecycle protocol differs.

## V3 campaign and curator boundary

`.github/workflows/evidence-campaign-scheduled.yml` is the active acquisition workflow. It is mainnet-only, paper-only, pinned to the repaired V3 runtime, and ordinary repository pushes do not launch the expensive evidence campaign.

`.github/workflows/evidence-corpus-curator-v3.yml` is the isolated V3 admission path. It:

1. requires the exact V3 source artifact and pinned runtime identity;
2. independently verifies genuine-mainnet, paper-only semantics;
3. requires clean transport plus complete replay/dataset evidence;
4. requires the fixed 45-minute entry / four-hour capture protocol identity;
5. requires flat replay exposure before corpus mutation;
6. rebuilds or extends only `v3-mainnet-corpus`;
7. never counts failed or unverified sources merely because a workflow ran;
8. never mixes historical V2 evidence into V3.

If a cohort is still open at four hours, it fails closed. The protocol never extends an individual cohort because a trade is winning or losing.

## Explicit V3 Phase 9 evaluation handoff

PR #90 added the explicit V3 Phase 9 evaluator and merged at `39c2f6a57c0b2db9929fa4050e4c1f47e55f55ed`. The historical V2 evaluator source was deliberately left untouched.

The V3 evaluator requires the exact repaired source protocol:

- protocol `v3-lifecycle-aware-mainnet`;
- pinned execution runtime `f8f84200dbc8b6fb262c5f6f99993b40714357be`;
- replay engine `phase8-v2-lifecycle-aware`;
- replay config `phase9-baseline-replay-v2-lifecycle-aware`;
- entry window `2700` seconds;
- capture window `14400` seconds;
- `economic_claim: none` at acquisition time;
- `live_orders: false`.

It uses distinct identities:

- snapshot: `v3-phase9-frozen-snapshot`;
- evaluation: `v3-phase9-evaluation`;
- candidate: `v3-baseline-fixed`.

`protocol.json` is copied into the frozen snapshot, hashed with the other immutable inputs, and bound by a canonical protocol digest. A corpus or snapshot with any incompatible runtime/window/protocol identity is rejected rather than silently reinterpreted.

The evaluator reuses the locked Phase 9 statistical engine and policy unchanged. The V3 handoff changes provenance and artifact identity only; it does not relax the economic promotion standard.

## Immutable V3 one-shot execution boundary

`.github/workflows/phase9-v3-one-shot.yml` is the production one-shot handoff. It runs only after a successful exact `Verified V3 Mainnet Evidence Corpus Curator` completion and uses only that curator's trusted `v3-mainnet-corpus` artifact.

The workflow:

1. pins evaluator revision `39c2f6a57c0b2db9929fa4050e4c1f47e55f55ed` and verifies the checkout SHA;
2. prepares a local-only V3 Phase 9 snapshot candidate with no exchange/network/live arguments;
3. evaluates readiness under the fixed 47-day one-shot protocol without inspecting economic performance to decide whether to continue collecting;
4. if the fixed test window is incomplete, produces no final OOS result and later trusted corpus growth may be checked again;
5. if the fixed test window is complete but the locked evidence minimums are not met, writes one terminal `v3-phase9-terminal-insufficient` readiness-only result;
6. if readiness passes, uploads `v3-phase9-frozen-snapshot` **before** running untouched evaluation, then writes `v3-phase9-evaluation`;
7. persists the first final outcome to append-once branch `phase9-v3-protocol-state`, file `phase9-v3-final.json`;
8. refuses to replace a different durable final state;
9. also refuses to create a replacement OOS result if a prior frozen/evaluation/terminal artifact exists but durable state persistence is missing, preventing accidental retesting on newer data;
10. keeps the evaluation job read-only; only the separate persistence job receives narrow `contents: write` permission.

The durable state uses protocol ID `v3-phase9-one-shot`, records the frozen evaluator revision, source curator run, attestation, source-protocol digest, snapshot/readiness, and exactly one final outcome. Network access and live orders are recorded as false.

## Evidence dashboard

Issue #82 is the canonical human-readable evidence tracker:

`https://github.com/Dtwosam/Cocomelon/issues/82`

The dashboard treats V3 as active and V2 as historical. Historical counts are never added to V3 progress. The dashboard is informational only and cannot enable real-money trading or change strategy/risk behavior.

## Locked economic gate

Before any Phase 10 promotion, genuine untouched V3 evidence must satisfy at least:

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

The frozen historical V2 one-shot evaluator remains revision `629db6294822c97690c006591802f8a47e08652e`. V3 evidence is never silently fed into that V2 identity.

## Locked safety/product invariants

- Hyperliquid testnet is forbidden.
- Market observation is Hyperliquid mainnet only.
- Default and current execution is paper/shadow.
- No live exchange adapter is enabled or authorized.
- No wallet/private-key signing, transfer, withdrawal, or private-account execution path is part of the evidence campaign.
- Whole-market discovery remains dynamic; eligibility is separate from ranking.
- Explainable deterministic baselines remain first-class before ML; `NO_TRADE` is valid.
- Strategy cannot size positions or send orders; independent risk has final veto.
- No averaging down, martingale, or stopless positions.
- No historical L2/order flow may be fabricated from candles.
- Real-money activation requires explicit later authorization after all promotion gates pass.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Let the repaired four-hour V3 campaign collect genuine mainnet paper evidence without intervention.
3. Verify each cohort for transport cleanliness, entry-cutoff enforcement, exit execution, replay/dataset completeness, and final flatness without using PnL for admission decisions.
4. Let the V3 curator create/extend `v3-mainnet-corpus` only from verified eligible cohorts.
5. Let the V3 one-shot workflow check readiness after trusted corpus updates while the fixed test window is still incomplete.
6. Once the fixed test window reaches its terminal boundary, allow exactly one readiness-only insufficient result or one frozen untouched evaluation; never retry on later data after a final result exists.
7. Advance toward Phase 10 only if the one-shot V3 evaluation reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Profitability and live-trading status

**REAL BASELINE EDGE: UNMEASURED.**

No currently verified result demonstrates repeatable economic edge. `UNMEASURED` is not the same as `NO_EDGE_DEMONSTRATED`.

**LIVE TRADING: DISABLED.**
