# Cocomelon Master Specification

**Status:** Canonical V1 specification  
**Repository:** `Dtwosam/Cocomelon`  
**Primary venue:** Hyperliquid perpetual futures  
**Primary language:** Python  
**Execution progression:** Mainnet data -> internal paper/shadow trading -> gated mainnet live trading  
**Hyperliquid testnet:** Forbidden

## 1. Product definition

Cocomelon is an autonomous intraday perpetual-futures trading system for Hyperliquid.

The finished system is expected to independently:

1. discover available perp markets;
2. filter out markets that are unsafe or unsuitable to trade;
3. continuously scan the eligible universe;
4. rank the best current opportunities;
5. perform deeper analysis on a dynamic shortlist;
6. choose LONG, SHORT, or NO TRADE;
7. determine an invalidation/stop and proposed exposure;
8. pass every proposed position through an independent risk engine;
9. place and manage paper orders against real Hyperliquid mainnet observations;
10. close positions automatically when risk, target, trailing, or thesis-exit conditions require it;
11. journal decisions, fills, costs, and outcomes;
12. evaluate strategy quality without lookahead bias;
13. train challenger models from trustworthy data;
14. promote challengers only when they beat the current champion under reproducible validation;
15. eventually execute real mainnet orders autonomously after live-promotion gates are met.

The economic objective is positive **net risk-adjusted expectancy**, not maximum trade frequency, win rate, leverage, or gross PnL.

No component or metric may claim guaranteed profitability.

## 2. Trading horizon

V1 is an intraday system.

Typical intended holding time is roughly **10 minutes to 6 hours**, but this is not a mandatory timer. A position may exit earlier if the setup invalidates and may remain open longer when risk limits permit and the thesis remains valid.

Primary analysis timeframes:

- `1m`: execution and microstructure context;
- `5m`: short-term structure/confirmation;
- `15m`: primary setup timeframe;
- `1h`: regime and directional context;
- `4h`: higher-timeframe context.

V1 is not intended to compete as a sub-second/high-frequency market maker.

## 3. Network and data policy

### 3.1 Mainnet only

All runtime market observations used to test or trade strategies must come from Hyperliquid mainnet.

Main API base: `https://api.hyperliquid.xyz`  
Main WebSocket: `wss://api.hyperliquid.xyz/ws`

Known Hyperliquid testnet hostnames must be rejected by runtime configuration.

### 3.2 Free-first constraint

The initial system must be buildable using free/public APIs and open-source libraries. Paid feeds, requester-pays archives, managed databases, paid hosting, or premium analytics must not become required dependencies without explicit user approval.

Hyperliquid's official S3 historical archives may incur requester data-transfer charges, so they are not part of the default free build.

### 3.3 Available Hyperliquid data

Use official endpoints/subscriptions where appropriate:

- perp metadata/universe and margin information;
- asset contexts including mark price, mid price, oracle price, funding, open interest, and daily notional volume;
- all mid prices;
- candle snapshots;
- WebSocket candle updates;
- L2 order-book snapshots;
- trade stream;
- user order/fill/position data later for live reconciliation.

At the time this spec was written, Hyperliquid documents only the most recent 5,000 candles per interval through `candleSnapshot`. That limitation must be treated as real. The system must begin recording its own mainnet history rather than pretending a deeper free history exists.

### 3.4 Data tiers

Use three tiers to avoid unnecessary storage and computation:

**Tier A — universe data:** lightweight metadata and asset-context data across all discoverable markets.

**Tier B — ranked watchlist data:** candles and richer state for markets that pass eligibility and rank highly.

**Tier C — deep microstructure data:** L2 books and trade streams for a bounded dynamic shortlist and all currently open positions.

The deep shortlist should initially target around 20 markets, configurable rather than hard-coded.

### 3.5 Persistence

Use:

- **SQLite** for configuration snapshots, system state, decisions, orders, simulated/real fills, positions, risk events, and trade journal records;
- **Parquet/columnar files** for higher-volume raw/normalized market events and derived feature datasets.

Every data record must preserve source/provenance and timestamps sufficient to prevent lookahead bias.

## 4. Market universe

Market discovery must be dynamic, not a hard-coded BTC/ETH/SOL list.

Represent each market with a canonical key that can distinguish perp DEX namespace and coin. The architecture must be capable of supporting the default Hyperliquid perp DEX and additional perp DEX/HIP-3 namespaces.

For sequencing, V1 may enable paper execution on the default validator-operated perp DEX first while preserving multi-DEX discovery/interfaces. Additional perp DEX execution is promoted only after their metadata, margin, symbol, and execution semantics are validated.

### 4.1 Eligibility gate

A market must pass quality requirements before any strategy can trade it. Filters are configurable and will be calibrated from observed distributions rather than invented once and forgotten.

Candidate filters include:

- active and not delisted;
- valid mark/mid/oracle state;
- minimum daily notional volume;
- minimum open interest;
- maximum bid/ask spread;
- minimum visible depth near mid;
- maximum data age;
- supported margin/leverage semantics;
- absence of operational anomalies.

Eligibility answers: **Can we responsibly trade this market?**

Ranking answers: **Is there an attractive setup right now?**

These are separate decisions.

## 5. Scanner and opportunity ranking

The system observes the broad universe cheaply, then spends expensive analysis only on high-quality candidates.

Pipeline:

`market discovery -> eligibility -> coarse features -> opportunity ranking -> dynamic shortlist -> deep features -> strategy engines`

Ranking inputs may include:

- multi-timeframe returns/momentum;
- realized volatility;
- range compression/expansion;
- relative volume;
- open-interest level/change;
- funding level/change;
- spread/depth quality;
- order-flow imbalance when deep data is available;
- relationship to BTC/ETH and broad market regime.

The ranker does not itself authorize a trade.

## 6. Strategy engines

V1 establishes multiple explainable strategy families instead of one opaque model:

### 6.1 Trend

Detects persistent directional structure and seeks continuation entries when trend quality, liquidity, and risk/reward are acceptable.

### 6.2 Breakout

Detects compression/range boundaries and seeks expansion only when confirmation reduces false-breakout risk.

### 6.3 Mean reversion

Detects statistically stretched moves in non-trending regimes and seeks reversion only when the regime permits it.

### 6.4 Funding/open-interest context

Measures crowding and positioning context. Extreme funding or rapidly changing OI may strengthen, weaken, or veto another setup; it is not automatically a standalone contrarian signal.

### 6.5 Order flow

Uses trustworthy L2/trade observations for imbalance, aggressor flow, depth changes, and execution timing. Historical order-flow performance is evaluated only on real recorded/reliably sourced microstructure data.

Every engine outputs a structured signal with market, direction, score, invalidation information, features/reasons, and timestamp. Strategy scores are not called calibrated probabilities unless calibration has actually been demonstrated.

## 7. Decision engine

The decision engine combines strategy evidence into exactly one of:

- `LONG`;
- `SHORT`;
- `NO_TRADE`.

Initial V1 combination logic must be deterministic and explainable. It should support regime-dependent weighting and vetoes without pretending to be machine intelligence.

The decision engine must record rejected/no-trade decisions as training/evaluation observations where storage costs permit. Missed opportunities and correctly avoided losses are both informative.

## 8. Risk engine

Risk is independent from signal conviction and has final veto power.

### 8.1 Initial limits

- planned account risk per trade: **0.25% of current equity**;
- maximum aggregate planned open risk: **0.75%**;
- daily realized-loss lockout: **1.00%**;
- rolling weekly drawdown lockout: **3.00%**;
- three consecutive losing closed trades trigger cooldown;
- no martingale;
- no averaging down;
- no trade without an explicit stop/invalidation;
- correlated positions share a risk bucket;
- new exposure is blocked on stale/inconsistent market data or degraded execution health.

### 8.2 Position sizing

Base sizing concept:

`risk_budget = account_equity * 0.0025`

`raw_notional = risk_budget / stop_distance_fraction`

Then cap/adjust for:

- venue leverage/margin constraints;
- available margin;
- liquidity/depth;
- per-market exposure limits;
- correlation bucket limits;
- aggregate open risk;
- estimated slippage and fees.

Leverage does not define risk. Stop distance and notional determine planned loss. Real loss can exceed planned loss because of slippage/gaps, so the simulator and journal must report realized outcomes honestly.

## 9. Paper execution engine

Paper trading is not a toy ledger. It is the primary pre-live proving ground.

It must use real mainnet observations and simulate:

- bid/ask spread;
- walking visible order-book depth for marketable orders;
- configurable latency;
- partial fill behavior where data permits;
- maker/taker fees from explicit configuration/versioned assumptions;
- funding accrual;
- stop/trigger execution;
- reduce-only semantics;
- position accounting;
- realized/unrealized PnL;
- liquidation-distance monitoring;
- rejected orders and stale-data failure.

V1 should prefer marketable/IOC-style simulated entry/exit behavior when realistic passive queue position cannot be proven. Do not award imaginary maker fills.

Paper and live adapters must implement the same narrow execution interface so strategy/risk code does not change when live execution is eventually introduced.

## 10. Position manager

Once a position exists, the system continues evaluating it.

Possible actions:

- hold;
- reduce/partial take profit;
- tighten stop;
- trail stop;
- exit because the thesis invalidated;
- emergency exit because risk/execution state degraded.

V1 forbids adding to a losing position. Pyramiding into winners is also out of initial scope unless later added by an explicit documented decision.

The maximum intended hold duration is a monitoring guard, not a reason to keep a bad trade alive.

## 11. Journal and evaluation

Every trade must be reconstructable.

Journal fields include at minimum:

- decision id;
- market and direction;
- decision timestamp;
- regime;
- strategy outputs and feature snapshot reference;
- entry plan and invalidation;
- approved risk budget/notional;
- simulated/real orders and fills;
- fees;
- funding;
- slippage estimate/realization;
- MFE and MAE;
- exit reason;
- gross and net PnL;
- net R multiple;
- account equity before/after;
- data-quality and execution-health state.

Primary evaluation metrics:

- net expectancy in R and currency;
- profit factor;
- maximum drawdown;
- return/drawdown ratio;
- Sharpe/Sortino-like risk-adjusted metrics where statistically meaningful;
- tail loss distribution;
- performance by market, regime, strategy, direction, time of day, and confidence/score bucket;
- fees/funding/slippage drag;
- missed-opportunity analysis for sampled NO_TRADE decisions.

Win rate is descriptive, not the optimization target.

## 12. Backtesting and replay

Backtests must be event/time ordered and lookahead-safe.

Two evidence classes must remain separate:

1. **Candle/context backtests** using trustworthy historical OHLCV/funding/context that was actually available.
2. **Microstructure replay** using recorded/reliable order-book and trade events.

Never infer a historical L2 book from a candle and label it an order-flow backtest.

Validation sequence:

`training/in-sample -> untouched out-of-sample -> walk-forward -> live mainnet shadow/paper`

A strategy is not considered proven because one backtest period is profitable.

## 13. Learning system

Machine learning is introduced only after baseline data and evaluation are trustworthy.

### 13.1 Champion/challenger model

- The **champion** is the currently approved decision/ranking model.
- A **challenger** trains offline from versioned datasets.
- Challenger data splits must be time aware.
- Hyperparameters and feature sets are recorded.
- Challenger results must be reproducible.
- A challenger may not touch live capital merely because training metrics improved.

Potential initial ML tasks:

- estimate expected net R conditional on setup features;
- rank opportunities;
- identify regime-dependent strategy weights;
- estimate stop/exit failure risk;
- calibrate score buckets.

Do not start with unconstrained reinforcement learning or a model that directly controls leverage/order placement.

## 14. Live trading promotion

Live code is built late and remains disabled by default.

Initial minimum promotion evidence before real autonomous orders are allowed:

- at least **500 closed mainnet paper trades** under the candidate champion;
- at least **45 calendar days** of live mainnet shadow operation;
- positive net expectancy after modeled fees, funding, and slippage;
- positive untouched out-of-sample results;
- stable walk-forward performance rather than one lucky window;
- profit factor of at least **1.20** overall;
- maximum paper drawdown no worse than **8%** under the locked risk model;
- no single market contributing more than **35%** of total positive net PnL;
- no single seven-day period contributing more than **50%** of total positive net PnL;
- zero unresolved risk-invariant violations;
- successful restart/recovery/reconciliation tests;
- user explicitly authorizes live promotion and decides capital amount.

These are initial gates, not claims that passing them guarantees profitability. Changes require a documented decision with evidence.

### 14.1 Live safety controls

Live activation must require at least two independent conditions, for example:

- configuration sets `execution.mode = live`;
- environment variable contains an exact live-trading acknowledgement value.

Use a dedicated Hyperliquid API/agent wallet. Never require the master wallet private key in the bot runtime.

The code-facing live adapter must expose trading actions only—orders, cancels, position/risk reconciliation—not withdrawal or arbitrary transfer methods.

## 15. Failure behavior

Fail closed on:

- stale WebSocket/market timestamps;
- irreconcilable account/position state;
- repeated order acknowledgement failures;
- unexpected duplicate fills/orders;
- database write failure for critical execution state;
- risk-state corruption;
- clock/time sanity failure affecting nonces or event ordering;
- configured daily/weekly loss lockouts.

Open positions receive priority over finding new trades. Recovery logic must first reconcile actual/simulated state, then resume decisions.

## 16. Technology baseline

Initial intended stack:

- Python 3.12;
- official `hyperliquid-python-sdk` for supported account/exchange interactions where appropriate;
- direct HTTP/WebSocket handling where tighter data-control/reconnect behavior is useful;
- `asyncio` for concurrent collectors/loops;
- `polars`/NumPy for feature research and datasets;
- SQLite for operational/journal state;
- Parquet for high-volume market datasets;
- pytest for testing;
- Ruff/formatting and static typing configured in the repo;
- scikit-learn/LightGBM/XGBoost only when the learning phase begins and only if justified by measured baselines.

The official SDK currently declares Python `^3.9` and classifiers through Python 3.13, so Python 3.12 is within its declared support range at the time of this specification.

## 17. Explicit non-goals for early V1

Do not spend early phases on:

- a polished web dashboard;
- mobile apps;
- social features;
- copy trading;
- user custody;
- Solidity contracts;
- sub-second HFT;
- market making;
- paid alternative-data feeds;
- autonomous strategy code rewriting;
- automatic live capital scaling;
- reinforcement learning controlling raw orders;
- dozens of strategies before a few baselines are validated.

## 18. Success definition

The project succeeds in stages.

**Engineering success:** reliable mainnet data, deterministic replay, realistic paper execution, correct risk accounting, and safe recovery.

**Research success:** at least one strategy/ensemble demonstrates repeatable positive net expectancy across out-of-sample, walk-forward, and live shadow data.

**Live readiness:** all promotion gates and operational safety tests pass and the user explicitly authorizes mainnet live execution.

**Economic success:** live results continue to show positive net expectancy without unacceptable drawdown. If the edge disappears, the correct behavior is to reduce/stop trading—not force activity.

## 19. Official references

- https://hyperliquid.gitbook.io/hyperliquid-docs
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets
- https://github.com/hyperliquid-dex/hyperliquid-python-sdk

Before implementing exchange-specific semantics, re-check the current official docs because endpoints, limits, market structure, and SDK behavior can change.