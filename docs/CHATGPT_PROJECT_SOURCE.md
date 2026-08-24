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

Cocomelon is an autonomous intraday Hyperliquid perpetual-futures trader under staged development. It dynamically discovers the real perp universe, rejects poor/stale markets, ranks opportunities, deeply analyzes a bounded shortlist, chooses LONG/SHORT/NO_TRADE, passes every directional proposal through an independent risk engine, paper-executes approved trades against real mainnet observations, manages positions, journals/replays outcomes without lookahead, evaluates out of sample, later trains offline challengers, and can only reach real-money trading after evidence gates pass and the user explicitly authorizes capital.

Economic objective: **positive net risk-adjusted expectancy after fees, funding, slippage, and realistic execution costs while preserving capital**. Profit is never guaranteed.

---

## 2. Operating instruction

Build directly in GitHub and handle routine architecture, implementation, tests, branches, PRs, CI fixes, reviews, and guarded merge decisions autonomously. Do not repeatedly ask for approval when repository evidence, locked specifications, or sound engineering judgment resolves a routine choice.

Real-money activation is the permanent exception: no live mode or real-capital order placement without explicit user authorization after later promotion gates pass.

---

## 3. Locked product decisions

### Hyperliquid mainnet only

- Hyperliquid testnet is forbidden at every stage.
- REST market-data base: `https://api.hyperliquid.xyz`
- WebSocket market-data base: `wss://api.hyperliquid.xyz/ws`
- Runtime configuration rejects known testnet hosts.

### Mainnet paper/shadow before real capital

Paper execution observes real Hyperliquid mainnet data but places no exchange orders. It models visible-book fills, spread/slippage, fees, funding, latency, partial/no-fill outcomes, and stop execution without assuming perfect fills.

### Intraday V1

Typical intended holding window is roughly 10 minutes to 6 hours, not a forced timer. The context stack is 1m execution/microstructure, 5m confirmation, 15m setup, 1h regime/direction, and 4h higher-timeframe context. V1 is not sub-second HFT or market making.

### Broad universe, bounded deep analysis

`discover all -> eligibility -> broad features -> rank -> dynamic shortlist -> deep features -> strategy -> decision -> risk -> execution`

No fixed favorite-token universe. Eligibility is mechanically separate from ranking.

### Locked risk model

- planned account risk per trade: **0.25%**
- max aggregate planned open risk: **0.75%**
- daily realized-loss lockout: **1.00%**
- rolling weekly drawdown lockout: **3.00%**
- three consecutive losing trades -> **60-minute cooldown**
- correlation-bucket planned-risk cap: **0.50%**
- gross system leverage ceiling: **3x** or lower venue maximum
- new exposure may consume at most **50%** of currently available margin after effective leverage
- new notional may consume at most **10%** of the weaker visible 25-bps side depth
- liquidation must be beyond the stop and at least **2x stop distance**
- no averaging down
- no martingale/loss-recovery sizing
- no position without stop/invalidation
- stale/inconsistent state blocks new exposure

Leverage is subordinate to dollar risk. Strategy score cannot scale the risk percentage upward. Authoritative risk arithmetic uses fixed 28-digit Decimal semantics and downward risk-budget-to-notional rounding.

### Deterministic baselines before ML

Explainable deterministic strategies remain the first-class baseline. `NO_TRADE` is valid. Phase 10 ML remains downstream of Phase 9 evidence gates and may never silently change hard risk limits.

### Never fabricate microstructure

Historical L2/order-flow evidence may only come from genuinely recorded/trusted book or trade observations. Candles can never be converted into synthetic L2/order flow.

### Storage boundary

Always-on normalized streaming evidence is durable fsynced JSONL. Phase 8 validates immutable JSONL and can compact it offline into genuine Parquet behind an optional research dependency while preserving source hashes/provenance. SQLite is for lower-volume operational/journal metadata.

---

## 4. Architecture and hard boundaries

```text
Hyperliquid Mainnet
  -> REST/WebSocket Data
  -> Durable Recorder / Data Quality
  -> Discovery + Eligibility
  -> Broad Scanner / Ranker
  -> Dynamic Deep Shortlist
  -> Deterministic Strategy Context
  -> LONG / SHORT / NO_TRADE
  -> Independent Risk APPROVE / REJECT
  -> Narrow Execution Interface
  -> Paper First / Live Much Later
  -> Position Manager
  -> Journal / Deterministic Replay
  -> Evaluation / OOS / Walk-Forward
  -> Champion / Challenger Learning
```

Hard boundaries:

- scanner rank is attention priority, not directional evidence;
- strategy can propose direction/invalidation but cannot size positions or send orders;
- context engines cannot originate a V1 trade without a primary thesis;
- risk is independent and has final veto;
- execution may use less than an approval but never more without a fresh risk decision;
- replay preserves evidence classes and cannot fabricate microstructure;
- replay uses evidence availability time and cannot expose future evidence early;
- models never call exchange APIs directly;
- learning cannot silently change hard risk limits;
- live trading remains disabled until later gates and explicit user authorization.

---

## 5. Approved build order

0. Governance/source-of-truth anchor — COMPLETE
1. Python foundation/domain/config/CI — MERGED
2. Mainnet REST discovery/normalization — MERGED
3. WebSocket collector/durable recorder — MERGED
4. Features/eligibility/scanner/ranking — MERGED
5. Explainable baseline strategies — MERGED
6. Independent risk engine — MERGED
7. Real-mainnet paper execution + position manager — MERGED
8. Journal + deterministic replay/backtester + offline analytical compaction — **MERGED**
9. Evaluation/OOS/walk-forward research gates — **ACTIVE DESIGN/SPEC**
10. Champion/challenger learning engine
11. Long-running mainnet shadow
12. Mainnet live adapter built but disabled
13. Explicit user-approved live promotion
14. Evidence-based optimization/scaling

`docs/STATUS.md` is the exact current state.

---

## 6. Merge history

- Phase 1: `3efd9e28b84eaa5dcd75f6949d8df02e2928d163`
- Phase 2: `b95352e238d6a9eabd63e13c1f8300e654a7e636`
- Phase 3: `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57` — PR #3
- Phase 4: `dae7cf6cf51af9def0a027529d2b0900a6a4d5f6` — PR #4
- Phase 5: `82c3db2f9ce39676e089eac79e63c5043b72e331` — PR #6
- Phase 6: `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912` — PR #8
- Phase 7: `5cd4b3603cf05d2e5dc2cc3a165c026a01b2fcab` — PR #9
- Phase 8: `f7f37044997e13b3ffe91edd312756862343782b` — PR #10

---

## 7. Phase 8 final evidence

**Final PR head:** `83454520fa652533c47688f6ab14c0d1fb19473f`  
**Merge:** `f7f37044997e13b3ffe91edd312756862343782b`  
**Final PR-head CI:** `32713492047` — SUCCESS  
**Core job:** `97389733152` — SUCCESS  
**Research job:** `97389733315` — SUCCESS  
**Python:** `3.12.14`

The exact PR head passed editable `[dev]` install, compileall, Ruff, mypy, full pytest, `[dev,research]` install, and dedicated Parquet compaction/replay tests. PR #10 had no comments/review threads, was mergeable, and was not behind `main`. Merge used expected-head SHA protection. `main` was immediately verified at the returned merge SHA, and comparing the feature branch to `main` showed only the merge commit with an empty file diff.

Phase 8 established:

- deterministic journal/replay contracts and semantic IDs;
- exact JSONL source hashing/validation and immutable source evidence;
- frozen replay manifests with code/config/data/schema/version provenance;
- explicit availability-time replay clock and lookahead protection;
- `CANDLE_CONTEXT` vs `MICROSTRUCTURE` evidence separation;
- restart-safe journal SQLite with conflict detection and atomic writes;
- lifecycle reconciliation through strategy/risk/plan/attempt/fill/action/funding/account state;
- gross/net PnL, fees, funding, net R, holding duration, signed slippage amounts/fractions, quantity-aware MFE/MAE;
- per-exit-plan slippage references for partial exits;
- deterministic Phase 5->8 LONG/SHORT replay plus NO_TRADE/risk-reject/no-fill zero-exposure coverage;
- optional PyArrow Parquet compaction behind the research extra only;
- JSONL/Parquet canonical replay equivalence and corruption/hash rejection;
- offline validation/compaction/replay/journal-inspection commands;
- executable boundaries excluding testnet, replay live/network exchange capability, wallet/signing/transfer/withdrawal/private account paths, ML optimization leakage, and candle-to-book fabrication.

---

## 8. Phase 7 paper-simulator assumptions retained

These are versioned simulation/control assumptions rather than optimal-policy claims:

- native validator-operated Hyperliquid perps for execution; HIP-3 remains observable/rankable but Phase 7 paper execution support remains separately gated;
- deterministic latency: 250 ms;
- maximum accepted L2 age: 1,000 ms;
- maximum public asset-context age: 5,000 ms;
- funding reconciliation grace: 300,000 ms;
- IOC slippage guard: 25 bps;
- native-perp baseline taker fee: `Decimal("0.00045")` with versioned schedule;
- native-perp minimum notional baseline: `Decimal("10")`;
- paper gross leverage ceiling: 3x or lower venue maximum;
- only displayed normalized L2 depth may fill;
- no passive maker fills/rebates;
- actual entry rechecks the inherited Phase 6 risk envelope;
- funding uses real public funding history plus lookahead-safe public oracle context;
- stale/inconsistent execution/account/funding state blocks new exposure while safe exits remain possible with usable public data.

---

## 9. Phase 9 active objective

Phase 9 must evaluate deterministic Phase 8 outputs rigorously before any learning engine or promotion. It should define reproducible research results and fail-closed evidence gates rather than tune for attractive backtests.

Required themes:

- cost-aware trade/portfolio statistics from valid Phase 8 journals;
- frozen untouched out-of-sample partitions;
- walk-forward evaluation with explicit train/calibration/evaluation windows and no future leakage;
- regime, market, time-period, drawdown and concentration diagnostics;
- stability/sensitivity analysis that detects parameter fragility without test-set optimization;
- minimum sample-size and evidence-quality requirements before metrics are research-ready;
- reproducible evaluation manifests/results tied to exact dataset/code/config provenance;
- promotion/rejection gates that preserve `NO_TRADE` and capital protection;
- strict separation from Phase 10 ML/champion-challenger training.

Do not begin Phase 10+, live-adapter construction, or real-money execution early.

---

## 10. Live-trading gate

Live trading remains disabled. A later promotion path must require substantial mainnet paper/shadow evidence, positive net expectancy after realistic costs, untouched OOS and walk-forward stability, bounded drawdown/concentration, no unresolved risk invariants, restart/reconciliation reliability, and finally explicit user authorization of live mode and capital.

Future live runtime should use a dedicated Hyperliquid API/agent wallet, never a master-wallet private key.

---

## 11. Fresh-chat continuation instructions

When asked to continue Cocomelon:

1. Treat this file as bootstrap context; the live repository is stronger authority.
2. Inspect `Dtwosam/Cocomelon` with connected GitHub tools.
3. Read `AGENTS.md`, `docs/MASTER_SPEC.md`, `docs/DECISIONS.md`, `docs/BUILD_ORDER.md`, `docs/STATUS.md`, then the active phase spec/plan.
4. Check `main`, open PRs, branch/compare state, review threads, and exact-head CI.
5. Continue from the precise active task; never rebuild merged phases.
6. Use design/spec -> detailed TDD plan -> implementation -> verification -> guarded integration for every new phase.
7. Handle routine engineering/product/CI/PR/merge decisions autonomously.
8. Ask only for genuinely non-derivable decisions; real-money activation always requires explicit user authorization.
9. Never claim completion without fresh verification evidence for the exact tree/head being discussed.
10. Update `docs/STATUS.md` and this portable source after every phase.
11. Verify current official Hyperliquid documentation before implementing behavior dependent on potentially changed venue semantics.

---

## 12. Exact handoff now

Phase 8 is merged into `main` at `f7f37044997e13b3ffe91edd312756862343782b`. Post-merge continuity docs are being reconciled on `main`; their push CI must remain green.

Immediate sequence:

1. verify the post-merge continuity-doc push CI;
2. re-read governance/build-order/master-spec decisions relevant to evaluation and promotion;
3. inspect Phase 8 journal/replay result contracts as the Phase 9 input boundary;
4. write the Phase 9 evaluation/OOS/walk-forward design spec;
5. write the Phase 9 detailed TDD implementation plan;
6. implement Phase 9 on an isolated feature branch after the spec/plan are coherent;
7. keep Phase 10+ and live trading deferred.

**Live trading status: DISABLED.**
