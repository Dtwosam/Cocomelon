# Cocomelon Project Status

**Last updated:** 2026-08-24  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Live trading:** **DISABLED**

## Current state

**Latest merged engineering milestone:** Phase 9 — deterministic evaluation, untouched OOS, and walk-forward research gates  
**Merged Phase 9 evaluator PR:** #13  
**Merged Phase 9 evaluator commit:** `97218fdec7b8896ce63cf5889dbe41fb39f97bd7`  
**Active integration:** Phase 9 Evidence Bridge — PR #15, branch `phase-9-evidence-bridge`  
**PR #15 base:** `main` at `9ff81397e8d8f179eee42a83aeaffe14134fa1fc`  
**Latest verified implementation/test head before this continuity-only update:** `13297a2fa5bd353e7bd8e111f70844c40bd91f7a`  
**Exact implementation CI:** `32757257536` — SUCCESS  
**Core job:** `97527559694` — SUCCESS  
**Research job:** `97527559475` — SUCCESS  
**Python:** `3.12.14`  
**PR branch divergence at verification:** `behind_by = 0`  
**Real baseline evidence status:** **UNMEASURED**  
**Phase 9 economic/research exit gate:** PENDING genuine recorded mainnet evidence  
**Phase 10:** BLOCKED pending a genuine Phase 9 baseline evaluation

## Phase 9 evaluator already merged

The merged Phase 9 evaluator provides deterministic, fail-closed research gates around trusted Phase 8 replay/journal outputs. It includes immutable evaluation facts and datasets, time-based train/validation/test partitions, six-hour purge/embargo, untouched-OOS consumption tracking, deterministic cost-aware metrics and bootstrap confidence intervals, walk-forward evaluation, market/regime/strategy/direction/time/score-bucket diagnostics, fixed predeclared fee/slippage/funding stress profiles, sampled `NO_TRADE` diagnostics, and five explicit evidence states:

- `INVALID_EVIDENCE`
- `OOS_CONTAMINATED`
- `INSUFFICIENT_EVIDENCE`
- `NO_EDGE_DEMONSTRATED`
- `CANDIDATE_EDGE`

Its versioned V1 research policy remains:

- minimum untouched OOS trades: 100;
- minimum OOS covered days: 30;
- minimum eligible walk-forward windows: 3;
- minimum trades per walk-forward window: 20;
- minimum score-bucket trades: 20;
- minimum positive walk-forward-window fraction: 60%;
- bootstrap confidence: 95%;
- day-block bootstrap size: 5 days;
- bootstrap resamples: 2,000;
- split embargo: 6 hours;
- sampled `NO_TRADE` horizons: 1 hour and 4 hours.

`CANDIDATE_EDGE` additionally requires positive untouched-test mean net R, bootstrap lower bound > 0, positive/stable eligible walk-forward behavior, market positive-PnL concentration <=35%, and seven-day concentration <=50%.

## Phase 9 Evidence Bridge implemented on PR #15

The Evidence Bridge closes the operational gap between genuine Hyperliquid mainnet public recordings and the merged evaluator. It does **not** add live trading, private account access, ML, or optimizer/search capability.

Implemented on the verified PR tree:

- deterministic evidence-recording contracts and immutable recording-session identity;
- bounded public Hyperliquid **mainnet-only** evidence capture in paper mode;
- dynamic ranked native-perp cohort selection rather than favorite-token hard-coding;
- public REST evidence recording for full market snapshots, candles, and funding with actual response receive-time provenance;
- WebSocket evidence recording for genuine asset context, L2, trades, and candles;
- funding dedupe by `(market, funding_time_ms)` preserving first-observation provenance;
- restart-safe recording sessions and immutable frozen baseline replay bundles;
- bundle/source/session/config/code-revision binding with exact source hashes;
- a fully offline `run-baseline-replay` path routed before runtime network settings;
- production deterministic decision epochs using existing Phase 4/5 feature, eligibility, regime, and strategy formulas;
- shared-account Phase 6 risk gating and Phase 7 paper opening/fill mechanics against recorded genuine L2;
- hard staleness/health/state-consistency gates for new exposure;
- paper liquidation surrogate used only for deterministic risk-buffer simulation, never presented as a venue liquidation quote;
- deterministic position management using genuine recorded mark/book evidence;
- funding reconciliation and accounting using exact recorded public funding boundaries and genuine pre-boundary oracle evidence;
- funding idempotency corrected to the locked Phase 7 identity contract: market + funding boundary, preventing duplicate cash application when mutable position state changes;
- complete Phase 8 journal lifecycle assembly and Phase 9 decision/equity fact persistence;
- deterministic same-bundle reruns across fresh stores and idempotent reopening of completed stores;
- end-to-end fixture proving `recorded rows -> frozen bundle -> production baseline replay -> journal/facts -> Phase 9 dataset`;
- offline summaries explicitly declare `network_access: false` and `live_orders: false` and make no profitability/edge claim;
- executable Evidence Bridge boundaries excluding testnet, live/order/wallet/signing/private-account/withdraw/transfer capability, ML/training, optimizer/grid/random search, offline network-client imports, and candle-derived L2/trade construction.

The end-to-end fixture intentionally includes fresh genuine `activeAssetCtx` before a latency-eligible entry book. This preserves the locked 5-second execution-context freshness gate instead of weakening risk controls to make a test trade pass.

## Exact verification for the implemented bridge tree

Commit `13297a2fa5bd353e7bd8e111f70844c40bd91f7a` passed CI run `32757257536`:

- Python `3.12.14`;
- editable `[dev]` install — PASS;
- `python -m compileall -q src tests scripts` — PASS;
- `python -m ruff check src tests scripts` — PASS;
- `python -m mypy src` — PASS;
- full `python -m pytest -q` — PASS;
- editable `[dev,research]` install — PASS;
- `python -m pytest tests/test_replay_compaction.py tests/test_parquet_replay_source.py -q` — PASS.

The PR audit at that point also showed:

- mergeable PR #15;
- `behind_by = 0` from `main`;
- no PR comments;
- no submitted reviews;
- no review threads;
- no `pyproject.toml` dependency drift;
- changed code/test surface limited to the Evidence Bridge, the minimum required Phase 7/8 accounting/replay hooks, and tests/spec/plan.

This continuity update is documentation-only and must receive its own exact-head CI before guarded merge.

## Real baseline evidence status

The repository still does **not** contain a connector-accessible persisted real mainnet replay/journal corpus to evaluate economically. Tracked source/tests prove engineering behavior only; `.gitignore` excludes runtime evidence and SQLite outputs.

Therefore:

**REAL BASELINE EDGE: UNMEASURED**

The production-shaped bridge fixtures are deterministic engineering regressions, not historical Hyperliquid performance evidence. They must not be presented as economic proof, and Phase 9 does not currently claim `CANDIDATE_EDGE`, `NO_EDGE_DEMONSTRATED`, or any real historical profitability result.

## Completed engineering phases

- Phase 0 — governance/source-of-truth anchor: COMPLETE.
- Phase 1 — Python foundation/domain/config/CI: MERGED at `3efd9e28b84eaa5dcd75f6949d8df02e2928d163`.
- Phase 2 — mainnet REST discovery/normalization: MERGED at `b95352e238d6a9eabd63e13c1f8300e654a7e636`.
- Phase 3 — WebSocket collector/durable recorder: MERGED at `e0c1eb6a9893de48ec3dee9e4ac2a57c9f660d57`.
- Phase 4 — feature engine/scanner/ranking/shortlist: MERGED at `dae7cf6cf51af9def0a027529d2b0900a6a4d5f6`.
- Phase 5 — explainable baseline strategy engines: MERGED at `82c3db2f9ce39676e089eac79e63c5043b72e331`.
- Phase 6 — independent risk engine: MERGED at `cb25d9e76f5db998b2e9298d1e1ca8b825ae8912`.
- Phase 7 — real-mainnet paper execution + position manager: MERGED at `5cd4b3603cf05d2e5dc2cc3a165c026a01b2fcab`.
- Phase 8 — deterministic journal/replay/backtester + analytical compaction: MERGED at `f7f37044997e13b3ffe91edd312756862343782b`.
- Phase 9 — deterministic evaluation/OOS/walk-forward infrastructure: MERGED at `97218fdec7b8896ce63cf5889dbe41fb39f97bd7`.
- Phase 9 Evidence Bridge — IMPLEMENTED on PR #15; guarded merge pending exact closeout CI/audit.

## Locked safety and product invariants

- Hyperliquid testnet is forbidden.
- Market observations are Hyperliquid mainnet only.
- Mainnet market-data endpoints remain `https://api.hyperliquid.xyz` and `wss://api.hyperliquid.xyz/ws`.
- Default execution is paper/shadow and places no real exchange orders.
- No live exchange adapter is enabled or authorized.
- No wallet/private-key signing, transfer, withdrawal, or private account/user subscription exists in the Evidence Bridge.
- Whole-market discovery remains dynamic; eligibility is separate from ranking.
- Explainable deterministic baselines remain first-class before ML; `NO_TRADE` is valid.
- Strategy cannot size positions or send orders; independent risk has final veto.
- Locked risk remains 0.25% planned account risk per trade, 0.75% aggregate planned open risk, 1% daily realized-loss lockout, 3% rolling weekly drawdown, and cooldown after three consecutive losing trades.
- No averaging down, martingale, or stopless positions.
- No historical L2/order flow may be fabricated from candles.
- PyArrow remains optional research tooling only.
- Real-money activation always requires explicit user authorization after all later promotion gates pass.

## Exact next action

1. Obtain exact-head CI for the continuity-only PR head.
2. Reconfirm PR #15 mergeability, `behind_by = 0`, expected changed-file surface, and zero unresolved comments/reviews/threads.
3. Guarded-merge PR #15 using the exact expected head SHA.
4. Verify `main` and an observable post-merge CI path.
5. Keep Phase 10 blocked.
6. In an environment that can persist runtime data, run `record-mainnet-evidence`, freeze the corpus, run the offline baseline replay, freeze Phase 9 dataset/splits/candidate/policy, and evaluate the genuine evidence.

## Live trading status

**DISABLED.**

Cocomelon can discover, analyze, decide, risk-gate, paper-execute/manage, journal, replay, and deterministically evaluate fake-capital outcomes against trusted evidence. The Evidence Bridge can now connect genuine public mainnet recordings to that pipeline, but no genuine corpus has yet demonstrated economic edge and no real-money order is authorized.