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
- reason codes are non-empty and deduplicated while preserving first occurrence;
- primary LONG/SHORT requires a positive finite invalidation price;
- primary signals may not set context vetoes;
- primary NO_TRADE has no invalidation;
- context signals never set an invalidation price;
- context may favor LONG/SHORT/NO_TRADE and may veto LONG and/or SHORT;
- `NO_TRADE` may never appear inside `veto_directions`;
- veto directions are deduplicated in deterministic LONG/SHORT enum order;
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
- signal IDs are stored in deterministic strategy-name then signal-ID order;
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

- sort by `(end_ms, start_ms)` deterministically;
- use only closed candles with `end_ms <= as_of_ms` and `received_at_ms <= as_of_ms`;
- reject market/interval mismatches;
- ignore future observations rather than leaking them into a decision;
- require explicit minimum sample counts per engine.

Directional primary signals use market structure for invalidation, not an arbitrary account-risk percentage. Phase 6 will later translate stop distance into position size.

Before accepting a directional invalidation:

- resolve reference price from positive finite `mid_px`, otherwise positive finite `mark_px`;
- LONG invalidation must be below the reference price;
- SHORT invalidation must be above the reference price;
- invalidation must be positive and finite.

The default swing window for trend and mean reversion is the latest **4 closed 15m candles** available at decision time.

## 6. Primary engine baselines

All thresholds below are transparent configurable **baseline research defaults**, not optimized claims. Phase 9 evaluation may later revise them through evidence.

Every primary engine returns a `StrategySignal`. It emits LONG/SHORT only when its own family threshold is met. Otherwise it returns NO_TRADE while preserving the strongest computed score and reason codes where useful.

### 6.1 Trend engine

Purpose: detect persistent multi-timeframe continuation.

Minimum inputs:

- rankable + deep-ready market;
- known `trend_regime` of UP or DOWN;
- 15m and 1h returns;
- at least 4 closed 15m candles.

Direction:

- UP -> candidate LONG;
- DOWN -> candidate SHORT.

Hard alignment rule:

- 15m return must have the regime sign;
- 1h return must have the regime sign;
- if either opposes, emit NO_TRADE.

Exact default score:

- `25` points: directional trend regime exists;
- `+20`: 15m return aligns;
- `+20`: 1h return aligns;
- `+10`: 4h return exists and aligns;
- `+5`: 5m return exists and aligns;
- `+5`: `relative_volume_15m >= 1.00`;
- `+5`: book imbalance exists and is at least `+0.10` for LONG or at most `-0.10` for SHORT.

Maximum score is clamped to `100`.

Default family threshold: `>= 65`.

Invalidation:

- LONG: minimum low of the latest 4 closed 15m candles;
- SHORT: maximum high of the latest 4 closed 15m candles.

If the resulting invalidation is on the wrong side of the reference price, emit NO_TRADE with `invalid_invalidation`.

### 6.2 Breakout engine

Purpose: detect expansion beyond an established closed-candle range with confirmation.

Minimum inputs:

- rankable + deep-ready market;
- at least 21 closed 15m candles: 20 prior range candles + 1 trigger candle.

Range definition:

- upper boundary = maximum high of the preceding 20 closed 15m candles;
- lower boundary = minimum low of the preceding 20 closed 15m candles;
- trigger candle is the 21st/latest closed candle and is excluded from range construction.

Direction:

- trigger close above upper boundary -> LONG candidate;
- trigger close below lower boundary -> SHORT candidate;
- otherwise NO_TRADE.

At least one expansion confirmation is mandatory:

- `relative_volume_15m >= 1.20`; or
- `range_expansion_15m >= 1.10`.

Exact default score after structural breakout exists:

- `50` points: close is beyond the prior 20-candle boundary;
- `+20`: relative-volume confirmation passes;
- `+20`: range-expansion confirmation passes;
- `+10`: 1h return exists and aligns with breakout direction.

Maximum score is clamped to `100`.

Default family threshold: `>= 70`.

Because at least one expansion confirmation is mandatory, an unconfirmed boundary break remains NO_TRADE even if another optional point source would otherwise lift its score.

Invalidation:

- LONG: trigger candle low;
- SHORT: trigger candle high.

If the invalidation is on the wrong side of the current reference price, emit NO_TRADE.

### 6.3 Mean-reversion engine

Purpose: fade a statistically stretched short-term move only when the regime is compatible.

Minimum inputs:

- rankable + deep-ready market;
- `trend_regime == MIXED`;
- volatility regime is LOW or NORMAL, never HIGH/UNKNOWN;
- usable non-zero 15m return;
- positive finite realized-volatility feature;
- at least 4 closed 15m candles.

Stretch metric:

`stretch = abs(return_15m) / realized_vol_15m`

Default trigger: `stretch >= 1.75`.

Direction:

- stretched positive 15m move -> SHORT candidate;
- stretched negative 15m move -> LONG candidate.

Exact default score after compatible regime and stretch trigger:

- `45` points: compatible regime + base stretch trigger passes;
- `+20`: `stretch >= 2.25`;
- `+15`: `range_expansion_15m >= 1.10`;
- `+10`: 5m return exists and has the proposed reversion direction;
- `+10`: 1h return exists and has the proposed reversion direction.

Maximum score is clamped to `100`.

Default family threshold: `>= 65`.

Invalidation:

- LONG: minimum low of the latest 4 closed 15m candles;
- SHORT: maximum high of the latest 4 closed 15m candles.

The order-flow context engine may veto a mean-reversion entry when aggressive real microstructure strongly confirms continuation.

## 7. Funding/open-interest context engine

Funding/OI is context, not a standalone contrarian strategy.

Inputs:

- current funding;
- OI change fraction when available;
- 15m and 1h returns when available.

Default constants:

- `oi_support_threshold = 0.01`;
- `oi_extreme_threshold = 0.03`;
- `funding_crowded_threshold = 0.0001`;
- `funding_extreme_threshold = 0.0002`.

Exact default behavior, evaluated in this order:

1. If OI change is missing or non-positive, return neutral context (`NO_TRADE`, score `0`).
2. If `oi_change_fraction >= 0.03` and `funding >= 0.0002`, return neutral direction with score `100` and veto LONG.
3. If `oi_change_fraction >= 0.03` and `funding <= -0.0002`, return neutral direction with score `100` and veto SHORT.
4. If 15m and 1h returns are both positive, `oi_change_fraction >= 0.01`, and `abs(funding) < 0.0001`, support LONG with score `70`.
5. If 15m and 1h returns are both negative under the same OI/funding conditions, support SHORT with score `70`.
6. If OI is expanding but funding is crowded without meeting the extreme-veto rule, return neutral context with score `50` and a crowding reason.
7. Otherwise return neutral context with score `0`.

Extreme funding never automatically originates the opposite direction.

All constants are baseline research defaults, not economic truths.

## 8. Real microstructure window

Create a deterministic derived `MicrostructureWindow` from normalized Phase 3 `StreamEvent` data.

Inputs must be real normalized public `TRADE` and `L2_BOOK` events. Candles may never be used to synthesize trade aggressor flow, book depth, or historical L2 state.

Default window length: `60_000 ms`, configurable.

For each event:

- convert `receive_time` to observed receive milliseconds;
- require receive milliseconds `<= as_of_ms`;
- if `exchange_time_ms` exists, require it `<= as_of_ms`;
- include only events whose receive milliseconds are within `[as_of_ms - window_ms, as_of_ms]`;
- sort by `(receive_ms, exchange_time_ms-or--1, event_key)` before aggregation.

Derived fields:

- `market`;
- `start_ms` / `as_of_ms`;
- `trade_count`;
- aggressive buy notional;
- aggressive sell notional;
- signed trade-flow imbalance in `[-1, 1]`;
- latest available book imbalance;
- optional book-imbalance change when at least two real books exist;
- latest receive-event age;
- ordered source event keys/provenance sufficient to reproduce the window.

Trade notional is `price * size` using `Decimal`.

Hyperliquid normalized trade side handling:

- `B` contributes buy/aggressive-positive notional;
- `A` contributes sell/aggressive-negative notional.

Unknown/malformed sides make the window unusable rather than being guessed.

Trade-flow imbalance is:

`(buy_notional - sell_notional) / (buy_notional + sell_notional)`

when total notional is positive; otherwise it is unavailable.

Latest/earliest real L2 book imbalance uses the same side-depth semantics as Phase 4. If fewer than two usable real book samples exist, book-imbalance change is `None` rather than fabricated.

## 9. Order-flow context engine

Purpose: reinforce timing or block a primary thesis using real current microstructure.

Default constants:

- `window_ms = 60_000`;
- `min_trade_count = 5`;
- `max_event_age_ms = 2_000`;
- `trade_support_threshold = 0.35`;
- `book_support_threshold = 0.15`;
- `trade_veto_threshold = 0.60`;
- `book_veto_threshold = 0.30`.

Exact default behavior:

1. If the microstructure window is missing, unusable, stale, has fewer than 5 trades, lacks trade-flow imbalance, or lacks current book imbalance: neutral context with score `0` and an explanatory reason.
2. If trade-flow imbalance `>= +0.60` and current book imbalance `>= +0.30`: support LONG with score `100` and veto SHORT.
3. If trade-flow imbalance `<= -0.60` and current book imbalance `<= -0.30`: support SHORT with score `100` and veto LONG.
4. Else if trade-flow imbalance `>= +0.35` and current book imbalance `>= +0.15`: support LONG with score `75`.
5. Else if trade-flow imbalance `<= -0.35` and current book imbalance `<= -0.15`: support SHORT with score `75`.
6. Otherwise: neutral context with score `0`; disagreement is not forced into a direction.

Book-imbalance change may be recorded in reasons/evidence and later evaluated, but it is not required for a Phase 5 directional context result because current Phase 3 frozen fixtures contain a trustworthy single-book example while the durable recorder will accumulate real sequences for later replay.

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

Trend-regime weights:

- UP/DOWN: trend `1.00`, breakout `0.90`, mean reversion `0.35`;
- MIXED: trend `0.50`, breakout `0.80`, mean reversion `1.00`;
- UNKNOWN: trend `0.50`, breakout `0.60`, mean reversion `0.50`.

Volatility modifiers:

- HIGH: trend `0.90`, breakout `1.00`, mean reversion `0.25`;
- NORMAL: all `1.00`;
- LOW: trend `0.90`, breakout `0.75`, mean reversion `1.00`;
- UNKNOWN: all `0.75`.

Effective primary weight is trend-regime weight multiplied by volatility modifier.

For each directional primary signal:

`effective_signal_score = raw_signal_score * effective_primary_weight`

### 10.3 Direction candidate score

For each direction independently:

1. collect directional primary signals for that direction;
2. choose the lead primary by highest `effective_signal_score`, tie-breaking by strategy name;
3. start candidate score at the lead primary's effective signal score;
4. add `+5` points for each additional same-direction qualifying primary, capped at `+10` total confirmation bonus;
5. clamp candidate score to `[0, 100]`.

A direction is a valid primary candidate only if:

- lead raw primary score is `>= 60`; and
- candidate score is `>= 60`.

### 10.4 Opposing primary conflict

If both LONG and SHORT primary candidates exist:

- compute `gap = abs(long_candidate_score - short_candidate_score)`;
- if `gap < 15`, return NO_TRADE with `primary_conflict`;
- otherwise keep the stronger direction and continue through context checks.

If only one candidate exists, continue with it.

### 10.5 Context adjustment and veto

Context may never create a candidate when no primary candidate exists.

For the surviving candidate direction:

1. If any context signal lists that direction in `veto_directions`, return NO_TRADE with `context_veto`.
2. For each directional context signal with score above `50`, compute:
   `context_strength = min(10, (score - 50) / 5)`.
3. Same-direction context contributes `+context_strength`.
4. Opposite-direction context contributes `-context_strength`.
5. Sum all context contributions and clamp the total adjustment to `[-10, +10]`.
6. Add the bounded adjustment to the primary candidate score and clamp final score to `[0, 100]`.

Examples:

- context score `75` -> strength `5`;
- context score `100` -> strength `10`.

Final directional trade threshold: `>= 65`.

The final decision invalidation comes from the lead primary only. Context never manufactures, tightens, or widens an invalidation.

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

NO_TRADE decision score is the strongest rejected candidate score after the last completed decision stage, or `0` when no candidate existed.

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

No strategy failure can silently fall through to an order path because no order path exists in Phase 5.

## 13. Testing strategy

Use TDD with deterministic unit and integration fixtures.

### Contract tests

- Decimal score/invalidation handling;
- deterministic signal/decision IDs;
- invalid role/invalidation/veto combinations fail;
- NO_TRADE contract behavior;
- no risk/order fields in final decision contract.

### Trend tests

- aligned UP -> LONG with exact score;
- aligned DOWN -> SHORT with exact score;
- opposing 15m/1h -> NO_TRADE;
- optional aligned features add only documented points;
- wrong-side invalidation -> NO_TRADE;
- insufficient closed candles -> NO_TRADE.

### Breakout tests

- 20-candle prior range excludes trigger candle;
- confirmed upside/downside breakout with exact score;
- no breakout -> NO_TRADE;
- no expansion confirmation -> NO_TRADE;
- future trigger candle cannot leak into decision.

### Mean-reversion tests

- stretched move in MIXED + LOW/NORMAL volatility;
- HIGH/UNKNOWN volatility blocks entry;
- directional trend blocks mean reversion;
- insufficient realized-vol data -> NO_TRADE;
- exact stretch/confirmation point allocation.

### Funding/OI tests

- supportive OI expansion without crowding;
- extreme long crowding vetoes LONG only;
- extreme short crowding vetoes SHORT only;
- extreme funding never creates the opposite trade by itself;
- crowded but non-extreme state is neutral rather than contrarian.

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
- exact regime/volatility weight multiplication;
- exact `+5` same-direction primary confirmation bonus;
- exact primary conflict gap handling;
- same-direction context adjustment follows the documented formula;
- opposite context subtracts symmetrically;
- total context adjustment is capped at 10 points in magnitude;
- explicit context veto wins;
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
