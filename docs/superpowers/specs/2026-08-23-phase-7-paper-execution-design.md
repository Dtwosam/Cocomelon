# Phase 7 Real-Mainnet Paper Execution and Position Management Design

**Status:** Approved in chat; written spec prepared for final review  
**Date:** 2026-08-23  
**Base:** `main` at `86fe6cc0edbb64b17ab0757b2b02ddc7a4e7fc81`  
**Phase 6 merge:** `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912`

## 1. Goal

Build the first autonomous execution layer that trades fake capital against real Hyperliquid mainnet observations. Phase 7 turns a Phase 6 `RiskDecision` approval into deterministic paper order attempts, realistic visible-book fills, durable position/account state, and autonomous exits without exposing any real-order, wallet, signing, transfer, or withdrawal capability.

The economic objective is honest pre-live evidence. The simulator must prefer under-crediting fills over inventing liquidity, must charge explicit costs, must preserve risk ceilings after realized entry price is known, and must fail closed on stale/inconsistent execution state.

## 2. Scope boundary

Phase 7 may:

- replace the Phase 1 float execution placeholders with immutable Decimal contracts;
- convert an approved Phase 6 notional envelope into a size-constrained paper order plan;
- simulate marketable IOC-style execution against actual normalized mainnet L2 snapshots;
- model configurable deterministic latency;
- support full, partial, and zero fills from displayed depth only;
- charge versioned taker fees;
- accrue actual timestamped public funding observations;
- maintain paper positions, realized/unrealized PnL, fees, funding, equity, gross notional, and conservative margin reservation;
- enforce reduce-only behavior;
- trigger stop exits from mark-price observations and execute the resulting exit through the same IOC simulator;
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
Phase 5 StrategyDecision
        |
        v
Phase 6 RiskDecision APPROVE
        |
        v
PaperOrderPlan
        |
        +--> instrument precision/minimum checks
        +--> deterministic latency eligibility
        |
        v
actual normalized mainnet L2 snapshot
        |
        v
visible-book IOC walk
        |
        +--> FULL / PARTIAL / ZERO fill
        |
        v
risk-envelope recheck using actual average entry
        |
        v
atomic fills + position + paper account update
        |
        v
position manager
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

The pure kernels contain no wall-clock reads, random numbers, network calls, or mutable global state. The stateful layer only coordinates durable SQLite transactions and event ordering.

## 4. Initial venue scope

Paper execution is enabled initially only for the validator-operated native Hyperliquid perp DEX (`MarketId.dex == ""`). Dynamic discovery and the rest of the pipeline remain multi-DEX capable.

HIP-3/perp-DEX markets remain observable and rankable, but Phase 7 must return an explicit unsupported-execution result for them until fee, margin, symbol, and execution semantics are separately validated and promoted. This avoids treating different deployer/margin semantics as identical merely because discovery is shared.

Hyperliquid testnet remains forbidden.

## 5. Current Hyperliquid behavior treated as external input

The implementation must re-check current official Hyperliquid documentation before encoding exchange-facing rules that can change.

As of this design review:

- perp metadata exposes `szDecimals`, which defines base-size precision;
- IOC means fill immediately against available crossing liquidity and cancel the unfilled remainder;
- reduce-only orders may only reduce an existing position and may not increase or flip it;
- native perp orders are subject to a documented minimum trade notional currently represented by a $10 baseline rejection threshold;
- price serialization has venue precision constraints separate from size precision;
- fee rates are tier/account dependent rather than one universal permanent constant;
- perpetual funding is paid on a recurring hourly schedule using position size, oracle price, and funding rate;
- Hyperliquid TP/SL triggering uses mark-price behavior rather than guaranteeing execution at the trigger price.

The paper simulator must record versioned assumptions instead of presenting mutable venue policy as timeless truth.

Official references:

- `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees`
- `https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding`

## 6. Domain contracts

All financial, price, fee, quantity, PnL, funding, notional, and ratio fields use `Decimal`. Mutable lists/dicts are not stored in domain contracts. IDs are deterministic hashes of canonical normalized values, consistent with Phase 4-6 domain patterns.

### 6.1 `PaperExecutionConfig`

Immutable versioned execution assumptions:

- `config_version`;
- `latency_ms`;
- `max_book_age_ms`;
- `max_ioc_slippage_bps`;
- `taker_fee_rate`;
- `fee_schedule_id`;
- `native_perp_min_notional`;
- `paper_max_gross_leverage`.

Initial V1 defaults:

- deterministic latency: `250 ms`;
- maximum accepted L2 age at simulated execution: `1_000 ms`;
- marketable IOC slippage guard: `25 bps` from the execution reference price;
- native perp base-tier taker-fee assumption: `Decimal("0.00045")`, stored with a dated/versioned fee-schedule ID and overrideable from config;
- native perp minimum order notional assumption: `Decimal("10")`, versioned and overrideable;
- paper gross leverage ceiling: `3x`, matching the Phase 6 system ceiling unless the market metadata is lower.

These are simulation assumptions, not claims of optimality. Phase 9 will test sensitivity.

### 6.2 `InstrumentExecutionSpec`

Immutable per-market execution metadata derived from `PerpMarketMeta` plus versioned venue policy:

- market;
- `sz_decimals`;
- venue max leverage;
- minimum order notional;
- execution-support flag/reason;
- metadata receive timestamp/provenance.

The size quantum is `Decimal(1).scaleb(-sz_decimals)`. Every requested opening or reduction size is rounded toward zero/down to this quantum. The simulator never rounds size upward to satisfy minimum notional.

### 6.3 `PaperOrderPlan`

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
- created timestamp;
- earliest execution timestamp = created timestamp + configured latency;
- instrument/config version references.

Opening plans may be created only from `RiskDecision(approved=True)`. Rejected/no-trade risk decisions cannot produce an opening plan.

### 6.4 `ExecutionAttempt`

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

### 6.5 `PaperFill`

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

### 6.6 `PaperPosition`

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
- cumulative realized PnL;
- cumulative fees;
- cumulative funding PnL;
- opened timestamp;
- last update timestamp;
- maximum favorable/adverse mark references needed for later position management;
- status.

The current stop may only move in the risk-reducing direction: upward for LONG, downward for SHORT. It may never be removed while the position is open.

### 6.7 `PaperAccountState`

Operational account truth required by subsequent risk decisions:

- initial equity;
- cash/equity base after realized PnL, fees, and funding;
- unrealized PnL from current mark observations;
- total equity;
- gross open notional;
- conservative reserved margin;
- available margin;
- daily realized PnL;
- rolling seven-day peak equity;
- consecutive closed-trade losses;
- last closed trade timestamp;
- state timestamp/version.

`equity = cash_balance + unrealized_pnl` where cash balance incorporates realized trading PnL, funding cash flows, and fees.

Available margin is a conservative paper-control estimate, not a claim to reproduce Hyperliquid's complete cross-margin engine. For each position, reserve at least `abs(mark_notional) / min(paper_max_gross_leverage, venue_max_leverage)`. Available margin is max(0, equity - total reserved margin). The exact formula and its version are persisted so Phase 9 sensitivity work can identify model dependence.

Phase 7 exposes a pure adapter from `PaperAccountState`/open positions to the Phase 6 `RiskAccountState`/`OpenPositionRisk` contracts.

### 6.8 `PositionAction`

Immutable manager output:

- action type: `HOLD`, `TIGHTEN_STOP`, `REDUCE`, `EXIT_THESIS`, `EXIT_STOP`, `EXIT_EMERGENCY`;
- market;
- quantity/fraction for reductions where applicable;
- new stop for tightening where applicable;
- reason codes;
- timestamp;
- source decision/health references where applicable.

Only `REDUCE` and exit actions can produce an execution plan for an already-open position, and every such plan is `reduce_only=True`.

## 7. Order planning from Phase 6 approval

For a new directional position:

1. require an approved Phase 6 decision;
2. require native-perp execution support and fresh metadata;
3. choose execution reference price from current trustworthy market state;
4. calculate `raw_quantity = approved_notional / execution_reference_price` under the fixed authoritative Decimal context;
5. round quantity downward to `szDecimals`;
6. reject if rounded quantity is zero;
7. reject if reference notional is below the versioned venue minimum;
8. create an IOC plan whose target notional never exceeds `approved_notional`.

The opening side is BUY for LONG and SELL for SHORT.

The paper planner never increases quantity because rounding or minimum notional would otherwise reject the trade.

## 8. Deterministic latency and snapshot eligibility

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

## 9. L2-aware IOC fill model

### 9.1 Book normalization

Never rely on input ordering:

- BUY walks asks sorted ascending by price;
- SELL walks bids sorted descending by price.

Ignore zero-size levels and reject malformed/negative/non-finite values.

### 9.2 Slippage guard

The maximum executable price is deterministic:

- BUY: `reference_price * (1 + max_ioc_slippage_bps / 10_000)`;
- SELL: `reference_price * (1 - max_ioc_slippage_bps / 10_000)`.

Only recorded displayed depth at prices inside that bound is eligible.

The 25-bps initial guard aligns execution with the Phase 6 visible-depth risk cap. It is a versioned assumption, not proof that 25 bps is universally optimal.

### 9.3 Walking depth

At each eligible level, fill the smaller of remaining quantity and displayed level size. Stop when:

- requested quantity is fully filled;
- the next level violates the slippage bound;
- recorded displayed depth ends.

The unfilled remainder is cancelled. The simulator does not extrapolate hidden liquidity beyond the recorded snapshot and does not wait for later passive fills.

### 9.4 Phase 6 envelope recheck

The simulator must never turn favorable sizing arithmetic into a Phase 6 breach after actual average entry is known.

For an opening attempt:

- total fill notional must remain `<= RiskDecision.approved_notional`;
- recompute actual stop-distance fraction from actual fill price to the approved invalidation;
- add the same versioned cost components used by Phase 6 plus the execution fee/slippage assumptions required by the plan;
- actual planned loss for accepted filled quantity must remain `<= RiskDecision.approved_risk_amount`.

If taking an entire next L2 level would cross either ceiling, reduce that final level allocation to the largest size that remains under both ceilings, rounded down to `szDecimals`. If the safe remainder rounds to zero, stop filling.

Phase 7 may execute less than Phase 6 approved. It may never execute more without a fresh risk decision.

## 10. Fees

V1 IOC fills are taker fills only.

For each fill:

`fee = abs(price * quantity) * taker_fee_rate`.

Fee rates come from `PaperExecutionConfig` and are persisted with `fee_schedule_id`. The initial native-perp baseline is 4.5 bps (`0.045%`) because that is the current base-tier assumption, but the architecture treats this as mutable venue/account policy.

No passive maker fill, maker rebate, staking discount, referral discount, builder fee, or VIP discount is awarded unless a later version has explicit evidence/configuration for it.

## 11. Funding accounting

Funding is accrued only from actual timestamped public funding observations available to the system.

For one funding observation:

`cash_delta = -(signed_quantity * oracle_price * funding_rate)`.

Thus a positive funding rate charges longs and credits shorts; negative funding does the reverse.

Requirements:

- position must have been open across the applicable funding timestamp;
- funding observation market must match;
- oracle price/rate must be finite and valid;
- each funding event is idempotent by deterministic event ID;
- funding is applied once only;
- missing funding observations are recorded as a data-quality problem, not silently interpolated;
- later Phase 8 replay must be able to reconstruct each accrual from its source event reference.

## 12. Position accounting

### 12.1 Opening

A first fill opens a position at weighted-average fill price. Fees are immediately debited from cash/equity. Initial/current stop comes from the approved Phase 6 invalidation.

A partial IOC opening creates a position only for the actually filled size. The cancelled remainder disappears; it does not remain as a working passive order.

### 12.2 Reducing/closing

Reduce-only fills realize PnL against average entry:

- LONG reduction: `(exit_price - average_entry_price) * quantity`;
- SHORT reduction: `(average_entry_price - exit_price) * quantity`.

Exit fees are debited separately.

A reduction cannot exceed current absolute quantity. If rounding leaves zero quantity, reject. A full close sets open quantity to zero, records closed-trade net result after fees/funding, updates daily realized PnL and consecutive-loss state, and removes the open position from the active set.

### 12.3 Unrealized PnL

Mark-to-market uses trustworthy current mainnet mark observations only. Missing/stale mark data blocks new exposure and marks account equity as execution-health degraded until reconciled; it does not substitute mid/oracle silently.

## 13. Position manager policy

The initial manager is intentionally conservative and avoids embedding an unvalidated take-profit strategy merely to produce more trades.

Rule precedence:

1. emergency health/risk-state exit;
2. hard stop trigger;
3. opposing directional thesis exit;
4. tighter same-direction invalidation update;
5. explicit validated reduction directive;
6. hold.

### 13.1 Emergency exit

If an open position exists and execution/market state is irreconcilably stale or a critical execution health invariant fails, the manager prioritizes reducing/closing existing exposure over finding new trades. The exit still requires a usable L2 snapshot; if none exists, state remains in emergency-exit-pending and new exposure stays blocked.

### 13.2 Stop trigger

Stops trigger from trustworthy mark price:

- LONG triggers when mark `<= current_stop`;
- SHORT triggers when mark `>= current_stop`.

Triggering does not award a fill at the stop price. It creates a reduce-only marketable IOC exit subject to latency, visible depth, slippage, and fees. Realized loss may therefore exceed planned loss.

### 13.3 Thesis exit

A fresh Phase 5 directional decision opposite the current position direction triggers `EXIT_THESIS`. A `NO_TRADE` result by itself does **not** close an existing position; entry selectivity and exit invalidation are distinct semantics.

### 13.4 Stop tightening / trailing primitive

If a fresh same-direction Phase 5 decision supplies an invalidation that is strictly more protective than the current stop, update the stop to that tighter level. Never loosen a stop.

This is the initial trailing mechanism: evidence can ratchet invalidation in the favorable direction, but Phase 7 does not invent an arbitrary 1R/2R profit-taking rule. More aggressive trailing/partial-take-profit policy belongs to later evidence-based evaluation.

### 13.5 Partial reductions

The execution/accounting layer supports deterministic reduce-only partial exits as a primitive. Phase 7 does not create a profit-target rule from thin air. A reduction directive must come from an explicit manager rule or future validated policy and must specify a fraction/quantity that rounds down safely and cannot flip the position.

## 14. Paper margin and liquidation-distance monitoring

Phase 7 must provide enough conservative account state for the independent Phase 6 risk engine without pretending to reproduce the full Hyperliquid clearinghouse.

For each open position:

- calculate current gross mark notional;
- reserve conservative margin using the smaller of the Phase 7 3x system cap and venue max leverage;
- available margin is equity minus total reserved margin, floored at zero;
- expose gross open notional and available margin to Phase 6 through a pure adapter.

Liquidation monitoring uses the validated liquidation-reference/buffer state supplied alongside the risk/execution request when available. Phase 7 does not invent undocumented Hyperliquid liquidation formulas. A missing or invalid required liquidation reference degrades execution/risk health and blocks new exposure; an observed breach triggers emergency reduction behavior.

## 15. SQLite operational state

Use Python stdlib `sqlite3`; do not add a database dependency merely for Phase 7.

Minimal durable tables:

- `paper_meta` — schema/config/account identity/version;
- `paper_order_plans` — one row per deterministic plan ID;
- `paper_execution_attempts` — one row per attempt;
- `paper_fills` — one row per level fill;
- `paper_positions` — current materialized open-position state;
- `paper_position_events` — position mutations/reductions/stop changes;
- `paper_funding_events` — idempotent funding accruals;
- `paper_account_state` — current materialized account control state.

High-volume market events are not duplicated into SQLite; rows reference Phase 3 event keys/provenance.

Critical execution updates are transactional. A successful fill transaction writes the attempt/fills and resulting position/account state atomically. If any critical write fails, rollback and fail closed. Never acknowledge a state-changing paper fill in memory if the durable transaction failed.

## 16. Idempotency and restart recovery

Deterministic IDs and database uniqueness constraints make replay/retry safe.

Rules:

- the same opening `risk_decision_id` cannot create two active opening plans;
- a plan/attempt/fill ID is applied at most once;
- duplicate L2/trade/funding delivery cannot duplicate position/account mutations;
- on startup, load persisted account and open positions before accepting new exposure;
- reconstruct/check position quantity and realized PnL from persisted fills/events against materialized rows;
- validate account totals against position/fill/funding aggregates within exact Decimal/tolerance rules defined in tests;
- any mismatch marks state inconsistent and blocks new exposure until reconciliation succeeds;
- open positions are reconciled/managed before scanner-generated new entries resume.

Because this is paper-only, recovery never queries a private exchange account. Phase 12 will add real-account reconciliation behind the separate live adapter.

## 17. Narrow execution interface

Define a small protocol/ABC that represents trading actions, not venue-specific private capabilities.

Required conceptual methods:

- create/submit a marketable IOC execution plan;
- process eligible market observations for pending plans;
- request a reduce-only reduction/close;
- read adapter-local execution/position health needed by the engine.

The interface must not expose:

- withdrawals;
- transfers;
- wallet management;
- arbitrary signing;
- raw private-key access;
- generic exchange-client escape hatches.

The paper adapter implements this interface in Phase 7. The eventual mainnet live adapter in Phase 12 must implement the same narrow semantics without changing strategy or risk code.

## 18. End-to-end control flow

The unattended paper loop is:

1. mainnet scanner/shortlist produces eligible deep-ready candidate;
2. Phase 5 produces LONG/SHORT/NO_TRADE;
3. Phase 6 evaluates current paper account/open-risk/execution health;
4. only `approved=True` can create an opening paper plan;
5. plan waits until latency cutoff and eligible real L2 evidence;
6. IOC simulator walks visible depth and charges costs;
7. successful filled portion creates/updates one paper position atomically;
8. manager continuously consumes fresh mark/strategy/health/funding observations;
9. stop/thesis/emergency/reduction actions use reduce-only IOC execution;
10. account/risk state is updated after every fill/funding/mark event;
11. after full close, closed-trade result updates daily PnL/consecutive-loss state used by Phase 6.

`NO_TRADE`, rejected risk, no-fill IOC, partial fill, and emergency-exit-pending are all normal first-class outcomes.

## 19. Failure behavior

Fail closed on:

- unsupported perp DEX execution;
- missing/stale/inconsistent L2 evidence;
- crossed/malformed books;
- future/inconsistent event timestamps;
- zero size after precision rounding;
- below-minimum order notional;
- attempted opening from rejected risk;
- attempted notional/risk above Phase 6 envelope;
- reduce-only action without a matching position;
- reduce-only quantity larger than the position;
- stop removal/loosening;
- duplicate state mutation;
- SQLite transaction/write failure;
- account/position recovery mismatch;
- missing/stale mark state required for accounting/stop evaluation;
- critical execution-health degradation.

A failure in new-entry execution never prevents the manager from attempting a risk-reducing exit when usable market data is available.

## 20. Testing requirements

Use TDD and deterministic fixtures, including actual normalized Phase 3 mainnet L2 shapes.

Tests must cover at minimum:

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
- actual stop-distance/cost planned loss never exceeds `approved_risk_amount`;
- a final L2 level is clipped/rounded down when needed;
- execution can use less risk than approved but never more.

### Fees and funding

- taker fee charged on every IOC fill;
- no maker rebate/passive fee path;
- funding sign correct for long/short and positive/negative rates;
- one funding observation applies once only;
- missing funding is surfaced, not interpolated.

### Position/accounting

- partial entry weighted-average price;
- long/short realized PnL formulas;
- partial reduction preserves remaining position;
- reduce-only cannot flip position;
- close updates realized PnL/fees/funding/equity;
- unrealized mark-to-market correct;
- gross notional/margin/available-margin adapter feeds Phase 6 consistently;
- closed loss increments consecutive-loss state and profit resets it according to the chosen account-state rule;
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

- fill + position + account write is atomic;
- injected DB failure rolls back all state;
- restart loads identical state;
- duplicate plan/fill/funding IDs are idempotent;
- materialized-state mismatch fails closed;
- failure injection cannot create duplicate positions.

### Boundary tests

- execution package contains no wallet/private-key/signing/withdraw/transfer capability;
- no real exchange order submission exists;
- no testnet URL/config path is introduced;
- no ML dependency;
- no candle-to-L2 fill fabrication;
- paper/live execution share a narrow abstraction rather than strategy-specific calls.

### End-to-end

A deterministic integration test must cover:

`scanner-ready fixture -> Phase 5 directional decision -> Phase 6 approval -> paper IOC entry -> paper position -> mark/strategy/stop management -> reduce-only IOC exit -> reconciled closed paper account`.

The test must also prove the equivalent rejection/no-fill path does not create a position.

## 21. Exit criteria

Phase 7 is complete only when:

- the float execution placeholders are replaced safely with Decimal contracts;
- paper execution is grounded in real normalized mainnet L2 evidence;
- latency, slippage, fees, funding, minimum notional, size precision, partial fills, and stop execution are modeled explicitly;
- unsupported passive maker fills are impossible;
- Phase 6 risk/notional envelopes cannot be exceeded by execution;
- one-position-per-market/reduce-only semantics prevent duplicate or flipped positions;
- paper account/equity/PnL/margin state deterministically feeds the Phase 6 risk engine;
- stop, thesis, tighter-stop, reduction, and emergency position-management mechanics work;
- restart/recovery is idempotent and fails closed on inconsistency;
- SQLite critical state changes are atomic;
- deterministic end-to-end paper lifecycle works unattended in tests;
- full Python 3.12 install/compile/Ruff/mypy/pytest CI passes;
- docs/STATUS.md and `docs/CHATGPT_PROJECT_SOURCE.md` record final verification/merge evidence;
- live trading remains disabled;
- no real-order, wallet/signing, transfer, withdrawal, or private exchange-account capability exists in Phase 7.

## 22. Deferred work

Explicitly deferred:

- rich analytical trade journal, MFE/MAE, replay manifests, and full deterministic backtester — Phase 8;
- evidence-based tuning of latency/slippage/exit assumptions — Phase 9;
- ML/champion-challenger — Phase 10;
- long-running service/shadow proving — Phase 11;
- real Hyperliquid order/cancel/account reconciliation adapter — Phase 12;
- real capital activation — Phase 13 and explicit user authorization only.

The Phase 7 simulator is therefore an honest operational proving ground, not a claim that every exchange micro-detail has already been modeled perfectly.
