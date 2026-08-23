# Phase 5 Design — Explainable Baseline Strategy Engines

**Date:** 2026-08-23
**Status:** Design specification
**Base:** `main` after Phase 4 closeout
**Scope:** Phase 5 only — strategy hypotheses and deterministic decision combination

## 1. Objective

Phase 5 converts Phase 4's trustworthy, versioned feature snapshots and deep-market observations into explainable directional hypotheses and a deterministic final strategy decision:

- `LONG`
- `SHORT`
- `NO_TRADE`

It does not size positions, calculate account risk, submit orders, simulate fills, manage positions, access user/account state, sign messages, or enable live execution.

The design must preserve these locked constraints:

- Hyperliquid mainnet observations only;
- NO_TRADE is first-class and expected to be common;
- eligibility/data-quality gates cannot be bypassed by strategy conviction;
- deterministic explainable baselines come before ML control;
- funding/OI and order flow may strengthen, weaken, or veto a primary thesis, but do not independently originate V1 trades;
- historical order flow is never fabricated from candles;
- strategy scores are evidence-strength scores, not calibrated probabilities.

## 2. Chosen architecture

Use **primary-thesis engines plus context engines**.

### Primary engines

These may originate a directional thesis when their own requirements pass:

1. trend;
2. breakout;
3. mean reversion.

A directional primary signal must carry a deterministic invalidation price that expresses where that thesis is wrong.

### Context engines

These cannot originate a trade by themselves:

4. funding/open-interest context;
5. order-flow/microstructure context.

Context may:

- support LONG;
- support SHORT;
- remain neutral;
- explicitly veto LONG and/or SHORT when configured extreme conditions are present.

### Deterministic combiner

The decision combiner consumes all five engine outputs plus Phase 4 eligibility/regime state. It may emit LONG or SHORT only when:

- the market is rankable;
- the market is `deep_ready`;
- at least one primary engine emits a qualifying directional thesis;
- any primary conflict is resolved by deterministic score/weight rules;
- no context veto blocks the candidate direction;
- final evidence clears the configured threshold;
- the lead primary provides a valid invalidation price.

Otherwise it emits NO_TRADE.

This architecture keeps strategy attribution measurable by family and avoids treating funding/OI or order flow as standalone edges before Phase 9 evidence exists.

## 3. Domain contracts

### 3.1 Direction

Keep the existing `Direction` enum:

- `LONG`
- `SHORT`
- `NO_TRADE`

### 3.2 StrategyRole

Add:

- `PRIMARY`
- `CONTEXT`

### 3.3 StrategySignal

Evolve the existing Phase 1 skeleton rather than introducing a parallel signal type.

Required fields:

- `strategy: str`
- `role: StrategyRole`
- `market: MarketId`
- `direction: Direction`
- `score: Decimal` bounded to `[0, 100]`
- `timestamp_ms: int`
- `reason_codes: tuple[str, ...]`
- `feature_snapshot_id: str`
- `invalidation_price: Decimal | None`
- `veto_directions: tuple[Direction, ...]`

Provide a deterministic `signal_id` derived from the canonical serialized content.

Contract rules:

- financial values use `Decimal`;
- reason codes are non-empty, deduplicated, and deterministically ordered/preserved;
- primary LONG/SHORT requires a positive finite invalidation price;
- primary signals may not set context vetoes;
- primary NO_TRADE has no invalidation;
- context signals never set an invalidation price;
- context may favor LONG/SHORT/NO_TRADE and may veto LONG and/or SHORT;
- `NO_TRADE` may never appear inside `veto_directions`;
- score is evidence strength only and must never be described as probability/confidence calibration.

### 3.4 StrategyDecision

Add an immutable final strategy-decision contract containing:

- deterministic `decision_id`;
- `market`;
- `direction`;
- `score: Decimal` in `[0, 100]`;
- `timestamp_ms`;
- `feature_snapshot_id`;
- `lead_strategy: str | None`;
- `invalidation_price: Decimal | None`;
- `signal_ids: tuple[str, ...]`;
- `reason_codes: tuple[str, ...]`.

Rules:

- LONG/SHORT requires a lead primary strategy and invalidation;
- NO_TRADE has no invalidation and may retain a non-zero score representing the strongest rejected candidate for later missed-opportunity analysis;
- the contract contains no quantity, leverage, account equity, risk budget, order type, target order, wallet, execution mode, or exchange action.

## 4. Strategy input boundary

Use a small immutable `StrategyContext` that contains only decision-time public market state:

- current `PerpMarketSnapshot`;
- current Phase 4 `FeatureSnapshot`;
- matching `EligibilityDecision`;
- closed 5m candles when available;
- closed 15m candles when available;
- optional recent real microstructure window;
- `as_of_ms`.

Validation must require matching market identities across supplied objects.

All candle/event inputs must be at or before `as_of_ms`. Future-received/future-ended observations must not influence the decision. Missing optional information causes a weaker signal or NO_TRADE; it never becomes a fabricated zero or synthetic certainty.

Opportunity rank is intentionally not a required strategy input. Phase 4 ranking decides where to spend attention; it must not masquerade as directional evidence or a probability of profit.

## 5. Candle handling and invalidation

Strategy candle helpers must:

- sort deterministically;
- use only closed candles with `end_ms <= as_of_ms` and `received_at_ms <= as_of_ms`;
- reject market/interval mismatches;
- ignore or fail closed on future observations;
- require explicit minimum sample counts per engine.

Directional primary signals use market structure for invalidation, not an arbitrary account-risk percentage. Phase 6 will later translate stop distance into position size.

Before accepting a directional invalidation:

- resolve reference price from usable `mid_px`, otherwise `mark_px`;
- LONG invalidation must be below the reference price;
- SHORT invalidation must be above the reference price;
- invalidation must be positive and finite.

## 6. Primary engine baselines

All thresholds below are transparent configurable **baseline research defaults**, not optimized claims. Phase 9 evaluation may later revise them through evidence.

### 6.1 Trend engine

Purpose: detect persistent multi-timeframe continuation.

Minimum inputs:

- rankable + deep-ready market;
- known `trend_regime` of UP or DOWN;
- 15m and 1h returns;
- enough closed 15m candles to establish recent swing invalidation.

Direction:

- UP -> candidate LONG;
- DOWN -> candidate SHORT.

Evidence components are additive and deterministic:

- regime direction present;
- 15m return aligns;
- 1h return aligns;
- 4h return aligns when available;
- 5m return aligns when available;
- relative volume at/above baseline when available;
- current book imbalance supports direction when available.

An explicitly opposing 15m or 1h return prevents a directional trend thesis instead of merely subtracting a few points.

Default qualifying score target: `>= 65`.

Invalidation:

- LONG: recent closed-15m swing low over a configurable small window;
- SHORT: recent closed-15m swing high over the same window.

If the resulting invalidation is on the wrong side of the reference price, emit NO_TRADE.

### 6.2 Breakout engine

Purpose: detect expansion beyond an established closed-candle range with confirmation.

Minimum inputs:

- rankable + deep-ready market;
- at least 21 closed 15m candles: 20 prior range candles + 1 trigger candle;
- relative-volume and/or range-expansion context sufficient to validate the move.

Range definition:

- upper boundary = maximum high of the preceding 20 closed 15m candles;
- lower boundary = minimum low of the preceding 20 closed 15m candles;
- trigger candle is excluded from range construction.

Direction:

- trigger close above upper boundary -> LONG candidate;
- trigger close below lower boundary -> SHORT candidate;
- otherwise NO_TRADE.

Confirmation favors:

- `relative_volume_15m >= 1.20` when available;
- `range_expansion_15m >= 1.10` when available;
- broader 1h direction consistent with the breakout when available.

A breakout without enough confirmation remains NO_TRADE rather than lowering the threshold until it trades.

Default qualifying score target: `>= 70`.

Invalidation:

- LONG: trigger candle low;
- SHORT: trigger candle high.

This is a thesis boundary, not a fixed risk percentage. Phase 6 may later reject an impractically wide stop.

### 6.3 Mean-reversion engine

Purpose: fade a statistically stretched short-term move only when the regime is compatible.

Minimum inputs:

- rankable + deep-ready market;
- `trend_regime == MIXED`;
- volatility regime is LOW or NORMAL, never HIGH;
- usable 15m return and realized-volatility feature;
- enough closed 15m candles for a recent extreme/invalidation.

Stretch metric:

`stretch = abs(return_15m) / realized_vol_15m`

Use only when realized volatility is positive and finite.

Default trigger: `stretch >= 1.75`.

Direction:

- stretched positive 15m move -> SHORT candidate;
- stretched negative 15m move -> LONG candidate.

Additional evidence may include range expansion and absence of strong higher-timeframe directional persistence.

Default qualifying score target: `>= 65`.

Invalidation:

- LONG: recent closed-15m swing low / stretch extreme;
- SHORT: recent closed-15m swing high / stretch extreme.

The order-flow context engine is allowed to veto a mean-reversion entry when aggressive real microstructure strongly confirms continuation.

## 7. Funding/open-interest context engine

Funding/OI is context, not a standalone contrarian strategy.

Inputs:

- current funding;
- OI change fraction when available;
- 15m/1h price direction when available.

Default baseline concepts:

- `oi_support_threshold = 0.01` (1% expansion);
- `oi_extreme_threshold = 0.03` (3% expansion);
- `funding_crowded_threshold = 0.0001`;
- `funding_extreme_threshold = 0.0002`.

Behavior:

- price direction + OI expansion with non-crowded funding may support that direction;
- extreme positive funding plus strong OI expansion may veto LONG due to long crowding;
- extreme negative funding plus strong OI expansion may veto SHORT due to short crowding;
- extreme funding does not automatically create the opposite trade;
- falling/unknown OI or missing history generally produces neutral context rather than a fabricated signal.

All thresholds are configurable baselines to be evaluated later, not economic truths.

## 8. Real microstructure window

Create a deterministic derived `MicrostructureWindow` from normalized Phase 3 `StreamEvent` data.

Inputs must be real normalized public `TRADE` and `L2_BOOK` events. Candles may never be used to synthesize trade aggressor flow, book depth, or historical L2 state.

Default window length: `60_000 ms`, configurable.

Derived fields should include at least:

- `market`;
- `start_ms` / `as_of_ms`;
- `trade_count`;
- aggressive buy notional;
- aggressive sell notional;
- signed trade-flow imbalance in `[-1, 1]`;
- available latest book imbalance;
- optional book-imbalance change when at least two real books exist;
- latest event age;
- source event keys/provenance sufficient to reproduce the window.

Trade notional is `price * size` using `Decimal`.

Hyperliquid normalized trade side handling:

- `B` contributes buy/aggressive-positive notional;
- `A` contributes sell/aggressive-negative notional.

Unknown/malformed sides make the affected window unusable rather than being guessed.

Insufficient or stale real microstructure produces neutral order-flow context.

## 9. Order-flow context engine

Purpose: reinforce timing or block a primary thesis using real current microstructure.

Baseline defaults, configurable:

- directional trade-flow support at absolute imbalance `>= 0.35`;
- directional current book-imbalance support at absolute imbalance `>= 0.15`;
- extreme opposite-flow veto may require trade-flow imbalance `>= 0.60` in magnitude plus book imbalance `>= 0.30` in the same opposite direction;
- require a minimum real trade count and fresh-enough event age.

Behavior:

- aligned aggressive buy flow + positive book imbalance may support LONG;
- aligned aggressive sell flow + negative book imbalance may support SHORT;
- extreme coherent flow may veto the opposite candidate direction;
- disagreement between trades/book remains neutral or weak rather than being forced into a direction;
- missing/stale microstructure is neutral and cannot become synthetic confirmation.

## 10. Deterministic decision combiner

### 10.1 Hard preconditions

Immediately return NO_TRADE when:

- `rankable` is false;
- `deep_ready` is false;
- market identities mismatch;
- feature snapshot is not decision-time valid;
- no primary thesis qualifies.

### 10.2 Regime-aware primary weights

Use simple transparent weights, not learned parameters.

Recommended starting matrix:

Trend regime:

- UP/DOWN: trend `1.00`, breakout `0.90`, mean reversion `0.35`;
- MIXED: trend `0.50`, breakout `0.80`, mean reversion `1.00`;
- UNKNOWN: trend `0.50`, breakout `0.60`, mean reversion `0.50`.

Volatility modifiers:

- HIGH: trend `0.90`, breakout `1.00`, mean reversion `0.25`;
- NORMAL: all `1.00`;
- LOW: trend `0.90`, breakout `0.75`, mean reversion `1.00`;
- UNKNOWN: all `0.75`.

Effective primary weight is trend-regime weight multiplied by volatility modifier.

### 10.3 Candidate construction

For each direction:

- include only qualifying primary directional signals;
- compute a weighted aggregate evidence score;
- identify the lead primary as highest weighted evidence with a stable deterministic tie-break by strategy name;
- preserve all contributing signal IDs/reasons.

A candidate must have:

- lead primary raw score `>= 60`;
- weighted primary evidence `>= 60`.

### 10.4 Opposing primary conflict

If both LONG and SHORT candidates exist:

- if evidence gap is `< 15` points -> NO_TRADE with `primary_conflict`;
- otherwise the stronger candidate may continue through context checks.

### 10.5 Context adjustment and veto

Context may not create a candidate when no primary candidate exists.

For an existing candidate:

- any explicit veto of that direction -> NO_TRADE;
- same-direction context may add at most `+10` points total;
- opposite-direction context may subtract at most `-10` points total;
- context adjustments are deterministic and bounded.

Final trade threshold: `>= 65`.

The final decision invalidation comes from the lead primary only. Context never manufactures or widens an invalidation.

### 10.6 NO_TRADE reason codes

At minimum support stable reasons for:

- `not_rankable`;
- `not_deep_ready`;
- `missing_primary_data`;
- `no_primary_thesis`;
- `primary_conflict`;
- `context_veto`;
- `below_decision_threshold`;
- `invalid_invalidation`;
- `stale_microstructure` where relevant.

## 11. Orchestration boundary

Add a small `StrategyEngine`/orchestrator that:

1. validates the `StrategyContext`;
2. runs trend, breakout, and mean-reversion primary engines;
3. runs funding/OI and order-flow context engines;
4. passes the complete signal set into the deterministic combiner;
5. returns both individual signals and the final `StrategyDecision` for later journaling/evaluation.

It must not import or call:

- risk sizing/approval;
- execution adapters;
- orders/fills;
- wallet/account APIs;
- live-mode activation;
- ML models.

## 12. Failure behavior

Fail closed.

- market identity mismatch -> reject context / deterministic error at boundary;
- future candle/event input -> cannot contribute;
- missing required primary inputs -> primary NO_TRADE;
- stale/insufficient order flow -> neutral context;
- malformed microstructure -> unusable/neutral context, never guessed;
- invalid lead invalidation -> final NO_TRADE;
- no qualifying thesis -> NO_TRADE.

No strategy failure should silently fall through to an order path because no order path exists in Phase 5.

## 13. Testing strategy

Use TDD with deterministic unit and integration fixtures.

Required coverage:

### Contract tests

- Decimal score/invalidation handling;
- deterministic signal/decision IDs;
- invalid role/invalidation/veto combinations fail;
- NO_TRADE contract behavior;
- no risk/order fields in final decision contract.

### Trend tests

- aligned UP -> LONG;
- aligned DOWN -> SHORT;
- opposing 15m/1h -> NO_TRADE;
- wrong-side invalidation -> NO_TRADE;
- insufficient closed candles -> NO_TRADE.

### Breakout tests

- 20-candle prior range excludes trigger candle;
- confirmed upside/downside breakout;
- no breakout -> NO_TRADE;
- weak volume/range confirmation -> NO_TRADE;
- future trigger candle cannot leak into decision.

### Mean-reversion tests

- stretched move in MIXED + LOW/NORMAL volatility;
- HIGH volatility blocks entry;
- directional trend blocks mean reversion;
- insufficient realized-vol data -> NO_TRADE.

### Funding/OI tests

- supportive OI expansion without crowding;
- extreme long crowding vetoes LONG only;
- extreme short crowding vetoes SHORT only;
- extreme funding never creates the opposite trade by itself.

### Order-flow tests

Use Phase 3 real-mainnet fixture structures, especially:

- `tests/fixtures/hyperliquid_ws/trades_btc.json`;
- `tests/fixtures/hyperliquid_ws/l2_book_btc.json`.

Tests must prove:

- real B/A trade sides become signed notional correctly;
- real trade-flow imbalance is deterministic;
- current real L2 imbalance can be included;
- missing second book leaves book-change absent rather than fabricated;
- insufficient/stale data becomes neutral;
- candle data is never accepted by the microstructure-window builder.

Synthetic candle fixtures are acceptable for candle-strategy unit tests. They must not be relabeled as historical order-flow evidence.

### Combiner tests

- ineligible/deep-not-ready markets cannot trade despite high primary scores;
- context alone cannot originate a trade;
- same-direction support can strengthen a real primary candidate;
- explicit context veto wins;
- close LONG/SHORT primary conflict -> NO_TRADE;
- clearly dominant candidate can survive conflict;
- lead primary supplies invalidation;
- deterministic input permutation yields identical decision.

### Boundary tests

- strategy package contains no execution behavior;
- no account/wallet/user API dependency;
- no quantity/leverage/risk budget in output;
- no ML dependency.

## 14. Expected implementation layout

Likely files:

- modify `src/cocomelon/domain/strategy.py`;
- create `src/cocomelon/strategies/__init__.py`;
- create `src/cocomelon/strategies/context.py`;
- create `src/cocomelon/strategies/candles.py`;
- create `src/cocomelon/strategies/trend.py`;
- create `src/cocomelon/strategies/breakout.py`;
- create `src/cocomelon/strategies/mean_reversion.py`;
- create `src/cocomelon/strategies/funding_oi.py`;
- create `src/cocomelon/strategies/microstructure.py`;
- create `src/cocomelon/strategies/order_flow.py`;
- create `src/cocomelon/strategies/decision.py`;
- create `src/cocomelon/strategies/engine.py`;
- focused tests under `tests/` for each contract/engine/combiner.

The implementation plan may combine very small modules where that improves clarity, but it must not collapse all logic into one monolithic strategy file.

## 15. Exit criteria

Phase 5 is complete only when fresh verification proves:

- trend, breakout, mean-reversion, funding/OI, and order-flow engines exist;
- each engine has deterministic unit tests;
- a shared immutable StrategySignal contract is used;
- the deterministic regime-aware combiner emits LONG/SHORT/NO_TRADE;
- eligibility/deep-readiness cannot be bypassed;
- NO_TRADE is a normal tested outcome;
- every directional final decision references its exact feature snapshot and a valid lead-primary invalidation;
- order-flow logic uses real trade/L2 structures and never fabricated candle microstructure;
- compileall, Ruff, mypy, and pytest are green;
- no risk sizing, paper fills, wallet/account access, orders, ML, or live execution is introduced.

## 16. Deferred to later phases

Explicitly out of Phase 5:

- account-equity/risk-budget sizing;
- stop-distance position sizing;
- correlation buckets and drawdown lockouts;
- paper fill simulation;
- targets/partial exits/trailing position management;
- journal persistence and replay;
- out-of-sample/walk-forward profitability evaluation;
- ML/champion-challenger logic;
- long-running service loop;
- live exchange adapter.
