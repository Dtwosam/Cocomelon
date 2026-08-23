# Phase 6 Independent Risk Engine Design

**Status:** Approved by current user delegation to continue autonomously  
**Date:** 2026-08-23  
**Base:** `main` at `10c53bfd1a5781baa1233f50534e2e995e8586fb`

## 1. Goal

Build an independent, deterministic, fail-closed risk engine that converts a Phase 5 directional `StrategyDecision` into either a bounded exposure approval or an explicit rejection. Risk is authoritative over strategy conviction and must remain completely separate from exchange order placement.

The economic objective is capital-efficient survival while preserving positive net expectancy after realistic costs. The risk engine must never increase risk because a strategy score is high, chase losses, or force capital deployment when constraints imply `REJECT`.

## 2. Scope boundary

Phase 6 may:

- validate a directional Phase 5 decision and its invalidation;
- consume immutable account, open-risk, market-liquidity, health, and cost estimates;
- compute risk budget, stop-distance loss fraction, cost-aware notional, and independent caps;
- enforce aggregate, correlation, drawdown, cooldown, liquidity, margin, leverage, and liquidation-buffer constraints;
- produce deterministic `APPROVE` / `REJECT` decisions with stable reason codes and audit fields.

Phase 6 may not:

- place, cancel, or query exchange orders;
- simulate fills or partial fills;
- mutate account equity or position state;
- access wallets, signing, user/account exchange APIs, transfers, or withdrawals;
- add to an existing same-market position;
- implement martingale, loss-recovery sizing, or score-proportional risk sizing;
- implement ML or dynamically rewrite hard risk limits;
- enable live trading.

Phase 7 will translate an approved risk decision into paper execution behavior.

## 3. Architecture

Use a pure deterministic risk kernel plus an explicit fixed rule pipeline. All state needed for a decision is supplied through immutable inputs. There is no hidden mutable `RiskManager` state and no plugin rule framework in V1.

Data flow:

```text
StrategyDecision
      +
immutable account/open-risk/liquidity/health/cost state
      |
      v
validate request identity + freshness
      |
      v
hard veto pipeline
      |
      v
cost-aware base sizing
      |
      v
aggregate/correlation/margin/leverage/liquidity caps
      |
      v
liquidation-buffer validation
      |
      v
APPROVE bounded notional OR REJECT zero exposure
```

No later rule may undo an earlier veto.

## 4. Core contracts

All monetary, price, ratio, notional, PnL, and percentage values use `Decimal`.

### 4.1 `RiskLimits`

Immutable configuration snapshot with:

- `risk_per_trade = Decimal("0.0025")`
- `max_open_risk = Decimal("0.0075")`
- `daily_loss_limit = Decimal("0.01")`
- `weekly_drawdown_limit = Decimal("0.03")`
- `consecutive_loss_cooldown = 3`
- `cooldown_ms = 3_600_000`
- `correlation_bucket_risk_limit = Decimal("0.005")`
- `max_gross_leverage = Decimal("3")`
- `max_available_margin_fraction = Decimal("0.50")`
- `max_visible_depth_fraction = Decimal("0.10")`
- `min_liquidation_stop_multiple = Decimal("2")`
- `max_state_age_ms` configurable, initial default `5_000` for risk/account health snapshots.

The locked 0.25% / 0.75% / 1% / 3% values come from `AGENTS.md`, `MASTER_SPEC.md`, and D-006. New Phase 6 defaults are deliberately conservative V1 constraints and are versioned configuration, not claims of optimality.

### 4.2 `RiskAccountState`

Immutable current control state:

- `equity`
- `day_start_equity`
- `daily_realized_pnl`
- `rolling_7d_peak_equity`
- `available_margin`
- `gross_open_notional`
- `consecutive_losses`
- `last_closed_trade_ms`
- `as_of_ms`
- deterministic `state_id`

Validation rejects negative/NaN/infinite values where economically invalid. Current equity and day-start equity must be positive. Rolling peak must be at least current equity unless the state is rejected as inconsistent.

### 4.3 `OpenPositionRisk`

Represents every currently open or reserved exposure:

- market
- direction
- planned_risk
- notional
- correlation_bucket
- entry_price
- stop_price

Risk sums planned loss absolutely. Opposite directions do not automatically offset risk.

### 4.4 `RiskHealthState`

Contains:

- `market_data_fresh`
- `account_state_fresh`
- `execution_health_ok`
- `state_consistent`
- `as_of_ms`

Any false required health flag rejects new exposure. Phase 6 does not inspect an exchange connection directly; callers provide already-normalized health state.

### 4.5 `ExecutionCostEstimate`

Pre-execution conservative cost estimate supplied by observable market state / future Phase 7 models:

- `entry_slippage_fraction`
- `stop_slippage_fraction`
- `round_trip_fee_fraction`

All must be finite and non-negative. Costs consume the trade risk budget rather than being ignored.

### 4.6 `LiquidityRiskState`

Contains:

- `entry_side_visible_notional_25bps`
- `exit_side_visible_notional_25bps`
- `venue_max_leverage`
- `liquidation_price`
- optional `venue_min_notional`
- `as_of_ms`

Visible-depth capacity uses the weaker entry/exit-side notional. `venue_max_leverage` must be positive. `liquidation_price` is supplied as a validated venue/account estimate; Phase 6 does not invent Hyperliquid liquidation formulas.

### 4.7 `RiskRequest`

Contains:

- the exact Phase 5 `StrategyDecision`;
- `entry_reference_price`;
- correlation bucket;
- account state;
- tuple of open-position risk records;
- health state;
- cost estimate;
- liquidity state;
- risk limits;
- `timestamp_ms`.

The request must preserve the Phase 5 decision ID and feature snapshot reference transitively through `StrategyDecision`.

### 4.8 `RiskDecision`

Replace the Phase 1 placeholder with an immutable Decimal-based contract containing:

- deterministic `risk_decision_id`;
- `strategy_decision_id`;
- market;
- direction;
- `approved`;
- stable sorted/ordered reason codes;
- `target_risk_amount`;
- `approved_risk_amount`;
- `approved_notional`;
- `entry_reference_price`;
- `stop_price`;
- `stop_distance_fraction`;
- `effective_loss_fraction`;
- `correlation_bucket`;
- `binding_caps`;
- `timestamp_ms`.

Rejected decisions always have `approved_risk_amount == 0` and `approved_notional == 0`.

No order type, quantity step, wallet, account key, exchange order ID, fill, or execution method belongs in this contract.

## 5. Deterministic rule pipeline

Rules execute in this exact order.

### 5.1 Request / strategy validation

Reject when:

- strategy direction is `NO_TRADE`;
- strategy market identity is inconsistent with any risk-state market-scoped input;
- strategy invalidation is missing;
- LONG stop is not strictly below entry reference;
- SHORT stop is not strictly above entry reference;
- entry or stop is non-positive/non-finite;
- request timestamp is earlier than strategy timestamp or inconsistent with state timestamps.

A strategy score does not alter the risk percentage.

### 5.2 Health / freshness veto

Reject if market data, account state, execution health, or normalized state consistency is unhealthy. Reject if required risk/liquidity/account timestamps are in the future or older than `max_state_age_ms` relative to request time.

### 5.3 Same-market exposure veto

If any open position has the same canonical market, reject new opening exposure regardless of its direction or PnL. This makes averaging down, doubling, and V1 winner pyramiding impossible through the public new-exposure interface.

### 5.4 Daily lockout

If `daily_realized_pnl <= -(day_start_equity * daily_loss_limit)`, reject.

This uses realized loss relative to day-start equity, not current-equity percentage drift.

### 5.5 Rolling weekly drawdown lockout

If current equity satisfies:

`(rolling_7d_peak_equity - equity) / rolling_7d_peak_equity >= weekly_drawdown_limit`

reject.

### 5.6 Consecutive-loss cooldown

When `consecutive_losses >= consecutive_loss_cooldown`, reject until:

`timestamp_ms - last_closed_trade_ms >= cooldown_ms`.

If a cooldown is active but `last_closed_trade_ms` is missing/invalid, fail closed.

### 5.7 Base cost-aware sizing

Compute:

```text
target_risk_amount = equity * risk_per_trade
stop_distance_fraction = abs(entry - stop) / entry
effective_loss_fraction =
    stop_distance_fraction
    + entry_slippage_fraction
    + stop_slippage_fraction
    + round_trip_fee_fraction
raw_notional = target_risk_amount / effective_loss_fraction
```

Reject zero/non-positive effective loss fraction.

The risk budget is capped by current safe capacity; the engine never inflates risk to compensate for costs or prior losses.

### 5.8 Aggregate planned-open-risk capacity

```text
max_total_risk = equity * max_open_risk
existing_open_risk = sum(open.planned_risk)
remaining_open_risk = max_total_risk - existing_open_risk
```

If remaining risk is non-positive, reject. Otherwise the request risk amount is capped to the smaller of target risk and remaining risk.

### 5.9 Correlation bucket capacity

Default unclassified crypto positions use `crypto_beta`.

```text
bucket_limit_amount = equity * correlation_bucket_risk_limit
existing_bucket_risk = sum(planned_risk for same bucket)
remaining_bucket_risk = bucket_limit_amount - existing_bucket_risk
```

If non-positive, reject. Otherwise cap request risk to the remaining bucket amount.

Risk is absolute planned loss; opposite directions do not net by default.

### 5.10 Gross leverage / margin capacity

System gross-notional ceiling:

`equity * min(max_gross_leverage, venue_max_leverage)`

New-notional capacity is that ceiling minus current gross open notional.

Margin capacity is:

`available_margin * max_available_margin_fraction * min(max_gross_leverage, venue_max_leverage)`

The approved notional cannot exceed either capacity. Leverage implements exposure; it does not define the risk budget.

### 5.11 Liquidity capacity

Use:

`visible_capacity = min(entry_side_visible_notional_25bps, exit_side_visible_notional_25bps) * max_visible_depth_fraction`

Approved notional may not exceed visible capacity.

This is a conservative entry/exit liquidity proxy, not a claim that 25-bps displayed depth guarantees a fill.

### 5.12 Convert all caps to final bounded notional

Risk-capacity notional is:

`approved_risk_amount / effective_loss_fraction`.

Final candidate notional is the minimum of raw notional, risk-capacity notional, gross capacity, margin capacity, and liquidity capacity.

If the final candidate notional is non-positive, reject.

Actual planned risk at that notional is:

`approved_notional * effective_loss_fraction`.

### 5.13 Liquidation buffer

For LONG:

- liquidation price must be below stop;
- `(entry - liquidation) / (entry - stop) >= min_liquidation_stop_multiple`.

For SHORT:

- liquidation price must be above stop;
- `(liquidation - entry) / (stop - entry) >= min_liquidation_stop_multiple`.

Missing, invalid, or insufficient liquidation safety rejects.

### 5.14 Venue minimum

If `venue_min_notional` exists and final notional is below it, reject rather than force risk upward.

### 5.15 Approval

Approval records the final notional/risk and every binding cap. A binding cap means it reduced the candidate below the uncapped raw notional. Stable reason code `risk_approved` is included only on approval.

## 6. Reason codes

At minimum:

- `strategy_no_trade`
- `missing_stop`
- `invalid_stop_side`
- `invalid_entry_price`
- `stale_market_data`
- `stale_account_state`
- `execution_health_degraded`
- `risk_state_inconsistent`
- `existing_market_exposure`
- `daily_loss_lockout`
- `weekly_drawdown_lockout`
- `consecutive_loss_cooldown`
- `invalid_execution_costs`
- `aggregate_risk_exhausted`
- `correlation_bucket_exhausted`
- `gross_leverage_exhausted`
- `margin_capacity_exhausted`
- `liquidity_capacity_exhausted`
- `liquidation_buffer_insufficient`
- `below_venue_min_notional`
- `risk_approved`

Rejections use the earliest hard veto encountered. Capacity reductions are recorded as `binding_caps` instead of rejection reasons when a smaller safe trade is still possible.

## 7. New conservative V1 defaults

The following Phase 6 defaults are newly locked by this design unless later revised from evidence:

- correlation-bucket planned-risk cap: 0.50% equity;
- gross system leverage ceiling: 3x equity or lower venue max;
- new exposure may consume at most 50% of currently available margin;
- new notional may use at most 10% of the weaker visible 25-bps side depth;
- liquidation distance must be at least 2x stop distance and beyond the stop;
- three-loss cooldown duration: 60 minutes;
- unknown crypto positions default to shared `crypto_beta` correlation bucket.

These constraints optimize for capital survival and robust evidence collection. Future relaxation belongs to Phase 14 and requires measured evidence; strategy conviction cannot change them.

## 8. Boundary with Phase 7

Phase 6 output is an approval envelope, not an order.

Phase 7 may consume `approved_notional` and translate it into quantity/order behavior using the actual paper-execution market state, instrument sizing rules, and fill simulator. Phase 7 may execute less exposure than approved, but it may never increase exposure beyond the approved notional/risk envelope without a fresh risk decision.

Reduce-only exits and emergency position reductions are separate lifecycle actions and are not blocked by the new-exposure risk pathway.

## 9. Testing requirements

Use TDD and pure deterministic fixtures.

Tests must cover:

- exact cost-aware 0.25% sizing;
- score invariance: higher strategy score does not increase risk;
- wrong-side/missing stop rejection;
- zero/negative/inconsistent equity rejection;
- stale/future account, market, and liquidity timestamps;
- health-state failures;
- same-market existing-position rejection;
- daily 1% lockout boundary;
- rolling weekly 3% drawdown boundary;
- three-loss cooldown active and expiry boundary;
- aggregate 0.75% open-risk cap and partial remaining capacity;
- 0.50% correlation-bucket cap and partial capacity;
- opposite-direction correlated positions not netting planned risk;
- 3x gross-leverage capacity;
- 50% available-margin capacity;
- 10% weak-side visible-depth capacity;
- high execution-cost sizing reduction;
- liquidation beyond-stop / 2x-distance checks for LONG and SHORT;
- venue minimum notional rejection without forced upsizing;
- deterministic decision IDs and stable reason/binding-cap ordering;
- rejected decision always has zero exposure;
- public-interface boundary tests proving no order placement, wallet/account exchange API, averaging-down, martingale, or ML capability.

## 10. Exit criteria

Phase 6 is complete only when:

- the old float-based placeholder risk contract has been replaced safely;
- deterministic TDD tests cover every locked risk rule;
- strategy code cannot override risk output;
- risk approval cannot place orders;
- adverse/missing/stale state fails closed;
- sizing includes estimated entry/stop slippage and round-trip fees;
- aggregate and correlation limits are enforced;
- same-market add-on exposure is impossible through the public new-exposure interface;
- rejected decisions expose zero approved risk/notional;
- full Python 3.12 install/compile/Ruff/mypy/pytest CI passes;
- `docs/STATUS.md` and the portable Project Source contain the exact verification/merge evidence;
- live trading remains disabled.
