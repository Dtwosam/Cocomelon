# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing the Cocomelon build across ChatGPT chats. The live GitHub repository is authoritative.  
**Repository:** `Dtwosam/Cocomelon`  
**Project:** Autonomous Hyperliquid perpetual-futures trading system  
**Primary language:** Python 3.12  
**Target venue:** Hyperliquid HyperCore perpetual markets  
**Execution mode now:** real-mainnet observation + bounded internal paper execution; live trading disabled  
**Hyperliquid testnet:** NEVER USE

---

## 1. Mission

Cocomelon is being built as an autonomous intraday Hyperliquid perp trader. The intended system dynamically discovers the real perp universe, rejects poor/stale markets, ranks opportunities, deeply analyzes a bounded shortlist, chooses LONG/SHORT/NO_TRADE, passes every directional proposal through an independent risk engine, executes approved trades, manages exits, journals every decision/cost/result, evaluates without lookahead, trains offline challengers, and eventually trades real mainnet capital only after evidence gates pass and the user explicitly authorizes live capital.

Economic objective: **positive net risk-adjusted expectancy after fees, funding, slippage, and realistic execution costs**. Profit is never guaranteed.

---

## 2. Operating instruction

Build the project from A to Z directly in GitHub and handle routine engineering/product decisions, branches, PRs, CI fixes, and guarded merges autonomously. Do not repeatedly ask for approval when the source of truth or sound engineering judgment resolves a choice.

Optimize for durable positive expectancy and capital survival, not trade count, leverage, or headline win rate.

Real-money activation is the exception: live mode and live capital amount require explicit user authorization after promotion gates pass.

---

## 3. Locked product decisions

### Hyperliquid mainnet only

- Never use Hyperliquid testnet for development, strategy testing, paper trading, or promotion.
- REST/API base: `https://api.hyperliquid.xyz`
- WebSocket: `wss://api.hyperliquid.xyz/ws`
- Runtime config rejects known testnet hosts.

### Mainnet paper/shadow before real capital

Paper execution runs internally against real Hyperliquid mainnet observations and models spread, visible depth/slippage, fees, funding, latency, stop behavior, partial fills where defensible, and execution failures. Never assume perfect fills.

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

Leverage is subordinate to dollar risk. Strategy score never scales the risk percentage upward. Authoritative risk arithmetic uses a fixed 28-digit Decimal context and risk-budget-to-notional division rounds downward.

### Python, not Solidity

Core system is Python. Solidity is outside V1 unless a later real HyperEVM requirement genuinely appears.

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
  -> Narrow Execution Interface
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
- execution may use less than approved but may never exceed the Phase 6 approved risk/notional envelope without a fresh decision;
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
7. Real-mainnet paper execution + position manager — **VERIFIED; PR #9 guarded merge closeout**
8. Journal + deterministic replay/backtester + offline raw-to-columnar compaction — NEXT AFTER PHASE 7 MERGE
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

Immutable strategy contracts, lookahead-safe helpers, primary trend/breakout/mean-reversion engines, real trade/L2 microstructure windows, funding/OI and order-flow context, deterministic regime-aware LONG/SHORT/NO_TRADE combination, orchestration, and boundary tests excluding risk/execution/exchange/ML leakage.

### Phase 6 — merged
Merge commit: `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912`  
PR: #8  
Final feature head: `09a7fc7c3ed611d700905081cb2b606d52b558d4`  
Final CI: `32663669112` — SUCCESS  
CI job: `97253567901`

Established immutable Decimal risk/account/liquidity/health/request/decision contracts; deterministic IDs; cost-aware 0.25% sizing; aggregate/correlation/daily/weekly/cooldown caps; same-market veto; leverage/margin/liquidity/liquidation limits; venue-minimum rejection without upsizing; fixed Decimal context; downward risk-to-notional rounding; source-level boundary tests.

### Phase 7 — verified on PR #9, merge closeout in progress

Branch: `phase-7-paper-execution`  
Verified implementation head before continuity-doc closeout: `6dabbd43e4333801ef797248117adc0b6dbfc660`  
Verified CI: `32667371201` — SUCCESS  
CI job: `97262807933`  
Python: `3.12.14`

Established:

- immutable Decimal paper execution contracts and deterministic lifecycle IDs;
- native-perp opening planner with exact size precision/minimum checks and 250 ms deterministic latency;
- exact carry-forward of Phase 6 approved risk/notional and stop/effective-loss envelope;
- public-only `activeAssetCtx` stream normalization and deep-watchlist subscription;
- visible-mainnet-L2 marketable IOC simulator with full/partial/no-fill outcomes, 25-bps guard, fee charging, no hidden liquidity, and safe final-level clipping to both Phase 6 ceilings;
- LONG/SHORT paper position/account state, weighted entries, realized/unrealized PnL, fees/funding, gross notional, conservative margin, daily realized PnL, rolling seven-day peak, loss streak, and Phase 6 account adapter;
- actual-public-evidence funding reconciliation with pre-boundary oracle context and unresolved-gap fail-closed behavior;
- deterministic emergency/stop/thesis/tighter-stop/reduction/HOLD position manager;
- reduce-only exits through the same IOC path, with no fill awarded at the stop price;
- atomic/idempotent SQLite operational state and restart reconciliation;
- narrow `TradingExecution` protocol and `PaperExecutionAdapter` with no generic private client escape hatch;
- Phase 5 -> Phase 6 -> Phase 7 LONG/SHORT/NO_TRADE integration coverage;
- explicit boundary tests excluding real order submission, wallet/private-key signing, transfer/withdrawal, private user/account subscription, testnet, passive-maker/candle fill fabrication, and ML.

Verification at `6dabbd43e4333801ef797248117adc0b6dbfc660`:
- editable install PASS;
- compileall PASS;
- Ruff PASS;
- mypy PASS across 67 source files;
- full pytest PASS to 100%;
- PR #9 has no inline review threads.

---

## 7. Phase 7 execution assumptions locked for the current simulator

These are versioned simulation/control assumptions, not claims of optimal venue policy:

- native validator-operated Hyperliquid perps only (`MarketId.dex == ""`) for execution;
- HIP-3 remains observable/rankable but unsupported for Phase 7 execution until separately validated;
- deterministic latency: 250 ms;
- max accepted L2 age: 1,000 ms;
- max public asset-context age: 5,000 ms;
- funding reconciliation grace: 300,000 ms;
- IOC slippage guard: 25 bps;
- native-perp baseline taker fee: `Decimal("0.00045")` with versioned schedule ID;
- native-perp minimum notional baseline: `Decimal("10")`;
- paper gross leverage ceiling: 3x or lower venue maximum;
- only displayed normalized L2 depth may fill;
- no passive maker fills/rebates;
- actual entry price rechecks the original Phase 6 envelope using inherited cost buffer;
- funding uses actual public funding history + lookahead-safe public oracle context;
- stale/inconsistent execution/account/funding state blocks new exposure while safe exit attempts remain allowed when usable public data exists.

---

## 8. Live-trading gate

Live trading remains disabled until evidence exists and the user explicitly authorizes capital.

Initial minimum gate:
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

Phase 7 implementation is verified on PR #9. The remaining closeout sequence is:

1. run CI on the continuity-doc closeout head;
2. re-check PR #9 diff/review threads/mergeability;
3. mark PR ready only if green;
4. merge with expected-head SHA protection;
5. verify `main` at the returned merge SHA and compare branch vs `main`;
6. reconcile merge metadata in continuity docs if necessary;
7. activate the Phase 8 design/spec workflow for journal/replay/deterministic backtesting and offline raw-to-columnar compaction.

Do not begin Phase 9+ early.

**Live trading status: DISABLED.**