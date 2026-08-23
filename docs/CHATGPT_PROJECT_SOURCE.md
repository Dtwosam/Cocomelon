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
4. Features, eligibility, scanner, opportunity ranking — COMPLETE / PR #4 FINAL MERGE GATE
5. Explainable baseline strategy engines — NEXT AFTER PHASE 4 MERGE
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

Established Python 3.12 package layout, mainnet-only config + testnet rejection, paper mode default, typed domain contracts, time/ID utilities, secret-safe logging, operator `status`, and Ruff/mypy/pytest/CI.

### Phase 2 — merged

Merge commit: `b95352e238d6a9eabd63e13c1f8300e654a7e636`

Established direct mainnet `/info` HTTP access, conservative rate budgeting/retry, dynamic native + HIP-3 discovery, correct namespaced market IDs, typed immutable REST-normalized records, Decimal financial normalization, candle/funding readers, read-only `cocomelon markets`, and real-mainnet contract fixtures.

Phase 2 public-mainnet smoke observed 500 discovered perp markets at that moment: 320 active and 180 delisted. This was an observation, not a permanent assumption.

### Phase 3 — merged

Merge commit: `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57`  
PR: #3

Established canonical mainnet-only WebSocket collection, public-only `allMids`/`l2Book`/`trades`/`candle` normalization, heartbeat/freshness/reconnect handling, duplicate/out-of-order protection, deterministic dynamic deep-watchlist reconciliation, bounded subscription safety, durable fsynced rotating JSONL recording with recovery manifests, `cocomelon stream-smoke`, and exact frozen real-mainnet WebSocket fixtures.

Phase 3 smoke run `32650798749` processed 1,002 normalized events in five seconds with 6 subscriptions, 0 gaps, 0 duplicates, 0 anomalies, 0 reconnects, and no stale streams. The temporary network workflow was removed before merge.

### Phase 4 — implementation verified, merge gate pending

PR: #4  
Verified implementation head before continuity-doc reconciliation: `6de2a1addc7da6018b76a107b59a2e5ba1426262`  
Verified merge-ref: `45938e4443b6bd119be96e164d5bc92ccc63456f`  
Deterministic CI run: `32655216604` — SUCCESS  
Public-mainnet scanner smoke: run `32655176825` — SUCCESS

Established:

- immutable/versioned/provenanced feature snapshots with deterministic IDs;
- broad funding/OI/volume/return/dislocation context across the dynamic universe;
- closed-window 5m/15m/1h/4h candle returns;
- realized volatility, range expansion, and relative volume;
- L2 spread/depth/imbalance/book-age features;
- explainable baseline trend + volatility regimes;
- coarse rankability separated from deep readiness;
- distribution-derived eligibility thresholds plus hard caps;
- direction-neutral percentile opportunity ranking with component contributions/reason codes;
- missing-feature weight renormalization rather than fabricated zero penalties;
- independent Tier B ranked watchlist and hysteretic Tier C shortlist;
- Phase 3 deep-watchlist/subscription-ceiling integration;
- broad-to-deep scanner orchestration with coarse fallback when enrichment is missing;
- bounded read-only `cocomelon scan-once --limit 20`.

Phase 4 public-mainnet smoke used one registry refresh and broad-only scanning. It discovered 500 markets, produced 500 feature snapshots, marked 320 rankable and 180 rejected, skipped 0, and bounded output to 20 rows. The top broad-attention names in that timestamped observation began XPL, PURR, ENA, PENGU, and PUMP. Rankable rows showed `missing_deep_data` because the operator command intentionally does not fan out L2/candle enrichment. This is attention ranking, not a trade signal or profitability claim.

The temporary Phase 4 smoke workflow was removed before the final merge gate. No wallet, account endpoint, signing, order, transfer, withdrawal, strategy direction, risk sizing, ML control, or live execution was introduced.

---

## 9. Next Phase 5 objective

Phase 5 begins only after PR #4 is merged and `main` is verified. It introduces **explainable baseline strategy engines**, not risk or execution.

Expected strategy families from the approved architecture:

- trend;
- breakout;
- mean reversion;
- funding/open-interest context;
- order-flow/microstructure.

Phase 5 must consume Phase 4 feature snapshots/ranks without allowing scanner scores to masquerade as trade probabilities. Strategy output may propose directional hypotheses with explicit reason codes, but cannot size risk, bypass eligibility/data-quality gates, or send orders. NO TRADE remains a first-class result.

Before Phase 5 implementation:

1. read `AGENTS.md`, `MASTER_SPEC.md`, `DECISIONS.md`, `BUILD_ORDER.md`, and `STATUS.md` from current `main`;
2. create/review the Phase 5 design/spec and implementation plan;
3. use TDD and an isolated branch;
4. keep risk engine, paper execution, ML, and live execution out of Phase 5.

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

**Phase 4 implementation and exit criteria are verified on PR #4. The temporary public-mainnet smoke workflow has been removed. The remaining Phase 4 work is continuity-doc CI, expected-head PR merge, and verification that `main` contains the Phase 4 merge.**

After that merge is verified, Phase 5 — explainable baseline strategy engines — becomes the active phase. Do not begin Phase 5 implementation from the Phase 4 branch, and do not begin risk, paper execution, ML, or live execution early.

**Live trading status: DISABLED.**
