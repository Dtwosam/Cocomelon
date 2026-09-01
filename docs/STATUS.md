# Cocomelon Project Status

**Last updated:** 2026-09-01  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`

## Current phase

Cocomelon is in the **V4 untouched mainnet evidence collection phase**. Phase 9 one-shot evaluation exists and remains locked behind the fixed untouched-evidence protocol. Phase 10 and live trading remain blocked.

The V4 strategy/risk/execution protocol is frozen for evidence collection. Research work is isolated from V4 and remains **TOUCHED / NON-PROMOTIONAL**.

## V4 untouched evidence lane

V4 acquisition is scheduled on Hyperliquid mainnet and remains outcome-blind. The acquisition workflow records genuine public-mainnet market evidence only. It does not inspect, reconstruct, export, or condition on hidden V4 economics.

The trusted V4 acquisition workflow remains `.github/workflows/evidence-campaign-v4-scheduled.yml`. Its acquisition authority is based on actual workflow attempt status plus recording session/segment evidence, not nominal schedule timestamps.

Frozen V4 safeguards remain in force:

- no strategy tuning during evidence collection;
- no manual retry or performance-conditioned acquisition;
- no hidden interim economic inspection;
- no research-derived promotion claim;
- no testnet evidence;
- no fabricated order-book history;
- no live wallet/order surface.

## Research-only lane

PR #119 introduced the authenticated research core and PR #120 added the dedicated research status output. All research economics are **TOUCHED / NON-PROMOTIONAL** and cannot advance V4 readiness or Phase 10.

The next D-023 rollout layer adds a research-only mainnet paper replay campaign without changing frozen V4 acquisition, curation, or one-shot evaluation:

- every runner attempt is persisted before artifact verification with immutable attempt/batch/source identity; terminal success, failure, and contamination outcomes cannot be rewritten;
- retries require a new attempt and batch identity, so infrastructure failures remain auditable and economic outcomes cannot authorize a hidden rerun;
- the runner derives the actual source interval, code revision, and config digest from the authenticated artifact rather than caller or schedule timestamps;
- candidate code/config identity must match the verified artifact and the V4 registry completeness watermark must be authoritative through the artifact end time before research economics are released;
- actual V4 overlap records a contaminated attempt and rejects the candidate through the canonical contamination state path;
- `cocomelon-research-runner` exposes only authenticated artifact execution and non-economic attempt history;
- the research cohort builder requires the acquisition transport summary, validates the physical public-mainnet recording, freezes and replays offline, requires complete/gap-free/flat evidence, emits `economic_claim="none"`, and self-verifies the finished genuine-mainnet cohort;
- `.github/workflows/research-campaign-scheduled.yml` runs one paper-only public-mainnet acquisition per workflow run at `2 7 * * *` UTC, restores the authoritative research registry, persists the attempt before acquisition, evaluates only through the canonical runner, and uploads the complete audit trail even on failure;
- `.github/workflows/research-v4-registry-sync.yml` is implemented as the trusted non-economic V4 acquisition-authority synchronizer: it inventories actual V4 workflow run attempts, validates acquisition session/segment evidence, and publishes only interval/completeness authority to `research-authoritative-registry`;
- after the research capture interval is bound, the campaign dispatches the implemented synchronizer and fails closed unless the returned V4 completeness watermark covers the actual bound research interval;
- the research workflow never synthesizes V4 authority from nominal schedules and never inspects hidden V4 performance;
- successful runner checkpoints continue to publish only through the dedicated **TOUCHED / NON-PROMOTIONAL** research status surface.

This runner cannot produce `CANDIDATE_EDGE`, mutate `v4-mainnet-corpus`, alter frozen V4 readiness, or enable live execution. The authoritative V4 interval/completeness synchronization path is implemented; the research campaign now depends on that trusted synchronizer succeeding and fails closed whenever current non-economic V4 source-time authority cannot be proven through the bound research interval.

## Evidence dashboard

Issue #82 remains the canonical human-readable V4 validation tracker. It treats V4 as active and V3/V2 as historical. Historical counts and research-lane metrics are never added to V4 progress.

Routine V4 dashboard output exposes operational/provenance state only. Before an immutable V4 final result exists, **Economic edge remains `Not measured yet`**. Interim PnL, final equity, mean net R, win rate, profit factor, bootstrap values, and other tuning-sensitive V4 fields remain hidden.

The dedicated research dashboard/status surface is separate and labels its economics **TOUCHED / NON-PROMOTIONAL**.

## Historical evidence

V3 is retained for audit/history only and does not advance V4 readiness. Its frozen historical V3 runtime is `f8f84200dbc8b6fb262c5f6f99993b40714357be`; its Phase 9 evaluator is `39c2f6a57c0b2db9929fa4050e4c1f47e55f55ed`.

V2 is also audit/history only. Its final trusted corpus remains 3 accepted genuine-mainnet cohorts, 45 strategy decisions, 0 closed paper trades, 0 closed-trade days, and no demonstrated economic edge. V2 evidence is never counted toward V4 readiness.

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
- No wallet/private-key signing, transfer, withdrawal, or private-account execution path is part of the evidence or research campaigns.
- Strategy cannot size positions or send orders; independent risk has final veto.
- `NO_TRADE` remains first-class.
- No averaging down, martingale, or stopless positions.
- No historical L2/order flow may be fabricated from candles.
- Real-money activation requires explicit later authorization after every promotion gate passes.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Continue naturally scheduled V4 acquisition unchanged; do not manually dispatch, retry, or performance-condition V4 cohorts.
3. Keep PR #119's research-core economics, PR #120's status output, and scheduled research-runner results strictly **TOUCHED / NON-PROMOTIONAL**; do not use research outputs for a V4 promotion claim.
4. Observe the implemented authoritative V4 interval/completeness synchronization path in scheduled operation; preserve its non-economic provenance-only boundary and fail closed on missing or insufficient authority.
5. Admit only clean, complete, flat corrected-runtime V4 sources into `v4-mainnet-corpus`.
6. Continue frozen V4 acquisition without strategy tuning until the economic minimums are reached.
7. Let the V4 one-shot workflow check fixed-protocol readiness after trusted corpus updates.
8. Advance toward Phase 10 only if an authoritative untouched one-shot result reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Profitability and live-trading status

**REAL BASELINE EDGE: UNMEASURED.**

No currently verified result demonstrates repeatable economic edge. `UNMEASURED` is not the same as `NO_EDGE_DEMONSTRATED`.

**LIVE TRADING: DISABLED.**