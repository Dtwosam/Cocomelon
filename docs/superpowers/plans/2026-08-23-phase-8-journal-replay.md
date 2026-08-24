# Phase 8 Journal, Replay, and Analytical Compaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, lookahead-safe journal/replay system that reconstructs Phase 4-7 paper-trading outcomes from trusted mainnet evidence and compacts validated JSONL offline into provenance-preserving Parquet.

**Architecture:** Keep trusted Phase 3 JSONL immutable, validate/index it into canonical replay records, drive existing deterministic trading boundaries from an explicit event clock, and store only low-volume research/journal metadata in a separate SQLite store. Parquet is an optional offline derivative behind a research extra and must round-trip to the same canonical replay sequence as JSONL.

**Tech Stack:** Python 3.12, stdlib dataclasses/`decimal`/`hashlib`/`json`/`sqlite3`/`pathlib`, pytest, Ruff, mypy, existing Phase 3 recorder and Phase 4-7 contracts, optional PyArrow in a `research` extra only.

**Spec:** `docs/superpowers/specs/2026-08-23-phase-8-journal-replay-design.md`

## Global Constraints

- Hyperliquid testnet is forbidden.
- Runtime/live exchange writes remain disabled and outside Phase 8.
- Trusted Phase 3 JSONL is immutable source evidence; Phase 8 readers never rewrite it.
- SQLite is for journal/control metadata; high-volume source/derived market data remains JSONL/columnar.
- Candle/context replay and microstructure replay are mechanically distinct evidence classes.
- Candle data may never be converted into synthetic L2/trade evidence.
- WebSocket evidence availability uses receive time, never an earlier exchange timestamp.
- Replay kernels use explicit timestamps and no wall-clock/network/random state.
- Financial calculations use deterministic `Decimal` semantics compatible with Phase 6-7.
- PyArrow is optional research tooling only; it may not enter base runtime dependencies or Phase 3 recorder imports.
- Phase 8 measures/reproduces behavior; it does not tune parameters, implement Phase 9 evaluation gates, train ML, or enable live trading.

---

### Task 1: Replace the journal placeholder with deterministic Phase 8 domain contracts

**Files:**
- Modify: `src/cocomelon/domain/journal.py`
- Create: `src/cocomelon/domain/replay.py`
- Test: `tests/test_journal_contracts.py`
- Test: `tests/test_replay_contracts.py`

**Interfaces:**
- Produces `EvidenceClass`, `ObservationKind`, `JournalObservation`, `ExcursionMetric`, `TradeJournalEntry`.
- Produces `SourceRecordKind`, `SourceSegment`, `ReplayRecord`, `ReplayManifest`, `ReplayResult`, and canonical hashing helpers.
- All later Phase 8 modules consume these immutable contracts.

- [ ] **Step 1: Write RED journal-contract tests**

Add tests that construct `JournalObservation`/`TradeJournalEntry` with `Decimal` financial fields, require timezone/market/reference validation where applicable, assert canonical tuple ordering for reason/reference fields, assert deterministic IDs under hostile ambient Decimal context, and assert changing any semantic lifecycle reference changes the ID.

```python
def test_trade_id_changes_when_funding_reference_changes() -> None:
    first = trade_entry(funding_event_ids=("funding-1",))
    second = trade_entry(funding_event_ids=("funding-2",))
    assert first.trade_id != second.trade_id


def test_journal_ids_ignore_ambient_decimal_context() -> None:
    expected = trade_entry().trade_id
    with localcontext(Context(prec=7, rounding=ROUND_UP)):
        assert trade_entry().trade_id == expected
```

- [ ] **Step 2: Write RED replay-contract tests**

Require `EvidenceClass.CANDLE_CONTEXT` and `MICROSTRUCTURE`, immutable `SourceSegment` SHA-256 metadata, `ReplayManifest` canonical ordering independent of input tuple enumeration, semantic manifest IDs, and `ReplayResult` deterministic digest.

```python
def test_manifest_source_order_is_canonical() -> None:
    a = source_segment("events/a.jsonl", digest="a" * 64)
    b = source_segment("events/b.jsonl", digest="b" * 64)
    assert manifest((b, a)).manifest_id == manifest((a, b)).manifest_id
```

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```bash
python -m pytest tests/test_journal_contracts.py tests/test_replay_contracts.py -q
```

Expected: collection/import failures because Phase 8 contracts do not exist.

- [ ] **Step 4: Implement minimal immutable contracts**

Use frozen/slots dataclasses and canonical JSON/hash helpers. Preserve the existing `DecisionRecord` name only as a compatibility alias or migrate tests/importers in the same task; do not keep two competing journal truths.

Canonical decimal serialization must use finite `Decimal` string values, never float conversion.

- [ ] **Step 5: Run focused + static checks**

```bash
python -m pytest tests/test_journal_contracts.py tests/test_replay_contracts.py -q
python -m ruff check src/cocomelon/domain/journal.py src/cocomelon/domain/replay.py tests/test_journal_contracts.py tests/test_replay_contracts.py
python -m mypy src
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cocomelon/domain/journal.py src/cocomelon/domain/replay.py tests/test_journal_contracts.py tests/test_replay_contracts.py
git commit -m "feat: define deterministic journal and replay contracts"
```

### Task 2: Validate trusted recorder segments and expose canonical JSONL replay records

**Files:**
- Create: `src/cocomelon/replay/__init__.py`
- Create: `src/cocomelon/replay/source.py`
- Test: `tests/test_replay_source.py`
- Reuse: `src/cocomelon/recorder.py`
- Reuse fixtures: `tests/fixtures/hyperliquid_ws/`

**Interfaces:**

```python
validate_recording(root: str | Path) -> tuple[SourceSegment, ...]

class ReplaySource(Protocol):
    def iter_records(self, manifest: ReplayManifest) -> Iterator[ReplayRecord]: ...

class JsonlReplaySource:
    def __init__(self, root: str | Path) -> None: ...
    def iter_records(self, manifest: ReplayManifest) -> Iterator[ReplayRecord]: ...
```

- [ ] **Step 1: Write RED source-validation tests**

Build temporary recorder-shaped partitions with exact `normalized_event` and `data_gap` rows. Require SHA-256 digest/bytes/row count, first/last availability timestamps, partition/kind/market/date consistency, finite typed payload values, and stable segment ordering.

```python
def test_validator_hashes_exact_bytes_and_checks_partition_identity(tmp_path: Path) -> None:
    root = write_valid_recording(tmp_path)
    segments = validate_recording(root)
    assert segments[0].sha256 == hashlib.sha256(segments[0].path.read_bytes()).hexdigest()
    assert segments[0].row_count > 0
```

Add corrupt JSON, truncated final row, unsupported schema, bad market partition, bad receive date, negative exchange timestamp, and duplicate event-key cases.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tests/test_replay_source.py -q
```

Expected: FAIL because `cocomelon.replay.source` is absent.

- [ ] **Step 3: Implement strict read-side validation**

Parse JSONL without mutating files. Convert recorder timestamps to integer availability milliseconds from `receive_time`; retain exchange timestamp separately. For `data_gap`, use `started_ms` as availability unless a later schema provides explicit observation time. Validate every complete line and reject conflicting duplicates.

- [ ] **Step 4: Implement `JsonlReplaySource`**

Yield typed `ReplayRecord` values filtered by manifest window/evidence class. The source re-hashes every manifest-listed segment before reading and rejects changed bytes.

- [ ] **Step 5: Verify GREEN**

```bash
python -m pytest tests/test_replay_source.py tests/test_recorder.py -q
python -m ruff check src/cocomelon/replay tests/test_replay_source.py
python -m mypy src
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cocomelon/replay tests/test_replay_source.py
git commit -m "feat: validate recorded evidence for deterministic replay"
```

### Task 3: Build replay manifests and the deterministic event clock

**Files:**
- Create: `src/cocomelon/replay/manifest.py`
- Create: `src/cocomelon/replay/clock.py`
- Test: `tests/test_replay_manifest.py`
- Test: `tests/test_replay_clock.py`

**Interfaces:**

```python
build_replay_manifest(
    segments: Sequence[SourceSegment],
    *,
    evidence_class: EvidenceClass,
    start_ms: int,
    end_ms: int,
    code_revision: str,
    config_snapshot: Mapping[str, object],
    feature_version: str,
    strategy_version: str,
    risk_version: str,
    execution_config: PaperExecutionConfig | None,
    replay_engine_version: str = "phase8-v1",
) -> ReplayManifest

class ReplayClock:
    @property
    def now_ms(self) -> int | None: ...
    def advance(self, record: ReplayRecord) -> int: ...
```

- [ ] **Step 1: Write RED manifest tests**

Require same semantic inputs -> same ID; source hash/config/code/window/evidence/version changes -> different ID; JSON object key ordering cannot affect config digest; start > end rejects; execution config is required for microstructure execution manifests that claim Phase 7 fill replay.

- [ ] **Step 2: Write RED event-clock/lookahead tests**

Use records deliberately supplied in shuffled file order. Require canonical sort by `(available_at_ms, kind_priority, market, event_key)`. Prove a WebSocket event with exchange time earlier than receive time cannot become available early.

```python
def test_receive_time_not_exchange_time_controls_ws_availability() -> None:
    record = replay_event(exchange_time_ms=1_000, available_at_ms=2_000)
    assert record.available_at_ms == 2_000
```

Require `ReplayClock.advance()` to reject time regression.

- [ ] **Step 3: Verify RED**

```bash
python -m pytest tests/test_replay_manifest.py tests/test_replay_clock.py -q
```

- [ ] **Step 4: Implement canonical manifest/clock**

No calls to `datetime.now`, `time.time`, network clients, or random functions. Keep stable kind priorities in one explicit mapping with a test locking the versioned order.

- [ ] **Step 5: Verify GREEN**

```bash
python -m pytest tests/test_replay_manifest.py tests/test_replay_clock.py tests/test_replay_source.py -q
python -m ruff check src/cocomelon/replay tests/test_replay_manifest.py tests/test_replay_clock.py
python -m mypy src
```

- [ ] **Step 6: Commit**

```bash
git add src/cocomelon/replay/manifest.py src/cocomelon/replay/clock.py tests/test_replay_manifest.py tests/test_replay_clock.py
git commit -m "feat: add deterministic replay manifests and clock"
```

### Task 4: Add the immutable journal SQLite store

**Files:**
- Create: `src/cocomelon/journal/__init__.py`
- Create: `src/cocomelon/journal/store.py`
- Test: `tests/test_journal_store.py`

**Interfaces:**

```python
class JournalStore:
    def __init__(self, path: str | Path) -> None: ...
    def record_observation(self, observation: JournalObservation) -> None: ...
    def record_trade(self, trade: TradeJournalEntry) -> None: ...
    def record_manifest(self, manifest: ReplayManifest) -> None: ...
    def begin_run(self, manifest_id: str, run_id: str) -> None: ...
    def finish_run(self, result: ReplayResult) -> None: ...
    def load_trade(self, trade_id: str) -> TradeJournalEntry | None: ...
    def close(self) -> None: ...
```

- [ ] **Step 1: Write RED schema/idempotency tests**

Require tables `journal_meta`, `journal_observations`, `journal_trades`, `journal_trade_refs`, `replay_manifests`, `replay_runs`, and `compaction_manifests`. Insert the same identical record twice successfully; inserting the same deterministic ID with a changed canonical payload must raise `JournalConsistencyError`.

- [ ] **Step 2: Write RED transaction/restart tests**

Inject a failure while persisting a trade plus references and prove the whole transaction rolls back. Reopen the database and require byte-equivalent canonical payload reconstruction.

- [ ] **Step 3: Verify RED**

```bash
python -m pytest tests/test_journal_store.py -q
```

- [ ] **Step 4: Implement stdlib SQLite store**

Store canonical JSON payloads alongside indexed columns used for lookup. Use explicit `BEGIN IMMEDIATE`/commit/rollback around multi-row mutations. Do not silently ignore conflicting duplicates.

- [ ] **Step 5: Verify GREEN**

```bash
python -m pytest tests/test_journal_store.py -q
python -m ruff check src/cocomelon/journal tests/test_journal_store.py
python -m mypy src
```

- [ ] **Step 6: Commit**

```bash
git add src/cocomelon/journal tests/test_journal_store.py
git commit -m "feat: persist deterministic research journal state"
```

### Task 5: Assemble closed trade lifecycles and compute reconciled analytics

**Files:**
- Create: `src/cocomelon/journal/analytics.py`
- Create: `src/cocomelon/journal/assembler.py`
- Test: `tests/test_trade_analytics.py`
- Test: `tests/test_trade_journal_assembler.py`
- Reuse: `src/cocomelon/execution/accounting.py`
- Reuse: `src/cocomelon/domain/execution.py`

**Interfaces:**

```python
compute_trade_analytics(
    *,
    direction: Direction,
    entry_price: Decimal,
    entry_reference_price: Decimal,
    exit_price: Decimal,
    exit_reference_price: Decimal,
    opened_quantity: Decimal,
    gross_realized_pnl: Decimal,
    entry_fees: Decimal,
    exit_fees: Decimal,
    funding_cash_pnl: Decimal,
    initial_risk_amount: Decimal,
    mark_observations: Sequence[ReplayRecord],
    known_gap_intervals: Sequence[tuple[int, int | None]],
) -> TradeAnalytics

assemble_trade_journal_entry(lifecycle: TradeLifecycleInput) -> TradeJournalEntry | JournalInconsistency
```

- [ ] **Step 1: Write RED net-PnL/net-R/slippage tests**

Cover LONG/SHORT profitable/losing trades, positive/negative funding, side-aware adverse slippage, and exact reconciliation:

```python
assert analytics.net_pnl == gross_realized - entry_fees - exit_fees + funding
assert analytics.net_r == analytics.net_pnl / initial_risk
```

Reject missing/non-positive initial risk when claiming net R.

- [ ] **Step 2: Write RED MFE/MAE tests**

Use only `ACTIVE_ASSET_CTX.mark_px` inside the open/close interval. Verify LONG/SHORT extrema, source event keys/timestamps, and `complete=False` when a known data gap intersects required mark coverage. Include partial-reduction quantity changes for currency excursion attribution.

- [ ] **Step 3: Write RED lifecycle reconciliation tests**

Require all fills/actions/funding to reference the same market/lifecycle, full close to reconcile quantity to zero, and journal net result to agree with Phase 7 lifecycle/account values. Missing/mismatched references return structured `JournalInconsistency` rather than a partial trade.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_trade_analytics.py tests/test_trade_journal_assembler.py -q
```

- [ ] **Step 5: Implement pure analytics/assembler**

Use the same fixed Decimal context conventions as Phase 6-7. Do not query SQLite or read files inside analytics functions.

- [ ] **Step 6: Verify GREEN**

```bash
python -m pytest tests/test_trade_analytics.py tests/test_trade_journal_assembler.py tests/test_paper_accounting.py tests/test_paper_funding.py -q
python -m ruff check src/cocomelon/journal tests/test_trade_analytics.py tests/test_trade_journal_assembler.py
python -m mypy src
```

- [ ] **Step 7: Commit**

```bash
git add src/cocomelon/journal/analytics.py src/cocomelon/journal/assembler.py tests/test_trade_analytics.py tests/test_trade_journal_assembler.py
git commit -m "feat: assemble and analyze reconciled paper trades"
```

### Task 6: Journal all first-class decisions, including deterministic NO_TRADE sampling

**Files:**
- Create: `src/cocomelon/journal/observations.py`
- Test: `tests/test_journal_observations.py`
- Reuse: Phase 4 scanner/feature, Phase 5 strategy, Phase 6 risk, Phase 7 execution contracts.

**Interfaces:**

```python
observation_from_strategy(decision: StrategyDecision, *, replay_run_id: str | None) -> JournalObservation
observation_from_risk(decision: RiskDecision, *, replay_run_id: str | None) -> JournalObservation
observation_from_execution(attempt: ExecutionAttempt, *, replay_run_id: str | None) -> JournalObservation
should_sample_no_trade(decision_id: str, *, numerator: int, denominator: int) -> bool
```

- [ ] **Step 1: Write RED observation tests**

Require strategy LONG/SHORT/NO_TRADE, risk approve/reject, execution full/partial/no-fill/reject, funding gap/accrual, and position action observations to preserve deterministic source IDs/reasons/timestamps.

- [ ] **Step 2: Write RED deterministic sampling tests**

Use SHA-256 of decision ID modulo denominator. Require same ID/config -> same answer across runs and ambient random state; numerator 0 samples none; numerator == denominator samples all; invalid fractions reject.

- [ ] **Step 3: Verify RED**

```bash
python -m pytest tests/test_journal_observations.py -q
```

- [ ] **Step 4: Implement pure observation builders and hash sampling**

No random module dependency. Do not classify NO_TRADE quality in Phase 8.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest tests/test_journal_observations.py -q
python -m ruff check src/cocomelon/journal tests/test_journal_observations.py
python -m mypy src
git add src/cocomelon/journal/observations.py tests/test_journal_observations.py
git commit -m "feat: journal deterministic trading observations"
```

### Task 7: Build the deterministic replay engine around existing Phase 4-7 boundaries

**Files:**
- Create: `src/cocomelon/replay/engine.py`
- Create: `src/cocomelon/replay/adapters.py`
- Test: `tests/test_replay_engine.py`
- Test: `tests/test_replay_lookahead.py`
- Reuse: existing feature/scanner/strategy/risk/execution APIs rather than duplicating formulas.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ReplayPipeline:
    on_record: Callable[[ReplayRecord, int], Sequence[JournalObservation]]
    finalize: Callable[[int], Sequence[TradeJournalEntry]]

class ReplayEngine:
    def __init__(self, source: ReplaySource, journal: JournalStore, pipeline: ReplayPipeline) -> None: ...
    def run(self, manifest: ReplayManifest) -> ReplayResult: ...
```

`ReplayPipeline` is deliberately narrow: Phase 8 controls evidence/time ordering while existing pipeline-specific orchestration can be adapted without moving strategy/risk logic into replay core.

- [ ] **Step 1: Write RED generic replay-engine tests**

Feed a shuffled source and require canonical time ordering, exact counts, idempotent journal results, deterministic `ReplayResult`, and no wall clock/network dependency.

- [ ] **Step 2: Write RED evidence-class enforcement tests**

A `CANDLE_CONTEXT` manifest containing or requesting a Phase 7 L2 execution replay must fail with `EvidenceClassError`. `MICROSTRUCTURE` accepts recorded L2/trade records but still fails if required L2 is absent.

- [ ] **Step 3: Write RED lookahead regressions**

Construct two fixtures identical before decision time but with dramatically different future candle/mark/L2 values. Require all pre-availability observations/decisions to have identical IDs and values. Then advance the clock and require the future evidence to become visible only at its receive/availability timestamp.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_replay_engine.py tests/test_replay_lookahead.py -q
```

- [ ] **Step 5: Implement engine and adapters**

The engine revalidates the manifest source, orders records canonically, advances `ReplayClock`, dispatches records, journals returned facts, and finalizes closed trades/result. It never imports Hyperliquid HTTP/WebSocket clients.

- [ ] **Step 6: Verify GREEN**

```bash
python -m pytest tests/test_replay_engine.py tests/test_replay_lookahead.py tests/test_phase7_risk_pipeline.py -q
python -m ruff check src/cocomelon/replay tests/test_replay_engine.py tests/test_replay_lookahead.py
python -m mypy src
```

- [ ] **Step 7: Commit**

```bash
git add src/cocomelon/replay/engine.py src/cocomelon/replay/adapters.py tests/test_replay_engine.py tests/test_replay_lookahead.py
git commit -m "feat: replay trading evidence on a deterministic clock"
```

### Task 8: Add optional offline PyArrow Parquet compaction

**Files:**
- Modify: `pyproject.toml`
- Create: `src/cocomelon/replay/compaction.py`
- Test: `tests/test_replay_compaction.py`

**Interfaces:**

```python
compact_recording(
    source_root: str | Path,
    output_root: str | Path,
    segments: Sequence[SourceSegment],
    *,
    converter_version: str = "phase8-v1",
) -> CompactionManifest
```

Add:

```toml
[project.optional-dependencies]
research = [
  "pyarrow>=21,<22",
]
```

Before finalizing the version range, verify Python 3.12 wheel availability in CI. If the currently installable stable PyArrow major differs, use the narrow current compatible major range and record it in the spec/status; do not broaden to an unbounded dependency.

- [ ] **Step 1: Write RED base-dependency boundary test**

Require base `[project].dependencies` contains no `pyarrow`; only `[project.optional-dependencies].research` may contain it. Require `cocomelon.recorder` imports without PyArrow installed.

- [ ] **Step 2: Write RED compaction tests under research extra**

Create recorder-shaped JSONL, compact it, open output with PyArrow, require genuine Parquet schema/magic, exact row counts, source/output hashes, atomic manifest, raw source bytes unchanged, and deterministic canonical semantic digest independent of segment enumeration.

- [ ] **Step 3: Write RED missing-dependency behavior**

Monkeypatch/import-isolate PyArrow absence and require `ResearchDependencyError` with an install hint rather than a base-runtime import failure.

- [ ] **Step 4: Verify RED**

Core:

```bash
python -m pytest tests/test_replay_compaction.py -q
```

Research environment:

```bash
python -m pip install -e ".[dev,research]"
python -m pytest tests/test_replay_compaction.py -q
```

- [ ] **Step 5: Implement offline compactor**

Import PyArrow inside the compaction boundary, not at recorder/package import time. Write output to a temporary path, fsync where supported, atomically rename, then persist the compaction manifest only after all output hashes/counts are known.

- [ ] **Step 6: Verify core + research GREEN**

```bash
python -m pip install -e ".[dev]"
python -m compileall -q src tests scripts
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
python -m pip install -e ".[dev,research]"
python -m pytest tests/test_replay_compaction.py -q
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/cocomelon/replay/compaction.py tests/test_replay_compaction.py
git commit -m "feat: compact validated recordings to offline Parquet"
```

### Task 9: Add Parquet replay source equivalence

**Files:**
- Create: `src/cocomelon/replay/parquet_source.py`
- Test: `tests/test_parquet_replay_source.py`

**Interfaces:**

```python
class ParquetReplaySource:
    def __init__(self, dataset_root: str | Path, manifest: CompactionManifest) -> None: ...
    def iter_records(self, manifest: ReplayManifest) -> Iterator[ReplayRecord]: ...
```

- [ ] **Step 1: Write RED equivalence tests**

Compact a mixed candle/context/L2/trade fixture, read it through `JsonlReplaySource` and `ParquetReplaySource`, and require identical tuples of canonical `ReplayRecord` values/event ordering.

- [ ] **Step 2: Write RED corruption tests**

Modify an output Parquet file after compaction and require hash mismatch before replay. Supply a compaction manifest with a different source-set semantic digest and require rejection.

- [ ] **Step 3: Verify RED**

```bash
python -m pytest tests/test_parquet_replay_source.py -q
```

- [ ] **Step 4: Implement manifest-validated reader**

PyArrow import remains inside the optional research path. Reconstruct the same typed Decimal/timestamp/provenance fields as the JSONL reader.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest tests/test_replay_compaction.py tests/test_parquet_replay_source.py tests/test_replay_source.py -q
python -m ruff check src/cocomelon/replay tests/test_parquet_replay_source.py
python -m mypy src
git add src/cocomelon/replay/parquet_source.py tests/test_parquet_replay_source.py
git commit -m "feat: replay compacted Parquet with source equivalence"
```

### Task 10: Add offline operator commands

**Files:**
- Modify: `src/cocomelon/cli.py`
- Test: `tests/test_phase8_cli.py`

**Interfaces:**

Add commands:

```text
cocomelon validate-recording --root PATH
cocomelon compact-recording --root PATH --out PATH
cocomelon replay --manifest PATH --journal PATH
cocomelon inspect-journal --journal PATH --trade-id ID
```

- [ ] **Step 1: Write RED CLI parser/behavior tests**

Require validation prints machine-readable segment/count/hash summary; compaction clearly errors without research dependency; replay requires an explicit frozen manifest and output journal; inspect-journal is read-only. Reject testnet URLs if any network-ish option is accidentally introduced.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tests/test_phase8_cli.py -q
```

- [ ] **Step 3: Implement minimal offline command routing**

Do not add implicit mainnet fetching. Replay must be runnable with networking unavailable. Keep existing CLI commands/regressions intact.

- [ ] **Step 4: Verify GREEN**

```bash
python -m pytest tests/test_phase8_cli.py tests/test_cli.py -q
python -m ruff check src/cocomelon/cli.py tests/test_phase8_cli.py
python -m mypy src
```

- [ ] **Step 5: Commit**

```bash
git add src/cocomelon/cli.py tests/test_phase8_cli.py
git commit -m "feat: expose offline Phase 8 replay tooling"
```

### Task 11: End-to-end deterministic Phase 5-8 replay and boundary audit

**Files:**
- Create: `tests/test_phase8_replay_pipeline.py`
- Create: `tests/test_phase8_boundaries.py`
- Modify: smallest existing orchestration adapter only if the end-to-end fixture exposes a real missing interface.

**Interfaces:**
- Uses `JsonlReplaySource` -> `ReplayEngine` -> existing Phase 5 strategy / Phase 6 risk / Phase 7 paper boundaries -> `JournalStore`.
- Produces no new trading formulas.

- [ ] **Step 1: Write frozen LONG/SHORT lifecycle replay tests**

Construct a recorder fixture whose canonical evidence produces a deterministic Phase 5 strategy decision, Phase 6 approval, Phase 7 IOC opening, mark/thesis/stop management, reduce-only close, and Phase 8 `TradeJournalEntry`.

Run twice against fresh journal/paper stores and require identical semantic IDs, fills, PnL, analytics, final account state, and `ReplayResult.result_digest`.

- [ ] **Step 2: Add NO_TRADE/risk-reject/no-fill replay fixture**

Require all three outcomes to be journaled and zero new position exposure created.

- [ ] **Step 3: Add boundary tests**

Source-scan Phase 8 for forbidden network client calls, testnet, wallet/private-key/signing/withdraw/transfer/live order capability, ML libraries, parameter optimization loops, and candle-to-book construction. Assert PyArrow remains absent from base dependencies and from `cocomelon.recorder` imports.

- [ ] **Step 4: Verify focused GREEN**

```bash
python -m pytest tests/test_phase8_replay_pipeline.py tests/test_phase8_boundaries.py -q
```

- [ ] **Step 5: Run complete core verification**

```bash
python -m pip install -e ".[dev]"
python -m compileall -q src tests scripts
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
```

Expected: PASS on Python 3.12.

- [ ] **Step 6: Run research-extra verification**

```bash
python -m pip install -e ".[dev,research]"
python -m pytest tests/test_replay_compaction.py tests/test_parquet_replay_source.py -q
```

Expected: PASS with genuine Parquet output.

- [ ] **Step 7: Commit**

```bash
git add tests/test_phase8_replay_pipeline.py tests/test_phase8_boundaries.py
git commit -m "test: prove deterministic Phase 8 replay boundaries"
```

### Task 12: Phase 8 continuity docs, PR audit, and guarded merge

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/CHATGPT_PROJECT_SOURCE.md`
- Modify: `docs/DECISIONS.md` only if implementation changes a genuinely locked architectural decision beyond D-015/D-021.

- [ ] **Step 1: Audit the implementation against every Phase 8 exit criterion**

Record concrete evidence for journal determinism, source hashes, lookahead tests, evidence-class separation, JSONL/Parquet equivalence, lifecycle accounting reconciliation, full core CI, research-extra compaction tests, and boundary tests.

- [ ] **Step 2: Update continuity docs with exact evidence**

Record feature head, PR number, CI run/job IDs, Python version, final test commands, and live-trading-disabled boundary. Mark Phase 9 active only after Phase 8 is merged.

- [ ] **Step 3: Audit PR surface**

Verify no unrelated files, no secrets, no unresolved review threads, no hidden network/live capability, and branch is not behind `main` unexpectedly.

- [ ] **Step 4: Run final CI on the exact closeout head**

Do not merge on stale CI evidence from an earlier head.

- [ ] **Step 5: Mark ready and guarded-merge**

Merge only with expected-head SHA protection after the exact PR head is green and mergeable.

- [ ] **Step 6: Verify post-merge state**

Require `main` at the returned merge SHA. Compare feature branch to `main`; expected file diff is empty and `main` is ahead only by the merge commit.

- [ ] **Step 7: Reconcile merge metadata on `main`**

Update continuity docs with the actual merge SHA if the pre-merge docs used placeholders, then activate Phase 9 design/spec workflow. Keep Phase 10+ and live trading deferred.