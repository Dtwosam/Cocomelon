# Cocomelon Project Status

**Last updated:** 2026-08-28  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified execution runtime:** `f8f84200dbc8b6fb262c5f6f99993b40714357be`  
**Live trading:** **DISABLED**  
**Real baseline edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

## Current production state

The active evidence-acquisition protocol is **V3 lifecycle-aware mainnet evidence**. It uses genuine public Hyperliquid mainnet data, paper execution only, a fixed entry window, and a longer fixed closeout-only observation window. No PnL, final equity, profitability, or edge value may alter acquisition length, retry, admission, or corpus selection.

The next pinned V3 campaign revision is `f8f84200dbc8b6fb262c5f6f99993b40714357be`, which contains the verified reduce-only latency repair from PR #88. The campaign protocol is fixed at:

- **45-minute entry window** (`2700` seconds);
- **4-hour total capture** (`14400` seconds);
- therefore **3 hours 15 minutes of closeout-only observation** after the entry cutoff;
- **4 scheduled cohorts per day**, at `37 1,7,13,19 * * *` UTC;
- one acquisition attempt per cohort;
- hard failure if evidence is incomplete, gapped, unverifiable, or still exposed at the endpoint;
- no forced close solely to make a cohort admissible;
- no performance-based retry or retrospective extension.

The longer window is a pre-evidence protocol change: V3 still has zero accepted cohorts, so no accepted V3 economic evidence is being mixed across lifecycle definitions.

## Execution defect found from rejected V3 evidence

Scheduled Campaign V3 run `33131799366` recorded a genuine mainnet cohort with 111,736 market events, 30 strategy decisions, two paper risk approvals, four fills, and two opened positions. The cohort was correctly rejected because replay/dataset evidence remained incomplete and both positions were still open at the hard endpoint.

Inspection separated two cases:

- one position was legitimately still open under the strategy at the endpoint;
- another had crossed its stop, but its paper reduce-only exit could never become executable because each market update created a fresh exit plan and reset the modeled latency clock. Every fresh plan was rejected as `LATENCY_NOT_ELAPSED`.

PR #88 fixed that execution/replay defect. A latency-blocked reduce-only intent is now retained and retried as the same order plan on later L2 updates. Once modeled latency has elapsed, that plan can receive its normal IOC simulation. The pending intent is cleared after the first real IOC attempt. This preserves latency realism rather than bypassing latency.

TDD evidence for the repair:

- RED CI `33170601237` reproduced the plan-ID reset;
- GREEN push CI `33170853723` passed compile, Ruff, mypy, full pytest, and research tests;
- exact PR CI `33170921370` passed;
- PR #88 merged to main at `f8f84200dbc8b6fb262c5f6f99993b40714357be`.

No signal threshold, stop rule, risk limit, position sizing rule, evidence admission rule, or live-order permission was relaxed by the repair.

## Active V3 evidence progress

V3 starts from a clean lifecycle-aware protocol boundary and does not inherit V2 counts.

Current accepted V3 evidence remains:

- **0 accepted V3 cohorts**;
- **0 / 100 closed paper trades**;
- **0 / 30 closed-trade days**;
- **0 V3 strategy decisions in accepted corpus**;
- **no economic edge claim**;
- **live orders disabled**.

A trusted `v3-mainnet-corpus` has not yet been established. Rejected V3 recordings remain diagnostic evidence only and do not advance the economic gate.

## Historical V2 evidence

The final trusted V2 corpus remains preserved for audit/history only:

- **3 accepted genuine-mainnet V2 cohorts**;
- **45 strategy decisions**;
- **0 closed paper trades**;
- **0 closed-trade days**;
- last trusted corpus artifact ID `9621177153`;
- no demonstrated economic edge;
- live orders disabled.

V2 observations are not counted as V3 readiness because the lifecycle protocol differs.

## V3 campaign and curator boundary

`.github/workflows/evidence-campaign-scheduled.yml` is the active acquisition workflow. It remains mainnet-only and paper-only. Ordinary repository pushes do not launch the expensive evidence campaign; manual dispatch remains available in GitHub Actions.

`.github/workflows/evidence-corpus-curator-v3.yml` is the isolated V3 admission path. It:

1. requires the exact source artifact and pinned runtime identity;
2. independently verifies genuine-mainnet, paper-only semantics;
3. requires clean transport plus complete replay/dataset evidence;
4. requires the fixed 45-minute entry / 4-hour capture protocol identity;
5. requires flat replay exposure before corpus mutation;
6. rebuilds or extends only `v3-mainnet-corpus`;
7. never counts failed/unverified sources merely because a workflow ran;
8. never mixes the historical V2 corpus into V3.

If a future cohort is still open at four hours, it will fail closed. The protocol will not extend that individual cohort based on whether its trade is winning or losing.

## Evidence dashboard

Issue #82 is the canonical human-readable evidence tracker:

`https://github.com/Dtwosam/Cocomelon/issues/82`

The dashboard treats V3 as active, V2 as historical, and keeps live-order state visible. Its current generic description of a fixed 45-minute entry period followed by a bounded closeout-only window remains accurate for the extended protocol.

## Locked economic gate

Before any Phase 10 promotion, genuine untouched evidence must satisfy at least:

- 100 untouched OOS closed trades;
- 30 OOS covered days;
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

The frozen historical V2 one-shot evaluator remains revision `629db6294822c97690c006591802f8a47e08652e`. V3 evidence is not silently fed into that V2 evaluator. A V3 evaluation handoff must preserve the same leakage controls and promotion standards while explicitly binding the V3 lifecycle protocol.

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
2. Complete CI/merge for the V3 runtime repin and fixed four-hour lifecycle protocol.
3. Let the first scheduled cohort under runtime `f8f84200dbc8b6fb262c5f6f99993b40714357be` run without intervention.
4. Inspect the artifact for transport cleanliness, entry-cutoff enforcement, exit execution, replay/dataset completeness, and final flatness without using PnL for admission decisions.
5. Verify the V3 curator either creates the first trusted `v3-mainnet-corpus` or preserves a rejected diagnostic intake without corpus mutation.
6. Verify issue #82 refreshes from the exact V3 curator provenance.
7. Continue accumulating temporally distinct V3 paper-only cohorts under the frozen protocol.
8. Build the explicit V3 one-shot evaluation handoff before making any economic claim.
9. Advance toward Phase 10 only if genuine untouched V3 evaluation reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Profitability and live-trading status

**REAL BASELINE EDGE: UNMEASURED.**

No currently verified result demonstrates repeatable economic edge. `UNMEASURED` is not the same as `NO_EDGE_DEMONSTRATED`.

**LIVE TRADING: DISABLED.**
