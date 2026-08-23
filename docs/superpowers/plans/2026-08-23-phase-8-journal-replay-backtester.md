# Phase 8 Journal, Replay, Backtester, and Compaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Cocomelon decisions and paper-trade outcomes durably journaled, deterministically replayable, analytically measurable, and compactable from trusted Phase 3 JSONL into provenance-preserving Parquet.

**Architecture:** Keep compact lifecycle facts in SQLite, define immutable content-addressed replay manifests, replay observations strictly by system availability time, and keep candle/context backtests separate from genuine L2/trade microstructure replay. Parquet compaction is offline only and uses optional PyArrow; it never enters the always-on recorder path.

**Tech Stack:** Python 3.12, stdlib dataclasses/Decimal/hashlib/json/sqlite3/pathlib, existing Cocomelon Phase 3-7 contracts, pytest/Ruff/mypy, optional PyArrow for offline Parquet.

**Spec:** `docs/superpowers/specs/2026-08-23-phase-8-journal-replay-backtester-design.md`

## Global Constraints

- Hyperliquid mainnet only; testnet remains forbidden.
- Execution remains paper-only; Phase 8 adds no exchange-order, wallet, signing, transfer, withdrawal, or private-user capability.
- Phase 6 remains sole authority for new exposure.
- JSONL is the trusted recorder log; Parquet is offline compaction only.
- Candle/context and microstructure evidence classes remain separate by type/public interface.
- Deterministic identifiers and monetary analytics use canonical serialization and Decimal-safe arithmetic.
- Missing/corrupt/inconsistent evidence fails closed; no interpolation of order books/trades.

---

### Task 1: Canonical replay and journal domain contracts

**Files:**
- Create: `src/cocomelon/domain/replay.py`
- Test: `tests/test_replay_domain.py`

**Interfaces:**
- Produces `EvidenceClass`, `JournalRecordType`, `InputArtifact`, `ReplayManifest`, `ReplayEvent`, `TradeAnalytics`, `canonical_json_bytes()`, `sha256_hex()`.
- Later tasks depend on deterministic `ReplayManifest.replay_id` and `JournalRecord.journal_id` semantics.

- [ ] Write failing tests proving mapping order and ambient Decimal context cannot change hashes; evidence classes are exactly `candle_context` and `microstructure`; manifest input order is canonical; non-finite Decimal and naive datetime values are rejected.
- [ ] Run `python -m pytest -q tests/test_replay_domain.py` and verify RED because the module does not exist.
- [ ] Implement frozen/slotted dataclasses and canonical JSON normalization using sorted keys, Decimal strings, enum values, timezone-aware UTC timestamps, and SHA-256.
- [ ] Run the focused tests and static gates; keep the implementation free of PyArrow and execution/private-account imports.
- [ ] Commit `feat: add deterministic replay domain contracts`.

### Task 2: Append-only SQLite lifecycle journal

**Files:**
- Create: `src/cocomelon/journal/store.py`
- Create: `src/cocomelon/journal/__init__.py`
- Test: `tests/test_journal_store.py`

**Interfaces:**
- `JournalStore(path: str | Path)`
- `append(record: JournalRecord) -> None`
- `append_many(records: Sequence[JournalRecord]) -> None`
- `get(journal_id: str) -> JournalRecord | None`
- `iter_records(*, replay_id: str | None = None) -> tuple[JournalRecord, ...]`

- [ ] Write RED tests for idempotent same-record append, conflicting same-ID rejection, atomic `append_many`, deterministic retrieval order, restart persistence, and rollback under an injected SQLite error.
- [ ] Implement a versioned schema with immutable logical fields plus recorded-at metadata; use explicit transactions and unique primary-key constraints.
- [ ] Ensure payload canonical JSON is compared on duplicate IDs and no silent overwrite path exists.
- [ ] Run focused pytest, Ruff, mypy; commit `feat: add append-only lifecycle journal`.

### Task 3: Lifecycle journal adapters

**Files:**
- Create: `src/cocomelon/journal/adapters.py`
- Test: `tests/test_journal_adapters.py`

**Interfaces:**
- Pure functions converting scanner snapshots, Phase 5 strategy decisions, Phase 6 risk decisions, Phase 7 order plans/attempts/fills/positions/actions/funding/account snapshots, and `DataGap` into `JournalRecord` values.

- [ ] Add RED fixture tests for LONG, SHORT, NO_TRADE, approved risk, rejected risk, zero-fill IOC, partial fill, stop close, funding accrual, and account snapshot records.
- [ ] Implement adapters without mutating source objects or duplicating full market books into SQLite payloads.
- [ ] Verify reason codes and cross-IDs survive exact round trip.
- [ ] Commit `feat: journal full paper lifecycle decisions`.

### Task 4: Strict Phase 3 JSONL validation and input artifacts

**Files:**
- Create: `src/cocomelon/replay/jsonl.py`
- Create: `src/cocomelon/replay/__init__.py`
- Test: `tests/test_replay_jsonl.py`

**Interfaces:**
- `validate_jsonl_file(path: Path, *, recorder_root: Path) -> ValidatedJsonlFile`
- `iter_validated_records(...) -> Iterator[ReplayEvent]`

- [ ] Add RED tests using existing recorder fixtures plus corrupt JSON, partition mismatch, unsupported schema, duplicate conflicting event keys, malformed decimals, and mutation-after-validation.
- [ ] Reconstruct event/gap semantics from recorder records while retaining source path and zero-based line number.
- [ ] Compute SHA-256 and byte size; reject file mutation when later opened against its `InputArtifact`.
- [ ] Commit `feat: validate recorder evidence for replay`.

### Task 5: Replay manifest builder and deterministic event ordering

**Files:**
- Create: `src/cocomelon/replay/manifest.py`
- Create: `src/cocomelon/replay/order.py`
- Test: `tests/test_replay_manifest.py`
- Test: `tests/test_replay_order.py`

**Interfaces:**
- `build_replay_manifest(...) -> ReplayManifest`
- `replay_sort_key(event: ReplayEvent) -> tuple[...]`
- `merge_replay_events(inputs: Sequence[ValidatedJsonlFile]) -> Iterator[ReplayEvent]`

- [ ] RED tests prove filesystem enumeration order never affects replay ID, receive-time availability dominates exchange time, ties resolve deterministically, and no event can move before receive time.
- [ ] Add adversarial same-timestamp fixtures across candle, context, book, trade, and gap records.
- [ ] Implement the versioned fixed priority table and deterministic k-way merge/sort suitable for bounded fixture datasets first; optimize only if measured later.
- [ ] Commit `feat: add deterministic replay manifests and ordering`.

### Task 6: Evidence-class boundary and lookahead-safe replay state

**Files:**
- Create: `src/cocomelon/replay/state.py`
- Test: `tests/test_replay_state.py`
- Modify: existing Phase 4/5 replay-facing helpers only where an explicit observation-time parameter is missing.

**Interfaces:**
- `ReplayState(evidence_class: EvidenceClass)`
- `apply(event: ReplayEvent) -> None`
- typed accessors that return only observations available at `now_ms` and reject microstructure access in candle-context mode.

- [ ] RED tests demonstrate a future profitable candle/book cannot affect an earlier decision; a candle-context state cannot provide L2/trade evidence; gaps mark required streams unavailable.
- [ ] Implement fail-closed freshness/data-gap semantics using receive-time cutoffs.
- [ ] Commit `feat: enforce replay evidence and lookahead boundaries`.

### Task 7: Candle/context backtester orchestration

**Files:**
- Create: `src/cocomelon/backtest/candle_context.py`
- Create: `src/cocomelon/backtest/__init__.py`
- Test: `tests/test_candle_context_backtest.py`

**Interfaces:**
- `run_candle_context_backtest(manifest, events, config) -> BacktestResult`

- [ ] RED tests cover deterministic LONG/SHORT/NO_TRADE decision sequences, risk veto journaling, and identical result digest on repeated runs.
- [ ] Route through existing scanner/strategy/risk contracts where evidence supports them; mark execution assumptions explicitly as candle/context class and never claim L2 fill precision.
- [ ] Journal all decisions and outcomes in a replay namespace.
- [ ] Commit `feat: add deterministic candle context backtester`.

### Task 8: Genuine microstructure replay through Phase 7 IOC

**Files:**
- Create: `src/cocomelon/backtest/microstructure.py`
- Test: `tests/test_microstructure_backtest.py`

**Interfaces:**
- `run_microstructure_backtest(...) -> BacktestResult`

- [ ] RED tests replay actual normalized L2/trade fixture structures into the existing Phase 7 `simulate_ioc`/paper execution path; no candle may satisfy required book evidence.
- [ ] Cover partial fill, zero fill, slippage cap, stop trigger followed by reduce-only IOC, duplicate evidence, and data-gap failure.
- [ ] Verify actual fills remain bounded by Phase 6 approved notional/risk.
- [ ] Commit `feat: replay recorded microstructure through paper IOC`.

### Task 9: Trade analytics and attribution

**Files:**
- Create: `src/cocomelon/replay/analytics.py`
- Test: `tests/test_trade_analytics.py`

**Interfaces:**
- `compute_trade_analytics(...) -> TradeAnalytics`

- [ ] RED tests cover LONG and SHORT MFE/MAE, partial entries/exits, fees, positive/negative funding, holding time, net R, exit reason, and missing/gapped metric evidence returning explicit unknown reason.
- [ ] Enforce `net_pnl = gross_realized_pnl - fees + funding`; report slippage separately from actual fill-based PnL so it is never double-counted.
- [ ] Commit `feat: add deterministic trade analytics`.

### Task 10: Offline Parquet compactor

**Files:**
- Modify: `pyproject.toml` to add optional `research = ["pyarrow>=18,<22"]`
- Create: `src/cocomelon/replay/compact.py`
- Test: `tests/test_parquet_compaction.py`

**Interfaces:**
- `compact_to_parquet(manifest: ReplayManifest, output_root: Path) -> DatasetManifest`

- [ ] RED tests skip only when PyArrow is genuinely absent; CI installs the research extra for this task/phase.
- [ ] Prove row count/order/provenance preservation, manifest input/output digests, schema version, PyArrow version capture, temp-output atomic promotion, and failure cleanup.
- [ ] Lazy-import PyArrow exclusively inside compaction code; add a boundary test proving recorder/runtime modules do not import it.
- [ ] Commit `feat: compact validated recorder data to parquet`.

### Task 11: Offline CLI commands

**Files:**
- Modify: `src/cocomelon/cli.py`
- Create: `src/cocomelon/replay/cli.py`
- Test: `tests/test_phase8_cli.py`

**Interfaces:**
- `cocomelon replay validate`
- `cocomelon replay run`
- `cocomelon compact parquet`
- `cocomelon journal inspect`

- [ ] RED tests cover deterministic JSON summaries, invalid evidence class, corrupt input, missing research dependency, and explicit rejection of live/testnet/private-key arguments.
- [ ] Keep commands offline: no exchange endpoint/order APIs.
- [ ] Commit `feat: add Phase 8 offline replay CLI`.

### Task 12: End-to-end reproducibility and safety boundary

**Files:**
- Create: `tests/test_phase8_end_to_end.py`
- Create: `tests/test_phase8_boundaries.py`

**Interfaces:**
- Full Phase 3 evidence -> replay manifest -> Phase 4/5 -> Phase 6 -> Phase 7 paper execution -> journal -> analytics -> result digest.

- [ ] Add an end-to-end recorded-fixture lifecycle and prove two independent runs produce identical journal logical sequence, final account values, analytics, and result digest.
- [ ] Add adversarial future-data leakage, mutated JSONL, duplicate conflict, and restart tests.
- [ ] Add source boundary checks excluding testnet, wallet/private-key/signing, transfer/withdrawal, private-user subscription, live-order adapter, ML libraries, and candle-to-book fabrication.
- [ ] Run `python -m compileall -q src tests scripts`, `python -m ruff check src tests scripts`, `python -m mypy src`, and full `python -m pytest -q`.
- [ ] Commit `test: verify Phase 8 deterministic replay boundaries`.

### Task 13: Phase completion evidence and source-of-truth update

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/CHATGPT_PROJECT_SOURCE.md`
- Modify: `docs/DECISIONS.md` only if implementation required a real architecture decision not already locked by D-015/D-021.

- [ ] Record exact final branch head, CI run/job, test evidence, exit-criteria audit, and Phase 9 as the next phase only after all Phase 8 criteria pass.
- [ ] Verify portable source agrees with authoritative docs and live trading remains disabled.
- [ ] Commit `docs: record Phase 8 completion evidence`.
