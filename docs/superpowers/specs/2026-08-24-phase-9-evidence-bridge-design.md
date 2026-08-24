# Phase 9 Evidence Bridge Design

**Date:** 2026-08-24  
**Status:** Approved for implementation under the repository's autonomous-build instruction  
**Base:** `main` at `9ff81397e8d8f179eee42a83aeaffe14134fa1fc`

## 1. Goal

Close the operational gap between the merged Phase 3-9 components and the still-unmeasured Phase 9 economic gate.

The repository already contains genuine Hyperliquid mainnet public readers, a durable JSONL recorder, deterministic feature/strategy/risk logic, realistic paper execution, immutable replay/journal infrastructure, and frozen OOS/walk-forward evaluation. The missing production path is that the current `replay` CLI performs only an evidence audit; complete Phase 5->8 strategy/risk/paper replay wiring exists only in tests. There is also no bounded evaluation-oriented recorder command that captures REST warmup/context/funding beside WebSocket microstructure.

The Evidence Bridge adds:

```text
mainnet public evidence
  -> bounded durable recording
  -> frozen baseline replay bundle
  -> deterministic Phase 5-8 paper replay
  -> journal + Phase 9 evaluation facts
  -> existing Phase 9 dataset/split/evaluate commands
```

It makes the real baseline measurable. It does not claim an edge.

## 2. Scope boundaries

### In scope

- bounded/restart-safe mainnet public evidence recording;
- dynamic startup selection from the discovered native-perp universe;
- genuine REST bootstrap market context and 5m/15m candle warmup;
- genuine public funding-history capture;
- immutable recording-session metadata;
- frozen replay bundle containing raw replay configuration/provenance plus `ReplayManifest`;
- deterministic production Phase 5->8 baseline replay from recorded evidence;
- shared multi-market paper account/risk state;
- genuine funding reconciliation/application;
- journal lifecycle assembly;
- Phase 9 decision/equity fact persistence during replay;
- offline CLI outputs feeding the existing Phase 9 evaluator;
- strict source/boundary tests.

### Explicitly out of scope

- Phase 10 ML/champion-challenger training;
- parameter/feature optimization or search;
- Phase 11 long-running deployment/service supervision/alerts;
- live exchange order placement;
- wallet/private-key/signing capability;
- private user/account subscriptions;
- withdrawals/transfers;
- Hyperliquid testnet;
- passive maker-fill assumptions;
- synthetic historical L2/trades;
- reconstructing missing funding or books from candles;
- automatic live promotion.

Live trading remains disabled.

## 3. Design principles

1. **Availability time wins.** REST evidence is available only at its actual local receive time. Historical candle/funding timestamps never make it available earlier.
2. **No semantic overloading.** REST market snapshots and funding records use explicit normalized recorder kinds, not fake WebSocket messages.
3. **No hidden tuning.** Selection policy, decision cadence, warmup, funding polling, risk/execution assumptions, and grace periods are versioned configuration.
4. **Replay is offline.** Production baseline replay imports no Hyperliquid network client and cannot call the venue.
5. **Reuse existing engines.** Strategy, risk, paper execution, position management, features, eligibility, and journal arithmetic are called rather than copied.
6. **One account across markets.** Aggregate risk/leverage/margin/loss/cooldown constraints act on shared paper state.
7. **Incomplete evidence fails closed.** Missing/stale prerequisites cause NO_TRADE/rejection/gap status, never fabricated values.
8. **Synthetic tests are not market evidence.** Fixtures prove mechanics only.

## 4. Package boundary

Create:

```text
src/cocomelon/evidence/
  __init__.py
  contracts.py
  recording.py
  bundle.py
  baseline.py
  cli_support.py
```

The package may depend on existing Phase 2-9 contracts. `cocomelon.evaluation` must not depend back on it.

## 5. Immutable bridge contracts

### 5.1 `EvidenceRecordingConfig`

Frozen/versioned settings:

- `config_version = "phase9-evidence-v1"`;
- `deep_limit = 20`;
- positive bounded `duration_seconds` supplied by CLI;
- `context_poll_seconds = 60`;
- `funding_poll_seconds = 60`;
- `warmup_5m_bars = 25`;
- `warmup_15m_bars = 25`;
- candle subscriptions `(1m, 5m, 15m)`;
- recorder segment limits;
- mainnet endpoint identities;
- selection policy ID `rankable-native-top-v1`.

`deep_limit` is capture capacity, not a performance-tuned strategy parameter, and must fit the existing subscription safety ceiling.

### 5.2 `EvidenceRecordingSession`

Immutable session metadata written before streaming starts:

- schema/config version;
- session ID;
- recorder code revision;
- actual start receive time;
- selected canonical markets, sorted;
- startup opportunity-rank ordinals and feature snapshot IDs;
- selection policy/config identity;
- endpoint identity;
- exact recording-config digest.

A pre-existing root may resume only if this metadata matches. A new cohort requires a new recording root.

### 5.3 `BaselineReplayConfig`

Frozen/versioned research settings:

- `config_version = "phase9-baseline-replay-v1"`;
- starting cash `10000`;
- decision timeframe `15m`;
- decision grace `30_000 ms`;
- microstructure window `60_000 ms`;
- correlation bucket `crypto_beta`;
- current locked `RiskLimits()`;
- current `EligibilityConfig()`;
- current `PaperExecutionConfig()`;
- paper liquidation-surrogate policy ID;
- feature/strategy/risk/replay version identifiers.

Changing any field changes the config digest and replay identity.

### 5.4 `FrozenBaselineReplayBundle`

A canonical JSON document containing:

- all `ReplayManifest` fields;
- canonical `BaselineReplayConfig` payload;
- recording-session metadata digest;
- source-set digest;
- bundle schema/version;
- bundle ID.

`manifest.config_digest` must equal the canonical digest of replay config plus immutable recording-session provenance. Load fails on divergence. This retains the raw versioned configuration beside the manifest rather than keeping only an opaque digest.

## 6. Bounded mainnet evidence recording

### 6.1 CLI

Add:

```text
cocomelon record-mainnet-evidence \
  --root <recording-root> \
  --seconds <bounded-duration> \
  [--deep-limit 20]
```

Rules:

- `ExecutionMode.PAPER` required;
- known testnet URLs remain rejected by `Settings`;
- public endpoints/subscriptions only;
- no order method imported or called;
- existing root may resume only matching immutable session/config;
- JSON summary never exposes secrets.

### 6.2 Dynamic startup cohort

For a new session:

1. `MarketRegistry(InfoClient(settings)).refresh()` discovers the current universe.
2. Existing broad features, eligibility, and ranking scan the universe.
3. Keep active/rankable **native/default-dex** markets because Phase 7 paper execution currently supports that execution namespace.
4. Select top `deep_limit` using the existing ranker.
5. Persist exact selected cohort and startup rank/feature references.

No favorite-token list. The V1 cohort is frozen only for that bounded session. A new session refreshes it; full intra-session subscription rotation remains a Phase 11 operational concern.

### 6.3 REST bootstrap

Before WebSocket streaming, capture for selected markets:

- full normalized `PerpMarketSnapshot` from official public `metaAndAssetCtxs`;
- genuine 5m candle warmup;
- genuine 15m candle warmup;
- recent genuine funding history.

Each response uses actual response receive time as evidence availability. Warmup allows the existing feature engine to calculate 1h/4h, volatility, range-expansion, and relative-volume values immediately without inventing history.

### 6.4 Explicit recorder kinds

Extend `DurableRecorder` with canonical public REST evidence helpers while retaining the existing `normalized_event` envelope:

- `market_snapshot`;
- `funding_rate`;
- existing `candle` kind for REST candle warmup.

They remain hash-validated under `events/<receive-date>/<kind>/<market>/...`. No private-data record type is added.

### 6.5 WebSocket capture

Use existing `DeepWatchlistManager` + `WebSocketSupervisor` for:

- `allMids`;
- selected `activeAssetCtx`;
- selected `l2Book`;
- selected `trades`;
- selected 1m/5m/15m candles.

Async sink wrappers call `DurableRecorder.append_event/append_gap`. Recorder failures propagate and stop capture instead of being misclassified as reconnects.

### 6.6 Periodic public REST evidence

During capture:

- poll native `metaAndAssetCtxs` every 60s and append full selected-market snapshots;
- poll recent `fundingHistory` every 60s for selected markets;
- deduplicate funding by `(market, funding_time_ms)` so the first observation fixes receive-time provenance.

REST failure records an explicit public-evidence data gap. It is never substituted with synthetic values.

## 7. Freezing a replay bundle

Add:

```text
cocomelon freeze-baseline-replay \
  --root <recording-root> \
  --out <bundle.json> \
  [--starting-cash 10000] \
  [--code-revision <sha>]
```

Behavior:

1. validate JSONL with Phase 8 validation;
2. validate recording-session metadata;
3. derive receive-time start/end;
4. derive deterministic gap references from recorded gaps;
5. build a `MICROSTRUCTURE` manifest with current versioned execution config;
6. bind exact baseline config + recording provenance into the bundle;
7. write atomically;
8. reload and reproduce identical IDs.

If code revision is omitted, resolve exact local Git HEAD. If that is unavailable, fail rather than write ambiguous provenance.

## 8. Production deterministic baseline replay

### 8.1 CLI

Add:

```text
cocomelon run-baseline-replay \
  --bundle <bundle.json> \
  --journal <journal.sqlite3> \
  --execution <paper-execution.sqlite3> \
  --facts <evaluation-facts.sqlite3>
```

It is fully offline, routed before `Settings.from_env()`, and tested to avoid network settings/clients.

### 8.2 Replay state

Per market, maintain only state derived from already-available records:

- latest and previous full `market_snapshot`;
- latest WS asset context merged only into fields it truly supplies;
- latest version of each 5m/15m candle keyed by interval/start;
- latest L2;
- rolling genuine TRADE/L2 events for the existing microstructure window;
- latest strategy decision;
- lifecycle lineage for open paper exposure;
- pending genuine funding/oracle evidence.

Global state has one shared `PaperExecutionAdapter`, journal, evaluation fact store, mark map, and decision-epoch state.

### 8.3 Decision epochs

Use 15m candle boundaries.

For each boundary:

- wait until all recorded cohort markets have a closed 15m candle for it, or until versioned 30s receive-time grace expires;
- evaluate once;
- incomplete/stale markets are non-tradable for that epoch;
- no later evidence can affect an earlier epoch.

This removes cross-market arrival-order bias.

### 8.4 Features, eligibility, strategy

For each ready market:

1. existing `calculate_broad_features` from latest/previous full public snapshots;
2. existing `calculate_candle_features`;
3. existing `calculate_microstructure_features` from genuine L2;
4. existing `build_microstructure_window` from genuine TRADE/L2 events;
5. existing `assemble_feature_snapshot`;
6. existing cross-sectional `derive_eligibility_thresholds`;
7. existing `evaluate_eligibility`;
8. existing `evaluate_strategies`.

No strategy formula is copied into the bridge.

### 8.5 Entry processing

Directional decisions are processed in deterministic market order:

- mark all open paper positions from current valid marks and roll day state;
- build `RiskRequest` from shared account state, locked `RiskLimits`, actual recorded L2 side depth, current metadata, execution health, and evidence freshness;
- use a versioned conservative execution-cost estimate derived from existing IOC slippage guard + taker fee assumptions, not fit outcomes;
- use a documented paper liquidation surrogate based on the lower of paper max leverage and venue max leverage solely for the existing liquidation-buffer risk check; it is a simulation control assumption, not an actual venue liquidation-price claim;
- execute only against the first valid L2 book whose receive time satisfies the existing latency boundary;
- submit through `PaperExecutionAdapter`; no fill creates no exposure.

### 8.6 Position management

For open positions as mark/book evidence arrives:

- mark-to-market first;
- call existing `PaperExecutionAdapter.manage_position`;
- use latest strategy only while fresh;
- preserve existing HOLD/TIGHTEN/REDUCE/STOP/THESIS/EMERGENCY semantics;
- collect real simulated lineage for journal assembly.

The bridge adds no new profit-taking strategy.

### 8.7 Funding accounting

Funding must not be ignored.

Add `apply_funding_accrual(account, accrual, timestamp_ms)` that:

- matches exactly one open position and accrual `position_id`;
- applies `cash_delta` to cash;
- increments account and position cumulative funding by the same signed delta;
- preserves gross realized PnL/fee accounting;
- recomputes account state through deterministic accounting;
- persists idempotently with `PaperExecutionStore.persist_funding`;
- rejects conflicting duplicate application.

At hourly boundaries crossed by an open position, use existing `reconcile_funding_boundary` with the latest genuine pre-boundary oracle and exact recorded public `FundingRate`. Missing/stale evidence emits a funding-gap journal observation and makes replay incomplete; no interpolation.

### 8.8 Journal assembly

Track lifecycle objects per opened position and call existing `assemble_trade_journal_entry` only when quantity reaches zero. Inputs come only from actual Phase 7 simulated lineage and recorded evidence: opening/exit plans and attempts, fills, position actions, funding accruals, equity before/after, exit reason, marks, known gaps, and `MICROSTRUCTURE` evidence class.

A lifecycle reconciliation failure fails replay rather than silently dropping exposure.

### 8.9 Phase 9 facts

During replay persist:

- `DecisionEvaluationFact` for every strategy decision from the exact feature snapshot;
- account equity facts at initial, mark, execution, funding, day-roll, and final states.

A successful replay is therefore directly consumable by existing `freeze-evaluation-dataset`.

## 9. Restart and determinism

- Recorder restart resumes only matching immutable session metadata and uses existing new-segment-on-resume behavior.
- Replay is deterministic from bundle + source bytes + code revision.
- Same replay into fresh execution storage must reproduce `ReplayResult.result_digest`, trade IDs, decision fact IDs, and dataset inputs.
- Same journal/fact store retries are idempotent immutable writes.
- Conflicting payloads under deterministic IDs fail closed.

## 10. CLI summaries

`record-mainnet-evidence` reports session/cohort/duration/event-gap/reconnect/anomaly counts and explicit `live_orders: false`.

`freeze-baseline-replay` reports bundle/manifest/source-set IDs, receive-time range, segment/row/gap counts, and exact config/code versions.

`run-baseline-replay` reports bundle/manifest/run/result IDs, strategy/risk/execution/fill/trade counts, final account state/equity, completeness, output paths, `network_access: false`, and `live_orders: false`.

No single replay summary may label itself profitable evidence; Phase 9 evaluation owns that conclusion.

## 11. Test strategy

### Contracts/serialization

- canonical IDs independent of enumeration order/Decimal ambient context;
- recording-session resume conflict rejection;
- bundle/config digest mismatch rejection;
- REST receive-time preservation.

### Recorder

- dynamic ranking/native-perp selection;
- warmup/snapshot/funding rows pass Phase 8 validation;
- funding dedupe preserves first observation;
- sink/REST failures fail closed or record gaps as specified;
- no private/testnet surface.

### Accounting/funding

- long/short funding signs;
- account/position cumulative funding exact reconciliation;
- persistence/restart idempotency;
- missing funding remains a gap.

### Baseline replay

- production-shaped JSONL fixtures;
- features calculated from rows, never fixture-injected snapshots;
- future rows cannot affect earlier decisions;
- cross-market 15m arrival-order permutations give identical decisions/results;
- shared account enforces aggregate risk;
- directional, NO_TRADE, risk-reject, no-fill, funding, exit, and data-gap cases;
- exact rerun digest equality;
- decision/equity fact restart equality;
- output feeds the existing Phase 9 dataset builder.

### Boundaries

Executable scans reject testnet, live/exchange-order/wallet/signing/withdrawal/transfer/private-subscription capability, ML/training, optimizer/grid/random parameter search, candle-to-book fabrication, and network imports in baseline replay modules.

## 12. Completion gate

Complete only when:

1. exact feature head passes Python 3.12 install/compile/Ruff/mypy/full pytest;
2. Phase 8 PyArrow research regression remains green;
3. end-to-end fixture proves `recorded rows -> frozen bundle -> production baseline replay -> journal/facts -> Phase 9 dataset`;
4. replay modules contain no network/live/private/ML/optimizer capability;
5. PR audit is clean, branch is not behind `main`, and guarded merge uses exact expected head;
6. `main` is verified after merge;
7. continuity docs keep **REAL BASELINE EDGE: UNMEASURED** until genuine external mainnet evidence is actually evaluated.

Bridge completion does not authorize Phase 10 or live trading.
