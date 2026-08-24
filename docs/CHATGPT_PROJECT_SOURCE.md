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

### Storage boundary

Always-on normalized streaming evidence is durable fsynced JSONL. Phase 8 validates immutable JSONL and can compact it offline into genuine Parquet behind an optional research dependency while preserving source hashes/provenance. SQLite is for lower-volume operational/journal/evaluation metadata.

---

## 3. Architecture and hard boundaries

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
  -> Champion / Challenger Learning (blocked until real Phase 9 evidence)
```

Hard boundaries:

- scanner rank is attention priority, not directional evidence;
- strategy cannot size positions or send orders;
- risk is independent and has final veto;
- replay preserves evidence classes and availability time;
- Phase 9 evaluation is offline/read-only relative to exchange and execution state;
- Phase 9 has no Hyperliquid network client, wallet/signing, private account, live-order, ML-training, or optimizer capability;
- models may never call exchange APIs directly;
- live trading remains disabled until later gates and explicit user authorization.

---

## 4. Approved build order and merge history

Merged engineering phases:

- Phase 1: `3efd9e28b84eaa5dcd75f6949d8df02e2928d163`
- Phase 2: `b95352e238d6a9eabd63e13c1f8300e654a7e636`
- Phase 3: `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57` — PR #3
- Phase 4: `dae7cf6cf51af9def0a027529d2b0900a6a4d5f6` — PR #4
- Phase 5: `82c3db2f9ce39676e089eac79e63c5043b72e331` — PR #6
- Phase 6: `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912` — PR #8
- Phase 7: `5cd4b3603cf05d2e5dc2cc3a165c026a01b2fcab` — PR #9
- Phase 8: `f7f37044997e13b3ffe91edd312756862343782b` — PR #10
- Phase 9 engineering infrastructure: `97218fdec7b8896ce63cf5889dbe41fb39f97bd7` — PR #13

Current gate:

- Phase 9 **economic/research exit gate** — PENDING genuine recorded mainnet evidence.
- Phase 10 — champion/challenger learning engine — **BLOCKED pending genuine Phase 9 baseline evaluation**.
- Phase 11 — long-running mainnet shadow.
- Phase 12 — mainnet live adapter built but disabled.
- Phase 13 — explicit user-approved live promotion.
- Phase 14 — evidence-based optimization/scaling.

`docs/STATUS.md` is the exact current state.

---

## 5. Phase 8 retained foundation

Phase 8 established deterministic journal/replay contracts, source hashing/validation, frozen replay manifests, availability-time replay clocks, restart-safe journal persistence, lifecycle/PnL reconciliation, signed slippage attribution, quantity-aware MFE/MAE, deterministic LONG/SHORT/NO_TRADE/risk-reject/no-fill replay coverage, optional PyArrow Parquet compaction, JSONL/Parquet semantic equivalence, and offline recording/replay/journal-inspection commands.

Phase 8 final PR head `83454520fa652533c47688f6ab14c0d1fb19473f` passed CI `32713492047`; merge commit is `f7f37044997e13b3ffe91edd312756862343782b`.

---

## 6. Phase 9 merged engineering implementation

Phase 9 wraps trusted Phase 8 outputs in deterministic anti-p-hacking research gates.

Implemented:

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
- offline CLI commands to freeze datasets/splits, evaluate, and inspect evaluation results without network settings;
- end-to-end synthetic closed-outcome regression fixtures plus a genuine small Phase 8 ReplayEngine -> Phase 9 lineage integration test;
- executable boundaries excluding testnet, network/live exchange capability, wallet/private keys/signing/transfers/withdrawals, ML training, optimizer/search helpers, and candle-derived microstructure.

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

## 7. Phase 9 final verification and merge evidence

Final PR head: `80f9d1fcbb26b858022e6fbd4d13b68ae01a5b21`  
Final PR-head CI: `32725387221` — SUCCESS  
Core job: `97425382295` — SUCCESS  
Research job: `97425382551` — SUCCESS  
Merge commit: `97218fdec7b8896ce63cf5889dbe41fb39f97bd7`

The exact PR head passed Python 3.12 editable installs, compileall, Ruff, mypy, full pytest, and the dedicated Phase 8 PyArrow research regression.

Integration audit:

- PR #13 was mergeable, ready, and `behind_by = 0`;
- 39 changed files were confined to Phase 9 spec/plan, evaluation implementation/tests, offline CLI, Phase 8 read-only journal accessors, and continuity docs;
- no Phase 9 dependency change was made to `pyproject.toml`;
- no PR comments, reviews, or review threads existed;
- guarded merge used exact expected head `80f9d1fcbb26b858022e6fbd4d13b68ae01a5b21`;
- `main` immediately pointed to `97218fdec7b8896ce63cf5889dbe41fb39f97bd7`;
- comparing `phase-9-evaluation-gates` to `main` showed exactly one merge commit and an empty file diff;
- a disposable non-merged PR #14 pointed exactly at post-merge `main` head `23d60a92c9ba279fe2412e4369fc12aa29534e53` so the normal pull-request CI could be observed through the connector;
- CI probe run `32726146583` passed core job `97427751752` and research job `97427751978`; PR #14 was closed without merge.

The final wording-only continuity tree is re-verified before handoff. No source, dependency, or test surface changes after the verified Phase 9 merge.

---

## 8. Real baseline evidence status

**REAL BASELINE EDGE: UNMEASURED**

The repository does not contain a connector-accessible persisted real mainnet replay/journal corpus to score economically. The tracked repo contains source/docs/tests/configuration while `.gitignore` excludes `data/`, `logs/`, `*.sqlite`, and `*.sqlite3`.

Therefore the synthetic positive/weak closed-outcome fixtures are **only statistical regression tests**. They are not historical Hyperliquid evidence, fills, or a profitability claim. Phase 9 currently does not claim `CANDIDATE_EDGE`, `NO_EDGE_DEMONSTRATED`, or any real historical baseline outcome.

Per `BUILD_ORDER.md` and `MASTER_SPEC.md`, Phase 10 must not start merely because the evaluator is merged. Genuine recorded mainnet paper/replay evidence must first be frozen and evaluated through Phase 9. The correct real result may be `CANDIDATE_EDGE`, `NO_EDGE_DEMONSTRATED`, `INSUFFICIENT_EVIDENCE`, or `INVALID_EVIDENCE` according to the corpus.

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

Phase 9 engineering infrastructure is merged into `main` at `97218fdec7b8896ce63cf5889dbe41fb39f97bd7`, with pre-merge and post-merge exact-tree CI evidence recorded above. The economic/research gate remains open because no genuine persisted mainnet corpus is connector-accessible.

Immediate sequence:

1. keep Phase 10 blocked;
2. obtain/use genuine recorded Hyperliquid mainnet paper/replay evidence through the existing Phase 3-8 pipeline;
3. freeze a Phase 9 dataset, time splits, candidate set, policy, and predeclared sensitivity profiles before revealing untouched-test metrics;
4. run and persist the genuine Phase 9 baseline evaluation;
5. only after the real evidence result is known decide whether Phase 10 is allowed by the approved build order or whether more data/baseline evidence is required.

**Live trading status: DISABLED.**
