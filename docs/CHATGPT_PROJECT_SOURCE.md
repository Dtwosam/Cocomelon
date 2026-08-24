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

Cocomelon is an autonomous intraday Hyperliquid perpetual-futures trader under staged development. The intended system dynamically discovers the real perp universe, rejects poor/stale markets, ranks opportunities, deeply analyzes a bounded shortlist, chooses LONG/SHORT/NO_TRADE, passes every directional proposal through an independent risk engine, paper-executes approved trades against real mainnet observations, manages positions, journals/replays outcomes without lookahead, evaluates out of sample, later trains offline challengers, and can only reach real-money live trading after evidence gates pass and the user explicitly authorizes capital.

Economic objective: **positive net risk-adjusted expectancy after fees, funding, slippage, and realistic execution costs while preserving capital**. Profit is never guaranteed.

---

## 2. Operating instruction

Build directly in GitHub and handle routine architecture, implementation, tests, branches, PRs, CI fixes, reviews, and guarded merge decisions autonomously. Do not repeatedly ask for approval when repository evidence, the locked specification, or sound engineering judgment resolves a routine choice.

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

Typical intended holding window is roughly 10 minutes to 6 hours, not a forced timer. The main context stack is 1m execution/microstructure, 5m confirmation, 15m setup, 1h regime/direction, and 4h higher-timeframe context. V1 is not sub-second HFT or market making.

### Broad universe, bounded deep analysis

`discover all -> eligibility -> broad features -> rank -> dynamic shortlist -> deep features -> strategy -> decision -> risk -> execution`

No fixed favorite-token trading universe. Eligibility is mechanically separate from ranking.

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

Leverage is subordinate to dollar risk. Strategy score cannot scale the risk percentage upward. Authoritative risk arithmetic uses a fixed 28-digit Decimal context and risk-budget-to-notional division rounds downward.

### Deterministic baselines before ML

Explainable deterministic strategies are the first-class decision baseline. `NO_TRADE` is a valid first-class outcome. Phase 10 ML must remain downstream of evidence/evaluation gates and may never silently change hard risk limits.

### Never fabricate microstructure

Historical L2/order-flow evidence may only come from genuinely recorded or trusted trade/book observations. Candles can never be converted into synthetic L2 or order flow.

### Storage boundary

Always-on normalized streaming evidence is durable fsynced JSONL. Phase 8 validates immutable JSONL and may compact it offline into genuine Parquet behind an optional research dependency while preserving hashes and provenance. SQLite is for lower-volume operational/journal metadata, not high-volume synthetic market history.

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
- replay uses evidence availability time, not future/exchange timestamps for early access;
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
8. Journal + deterministic replay/backtester + offline analytical compaction — **IMPLEMENTATION COMPLETE / PR CLOSEOUT**
9. Evaluation/OOS/walk-forward research gates — DEFERRED UNTIL PHASE 8 MERGE
10. Champion/challenger learning engine
11. Long-running mainnet shadow
12. Mainnet live adapter built but disabled
13. Explicit user-approved live promotion
14. Evidence-based optimization/scaling

`docs/STATUS.md` is the exact current state.

---

## 6. Completed engineering state

### Phase 1
Merge: `3efd9e28b84eaa5dcd75f6949d8df02e2928d163`

Python 3.12 package/config/domain foundation, mainnet-only/testnet-rejecting configuration, paper default, secret-safe logging, Ruff/mypy/pytest, and CI.

### Phase 2
Merge: `b95352e238d6a9eabd63e13c1f8300e654a7e636`

Direct mainnet `/info`, conservative retry/rate handling, dynamic native + HIP-3 discovery, namespaced market IDs, immutable Decimal normalization, candles/funding readers, and read-only market tooling.

### Phase 3
Merge: `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57` — PR #3

Public mainnet WebSocket normalization, freshness/reconnect/duplicate/out-of-order handling, bounded dynamic deep-watchlist subscriptions, durable rotating JSONL with recovery, real-mainnet fixtures.

### Phase 4
Merge: `dae7cf6cf51af9def0a027529d2b0900a6a4d5f6` — PR #4

Immutable feature snapshots, funding/OI/volume/returns/dislocation, multi-timeframe context, volatility/range/relative-volume, L2 spread/depth/imbalance/age, regimes, eligibility/ranking/shortlist, broad-to-deep scanner orchestration.

### Phase 5
Merge: `82c3db2f9ce39676e089eac79e63c5043b72e331` — PR #6

Explainable trend/breakout/mean-reversion baselines, real trade/L2 microstructure windows, funding/OI and order-flow context, deterministic regime-aware LONG/SHORT/NO_TRADE combination, orchestration and boundary tests.

### Phase 6
Merge: `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912` — PR #8

Immutable Decimal risk/account/liquidity/health contracts; deterministic IDs; cost-aware 0.25% sizing; aggregate/correlation/daily/weekly/cooldown caps; same-market veto; leverage/margin/liquidity/liquidation limits; venue-minimum rejection without forced upsizing; downward risk-to-notional rounding; boundary tests.

### Phase 7
Merge: `5cd4b3603cf05d2e5dc2cc3a165c026a01b2fcab` — PR #9  
Final feature head: `f0059025f578524df56e4cdbff75710e9885f45c`  
Final CI: `32667484578` — SUCCESS  
Core job: `97263085563`  
Python: `3.12.14`

Established deterministic mainnet-observed paper IOC execution, inherited Phase 6 risk ceilings, public `activeAssetCtx`, visible-L2 full/partial/no-fill simulation, fees/funding, paper positions/account/equity/margin, rolling risk state, reduce-only exits, deterministic position management, atomic SQLite recovery, and narrow `TradingExecution` / `PaperExecutionAdapter` boundaries with no private/live capability.

---

## 7. Phase 8 implementation state

**Branch:** `phase-8-journal-replay`  
**PR:** #10 — `Phase 8: deterministic journal and replay`  
**Latest verified implementation head:** `4447f7af169a0449f87dca86f665c6ccdbd0debb`  
**CI run:** `32713200269` — SUCCESS  
**Core job:** `97388844825` — SUCCESS  
**Research job:** `97388844471` — SUCCESS  
**Python:** `3.12.14`

The exact verified implementation head passed editable install, compileall, Ruff, mypy, full pytest, research-extra install, and the dedicated Parquet compaction/replay tests.

Phase 8 established:

- deterministic immutable journal/replay domain contracts and semantic IDs;
- exact JSONL segment validation with byte hashes, row counts, source identity, availability windows, and fail-closed corruption checks;
- frozen replay manifests with code/config/data/schema/version provenance;
- explicit replay clock and canonical event ordering based on evidence availability;
- lookahead regressions proving future candle/mark/L2 evidence cannot affect earlier outputs;
- mechanical `CANDLE_CONTEXT` vs `MICROSTRUCTURE` evidence separation;
- restart-safe SQLite journal for observations, trades, references, manifests/runs and compaction provenance;
- closed-trade lifecycle reconciliation across strategy/risk/plan/attempt/fill/action/funding/account state;
- net PnL, fees, public funding, net R, holding duration, signed slippage amount/fraction, MFE/MAE;
- partial-reduction-aware excursion currency attribution using quantity open at each extremum;
- multi-exit slippage using the actual reference price attached to each exit plan;
- deterministic replay engine wrapping existing Phase 5 strategy, Phase 6 risk and Phase 7 paper boundaries rather than adding parallel formulas;
- deterministic LONG/SHORT end-to-end replay and NO_TRADE/risk-reject/no-fill zero-exposure regressions;
- optional PyArrow genuine-Parquet compaction in `[project.optional-dependencies].research` only;
- JSONL/Parquet canonical record equivalence and derived-file corruption/hash rejection;
- offline `validate-recording`, `compact-recording`, `replay`, and `inspect-journal` commands;
- source-level boundaries excluding testnet, network/live exchange clients in replay, wallet/private-key/signing, transfer/withdrawal, private user/account data, ML/parameter optimization, and candle-to-book fabrication.

PR audit at the verified implementation point:

- PR #10 has no comments/review threads;
- PR is mergeable;
- feature branch is `behind_by = 0` relative to `main`;
- changed-file surface is confined to Phase 8 design/plan, CI/research dependency, replay/journal/CLI/execution-lineage plumbing, and Phase 8 tests;
- live trading remains disabled.

Continuity docs are now being updated. A new exact-head CI run is mandatory after those doc commits and before guarded merge, so the verified implementation CI above must not be treated as the final merge CI.

---

## 8. Phase 7 paper-simulator assumptions retained

These are versioned simulator/control assumptions rather than claims of optimal venue policy:

- native validator-operated Hyperliquid perps for execution; HIP-3 remains observable/rankable but unsupported for Phase 7 paper execution until separately validated;
- deterministic latency: 250 ms;
- maximum accepted L2 age: 1,000 ms;
- maximum public asset-context age: 5,000 ms;
- funding reconciliation grace: 300,000 ms;
- IOC slippage guard: 25 bps;
- native-perp baseline taker fee: `Decimal("0.00045")` with versioned fee schedule;
- native-perp minimum notional baseline: `Decimal("10")`;
- paper gross leverage ceiling: 3x or lower venue maximum;
- only displayed normalized L2 depth may fill;
- no passive maker fills/rebates;
- actual entry rechecks the inherited Phase 6 risk envelope;
- funding uses real public funding history plus lookahead-safe public oracle context;
- stale/inconsistent execution/account/funding state blocks new exposure while safe exits remain possible when usable public data exists.

---

## 9. Phase 9 boundary

Phase 9 is evaluation/OOS/walk-forward research gating. It may begin only after Phase 8 is merged and continuity docs on `main` record the actual merge SHA.

Phase 9 must evaluate deterministic behavior rather than silently tune the locked system. Phase 10 ML, Phase 11 long-running shadow, Phase 12 live-adapter construction, and any real-money activation remain deferred.

---

## 10. Live-trading gate

Live trading remains disabled. A later promotion path must require substantial mainnet paper/shadow evidence, positive net performance after realistic costs, untouched OOS and walk-forward stability, bounded drawdown/concentration, no unresolved risk invariants, restart/reconciliation reliability, and finally explicit user authorization of live mode and capital.

Future live runtime should use a dedicated Hyperliquid API/agent wallet, never a master-wallet private key.

---

## 11. Fresh-chat continuation instructions

When asked to continue Cocomelon:

1. Treat this file as bootstrap context, never as stronger authority than the live repository.
2. Inspect `Dtwosam/Cocomelon` with connected GitHub tools.
3. Read `AGENTS.md`, `docs/MASTER_SPEC.md`, `docs/DECISIONS.md`, `docs/BUILD_ORDER.md`, `docs/STATUS.md`, then the active phase spec/plan.
4. Check `main`, open PRs, current head, review threads, compare state, and exact-head CI.
5. Continue from the precise active task; never rebuild merged phases.
6. Use design/spec -> detailed TDD plan -> implementation -> verification -> guarded integration for each phase.
7. Handle routine engineering/product/CI/PR/merge decisions autonomously.
8. Ask only for genuinely non-derivable decisions; real-money activation always requires explicit user authorization.
9. Never claim completion without fresh verification evidence for the exact tree/head being discussed.
10. Update `docs/STATUS.md` and this portable source after every phase.
11. Verify current official Hyperliquid documentation before implementing behavior that depends on potentially changed external venue semantics.

---

## 12. Exact handoff now

Phase 7 is merged. Phase 8 implementation is complete and PR #10 is in closeout.

Immediate sequence:

1. finish continuity-doc updates on `phase-8-journal-replay`;
2. run exact-head full core + research CI;
3. re-audit PR surface/comments/mergeability/branch freshness/live boundaries;
4. guarded-merge PR #10 only on the exact green head;
5. verify `main` and post-merge branch diff;
6. reconcile actual Phase 8 merge metadata in `docs/STATUS.md` and this file on `main`;
7. then activate Phase 9 design/spec work — not Phase 10+ and not live trading.

**Live trading status: DISABLED.**
