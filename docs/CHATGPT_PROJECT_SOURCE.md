# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing the Cocomelon build across ChatGPT chats. The live GitHub repository is authoritative.  
**Repository:** `Dtwosam/Cocomelon`  
**Project:** Autonomous Hyperliquid perpetual-futures trading system  
**Primary language:** Python 3.12  
**Target venue:** Hyperliquid HyperCore perpetual markets  
**Execution mode now:** research + mainnet observation + bounded internal paper execution work; live trading disabled  
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

### Mainnet paper/shadow before real capital

Paper execution runs internally against real Hyperliquid mainnet observations and must model spread, visible depth/slippage, fees, funding, latency, stop behavior, partial fills where defensible, and execution failures. Never assume perfect fills.

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

### Locked risk model

Core locked limits:
- planned account risk per trade: **0.25%**
- max aggregate planned open risk: **0.75%**
- daily realized-loss lockout: **1.00%**
- rolling weekly drawdown lockout: **3.00%**
- three consecutive losses -> **60-minute cooldown**
- correlation-bucket planned-risk cap: **0.50%**
- gross system leverage ceiling: **3x** or lower venue maximum
- new exposure may consume at most **50%** of currently available margin after effective leverage
- new notional may consume at most **10%** of the weaker visible 25-bps side depth
- liquidation must be beyond the stop and at least **2x stop distance**
- no averaging down
- no martingale/loss-recovery sizing
- no position without stop/invalidation
- stale/inconsistent state blocks new exposure

Leverage is subordinate to the dollar-risk budget. Strategy score never scales the risk percentage upward.

Authoritative risk arithmetic uses a fixed 28-digit Decimal context. Risk-budget-to-notional division rounds downward so repeating Decimal quotients cannot exceed the approved budget by a rounding unit.

### Python, not Solidity

Core system is Python. HyperCore perps are accessed through Hyperliquid APIs/SDK. Solidity is out of V1 unless a later genuine HyperEVM contract feature requires it.

### Free/public sources first

Initial build must not depend on paid market-data services. Prefer Hyperliquid public REST/WebSocket APIs and open-source libraries.

### Never fabricate microstructure history

Do not synthesize historical L2/order flow from OHLCV candles. Order-flow research must use real recorded/reliably sourced trade/book events.

### Raw storage

Always-on normalized stream recording is fsynced rotating JSONL. Later replay/research compacts validated JSONL offline into real columnar data such as Parquet.

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
- Phase 7 may execute **less** than approved but may never exceed the Phase 6 approved notional/risk envelope without a fresh risk decision;
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
6. Independent risk engine — COMPLETE / MERGED
7. Real-mainnet paper execution + position manager — **ACTIVE NEXT**
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

Established immutable strategy contracts, lookahead-safe helpers, primary trend/breakout/mean-reversion engines, real trade/L2 microstructure windows, funding/OI and order-flow context, deterministic regime-aware LONG/SHORT/NO_TRADE combination, orchestration, and boundary tests excluding risk/execution/exchange/ML leakage.

### Phase 6 — merged
Merge commit: `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912`  
PR: #8  
Final feature head: `09a7fc7c3ed611d700905081cb2b606d52b558d4`  
Final CI: `32663669112` — SUCCESS  
CI job: `97253567901`  
Python: `3.12.14`

Established:
- immutable Decimal risk/account/liquidity/health/request/decision contracts;
- deterministic approval IDs and stable reason/binding-cap ordering;
- cost-aware 0.25% risk sizing including entry slippage, stop slippage, and round-trip fees;
- 0.75% aggregate planned-open-risk cap;
- 0.50% correlation-bucket cap with no default long/short netting;
- 1% daily realized-loss lockout;
- 3% rolling weekly drawdown lockout;
- same-market exposure veto;
- three-loss / 60-minute cooldown;
- 3x/lower-venue gross leverage cap;
- 50%-available-margin cap;
- 10%-weak-side-visible-depth cap;
- liquidation beyond-stop and 2x-distance safety;
- venue-minimum rejection without forced upsizing;
- fixed 28-digit authoritative Decimal context;
- downward risk-to-notional rounding;
- boundary tests excluding order, wallet, account-exchange, fill simulation, averaging-down, martingale, ML, and live capability.

Late audit regressions caught and fixed before merge:
1. a one-ulp repeating-Decimal risk-budget overshoot;
2. dependence on ambient Decimal precision/rounding.

The final full install/compileall/Ruff/mypy/pytest suite passed. PR #8 merged with expected-head protection. `main` was verified at `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912`; comparing `main` to `phase-6-independent-risk` showed branch ahead-by 0 and an empty file diff.

---

## 7. Phase 7 — active objective

Phase 7 builds **real-mainnet paper execution and position management** while treating the Phase 6 risk approval as a hard upper bound.

Required design/implementation themes:
- one execution interface that paper implements now and live may implement much later;
- immutable deterministic execution records: order plan/attempt/fill/position state/lifecycle actions;
- translate approved notional into venue-valid quantity using actual instrument sizing/minimum rules;
- consume real Hyperliquid mainnet L2/trade observations only;
- model spread, visible-depth impact/slippage, latency, fees, partial fills where defensible, and explicit execution failures;
- never assume perfect fills;
- never execute more notional/risk than Phase 6 approved;
- support LONG and SHORT entries and reduce-only exits;
- stop/invalidation and bounded intraday position management cannot widen risk;
- deterministic/restart-friendly account and position state;
- fills must be auditable/replayable from recorded market evidence;
- no signing, wallet/private key, exchange account API, transfer, withdrawal, or live order submission in the paper adapter.

Do not begin Phase 8 backtesting/journaling, Phase 10 ML, or Phase 12 live adapter early except for narrow interfaces strictly required by Phase 7.

Before coding against Hyperliquid order/instrument behavior, verify current official mainnet documentation because external rules may change.

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

Phase 6 is merged into `main` at `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912`. Continuity docs activate Phase 7.

Next sequence:
1. treat Phase 7 — real-mainnet paper execution + position manager — as active;
2. inspect authoritative governance/build-order/current domain and stream/risk contracts;
3. verify current official Hyperliquid mainnet instrument sizing/order semantics/public fee behavior relevant to paper modeling;
4. run the Phase 7 design/spec workflow;
5. write the Phase 7 implementation plan;
6. implement with TDD on an isolated branch;
7. keep signing, wallet/account private APIs, real orders, ML, and live execution out of Phase 7.

**Live trading status: DISABLED.**
