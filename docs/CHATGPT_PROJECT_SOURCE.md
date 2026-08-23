# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing the Cocomelon build across ChatGPT chats. The live GitHub repository is authoritative.  
**Repository:** `Dtwosam/Cocomelon`  
**Project:** Autonomous Hyperliquid perpetual-futures trading system  
**Primary language:** Python  
**Target venue:** Hyperliquid HyperCore perpetual markets  
**Execution mode now:** research + mainnet observation; live trading disabled  
**Hyperliquid testnet:** NEVER USE

---

## 1. Mission

Cocomelon is being built as an autonomous intraday Hyperliquid perp trader. The final system should:

1. discover the real Hyperliquid perp universe dynamically;
2. reject unsuitable, illiquid, stale, or inconsistent markets;
3. rank current opportunities;
4. deeply analyze a bounded dynamic shortlist;
5. choose LONG, SHORT, or NO TRADE;
6. define entry context and thesis invalidation;
7. pass every proposal through an independent risk engine;
8. size approved exposure within hard risk limits;
9. execute approved trades autonomously;
10. manage stops, partial exits, trailing/thesis exits, and emergency exits;
11. journal every decision, rejection, fill, cost, and result;
12. replay/evaluate without lookahead bias;
13. train challenger models offline;
14. promote challengers only after time-aware evidence shows genuine improvement;
15. eventually trade real mainnet capital only after all promotion gates pass and the user explicitly authorizes live capital.

Economic objective: **positive net risk-adjusted expectancy after fees, funding, slippage, and realistic execution costs**. Profit is never guaranteed.

---

## 2. User operating instruction

The user wants ChatGPT to build this project **from A to Z directly in GitHub** and to handle routine engineering/product decisions autonomously. Do not repeatedly ask for approval when the source of truth or best engineering judgment can resolve a choice.

Optimize decisions toward durable positive expectancy and capital survival, not trade count, leverage, or headline win rate.

The exception remains real-money activation: live mode and live capital amount require explicit user authorization after the evidence gates pass.

---

## 3. Locked product decisions

### Mainnet only

- Hyperliquid testnet is forbidden for development, strategy testing, paper trading, or promotion.
- Main REST/API base: `https://api.hyperliquid.xyz`
- Main WebSocket: `wss://api.hyperliquid.xyz/ws`
- Runtime configuration rejects known Hyperliquid testnet hosts.

### Paper/shadow uses real mainnet observations

Before real money, Cocomelon will use an internal paper/shadow execution engine against real Hyperliquid mainnet market observations. Paper execution must model spread, visible depth/slippage, fees, funding, latency, stops, partial fills where defensible, and execution failure. Never assume perfect fills.

### Intraday V1

Typical intended holding window is roughly **10 minutes to 6 hours**, but it is not a forced timer. Exit whenever the thesis/risk logic says the trade is invalid; a strong move may remain open longer if later position-management rules permit it.

Primary timeframes:

- 1m — execution/microstructure context
- 5m — short-term confirmation
- 15m — main setup
- 1h — regime/direction
- 4h — higher-timeframe context

V1 is not sub-second HFT or market making.

### Broad universe, bounded deep analysis

Pipeline:

`discover all -> eligibility -> broad features -> rank -> dynamic shortlist -> deep features -> strategy -> decision -> risk -> execution`

No fixed favorite-token trading universe.

### Locked initial risk model

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

Leverage is subordinate to the risk budget; it is not itself the risk budget.

### Python, not Solidity

The main system is Python. HyperCore perp trading is accessed through Hyperliquid APIs/SDK. Solidity is unnecessary for V1 and should appear only if a later genuine HyperEVM contract feature requires it.

### Free/public sources first

The initial build must not depend on paid market-data services. Prefer Hyperliquid public REST/WebSocket APIs and open-source libraries. Requester-pays archives are optional, not part of the free baseline.

### Never fabricate microstructure history

Do not reconstruct fake historical L2/order flow from OHLCV candles. Order-flow research must use real normalized trade/book events recorded or reliably sourced at the time.

### Raw storage

Phase 3 uses fsynced append-only rotating JSONL as the trusted operational stream log. Later replay/research phases may compact validated JSONL offline into Parquet or another real columnar format. Never fake Parquet by renaming files.

---

## 4. Architecture and hard boundaries

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
Dynamic Deep Shortlist
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
            first          much later,
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
- scanner opportunity rank is attention priority, not directional evidence;
- strategy code may propose direction/invalidation but cannot size positions or send orders;
- context engines cannot originate a V1 trade without a qualifying primary thesis;
- risk is independent and has final veto;
- models never call exchange APIs directly;
- paper/live execution share a narrow interface;
- learning cannot silently modify hard risk limits;
- live execution remains absent/disabled until much later.

---

## 5. Data design

### Tier A — broad universe

Across all discovered perps maintain lightweight metadata/context such as active/delisted state, mark/mid/oracle, volume, funding, open interest, and basic market quality.

### Tier B — ranked watchlist

Maintain richer candle/context data for eligible high-ranked candidates.

### Tier C — deep shortlist

For a bounded dynamic shortlist and any future open positions collect L2 book, public trades, microstructure/execution-quality state, and detailed short-timeframe events.

Persistence direction:

- SQLite for operational state/decisions/risk/orders/fills/positions/journal metadata;
- durable JSONL for liveness-critical normalized event recording;
- offline columnar datasets for replay/research.

Preserve provenance, market identity, exchange timestamp where present, receive timestamp, and schema version.

---

## 6. Strategy and learning direction

Explainable deterministic baselines precede ML control:

- trend
- breakout
- mean reversion
- funding/open-interest context
- order-flow/microstructure context

The deterministic decision layer produces LONG, SHORT, or NO TRADE with reason codes. Evidence scores are bounded deterministic strengths, **not calibrated probabilities**.

Learning later is champion/challenger only:

`versioned data -> offline challenger -> time-aware validation -> untouched OOS -> walk-forward -> mainnet shadow -> compare -> promote only if materially better`

No unconstrained reinforcement-learning agent or model directly controlling leverage/orders in the initial system.

---

## 7. Live-trading gate

Live trading remains disabled until the required evidence exists and the user explicitly authorizes it.

Initial minimum gate:

- at least 500 closed mainnet paper trades under the candidate champion;
- at least 45 calendar days of live-mainnet shadow operation;
- positive net expectancy after modeled fees/funding/slippage;
- positive untouched out-of-sample performance;
- stable walk-forward performance;
- overall profit factor at least 1.20;
- maximum paper drawdown at most 8% under the locked risk model;
- no single market contributes more than 35% of total positive net PnL;
- no single seven-day period contributes more than 50% of total positive net PnL;
- zero unresolved risk-invariant violations;
- restart/recovery/reconciliation tests pass;
- user explicitly chooses capital and authorizes live mode.

Later live runtime should use a dedicated Hyperliquid API/agent wallet. Never put the master-wallet private key in the bot runtime. Live activation must require multiple independent safeguards.

---

## 8. Approved build order

Do not skip phases.

0. Governance/source-of-truth anchor — COMPLETE
1. Python foundation/domain contracts/config/CI — COMPLETE / MERGED
2. Mainnet REST market discovery and normalization — COMPLETE / MERGED
3. WebSocket collector and durable recorder — COMPLETE / MERGED
4. Features, eligibility, scanner, opportunity ranking — COMPLETE / MERGED
5. Explainable baseline strategy engines — IMPLEMENTED + VERIFIED, PR #6 MERGE PENDING
6. Independent risk engine — NEXT AFTER PHASE 5 MERGE
7. Real-mainnet paper execution + position manager
8. Journal + deterministic replay/backtester + offline raw-to-columnar compaction
9. Evaluation/OOS/walk-forward research gates
10. Champion/challenger learning engine
11. Long-running mainnet shadow operation
12. Mainnet live execution adapter built but disabled
13. Explicit user-approved live promotion
14. Evidence-based optimization/scaling

The exact current state is always `docs/STATUS.md`.

---

## 9. Completed engineering state

### Phase 1 — merged

Merge commit: `3efd9e28b84eaa5dcd75f6949d8df02e2928d163`

Established Python 3.12 package structure, mainnet-only/testnet-rejecting config, paper default, typed domain contracts, secret-safe logging, operator status, Ruff/mypy/pytest, and CI.

### Phase 2 — merged

Merge commit: `b95352e238d6a9eabd63e13c1f8300e654a7e636`

Established direct mainnet `/info` access, conservative rate/retry behavior, dynamic native + HIP-3 discovery, namespaced market IDs, immutable Decimal-normalized REST records, candle/funding readers, read-only market operator tooling, and real-mainnet contract fixtures.

### Phase 3 — merged

Merge commit: `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57`  
PR: #3

Established mainnet-only public WebSocket collection and normalization, freshness/reconnect/duplicate/out-of-order handling, dynamic bounded deep-watchlist subscriptions, durable rotating JSONL recording/recovery, stream-smoke tooling, and frozen real-mainnet WebSocket fixtures.

A public-mainnet smoke run processed 1,002 normalized events in five seconds with no observed gaps/duplicates/anomalies/reconnects in that timestamped run. The temporary network workflow was removed before merge.

### Phase 4 — merged

Merge commit: `dae7cf6cf51af9def0a027529d2b0900a6a4d5f6`  
PR: #4

Established immutable versioned feature snapshots, broad funding/OI/volume/return/dislocation features, closed 5m/15m/1h/4h context, volatility/range/relative-volume features, L2 spread/depth/imbalance/age, deterministic trend/volatility regimes, rankability vs deep-readiness gates, distribution-derived eligibility, direction-neutral percentile opportunity ranking, Tier B watchlist/Tier C shortlist, scanner orchestration, and bounded read-only `scan-once` tooling.

The Phase 4 mainnet smoke observation discovered 500 perp markets at that time, produced 500 feature snapshots, marked 320 rankable and 180 rejected, and skipped 0. Those counts/rankings are timestamped observations, not permanent assumptions or profitability evidence.

### Phase 5 — implemented and verified, merge pending

Branch: `phase-5-baseline-strategies`  
PR: #6  
Verified implementation/boundary head: `76bf0df9ab3289eab56213db3c54b2d1c16c6b85`  
Verified CI run: `32660243872` — SUCCESS  
Verified CI job: `97245184233`  
Python: `3.12.14`

Established:

- immutable `StrategySignal`, `StrategyContext`, `MicrostructureWindow`, and `StrategyDecision` contracts;
- `Decimal` strategy/evidence values and deterministic IDs;
- closed-candle lookahead-safe helpers and structural invalidation helpers;
- primary trend engine;
- primary breakout engine using 20 prior closed 15m candles plus a separate trigger candle;
- primary mean-reversion engine restricted to compatible regimes;
- real normalized `TRADE`/`L2_BOOK` microstructure windowing;
- funding/OI context support/veto;
- order-flow context support/veto;
- deterministic regime-aware combiner;
- deterministic five-engine orchestrator;
- boundary tests enforcing no risk/execution/exchange/ML leakage into strategy code.

Phase 5 full verification at the head above:

- editable install — PASS;
- compileall — PASS;
- Ruff — PASS;
- mypy — PASS, no issues in 49 source files;
- pytest — PASS to 100%.

Phase 5 decision behavior is deliberately conservative:

- scanner `rankable` and `deep_ready` are hard gates;
- primary raw score must be at least 60 to qualify;
- primary effective score is fixed regime weight × fixed volatility modifier × raw evidence;
- same-direction qualifying primary agreement adds +5 each, capped +10;
- best opposing primary within 15 effective points causes `NO_TRADE`;
- context can veto the candidate direction;
- non-veto context adjustment is capped to ±10 total;
- final directional threshold is 65;
- lead primary owns the invalidation and invalidation must be on the correct side of reference price;
- context-only evidence cannot originate a trade;
- `NO_TRADE` is a normal result.

Real Phase 3 Hyperliquid mainnet trade/L2 fixtures ground microstructure tests. Candles cannot be accepted as synthetic order-flow history.

The Phase 5 strategy package does **not** import the risk or execution domains, Hyperliquid exchange/wallet/account APIs, or ML libraries. Strategy contracts contain no quantity, leverage, risk-budget, order, wallet, account-equity, margin, or position-size fields.

---

## 10. Fresh-chat continuation instructions

When asked to continue Cocomelon:

1. Treat this file as bootstrap context, not final authority.
2. Inspect `Dtwosam/Cocomelon` with the connected GitHub tools.
3. Read in order:
   - `AGENTS.md`
   - `docs/MASTER_SPEC.md`
   - `docs/DECISIONS.md`
   - `docs/BUILD_ORDER.md`
   - `docs/STATUS.md`
   - active phase spec/plan referenced by status
4. Check recent `main`, open PRs, and current CI.
5. Continue from the exact active task; never rebuild completed phases.
6. Use TDD and small verifiable commits.
7. Handle routine engineering choices, branches, PRs, CI fixes, and guarded merges autonomously.
8. Ask the user only for a genuine decision that cannot be safely derived from the source of truth; real-money activation still needs explicit user authorization.
9. Never claim a phase complete until its verification actually passes.
10. After every phase, update `docs/STATUS.md` and this portable Project Source.
11. If coding against potentially changed Hyperliquid behavior, verify current official documentation first.

---

## 11. Exact handoff now

Phase 5 implementation and boundary auditing are verified on PR #6's branch. The exact pre-continuity-doc verification head is `76bf0df9ab3289eab56213db3c54b2d1c16c6b85`; CI run `32660243872`, job `97245184233`, passed install, compileall, Ruff, mypy, and pytest on Python 3.12.14.

Current required sequence:

1. verify CI on the Phase 5 continuity-document head;
2. re-read PR #6 head and mergeability;
3. merge only with exact expected-head protection;
4. verify `main` contains the Phase 5 merge and no runtime changes were left behind;
5. if needed, make a docs-only closeout update with the actual merge SHA;
6. activate Phase 6 — the independent risk engine.

Do not begin paper execution, ML, or live execution before the build-order gates.

**Live trading status: DISABLED.**
