# Phase 8 Journal, Deterministic Replay, and Analytical Compaction Design

**Status:** Approved autonomous design under the user's standing instruction to make routine project decisions without approval prompts  
**Date:** 2026-08-23  
**Base:** `main` at `de1a8c1234de64558378c8be61218d1319e75cee`  
**Phase 7 merge:** `5cd4b3603cf05d2e5dc2cc3a165c026a01b2fcab`

## 1. Goal

Make every Cocomelon decision, simulated trade, cost, and outcome reproducible from explicit evidence and versioned configuration.

Phase 8 converts the trusted Phase 3 JSONL event history plus Phase 4-7 deterministic pipeline contracts into a research-grade journal/replay system. The same validated evidence, manifest, configuration, and code revision must reproduce the same ordered replay outputs. Microstructure claims remain grounded in actual recorded books/trades; candle/context data may never be promoted into synthetic order-book evidence.

The economic purpose is to create trustworthy measurements for later evaluation and model research. Phase 8 does not optimize parameters, promote strategies, train ML, or enable live execution.

## 2. Scope boundary

Phase 8 may:

- replace the Phase 1 `DecisionRecord` placeholder with immutable Decimal-safe journal/replay contracts;
- persist low-volume decision/trade/control journal records in a dedicated SQLite journal store;
- reference existing Phase 4 feature snapshots, Phase 5 strategy decisions, Phase 6 risk decisions, and Phase 7 plans/attempts/fills/funding/position actions/account states by deterministic IDs;
- validate and read Phase 3 normalized JSONL event partitions and data-gap records;
- create immutable replay manifests containing exact input/provenance/version digests;
- replay normalized events through a deterministic event clock with strict as-of semantics;
- define explicit evidence classes for candle/context replay versus microstructure replay;
- compact validated JSONL partitions offline into genuine Parquet using an optional research dependency;
- preserve raw-event provenance in compacted rows and dataset manifests;
- compute closed-trade analytics including gross/net PnL, fees, funding, realized slippage, holding time, MFE, MAE, and net R;
- record sampled `NO_TRADE` decisions as journal observations so later evaluation can study avoided/missed opportunities;
- expose deterministic replay results for Phase 9 evaluation.

Phase 8 may not:

- alter Phase 5 strategy rules or Phase 6 risk limits to improve backtest results;
- tune or optimize parameters using replay results;
- implement walk-forward/OOS promotion gates beyond interfaces needed to export replay results;
- train ML or add champion/challenger behavior;
- synthesize L2 books, trades, queue position, passive fills, or market impact from candles;
- interpolate missing microstructure evidence;
- silently skip corrupt segments or data gaps;
- rewrite or mutate the trusted Phase 3 JSONL source history;
- make PyArrow a dependency of the always-on collector/runtime;
- add wallet, signing, private-account, transfer, withdrawal, or live-order capability;
- use Hyperliquid testnet.

## 3. Recommended architecture

Use four isolated layers:

```text
trusted Phase 3 JSONL + gaps
        |
        v
validation / canonical source index
        |-----------------------------+
        v                             v
replay manifest                  offline compactor
        |                             |
        v                             v
deterministic event clock       Parquet dataset + dataset manifest
        |
        v
existing Phase 4 -> 5 -> 6 -> 7 pure/deterministic boundaries
        |
        v
journal observations + trade lifecycle references
        |
        v
closed-trade analytics / replay result
        |
        v
Phase 9 evaluation (deferred)
```

SQLite stores low-volume journal/control metadata. High-volume event evidence remains JSONL and derived Parquet. Replay components never need a network connection.

## 4. Architectural choices considered

### 4.1 Recommended: provenance-first event replay with separate journal and analytical datasets

Replay consumes canonical validated normalized events in event/receive-time order. Journal rows store decisions and lifecycle references, not copies of every market event. Parquet is an offline derivative with its own manifest and raw-source hashes.

Advantages:

- preserves the Phase 3 raw trust boundary;
- supports exact reproduction and audit;
- keeps runtime dependencies small;
- prevents research convenience from contaminating live ingestion;
- scales to large event history later.

### 4.2 Rejected: SQLite as the universal event store

Putting all L2/trade history into SQLite would simplify querying but duplicate high-volume evidence, conflict with D-015/D-021, and increase operational write/size pressure.

### 4.3 Rejected: backtest directly from candles for every strategy

This is cheaper but would create false confidence for microstructure-dependent logic. Candle replay remains valid only for components whose required evidence is genuinely present in candle/context data.

## 5. Evidence classes

Define an immutable `EvidenceClass` enum:

- `CANDLE_CONTEXT`
- `MICROSTRUCTURE`

A replay manifest declares exactly one evidence class.

### 5.1 Candle/context replay

May consume only evidence that exists without reconstructing a book:

- normalized candles;
- broad/public context available at the replay timestamp;
- funding records/context where properly timestamped;
- metadata and deterministic derived features whose source data is available as-of time.

It may evaluate candle/context-compatible feature/strategy behavior but may not invoke L2-aware execution as though a historical book existed. If a workflow requires L2 execution and no recorded eligible L2 event exists, the outcome is explicitly unavailable/pending/rejected rather than fabricated.

### 5.2 Microstructure replay

May consume genuinely recorded:

- `L2_BOOK` events;
- `TRADE` events;
- `ACTIVE_ASSET_CTX` events;
- candles/context used by the broader strategy pipeline;
- recorded data-gap events.

Only this evidence class can claim historical IOC fill/replay results from Phase 7's L2 simulator.

## 6. Source validation and canonical indexing

Phase 3 `DurableRecorder` JSONL is immutable source evidence. Phase 8 adds read-side validation, never mutation.

Every input segment must be validated for:

- valid UTF-8 JSONL with one JSON object per complete line;
- allowed `record_type` (`normalized_event` or `data_gap`);
- supported schema version;
- valid source string and required provenance fields;
- canonical market identifier for event rows;
- timezone-aware normalized receive timestamp;
- non-negative exchange timestamp where present;
- valid event key;
- partition path consistent with receive date, event kind, and market;
- no duplicate event key inside a canonical replay input set unless duplicate policy explicitly identifies the later row as duplicate evidence;
- no truncated/corrupt final record;
- deterministic byte/content digest.

Validation returns immutable `SourceSegment` records. A corrupt or structurally inconsistent segment fails closed. Phase 8 never silently drops it to make a backtest run.

### 6.1 Segment digest

Use SHA-256 over exact segment bytes. Dataset/replay manifests record the digest, byte length, row count, partition identity, schema version, first/last evidence timestamp, and relative source path.

The exact source bytes remain authoritative; normalization into typed replay events is deterministic and separately versioned.

## 7. Replay manifest

Define immutable `ReplayManifest` containing at minimum:

- deterministic `manifest_id`;
- manifest schema version;
- evidence class;
- replay start/end timestamps;
- ordered tuple of source segment descriptors and SHA-256 digests;
- ordered tuple of explicit data-gap descriptors relevant to the window;
- code revision identifier supplied by the caller/CLI (normally Git commit SHA);
- configuration snapshot/version/digest;
- feature schema/version references;
- strategy version/reference;
- risk-limits/risk-engine version reference;
- paper execution config/version and fee-schedule ID where execution replay is enabled;
- replay engine version;
- dataset/compaction manifest ID when replaying from a derived columnar dataset;
- creation timestamp as metadata only, excluded from semantic replay identity where appropriate.

`manifest_id` hashes canonical semantic inputs. Re-running manifest construction from the same evidence/config/version inputs yields the same ID.

A replay run refuses to start if a supplied segment digest no longer matches disk contents.

## 8. Deterministic event clock and ordering

Replay uses an explicit event clock. No wall-clock reads occur in replay kernels.

Canonical ordering key:

1. evidence availability timestamp;
2. stable evidence-kind priority;
3. canonical market key;
4. event key/source key.

The evidence availability timestamp is the receive timestamp for WebSocket observations because that is when the system could actually know the event. Exchange timestamps remain provenance and may be used for event-specific validity checks, but they cannot make an observation available before receive time.

For REST/history records, the replay adapter must carry an explicit availability/as-of timestamp. A record whose publication/availability time cannot be established may be used only in analyses that do not claim live-decision equivalence.

Stable ordering avoids ambient file-system enumeration order or dictionary order changing results.

## 9. Lookahead boundary

At replay decision time `t`, every feature/strategy/risk/execution input must satisfy `available_at_ms <= t`.

Rules:

- future candle close values cannot enter a decision before their close/availability time;
- current/next L2 snapshots cannot satisfy an IOC before Phase 7 latency eligibility and actual receive time;
- funding uses the same Phase 7 pre-boundary oracle + post-boundary actual record semantics;
- data gaps are part of replay state and can cause freshness/health rejection;
- no backward fill/interpolation may introduce a value that was not known at decision time;
- dataset compaction must preserve availability timestamps unchanged.

Dedicated tests deliberately insert attractive future information and prove outputs are unchanged until that evidence becomes available.

## 10. Journal domain

Replace the minimal Phase 1 journal placeholder with immutable versioned records.

### 10.1 `JournalObservation`

Represents a low-volume decision/control observation:

- deterministic `observation_id`;
- observation kind;
- market when applicable;
- occurred/decision timestamp;
- available/provenance timestamp when different;
- feature snapshot ID;
- strategy decision ID;
- risk decision ID;
- execution plan/attempt IDs when applicable;
- position action ID when applicable;
- account state ID when applicable;
- stable reason codes;
- health/data-gap references;
- replay/run ID when generated by replay;
- schema/version references.

Observation kinds include scanner shortlist, strategy decision, risk decision, execution attempt, position action, funding event/gap, account state, and lifecycle close summary. `NO_TRADE` and risk rejection remain first-class observations.

### 10.2 `TradeJournalEntry`

Represents one closed paper-trade lifecycle, not one fill:

- deterministic `trade_id`;
- market/direction;
- open/close timestamps;
- originating feature/strategy/risk IDs;
- opening/exit plan and attempt IDs;
- ordered fill IDs;
- position-action IDs;
- funding-event IDs;
- initial stop/risk amount;
- entry/exit weighted prices;
- filled quantity;
- gross realized trading PnL;
- entry/exit fees;
- funding cash PnL;
- net PnL;
- realized slippage amounts/fractions against explicit references;
- MFE/MAE;
- net R;
- holding duration;
- equity before/after;
- exit reason;
- data-quality/health references;
- evidence class and replay/run provenance.

Financial fields use `Decimal` and fixed authoritative Decimal arithmetic.

## 11. Journal SQLite store

Create a separate `JournalStore` rather than overloading Phase 7 operational tables.

Minimal tables:

- `journal_meta` — schema/replay version metadata;
- `journal_observations` — immutable idempotent observations;
- `journal_trades` — closed lifecycle summaries;
- `journal_trade_refs` — normalized ordered references to fills/actions/funding/evidence;
- `replay_manifests` — canonical manifest JSON + digest/ID;
- `replay_runs` — run status/result references;
- `compaction_manifests` — derived dataset provenance.

Writes use explicit SQLite transactions. Deterministic primary keys make retry idempotent. A conflicting duplicate ID with different canonical payload is corruption and fails closed rather than `INSERT OR IGNORE` silently accepting divergence.

The journal may reference Phase 7 operational SQLite IDs but does not mutate Phase 7 accounting state.

## 12. Lifecycle journal assembly

A pure assembler builds a `TradeJournalEntry` from persisted Phase 7 lifecycle records and replay evidence.

Required invariants:

- position starts from exactly one initial risk decision;
- all fills belong to matching plan/attempt/market/side semantics;
- reduction fills cannot exceed opened quantity;
- funding events belong to the position's open interval;
- close quantity reconciles to zero;
- gross trading PnL, fees, funding, and net PnL reconcile with Phase 7 account/position records;
- no missing source fill/action/funding reference is silently ignored.

If lifecycle references cannot reconcile, journal assembly returns a structured inconsistency and the trade is excluded from valid research output until fixed.

## 13. Trade analytics

### 13.1 Net PnL

`net_pnl = gross_realized_trading_pnl - total_fees + funding_cash_pnl`

The sign convention must match Phase 7 accounting exactly.

### 13.2 Net R

`net_r = net_pnl / initial_risk_amount`

Initial risk comes from the originating Phase 6 approval actually used by Phase 7. If the risk amount is missing/zero/inconsistent, net R is unavailable and the journal entry fails research-readiness validation rather than inventing a denominator.

### 13.3 Realized entry/exit slippage

Store both currency and fractional slippage relative to explicit reference prices used by the corresponding Phase 7 plans. Slippage must be side-aware and signed so adverse slippage is positive drag.

### 13.4 MFE/MAE

For each position lifecycle, calculate excursions from genuine mark evidence within the open interval using `ACTIVE_ASSET_CTX.mark_px` observations.

For LONG:

- favorable excursion uses maximum mark above weighted entry;
- adverse excursion uses minimum mark below weighted entry.

For SHORT the signs reverse.

Store:

- absolute currency excursion on the actually open quantity at the observation;
- per-unit price excursion;
- fraction of entry;
- R multiple versus initial risk where defined;
- timestamp and source event key of the extremum.

If required mark evidence is missing across a known data gap, MFE/MAE is marked incomplete rather than presented as exact.

Partial reductions require quantity-aware excursion accounting for currency attribution; price-level excursion remains defined against entry for the lifecycle.

## 14. NO_TRADE observations

Journal every strategy `NO_TRADE` decision selected for the replay sample, with its feature/strategy/reason references and decision time.

Phase 8 does not label a NO_TRADE as good or bad. It only preserves the observation plus subsequent market evidence windows needed by Phase 9 missed-opportunity analysis.

To control storage, sampling policy must be explicit/versioned and deterministic (for example canonical hash sampling or configured interval), never random without a seed/provenance record.

## 15. Offline Parquet compaction

Phase 8 introduces genuine Parquet only in an offline research path.

### 15.1 Dependency boundary

Add an optional `research` dependency extra containing a pinned-compatible PyArrow major/minor range. Do not add PyArrow to base runtime dependencies or the always-on recorder path.

If the compaction command is used without the research extra installed, fail with a clear operator message. Core runtime/tests not requiring Parquet must remain installable without PyArrow.

### 15.2 Compaction behavior

For each validated source partition:

1. verify source segment digests;
2. parse and type-normalize every row;
3. preserve event/source/schema/market/exchange/receive/availability/event-key fields;
4. canonicalize high-volume payload fields into a stable column schema appropriate to the event kind;
5. sort deterministically by canonical replay order;
6. write actual Parquet with deterministic schema/options as far as the library permits;
7. fsync/atomically replace completed output files;
8. create a `CompactionManifest` containing exact source segment digests, output file SHA-256 digests, row counts, schemas, converter version, and partition coverage.

The raw JSONL files are never deleted or overwritten by compaction.

A compaction rerun with identical inputs/config must produce semantically identical rows/schema/manifests even if physical Parquet metadata contains library-specific variation. Research identity therefore hashes canonical semantic rows/schema/source digests rather than relying solely on byte-identical Parquet output.

## 16. Replay from JSONL versus Parquet

The replay API is source-agnostic behind a narrow `ReplaySource` protocol yielding canonical typed replay records.

Implementations:

- `JsonlReplaySource` — authoritative baseline and always available;
- `ParquetReplaySource` — optional research acceleration after manifest validation.

Tests require both sources to produce the same canonical replay record sequence for the same compacted evidence set. If they differ, the derived dataset is invalid.

## 17. Backtest/replay orchestration

Phase 8 provides a deterministic orchestration shell, not a parameter optimizer.

Conceptual interfaces:

```python
ReplaySource.iter_records(manifest) -> Iterator[ReplayRecord]
ReplayClock.advance(record) -> ReplayTimestamp
ReplayEngine.run(manifest, config) -> ReplayResult
```

`ReplayEngine` owns only time/evidence orchestration. It calls existing feature/strategy/risk/paper-execution boundaries through explicit adapters rather than duplicating trading logic.

The engine records all outcomes, including:

- candidate rejected by eligibility;
- shortlist/rank changes where journaled;
- `NO_TRADE`;
- risk rejection;
- pending/no-fill/partial/full execution;
- stop/thesis/emergency management;
- funding gaps/accruals;
- closed trade summaries.

Phase 8 does not create a second set of strategy or risk formulas.

## 18. Replay result

Define immutable `ReplayResult` with:

- manifest/run IDs;
- start/end timestamps;
- evidence class;
- counts of processed events, gaps, strategy decisions, risk approvals/rejections, execution attempts, fills, opens/closes, and journal observations;
- ordered closed trade IDs;
- final paper account state ID/value snapshot;
- data-quality completeness flags;
- deterministic result digest.

Do not add Phase 9 aggregate performance ranking/promotion logic here. Phase 8 exports trustworthy facts; Phase 9 judges them.

## 19. CLI/operator surfaces

Add offline-only commands with no exchange-write capability, for example:

- `cocomelon validate-recording --root ...`
- `cocomelon compact-recording --root ... --out ...`
- `cocomelon replay --manifest ... --journal ...`
- `cocomelon inspect-journal --journal ... --trade-id ...`

Commands default to read-only source evidence and explicit output paths. They never contact testnet or submit exchange actions.

Replay from a frozen manifest should be possible with networking disabled.

## 20. Failure behavior

Fail closed on:

- source segment hash mismatch;
- corrupt/truncated JSONL;
- unsupported schema version;
- partition/record provenance mismatch;
- conflicting duplicate deterministic IDs;
- replay evidence outside manifest bounds;
- unavailable/future evidence entering state early;
- required data gap or stale state that invalidates a downstream operation;
- microstructure execution requested from candle-only evidence;
- Parquet manifest/source mismatch;
- JSONL/Parquet canonical-sequence mismatch;
- journal lifecycle/accounting reconciliation mismatch;
- missing initial risk for net-R claims;
- incomplete mark evidence when claiming exact MFE/MAE;
- output transaction/write failure.

A failed research run does not mutate trusted source data or Phase 7 operational state.

## 21. Testing requirements

Use TDD and deterministic fixtures.

### Source validation

- valid recorder partitions pass;
- corrupt/truncated JSONL rejects;
- partition/date/kind/market mismatch rejects;
- source hashes stable;
- unsupported schema rejects;
- duplicate/conflicting event identity handled deterministically.

### Manifest

- same semantic inputs -> same manifest ID;
- any source digest/config/version/window/evidence-class change -> different ID;
- source mutation after manifest construction prevents replay;
- ambient ordering of files/dicts cannot change manifest identity.

### Event clock/lookahead

- receive-time ordering is authoritative for WS availability;
- stable tie-breakers produce identical order independent of file enumeration;
- future attractive candle/context cannot influence earlier decisions;
- post-latency L2 is required for execution;
- funding boundary preserves Phase 7 lookahead rules;
- data gaps propagate to health instead of interpolation.

### Evidence-class boundary

- candle replay cannot invoke or fabricate L2 IOC fills;
- microstructure replay uses recorded L2/trades only;
- no candle-to-book conversion exists;
- replay result records evidence class.

### Journal

- deterministic/idempotent observation/trade IDs;
- conflicting duplicate payload fails;
- NO_TRADE and risk rejection persist;
- full LONG/SHORT lifecycle references reconcile;
- restart store reads identical records;
- failed SQLite transaction leaves no partial journal state.

### Analytics

- LONG/SHORT net PnL and side-aware slippage;
- fees/funding attribution matches Phase 7;
- net R uses originating initial risk;
- MFE/MAE uses only in-lifecycle public mark evidence;
- incomplete/gapped mark history marks excursion quality incomplete;
- partial reductions preserve quantity-aware currency attribution.

### Compaction

- base install does not require PyArrow;
- research extra compacts to actual Parquet;
- raw JSONL is untouched;
- source/output manifests include hashes/counts/schema/provenance;
- deterministic canonical rows independent of segment enumeration;
- JSONL and Parquet replay sources yield identical canonical sequences;
- corruption/mismatched manifest rejects.

### End-to-end replay

A frozen fixture covers:

`validated source manifest -> ordered replay -> existing feature/strategy/risk boundaries -> Phase 7 IOC/account/manager -> closed paper trade -> journal entry -> analytics -> deterministic replay result`.

Run it twice from fresh stores and require identical semantic IDs/results.

A parallel `NO_TRADE`/risk-reject/no-fill fixture proves those outcomes are journaled without creating exposure.

### Boundary tests

- no network dependency in deterministic replay core;
- no testnet;
- no wallet/signing/private-account/live-order capability;
- no Phase 9 optimization or Phase 10 ML dependency;
- no candle-to-L2 fabrication;
- PyArrow is optional research-only, not core runtime/recorder dependency.

## 22. Exit criteria

Phase 8 is complete only when:

- every relevant Phase 4-7 decision/lifecycle outcome can be represented in immutable journal records with deterministic references;
- recorder segments can be validated and cryptographically identified without mutation;
- replay manifests capture exact evidence/config/code/schema provenance;
- replay ordering and as-of semantics are deterministic and lookahead-safe;
- candle/context and microstructure evidence classes are mechanically separated;
- a frozen deterministic replay can reproduce Phase 5 -> 6 -> 7 outcomes and closed-trade journal facts;
- journal lifecycle PnL/fees/funding reconciles to Phase 7 accounting;
- MFE/MAE/net-R/slippage/holding-time facts are computed without future-data leakage and expose incompleteness honestly;
- validated JSONL can be compacted offline into genuine versioned Parquet without changing/removing trusted raw evidence;
- JSONL and Parquet sources yield the same canonical replay sequence for the same data;
- duplicate/restart/write failures are idempotent/fail closed;
- full Python 3.12 install/compile/Ruff/mypy/pytest CI passes for core; research-extra CI/tests validate Parquet path;
- continuity docs record final verification/merge evidence;
- Phase 9+ remains unimplemented;
- live trading remains disabled and no private/live exchange capability is introduced.

## 23. Deferred work

Explicitly deferred:

- performance acceptance thresholds, OOS split policy, walk-forward grids, robustness/sensitivity judgments, and champion qualification — Phase 9;
- ML/champion-challenger model training — Phase 10;
- long-running mainnet shadow evidence accumulation — Phase 11;
- real Hyperliquid order/account adapter — Phase 12;
- live promotion and capital activation — Phase 13 with explicit user authorization.

Phase 8 builds trustworthy measurement infrastructure. It does not use that measurement infrastructure to declare the system profitable.