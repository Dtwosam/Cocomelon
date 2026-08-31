# Cocomelon Project Status

**Last updated:** 2026-08-31  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified V4 execution runtime:** `0c14c9cfa37c80babc65d050fed6d4465dcb9032`  
**Funding-corrected V4 activation merge:** `fa89892a1ec27412d11d8457dc5d41334afdaf11`  
**Frozen V4 Phase 9 evaluator:** `efd33f8f89bc11e51c0e4f94591b9d8d1ce5b5ff`  
**Live trading:** **DISABLED**  
**Real baseline edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

## Current production state

The active authoritative evidence protocol remains **V4 thesis-expiry mainnet evidence**. It uses genuine public Hyperliquid mainnet data with paper execution only.

The frozen V4 acquisition contract is unchanged:

- fixed **45-minute entry window** (`2700` seconds);
- exact **4-hour maximum position age** (`14400` seconds);
- fixed **5h15m total capture** (`18900` seconds);
- **4 scheduled cohorts per day** at `37 1,7,13,19 * * *` UTC;
- one acquisition attempt per cohort;
- schedule-triggered acquisition only; manual dispatch is an auditable rejected path and cannot produce economic evidence;
- no PnL-, equity-, profitability-, or outcome-conditioned retry or extension;
- no forced close solely to make a cohort admissible;
- final cohort admission requires clean transport, complete replay/dataset evidence, empty gap refs, and flat replay exposure;
- live orders remain disabled.

Exact active V4 evidence identity:

- protocol `v4-thesis-expiry-mainnet`;
- runtime `0c14c9cfa37c80babc65d050fed6d4465dcb9032`;
- replay engine `phase8-v3-thesis-expiry`;
- replay config `phase9-baseline-replay-v3-thesis-expiry`;
- execution config `phase7-v2-4h-thesis-expiry`;
- frozen evaluator `efd33f8f89bc11e51c0e4f94591b9d8d1ce5b5ff`.

The runtime/evaluator repin was a correctness/provenance correction made before the first accepted V4 cohort. Strategy logic, risk rules, execution economics, entry/capture/expiry windows, readiness thresholds, and the one-shot economic protocol were not changed.

V3 scheduled acquisition is retired. Its workflow remains manual-only for frozen audit/reproduction and cannot compete with V4 scheduled evidence.

## Active V4 evidence progress

The trusted dashboard state as of 2026-08-31 08:37 UTC is:

- **1 accepted V4 cohort**;
- **2 / 100 closed paper trades**;
- **1 / 30 closed-trade days**;
- **105 strategy decisions** in the accepted V4 corpus;
- **no V4 economic edge claim**;
- **live orders disabled**.

The first accepted corrected-runtime source was scheduled campaign run `33338032370`, admitted by curator run `33356082082` into `v4-mainnet-corpus` artifact `9745203020`.

The subsequent scheduled campaign run `33369130434` failed during acquisition after a simultaneous redundant WebSocket disconnect created `redundant_disconnect` gaps across subscribed streams. The gap watcher failed closed and verification was skipped. That run contributes zero economic progress and the accepted corpus remains unchanged.

No failed or pre-fix V4 source has been retried, reclassified, or retroactively admitted. All remain diagnostic evidence only and contribute zero economic progress.

### Accounting correction boundary

The first scheduled V4 campaign, run `33228947939`, captured the full genuine-mainnet window successfully but offline replay failed with `EQUITY_RECONCILIATION_MISMATCH` while positions overlapped. The journal had incorrectly required one closed trade's net PnL to equal the change in whole-account equity while another open position's unrealized PnL was moving.

PR #109 removed only that invalid cross-position equality while preserving authoritative trade-local fill/fee/funding reconciliation and account-equity snapshots. Its corrected runtime was `0ad7c5c3626d0a4a1f2ec87c8806983d529a9be7`. Because zero V4 cohorts had been accepted, PRs #110 and #111 prospectively repinned the V4 source/evaluator boundary without changing trading logic.

### GitHub Actions timeout correction

Subsequent scheduled cohorts showed that the single `350`-minute campaign job left only about 35 minutes for offline replay after the fixed 5h15 acquisition. Runs #3 and #4 therefore completed acquisition but were cancelled during replay at the job timeout.

PR #113 separated the fixed evidence campaign into two jobs:

- `acquire-evidence`: `330`-minute budget for the single 5h15 mainnet capture;
- `verify-evidence`: independent `90`-minute budget for offline validation/replay;
- an intermediate acquisition artifact transfers the exact captured evidence between jobs;
- acquisition-only concurrency remains `cancel-in-progress: false`.

Run `33313715800` proved that correction operationally: acquisition completed, its staging artifact uploaded, the independent verification job downloaded it, and offline validation/replay completed. The prior 350-minute cancellation mode did not recur.

### Funding-boundary timestamp correction

Run `33254784124` and later run `33313715800` both had clean transport and flat closed positions, yet replay/dataset completeness remained false under runtime `0ad7c5c...`.

Investigation found the remaining correctness defect in hourly funding evidence. Hyperliquid historical funding records can carry source timestamps a few milliseconds after the exact hourly boundary. The replay state book indexed those records only by their raw timestamp while funding reconciliation looked them up by the exact hourly boundary, producing false `FUNDING_RECORD_MISSING` gaps even when the source funding evidence was present.

PR #114 fixed this narrowly:

- preserves the original funding source timestamp and provenance;
- maps only bounded post-hour timestamp jitter (`<= 1000 ms`) to the canonical hourly reconciliation boundary;
- still rejects records outside that strict tolerance;
- adds RED/GREEN regressions for mainnet-style `+49 ms` timestamps and out-of-window rejection;
- does not change funding rates, cash-flow formulas, strategy, risk, execution economics, or evidence thresholds.

The funding-corrected runtime is `0c14c9cfa37c80babc65d050fed6d4465dcb9032`.

Because zero V4 cohorts had been accepted and no V4 corpus/final one-shot freeze existed, PR #115 prospectively repinned the V4 source protocol to that runtime. PR #116 then activated the corrected runtime for acquisition/replay and curator verification, and pinned the frozen one-shot evaluator to `efd33f8f89bc11e51c0e4f94591b9d8d1ce5b5ff`.

Run `33313715800` remains diagnostic only: it used the pre-funding-fix runtime, completed replay successfully under the split workflow, produced one closed/flat paper trade, but was correctly rejected with `replay_incomplete` and `dataset_incomplete`. Its final source artifact is `9737092116` with SHA256 `2079f2e4738546dd8003b3bde97ca83d5225f3c9ec66fe2f1c0b9f5684c8cc54`.

## V4 acquisition and isolated curator

`.github/workflows/evidence-campaign-v4-scheduled.yml` is the active acquisition workflow. It is paper-only, mainnet-only, fixed-duration, schedule-only for economic acquisition, uses independent acquisition/replay time budgets, and is pinned to runtime `0c14c9cfa37c80babc65d050fed6d4465dcb9032`.

`.github/workflows/evidence-corpus-curator-v4.yml` is the only V4 admission path. It:

1. accepts only completed exact V4 campaign sources;
2. verifies repository/workflow provenance before trusting artifacts;
3. requires the exact active V4 runtime/replay/config/execution identity;
4. fails closed on incomplete replay, incomplete dataset, gaps, or open exposure;
5. writes only `v4-mainnet-corpus`;
6. never imports V3 or V2 corpus evidence;
7. never uses interim economic outcomes for admission decisions.

## V4 Phase 9 evaluator handoff

The frozen evaluator revision is `efd33f8f89bc11e51c0e4f94591b9d8d1ce5b5ff` and is bound to source runtime `0c14c9cfa37c80babc65d050fed6d4465dcb9032`.

The V4 evaluator uses distinct immutable identities:

- snapshot `v4-phase9-frozen-snapshot`;
- evaluation `v4-phase9-evaluation`;
- candidate `v4-baseline-fixed`.

It requires the exact V4 `protocol.json`, copies and hashes that protocol into the frozen snapshot, binds the canonical protocol digest, and rejects incompatible source/snapshot identity rather than silently reinterpreting evidence.

The statistical engine and `EvaluationPolicy()` are unchanged. The accounting, timeout, funding-timestamp, and dual-lane research changes do not relax Phase 9 promotion thresholds.

## Immutable V4 one-shot boundary

`.github/workflows/phase9-v4-one-shot.yml` consumes only a successful exact `Verified V4 Mainnet Evidence Corpus Curator` run and pins evaluator revision `efd33f8f89bc11e51c0e4f94591b9d8d1ce5b5ff`.

The one-shot workflow verifies curator provenance, downloads one trusted V4 corpus, prepares a local-only frozen snapshot, persists an append-once freeze before any economic evaluation, refuses replacement OOS data after freeze, and then produces exactly one terminal insufficient-evidence result or one untouched economic evaluation. Preparation/evaluation remain offline and read-only; narrow repository write permission is isolated to immutable state persistence.

## Dual-lane research decision

Decision **D-023** adds a parallel research lane without changing the authoritative V4 validation experiment.

The research lane exists to learn quickly from **touched, non-promotional** evidence and reject weak challengers early. The governing rule is: **candidates may fail fast; candidates may not succeed fast**.

While V4 remains performance-blind:

- research may not inspect or reconstruct hidden V4 economics;
- research economics may only use source-time intervals provably disjoint from all actual V4 acquisition intervals, including failed/diagnostic sessions;
- ambiguous or overlapping research batches fail closed as `REJECTED_CONTAMINATION`;
- every candidate persists immutable family/parent/ancestor lineage;
- descendants inherit the union of all ancestor touched intervals;
- economic futility may reject after at least 20 closed research trades under the precommitted Bayesian rule;
- `RESEARCH_PROMISING` requires at least 40 closed research trades, 7 distinct closed-trade days, and the locked positive posterior threshold, but remains non-promotional;
- any selected challenger must be frozen and begin a separate untouched validation period only after a 6-hour embargo beyond the latest inherited touched interval.

The full design is `docs/superpowers/specs/2026-08-31-dual-lane-sequential-research-design.md`. This research architecture is intended to reduce wasted calendar time if a candidate is clearly weak while preserving a trustworthy final promotion test.

## Evidence dashboard

Issue #82 remains the canonical human-readable V4 validation tracker. It treats V4 as active and V3/V2 as historical. Historical counts and future research-lane metrics are never added to V4 progress.

Routine V4 dashboard output exposes operational/provenance state only. Before an immutable V4 final result exists, **Economic edge remains `Not measured yet`**. Interim PnL, final equity, mean net R, win rate, profit factor, bootstrap values, and other tuning-sensitive V4 fields remain hidden.

Any research dashboard is separate and must label its economics **TOUCHED / NON-PROMOTIONAL**.

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
3. Implement the dual-lane research architecture from the approved design, starting with candidate lineage/touched-data contracts and V4 source-interval isolation.
4. Admit only clean, complete, flat corrected-runtime V4 sources into `v4-mainnet-corpus`.
5. Continue frozen V4 acquisition without strategy tuning until the economic minimums are reached.
6. Let the V4 one-shot workflow check fixed-protocol readiness after trusted corpus updates.
7. Use research-lane economics only for touched challenger keep/change/kill decisions, never for a V4 promotion claim.
8. Advance toward Phase 10 only if an authoritative untouched one-shot result reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Profitability and live-trading status

**REAL BASELINE EDGE: UNMEASURED.**

No currently verified result demonstrates repeatable economic edge. `UNMEASURED` is not the same as `NO_EDGE_DEMONSTRATED`.

**LIVE TRADING: DISABLED.**
