# Historical Two-Sided Directional Learning Plan

**Status:** active  
**Created:** 2026-09-21  
**Supersedes for primary development:** `2026-09-20-r2-natural-research-validation.md`  
**Scope:** offline/touched historical learning engineering and future paper/shadow validation; no live orders.

## Goal

Build a learning system that studies how eligible Hyperliquid perpetual markets behaved in historical market states and estimates the forward opportunity for **LONG**, **SHORT**, and **NO_TRADE** without hard-coding one permanent direction.

The system must learn from trustworthy, timestamped observations only. Future information is allowed only in explicit outcome labels, never in the feature state presented to a model.

## Product target

For each eligible coin and timestamp, the research pipeline should eventually produce:

1. a point-in-time feature state containing only information available at that timestamp;
2. one or more predeclared forward horizons;
3. realized LONG and SHORT outcomes after that state;
4. a trained estimate of the distribution or expected net outcome for each side;
5. a decision policy that selects LONG, SHORT, or NO_TRADE only when expected edge clears costs, uncertainty, eligibility, and risk gates.

The learner is direction-neutral. LONG and SHORT must be evaluated independently. NO_TRADE remains first-class.

## Historical data policy

- Use public Hyperliquid mainnet data only.
- Backfill public candle and funding history as far as the free/public API can honestly provide.
- Respect the documented/implemented 5,000-candle request ceiling; split larger requested windows deterministically rather than pretending one call can return unlimited history.
- Preserve market, interval, timestamps, source identity, schema version, and retrieval provenance.
- Use the project's own authenticated recorder for richer future microstructure, OI, book, trade-flow, and other state that cannot be honestly reconstructed far back in time.
- Do not fabricate historical L2/order-flow/OI observations when the source did not provide them.
- Paid archives remain optional and require a separate documented decision.

## Learning dataset contract

The initial dataset substrate is model-agnostic.

For a historical anchor state:

- the anchor price/state must be fixed at or before the anchor timestamp;
- outcome targets may look forward only by an explicitly declared horizon;
- targets require an exact future observation at the requested timestamp; missing target candles are excluded rather than approximated across gaps;
- LONG gross return and SHORT gross return are both recorded;
- fees, slippage, and funding are applied later through versioned cost/execution assumptions to form net targets;
- every row must be reproducible from immutable source data and versioned transformation code.

Initial target horizons should be evaluated from a common fine-grained base where data permits, including candidates such as 5m, 15m, 30m, 1h, and 4h. Final horizons are frozen per model candidate before evaluation.

## Feature direction

Reuse existing point-in-time Cocomelon features where they are genuinely available:

- multi-timeframe returns and trend regime;
- realized volatility and range expansion;
- relative volume;
- funding level/change;
- open-interest level/change when sourced;
- mark/oracle dislocation;
- spread/depth/book imbalance and order flow only on real recorded microstructure;
- broader BTC/ETH/market context where timestamp-aligned;
- market identity/age/liquidity context where appropriate.

No feature may contain data observed after the row's anchor timestamp.

## Model research

Do not precommit to one model family. Start with transparent baselines and make complexity earn its place.

Candidate sequence:

1. simple conditional/statistical baselines;
2. regularized linear/logistic or tree-based supervised models;
3. boosted trees if they materially improve time-aware OOS results;
4. more complex sequence/deep models only if simpler models are demonstrably insufficient.

Models should estimate side-specific expected net return, probability/distribution of favorable return, or a directly comparable ranking target. They do not control leverage or bypass the independent risk engine.

## Cross-coin learning

Prefer a shared learner across the eligible universe with market/regime features, then evaluate coin-specific calibration only where sufficient data exists.

This lets liquid markets contribute general pattern information while still allowing BTC, ETH, SOL, and smaller markets to express different conditional behavior.

Do not fit isolated per-coin models when the coin does not have enough chronological data to support them.

## Validation

All learning research is chronological.

Required controls:

- train -> validation -> test in time order;
- embargo around split boundaries where required;
- rolling/walk-forward evaluation;
- no random train/test shuffling for time-series evidence;
- no feature normalization fit on future partitions;
- no hyperparameter or feature selection from the untouched test set;
- performance reported by market, regime, direction, horizon, and time;
- complete modeled fees/funding/slippage before any edge claim;
- bootstrap/Bayesian uncertainty where appropriate;
- untouched promotion evidence starts only after the candidate is frozen.

Historical backtests are development evidence. They are not substitutes for future live-mainnet paper/shadow evidence.

## Relationship to r2

`research-r2-short-trend-quality-v1` remains immutable and auditable as a bounded touched short-side hypothesis. It is no longer the product architecture or the sole gate for development.

Do not mutate r2 into a two-sided learner. Preserve its lineage/results separately.

Any future model candidate derived from V4/r1/r2 observations inherits touched lineage. A promotion candidate must be frozen before a new clean validation sample begins.

## Phase status

The Phase 9 exit criterion has been met in the honest-failure sense: the retired V4 baseline did not demonstrate edge.

Therefore Phase 10 **offline learning engineering is active**.

This does **not** authorize:

- live orders;
- live wallet/transfer/withdrawal behavior;
- relaxed risk limits;
- calling touched historical backtests untouched/OOS promotion evidence;
- skipping future paper/shadow promotion gates.

## Implementation sequence

### Slice A — historical outcome substrate

- [x] Add deterministic bounded candle backfill-window planning.
- [x] Add exact-timestamp LONG/SHORT forward-return outcome labels.
- [x] Fail closed on mixed markets, mixed intervals, duplicate timestamps, non-positive prices, and missing exact future target candles.
- [x] Preserve deterministic provenance/identity for labels.

### Slice B — historical source acquisition

- [x] Build an offline historical candle/funding backfill command using `InfoClient`.
- [x] Persist raw responses and normalized records with manifests and checksums.
- [x] Deduplicate page boundaries and detect coverage gaps.
- [x] Add rate-budget-aware resumability.
- [x] Produce coverage reports by market/interval/source.

Verified implementation evidence: PR #235 implementation head `0b463d515b2f0914a1ff7aae5ddc8682a12b931d`; CI run `35609936635` passed compile, Ruff, strict mypy, full pytest, and research smoke.

### Slice C — point-in-time feature reconstruction

- [x] Reconstruct candle/funding-derived feature states using only data available at each anchor.
- [x] Separate features unavailable historically from genuinely sourced fields.
- [x] Join immutable feature rows to directional outcome labels.
- [x] Export versioned columnar training datasets.

Verified implementation evidence: PR #236 implementation head `4c04600d5835197209c5405c9a05d992db38f78a`; CI run `35613448712` passed compile, Ruff, strict mypy, full pytest, and the research job with real PyArrow historical-dataset export.

### Slice D — baseline learners

- [x] Establish simple direction-neutral statistical baselines.
- [x] Add time-aware training and walk-forward evaluation.
- [x] Estimate separate LONG and SHORT conditional edge.
- [x] Calibrate NO_TRADE thresholds after costs using validation data only.
- [x] Compare shared cross-coin versus coin-calibrated variants.

Verified implementation evidence: PR #237 implementation head `2e61ea9966e02475059e54b9c670d681ae4ae449`; CI run `35614793455` passed compile, Ruff, strict mypy, full pytest, and research smoke. The baseline is transparent and direction-neutral, preserves same-anchor temporal grouping, enforces embargo/walk-forward ordering, uses explicit fee/slippage plus a conservative funding reserve, calibrates NO_TRADE thresholds on validation only, regression-locks test-set isolation, and reports shared-only versus coin-calibrated performance separately.

### Slice E — challenger integration

- [ ] Freeze a reproducible model candidate, feature registry, data manifest, and decision policy.
- [ ] Integrate it behind the existing strategy/risk boundary.
- [ ] Keep risk sizing independent and immutable.
- [ ] Run touched research first; only qualifying candidates proceed to future clean validation.

## Hard prohibitions

- No Hyperliquid testnet.
- No future leakage into features.
- No fabricated historical microstructure.
- No random temporal shuffling presented as OOS validation.
- No live wallet/order/transfer/withdrawal behavior.
- No model authority over hard risk limits.
- No manual economic retry/backfill merely to make performance look better.
- No promotion claim from touched historical research alone.


### Slice E1 — empirical challenger hardening

- [x] Make zero-return NO_TRADE dominate non-positive validation policies (#243).
- [x] Add a continuous regularized ridge challenger with train-only preprocessing (#244).
- [x] Compare challenger and transparent baseline on identical chronological folds/data/costs (#245).
- [x] Calibrate NO_TRADE independently by horizon (#246).
- [x] Require multi-block chronological validation stability before a horizon may trade (#248).
- [x] Preserve the observed result that stable ridge selected NO_TRADE across the tested September folds; this avoided losses but did not demonstrate edge.

### Slice E2 — deeper trustworthy history

- [x] Reconstruct deterministic candles from official Hyperliquid node fill archives (#251).
- [x] Gate requester-pays archive inspection/download behind exact acknowledgement, hard byte budgets, and integrity checks (#252).
- [x] Compose verified archive cache -> funding -> reconstructed candles -> authenticated dataset -> model comparison (#253).
- [x] Require archive/native candle overlap equality before archive-based learning may proceed (#254).
- [ ] Run broader multi-regime archive experiments only after the archive source is verified and any requester-pays transfer is explicitly authorized.

### Slice E3 — nonlinear challenger

- [ ] Evaluate the fixed shallow tree challenger in PR #256 under the same chronological folds, costs, NO_TRADE floor, and four-block validation stability rule.
- [ ] Do not tune the tree from test outcomes; reject it if stable validation does not justify trading.
- [ ] Freeze a candidate only after a model demonstrates reproducible touched-development edge strong enough to justify future clean validation.



## Slice F — frozen prospective clean validation

A touched historical discovery has earned prospective-only observation, not promotion.

- [x] Freeze `hype-down-bearish-near-basket-long-4h-v1` before prospective evidence (#289).
- [x] Build append-only prospective observation/outcome evidence with exact 4h settlement (#290–#291).
- [x] Run redundant hourly paper-only public-mainnet observer attempts (#292–#293).
- [x] Freeze a 45-day prospective validation window and economic/data-quality gates (#294).
- [x] Require cumulative state continuity after cutover (#296).
- [x] Stop new observations at the frozen validation end while preserving due settlement (#297).
- [x] Publish immutable per-cycle validation/capture-health evidence (#298).
- [x] Attest the candidate/plan/source runtime before cutover (#299).
- [x] Pin every campaign observer checkout to source revision `0131fccdb09a2b9ba959dd5785ea213a6297f719` (#300).
- [x] Monitor mathematical campaign recoverability without changing the frozen runtime (#302).
- [x] Predeclare one canonical terminal finalization and reject later state/economic drift (#303).
- [x] Freeze the capture-critical workflow control plane before cutover (#304).
- [ ] Collect the frozen 1,080-anchor prospective window from 2026-09-23 through 2026-11-07 without retuning.
- [ ] Settle every due exact 4h outcome under the frozen cost assumptions.
- [ ] Accept the canonical finalization verdict without changing rules from emerging results.
- [ ] If the final status is `eligible_for_candidate_review`, perform candidate review only; do not call the result promoted or live-ready.
- [ ] If the campaign is data-incomplete, not-qualified, or becomes irrecoverable, preserve that result and do not backfill/retry it into success.

### Frozen prospective gates

- 1,080 expected hourly anchors.
- >=90% capture = >=972 observations; 108-anchor maximum miss budget.
- >=80 settled executable trades.
- Four chronological stability blocks.
- >=15 settled executable trades per block.
- Overall modeled mean net return > 0.
- Every block modeled mean net return > 0.
- One-position-per-market occupancy.
- Frozen 4h LONG candidate only when the exact `down/bearish/near_basket` context matches.
- Frozen modeled costs: fee 0.0007 round trip, slippage 0.0005 round trip, funding reserve 0.0001/hour.
- Passing the prospective plan means candidate-review eligibility only.
- Historical discovery and all pre-freeze experimentation remain touched.
- No campaign output can bypass >=500 closed mainnet paper trades, >=45 calendar days shadow, hard risk/integrity gates, or explicit live authorization.

### Freeze rule during Slice F

After the first clean anchor, this campaign is observational. Do not change its candidate specification, context calculation, direction, horizon, costs, occupancy semantics, validation thresholds, observer/report/evidence Python runtime, or capture control-plane identity. Any materially different hypothesis must become a new candidate and a new future campaign; it may not inherit this campaign's evidence.
