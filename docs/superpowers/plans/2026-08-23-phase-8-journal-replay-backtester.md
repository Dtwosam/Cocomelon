# Phase 8 Journal, Replay, Backtester, and Compaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Cocomelon paper decisions/trades reconstructable and deterministically replayable from recorded mainnet evidence, with reproducible analytics and offline Parquet compaction.

**Architecture:** Add an append-only lifecycle journal plus materialized trade summaries in SQLite, validate Phase 3 JSONL into provenance-preserving replay envelopes, order evidence by receive-time availability, and run deterministic candle/context or microstructure replay through explicit evidence-class boundaries. Keep Parquet/Polars offline-only and build result identity from canonical logical content rather than writer bytes alone.

**Tech Stack:** Python 3.12, Decimal, SQLite, hashlib/json/pathlib, pytest, Ruff, mypy, optional Polars research dependency for Parquet.

**Spec:** `docs/superpowers/specs/2026-08-23-phase-8-journal-replay-backtester-design.md`

## Global Constraints

- Hyperliquid testnet is forbidden.
- Runtime/replay market evidence is Hyperliquid mainnet only.
- Receive time is authoritative evidence availability time; exchange time never makes evidence available earlier.
- Candle/context and microstructure evidence classes must remain distinct.
- Never fabricate historical L2/trades from candles.
- Live trading remains disabled; add no wallet/signing/private-account/transfer/withdrawal/live-order path.
- SQLite stores journal/control state; true Parquet is produced only by an offline optional research dependency.
- Phase 3's always-on JSONL recorder remains unchanged as the trusted ingestion log.
- Authoritative arithmetic uses explicit Decimal operations and must not depend on ambient Decimal context.

---

### Task 1: Journal and replay domain contracts

**Files:**
- Replace: `src/cocomelon/domain/journal.py`
- Create: `src/cocomelon/domain/replay.py`
- Test: `tests/test_journal_contracts.py`
- Test: `tests/test_replay_contracts.py`

**Interfaces:**
- Produces: `JournalEvent`, `JournalEventType`, `TradeSummary`, `EvidenceClass`, `SourceCoordinate`, `ReplayEvidence`, `ReplayInputFile`, `ReplayManifest`.
- Produces helpers: `canonical_json(value: object) -> str`, `sha256_text(value: str) -> str`.

- [ ] **Step 1: Write journal contract tests**

Cover deterministic event IDs, canonical Decimal-as-string payloads, timezone-independent integer timestamps, LONG/SHORT trade summaries, positive approved risk, and `net_r == net_pnl / approved_risk_amount` under a fixed local Decimal context.

Example assertion:

```python
first = JournalEvent.create(
    event_type=JournalEventType.STRATEGY_DECISION,
    occurred_at_ms=1000,
    code_version="abc123",
    config_snapshot_id="cfg-1",
    payload={"score": Decimal("0.2500"), "reasons": ("TREND",)},
    decision_id="decision-1",
    market=MarketId(dex="", coin="SOL"),
)
second = JournalEvent.create(...same logical values...)
assert first.journal_event_id == second.journal_event_id
assert '"0.2500"' in first.payload_json
```

- [ ] **Step 2: Run journal tests and confirm RED**

Run: `python -m pytest -q tests/test_journal_contracts.py`
Expected: import/attribute failures for the new contracts.

- [ ] **Step 3: Implement journal contracts**

Use frozen/slots dataclasses and `StrEnum`. `JournalEvent.create` canonicalizes payload, hashes the canonical envelope with SHA-256, and stores the full 64-character hex digest. Reject blank code/config IDs, negative timestamps, non-finite Decimal values, and invalid trade summaries. `TradeSummary` stores explicit `gross_pnl`, `fees`, `funding`, `entry_slippage`, `exit_slippage`, `net_pnl`, `approved_risk_amount`, `mfe_pnl`, `mae_pnl`, `holding_ms`, and reason trace; expose deterministic `net_r`, `mfe_r`, and `mae_r` properties.

- [ ] **Step 4: Write replay contract tests**

Assert `SourceCoordinate` ordering, supported evidence classes, file digest validation fields, canonical manifest ID stability across input enumeration order, and rejection of absolute input paths.

- [ ] **Step 5: Run replay tests and confirm RED**

Run: `python -m pytest -q tests/test_replay_contracts.py`
Expected: import failure for `cocomelon.domain.replay`.

- [ ] **Step 6: Implement replay contracts**

`ReplayInputFile` fields: `relative_path`, `size_bytes`, `sha256`, `schema_version`. `ReplayManifest.create` sorts inputs by relative path and hashes canonical content excluding wall-clock creation time and absolute paths. `ReplayEvidence` carries `evidence_class`, `receive_time_ms`, optional `exchange_time_ms`, `record_type`, optional `market`, `event_kind`, `event_key`, `payload_json`, and `SourceCoordinate`.

- [ ] **Step 7: Run focused + static gates**

Run:

```bash
python -m compileall -q src tests
python -m ruff check src tests
python -m mypy src
python -m pytest -q tests/test_journal_contracts.py tests/test_replay_contracts.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/cocomelon/domain/journal.py src/cocomelon/domain/replay.py tests/test_journal_contracts.py tests/test_replay_contracts.py
git commit -m "feat: define Phase 8 journal replay contracts"
```

---

### Task 2: Append-only SQLite journal store

**Files:**
- Create: `src/cocomelon/journal/__init__.py`
- Create: `src/cocomelon/journal/store.py`
- Test: `tests/test_journal_store.py`

**Interfaces:**
- Consumes: Task 1 `JournalEvent`, `TradeSummary`.
- Produces: `JournalStore(path: str | Path)`, `append_event(event)`, `upsert_trade_summary(summary)`, `load_events(...)`, `load_trade_summary(trade_id)`.

- [ ] **Step 1: Write failing idempotency/conflict tests**

Create a temporary SQLite DB. Append the same event twice and assert one stored row. Construct an event with the same `journal_event_id` but altered payload and assert `JournalConflictError`.

- [ ] **Step 2: Write failing atomicity/restart tests**

Persist event + summary in one transaction via `commit_trade_close(event, summary)`, inject an exception between writes, and assert neither is visible after reopening. Then test successful close survives restart exactly once.

- [ ] **Step 3: Run RED**

Run: `python -m pytest -q tests/test_journal_store.py`
Expected: missing package/store.

- [ ] **Step 4: Implement schema and store**

Use SQLite foreign keys, WAL-compatible ordinary transactions, `journal_events` keyed by `journal_event_id`, and `trade_summaries` keyed by `trade_id`. Store canonical JSON text and SHA-256. Exact duplicates are no-ops; ID/content mismatches raise `JournalConflictError`.

- [ ] **Step 5: Implement atomic trade-close write**

`commit_trade_close` begins one transaction, inserts the event, inserts/replaces only an identical-or-new summary, and commits. Roll back on any error.

- [ ] **Step 6: Run focused + static gates**

Run: `python -m ruff check src tests && python -m mypy src && python -m pytest -q tests/test_journal_store.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/cocomelon/journal tests/test_journal_store.py
git commit -m "feat: add append only journal store"
```

---

### Task 3: Validated Phase 3 JSONL reader

**Files:**
- Create: `src/cocomelon/replay/__init__.py`
- Create: `src/cocomelon/replay/jsonl.py`
- Test: `tests/test_replay_jsonl.py`

**Interfaces:**
- Consumes: Task 1 replay contracts and Phase 3 recorder schema.
- Produces: `validate_jsonl_segment(path, *, root, evidence_class) -> ValidatedSegment` and `iter_validated_evidence(segment) -> Iterator[ReplayEvidence]`.

- [ ] **Step 1: Write valid normalized-event/gap fixtures in tests**

Use recorder-compatible JSON lines containing source, schema, event key, UTC receive time, optional exchange time, payload, and gap records.

- [ ] **Step 2: Add corrupt/truncated/schema/non-finite/path tests**

Assert failures for invalid JSON final line, unsupported schema, missing required provenance, `NaN`, non-`.jsonl`, and paths escaping the supplied root.

- [ ] **Step 3: Add receive-time lookahead trap**

Create an event whose exchange timestamp is `1000` but receive timestamp is `5000`; assert resulting `ReplayEvidence.receive_time_ms == 5000` and exchange time remains `1000` only as provenance.

- [ ] **Step 4: Run RED**

Run: `python -m pytest -q tests/test_replay_jsonl.py`
Expected: missing replay JSONL module.

- [ ] **Step 5: Implement strict line reader**

Read bytes, compute whole-file SHA-256/size, decode UTF-8, reject a file not ending in newline, parse every non-empty line, and assign one-based line numbers. Convert receive ISO strings to UTC epoch milliseconds without using local timezone.

- [ ] **Step 6: Implement record normalization**

Support Phase 3 `normalized_event` and `data_gap`. Preserve payload as canonical JSON and source coordinate as relative path + parsed segment number + line number.

- [ ] **Step 7: Run focused + static gates**

Run: `python -m ruff check src tests && python -m mypy src && python -m pytest -q tests/test_replay_jsonl.py`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/cocomelon/replay tests/test_replay_jsonl.py
git commit -m "feat: validate Phase 3 replay evidence"
```

---

### Task 4: Deterministic replay orderer and evidence boundaries

**Files:**
- Create: `src/cocomelon/replay/engine.py`
- Test: `tests/test_replay_engine.py`

**Interfaces:**
- Consumes: `ReplayEvidence` sequences.
- Produces: `ReplayEngine(evidence_class, rows)`, `peek_time()`, `next_event()`, `completion_digest`.

- [ ] **Step 1: Write receive-order and tie-break tests**

Provide rows out of input order and assert output sorts by `(receive_time_ms, relative_path, segment, line_number)` while preserving exchange timestamps unchanged.

- [ ] **Step 2: Write evidence-class rejection tests**

A `CANDLE_CONTEXT` engine rejects L2/trade rows; a `MICROSTRUCTURE` run may contain context/candle rows but execution claims require recorded L2 evidence. Explicitly reject an attempt to label candle-derived rows as `l2_book`/`trade`.

- [ ] **Step 3: Write determinism test**

Shuffle the same logical rows across several input list orders and assert identical event order and completion digest.

- [ ] **Step 4: Run RED**

Run: `python -m pytest -q tests/test_replay_engine.py`
Expected: missing replay engine.

- [ ] **Step 5: Implement pure replay engine**

No sleeping, wall clock, network, or file writes. The engine copies/sorts immutable rows and hashes canonical emitted coordinates/content into `completion_digest` only after exhaustion.

- [ ] **Step 6: Run focused + static gates**

Run: `python -m ruff check src tests && python -m mypy src && python -m pytest -q tests/test_replay_engine.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/cocomelon/replay/engine.py tests/test_replay_engine.py
git commit -m "feat: add deterministic replay engine"
```

---

### Task 5: Replay manifest builder and verification

**Files:**
- Create: `src/cocomelon/replay/manifest.py`
- Test: `tests/test_replay_manifest.py`

**Interfaces:**
- Consumes: Task 1 contracts and Task 3 validated segments.
- Produces: `build_replay_manifest(...) -> ReplayManifest`, `verify_replay_inputs(manifest, root) -> tuple[ValidatedSegment, ...]`.

- [ ] **Step 1: Write deterministic manifest tests**

Assert same files in different enumeration order produce same `run_id`; changing one byte, config hash, code SHA, replay engine version, or evidence class changes it.

- [ ] **Step 2: Write mismatch tests**

After manifest creation mutate a segment and assert verification rejects size/hash mismatch before yielding evidence.

- [ ] **Step 3: Run RED**

Run: `python -m pytest -q tests/test_replay_manifest.py`
Expected: missing manifest functions.

- [ ] **Step 4: Implement manifest builder/verifier**

Use Task 3 file hashes and canonical sorted input metadata. Reject blank code/config/version values and empty input sets.

- [ ] **Step 5: Run focused + static gates and commit**

Run: `python -m ruff check src tests && python -m mypy src && python -m pytest -q tests/test_replay_manifest.py`
Expected: PASS.

Commit: `feat: add reproducible replay manifests`.

---

### Task 6: Trade MFE/MAE, net-R, and cost attribution

**Files:**
- Create: `src/cocomelon/journal/analytics.py`
- Test: `tests/test_trade_analytics.py`

**Interfaces:**
- Produces: `ExcursionPoint(timestamp_ms, mark_price)`, `build_trade_summary(...) -> TradeSummary`.

- [ ] **Step 1: Write LONG fixture test**

Use entry `100`, quantity `10`, approved risk `50`, marks `98, 103, 105, 99`, exit `102`, explicit fees/funding/slippage. Assert MFE/MAE, holding time, gross/net PnL, and exact net R.

- [ ] **Step 2: Write SHORT mirror test**

Verify favorable/adverse signs reverse correctly and no ambient Decimal rounding context changes results.

- [ ] **Step 3: Write time-window test**

Marks before entry and after exit must not affect MFE/MAE.

- [ ] **Step 4: Run RED**

Run: `python -m pytest -q tests/test_trade_analytics.py`
Expected: missing analytics module.

- [ ] **Step 5: Implement analytics with explicit Decimal context**

Filter excursion points to `[entry_timestamp_ms, exit_timestamp_ms]`, compute quantity-scaled excursion PnL, cost attribution, and build a validated Task 1 `TradeSummary`.

- [ ] **Step 6: Run focused + static gates and commit**

Run: `python -m ruff check src tests && python -m mypy src && python -m pytest -q tests/test_trade_analytics.py`
Expected: PASS.

Commit: `feat: add deterministic trade analytics`.

---

### Task 7: Offline Polars/Parquet compactor

**Files:**
- Modify: `pyproject.toml`
- Create: `src/cocomelon/replay/compact.py`
- Test: `tests/test_replay_compaction.py`

**Interfaces:**
- Produces: `compact_validated_segments(segments, output_root, *, dataset_schema_version=1) -> DatasetManifest`.

- [ ] **Step 1: Add optional research dependency**

Add a `research` optional dependency containing a bounded Polars version compatible with Python 3.12. Do not add Polars to base runtime dependencies or `dev` unless CI explicitly installs research tests separately.

- [ ] **Step 2: Write dependency-boundary test**

Mock import absence and assert a clear `ColumnarDependencyError` only when compaction is invoked; importing collector/recorder/replay core must not import Polars.

- [ ] **Step 3: Write true-Parquet provenance test**

With Polars available, compact a tiny validated segment and read it back. Assert stable logical row order and preserved source path/segment/line/hash/payload. Verify the output begins with a real Parquet writer result, not copied JSONL text.

- [ ] **Step 4: Write deterministic dataset-ID test**

Same logical inputs in different enumeration order produce the same dataset ID/manifest logical content.

- [ ] **Step 5: Run RED in research environment**

Run: `python -m pytest -q tests/test_replay_compaction.py`
Expected: missing compactor.

- [ ] **Step 6: Implement lazy Polars import and atomic dataset publish**

Write to `<dataset_id>.tmp`, produce event-kind/date Parquet parts in canonical row order, write canonical manifest JSON, hash outputs, then rename temp directory to final dataset directory only after validation.

- [ ] **Step 7: Run research + base gates**

Run both the normal suite without the optional package requirement and the compaction suite in an environment with `.[research]` installed.

- [ ] **Step 8: Commit**

Commit: `feat: compact replay evidence to parquet`.

---

### Task 8: Runtime journal integration across Phase 5-7 lifecycle

**Files:**
- Modify focused orchestration/execution integration files identified by existing Phase 7 runtime tests.
- Add: `src/cocomelon/journal/events.py`
- Test: `tests/test_phase8_lifecycle_journal.py`

**Interfaces:**
- Consumes existing scanner/strategy/risk/execution/account contracts.
- Produces deterministic conversion functions from existing domain objects to Task 1 `JournalEvent` without changing trading decisions.

- [ ] **Step 1: Map existing lifecycle objects**

Write pure conversion tests for strategy decision, risk decision, order plan/attempt/fill, manager action, funding event, and account/close outcome. Assert payloads contain IDs/reason codes/config versions already carried by source objects.

- [ ] **Step 2: Add NO_TRADE journal test**

A NO_TRADE decision must still produce a durable journal event and must not fabricate risk/order/fill records.

- [ ] **Step 3: Add atomic successful-close integration test**

Drive an existing Phase 5 -> 6 -> 7 fixture lifecycle, write journal records, and assert the closed trade summary references the exact opening decision/risk/plan IDs.

- [ ] **Step 4: Implement converters/integration hook**

Keep business logic unchanged. Journal creation is downstream of the authoritative objects; if critical journal persistence fails during an atomic execution transition, fail closed per the Phase 8 spec.

- [ ] **Step 5: Run full regression**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

Commit: `feat: journal paper trading lifecycle`.

---

### Task 9: Deterministic candle/context and microstructure backtest harness

**Files:**
- Create: `src/cocomelon/replay/backtest.py`
- Test: `tests/test_backtest_harness.py`

**Interfaces:**
- Produces: `BacktestConfig`, `BacktestResult`, `run_backtest(manifest, evidence, initial_account, pipeline) -> BacktestResult`.

- [ ] **Step 1: Write deterministic NO_TRADE candle/context test**

Use a minimal replay fixture that produces no eligible trade. Run twice with changed wall clock and ambient Decimal context; assert same result digest and zero fabricated fills.

- [ ] **Step 2: Write microstructure fill test**

Use recorded-style `l2_book` evidence and existing Phase 7 IOC simulator; assert actual visible depth determines fills and no candle data is used as a replacement book.

- [ ] **Step 3: Write missing-L2 rejection test**

A run requesting microstructure execution with only candle/context evidence must fail with an evidence-boundary error rather than create a fill.

- [ ] **Step 4: Implement isolated deterministic harness**

The harness receives an explicit pure pipeline callback/object so Phase 8 can reuse Phase 4-7 components without network or wall-clock access. Start from supplied paper account; return ordered journal IDs, summaries, final account canonical JSON, anomaly/gap summary, and result digest.

- [ ] **Step 5: Run focused + full gates and commit**

Run normal static gates and `python -m pytest -q`.

Commit: `feat: add deterministic backtest harness`.

---

### Task 10: Reproducibility, safety audit, CLI, and Phase 8 closeout

**Files:**
- Modify: `src/cocomelon/cli.py`
- Create: `tests/test_phase8_reproducibility.py`
- Create: `tests/test_phase8_boundaries.py`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHATGPT_PROJECT_SOURCE.md`

**Interfaces:**
- Adds read/offline commands only: manifest build/verify, replay summary, and compaction. No exchange write actions.

- [ ] **Step 1: Add whole-run reproducibility test**

Run the same small fixture twice with input files enumerated differently, different absolute temp roots, changed ambient Decimal context, and different wall-clock time. Assert identical manifest run ID, journal IDs, trade summaries, final account canonical representation, and result digest.

- [ ] **Step 2: Add source-level forbidden-capability audit**

Scan new Phase 8 modules for testnet URLs, wallet/private-key/signing/withdraw/transfer/private-user subscription/live-order adapter/ML-control capability. Allow harmless words only where tests explicitly describe the prohibition.

- [ ] **Step 3: Add offline CLI commands**

Commands validate local recorded inputs and print canonical IDs/summaries. They must not initialize Hyperliquid exchange clients or require secrets.

- [ ] **Step 4: Run complete verification**

Run:

```bash
python -m pip install -e ".[dev]"
python -m compileall -q src tests scripts
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
```

Then separately verify research/Parquet tests with the optional dependency installed.

Expected: all PASS.

- [ ] **Step 5: Update continuity docs with exact evidence**

Record final branch head, CI run/job IDs, test/static evidence, Phase 8 exit-criteria audit, and Phase 9 as next phase only after Phase 8 is fully green.

- [ ] **Step 6: Open/ready PR only after all gates are green**

Use expected-head protection for merge. Do not activate Phase 9 before the Phase 8 merge is verified on `main`.
