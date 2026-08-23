# Phase 7 Real-Mainnet Paper Execution and Position Management Design

**Status:** Approved in chat; written spec prepared for final review  
**Date:** 2026-08-23  
**Base:** `main` at `86fe6cc0edbb64b17ab0757b2b02ddc7a4e7fc81`  
**Phase 6 merge:** `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912`

## 1. Goal

Build the first autonomous execution layer that trades fake capital against real Hyperliquid mainnet observations. Phase 7 turns a Phase 6 `RiskDecision` approval into deterministic paper order attempts, realistic visible-book fills, durable position/account state, and autonomous exits without exposing any real-order, wallet, signing, transfer, withdrawal, or private-account capability.

The economic objective is honest pre-live evidence. The simulator must prefer under-crediting fills over inventing liquidity, charge explicit costs, preserve Phase 6 risk ceilings after realized entry price is known, and fail closed on stale or inconsistent execution/account state.

## 2. Scope boundary

Phase 7 may:

- replace the Phase 1 float execution placeholders with immutable Decimal contracts;
- extend the existing public mainnet WebSocket normalization with the execution-critical public `activeAssetCtx` subscription for mark/oracle/funding context;
- convert an approved Phase 6 notional envelope into a size-constrained paper order plan;
- simulate marketable IOC-style execution against actual normalized mainnet L2 snapshots;
- model configurable deterministic latency;
- support full, partial, and zero fills from displayed depth only;
- charge versioned taker fees;
- reconcile hourly funding from actual public funding records plus lookahead-safe public oracle context;
- maintain paper positions, realized/unrealized PnL, fees, funding, equity, gross notional, conservative margin reservation, daily realized PnL, weekly equity peak, and loss streak state;
- enforce reduce-only behavior;
- trigger stop exits from public mark-price observations and execute the resulting exit through the same IOC simulator;
- support deterministic position-management actions including hold, tighter stops, reductions, thesis exits, and emergency exits;
- persist operational execution/account/position state in SQLite with atomic transactions and idempotent recovery;
- expose a narrow execution interface intended to be shared by a later disabled live adapter.

Phase 7 may not:

- submit, cancel, modify, or query real Hyperliquid orders;
- import or call a private-key/wallet/signing exchange client;
- call private user/account exchange endpoints;
- expose withdrawals or transfers;
- award passive maker fills or maker rebates;
- invent hidden book depth beyond recorded L2 levels;
- infer fills from candles;
- synthesize historical order flow;
- increase Phase 6 approved risk or notional;
- pyramid, average down, martingale, or flip a position through a reduce-only exit;
- implement ML;
- enable live execution;
- implement the Phase 8 analytical journal/replay system early.

## 3. Approved architecture

Use an evidence-grounded IOC paper adapter with pure execution/accounting kernels behind a durable SQLite state store.

```text
mainnet public market data
  +-> L2_BOOK -----------------------------+
  +-> ACTIVE_ASSET_CTX (mark/oracle/rate) -+----+
  +-> public funding history -------------------+----+
                                                    |
Phase 5 StrategyDecision                             |
        |                                           |
        v                                           |
Phase 6 RiskDecision APPROVE                         |
        |                                           |
        v                                           |
PaperOrderPlan                                      |
        |                                           |
        +--> instrument precision/minimum checks    |
        +--> deterministic latency eligibility      |
        |                                           |
        v                                           |
actual normalized mainnet L2 snapshot <-------------+
        |
        v
visible-book IOC walk
        |
        +--> FULL / PARTIAL / ZERO fill
        |
        v
Phase 6 envelope recheck using actual average entry
        |
        v
atomic fills + position + paper account update
        |
        v
position manager <---- mark/strategy/health/funding context
        |
        +--> HOLD
        +--> TIGHTEN_STOP
        +--> REDUCE
        +--> EXIT_THESIS
        +--> EXIT_STOP
        +--> EXIT_EMERGENCY
        |
        +------> reduce-only IOC path
```

The pure kernels contain no wall-clock reads, random numbers, network calls, or mutable global state. The stateful layer coordinates durable SQLite transactions, public market-data inputs, and deterministic event ordering.

## 4. Initial venue scope

Paper execution is enabled initially only for the validator-operated native Hyperliquid perp DEX (`MarketId.dex == ""`). Dynamic discovery and the rest of the pipeline remain multi-DEX capable.

HIP-3/perp-DEX markets remain observable and rankable, but Phase 7 returns an explicit unsupported-execution result for them until fee, margin, symbol, and execution semantics are separately validated and promoted. This avoids treating different deployer/margin semantics as identical merely because discovery is shared.

Hyperliquid testnet remains forbidden.

## 5. Current Hyperliquid behavior treated as external input

The implementation must re-check current official Hyperliquid documentation before encoding exchange-facing rules that can change.

As of this design review:

- perp metadata exposes `szDecimals`, which defines base-size precision;
- IOC fills immediately against crossing liquidity and cancels the unfilled remainder;
- reduce-only orders may only reduce an existing position and may not increase or flip it;
- native perp orders are subject to a documented minimum trade notional currently represented by a $10 baseline rejection threshold;
- fee rates are tier/account dependent rather than one universal permanent constant;
- perpetual funding is settled on an hourly cadence using position size, oracle price, and funding rate;
- stop/TP triggering is based on mark-price behavior rather than guaranteeing execution at the trigger price;
- the official Python SDK currently lists the public `activeAssetCtx` subscription and its perp payload includes `funding`, `openInterest`, `oraclePx`, `markPx`, and `midPx`.

The paper simulator records versioned assumptions instead of presenting mutable venue policy as timeless truth.

Official references:

- `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding`
- `https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/master/hyperliquid/utils/types.py`

## 6. Public execution-context stream

Phase 7 adds a public-only normalized stream kind for `activeAssetCtx` rather than polling private account state.

Normalized `ACTIVE_ASSET_CTX` payload:

- market;
- mark price;
- optional mid price;
- oracle price;
- funding rate;
- open interest;
- receive timestamp;
- exchange timestamp only if the upstream message actually supplies one;
- source/event key/schema version.

The normalizer must not invent an exchange timestamp when the upstream message omits one. Receive time is the evidence clock in that case.

This stream is used for:

- stop triggering from mark price;
- unrealized mark-to-market;
- current oracle context;
- funding-rate context and hourly funding reconciliation support;
- execution-health freshness for open positions.

It remains a public market-data subscription. No user address, wallet, account, signing, or private endpoint is involved.

## 7. Domain contracts

All financial, price, fee, quantity, PnL, funding, notional, and ratio fields use `Decimal`. Mutable lists/dicts are not stored in domain contracts. IDs are deterministic hashes of canonical normalized values, consistent with Phase 4-6 patterns.

### 7.1 `PaperExecutionConfig`

Immutable versioned execution assumptions:

- `config_version`;
- `latency_ms`;
- `max_book_age_ms`;
- `max_asset_ctx_age_ms`;
- `funding_reconciliation_grace_ms`;
- `max_ioc_slippage_bps`;
- `taker_fee_rate`;
- `fee_schedule_id`;
- `native_perp_min_notional`;
- `paper_max_gross_leverage`.

Initial V1 defaults:

- deterministic latency: `250 ms`;
- maximum accepted L2 age: `1_000 ms`;
- maximum accepted asset-context age: `5_000 ms`;
- funding reconciliation grace after an hourly boundary: `300_000 ms`;
- IOC slippage guard: `25 bps` from execution reference price;
- native perp base-tier taker-fee assumption: `Decimal("0.00045")`, stored with a dated/versioned fee-schedule ID and overrideable from config;
- native perp minimum order notional assumption: `Decimal("10")`, versioned and overrideable;
- paper gross leverage ceiling: `3x`, matching Phase 6 unless market metadata is lower.

These are simulation/control assumptions, not claims of optimality. Phase 9 tests sensitivity.

### 7.2 `InstrumentExecutionSpec`

Immutable per-market execution metadata derived from `PerpMarketMeta` plus versioned venue policy:

- market;
- `sz_decimals`;
- venue max leverage;
- minimum order notional;
- execution-support flag/reason;
- metadata receive timestamp/provenance.

The size quantum is `Decimal(1).scaleb(-sz_decimals)`. Every requested opening or reduction size is rounded toward zero/down to this quantum. The simulator never rounds size upward to satisfy minimum notional.

### 7.3 `PaperOrderPlan`

Represents one approved execution request, not a fill:

- deterministic `plan_id`;
- originating `risk_decision_id`;
- originating `strategy_decision_id`;
- market;
- side;
- requested quantity;
- `reduce_only`;
- execution style fixed to `MARKETABLE_IOC` in V1;
- execution reference price;
- maximum slippage bps;
- stop/invalidation reference when opening;
- Phase 6 stop-distance fraction;
- Phase 6 effective-loss fraction;
- created timestamp;
- earliest execution timestamp = created timestamp + configured latency;
- instrument/config version references.

Opening plans may be created only from `RiskDecision(approved=True)`. Rejected/no-trade risk decisions cannot produce an opening plan.

The Phase 6 cost buffer carried into execution is exactly:

`cost_buffer_fraction = effective_loss_fraction - stop_distance_fraction`.

It must be finite and non-negative.

### 7.4 `ExecutionAttempt`

Immutable result of trying one plan against one eligible L2 snapshot:

- deterministic attempt ID;
- plan ID;
- selected L2 event key;
- snapshot exchange/receive timestamps;
- requested quantity;
- filled quantity;
- average fill price if any;
- gross fill notional;
- fee;
- unfilled quantity;
- result status (`FULL`, `PARTIAL`, `NO_FILL`, `REJECTED`);
- stable reason codes;
- attempt timestamp.

A zero-fill IOC is a valid execution result, not an exception.

### 7.5 `PaperFill`

One immutable fill allocation produced by walking a recorded L2 level:

- deterministic fill ID;
- plan/attempt IDs;
- market;
- side;
- price;
- quantity;
- notional;
- taker fee;
- source L2 event key;
- timestamp.

Multiple level fills may belong to one IOC attempt. No fill can reference an unrecorded price/quantity source.

### 7.6 `PaperPosition`

At most one open position per market:

- market;
- direction;
- signed quantity;
- average entry price;
- initial stop;
- current stop;
- initial risk amount;
- initial risk decision ID;
- correlation bucket;
- cumulative realized trading PnL;
- cumulative fees;
- cumulative funding PnL;
- opened timestamp;
- last update timestamp;
- latest mark;
- maximum favorable/adverse mark references;
- optional validated liquidation-reference price;
- status.

The current stop may only move in the risk-reducing direction: upward for LONG, downward for SHORT. It may never be removed while the position is open.

### 7.7 `PaperAccountState`

Operational account truth required by subsequent risk decisions:

- initial equity;
- cash balance after realized PnL, fees, and funding;
- unrealized PnL from current mark observations;
- total equity;
- gross open notional;
- conservative reserved margin;
- available margin;
- net daily realized PnL;
- rolling seven-day peak equity;
- consecutive closed-trade losses;
- last closed trade timestamp;
- state timestamp/version.

`equity = cash_balance + unrealized_pnl`.

Cash balance includes realized trading PnL, all execution fees, and booked funding cash flows. `daily_realized_pnl` supplied to Phase 6 is the same-day net cash result from realized trading PnL + fees + funding, excluding unrealized mark movement.

Available margin is a conservative paper-control estimate, not a claim to reproduce Hyperliquid's complete cross-margin engine. For each position, reserve at least:

`abs(mark_notional) / min(paper_max_gross_leverage, venue_max_leverage)`.

Available margin is `max(0, equity - total_reserved_margin)`.

Phase 7 exposes a pure adapter from `PaperAccountState`/open positions to Phase 6 `RiskAccountState`/`OpenPositionRisk`.

### 7.8 Closed-trade loss streak

Update the consecutive-loss counter only when a position becomes fully closed.

- net closed-trade result `< 0`: increment by one;
- net closed-trade result `>= 0`: reset to zero;
- partial reductions do not alter the streak.

Net closed-trade result includes realized price PnL, all position-attributed entry/exit fees, and all position funding cash flows.

### 7.9 Rolling seven-day peak

Weekly drawdown must use the highest observed paper equity in the preceding rolling seven calendar days, including unrealized mark-to-market equity while positions are open.

Maintain an exact timestamped monotonic rolling-maximum candidate queue:

1. on every account equity update, remove candidate peaks from the tail while their equity is `<=` the new equity;
2. append the new `(timestamp_ms, equity)` candidate;
3. remove candidates from the head once older than seven days;
4. the head is the current rolling seven-day peak.

Persist the candidate queue so restart recovery cannot silently reset the drawdown baseline.

### 7.10 `PositionAction`

Immutable manager output:

- action type: `HOLD`, `TIGHTEN_STOP`, `REDUCE`, `EXIT_THESIS`, `EXIT_STOP`, `EXIT_EMERGENCY`;
- market;
- quantity/fraction for reductions where applicable;
- new stop for tightening where applicable;
- reason codes;
- timestamp;
- source decision/health references where applicable.

Only `REDUCE` and exit actions can produce a plan for an already-open position, and every such plan is `reduce_only=True`.

## 8. Order planning from Phase 6 approval

For a new directional position:

1. require an approved Phase 6 decision;
2. require native-perp execution support and fresh metadata;
3. choose execution reference price from current trustworthy market state;
4. calculate `raw_quantity = approved_notional / execution_reference_price` under the fixed authoritative Decimal context;
5. round quantity downward to `szDecimals`;
6. reject if rounded quantity is zero;
7. reject if reference notional is below the versioned venue minimum;
8. carry the exact Phase 6 stop/effective-loss fields into the plan;
9. create an IOC plan whose target notional never exceeds `approved_notional`.

The opening side is BUY for LONG and SELL for SHORT.

The paper planner never increases quantity because rounding or minimum notional would otherwise reject the trade.

## 9. Deterministic latency and snapshot eligibility

The paper plan becomes executable at:

`eligible_ms = plan.created_at_ms + config.latency_ms`.

For event-driven simulation, use the first valid normalized L2 snapshot for the same market received at or after `eligible_ms`. The execution attempt timestamp is that snapshot's receive time; the simulator does not pretend the order filled earlier than the evidence it used.

The selected snapshot must:

- come from `StreamKind.L2_BOOK`;
- match the exact market;
- have a valid event key/provenance;
- have no future/inconsistent exchange timestamp relative to receive time;
- be no older than `max_book_age_ms` by exchange-vs-receive age when exchange time is available;
- contain non-crossed positive-price/positive-size levels;
- arrive after plan creation and latency cutoff.

If no eligible snapshot exists, execution remains pending rather than fabricating a fill. If the stream becomes explicitly stale/unhealthy, the attempt rejects/fails closed.

## 10. L2-aware IOC fill model

### 10.1 Book normalization

Never rely on input ordering:

- BUY walks asks sorted ascending by price;
- SELL walks bids sorted descending by price.

Ignore zero-size levels and reject malformed/negative/non-finite values.

### 10.2 Slippage guard

The maximum executable price is deterministic:

- BUY: `reference_price * (1 + max_ioc_slippage_bps / 10_000)`;
- SELL: `reference_price * (1 - max_ioc_slippage_bps / 10_000)`.

Only recorded displayed depth at prices inside that bound is eligible.

The initial 25-bps guard aligns execution with the Phase 6 visible-depth risk cap. It is versioned, not assumed optimal.

### 10.3 Walking depth

At each eligible level, fill the smaller of remaining quantity and displayed level size. Stop when:

- requested quantity is fully filled;
- the next level violates the slippage bound;
- recorded displayed depth ends.

The unfilled remainder is cancelled. The simulator does not extrapolate hidden liquidity beyond the recorded snapshot and does not wait for later passive fills.

### 10.4 Phase 6 envelope recheck

Actual entry price changes stop distance, so the executor rechecks the original risk envelope without double-counting the original cost assumptions.

For the cumulative filled quantity at cumulative average entry price:

`actual_stop_distance_fraction = abs(actual_average_entry - approved_stop) / actual_average_entry`

`actual_effective_loss_fraction = actual_stop_distance_fraction + cost_buffer_fraction`

`actual_planned_loss = cumulative_fill_notional * actual_effective_loss_fraction`

The accepted cumulative fill must satisfy both:

- `cumulative_fill_notional <= RiskDecision.approved_notional`;
- `actual_planned_loss <= RiskDecision.approved_risk_amount`.

The cost buffer is inherited exactly from Phase 6; Phase 7 does not add a second entry-slippage/fee allowance on top of it. Actual taker fees are still charged separately to the paper cash ledger for realized accounting.

If an entire next L2 level would cross either ceiling, reduce that final level allocation to the largest size that remains under both ceilings, rounded down to `szDecimals`. If the safe remainder rounds to zero, stop filling.

Phase 7 may execute less than Phase 6 approved. It may never execute more without a fresh risk decision.

## 11. Fees

V1 IOC fills are taker fills only.

For each fill:

`fee = abs(price * quantity) * taker_fee_rate`.

Fee rates come from `PaperExecutionConfig` and are persisted with `fee_schedule_id`. The initial native-perp baseline is 4.5 bps (`0.045%`) because that is the current base-tier assumption, but the architecture treats this as mutable venue/account policy.

No passive maker fill, maker rebate, staking discount, referral discount, builder fee, or VIP discount is awarded unless a later version has explicit evidence/configuration for it.

The implementation must assert that Phase 6's configured round-trip cost buffer is not less conservative than the execution fee model it is paired with. If cost-model versions are inconsistent, block new execution rather than silently exceeding the approved risk envelope.

## 12. Funding accounting

Funding is reconciled from actual public evidence, not estimated from candles.

For each UTC hourly funding boundary crossed by an open position:

1. retain the latest fresh `ACTIVE_ASSET_CTX` oracle observation received at or before the boundary;
2. after the boundary, obtain/consume the actual public funding-history record for that exact market/time when it becomes available;
3. pair the actual rate with the pre-boundary oracle context;
4. book exactly one funding event by deterministic market+funding-time ID.

Funding cash delta:

`cash_delta = -(signed_quantity * oracle_price * funding_rate)`.

Positive funding charges longs and credits shorts; negative funding does the reverse.

Requirements:

- position must have been open across the funding timestamp;
- funding record market/time must match exactly;
- oracle context must be finite, valid, and received no later than the funding boundary;
- each funding event applies once only;
- do not interpolate missing funding records or oracle context;
- an unreconciled funding boundary is recorded as a data-quality gap;
- after `funding_reconciliation_grace_ms`, an unresolved gap marks account state inconsistent and blocks **new exposure** until resolved, while existing-position stop/emergency management continues;
- Phase 8 replay must be able to reconstruct each accrual from source references.

## 13. Position accounting

### 13.1 Opening

A first fill opens a position at weighted-average fill price. Fees are immediately debited from cash. Initial/current stop comes from the approved Phase 6 invalidation.

A partial IOC opening creates a position only for actually filled size. The cancelled remainder disappears; it does not remain a working passive order.

### 13.2 Reducing/closing

Reduce-only fills realize PnL against average entry:

- LONG reduction: `(exit_price - average_entry_price) * quantity`;
- SHORT reduction: `(average_entry_price - exit_price) * quantity`.

Exit fees are debited separately.

A reduction cannot exceed current absolute quantity. If rounding leaves zero quantity, reject. A full close sets open quantity to zero, computes net closed-trade result including attributed fees/funding, updates daily realized PnL and consecutive-loss state, and removes the position from the active set.

### 13.3 Unrealized PnL

Mark-to-market uses fresh `ACTIVE_ASSET_CTX.markPx` only. Missing/stale mark data blocks new exposure and marks execution/account health degraded; it does not substitute mid/oracle silently.

For current signed quantity `q`, average entry `e`, and mark `m`:

`unrealized_pnl = q * (m - e)`.

This naturally yields correct sign for longs and shorts.

## 14. Position manager policy

The initial manager is intentionally conservative and avoids embedding an unvalidated take-profit rule merely to produce activity.

Rule precedence:

1. emergency health/risk-state exit;
2. hard stop trigger;
3. opposing directional thesis exit;
4. tighter same-direction invalidation update;
5. explicit validated reduction directive;
6. hold.

### 14.1 Emergency exit

If an open position exists and execution/market/account state is critically inconsistent, the manager prioritizes reducing/closing existing exposure over finding new trades. The exit still requires usable L2 evidence; if none exists, state remains `emergency_exit_pending` and new exposure stays blocked.

### 14.2 Stop trigger

Stops trigger from fresh `ACTIVE_ASSET_CTX.markPx`:

- LONG triggers when mark `<= current_stop`;
- SHORT triggers when mark `>= current_stop`.

Triggering does not award a fill at the stop. It creates a reduce-only marketable IOC exit subject to latency, visible depth, slippage, and fees. Realized loss may therefore exceed planned loss.

### 14.3 Thesis exit

A fresh Phase 5 directional decision opposite the current position direction triggers `EXIT_THESIS`. A `NO_TRADE` result by itself does **not** close an existing position; entry selectivity and exit invalidation are distinct semantics.

### 14.4 Stop tightening / trailing primitive

If a fresh same-direction Phase 5 decision supplies an invalidation strictly more protective than the current stop, update the stop to that tighter level. Never loosen a stop.

This is the initial trailing mechanism: evidence can ratchet invalidation favorably, but Phase 7 does not invent an arbitrary 1R/2R profit-taking rule. More aggressive trailing/take-profit policy belongs to later evidence-based evaluation.

### 14.5 Partial reductions

The execution/accounting layer supports deterministic reduce-only partial exits as a first-class primitive. Phase 7 does not create a profit target from thin air. A reduction directive must come from an explicit manager/risk-control rule, specify fraction/quantity, round down safely, and never flip the position.

## 15. Paper margin and liquidation-distance monitoring

Phase 7 provides enough conservative account state for Phase 6 without pretending to reproduce the full Hyperliquid clearinghouse.

For each open position:

- calculate current gross mark notional;
- reserve conservative margin using the smaller of the Phase 7 3x system cap and venue max leverage;
- available margin is equity minus total reserved margin, floored at zero;
- expose gross open notional and available margin to Phase 6 through a pure adapter.

Liquidation monitoring uses the validated liquidation-reference/buffer state supplied alongside the risk/execution request when available. Phase 7 does not invent undocumented liquidation formulas. A missing/invalid required liquidation reference degrades risk health and blocks new exposure; an observed reference breach triggers emergency reduction behavior.

## 16. SQLite operational state

Use Python stdlib `sqlite3`; do not add a database dependency merely for Phase 7.

Minimal durable tables:

- `paper_meta` — schema/config/account identity/version;
- `paper_order_plans` — deterministic plans;
- `paper_execution_attempts` — IOC attempts;
- `paper_fills` — per-level fills;
- `paper_positions` — current materialized open-position state;
- `paper_position_events` — position mutations/reductions/stop changes;
- `paper_funding_events` — idempotent funding accruals/gaps;
- `paper_account_state` — current materialized account control state;
- `paper_equity_peak_candidates` — persisted rolling-seven-day monotonic peak queue.

High-volume market events are not duplicated into SQLite; rows reference Phase 3/7 normalized event keys/provenance.

Critical execution updates are transactional. A successful fill transaction writes attempt/fills plus resulting position/account/peak-state changes atomically. If any critical write fails, rollback and fail closed. Never acknowledge a state-changing paper fill in memory if the durable transaction failed.

## 17. Idempotency and restart recovery

Deterministic IDs and database uniqueness constraints make retry safe.

Rules:

- the same opening `risk_decision_id` cannot create two active opening plans;
- a plan/attempt/fill/funding ID is applied at most once;
- duplicate L2/asset-context/funding delivery cannot duplicate account mutations;
- on startup, load persisted account, rolling-peak candidates, and open positions before accepting new exposure;
- reconstruct/check position quantity and realized PnL from persisted fills/events against materialized rows;
- validate account totals against position/fill/funding aggregates under exact Decimal/tolerance rules defined in tests;
- any mismatch marks state inconsistent and blocks new exposure until reconciliation succeeds;
- open positions are reconciled/managed before scanner-generated new entries resume.

Because this is paper-only, recovery never queries a private exchange account. Phase 12 adds real-account reconciliation behind the separate live adapter.

## 18. Narrow execution interface

Define a small protocol/ABC representing trading actions, not venue-specific private capabilities.

Required conceptual methods:

- create/submit a marketable IOC execution plan;
- process eligible public market observations for pending plans;
- request a reduce-only reduction/close;
- read adapter-local execution/position health needed by the engine.

The interface must not expose:

- withdrawals;
- transfers;
- wallet management;
- arbitrary signing;
- raw private-key access;
- generic exchange-client escape hatches.

The paper adapter implements this interface in Phase 7. The eventual mainnet live adapter in Phase 12 implements the same narrow semantics without changing strategy or risk code.

## 19. End-to-end control flow

The unattended paper loop is:

1. mainnet scanner/shortlist produces eligible deep-ready candidate;
2. Phase 5 produces LONG/SHORT/NO_TRADE;
3. Phase 6 evaluates current paper account/open-risk/execution health;
4. only `approved=True` creates an opening paper plan;
5. plan waits until latency cutoff and eligible real L2 evidence;
6. IOC simulator walks visible depth, rechecks risk envelope, and charges costs;
7. successful filled portion creates/updates one paper position atomically;
8. manager continuously consumes fresh `ACTIVE_ASSET_CTX`, strategy, health, and funding-reconciliation state;
9. stop/thesis/emergency/reduction actions use reduce-only IOC execution;
10. account/risk state updates after every fill, funding, or mark event;
11. after full close, net closed result updates daily PnL and consecutive-loss state used by Phase 6.

`NO_TRADE`, rejected risk, pending execution, no-fill IOC, partial fill, unresolved funding gap, and emergency-exit-pending are normal first-class outcomes.

## 20. Failure behavior

Fail closed on:

- unsupported perp DEX execution;
- missing/stale/inconsistent L2 evidence;
- stale/malformed `ACTIVE_ASSET_CTX` when required;
- crossed/malformed books;
- future/inconsistent event timestamps;
- zero size after precision rounding;
- below-minimum order notional;
- attempted opening from rejected risk;
- attempted notional/risk above Phase 6 envelope;
- inconsistent Phase 6/execution cost-model versions;
- reduce-only action without a matching position;
- reduce-only quantity larger than the position;
- stop removal/loosening;
- duplicate state mutation;
- SQLite transaction/write failure;
- account/position/rolling-peak recovery mismatch;
- unresolved funding gap beyond grace;
- missing/stale mark state required for accounting/stop evaluation;
- critical execution-health degradation.

A failure in new-entry execution never prevents the manager from attempting a risk-reducing exit when usable public market data is available.

## 21. Testing requirements

Use TDD and deterministic fixtures, including actual normalized Phase 3 mainnet L2 shapes and a frozen public `activeAssetCtx` mainnet fixture captured without user/private data.

Tests must cover at minimum:

### Public asset context

- subscription/normalization is public-only;
- mark/oracle/funding/OI parse as Decimal;
- missing upstream exchange timestamp remains `None` rather than being invented;
- duplicate/stale/future-inconsistent context is handled deterministically.

### Contracts and precision

- all execution/accounting financial values are Decimal;
- exact `szDecimals` round-down behavior;
- zero quantity after rounding rejects;
- minimum notional rejects without upsizing;
- deterministic IDs and stable reason codes;
- ambient Decimal context cannot change results.

### IOC execution

- BUY walks asks low-to-high independent of fixture ordering;
- SELL walks bids high-to-low independent of fixture ordering;
- full fill;
- partial fill;
- zero fill;
- unfilled IOC remainder cancels and never fills later passively;
- visible depth beyond slippage bound is ignored;
- no hidden depth is invented;
- latency uses only eligible post-cutoff evidence;
- stale/future/crossed books fail closed;
- duplicate snapshot processing does not duplicate fills.

### Risk-envelope preservation

- filled notional never exceeds `approved_notional`;
- actual stop-distance plus inherited Phase 6 cost buffer never exceeds `approved_risk_amount`;
- execution cost assumptions are not double-counted;
- a final L2 level is clipped/rounded down when needed;
- execution can use less risk than approved but never more;
- incompatible risk/execution fee-cost versions fail closed.

### Fees and funding

- taker fee charged on every IOC fill;
- no maker rebate/passive fee path;
- funding sign correct for long/short and positive/negative rates;
- pre-boundary oracle context is lookahead-safe;
- actual public funding-history time/rate matches the accrual;
- one funding event applies once only;
- unresolved funding gap is surfaced and eventually blocks new exposure rather than interpolating.

### Position/accounting

- partial entry weighted-average price;
- long/short realized PnL formulas;
- partial reduction preserves remaining position;
- reduce-only cannot flip position;
- close updates net realized PnL/fees/funding/equity;
- daily realized PnL is net of same-day realized trading PnL, fees, and funding;
- loss streak increments only on fully closed net losers and resets on fully closed non-losers;
- unrealized mark-to-market correct from fresh mark;
- rolling seven-day monotonic peak queue remains exact across updates/expiry/restart;
- gross notional/margin/available-margin adapter feeds Phase 6 consistently;
- daily/weekly state remains compatible with Phase 6 vetoes.

### Position management

- emergency exit precedence;
- long/short mark stop trigger;
- stop trigger fills at actual book prices, not stop price;
- opposite fresh strategy decision exits;
- `NO_TRADE` alone holds;
- same-direction tighter invalidation tightens stop;
- stop can never loosen;
- partial reduction primitive is reduce-only/idempotent.

### Persistence and recovery

- fill + position + account + rolling-peak write is atomic;
- injected DB failure rolls back all state;
- restart loads identical state;
- duplicate plan/fill/funding IDs are idempotent;
- materialized-state mismatch fails closed;
- failure injection cannot create duplicate positions.

### Boundary tests

- execution package contains no wallet/private-key/signing/withdraw/transfer capability;
- no real exchange order submission exists;
- no private user/account WebSocket subscription is introduced;
- no testnet URL/config path is introduced;
- no ML dependency;
- no candle-to-L2 fill fabrication;
- paper/live execution share a narrow abstraction rather than strategy-specific calls.

### End-to-end

A deterministic integration test covers:

`scanner-ready fixture -> Phase 5 directional decision -> Phase 6 approval -> paper IOC entry -> paper position -> mark/strategy/stop management -> reduce-only IOC exit -> reconciled closed paper account`.

It also proves the equivalent rejection/no-fill path does not create a position.

## 22. Exit criteria

Phase 7 is complete only when:

- the float execution placeholders are replaced safely with Decimal contracts;
- public `ACTIVE_ASSET_CTX` mark/oracle/funding context is normalized without private account data;
- paper execution is grounded in real normalized mainnet L2 evidence;
- latency, slippage, fees, funding, minimum notional, size precision, partial fills, and stop execution are modeled explicitly;
- unsupported passive maker fills are impossible;
- Phase 6 risk/notional envelopes cannot be exceeded or double-counted by execution;
- one-position-per-market/reduce-only semantics prevent duplicate or flipped positions;
- paper account/equity/PnL/margin/daily-loss/weekly-peak state deterministically feeds Phase 6;
- stop, thesis, tighter-stop, reduction, and emergency position-management mechanics work;
- restart/recovery is idempotent and fails closed on inconsistency;
- SQLite critical state changes are atomic;
- deterministic end-to-end paper lifecycle works unattended in tests;
- full Python 3.12 install/compile/Ruff/mypy/pytest CI passes;
- `docs/STATUS.md` and `docs/CHATGPT_PROJECT_SOURCE.md` record final verification/merge evidence;
- live trading remains disabled;
- no real-order, wallet/signing, transfer, withdrawal, private user-subscription, or private exchange-account capability exists in Phase 7.

## 23. Deferred work

Explicitly deferred:

- rich analytical trade journal, MFE/MAE, replay manifests, and full deterministic backtester — Phase 8;
- evidence-based tuning of latency/slippage/exit assumptions — Phase 9;
- ML/champion-challenger — Phase 10;
- long-running service/shadow proving — Phase 11;
- real Hyperliquid order/cancel/account reconciliation adapter — Phase 12;
- real capital activation — Phase 13 and explicit user authorization only.

The Phase 7 simulator is an honest operational proving ground, not a claim that every exchange micro-detail has already been modeled perfectly.
