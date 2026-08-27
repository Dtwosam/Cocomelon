# Cocomelon Project Status

**Last updated:** 2026-08-27  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified main revision:** `c37561c3a7acddfe9a0910527d43c0f44ef83cd3`  
**Live trading:** **DISABLED**  
**Real baseline edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

## Current production state

The active evidence-acquisition protocol is now **V3 lifecycle-aware mainnet evidence**. PR #86 merged the V3 campaign, isolated V3 corpus curator, and V3-aware dashboard at `c37561c3a7acddfe9a0910527d43c0f44ef83cd3`. Post-merge main CI run `33071455368` passed compile, Ruff, mypy, the full pytest suite, and research tests.

V3 keeps the strategy, risk, sizing, execution model, and live-order state frozen while changing only the evidence lifecycle around the end of each recording window:

- genuine public Hyperliquid **mainnet** data only;
- paper execution only;
- one fixed **90-minute** capture per scheduled cohort;
- new paper exposure allowed only during the first **45 minutes**;
- after the entry cutoff, existing paper positions continue receiving ordinary position management and exits;
- no new entry or staged opening fill may occur at or after the cutoff;
- a cohort that remains open, incomplete, gapped, or otherwise unverifiable at the hard endpoint fails closed;
- no PnL, final-equity, profitability, or edge value can influence acquisition length, retry, admission, or corpus selection;
- there is no performance-based retry path in V3.

The immutable replay/evidence runtime for the active V3 protocol is:

- **V3 lifecycle-aware runtime:** `f21ad7be581bc662127e75f832cd8fcbf4f5f93b`;
- **replay engine:** `phase8-v2-lifecycle-aware`;
- **replay config:** `phase9-baseline-replay-v2-lifecycle-aware`.

No signal, stop, risk, sizing, ranking, or live-trading rule was changed by the V3 activation.

## Active V3 evidence progress

The V3 corpus starts from a clean protocol boundary and does **not** inherit V2 counts.

Current V3 accepted evidence:

- **0 accepted V3 cohorts**;
- **0 / 100 closed paper trades**;
- **0 / 30 closed-trade days**;
- **0 V3 strategy decisions in accepted corpus**;
- **no economic edge claim**;
- **live orders disabled**.

A `v3-mainnet-corpus` artifact has not yet been established. The first eligible scheduled V3 capture must complete, independently verify, and finish flat before it can become the first V3 corpus cohort.

## Historical V2 evidence

The final trusted V2 corpus remains preserved for audit/history only:

- **3 accepted genuine-mainnet V2 cohorts**;
- **45 strategy decisions**;
- **0 closed paper trades**;
- **0 closed-trade days**;
- last trusted corpus artifact ID `9621177153`;
- mainnet attestation prefix `7143774193475939…`;
- no demonstrated economic edge;
- live orders disabled.

Those V2 observations are real historical evidence, but they are **not counted as V3 progress** because the replay lifecycle changed. Mixing the two protocols would obscure whether the closeout-window change actually resolves right-censoring and would weaken the experimental boundary.

## Why V3 exists

The 45-minute V2 acquisition window could produce a legitimate paper opening near the end of the recording and then terminate before the strategy had time to close it. Such right-censored cohorts correctly failed economic admission, but repeated failures could prevent the system from accumulating closed-trade evidence even when the trading logic itself was functioning normally.

V3 fixes that evidence-lifecycle problem without changing the trading strategy. Entries remain frozen to the original 45-minute opportunity window, while a second 45-minute period records only the natural management and closeout of already-open paper exposure. If the position still does not close by the hard 90-minute endpoint, the cohort is rejected rather than force-closed or retrospectively extended.

This makes the evidence more useful without using performance information to decide how long to observe a trade.

## V3 campaign and curator boundary

`.github/workflows/evidence-campaign-scheduled.yml` is the active scheduled acquisition workflow. It runs at:

`37 1,4,7,10,13,16,19,22 * * *` UTC

Ordinary repository pushes do not launch the expensive evidence campaign. The workflow also supports manual dispatch.

`.github/workflows/evidence-corpus-curator-v3.yml` is the isolated V3 admission path. It listens only to completed `Scheduled Genuine Mainnet Evidence Campaign V3` runs and:

1. requires the exact V3 source artifact and pinned runtime identity;
2. independently verifies genuine-mainnet, paper-only, complete, gap-free replay semantics;
3. requires lifecycle-aware replay metadata and the fixed 45/90-minute protocol;
4. requires flat replay exposure before mutation;
5. rebuilds/extends only `v3-mainnet-corpus`;
6. never reads or mutates `v2-mainnet-corpus`;
7. preserves rejected intake diagnostics without admitting the cohort.

The historical `.github/workflows/evidence-corpus-curator.yml` remains available only for V2 provenance/history.

## Evidence dashboard

Issue #82 is the canonical human-readable evidence tracker:

`https://github.com/Dtwosam/Cocomelon/issues/82`

The dashboard now listens to both exact trusted curator workflows. It treats **V3 as active**, displays V2 only as historical context, and never sums V2 counts into V3 readiness. If a V3 curator completes before a V3 corpus exists, the dashboard explicitly reports that the V3 accepted corpus is not established yet instead of silently falling back to V2 as active evidence.

The dashboard is informational only. It cannot enable live trading or change strategy/risk behavior.

## Locked economic gate

The economic promotion standard remains conservative and unchanged. Before any Phase 10 promotion, genuine untouched evidence must satisfy at least:

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

The frozen historical V2 one-shot evaluator remains revision `629db6294822c97690c006591802f8a47e08652e`. **V3 evidence is not silently fed into that V2 evaluator.** A V3 evaluation handoff must preserve the same leakage controls and promotion standards while explicitly binding the new lifecycle-aware protocol identity.

Until that V3 evaluation boundary exists and enough genuine V3 evidence accumulates, economic edge remains unmeasured and Phase 10 remains blocked.

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
2. Let the first scheduled V3 campaign run the fixed 90-minute lifecycle-aware capture without intervention.
3. Inspect its artifact for transport cleanliness, replay/dataset completeness, entry-cutoff enforcement, and final flatness without using PnL for admission decisions.
4. Verify the V3 curator either creates the first trusted `v3-mainnet-corpus` or preserves a rejected diagnostic intake without corpus mutation.
5. Verify issue #82 auto-refreshes from the exact V3 curator provenance.
6. Continue accumulating temporally distinct V3 paper-only cohorts at the fixed eight-window UTC cadence.
7. Build the explicit V3 one-shot evaluation handoff before any economic claim is allowed; do not reuse V2 snapshot identity implicitly.
8. Advance toward Phase 10 only if a genuine untouched V3 evaluation reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Profitability and live-trading status

**REAL BASELINE EDGE: UNMEASURED.**

No currently verified result demonstrates repeatable economic edge. `UNMEASURED` is not the same as `NO_EDGE_DEMONSTRATED`.

**LIVE TRADING: DISABLED.**
