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

Cocomelon is being built as an autonomous intraday Hyperliquid perp trader. The final system should dynamically discover the real perp universe, reject poor/stale markets, rank opportunities, deeply analyze a bounded shortlist, choose LONG/SHORT/NO_TRADE, pass every directional proposal through an independent risk engine, execute approved trades, manage exits, journal every decision/cost/result, evaluate without lookahead, train offline challengers, and eventually trade real mainnet capital only after evidence gates pass and the user explicitly authorizes live capital.

Economic objective: **positive net risk-adjusted expectancy after fees, funding, slippage, and realistic execution costs**. Profit is never guaranteed.

---

## 2. User operating instruction

The user wants ChatGPT to build this project **from A to Z directly in GitHub** and to handle routine engineering/product decisions, branches, PRs, CI fixes, and guarded merges autonomously. Do not repeatedly ask for approval when the source of truth or best engineering judgment can resolve a choice.

Optimize for durable positive expectancy and capital survival, not trade count, leverage, or headline win rate.

Real-money activation is the exception: live mode and live capital amount require explicit user authorization after the promotion gates pass.

---

## 3. Locked product decisions

### Hyperliquid mainnet only

- Never use Hyperliquid testnet for development, strategy testing, paper trading, or promotion.
- REST/API base: `https://api.hyperliquid.xyz`
- WebSocket: `wss://api.hyperliquid.xyz/ws`
- Runtime config rejects known testnet hosts.

### Mainnet paper/shadow before real money

Paper execution will run internally against real Hyperliquid mainnet observations and must eventually model spread, visible depth/slippage, fees, funding, latency, stop behavior, partial fills where defensible, and execution failures. Never assume perfect fills.

### Intraday V1

Typical intended holding window: roughly **10 minutes to 6 hours**, not a hard timer.

Timeframes:
- 1m execution/microstructure
- 5m short-term confirmation
- 15m main setup
- 1h regime/direction
- 4h higher-timeframe context

V1 is not sub-second HFT or market making.

### Broad universe, bounded deep analysis

`discover all -> eligibility -> broad features -> rank -> dynamic shortlist -> deep features -> strategy -> decision -> risk -> execution`

No hard-coded favorite-token trading universe.

### Locked initial risk model

- planned account risk per trade: **0.25%**
- max aggregate planned open risk: **0.75%**
- daily realized-loss lockout: **1.00%**
- rolling weekly drawdown lockout: **3.00%**
- three consecutive losing trades trigger cooldown
- correlated exposure is constrained
- no averaging down
- no martingale
- no position without stop/invalidation
- stale/inconsistent state blocks new exposure

Leverage is subordinate to the dollar-risk budget.

### Python, not Solidity

Core system is Python. HyperCore perps are accessed through Hyperliquid APIs/SDK. Solidity is out of V1 unless a later genuine HyperEVM contract feature requires it.

### Free/public sources first

Initial build must not depend on paid market-data services. Prefer Hyperliquid public REST/WebSocket APIs and open-source libraries.

### Never fabricate microstructure history

Do not synthesize historical L2/order flow from OHLCV candles. Order-flow research must use real recorded/reliably sourced trade/book events.

### Raw storage

Always-on normalized stream recording is fsynced rotating JSONL. Later replay/research can compact validated JSONL offline into real columnar data such as Parquet.

---

## 4. Architecture and hard boundaries

```text
Hyperliquid Mainnet
  -> REST/WebSocket Data
  -> Durable Recorder / Data Quality
  -> Discovery + Eligibility
  -> Broad Scanner / Ranker
  -> Dynamic Deep Shortlist
  -> Trend / Breakout / Mean Reversion
     + Funding/OI context
     + Order-flow context
  -> Deterministic LONG/SHORT/NO_TRADE Decision
  -> Independent Risk Engine APPROVE/REJECT
  -> Execution Interface
  -> Paper first / Live much later
  -> Position Manager
  -> Journal / Replay
  -> Evaluation / Research
  -> Champion / Challenger ML
```

Hard boundaries:
- scanner rank is attention priority, not directional evidence;
- strategy may propose direction/invalidation but cannot size positions or send orders;
- context engines cannot originate a V1 trade without a primary thesis;
- risk is independent and has final veto;
- models never call exchange APIs directly;
- learning cannot silently change hard risk limits;
- live trading remains disabled until much later.

---

## 5. Approved build order

0. Governance/source-of-truth anchor — COMPLETE
1. Python foundation/domain/config/CI — COMPLETE / MERGED
2. Mainnet REST discovery/normalization — COMPLETE / MERGED
3. WebSocket collector/durable recorder — COMPLETE / MERGED
4. Features/eligibility/scanner/ranking — COMPLETE / MERGED
5. Explainable baseline strategy engines — COMPLETE / MERGED
6. Independent risk engine — **ACTIVE NEXT**
7. Real-mainnet paper execution + position manager
8. Journal + deterministic replay/backtester + offline raw-to-columnar compaction
9. Evaluation/OOS/walk-forward research gates
10. Champion/challenger learning engine
11. Long-running mainnet shadow
12. Mainnet live adapter built but disabled
13. Explicit user-approved live promotion
14. Evidence-based optimization/scaling

`docs/STATUS.md` is the exact current state.

---

## 6. Completed engineering state

### Phase 1 — merged
Merge commit: `3efd9e28b84eaa5dcd75f6949d8df02e2928d163`

Python 3.12 structure, mainnet-only/testnet-rejecting config, paper default, typed domain contracts, secret-safe logging, operator status, Ruff/mypy/pytest, CI.

### Phase 2 — merged
Merge commit: `b95352e238d6a9eabd63e13c1f8300e654a7e636`

Direct mainnet `/info`, conservative rate/retry, dynamic native + HIP-3 discovery, namespaced market IDs, immutable Decimal-normalized REST records, candle/funding readers, read-only market tooling, real-mainnet fixtures.

### Phase 3 — merged
Merge commit: `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57`  
PR: #3

Mainnet-only public WebSocket normalization, freshness/reconnect/duplicate/out-of-order handling, bounded dynamic deep-watchlist subscriptions, durable rotating JSONL recovery, real-mainnet WebSocket fixtures.

### Phase 4 — merged
Merge commit: `dae7cf6cf51af9def0a027529d2b0900a6a4d5f6`  
PR: #4

Immutable versioned feature snapshots; funding/OI/volume/returns/dislocation; 5m/15m/1h/4h context; volatility/range/relative-volume; L2 spread/depth/imbalance/age; deterministic regimes; rankability vs deep-readiness; distribution-derived eligibility; direction-neutral percentile ranking; Tier B watchlist/Tier C shortlist; broad-to-deep scanner orchestration.

### Phase 5 — merged
Merge commit: `82c3db2f9ce39676e089eac79e63c5043b72e331`  
PR: #6  
Final PR head: `7e70c70fcde325fd0b19d19cbaa346b7cec7de41`  
Final PR-head CI: `32660385058` — SUCCESS  
CI job: `97245537563`  
Python: `3.12.14`

Established:
- immutable `StrategySignal`, `StrategyContext`, `MicrostructureWindow`, `StrategyDecision`;
- Decimal evidence values and deterministic IDs;
- lookahead-safe closed-candle/reference/invalidation helpers;
- primary trend engine;
- primary breakout engine using 20 prior closed 15m candles plus a separate trigger;
- primary mean-reversion engine restricted to compatible regimes;
- real normalized `TRADE`/`L2_BOOK` microstructure window;
- funding/OI context support/veto;
- real order-flow context support/veto;
- deterministic regime-aware combiner;
- deterministic five-engine orchestrator;
- boundary tests enforcing no risk/execution/exchange/ML leakage.

Final Phase 5 CI passed editable install, compileall, Ruff, mypy, and full pytest. A separate boundary-audit head `76bf0df9ab3289eab56213db3c54b2d1c16c6b85` also passed CI run `32660243872`, job `97245184233`, with mypy clean across 49 source files and pytest at 100%.

PR #6 was merged only with exact expected-head protection. `main` was immediately verified at merge SHA `82c3db2f9ce39676e089eac79e63c5043b72e331`. Comparing `main` to the Phase 5 feature branch showed ahead-by 0 for the feature branch and an empty file diff, proving no runtime work was left unmerged.

### Phase 5 decision behavior

- `rankable` and `deep_ready` are hard gates;
- primary raw evidence must be >=60 to qualify;
- fixed regime and volatility weights modify primary evidence;
- same-direction primary agreement adds +5 each, capped +10;
- opposing primary within 15 effective points yields `NO_TRADE`;
- context may veto candidate direction;
- non-veto context adjustment is capped ±10;
- final directional threshold is 65;
- lead primary owns invalidation and it must be on the correct side of reference price;
- context-only evidence cannot originate a trade;
- `NO_TRADE` is first-class.

Real frozen Phase 3 Hyperliquid mainnet trade/L2 fixtures ground microstructure tests. Candles cannot be accepted as fake order-flow history.

---

## 7. Phase 6 — active objective

Phase 6 builds the **independent risk engine** between strategy decisions and any future execution layer. Strategy output remains a proposal until risk approves it.

Phase 6 must design and implement, at minimum:
- 0.25% planned risk-per-trade sizing from equity and stop distance;
- 0.75% aggregate planned open-risk cap;
- 1% daily realized-loss lockout;
- 3% rolling weekly drawdown lockout;
- cooldown after three consecutive losses;
- correlated-exposure restrictions;
- leverage and liquidation-buffer constraints subordinate to dollar risk;
- liquidity/depth/slippage constraints on allowed notional;
- stale/inconsistent-state rejection;
- no averaging down or martingale;
- deterministic approve/reject outcomes with reason codes and auditability;
- no exchange order placement inside risk code.

Do **not** begin Phase 7 paper execution, position management, ML, or live execution early.

---

## 8. Live-trading gate

Live trading remains disabled until evidence exists and the user explicitly authorizes capital.

Initial minimum gate remains:
- >=500 closed mainnet paper trades under candidate champion;
- >=45 calendar days mainnet shadow;
- positive net expectancy after modeled costs;
- positive untouched OOS;
- stable walk-forward;
- profit factor >=1.20;
- max paper drawdown <=8% under locked risk;
- no single market >35% of positive net PnL;
- no single seven-day period >50% of positive net PnL;
- zero unresolved risk-invariant violations;
- restart/recovery/reconciliation tests pass;
- user explicitly chooses capital and authorizes live mode.

Future live runtime should use a dedicated Hyperliquid API/agent wallet, never the master-wallet private key.

---

## 9. Fresh-chat continuation instructions

When asked to continue Cocomelon:
1. Treat this file as bootstrap context, not final authority.
2. Inspect `Dtwosam/Cocomelon` with connected GitHub tools.
3. Read `AGENTS.md`, `docs/MASTER_SPEC.md`, `docs/DECISIONS.md`, `docs/BUILD_ORDER.md`, `docs/STATUS.md`, then the active phase spec/plan.
4. Check recent `main`, open PRs, and CI.
5. Continue from the exact active task; never rebuild completed phases.
6. Use the required design/spec workflow before each new implementation phase, then TDD and small verifiable commits.
7. Handle routine choices/branches/PRs/CI/guarded merges autonomously.
8. Ask the user only for genuinely non-derivable decisions; live-money activation still requires explicit user authorization.
9. Never claim completion without fresh verification evidence.
10. Update `docs/STATUS.md` and this portable source after every phase.
11. Verify current official Hyperliquid docs before coding against potentially changed external behavior.

---

## 10. Exact handoff now

Phase 5 is merged into `main` at `82c3db2f9ce39676e089eac79e63c5043b72e331`. A docs-only closeout branch records the actual merge metadata and activates Phase 6.

Next implementation sequence:
1. complete/merge the Phase 5 docs-only closeout after its CI passes;
2. treat Phase 6 — independent risk engine — as active;
3. read authoritative repository governance/spec/build-order/status and existing risk-domain code/tests;
4. run the required Phase 6 design/spec workflow;
5. create the Phase 6 implementation plan;
6. implement with TDD on an isolated branch;
7. keep paper execution, ML, and live execution out of Phase 6.

**Live trading status: DISABLED.**
