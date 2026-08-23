# Phase 8 Journal, Replay, Backtester, and Compaction Design

**Status:** Approved for autonomous implementation under the user's standing instruction to proceed without routine approval prompts.

## 1. Goal

Phase 8 makes every Cocomelon decision and paper-trade outcome reproducible and measurable from immutable inputs while preserving the evidence boundaries established in Phases 1-7.

The phase must provide four connected capabilities:

1. a complete durable journal for scanner, strategy, risk, execution, position-management, funding, and account outcomes;
2. deterministic replay of recorded observations and decisions;
3. deterministic candle/context backtesting plus genuine microstructure replay from recorded L2/trade evidence;
4. offline compaction of validated Phase 3 JSONL into versioned Parquet analytical datasets without changing provenance.

Phase 8 does not add ML, live exchange orders, wallet/signing capability, private-user subscriptions, transfers, withdrawals, testnet support, or risk-limit changes.

## 2. Locked constraints

The implementation must preserve these existing decisions:

- Hyperliquid mainnet observations only; testnet remains forbidden.
- Paper execution remains the only execution capability.
- Phase 6 remains the sole authority for new-exposure risk.
- No candle may be converted into fabricated L2/trade history.
- SQLite stores compact operational/journal state; high-volume observations live in JSONL/Parquet.
- The Phase 3 collector continues writing fsynced JSONL. Parquet is produced only by an offline job.
- Authoritative monetary/risk arithmetic remains Decimal-deterministic.
- Missing/corrupt/inconsistent evidence fails closed rather than being silently interpolated.
- NO_TRADE and rejected risk decisions are journal-worthy observations, not discarded noise.

## 3. Architecture

Phase 8 is split into five focused units.

### 3.1 Journal ledger

A journal record is an immutable, append-only fact about a decision lifecycle. The operational store persists these compact facts in SQLite independently of the high-volume market recorder.

Each record has:

- `journal_id`: deterministic content-addressed identifier;
- `record_type`: typed lifecycle category;
- `occurred_at_ms`: event/decision time used for replay ordering;
- `recorded_at_ms`: local persistence time;
- `market`: canonical `MarketId` when applicable;
- `decision_id`, `risk_decision_id`, `plan_id`, `attempt_id`, `fill_id`, `position_id`, or `funding_record_id` references when applicable;
- `schema_version`;
- `code_version`;
- `config_version`;
- `payload`: canonical JSON-compatible content containing reason codes and references rather than high-volume duplicated market data.

The deterministic journal ID is SHA-256 over canonical JSON of all logical fields except `recorded_at_ms`. Re-recording the same logical fact is idempotent. A conflicting row under the same ID is a fail-closed consistency error.

Required journal record types include at minimum:

- `SCANNER_SNAPSHOT`;
- `STRATEGY_DECISION` including LONG/SHORT/NO_TRADE and component signals/reason codes;
- `RISK_DECISION` including approved/rejected status and all veto reasons;
- `ORDER_PLAN`;
- `EXECUTION_ATTEMPT`;
- `FILL`;
- `POSITION_OPEN`;
- `POSITION_ACTION`;
- `POSITION_CLOSE`;
- `FUNDING_ACCRUAL`;
- `ACCOUNT_SNAPSHOT`;
- `DATA_GAP`;
- `REPLAY_RESULT`.

The journal stores references to feature snapshots and market event keys rather than copying entire L2 books into SQLite.

### 3.2 Replay manifest

Every replay/backtest run is defined by an immutable `ReplayManifest`.

It contains:

- `manifest_schema_version`;
- `replay_id` derived from canonical manifest content;
- `evidence_class`: `CANDLE_CONTEXT` or `MICROSTRUCTURE`;
- ordered input partitions/files;
- per-input SHA-256 digest, byte size, and logical partition identity;
- inclusive start and end receive-time bounds;
- code version;
- strategy/config/risk/execution versions;
- recorder/event schema versions;
- compaction dataset version when Parquet is used;
- deterministic tie-break policy version.

The replay manifest must never depend on filesystem enumeration order. Inputs are normalized to POSIX relative paths and sorted deterministically.

### 3.3 Validated event reader and deterministic replay

Phase 3 JSONL remains the provenance root for microstructure evidence. Phase 8 adds a strict reader that:

- validates each JSON line structure;
- rejects malformed JSON, unsupported schema versions, non-finite decimals, duplicate logical records with conflicting contents, and path/record partition mismatches;
- reconstructs normalized `StreamEvent`/`DataGap` semantics without inventing missing timestamps;
- computes file digests while reading;
- emits deterministic `ReplayEvent` envelopes.

Replay ordering is stable and lookahead-safe. The ordering key is:

1. observation availability time (`receive_time_ms` for market events; explicit occurrence time for journal/control records);
2. exchange timestamp when present, otherwise a sentinel that does not move the record before its receive time;
3. evidence-kind priority from a versioned fixed table;
4. canonical market key;
5. stable source/event key;
6. input path;
7. zero-based line number.

The engine must never order a record earlier than the time it became available to the system.

Data gaps are replayed as first-class state. A consumer that requires missing/stale evidence must fail closed or produce NO_TRADE/rejection according to the existing phase contracts; the replay layer itself does not fill gaps.

### 3.4 Evidence-separated backtesting

The backtesting API exposes two explicit modes and does not allow them to masquerade as each other.

#### Candle/context mode

Inputs may include trustworthy candles, mids/mark/oracle/funding/OI context, scanner features, and other observations whose historical timestamp/availability can be proven.

It can evaluate strategy/risk decisions and higher-level position outcomes where the execution model is explicitly candle/context-class. It may not claim L2 slippage, queue position, or order-flow precision.

#### Microstructure mode

Inputs require actual recorded normalized L2 and/or trade events. Paper IOC fills use the existing Phase 7 L2-aware simulator against replayed books. Microstructure strategy components may run only when their required recorded evidence is present and fresh.

The backtester routes through the same Phase 4 scanner, Phase 5 strategy, Phase 6 risk, and Phase 7 paper execution/accounting interfaces where practical. Separate research-only execution shortcuts that award better fills are forbidden.

### 3.5 Offline Parquet compaction

Compaction is a separate offline command/library path. It must not be imported by the always-on recorder.

A compaction job:

1. discovers only explicitly requested validated JSONL partitions;
2. validates every record before writing output;
3. preserves provenance fields (`source`, `schema_version`, `event_key`, exchange/receive timestamps, market, input file, input line number);
4. sorts rows using the same deterministic replay ordering key;
5. writes versioned Parquet partitions;
6. writes a dataset manifest containing input/output SHA-256 digests, row counts, schemas, code version, and compaction version;
7. writes to a temporary path and atomically promotes the completed dataset only after validation succeeds.

`pyarrow` is permitted only as an offline/research optional dependency. It must not become a mandatory dependency of the liveness-critical collector/runtime package path.

Re-running compaction with identical validated inputs, versions, and configuration must produce the same logical rows, manifest contents, ordering, and dataset identity. Binary Parquet byte identity is not required across different PyArrow versions; the manifest records the writer/library version so the environment is reproducible.

## 4. Canonical serialization and hashing

All deterministic identifiers/manifests use canonical UTF-8 JSON:

- sorted object keys;
- separators `(',', ':')`;
- no NaN/Infinity;
- Decimal encoded as canonical decimal strings;
- UTC timestamps encoded as integer milliseconds or RFC3339 `Z` according to the field contract;
- enums encoded by stable string value;
- no process-memory addresses, unordered sets, or local absolute paths.

Content hashes use SHA-256 hex digests. Hash inputs are versioned so later schema evolution does not silently collide with Phase 8 identities.

## 5. Trade analytics

For every closed simulated trade with sufficient evidence, Phase 8 computes a deterministic `TradeAnalytics` result including:

- market, direction, strategy decision ID, risk decision ID, position ID;
- entry and exit timestamps;
- holding time milliseconds;
- entry VWAP and exit VWAP;
- gross realized PnL;
- fees;
- funding;
- slippage attribution versus the plan/reference price;
- net PnL;
- approved risk amount;
- realized net R = net PnL / approved risk amount;
- MFE in currency and R;
- MAE in currency and R;
- exit reason;
- strategy/regime/reason-code trace;
- evidence class;
- replay/dataset provenance IDs.

MFE/MAE use only observations available between the first executed entry fill and final close. For LONG, favorable excursion uses the highest valid mark/reference observation and adverse excursion the lowest; SHORT is symmetric. The metric source is recorded. If the required observation class is missing or has a gap that makes the metric unknowable, the metric is `None` with an explicit reason rather than fabricated.

Net PnL attribution must reconcile:

`net_pnl = gross_realized_pnl - fees + funding`

with slippage reported as attribution, not subtracted twice if it is already embedded in actual fill prices.

## 6. Lookahead rules

A decision at time `T` may consume only evidence whose system-availability time is `<= T`.

Specific rules:

- candle close values are unavailable until the candle's recorded availability/receive time;
- exchange timestamp alone never permits a record to arrive before receive time;
- funding settlement uses the existing Phase 7 lookahead-safe funding reconciliation semantics;
- replayed feature snapshots preserve their original observation cutoffs;
- future records are not preloaded into state visible to strategies;
- stable sorting may resolve records with equal availability timestamps but may not allow a later timestamp to influence an earlier decision.

Tests must include adversarial fixtures where a profitable future candle/book update would change a decision if leaked.

## 7. Journal/replay integration

Replay produces a fresh output journal namespace keyed by `replay_id`; it never mutates or overwrites the original operational journal.

The replay result must link:

- input manifest;
- emitted strategy/risk/order/fill/position records;
- analytics rows;
- final account snapshot;
- deterministic result digest.

Two runs with the same manifest and code/config versions must produce the same logical journal sequence and result digest.

## 8. CLI surface

Phase 8 adds offline commands only:

- `cocomelon replay validate ...` — validate inputs and print manifest/replay ID;
- `cocomelon replay run ...` — run deterministic replay/backtest in one explicit evidence class;
- `cocomelon compact parquet ...` — compact validated recorder partitions offline;
- `cocomelon journal inspect ...` — inspect journal/replay summaries without mutating them.

Commands must refuse testnet URLs, live execution configuration, private keys, or any request to place real orders. Phase 8 does not add an exchange endpoint dependency.

## 9. Failure behavior

Fail closed on:

- malformed/corrupt JSONL;
- unsupported recorder or journal schema version;
- hash mismatch;
- duplicate record ID with conflicting content;
- input file changes after manifest construction;
- unrecognized evidence class;
- candle/context data passed to microstructure-required logic without actual microstructure evidence;
- event ordering regression that would violate availability time;
- Parquet output/manifest mismatch;
- journal transaction failure;
- accounting or result-digest mismatch.

A failed replay/compaction must not publish a successful output manifest.

## 10. Dependencies

Core runtime remains lightweight and keeps existing mandatory dependencies.

Phase 8 may add an optional dependency group:

`research = ["pyarrow>=18,<22"]`

The recorder, scanner, strategy, risk, paper execution, and normal paper runtime must not import PyArrow. Parquet modules may import it lazily and produce a clear error when the research extra is absent.

No ML library is added in Phase 8.

## 11. Testing strategy

Required test classes:

- canonical serialization/hash determinism under reordered mappings and ambient Decimal context changes;
- journal idempotency and conflict rejection;
- atomic journal writes and restart reads;
- manifest deterministic ordering and file hash verification;
- corrupt/mutated input rejection;
- exact ReplayEvent ordering for timestamp ties;
- explicit candle/context vs microstructure boundary rejection;
- adversarial lookahead leakage tests;
- genuine Phase 3 L2/trade replay through Phase 7 IOC simulation;
- NO_TRADE and risk rejection journaling;
- deterministic full lifecycle replay result digest;
- MFE/MAE/net-R/fees/funding/slippage attribution invariants;
- Parquet compaction row/provenance preservation and deterministic dataset manifest;
- compaction atomicity/failure injection;
- source-level safety boundary excluding testnet/live-order/wallet/signing/withdraw/transfer/private-user capability.

Full CI remains editable install, compileall, Ruff, mypy, and pytest under Python 3.12.

## 12. Exit criteria

Phase 8 is complete only when:

- every lifecycle decision/outcome required by the Master Spec can be represented and durably journaled;
- same validated data + manifest + config/code versions reproduces the same logical replay journal and result digest;
- lookahead adversarial tests pass;
- candle/context and microstructure evidence classes are impossible to confuse through public interfaces;
- actual recorded L2/trade fixtures replay through the existing paper IOC path;
- MFE/MAE, net R, costs, and reason traces are deterministic and reconciled;
- validated JSONL compacts into real Parquet with complete provenance and a versioned dataset manifest;
- malformed/mutated evidence fails closed;
- no Phase 9 evaluation, Phase 10 ML, or live execution capability is introduced;
- full Python 3.12 CI passes.
