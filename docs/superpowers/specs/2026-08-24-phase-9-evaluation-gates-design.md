# Phase 9 Evaluation, OOS, and Walk-Forward Research Gates Design

**Status:** Proposed Phase 9 architecture  
**Date:** 2026-08-24  
**Repository:** `Dtwosam/Cocomelon`  
**Predecessor:** Phase 8 merged at `f7f37044997e13b3ffe91edd312756862343782b`

## 1. Goal

Phase 9 determines whether the deterministic baseline system has repeatable positive net expectancy after realistic costs, or records honestly that no edge has been demonstrated.

It must make strategy evaluation harder to fool, not easier to optimize.

The phase consumes trusted Phase 8 journal/replay outputs and adds:

- frozen time-based train/validation/test partitions;
- mechanically protected untouched out-of-sample evaluation;
- deterministic walk-forward reports;
- cost-aware portfolio/trade statistics;
- market/regime/strategy/direction/time/score diagnostics;
- drawdown, tail-loss, concentration, and uncertainty analysis;
- predeclared fee/slippage/funding sensitivity scenarios;
- deterministic NO_TRADE missed-opportunity diagnostics;
- explicit evidence statuses that can say `INSUFFICIENT_EVIDENCE` or `NO_EDGE_DEMONSTRATED`;
- a read-only preview of later promotion gates without enabling promotion or live execution.

Phase 9 does **not** train ML, search strategy parameters, alter locked risk, build a live adapter, or place exchange orders.

## 2. Governing constraints

Phase 9 inherits all repository invariants.

### 2.1 Mainnet and evidence

- Hyperliquid testnet remains forbidden.
- Evaluation uses real Hyperliquid mainnet evidence captured/validated by earlier phases.
- `CANDLE_CONTEXT` and `MICROSTRUCTURE` results remain distinct evidence classes.
- A candle/context result may not be relabeled as microstructure evidence.
- Missing/gapped evidence is surfaced; it is never interpolated into certainty.

### 2.2 Risk and decision boundaries

- Phase 6 remains the new-exposure risk authority.
- Locked V1 risk limits are unchanged.
- `NO_TRADE` remains first-class.
- Strategy score is not a calibrated probability unless Phase 9 demonstrates calibration; Phase 9 reports score-bucket outcome behavior instead.

### 2.3 Research discipline

- Time partitions are frozen before untouched-test metrics are revealed.
- Test boundaries never move because performance was disappointing.
- Candidate definitions and evaluation policy are frozen before consuming an untouched test partition.
- Sensitivity scenarios are predeclared; Phase 9 does not search a grid and select the best result.
- Identical dataset + candidate set + policy + code produces the same evaluation IDs and results.
- Every research result carries exact source/replay/config/code provenance.

### 2.4 Live boundary

- Phase 9 cannot enable real-money execution.
- Phase 9 cannot claim live readiness by itself.
- Later live-promotion requirements in `MASTER_SPEC.md` remain authoritative, including 500 closed paper trades, 45 calendar days mainnet shadow, positive OOS/walk-forward results, profit factor >= 1.20, paper max drawdown <= 8%, concentration limits, zero unresolved risk violations, and explicit user authorization.

## 3. Architectural choice

Use an immutable **evaluation-fact + frozen-manifest + pure-engine** architecture.

```text
Phase 8 JournalStore / ReplayResult / ReplayManifest
            +
Phase 4 FeatureSnapshot + Phase 5 StrategyDecision facts
            +
optional paper-account equity facts
            |
            v
EvaluationFactStore (SQLite, low volume)
            |
            v
EvaluationDatasetManifest
            |
            v
FrozenSplitManifest + FrozenCandidateSet + EvaluationPolicy
            |
            v
Pure metric / uncertainty / slice / walk-forward engines
            |
            v
EvaluationResult + OOS consumption record + reports
```

This is preferred over either:

1. computing ad-hoc statistics directly from journal SQL, which is difficult to reproduce and cannot protect untouched OOS usage; or
2. introducing a large dataframe/ML dependency now, which would be unnecessary before Phase 10 and would weaken the lightweight deterministic baseline.

Phase 9 core remains Python stdlib + existing package dependencies. PyArrow stays optional research tooling only.

## 4. Why Phase 8 needs a narrow evaluation-fact companion

Phase 8 intentionally journals stable lifecycle references rather than every strategy/feature/account value. That is sufficient for deterministic replay and trade reconstruction, but Phase 9 also needs dimensions such as strategy score, lead strategy, regime, and account-equity observations.

Do **not** mutate Phase 8 `JournalObservation` identity or retrofit score/regime values into its schema.

Instead add immutable Phase 9 facts derived from already-existing typed objects at decision/account observation time.

### 4.1 `DecisionEvaluationFact`

Required fields:

- `strategy_decision_id`;
- `feature_snapshot_id`;
- `replay_run_id`;
- market;
- direction;
- decision timestamp;
- score;
- lead strategy;
- signal IDs;
- strategy reason codes;
- trend regime;
- volatility regime;
- schema version.

The fact ID is a canonical digest of semantic fields.

A fact is created from the exact `StrategyDecision` plus the exact `FeatureSnapshot` that decision references. IDs must reconcile before persistence.

This supports:

- performance by lead strategy;
- direction;
- score bucket;
- trend/volatility regime;
- market;
- time-of-day derived from UTC decision time;
- sampled `NO_TRADE` analysis.

### 4.2 `AccountEquityFact`

Required fields:

- `replay_run_id`;
- `account_state_id`;
- timestamp;
- equity;
- cash;
- unrealized PnL;
- realized gross PnL;
- cumulative fees;
- cumulative funding;
- gross open notional;
- open-position count;
- schema version.

It is created only from a genuine `PaperAccountState` produced by existing Phase 7 accounting. Phase 9 must not invent intermediate account states.

If account-equity observations are not dense enough to support a mark-to-market drawdown claim, the report marks account-equity drawdown incomplete. Phase 9 may still report a clearly named realized closed-trade drawdown diagnostic, but must not silently substitute it for full account drawdown.

## 5. `EvaluationFactStore`

Use a separate low-volume SQLite store rather than overloading the Phase 8 journal.

Minimal tables:

- `evaluation_decision_facts`;
- `evaluation_equity_facts`;
- `evaluation_dataset_manifests`;
- `evaluation_split_manifests`;
- `evaluation_candidate_sets`;
- `evaluation_oos_consumptions`;
- `evaluation_results`.

Rules:

- canonical deterministic primary IDs;
- exact duplicate retry is idempotent;
- same ID with a different canonical payload is corruption and fails closed;
- explicit transactions for multirow writes;
- restart reconstruction must reproduce typed objects and IDs exactly;
- Phase 9 never mutates Phase 8 `JournalStore`, Phase 7 execution state, or raw market data.

## 6. Evaluation dataset construction

### 6.1 Valid trade sample

A closed trade is eligible for primary evaluation only if:

- `TradeJournalEntry` exists and passes its own invariants;
- it references a matching `DecisionEvaluationFact`;
- market/direction/decision IDs reconcile;
- the source replay result exists;
- replay evidence class is known;
- source replay result is deterministic and its manifest is available;
- required data quality for the requested metric is present;
- no trade ID appears twice in the same dataset.

Trades may be reported diagnostically even when an evidence-quality condition fails, but they cannot silently enter a `research_ready` primary metric set.

### 6.2 `EvaluationDatasetManifest`

Freeze:

- included replay manifest IDs;
- included replay result digests;
- included closed-trade IDs;
- included decision-fact IDs;
- included equity-fact IDs;
- evidence class or explicit mixed-class policy;
- dataset start/end timestamps;
- code revision;
- evaluation schema version;
- data-completeness flags and gap references.

Input tuple enumeration cannot affect the manifest ID.

Mixed evidence classes are allowed only for explicitly labeled aggregate diagnostics. A result that requires microstructure cannot inherit credibility from candle-only samples.

## 7. Frozen time splits

### 7.1 `FrozenSplitManifest`

Phase 9 uses explicit absolute UTC millisecond boundaries, never boundaries chosen from observed PnL.

Required named partitions:

- `train` — development/in-sample history;
- `validation` — pre-test validation/calibration history;
- `test` — untouched out-of-sample history.

Phase 9 itself does not fit a model in `train`; the naming matches the approved future validation sequence and allows reuse by Phase 10.

Each split stores:

- start/end;
- embargo duration;
- source dataset manifest ID;
- policy version;
- split-manifest ID.

### 7.2 Purging and embargo

A trade belongs to a split only when its full lifecycle is contained inside the split evaluation window.

A trade crossing a split boundary is excluded with `CROSSES_SPLIT_BOUNDARY`; it is never assigned according to only open or close time.

Default Phase 9 embargo is **6 hours**, versioned in policy. This is conservative relative to the V1 4h feature context and intended maximum holding horizon. A position that remains open longer than the embargo is still purged by the full-lifecycle rule.

The embargo value is policy/config, never tuned using test performance.

### 7.3 Split creation

Core evaluation APIs require explicit frozen boundaries.

A helper may propose chronological split boundaries from deterministic fractions or durations, but it only writes a candidate manifest. No metrics are computed until that manifest is explicitly persisted/frozen. Once the untouched test is consumed, changing boundaries creates a new split lineage and the old test remains recorded as consumed.

## 8. Untouched OOS consumption protection

The store mechanically tracks test-set use.

### 8.1 `FrozenCandidateSet`

Before test metrics are computed, freeze:

- strategy version;
- risk version;
- execution-config version;
- code revision;
- relevant config digest;
- deterministic candidate identifiers;
- evaluation-policy ID;
- predeclared sensitivity-profile IDs.

Multiple baseline candidates may share one untouched test **only if the whole candidate set was frozen before first test reveal**.

### 8.2 Consumption rule

The first untouched-test evaluation persists:

`(test_partition_digest, candidate_set_digest, policy_id, consumed_at_evaluation_id)`

Identical reruns are idempotent and remain untouched reproductions.

Trying to evaluate a changed candidate set or changed policy against the already-consumed test can still produce a diagnostic report, but the result is marked:

`OOS_CONTAMINATED`

and cannot be used as untouched evidence.

A new candidate/policy requires a genuinely new untouched time partition to regain `UNTOUCHED` status.

This is a deliberate anti-p-hacking control.

## 9. Core performance metrics

All financial arithmetic uses deterministic `Decimal` semantics.

### 9.1 Trade-level

Report at minimum:

- trade count;
- gross PnL;
- total fees;
- total funding cash PnL;
- signed realized slippage amount;
- net PnL;
- total net R;
- mean net R (primary trade expectancy metric);
- median net R;
- win rate (descriptive only);
- average winner/loser R;
- profit factor;
- largest winner/loser R;
- 5th percentile net R;
- 5% expected shortfall / tail mean where sample size permits;
- median and percentile holding duration.

Profit factor is `sum(positive net pnl) / abs(sum(negative net pnl))`.

If there are no losing trades, profit factor is `None` with an explicit reason rather than `Infinity`.

### 9.2 Drawdown

Report two distinct measures:

1. `account_equity_max_drawdown_fraction` from genuine ordered `AccountEquityFact` observations when complete enough;
2. `realized_closed_trade_max_drawdown_fraction` from cumulative closed-trade net PnL, explicitly labeled realized-only.

Never substitute measure 2 for measure 1 without the label.

### 9.3 Risk-adjusted daily metrics

Sharpe/Sortino-like values are produced only when a covered calendar series is statistically meaningful under policy minimums.

Where genuine account-equity facts are complete, daily returns use end-of-day account equity.

Where they are incomplete, no account-equity Sharpe/Sortino is produced. Phase 9 may separately report a realized-PnL daily-series diagnostic, clearly labeled.

No annualization is presented when coverage is too short for the policy minimum.

### 9.4 Concentration

Report:

- positive net PnL share by market;
- positive net PnL share by lead strategy;
- positive net PnL share by UTC seven-day bucket;
- trade-count share by market/strategy;
- largest positive contributor.

The later live reference limits of 35% per market and 50% per seven-day period are included as preview diagnostics. Phase 9 cannot declare live promotion.

## 10. Deterministic uncertainty

Point estimates alone are not enough to claim repeatable edge.

Phase 9 implements a deterministic block-bootstrap confidence interval for mean net R.

### 10.1 Method

- group trades by UTC close date;
- preserve all trades within a day together;
- resample contiguous day blocks with replacement;
- fixed policy block length: 5 days;
- fixed policy resamples: 2,000;
- deterministic PRNG seed derived from SHA-256 of evaluation-manifest ID + metric name;
- percentile 95% interval using deterministic nearest-rank selection.

A sample must meet the policy minimum days/trades before the CI is research-ready. Otherwise the CI is unavailable and evidence status is `INSUFFICIENT_EVIDENCE`.

The bootstrap is an uncertainty diagnostic, not a significance-hacking loop. Block length/resample count are versioned policy inputs and cannot be selected from test results.

## 11. Phase 9 V1 evidence policy

Use a versioned `phase9-v1` research-readiness policy. These are Phase 9 research defaults, **not live-promotion gates**:

- minimum untouched OOS closed trades: **100**;
- minimum untouched OOS calendar coverage: **30 days**;
- minimum eligible walk-forward evaluation windows: **3**;
- minimum closed trades per eligible walk-forward evaluation window: **20**;
- minimum score-bucket trades before a bucket is interpreted: **20**;
- minimum positive walk-forward-window fraction for stability: **60%**;
- bootstrap confidence level: **95%**;
- bootstrap block length: **5 days**;
- bootstrap resamples: **2,000**;
- split embargo: **6 hours**.

Changing these values creates a new policy ID. A changed policy cannot reuse an already-consumed test set and still call it untouched.

These defaults intentionally demand more than a toy backtest while remaining separate from the later 500-trade / 45-day shadow live gate.

## 12. Edge evidence status

Primary evaluation returns one of:

- `INVALID_EVIDENCE` — missing/corrupt/inconsistent required source facts;
- `OOS_CONTAMINATED` — test already revealed to a different candidate set/policy;
- `INSUFFICIENT_EVIDENCE` — valid data but readiness sample/coverage criteria not met;
- `NO_EDGE_DEMONSTRATED` — ready sample but positive repeatable net expectancy criteria fail;
- `CANDIDATE_EDGE` — untouched OOS and walk-forward evidence satisfy the Phase 9 edge criteria.

`CANDIDATE_EDGE` requires all of:

- untouched OOS status is genuinely `UNTOUCHED` or exact idempotent reproduction;
- OOS readiness sample/coverage gates pass;
- OOS mean net R > 0;
- lower bound of deterministic 95% block-bootstrap mean-net-R CI > 0;
- aggregate walk-forward evaluation mean net R > 0;
- enough walk-forward windows are eligible;
- at least 60% of eligible walk-forward evaluation windows have positive mean net R;
- no single market contributes more than 35% of positive net PnL;
- no single seven-day bucket contributes more than 50% of positive net PnL.

Drawdown and profit-factor live thresholds are reported separately as promotion-preview checks. Failing a later live threshold cannot be hidden by `CANDIDATE_EDGE` and will prevent future live promotion, but Phase 9 keeps statistical edge evidence distinct from full operational live readiness.

If no candidate qualifies, the correct Phase 9 result is `NO_EDGE_DEMONSTRATED` or `INSUFFICIENT_EVIDENCE`; the system does not force optimization or trade activity.

## 13. Walk-forward evaluation

### 13.1 `WalkForwardPlan`

The plan is deterministic and predeclared:

- dataset manifest ID;
- first window start;
- development/train duration;
- validation duration;
- evaluation duration;
- step duration;
- embargo duration;
- anchored-expanding vs fixed-rolling development mode;
- policy ID.

Phase 9 V1 supports both anchored-expanding and fixed-rolling plans but does not select between them from performance. The chosen plan is frozen in the evaluation manifest.

### 13.2 Window behavior

For each window:

- generate train/validation/evaluation partitions mechanically;
- purge lifecycle-crossing trades;
- apply embargo;
- compute the same metrics independently;
- mark insufficient windows rather than padding them;
- preserve exact trade IDs and boundaries in the result.

Aggregate walk-forward metrics are computed only from evaluation partitions, never training/validation outcomes.

## 14. Slice diagnostics

Primary results include deterministic slices by:

- market;
- lead strategy;
- direction;
- trend regime;
- volatility regime;
- UTC hour bucket;
- score bucket;
- evidence class;
- calendar month/week where useful.

### 14.1 Score buckets

Strategy score is 0-100 and is not a probability.

Use fixed 10-point buckets (`[0,10)`, ..., `[90,100]`) rather than data-dependent quantiles. Report trade count, mean net R, median net R, profit factor, and win rate per sufficiently sampled bucket.

Do not label this probability calibration.

### 14.2 Multiple-slice discipline

Slice reports are diagnostics. Phase 9 does not automatically pick the best market/regime/hour/score slice and create a new strategy from it. Any later strategy change is a new candidate and must receive a new frozen validation lineage.

## 15. Cost sensitivity

Sensitivity must answer whether an apparent edge survives worse costs without turning Phase 9 into parameter search.

### 15.1 Predeclared accounting stress profiles

V1 supports a small fixed set of versioned profiles, frozen before untouched OOS evaluation:

- `base` — actual Phase 8 recorded costs;
- `fees_1_25x` — fees multiplied by 1.25;
- `adverse_slippage_1_50x` — favorable signed slippage credit removed; adverse slippage drag multiplied by 1.50;
- `adverse_funding_1_50x` — favorable funding credit removed; adverse funding cash flow multiplied by 1.50;
- `combined_stress` — applies all three adverse adjustments.

For accounting-only stress, reconstruct a reference-price gross PnL using Phase 8 signed slippage amounts, then apply the declared stressed drag. This is clearly labeled a post-trade accounting stress and does **not** pretend to model changed fill/no-fill behavior.

### 15.2 Execution-path sensitivity

If changed execution assumptions could alter fills or trade existence, use separate operator-supplied Phase 8 replay manifests generated under those predeclared configurations. Phase 9 compares those manifests; it does not auto-search execution parameters.

## 16. NO_TRADE missed-opportunity analysis

Phase 8 already provides deterministic `NO_TRADE` sampling primitives. Phase 9 adds an evidence-safe outcome diagnostic.

For sampled `NO_TRADE` decisions:

- require a matching `DecisionEvaluationFact`;
- use only future mark/candle evidence that becomes available after the decision time;
- evaluate predeclared fixed horizons from policy;
- record subsequent absolute/signed mark movement and favorable/adverse extrema;
- mark horizons incomplete when a known gap intersects them;
- never fabricate a hypothetical order book or call the result executable trade PnL.

V1 default horizons are 1 hour and 4 hours, aligned with existing context horizons and fully versioned in policy.

The analysis answers whether the strategy systematically ignored large subsequent moves; it does not manufacture counterfactual fills.

## 17. Result contracts

### 17.1 `PerformanceMetrics`

Immutable Decimal-based metrics plus explicit unavailable-reason fields where a statistic cannot be supported.

### 17.2 `SliceMetrics`

Slice key, sample size, research-ready flag, and the supported subset of performance metrics.

### 17.3 `WalkForwardWindowResult`

Window boundaries, included/excluded trade IDs, metrics, readiness, and deterministic result digest.

### 17.4 `PromotionGatePreview`

Read-only checks against already locked later-stage thresholds:

- profit factor >= 1.20;
- account max drawdown <= 8% when supported;
- market positive-PnL concentration <= 35%;
- seven-day positive-PnL concentration <= 50%;
- closed paper trades >= 500;
- covered/shadow days >= 45;
- zero unresolved invariant failures where that evidence is available.

The object must expose `preview_only=True` and cannot enable execution.

### 17.5 `EvaluationResult`

Contains:

- dataset manifest ID;
- split manifest ID;
- candidate-set ID;
- policy ID;
- OOS consumption status;
- train/validation/test metric sets;
- uncertainty results;
- walk-forward results;
- slice reports;
- sensitivity reports;
- NO_TRADE report references;
- edge evidence status;
- promotion-gate preview;
- exact included/excluded sample counts and reason codes;
- deterministic result digest;
- schema version.

## 18. CLI / operator workflow

Add offline commands only:

```text
cocomelon freeze-evaluation-dataset --journal PATH --facts PATH --out MANIFEST
cocomelon freeze-evaluation-splits --dataset MANIFEST --splits SPEC --store PATH
cocomelon evaluate --dataset MANIFEST --splits ID --facts PATH --journal PATH --store PATH
cocomelon inspect-evaluation --store PATH --evaluation-id ID
```

Optional later Phase 9 command:

```text
cocomelon evaluate-no-trade --manifest PATH --journal PATH --facts PATH --out PATH
```

Rules:

- no implicit network fetches;
- no testnet options;
- no live adapter;
- no parameter-search command;
- all split/candidate/policy inputs are printed in machine-readable output;
- inspect commands are read-only.

## 19. Failure behavior

Fail closed or downgrade evidence status on:

- missing Phase 8 manifest/result referenced by the dataset;
- result digest mismatch;
- missing trade or decision fact;
- trade/decision market/direction mismatch;
- non-finite financial value;
- duplicate trade IDs;
- overlapping/invalid split boundaries;
- lifecycle crossing a split boundary without purge;
- OOS reuse by a changed candidate set/policy;
- data-incomplete replay when a metric requires completeness;
- insufficient account-equity facts for mark-to-market drawdown;
- invalid walk-forward window generation;
- sensitivity profile not frozen before test consumption;
- any testnet/live/private capability appearing in Phase 9 modules.

An unavailable statistic is not replaced with zero or an optimistic sentinel.

## 20. Module boundaries

Proposed package:

```text
src/cocomelon/domain/evaluation.py
src/cocomelon/evaluation/
  __init__.py
  facts.py
  store.py
  dataset.py
  splits.py
  metrics.py
  uncertainty.py
  walkforward.py
  slices.py
  sensitivity.py
  no_trade.py
  engine.py
```

The implementation may combine very small modules when doing so improves clarity, but these responsibilities must stay conceptually separate.

`evaluation` may import stable Phase 4-8 domain/accounting contracts. Phase 4-8 trading packages must not import `evaluation`.

## 21. Determinism

- canonical JSON uses sorted keys and finite Decimal strings;
- IDs are SHA-256-derived semantic digests;
- tuple/set inputs are canonicalized before hashing;
- split generation uses integer timestamps only;
- bootstrap is the only pseudo-random operation and is seeded from immutable manifest identity;
- no wall-clock time enters result IDs;
- no network access enters evaluation;
- no ambient Decimal context changes authoritative calculations.

## 22. Testing strategy

### 22.1 Domain/store

- hostile Decimal context determinism;
- ID changes for every semantic field;
- exact restart round-trip;
- conflicting duplicate failure;
- transaction rollback.

### 22.2 Dataset joins

- trade/decision reconciliation;
- duplicate/missing facts;
- mixed evidence labels;
- incomplete source evidence;
- canonical enumeration independence.

### 22.3 Split/OOS protection

- absolute time splits;
- boundary-crossing purge;
- embargo behavior;
- identical rerun idempotency;
- changed candidate/policy -> `OOS_CONTAMINATED`;
- candidate set frozen before reveal.

### 22.4 Metrics

Frozen synthetic Decimal fixtures cover:

- profitable/unprofitable/flat sets;
- no-loss profit-factor behavior;
- fees/funding/slippage decomposition;
- realized drawdown;
- genuine account-equity drawdown when facts exist;
- concentration;
- tail metrics;
- insufficient sample handling.

### 22.5 Uncertainty

- same manifest -> same bootstrap interval;
- changed manifest -> changed deterministic seed where sample selection matters;
- block grouping preserves daily clusters;
- insufficient samples return unavailable rather than fake confidence.

### 22.6 Walk-forward

- no future window leakage;
- exact deterministic windows;
- only evaluation partitions aggregate into walk-forward evidence;
- insufficient windows excluded with reasons.

### 22.7 Sensitivity

- adverse fee/slippage/funding formulas;
- favorable slippage/funding is not amplified under stress;
- sensitivity cannot improve base result through sign mistakes;
- predeclared profile IDs are provenance-bound.

### 22.8 NO_TRADE

- deterministic sampling;
- future evidence visible only after decision;
- gaps mark outcomes incomplete;
- no L2/fill fabrication.

### 22.9 End-to-end

Build a frozen Phase 8 journal/fact fixture with:

- positive candidate that passes research evidence;
- weak candidate that returns `NO_EDGE_DEMONSTRATED`;
- small candidate that returns `INSUFFICIENT_EVIDENCE`;
- contaminated candidate-set reuse;
- concentration failure despite aggregate profitability.

Run twice and require identical evaluation IDs/results.

### 22.10 Boundary audit

Source-scan Phase 9 for:

- testnet;
- network/Hyperliquid clients;
- wallet/private-key/signing;
- transfer/withdraw;
- live order capability;
- ML libraries/training;
- parameter-optimization/search loops;
- candle-to-L2 construction.

## 23. Non-goals

Phase 9 does not:

- change strategy formulas to improve the report;
- tune Phase 5 thresholds against OOS;
- change hard Phase 6 risk limits;
- train scikit-learn/LightGBM/XGBoost models;
- create a champion/challenger registry beyond freezing evaluation candidate identity;
- begin long-running Phase 11 shadow promotion;
- implement a Hyperliquid live adapter;
- add wallet/signing/private exchange-account code;
- use Hyperliquid testnet;
- fabricate historical order flow;
- promise profitability.

## 24. Exit criteria

Phase 9 is complete when:

1. evaluation facts preserve the score/regime/account context required by `MASTER_SPEC.md` without mutating Phase 8 journal identity;
2. evaluation datasets and split manifests are deterministic and provenance-complete;
3. untouched OOS consumption is mechanically recorded and changed candidates/policies cannot silently reuse it as untouched;
4. split-boundary lifecycle purge and embargo tests pass;
5. cost-aware metrics, drawdown/tail/concentration diagnostics, and deterministic uncertainty tests pass;
6. walk-forward evaluation is deterministic and lookahead-safe;
7. fixed sensitivity profiles cannot become parameter optimization;
8. sampled NO_TRADE outcomes use genuine future evidence and never claim executable counterfactual PnL;
9. full core Python 3.12 compile/Ruff/mypy/pytest CI passes;
10. Phase 9 boundary tests prove no ML/live/testnet/private/candle-to-book capability was introduced;
11. an evaluation result for available baseline evidence is recorded as exactly one of `CANDIDATE_EDGE`, `NO_EDGE_DEMONSTRATED`, `INSUFFICIENT_EVIDENCE`, `OOS_CONTAMINATED`, or `INVALID_EVIDENCE`;
12. if current real recorded evidence is insufficient, the project says so and does not fabricate an edge to satisfy the phase;
13. Phase 10 remains deferred until Phase 9 is merged and its evidence status is explicit;
14. live trading remains disabled.
