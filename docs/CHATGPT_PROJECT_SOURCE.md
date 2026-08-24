# COCOMELON — CHATGPT PROJECT SOURCE

**Purpose:** Portable bootstrap context for continuing the Cocomelon build across ChatGPT chats. The live GitHub repository is authoritative.  
**Repository:** `Dtwosam/Cocomelon`  
**Primary language:** Python 3.12  
**Venue:** Hyperliquid HyperCore perpetual markets  
**Execution mode now:** real-mainnet observation + bounded internal paper/shadow execution  
**Live trading:** DISABLED  
**Hyperliquid testnet:** NEVER USE

---

## 1. Mission

Cocomelon is an autonomous intraday Hyperliquid perpetual-futures research/trading system under staged development. It dynamically discovers the real perp universe, rejects poor/stale markets, ranks opportunities, deeply analyzes a bounded shortlist, chooses LONG/SHORT/NO_TRADE, passes every directional proposal through an independent risk engine, paper-executes approved trades against real mainnet observations, manages positions, journals/replays outcomes without lookahead, and evaluates deterministic baselines through frozen OOS/walk-forward gates before any learning phase.

Economic objective: **positive net risk-adjusted expectancy after fees, funding, slippage, and realistic execution costs while preserving capital**. Profit is never guaranteed.

Routine architecture, implementation, tests, branches, PRs, CI fixes, reviews, and guarded merge decisions are handled autonomously. Real-money activation is the permanent exception: no real-capital order placement without later promotion gates and explicit user authorization.

---

## 2. Locked product and safety decisions

### Hyperliquid mainnet only

- Hyperliquid testnet is forbidden.
- REST market-data base: `https://api.hyperliquid.xyz`
- WebSocket market-data base: `wss://api.hyperliquid.xyz/ws`
- Runtime configuration rejects known testnet hosts.

### Paper/shadow before real capital

Paper execution observes real Hyperliquid mainnet evidence but places no exchange orders. It models visible-book fills, spread/slippage, fees, funding, latency, partial/no-fill outcomes, stops, accounting, and recovery without assuming perfect fills.

### Broad universe, bounded deep analysis

`discover all -> eligibility -> broad features -> rank -> dynamic shortlist -> deep features -> strategy -> decision -> risk -> execution`

No fixed favorite-token universe. Eligibility is mechanically separate from ranking.

### Locked V1 risk

- planned account risk per trade: **0.25%**
- max aggregate planned open risk: **0.75%**
- daily realized-loss lockout: **1.00%**
- rolling weekly drawdown lockout: **3.00%**
- three consecutive losing trades -> **60-minute cooldown**
- correlation-bucket planned-risk cap: **0.50%**
- gross leverage ceiling: **3x** or lower venue maximum
- new exposure may consume at most **50%** of currently available margin after effective leverage
- new notional may consume at most **10%** of weaker visible 25-bps side depth
- liquidation must be beyond the stop and at least **2x stop distance**
- no averaging down
- no martingale/loss-recovery sizing
- no position without stop/invalidation
- stale/inconsistent state blocks new exposure

Leverage is subordinate to dollar risk. Strategy score cannot scale the risk percentage upward. Authoritative risk arithmetic uses deterministic fixed-precision Decimal semantics.

### Deterministic baselines before ML

Explainable deterministic strategies remain first-class. `NO_TRADE` is valid. Phase 10 ML/champion-challenger work is downstream of a genuine Phase 9 evidence result and may never silently alter hard risk limits.

### Never fabricate microstructure

Historical L2/order-flow evidence may only come from genuinely recorded/trusted book or trade observations. Candles can never be converted into synthetic L2/order flow.

### Real-money boundary

No wallet/private-key/signing/private-account/transfer/withdrawal capability belongs in paper/replay/evaluation paths. No real-money order may be enabled without later promotion gates and explicit user authorization.

---

## 3. Architecture

```text
Hyperliquid Mainnet
  -> Public REST/WebSocket Evidence
  -> Durable Recorder / Data Quality
  -> Dynamic Discovery + Eligibility + Ranking
  -> Deep Features / Deterministic Strategies
  -> LONG / SHORT / NO_TRADE
  -> Independent Risk APPROVE / REJECT
  -> Paper Execution / Position Management
  -> Journal / Deterministic Replay
  -> Phase 9 Evaluation / OOS / Walk-Forward
  -> Champion / Challenger Learning (blocked until real Phase 9 evidence)
```

Hard boundaries:

- scanner rank is attention priority, not directional evidence;
- strategy cannot size positions or send orders;
- risk is independent and has final veto;
- replay preserves evidence class and availability time;
- Phase 9 evaluation is offline/read-only relative to exchange state;
- models may never call exchange APIs directly;
- live trading remains disabled until later gates and explicit user authorization.

---

## 4. Merge history and active integration

Merged engineering phases:

- Phase 1: `3efd9e28b84eaa5dcd75f6949d8df02e2928d163`
- Phase 2: `b95352e238d6a9eabd63e13c1f8300e654a7e636`
- Phase 3: `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57` — PR #3
- Phase 4: `dae7cf6cf51af9def0a027529d2b0900a6a4d5f6` — PR #4
- Phase 5: `82c3db2f9ce39676e089eac79e63c5043b72e331` — PR #6
- Phase 6: `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912` — PR #8
- Phase 7: `5cd4b3603cf05d2e5dc2cc3a165c026a01b2fcab` — PR #9
- Phase 8: `f7f37044997e13b3ffe91edd312756862343782b` — PR #10
- Phase 9 evaluator: `97218fdec7b8896ce63cf5889dbe41fb39f97bd7` — PR #13

Active integration at this handoff:

- PR #15 — **Phase 9: production evidence bridge**
- branch: `phase-9-evidence-bridge`
- base: `main` at `9ff81397e8d8f179eee42a83aeaffe14134fa1fc`
- latest verified implementation/test head before continuity-only docs: `13297a2fa5bd353e7bd8e111f70844c40bd91f7a`
- exact CI: `32757257536` — SUCCESS
- core job: `97527559694` — SUCCESS
- research job: `97527559475` — SUCCESS
- Python: `3.12.14`
- branch was `behind_by = 0`, PR mergeable, with zero comments/reviews/review threads at audit.

The continuity docs themselves are the only changes after that verified implementation head and require their own exact-head CI before guarded merge.

---

## 5. Phase 8 retained foundation

Phase 8 established deterministic journal/replay contracts, source hashing/validation, frozen replay manifests, availability-time replay clocks, restart-safe journal persistence, lifecycle/PnL reconciliation, signed slippage attribution, quantity-aware MFE/MAE, deterministic LONG/SHORT/NO_TRADE/risk-reject/no-fill replay coverage, optional PyArrow Parquet compaction, JSONL/Parquet semantic equivalence, and offline recording/replay/journal-inspection commands.

Phase 8 final merge commit: `f7f37044997e13b3ffe91edd312756862343782b`.

---

## 6. Phase 9 evaluator already merged

Phase 9 wraps trusted Phase 8 outputs in deterministic anti-p-hacking research gates.

Implemented and merged:

- immutable evaluation facts/contracts and canonical IDs;
- restart-safe separate `EvaluationFactStore`;
- provenance-complete evaluation dataset manifests;
- frozen absolute train/validation/test splits with full-lifecycle containment and six-hour embargo;
- mechanical untouched-OOS consumption and `OOS_CONTAMINATED` tracking;
- cost-aware trade/portfolio metrics, drawdown, tail loss, concentration, and score/regime/market/time slices;
- deterministic day-block bootstrap confidence intervals;
- deterministic walk-forward evaluation;
- predeclared fee/slippage/funding stress profiles only, with no search for the best profile;
- lookahead-safe sampled `NO_TRADE` missed-opportunity diagnostics using genuine marks only;
- five explicit evidence states: `INVALID_EVIDENCE`, `OOS_CONTAMINATED`, `INSUFFICIENT_EVIDENCE`, `NO_EDGE_DEMONSTRATED`, `CANDIDATE_EDGE`;
- read-only promotion previews that cannot authorize execution;
- offline CLI commands to freeze datasets/splits, evaluate, and inspect evaluation results without network settings.

Versioned `phase9-v1` research defaults:

- minimum untouched OOS trades: 100;
- minimum OOS covered days: 30;
- minimum eligible walk-forward windows: 3;
- minimum trades per walk-forward window: 20;
- minimum score-bucket trades: 20;
- minimum positive walk-forward-window fraction: 60%;
- bootstrap confidence: 95%;
- bootstrap block length: 5 days;
- bootstrap resamples: 2,000;
- split embargo: 6 hours;
- sampled `NO_TRADE` horizons: 1 hour and 4 hours.

`CANDIDATE_EDGE` additionally requires positive untouched-test mean net R, bootstrap lower bound > 0, positive/stable eligible walk-forward behavior, market positive-PnL concentration <=35%, and seven-day concentration <=50%.

---

## 7. Phase 9 Evidence Bridge implementation

The Evidence Bridge makes genuine public mainnet recordings evaluation-ready without adding exchange-write or learning capability.

Implemented on PR #15:

- deterministic evidence-recording contracts and immutable recording-session IDs;
- bounded public mainnet recording allowed only in paper mode;
- dynamic ranked native-perp selection;
- real receive-time preservation for REST snapshots/candles/funding;
- genuine WebSocket asset-context/L2/trade/candle recording;
- funding dedupe by `(market, funding_time_ms)` preserving first receive provenance;
- restart-safe recording sessions;
- immutable replay bundles binding source bytes, recording session, replay config, and code revision;
- fully offline `run-baseline-replay` CLI routed before `Settings.from_env()`;
- deterministic decision epochs with lookahead protection and cross-market arrival-order invariance;
- reuse of existing Phase 4/5 feature, regime, eligibility, and strategy formulas;
- shared-account Phase 6 risk and Phase 7 paper fills against genuine recorded L2;
- execution staleness/health/state-consistency hard gates;
- deterministic position management against recorded marks/books;
- exact recorded funding reconciliation and signed paper cash accounting;
- funding application idempotency keyed by the locked Phase 7 market + funding-boundary identity, rather than mutable position payload;
- Phase 8 journal lifecycle assembly and Phase 9 decision/equity facts;
- deterministic fresh-store reruns and idempotent completed-store reopening;
- end-to-end proof of `recorded rows -> frozen bundle -> baseline replay -> journal/facts -> Phase 9 dataset`;
- executable boundaries excluding testnet, live/order/wallet/private/signing/transfer/withdrawal capability, ML/training, optimizer/search helpers, offline network clients, and candle-derived L2/trades.

A useful regression discovered during closeout: a strategy decision may still be eligible on a 60-second broad context window while Phase 7 execution correctly refuses a context older than 5 seconds. The integration fixture was corrected by supplying a genuine fresh `activeAssetCtx` before the latency-eligible book. No production freshness limit was weakened.

Verified implementation head `13297a2fa5bd353e7bd8e111f70844c40bd91f7a` passed:

- editable `[dev]` install;
- compileall;
- Ruff;
- mypy;
- full pytest;
- editable `[dev,research]` install;
- Phase 8 PyArrow research replay/compaction regression.

CI run: `32757257536`.

---

## 8. Real baseline evidence status

**REAL BASELINE EDGE: UNMEASURED**

The tracked repository does not contain a connector-accessible persisted genuine mainnet replay/journal corpus. Runtime evidence and SQLite outputs remain outside tracked source history.

The Evidence Bridge integration fixtures are production-shaped deterministic engineering tests, not historical market-performance evidence. They prove lineage, fills, accounting, replay, and evaluator handoff only. They are not an economic edge claim.

Phase 10 remains **BLOCKED** until genuine recorded mainnet evidence is frozen, replayed, and evaluated by the merged Phase 9 gates. A real result may honestly be `CANDIDATE_EDGE`, `NO_EDGE_DEMONSTRATED`, `INSUFFICIENT_EVIDENCE`, or `INVALID_EVIDENCE` according to the corpus.

---

## 9. Fresh-chat continuation instructions

When asked to continue Cocomelon:

1. Treat this file as bootstrap context; the live repository is stronger authority.
2. Inspect `Dtwosam/Cocomelon` with connected GitHub tools.
3. Read `AGENTS.md`, `docs/MASTER_SPEC.md`, `docs/DECISIONS.md`, `docs/BUILD_ORDER.md`, `docs/STATUS.md`, then the active phase spec/plan.
4. Check `main`, open PRs, branch/compare state, review threads, and exact-head CI.
5. Continue from the precise active task; never rebuild merged phases.
6. Use design/spec -> detailed TDD plan -> implementation -> verification -> guarded integration.
7. Handle routine engineering/product/CI/PR/merge decisions autonomously.
8. Ask only for genuinely non-derivable decisions; real-money activation always requires explicit user authorization.
9. Never claim completion without fresh verification evidence for the exact tree/head being discussed.
10. Update `docs/STATUS.md` and this portable source after every phase/integration boundary.
11. Verify current official Hyperliquid documentation before behavior dependent on potentially changed venue semantics.

---

## 10. Exact handoff now

PR #15 has completed implementation and executable boundary verification. The last verified implementation/test head is `13297a2fa5bd353e7bd8e111f70844c40bd91f7a`, CI `32757257536`, with core and research jobs green. The branch was not behind `main`, the PR was mergeable, and there were no comments/reviews/review threads.

Immediate sequence:

1. obtain exact-head CI for the continuity-only docs commits now at the tip of `phase-9-evidence-bridge`;
2. re-audit PR #15 and confirm `behind_by = 0`;
3. mark PR ready and guarded-merge using the exact expected head SHA;
4. verify the returned merge SHA is `main` and compare branch -> `main` for an empty file diff;
5. verify post-merge continuity through an observable CI path;
6. keep Phase 10 blocked;
7. next economic action is external-runtime evidence collection: `record-mainnet-evidence`, freeze the corpus, run `run-baseline-replay`, then run the merged Phase 9 evaluation on genuine evidence.

**Live trading status: DISABLED.**