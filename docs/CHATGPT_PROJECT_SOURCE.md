# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose of this file:** Upload this file to the ChatGPT Project Sources for the Cocomelon project. It is a portable bootstrap context so a new chat can continue development without reconstructing earlier decisions from conversation history.

**Repository:** https://github.com/Dtwosam/Cocomelon  
**Project:** Autonomous Hyperliquid perpetual-futures trading system  
**Primary language:** Python  
**Target venue:** Hyperliquid HyperCore perpetual markets  
**Current execution mode:** Paper/shadow only  
**Hyperliquid testnet:** NEVER USE

---

## 1. What we are building

Cocomelon is an autonomous perp trading system whose final job is to make its own trading decisions on Hyperliquid.

The finished system should continuously:

1. discover Hyperliquid perpetual markets;
2. filter out markets with bad liquidity/data/market quality;
3. scan the broad eligible universe;
4. rank current opportunities;
5. deeply analyze a dynamic shortlist;
6. choose LONG, SHORT, or NO TRADE;
7. define an entry, invalidation/stop, and position size;
8. pass the proposed trade through an independent risk engine;
9. execute the approved order itself;
10. manage the position itself;
11. take partial profits/tighten or trail risk when evidence supports it;
12. close the position when the thesis invalidates, risk requires it, or the exit logic fires;
13. record the full decision/trade lifecycle;
14. evaluate what worked under which market conditions;
15. train challenger models offline;
16. promote a challenger only if it proves better than the current champion;
17. eventually do the same with real mainnet capital after strict promotion gates pass.

The goal is **positive net risk-adjusted expectancy after fees, funding, slippage, and realistic execution costs**. Do not optimize the project around trade count, leverage, or win rate. There is no guarantee of profit.

---

## 2. Critical decisions already made

These are not open questions unless the user explicitly changes them.

### Mainnet, not testnet

Do not use Hyperliquid testnet for market learning, paper trading, execution testing, or any other stage.

Use real Hyperliquid mainnet market observations from:

- REST/API base: `https://api.hyperliquid.xyz`
- WebSocket: `wss://api.hyperliquid.xyz/ws`

The code should reject known Hyperliquid testnet hostnames.

### Paper trading on real mainnet data

Before real money, Cocomelon uses an internal paper/shadow execution engine fed by real Hyperliquid mainnet data.

Paper execution must be realistic: spread, depth/slippage, fees, funding, latency, stop behavior, partial fills where defensible, and rejected/stale orders must be modeled. Never assume every signal fills perfectly at the displayed price.

### Autonomous trade lifecycle

The final bot does not wait for manual approval of each trade. It selects market/direction, enters, manages, and closes positions autonomously inside hard risk constraints.

### Intraday focus

V1 is aimed at trades typically held about **10 minutes to 6 hours**.

This is not a hard holding timer. Exit earlier if the setup fails; remain longer only if thesis/risk logic still supports the position.

Use multiple timeframes:

- 1m: execution/microstructure context
- 5m: short-term confirmation
- 15m: main setup
- 1h: regime/directional context
- 4h: higher-timeframe context

This is not a sub-second HFT project.

### Broad scanner, narrow deep analysis

Do not deeply analyze every listed market continuously.

Use this funnel:

`discover all -> eligibility filter -> coarse scan -> rank -> dynamic shortlist -> deep analysis -> decision -> risk -> execution`

The system should not have favorite coins hard-coded. BTC/ETH/SOL/HYPE can naturally rank highly, but market discovery is dynamic.

### Risk defaults

Initial V1 risk policy:

- planned account risk per trade: **0.25%**
- maximum aggregate planned open risk: **0.75%**
- daily realized-loss lockout: **1.00%**
- rolling weekly drawdown lockout: **3.00%**
- three consecutive losing closed trades trigger a cooldown
- no averaging down
- no martingale
- no trade without a defined stop/invalidation
- correlated positions share risk
- stale/inconsistent data blocks new exposure

Leverage is not the risk budget. Position size comes from equity, stop distance, liquidity, and the 0.25% planned-loss budget, then venue/margin constraints are applied.

### Python, not Solidity

Use Python for the main system.

Hyperliquid has HyperEVM, but the target perp order books/positions are in HyperCore and are accessible through the API/SDK. Solidity adds no benefit to V1. Only add Solidity later if a specific HyperEVM smart-contract feature genuinely requires it.

### Free/public sources first

The initial build should not depend on paid market data or paid infrastructure.

Use Hyperliquid public APIs/WebSockets and open-source libraries. Hyperliquid historical S3 archives can be requester-pays, so they are not a required part of the free build.

### Do not fake history

Hyperliquid's candle API provides a limited recent history (official docs currently state the most recent 5,000 candles per interval). Begin collecting our own mainnet history.

Never fabricate historical L2 books or trade flow from OHLCV candles and then claim an order-flow backtest. Microstructure research needs actual recorded/reliably sourced book/trade data.

---

## 3. System architecture

Target flow:

```text
Hyperliquid Mainnet
        |
        v
Market Data / Recorder
        |
        v
Market Discovery + Eligibility
        |
        v
Broad Scanner / Opportunity Ranker
        |
        v
Dynamic Deep Watchlist
        |
        +-----------------------------+
        |             |               |
        v             v               v
      Trend        Breakout      Mean Reversion
        |             |               |
        +------- Funding/OI -----------+
        +-------- Order Flow ----------+
                      |
                      v
               Decision Engine
             LONG/SHORT/NO_TRADE
                      |
                      v
                 Risk Engine
              APPROVE / REJECT
                      |
                      v
              Execution Interface
                /             \
               v               v
          Paper Adapter     Live Adapter
           (current)       (built late,
                            disabled)
               |
               v
          Position Manager
               |
               v
          Journal / Replay
               |
               v
       Evaluation / Research
               |
               v
      Champion / Challenger ML
```

Important boundaries:

- market data does not make trading decisions;
- strategies do not control risk limits;
- risk has final veto;
- models never call exchange APIs directly;
- paper and live execution implement the same narrow interface;
- learning cannot silently modify hard risk limits.

---

## 4. Data design

Use tiers so we can watch many markets without storing an insane amount of data.

### Tier A — broad universe

Across discoverable perps, periodically maintain:

- metadata/universe
- active/delisted status
- mark/mid/oracle
- daily notional volume
- funding
- open interest
- basic market quality

### Tier B — ranked watchlist

For eligible/ranked markets maintain richer candles/features across the required timeframes.

### Tier C — deep shortlist

For a bounded dynamic shortlist (initial target around 20, configurable) and all open positions, record/order-process:

- L2 book
- trade stream
- execution-quality features
- detailed short-timeframe events

Storage:

- SQLite: operational state, configs, decisions, risk records, orders, fills, positions, journal metadata
- Parquet/columnar datasets: higher-volume raw/normalized market events and feature datasets

Every important record must preserve source and timestamps. Prevent lookahead bias.

---

## 5. Market eligibility vs opportunity

Never confuse these.

**Eligibility:** is this market responsible to trade at all?

Potential checks:

- active/not delisted
- fresh valid prices
- adequate volume/OI
- acceptable spread
- sufficient visible depth
- supported margin semantics
- healthy data/execution state

**Opportunity:** assuming the market is eligible, is there an edge right now?

A high momentum score must never rescue an illiquid/broken market from the eligibility veto.

---

## 6. Baseline strategy families

Start explainable. Do not jump directly to a giant AI model.

### Trend

Continuation when multi-timeframe structure and conditions support persistent direction.

### Breakout

Compression/range expansion with confirmation and false-breakout controls.

### Mean reversion

Stretched moves only in regimes where reversion historically works.

### Funding / open interest

Crowding/positioning context. It can strengthen, weaken, or veto another setup. Extreme funding is not automatically a short signal.

### Order flow

L2/trade imbalance, aggressive flow, depth changes, and execution timing using trustworthy recorded microstructure.

The deterministic baseline decision engine combines the strategy evidence and outputs LONG, SHORT, or NO_TRADE with reason codes. Do not label a score as a real probability unless it has been calibrated.

---

## 7. Paper execution requirements

Paper trading is the main pre-live proving environment and must be difficult enough to trust.

Model:

- current bid/ask spread
- visible order-book depth for marketable fills
- slippage
- latency
- fees
- funding
- partial fills when defensible
- stop execution
- reduce-only behavior
- rejected orders
- stale-data failures
- realized/unrealized PnL
- liquidation-distance monitoring

Prefer conservative marketable/IOC-style fill assumptions initially. Do not grant imaginary passive maker fills without queue evidence.

---

## 8. Position management

After entry, the bot continues evaluating the position.

Possible actions:

- hold
- partial take profit
- tighten stop
- trail
- exit because setup invalidated
- emergency exit because system/risk state degraded

V1 does not add to losing positions. Do not keep a bad position alive just to satisfy the typical holding window.

---

## 9. What the system learns

The system should learn **which setups have positive expectancy under which conditions**, not merely whether the last trade won.

Record enough context for each decision/trade to analyze:

- market/regime
- strategy outputs
- trend/momentum/volatility
- volume
- funding/OI
- book/order-flow context when available
- BTC/broad-market context
- entry/stop/size
- fees/funding/slippage
- MFE/MAE
- exit reason
- net PnL and net R

Record sampled NO_TRADE/rejected opportunities too, because correct avoidance and missed opportunities are useful evidence.

Evaluate primarily:

- net expectancy
- profit factor
- max drawdown
- return vs drawdown
- risk-adjusted metrics
- tail losses
- performance by market/regime/strategy/direction/time
- cost drag

Do not optimize primarily for win rate.

---

## 10. Learning architecture

Learning is **champion/challenger**, not uncontrolled live self-modification.

```text
versioned data
    -> offline challenger training
    -> time-aware validation
    -> untouched out-of-sample
    -> walk-forward
    -> mainnet live shadow
    -> compare with champion
    -> promote only if genuinely better
```

Initial ML should focus on useful bounded problems such as expected net R, opportunity ranking, regime-dependent strategy weights, and score calibration.

Do not start with reinforcement learning controlling raw orders/leverage.

---

## 11. Live trading gate

Live trading is disabled until evidence and user authorization both exist.

Initial minimum gate defined in the master spec:

- >= 500 closed mainnet paper trades under the candidate champion
- >= 45 calendar days of mainnet shadow operation
- positive net expectancy after fees/funding/slippage
- positive untouched out-of-sample performance
- stable walk-forward results
- overall profit factor >= 1.20
- maximum paper drawdown <= 8% under locked risk model
- no single market contributes >35% of total positive net PnL
- no single seven-day period contributes >50% of total positive net PnL
- zero unresolved risk-invariant failures
- restart/recovery/reconciliation tests pass
- user explicitly authorizes live mode and chooses capital amount

Passing these gates does not guarantee future profit. If the edge disappears, the system should stop/reduce trading rather than force trades.

Live runtime later uses a dedicated Hyperliquid API/agent wallet. Never put the master-wallet private key in the bot runtime.

Live activation must require two independent conditions (for example a config mode plus exact environment acknowledgement). One accidental switch cannot turn on live trading.

---

## 12. Approved build order

Do not skip phases.

0. Governance/source-of-truth anchor
1. Python foundation/domain contracts/config/CI
2. Mainnet REST market discovery and normalization
3. WebSocket collector and durable recorder
4. Features, eligibility, scanner, opportunity ranking
5. Explainable baseline strategy engines
6. Independent risk engine
7. Mainnet paper execution + position manager
8. Journal + deterministic replay/backtester
9. Evaluation/out-of-sample/walk-forward research gates
10. Champion/challenger learning engine
11. Long-running mainnet shadow operation
12. Mainnet live execution adapter built but disabled
13. Explicit user-approved live promotion
14. Evidence-based optimization/scaling

The current exact repo phase is always in `docs/STATUS.md`.

---

## 13. Instructions for ChatGPT when continuing this project

When a new chat is asked to continue building Cocomelon:

1. Treat this file as bootstrap context, not a substitute for the live repo.
2. Inspect `https://github.com/Dtwosam/Cocomelon` using the connected GitHub tools.
3. Read, in order:
   - `AGENTS.md`
   - `docs/MASTER_SPEC.md`
   - `docs/DECISIONS.md`
   - `docs/BUILD_ORDER.md`
   - `docs/STATUS.md`
   - the active plan referenced by `STATUS.md`
4. Check recent commits so the current repo state is known rather than guessed.
5. Continue from the exact active task/phase. Do not rebuild completed phases.
6. Use test-driven, small, verifiable changes.
7. Keep the user updated during long work, but continue autonomously unless an actual product decision requires explicit approval.
8. Never claim a phase is complete without running its verification commands/tests.
9. After each completed phase, update `docs/STATUS.md` with evidence and the exact next action.
10. If a newly discovered Hyperliquid fact could invalidate the design, verify it against current official docs and update `docs/DECISIONS.md`/`MASTER_SPEC.md` deliberately rather than silently changing architecture.

The user expects ChatGPT to build the project **from A to Z in the GitHub repository**, not merely provide snippets for the user to assemble.

---

## 14. Current handoff status

**Phase 1 — Python foundation and domain contracts — is complete and merged into `main`. Phase 2 — Hyperliquid mainnet discovery and REST snapshots — is the active next phase.**

Phase 1 merge commit on `main`:

`3efd9e28b84eaa5dcd75f6949d8df02e2928d163`

Pull request #1 was merged after successful Python 3.12 CI. The verified Phase 1 checks included project installation, Ruff, mypy, and pytest, with paper mode and mainnet-only safety defaults preserved.

The exact next action is:

1. re-check current official Hyperliquid API schemas and rate limits;
2. create and commit the Phase 2 implementation plan for **Hyperliquid mainnet discovery and REST snapshots**;
3. execute Phase 2 autonomously through a feature branch/PR;
4. merge only after verification passes and update `docs/STATUS.md`;
5. continue through the build order without asking for routine integration choices.

Do not begin strategy code, ML, paper execution, or live execution before the preceding build-order phases pass. The user expects routine engineering, branch, PR, CI, and merge decisions to be handled autonomously; ask only for genuine product/risk decisions that cannot be derived from the source of truth.

---

## 15. Official references to re-check when needed

- Hyperliquid overview: https://hyperliquid.gitbook.io/hyperliquid-docs
- API: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
- Info endpoint: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- Perpetual info: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
- WebSocket: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket
- WebSocket subscriptions: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- Rate limits: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- Exchange endpoint: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint
- Nonces/API wallets: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets
- Official Python SDK: https://github.com/hyperliquid-dex/hyperliquid-python-sdk

Hyperliquid changes over time. Verify exchange-specific details against current official docs before coding them.