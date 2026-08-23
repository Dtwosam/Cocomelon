# Phase 8 — Journal, Replay, Deterministic Backtester, and Offline Compaction

**Status:** Approved autonomous build design  
**Date:** 2026-08-23  
**Base:** `main` after Phase 7 merge  
**Scope:** Phase 8 only. Phase 9 evaluation gates, Phase 10 ML, and live execution remain out of scope.

## 1. Objective

Phase 8 makes Cocomelon reproducible enough to answer, for any paper decision or closed trade:

- what market evidence was available;
- what scanner/features/strategy/risk/execution state produced the action;
- what code/config/schema versions were active;
- what fills, fees, funding, slippage, and management actions occurred;
- what the trade's MFE, MAE, gross/net PnL, and net R were;
- whether rerunning the same recorded evidence with the same versions produces the same result.

The phase does not attempt to prove an edge. It builds the trustworthy research machinery Phase 9 will use.

## 2. Non-negotiable boundaries

The following existing invariants remain locked:

1. Hyperliquid testnet is forbidden.
2. Mainnet observations are the only runtime/replay market evidence.
3. Live exchange execution remains disabled and no wallet/signing/private-account capability is added.
4. Candle/context evidence and microstructure evidence remain separate.
5. Historical L2/trades are never fabricated from candles.
6. Strategy cannot bypass Phase 6 risk authority.
7. Phase 7 execution may execute less than approved risk/notional but never more.
8. SQLite remains the operational/journal store; large analytical market datasets are compacted offline to a true columnar format.
9. The always-on Phase 3 recorder remains lightweight JSONL; no columnar dependency enters its liveness-critical write path.

## 3. Architecture

Phase 8 has six focused components:

1. **Journal contracts and append store** — immutable lifecycle records plus a materialized trade summary.
2. **Replay manifest** — hashes/versions that identify the exact code, config, schemas, and input evidence.
3. **Validated JSONL reader** — reads Phase 3 partitions line-by-line, validates provenance, and assigns stable source coordinates.
4. **Deterministic replay clock/orderer** — exposes evidence in the exact order it became available to the system.
5. **Offline columnar compactor** — converts validated JSONL records into versioned Parquet datasets without changing provenance.
6. **Backtest/trade analytics** — computes lifecycle outcomes, MFE/MAE, net R, cost attribution, and deterministic result digests.

These components are deliberately independent. The journal can be used by the live paper runtime without importing the offline compactor; the compactor can process Phase 3 files without importing execution; replay can run against JSONL or compacted rows through the same evidence contract.

## 4. Evidence ordering and lookahead rule

### 4.1 Authoritative availability time

For replay, **receive time is the authoritative availability timestamp**. An event is not visible to the replayed trading system before the timestamp at which Cocomelon recorded receiving it.

`exchange_time_ms` remains preserved as source provenance and may be used for exchange chronology/anomaly checks, but it must never make evidence available earlier than receive time.

### 4.2 Stable tie-breaks

Records sharing the same receive timestamp are ordered deterministically by:

1. receive timestamp;
2. normalized evidence-class priority only where an explicit dependency requires it;
3. recorder partition path;
4. segment number;
5. one-based line number.

The source coordinate `(relative_path, segment, line_number)` is immutable provenance and participates in replay/result digests.

### 4.3 Candle semantics

Recorded WebSocket candle updates are replayed as the exact updates that were received. A strategy that requires a closed candle may only consume it after the recorded candle end boundary has been observed under the existing feature-engine semantics.

A historical candle snapshot may be used only through a separate candle/context dataset contract that states its availability semantics explicitly. It may not be mixed into microstructure replay and may not be assigned invented L2/trade observations.

### 4.4 Microstructure semantics

Order-flow and L2 execution replay uses only recorded normalized `l2_book` and `trade` evidence. Missing depth remains missing. Replay never infers hidden liquidity or creates intermediate book states from candles.

## 5. Complete journal model

### 5.1 Append-only lifecycle events

The durable journal records immutable events using a common envelope:

- `journal_event_id` — deterministic content-derived ID;
- `event_type`;
- `occurred_at_ms`;
- `decision_id` when applicable;
- `market` when applicable;
- `schema_version`;
- `code_version`;
- `config_snapshot_id`;
- `payload` — canonical JSON with Decimal values encoded as strings;
- `payload_sha256`.

Required event families include:

- scanner eligibility/ranking/shortlist outcome;
- feature snapshot reference;
- strategy engine outputs;
- combined LONG/SHORT/NO_TRADE decision;
- risk approval/rejection and reason codes;
- paper order plan/attempt/fill/no-fill;
- position-open and position-management action;
- funding accrual/reconciliation;
- position reduction/close;
- account/equity snapshot relevant to a decision or close;
- data-quality/execution-health veto state.

The journal store rejects an existing `journal_event_id` with different content and treats exact duplicates idempotently.

### 5.2 Materialized trade summary

A closed paper trade has one deterministic summary keyed by `trade_id`, containing at minimum:

- opening decision/risk/order references;
- market and LONG/SHORT direction;
- entry/exit timestamps;
- weighted-average entry and exit prices;
- initial stop/invalidation;
- approved risk amount;
- maximum actual notional;
- gross PnL;
- taker fees;
- funding;
- realized slippage attribution;
- net PnL;
- net R = `net_pnl / approved_risk_amount`;
- MFE and MAE in currency and R;
- holding duration;
- exit reason and complete reason-code trace;
- equity before/after;
- evidence/replay manifest reference.

Materialized rows are derived outputs. The append journal is the reconstructable source of lifecycle truth.

## 6. Replay manifest

Every replay/backtest run requires an immutable manifest with:

- `manifest_schema_version`;
- `run_id` — deterministic hash of canonical manifest content;
- repository/code commit SHA;
- Python/runtime version;
- strategy/risk/execution/journal schema/config versions;
- canonical configuration SHA-256;
- evidence class: `CANDLE_CONTEXT` or `MICROSTRUCTURE`;
- input dataset identifiers;
- each input file/segment relative path, byte size, SHA-256, and recorder schema metadata;
- replay start/end receive timestamps;
- replay engine version;
- optional parent manifest/run for controlled reruns.

Mutable labels, wall-clock creation time, or local absolute filesystem paths do not participate in `run_id`.

The same canonical inputs produce the same `run_id`.

## 7. Phase 3 JSONL validation

The reader validates before replay or compaction:

- every input is a `.jsonl` segment, not a file merely renamed to a columnar extension;
- each line is valid JSON and has a supported record/schema type;
- normalized events preserve source, kind, market, receive time, exchange time if present, event key, and payload;
- gaps preserve stream, start/end, reason, source, and schema version;
- receive times are timezone-aware UTC-normalizable values;
- no NaN/Infinity numeric values enter canonical datasets;
- duplicate source coordinates are impossible;
- truncated/corrupt final lines fail the validation job rather than being silently dropped;
- segment SHA-256 and byte size are calculated before conversion.

A compaction/replay manifest names only validated inputs.

## 8. Offline columnar compaction

### 8.1 Dependency boundary

Columnar support is an **offline/research dependency**, not a required dependency of the always-on collector or paper runtime.

The preferred V1 implementation uses Polars to write real Parquet. If the optional research dependency is absent, compaction fails with a clear dependency error; it does not fall back to fake `.parquet` files.

### 8.2 Dataset layout

Compaction creates versioned dataset roots such as:

`datasets/v1/<dataset_id>/events/<receive_date>/<kind>/part-000001.parquet`

and a dataset manifest containing source-segment hashes and output-file hashes.

Rows retain, at minimum:

- record type/schema;
- source;
- market/stream;
- event kind;
- exchange timestamp;
- receive timestamp;
- event key;
- source relative path;
- segment number;
- line number;
- canonical payload JSON;
- input segment SHA-256.

Typed analytical columns may be added by event kind, but the canonical payload/provenance columns remain available so conversion is auditable.

### 8.3 Determinism

For identical validated inputs and compactor version:

- row order is stable;
- dataset ID is stable;
- logical row content is stable;
- manifest content is stable.

Parquet binary bytes are not used as the sole reproducibility identity because writer metadata/library versions can affect encoding. Reproducibility is asserted from canonical logical rows plus explicit writer version and output hashes.

## 9. Replay engine

The replay engine is a pure deterministic iterator over normalized evidence envelopes.

It exposes:

- `peek_time()`;
- `next_event()`;
- current replay receive time;
- evidence class;
- source coordinate;
- deterministic completion digest.

It does not sleep, read wall-clock time, call Hyperliquid, or mutate input files.

Replay consumers receive events only when the replay clock reaches their recorded availability time.

## 10. Deterministic backtester

### 10.1 Candle/context backtester

Consumes only candle/context-compatible evidence and runs the same deterministic feature/strategy/risk logic where the required inputs exist.

Execution must use an evidence model explicitly appropriate to the dataset. Candle-only runs may evaluate signal/decision outcomes and bar-based excursions, but they must not claim L2 fill realism or order-flow results.

### 10.2 Microstructure replay

When recorded L2/trade evidence is present, Phase 7's marketable-IOC simulator is reused for paper fills. This preserves visible-depth, latency, slippage, partial-fill, and cost semantics.

### 10.3 State isolation

Each backtest run starts from explicit initial paper account state and an empty isolated operational store. No live runtime SQLite state is read or mutated.

All IDs and outputs are deterministic for the same manifest.

## 11. Trade analytics

For each closed trade:

### MFE/MAE

Excursions use only marks/evidence available while the position was actually open.

For a LONG:

- favorable excursion = `max(mark - entry)`;
- adverse excursion = `max(entry - mark)`.

For a SHORT the signs reverse.

MFE/MAE are reported in price, currency/notional impact, and R where approved risk is known.

### Net R

`net_r = net_pnl / approved_risk_amount`

Approved risk is the inherited Phase 6 approved risk ceiling attached to the opening plan; it is not recomputed after the fact from realized loss.

### Cost attribution

At minimum report separately:

- gross trading PnL before explicit costs;
- taker fees;
- funding;
- entry slippage vs execution reference;
- exit slippage vs trigger/reference where available;
- net PnL.

No unexplained residual may be silently assigned to strategy PnL.

## 12. Reproducibility check

A replay/backtest result has a canonical result digest built from stable logical outputs, including:

- manifest `run_id`;
- ordered journal event IDs;
- ordered trade summary canonical forms;
- final paper-account canonical form;
- gap/anomaly summary.

Running the same inputs twice must produce the same digest.

Tests deliberately vary ambient Decimal context, filesystem absolute path, input enumeration order, and wall-clock time to prove those cannot change the logical result.

## 13. Failure behavior

Phase 8 fails closed on:

- corrupt/truncated JSONL;
- unsupported schema version;
- manifest hash/size mismatch;
- duplicate source coordinate with different content;
- non-monotonic replay availability after canonical ordering;
- evidence-class violation;
- missing required microstructure evidence for a microstructure execution claim;
- journal duplicate-ID content conflict;
- inability to atomically persist critical journal/materialized trade state;
- optional Parquet writer unavailable when compaction is explicitly requested.

A failed replay never emits a success result digest.

## 14. Storage and atomicity

Journal/control records use SQLite transactions and foreign/uniqueness constraints consistent with Phase 7's operational store discipline.

Critical lifecycle transitions that create a fill/position/account change and a journal event are committed atomically where they share a store. If a transition cannot be journaled, it must not be represented as successfully persisted execution state.

Offline datasets are written to a temporary dataset directory and atomically renamed into place only after all files and the manifest validate.

## 15. Testing strategy

Phase 8 is TDD-driven.

Required test groups:

1. journal contract canonicalization, deterministic IDs, idempotency, and conflict rejection;
2. journal SQLite atomicity/restart reconstruction;
3. JSONL validation including corrupt/truncated lines and provenance retention;
4. replay receive-time ordering and deterministic tie-breaks;
5. explicit lookahead traps where exchange time precedes receive time;
6. candle/context vs microstructure evidence-boundary tests;
7. manifest/run-ID determinism and file hash mismatch rejection;
8. optional Parquet compaction logical-row equivalence and provenance preservation;
9. MFE/MAE/net-R/cost attribution for LONG and SHORT fixtures;
10. whole-run reproducibility across repeated executions and changed ambient Decimal context;
11. source-level safety audit proving Phase 8 adds no testnet, wallet, signing, private-account, live-order, transfer, withdrawal, or ML-control path.

## 16. Phase 8 exit criteria

Phase 8 is complete only when:

- every Phase 5-7 paper lifecycle can be represented in the durable journal;
- a closed trade can be reconstructed from journal/provenance references;
- same manifest inputs reproduce the same logical result digest;
- lookahead tests pass using receive-time availability;
- candle/context and microstructure replay cannot be accidentally mixed;
- real recorded L2/trades are required for microstructure execution claims;
- validated Phase 3 JSONL compacts into a true versioned Parquet dataset with provenance preserved;
- MFE, MAE, net R, holding time, fees, funding, and slippage attribution are deterministic;
- full Python 3.12 install/compile/Ruff/mypy/pytest CI is green;
- live trading remains disabled and no new private/user exchange capability exists.

## 17. Explicitly deferred

Phase 8 does not add:

- statistical edge promotion gates;
- train/validation/test research policy beyond reproducibility plumbing;
- walk-forward reporting;
- ML training or model registry;
- long-running service deployment;
- live exchange adapter;
- dashboard/UI;
- automatic risk scaling.

Those remain Phase 9+ concerns under the approved build order.
