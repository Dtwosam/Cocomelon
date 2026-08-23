# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Upload this file to ChatGPT Project Sources. It is the portable bootstrap context for continuing the Cocomelon build across chats. The live GitHub repository remains authoritative.

**Repository:** https://github.com/Dtwosam/Cocomelon  
**Project:** Autonomous Hyperliquid perpetual-futures trading system  
**Primary language:** Python  
**Target venue:** Hyperliquid HyperCore perpetual markets  
**Execution mode now:** Paper/shadow infrastructure only  
**Hyperliquid testnet:** NEVER USE

---

## 1. Mission

Cocomelon is being built as an autonomous intraday Hyperliquid perp trader. The final system should:

1. discover the real Hyperliquid perp universe dynamically;
2. reject unsuitable/illiquid/stale markets;
3. rank current opportunities;
4. deeply analyze a bounded shortlist;
5. choose LONG, SHORT, or NO TRADE;
6. choose entry, invalidation/stop, and exposure;
7. pass every proposal through an independent risk engine;
8. execute approved trades autonomously;
9. manage stops, partial exits, trailing/thesis exits, and emergency exits;
10. journal every decision, rejection, fill, cost, and result;
11. evaluate strategies without lookahead bias;
12. train challenger models offline;
13. promote a challenger only if it proves better than the frozen champion;
14. eventually trade real Hyperliquid mainnet capital only after explicit promotion gates pass.

Economic objective: **positive net risk-adjusted expectancy after fees, funding, slippage, and realistic execution costs**. Profit is never guaranteed.

---

## 2. Locked product decisions

These are not open questions unless the user explicitly changes them.

### Hyperliquid mainnet only

- Do not use Hyperliquid testnet for development, strategy learning, execution testing, paper trading, or live promotion.
- Main REST/API base: `https://api.hyperliquid.xyz`
- Main WebSocket: `wss://api.hyperliquid.xyz/ws`
- Runtime configuration rejects known Hyperliquid testnet hostnames.

### Paper trading uses real mainnet observations

Before real money, Cocomelon runs its own internal paper/shadow execution engine against real Hyperliquid mainnet observations. Paper fills must model spread, depth/slippage, fees, funding, latency, stop behavior, partial fills where defensible, and execution failures. Never assume perfect fills.

### Intraday V1

Typical target holding time is roughly **10 minutes to 6 hours**, but this is not a forced timer. Exit earlier when invalidated; remain longer only when thesis/risk logic permits.

Primary timeframes:

- 1m: execution/microstructure context
- 5m: short-term confirmation
- 15m: main setup
- 1h: regime/direction
- 4h: higher-timeframe context

V1 is not sub-second HFT or market making.

### Broad scanner, bounded deep analysis

Pipeline:

`discover all -> eligibility -> coarse scan -> rank -> dynamic shortlist -> deep analysis -> strategy -> decision -> risk -> execution`

No fixed favorite-token list. BTC/ETH/SOL/HYPE may rank naturally but are not hard-coded as the trading universe.

### Initial risk model

- planned account risk per trade: **0.25%**
- maximum aggregate planned open risk: **0.75%**
- daily realized-loss lockout: **1.00%**
- rolling weekly drawdown lockout: **3.00%**
- three consecutive losing trades trigger cooldown
- no averaging down
- no martingale
- no position without stop/invalidation
- correlated positions share risk
- stale/inconsistent data blocks new exposure

Leverage is not the risk budget. Position size is derived from equity, stop distance, liquidity, and risk constraints.

### Python, not Solidity

The main system is Python. HyperCore perp trading is accessed through Hyperliquid APIs/SDK. Solidity is unnecessary for V1 and is only introduced if a later explicit HyperEVM contract feature genuinely requires it.

### Free/public sources first

The initial system must not require paid market-data or infrastructure services. Prefer Hyperliquid public APIs/WebSockets and open-source libraries. Requester-pays historical archives are optional, not part of the free baseline.

### Do not fabricate history

Never reconstruct fake historical L2 books or trade flow from OHLCV candles and then call it an order-flow backtest. Microstructure research requires real recorded/reliably sourced book/trade events.

### Raw storage decision

The Phase 3 always-on collector writes fsynced, append-only, rotating JSONL as the trusted operational raw/normalized stream log. Do not add PyArrow merely to force Parquet during liveness-critical ingestion. Validated JSONL partitions are compacted/exported offline to Parquet or an equivalent columnar analytical format in the later replay/research phase. Never fake Parquet by changing file extensions.

---

## 3. Target architecture

```text
Hyperliquid Mainnet
        |
        v
REST + WebSocket Market Data
        |
        v
Durable Recorder / Data Quality
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
            first         built much later,
                           disabled by default
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

Hard boundaries:

- market-data code does not make trading decisions;
- strategy code cannot override risk;
- risk has final veto;
- models never call exchange APIs directly;
- paper/live execution share a narrow interface;
- learning cannot silently change hard risk limits.

---

## 4. Data design

### Tier A — broad universe

Maintain lightweight metadata/context across all discovered perp markets:

- universe/market metadata
- active/delisted status
- mark/mid/oracle
- volume
- funding
- open interest
- basic market-quality state

### Tier B — ranked watchlist

Maintain richer candle/context data for eligible/ranked candidates.

### Tier C — deep shortlist

For a configurable bounded shortlist (initial target around 20) and all open positions, collect:

- L2 book
- public trades
- execution-quality/microstructure state
- detailed short-timeframe events

Persistence target:

- SQLite for operational state, decisions, risk, orders/fills, positions, and journal metadata;
- durable JSONL for the Phase 3 liveness-critical raw/normalized stream log;
- Parquet or equivalent columnar datasets produced offline from validated JSONL for research/features/replay at scale.

All persisted data must preserve provenance, market identity, exchange timestamp where available, receive timestamp, and schema version.

---

## 5. Baseline strategy/learning direction

Explainable baselines come before ML control:

- trend
- breakout
- mean reversion
- funding/open-interest context
- order-flow/microstructure

The deterministic decision layer outputs LONG, SHORT, or NO TRADE with reason codes. Scores are not called probabilities unless calibration has actually been demonstrated.

Learning is champion/challenger only:

`versioned data -> offline challenger -> time-aware validation -> untouched out-of-sample -> walk-forward -> mainnet shadow -> compare -> promote only if genuinely better`

Do not start with unconstrained reinforcement learning or a model directly controlling leverage/orders.

---

## 6. Live-trading gate

Live trading remains disabled until all required evidence exists and the user explicitly authorizes it.

Initial minimum gate:

- >= 500 closed mainnet paper trades under the candidate champion
- >= 45 calendar days of live mainnet shadow operation
- positive net expectancy after modeled fees/funding/slippage
- positive untouched out-of-sample performance
- stable walk-forward performance
- overall profit factor >= 1.20
- maximum paper drawdown <= 8% under the locked risk model
- no single market contributes >35% of total positive net PnL
- no single seven-day period contributes >50% of total positive net PnL
- zero unresolved risk-invariant violations
- restart/recovery/reconciliation tests pass
- user explicitly chooses capital and authorizes live mode

Later live runtime uses a dedicated Hyperliquid API/agent wallet. Never put the master-wallet private key in the bot runtime. Live activation must require at least two independent conditions.

---

## 7. Approved build order

Do not skip phases.

0. Governance/source-of-truth anchor — COMPLETE
1. Python foundation/domain contracts/config/CI — COMPLETE
2. Mainnet REST market discovery and normalization — COMPLETE
3. WebSocket collector and durable recorder — COMPLETE / MERGED
4. Features, eligibility, scanner, opportunity ranking — ACTIVE NEXT
5. Explainable baseline strategy engines
6. Independent risk engine
7. Real-mainnet paper execution + position manager
8. Journal + deterministic replay/backtester + offline raw-to-columnar compaction
9. Evaluation/out-of-sample/walk-forward research gates
10. Champion/challenger learning engine
11. Long-running mainnet shadow operation
12. Mainnet live execution adapter built but disabled
13. Explicit user-approved live promotion
14. Evidence-based optimization/scaling

The exact current state is always `docs/STATUS.md`.

---

## 8. Completed engineering state

### Phase 1 — merged

Merge commit: `3efd9e28b84eaa5dcd75f6949d8df02e2928d163`

Established:

- Python 3.12 package layout
- mainnet-only config + testnet rejection
- paper mode default
- typed domain contracts
- time/ID utilities
- secret-safe logging
- operator `status` command
- Ruff, mypy, pytest, CI

### Phase 2 — merged

Merge commit: `b95352e238d6a9eabd63e13c1f8300e654a7e636`

Established:

- direct mainnet `/info` HTTP client
- conservative weighted rate budget
- retry/backoff
- dynamic native + HIP-3/perp DEX discovery
- correct HIP-3 market identifiers such as `xyz:NVDA`
- typed immutable market/asset/candle/funding records
- Decimal financial normalization
- active/delisted preservation
- candle + funding-history readers/normalizers
- read-only `cocomelon markets`
- real public-mainnet fixture capture
- deterministic contract tests against captured real-mainnet structures

Phase 2 real-mainnet smoke observed 500 discovered perp markets at that moment: 320 active and 180 delisted, across 11 perp DEX namespaces total (native plus 10 additional namespaces). This is an observation from the Phase 2 smoke, not a permanent market-count assumption.

### Phase 3 — merged

Merge commit: `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57`  
PR: #3  
Final verified feature head: `283bb6aadbf850a26e948fe1bbc2f1075d1c7226`

Established:

- canonical mainnet-only WebSocket client with injectable transport;
- public-only `allMids`, `l2Book`, `trades`, and `candle` protocol validation;
- normalized typed stream events and explicit data-gap contracts;
- exchange + receive timestamp provenance;
- application heartbeat and freshness tracking;
- reconnect/resubscribe with bounded exponential backoff;
- duplicate suppression and explicit out-of-order rejection/gap reporting;
- freshness baseline for subscriptions before their first event;
- fail-closed propagation of recorder/event-sink failures;
- dynamic deep-watchlist subscriptions with deterministic reconciliation;
- 800 configured subscription ceiling and hard maximum <= Hyperliquid's documented 1,000 per-IP subscription limit;
- durable rotating append-only JSONL with fsync, atomic manifest, deterministic serialization, safe recovery, and Windows-safe HIP-3 partition names;
- bounded read-only `cocomelon stream-smoke` CLI;
- exact frozen public-mainnet WebSocket fixtures with SHA-256 mutation locks.

Phase 3 real-mainnet WebSocket evidence:

- successful workflow run: `32650798749`;
- Python 3.12.14;
- `cocomelon stream-smoke --seconds 5 --market BTC` processed 1,002 normalized events;
- 6 subscriptions;
- 0 gaps, 0 duplicates, 0 anomalies, 0 reconnects, and no stale streams at completion;
- fixture artifact: `9496120799`;
- artifact ZIP SHA-256: `a5720f2012ce696536fa437d9c9102e996e098d0d98fa949c05402f88d515e88`;
- HIP-3 sample DEX `xyz`; live `allMids` carried `data.dex: "xyz"` and prefixed symbols such as `xyz:NVDA` and `xyz:XYZ100`;
- temporary network workflow removed before merge;
- no wallet, user/account stream, signing, order, transfer, withdrawal, or `post` action used.

Pre-merge regression audit:

- RED tests-only commit: `9e31762c25c5a588c904f79aff93d284880e7285`;
- RED CI: `32651509744`, failed exactly the never-seen freshness and sink-failure propagation tests;
- GREEN fix commit: `c5eba63eb30379c8a7812d660382fbfb5b83cd88`;
- GREEN CI: `32651574711`, install/compileall/Ruff/mypy/pytest all passed.

Final Phase 3 feature-tree verification:

- CI run: `32651779102` — SUCCESS;
- Python 3.12.14;
- install — PASS;
- compileall — PASS;
- Ruff — PASS;
- mypy — PASS, no issues in 26 source files;
- pytest — PASS to 100%;
- PR #3 merged with expected-head SHA protection;
- `main` verified at merge commit `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57` immediately after merge.

---

## 9. Current Phase 4 objective

Phase 4 turns trustworthy Phase 2/3 observations into a broad-to-deep market opportunity funnel without yet producing trade decisions.

Required deliverables from the approved build order:

- liquidity/spread/depth quality features;
- multi-timeframe returns/trend features;
- realized volatility and range features;
- relative-volume features;
- funding/open-interest context;
- market regime baseline;
- eligibility gate;
- opportunity score/ranker;
- dynamic shortlist manager;
- feature snapshot versioning.

Required exit properties:

- bad-quality markets cannot rank into tradable/eligible state;
- scanner operates across dynamically discovered markets rather than a favorites list;
- calculations are deterministic and lookahead-safe;
- shortlist changes are explainable from stored feature snapshots/reason codes;
- Phase 4 does not add strategy LONG/SHORT decisions, risk sizing, paper fills, ML control, wallet access, or live execution.

---

## 10. Instructions for a fresh ChatGPT chat

When asked to continue Cocomelon:

1. Treat this file as bootstrap context, not the final authority.
2. Inspect `https://github.com/Dtwosam/Cocomelon` with the connected GitHub tools.
3. Read, in order:
   - `AGENTS.md`
   - `docs/MASTER_SPEC.md`
   - `docs/DECISIONS.md`
   - `docs/BUILD_ORDER.md`
   - `docs/STATUS.md`
   - the active phase spec/plan referenced by status
4. Check recent `main` commits and open PRs.
5. Continue from the exact active task; never rebuild completed phases.
6. Use TDD and small verifiable commits.
7. Handle routine branches, PRs, CI fixes, and merges autonomously.
8. Ask the user only for a genuine product/risk decision that cannot be derived from source of truth.
9. Never claim a phase complete until its verification commands actually pass.
10. After every phase, update `docs/STATUS.md` and this portable Project Source.
11. If current Hyperliquid behavior could have changed, verify official docs immediately before coding against it.

The user expects ChatGPT to build this project **from A to Z directly in the GitHub repository**.

---

## 11. Exact handoff now

**Phase 3 is complete and merged. Phase 4 — feature engine, eligibility, scanner, opportunity ranking, and dynamic shortlist integration — is the active next phase.**

Exact next actions:

1. inspect the repository for an existing approved Phase 4 spec/implementation plan;
2. if absent, derive and commit the detailed Phase 4 plan from `MASTER_SPEC.md`, `DECISIONS.md`, and `BUILD_ORDER.md` before implementation;
3. create an isolated Phase 4 branch from current `main`;
4. implement Phase 4 with TDD, deterministic time-bounded inputs, immutable/versioned feature snapshots, and explainable eligibility/ranking reason codes;
5. integrate the resulting shortlist with the Phase 3 deep-watchlist boundary without introducing strategy or execution behavior;
6. run full deterministic CI and a bounded public-mainnet read-only smoke only if necessary to validate data wiring;
7. merge only after Phase 4 exit criteria pass;
8. do not begin baseline strategies, risk, paper execution, ML, or live execution early.

**Live trading status: DISABLED.**
