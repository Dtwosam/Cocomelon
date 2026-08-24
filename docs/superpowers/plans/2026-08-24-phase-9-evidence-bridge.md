# Phase 9 Evidence Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make genuine Hyperliquid mainnet public recordings flow deterministically through the existing Phase 5-8 paper stack into Phase 9 evaluation-ready journals/facts without adding live-order or ML capability.

**Architecture:** Add a narrow `cocomelon.evidence` orchestration package. Recording remains online/public/mainnet and writes Phase 8-compatible immutable JSONL; bundle freezing and baseline replay are offline. Baseline replay reconstructs state only from available recorded rows and reuses existing feature, strategy, risk, paper-execution, journal, and evaluation engines.

**Tech Stack:** Python 3.12, stdlib `asyncio`/`dataclasses`/`decimal`/`hashlib`/`json`/`pathlib`/`subprocess`, existing HTTP/WebSocket clients, SQLite stores, pytest, Ruff, mypy. No new core dependency.

**Spec:** `docs/superpowers/specs/2026-08-24-phase-9-evidence-bridge-design.md`

## Global Constraints

- Hyperliquid testnet is forbidden.
- Online recording is public mainnet-read-only and requires paper execution mode.
- Baseline replay is fully offline and may not import Hyperliquid network clients.
- No wallet/private-key/signing, private account subscriptions, transfer/withdrawal, or live-order capability.
- No Phase 10 ML/training or optimizer/search capability.
- Never fabricate L2/trades/funding from candles.
- REST evidence availability equals actual response receive time.
- Reuse existing feature/strategy/risk/execution/journal/evaluation formulas; do not duplicate trading logic.
- `REAL BASELINE EDGE` remains `UNMEASURED` until genuine external evidence passes the Phase 9 evaluator.
- Real-money activation always requires later explicit user authorization.

---

### Task 1: Define deterministic Evidence Bridge contracts

**Files:**
- Create: `src/cocomelon/evidence/__init__.py`
- Create: `src/cocomelon/evidence/contracts.py`
- Test: `tests/test_evidence_contracts.py`

**Interfaces:**

Produce:

```python
@dataclass(frozen=True, slots=True)
class EvidenceRecordingConfig:
    duration_seconds: int
    deep_limit: int = 20
    context_poll_seconds: int = 60
    funding_poll_seconds: int = 60
    warmup_5m_bars: int = 25
    warmup_15m_bars: int = 25
    candle_intervals: tuple[str, ...] = ("1m", "5m", "15m")
    max_records: int = 100_000
    max_bytes: int = 64 * 1024 * 1024
    api_url: str = MAINNET_API_URL
    ws_url: str = MAINNET_WS_URL
    selection_policy_id: str = "rankable-native-top-v1"
    config_version: str = "phase9-evidence-v1"
    @property
    def config_digest(self) -> str: ...

@dataclass(frozen=True, slots=True)
class SelectedEvidenceMarket:
    market: MarketId
    rank: int
    feature_snapshot_id: str
    score: Decimal

@dataclass(frozen=True, slots=True)
class EvidenceRecordingSession:
    started_at_ms: int
    recorder_code_revision: str
    selected: tuple[SelectedEvidenceMarket, ...]
    recording_config_digest: str
    api_url: str
    ws_url: str
    selection_policy_id: str
    schema_version: int = 1
    @property
    def session_id(self) -> str: ...

@dataclass(frozen=True, slots=True)
class BaselineReplayConfig:
    starting_cash: Decimal = Decimal("10000")
    decision_interval: str = "15m"
    decision_grace_ms: int = 30_000
    microstructure_window_ms: int = 60_000
    correlation_bucket: str = "crypto_beta"
    risk_limits: RiskLimits = RiskLimits()
    eligibility: EligibilityConfig = EligibilityConfig()
    execution: PaperExecutionConfig = PaperExecutionConfig()
    liquidation_policy_id: str = "paper-leverage-distance-v1"
    feature_version: str = "phase4-v1"
    strategy_version: str = "phase5-v1"
    risk_version: str = "phase6-v1"
    replay_engine_version: str = "phase8-v1"
    config_version: str = "phase9-baseline-replay-v1"
    @property
    def config_digest(self) -> str: ...

@dataclass(frozen=True, slots=True)
class FrozenBaselineReplayBundle:
    manifest: ReplayManifest
    replay_config: BaselineReplayConfig
    recording_session_digest: str
    source_set_digest: str
    schema_version: int = 1
    @property
    def bundle_id(self) -> str: ...
```

- [ ] **Step 1: Write RED canonicalization tests**

```python
def test_recording_session_id_is_enumeration_stable() -> None:
    first = session(selected=(selected("ETH", 2), selected("BTC", 1)))
    second = session(selected=(selected("BTC", 1), selected("ETH", 2)))
    assert first.session_id == second.session_id


def test_baseline_config_id_ignores_ambient_decimal_context() -> None:
    expected = BaselineReplayConfig().config_digest
    with localcontext(Context(prec=6, rounding=ROUND_UP)):
        assert BaselineReplayConfig().config_digest == expected
```

Require lowercase SHA-256 digests, unique/sorted selected markets, positive durations/limits, mainnet-only URLs, `deep_limit` capacity validation, valid fixed interval set, finite positive starting cash, and immutable config identity.

- [ ] **Step 2: Write RED bundle-binding tests**

```python
def test_bundle_rejects_manifest_config_digest_mismatch() -> None:
    with pytest.raises(ValueError, match="config_digest"):
        FrozenBaselineReplayBundle(
            manifest=manifest(config_digest="0" * 64),
            replay_config=BaselineReplayConfig(),
            recording_session_digest="1" * 64,
            source_set_digest="2" * 64,
        )
```

Define a helper `baseline_manifest_config_digest(replay_config, session_digest) -> str`; bundle validation requires exact equality.

- [ ] **Step 3: Verify RED**

Run:

```bash
python -m pytest tests/test_evidence_contracts.py -q
```

Expected: collection/import failure because `cocomelon.evidence.contracts` does not exist.

- [ ] **Step 4: Implement contracts with canonical JSON helpers**

Canonical values must convert `Decimal` to exact strings, enums to values, dataclasses recursively, mappings by sorted key, and set-like tuple fields by explicit canonical sorting. IDs may not read clock/random/global Decimal context.

- [ ] **Step 5: Verify GREEN + static checks**

```bash
python -m pytest tests/test_evidence_contracts.py -q
python -m ruff check src/cocomelon/evidence/contracts.py tests/test_evidence_contracts.py
python -m mypy src
```

- [ ] **Step 6: Commit**

```bash
git add src/cocomelon/evidence tests/test_evidence_contracts.py
git commit -m "feat: define evidence bridge contracts"
```

---

### Task 2: Record explicit public REST evidence in Phase 8 JSONL

**Files:**
- Modify: `src/cocomelon/recorder.py`
- Create: `src/cocomelon/evidence/recording.py`
- Test: `tests/test_evidence_recorder.py`
- Test: `tests/test_replay_source.py`

**Interfaces:**

Add recorder helpers:

```python
class DurableRecorder:
    def append_market_snapshot(self, snapshot: PerpMarketSnapshot) -> Path: ...
    def append_funding_rate(self, rate: FundingRate) -> Path: ...
    def append_candle(self, candle: Candle) -> Path: ...
```

The methods write the existing `record_type="normalized_event"` envelope with explicit event kinds `market_snapshot`, `funding_rate`, and `candle`. REST receive timestamps come from each domain object's `received_at_ms`.

Create pure codecs:

```python
def market_snapshot_record_event(snapshot: PerpMarketSnapshot) -> RecordedPublicEvent: ...
def funding_rate_record_event(rate: FundingRate) -> RecordedPublicEvent: ...
def candle_record_event(candle: Candle) -> RecordedPublicEvent: ...
```

`RecordedPublicEvent` is an internal frozen helper carrying kind/market/source/exchange time/receive time/event key/payload.

- [ ] **Step 1: Write RED row-shape/receive-time tests**

Require market snapshot payload to round-trip all metadata/context values needed by feature/risk replay; require funding payload to preserve exact boundary/rate/premium; require historical candle `receive_time` to equal REST receipt rather than candle end.

- [ ] **Step 2: Write RED Phase 8 validation tests**

Append all three REST types, run `validate_recording(root)`, and require valid source segments and deterministic hashes. Append the same semantic funding record twice with identical receive provenance and require duplicate event-key validation to catch the duplicate; the higher orchestration layer must dedupe before append.

- [ ] **Step 3: Verify RED**

```bash
python -m pytest tests/test_evidence_recorder.py tests/test_replay_source.py -q
```

- [ ] **Step 4: Implement canonical recorder helpers**

Use one private `_append_public_event(...)` path in `DurableRecorder`; do not add private/user event support. Keep existing WebSocket `append_event` unchanged.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest tests/test_evidence_recorder.py tests/test_replay_source.py -q
python -m ruff check src/cocomelon/recorder.py src/cocomelon/evidence/recording.py tests/test_evidence_recorder.py
python -m mypy src
git add src/cocomelon/recorder.py src/cocomelon/evidence/recording.py tests/test_evidence_recorder.py tests/test_replay_source.py
git commit -m "feat: record public REST evidence"
```

---

### Task 3: Complete deterministic paper funding application

**Files:**
- Modify: `src/cocomelon/execution/accounting.py`
- Modify: `src/cocomelon/execution/store.py`
- Modify: `src/cocomelon/execution/paper.py`
- Test: `tests/test_paper_funding_accounting.py`
- Test: `tests/test_execution_store.py`

**Interfaces:**

```python
def apply_funding_accrual(
    account: PaperAccountState,
    accrual: FundingAccrual,
    timestamp_ms: int,
) -> PaperAccountState: ...

class PaperExecutionStore:
    def has_funding_accrual(self, accrual_id: str) -> bool: ...

class PaperExecutionAdapter:
    def apply_funding(self, accrual: FundingAccrual, *, timestamp_ms: int) -> PaperAccountState: ...
```

- [ ] **Step 1: Write RED account arithmetic tests**

For LONG positive funding debit and SHORT positive funding credit, require:

```python
updated.cash == prior.cash + accrual.cash_delta
updated.cumulative_funding == prior.cumulative_funding + accrual.cash_delta
updated.positions[0].cumulative_funding == prior.positions[0].cumulative_funding + accrual.cash_delta
```

Also require market/position ID exact match, monotonic timestamp, unchanged realized-gross PnL/fees, and equity consistency after funding.

- [ ] **Step 2: Write RED adapter idempotency tests**

Apply the same accrual twice before and after closing/reopening the adapter. The second application must return the already-funded account unchanged and must not double cash/funding. A same accrual ID with a conflicting immutable payload remains a store error.

- [ ] **Step 3: Verify RED**

```bash
python -m pytest tests/test_paper_funding_accounting.py tests/test_execution_store.py -q
```

- [ ] **Step 4: Implement accounting and adapter/store guard**

Use existing authoritative Decimal context and `_state_with_equity`; recompute mark-derived unrealized/notional/margin from existing `latest_mark` values rather than zeroing an open account. Store lookup must occur before arithmetic on retries.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest tests/test_paper_funding.py tests/test_paper_funding_accounting.py tests/test_execution_store.py -q
python -m ruff check src/cocomelon/execution tests/test_paper_funding_accounting.py
python -m mypy src
git add src/cocomelon/execution tests/test_paper_funding_accounting.py tests/test_execution_store.py
git commit -m "feat: apply paper funding accruals"
```

---

### Task 4: Build immutable recording-session selection and bootstrap

**Files:**
- Modify: `src/cocomelon/evidence/recording.py`
- Test: `tests/test_evidence_recording_session.py`

**Interfaces:**

Use protocols instead of concrete network clients in the pure orchestration layer:

```python
class EvidenceInfoReader(Protocol):
    def perp_dexs(self) -> object: ...
    def meta_and_asset_ctxs(self, dex: str = "") -> object: ...
    def candles(self, market: MarketId, interval: str, *, start_ms: int, end_ms: int) -> object: ...
    def funding_history(self, market: MarketId, *, start_ms: int, end_ms: int | None = None) -> object: ...

@dataclass(frozen=True, slots=True)
class RecordingBootstrap:
    session: EvidenceRecordingSession
    snapshots: tuple[PerpMarketSnapshot, ...]
    candles: tuple[Candle, ...]
    funding_rates: tuple[FundingRate, ...]
    subscriptions: tuple[dict[str, object], ...]


def build_recording_bootstrap(
    reader: EvidenceInfoReader,
    config: EvidenceRecordingConfig,
    *,
    now_ms: Callable[[], int],
    code_revision: str,
) -> RecordingBootstrap: ...
```

- [ ] **Step 1: Write RED dynamic-selection tests**

Feed a fake discovered universe with shuffled input order, delisted/HIP-3/low-quality markets, and at least five eligible native markets. Require identical top-N native selection under permutation and no favorite-token special case.

- [ ] **Step 2: Write RED warmup provenance tests**

Fake the clock to advance after each REST response. Require normalized warmup candles/funding/snapshots to carry the response receive time, not their historical event timestamp. Require at least 25 requested 5m and 25 requested 15m bars per selected market.

- [ ] **Step 3: Write RED subscription-plan tests**

Require all subscriptions to validate through existing public `subscription_id`; selected markets get active context/L2/trades/1m/5m/15m and count remains below the existing safety ceiling.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_evidence_recording_session.py -q
```

- [ ] **Step 5: Implement using existing registry/scan/ranker/normalizers**

Do not copy ranking formulas. Filter `market.dex == ""` only after broad ranking/eligibility has established rankability, because this is execution-support gating rather than a favorite-universe filter.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest tests/test_evidence_recording_session.py tests/test_scan_once.py -q
python -m ruff check src/cocomelon/evidence/recording.py tests/test_evidence_recording_session.py
python -m mypy src
git add src/cocomelon/evidence/recording.py tests/test_evidence_recording_session.py
git commit -m "feat: bootstrap evaluation evidence sessions"
```

---

### Task 5: Run bounded/restart-safe public mainnet recording

**Files:**
- Modify: `src/cocomelon/evidence/recording.py`
- Create: `src/cocomelon/evidence/cli_support.py`
- Modify: `src/cocomelon/cli.py`
- Test: `tests/test_evidence_recording_runner.py`
- Test: `tests/test_evidence_cli.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class RecordingRunSummary:
    session_id: str
    selected_markets: tuple[str, ...]
    duration_seconds: int
    event_count: int
    gap_count: int
    reconnect_count: int
    duplicate_count: int
    anomaly_count: int
    root: str
    network_access: bool = True
    live_orders: bool = False

async def run_bounded_recording(
    *,
    bootstrap: RecordingBootstrap,
    reader: EvidenceInfoReader,
    connection_factory: ConnectionFactory,
    recorder: DurableRecorder,
    config: EvidenceRecordingConfig,
    sleep: Sleep = asyncio.sleep,
    clock_ms: ClockMs = utc_now_ms,
    utcnow: UtcNow = ...,
) -> RecordingRunSummary: ...
```

Session metadata helpers:

```python
def write_recording_session(root: Path, session: EvidenceRecordingSession) -> None: ...
def load_recording_session(root: Path) -> EvidenceRecordingSession | None: ...
def verify_recording_resume(root: Path, requested: EvidenceRecordingSession) -> None: ...
```

- [ ] **Step 1: Write RED restart/session-conflict tests**

Same session retry succeeds and recorder opens a new segment as existing Phase 3 semantics dictate. Changed selected cohort/config/code revision in a populated root fails before network streaming.

- [ ] **Step 2: Write RED concurrent-loop tests**

Use fake connection + fake REST reader + fake sleep/clock. Require initial bootstrap rows, WS rows, periodic full market snapshots, and funding dedupe by `(market,time_ms)`. A REST poll exception creates an explicit gap; a recorder sink exception terminates the run.

- [ ] **Step 3: Write RED CLI safety/parser tests**

Require:

```text
record-mainnet-evidence --root ROOT --seconds 3600 --deep-limit 20
```

Reject non-paper execution mode and testnet via existing settings; ensure parser has no live/private/wallet/order arguments.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_evidence_recording_runner.py tests/test_evidence_cli.py -q
```

- [ ] **Step 5: Implement bounded orchestration**

Use `asyncio.wait_for`/task cancellation so `duration_seconds` is an actual bound. REST poll loops use config cadence. Count writes only after successful durable append. Close connection via supervisor semantics; do not swallow cancellation/sink failure.

- [ ] **Step 6: Wire CLI with concrete `InfoClient`/`connect_ws` only in online CLI path**

Keep network client imports out of `baseline.py`/`bundle.py`.

- [ ] **Step 7: Verify GREEN and commit**

```bash
python -m pytest tests/test_evidence_recording_runner.py tests/test_evidence_cli.py -q
python -m ruff check src/cocomelon/evidence src/cocomelon/cli.py tests/test_evidence_recording_runner.py tests/test_evidence_cli.py
python -m mypy src
git add src/cocomelon/evidence src/cocomelon/cli.py tests/test_evidence_recording_runner.py tests/test_evidence_cli.py
git commit -m "feat: add bounded mainnet evidence recorder"
```

---

### Task 6: Freeze and round-trip baseline replay bundles

**Files:**
- Create: `src/cocomelon/evidence/bundle.py`
- Modify: `src/cocomelon/evidence/cli_support.py`
- Modify: `src/cocomelon/cli.py`
- Test: `tests/test_evidence_bundle.py`
- Test: `tests/test_evidence_cli.py`

**Interfaces:**

```python
def freeze_baseline_replay_bundle(
    recording_root: str | Path,
    *,
    replay_config: BaselineReplayConfig,
    code_revision: str,
) -> FrozenBaselineReplayBundle: ...

def write_baseline_replay_bundle(path: str | Path, bundle: FrozenBaselineReplayBundle) -> None: ...
def load_baseline_replay_bundle(path: str | Path) -> FrozenBaselineReplayBundle: ...
def resolve_code_revision(explicit: str | None, *, cwd: Path) -> str: ...
```

- [ ] **Step 1: Write RED source/gap/bundle tests**

Require source-set digest to include every `SourceSegment` canonical payload, gap refs derived deterministically from real `DataGap` records, `MICROSTRUCTURE` evidence class, exact execution version/fee schedule, recording-session digest binding, and atomic load equality.

- [ ] **Step 2: Write RED corruption/provenance tests**

Changed session metadata, source byte, replay config, or manifest field must invalidate load/freeze identity. Missing explicit code revision with unavailable Git HEAD must fail.

- [ ] **Step 3: Write RED CLI test**

Require `freeze-baseline-replay --root ... --out ... --starting-cash ...` to run offline and not call `Settings.from_env()`.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_evidence_bundle.py tests/test_evidence_cli.py -q
```

- [ ] **Step 5: Implement bundle codec/freeze**

Reuse `validate_recording` + `build_replay_manifest`. Do not alter legacy Phase 8 flat manifest loader or evidence-audit CLI semantics.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest tests/test_evidence_bundle.py tests/test_evidence_cli.py tests/test_replay_manifest.py -q
python -m ruff check src/cocomelon/evidence/bundle.py src/cocomelon/evidence/cli_support.py tests/test_evidence_bundle.py
python -m mypy src
git add src/cocomelon/evidence src/cocomelon/cli.py tests/test_evidence_bundle.py tests/test_evidence_cli.py
git commit -m "feat: freeze baseline replay bundles"
```

---

### Task 7: Reconstruct lookahead-safe recorded market state

**Files:**
- Create: `src/cocomelon/evidence/baseline.py`
- Test: `tests/test_baseline_replay_state.py`

**Interfaces:**

```python
@dataclass(slots=True)
class RecordedMarketState:
    market: MarketId
    latest_snapshot: PerpMarketSnapshot | None = None
    previous_snapshot: PerpMarketSnapshot | None = None
    candles_5m: dict[int, Candle] = field(default_factory=dict)
    candles_15m: dict[int, Candle] = field(default_factory=dict)
    latest_book: StreamEvent | None = None
    micro_events: deque[StreamEvent] = field(default_factory=deque)
    latest_asset_ctx: StreamEvent | None = None
    funding_by_boundary: dict[int, FundingRate] = field(default_factory=dict)

class RecordedStateBook:
    def apply(self, record: ReplayRecord, now_ms: int) -> None: ...
    def state(self, market: MarketId) -> RecordedMarketState: ...
```

Pure decoders:

```python
def replay_record_market_snapshot(record: ReplayRecord) -> PerpMarketSnapshot: ...
def replay_record_candle(record: ReplayRecord) -> Candle: ...
def replay_record_stream_event(record: ReplayRecord) -> StreamEvent: ...
def replay_record_funding_rate(record: ReplayRecord) -> FundingRate: ...
```

- [ ] **Step 1: Write RED decoder fidelity tests**

Round-trip Task 2 recorder rows through `JsonlReplaySource` and these decoders, requiring typed equality for all replay-relevant fields and exact availability receive time.

- [ ] **Step 2: Write RED state-update tests**

Require candle updates with the same interval/start to replace only when later evidence arrives; older/out-of-order availability cannot overwrite later state. WS active context may update mark/mid/oracle/funding/OI but may not fabricate day volume/prev-day/metadata absent a full snapshot.

- [ ] **Step 3: Write RED rolling-window pruning tests**

After applying TRADE/L2 rows, keep enough event history for the configured microstructure window and prune only events older than the current replay clock minus window.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_baseline_replay_state.py -q
```

- [ ] **Step 5: Implement pure offline state reconstruction**

`baseline.py` must import no module under `cocomelon.hyperliquid`.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest tests/test_baseline_replay_state.py -q
python -m ruff check src/cocomelon/evidence/baseline.py tests/test_baseline_replay_state.py
python -m mypy src
git add src/cocomelon/evidence/baseline.py tests/test_baseline_replay_state.py
git commit -m "feat: reconstruct recorded replay state"
```

---

### Task 8: Build deterministic 15m decision epochs and strategy facts

**Files:**
- Modify: `src/cocomelon/evidence/baseline.py`
- Test: `tests/test_baseline_decision_epochs.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class EpochMarketEvaluation:
    feature: FeatureSnapshot
    eligibility: EligibilityDecision
    decision: StrategyDecision

@dataclass(frozen=True, slots=True)
class DecisionEpoch:
    boundary_ms: int
    evaluated_at_ms: int
    markets: tuple[EpochMarketEvaluation, ...]

class BaselineDecisionEngine:
    def observe(self, record: ReplayRecord, now_ms: int) -> tuple[DecisionEpoch, ...]: ...
    def flush(self, end_ms: int) -> tuple[DecisionEpoch, ...]: ...
```

- [ ] **Step 1: Write RED arrival-order invariance test**

Create BTC/ETH production-shaped rows for the same 15m boundary in opposite arrival orders. After the 30s grace/all-market readiness condition, require equal epoch identity, feature IDs, eligibility, and strategy decisions.

- [ ] **Step 2: Write RED lookahead test**

A favorable L2/context/candle arriving after an epoch's `evaluated_at_ms` must not change that epoch. A market missing a fresh book/context becomes non-tradable/NO_TRADE through existing eligibility rather than borrowing later evidence.

- [ ] **Step 3: Write RED formula-reuse test**

Compare epoch feature values against direct calls to existing `calculate_broad_features`, `calculate_candle_features`, `calculate_microstructure_features`, `build_microstructure_window`, and `assemble_feature_snapshot`. This prevents fixture-injected feature values.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_baseline_decision_epochs.py -q
```

- [ ] **Step 5: Implement epoch engine**

At each epoch, calculate all available market features first, derive one cross-sectional threshold set, then evaluate eligibility and strategy in canonical market order.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest tests/test_baseline_decision_epochs.py tests/test_strategy_engine.py -q
python -m ruff check src/cocomelon/evidence/baseline.py tests/test_baseline_decision_epochs.py
python -m mypy src
git add src/cocomelon/evidence/baseline.py tests/test_baseline_decision_epochs.py
git commit -m "feat: evaluate deterministic baseline epochs"
```

---

### Task 9: Drive shared-account risk and paper openings from epochs

**Files:**
- Modify: `src/cocomelon/evidence/baseline.py`
- Test: `tests/test_baseline_paper_openings.py`

**Interfaces:**

```python
def conservative_cost_estimate(config: PaperExecutionConfig) -> ExecutionCostEstimate: ...
def paper_liquidation_surrogate(
    entry: Decimal,
    direction: Direction,
    *,
    paper_max_leverage: Decimal,
    venue_max_leverage: Decimal,
) -> Decimal: ...

class BaselineReplayPipeline:
    def on_record(self, record: ReplayRecord, now_ms: int) -> tuple[JournalObservation, ...]: ...
    def finalize(self, end_ms: int) -> tuple[TradeJournalEntry, ...]: ...
    def replay_pipeline(self) -> ReplayPipeline: ...
```

The constructor receives `BaselineReplayConfig`, `PaperExecutionAdapter`, `EvaluationFactStore`, and the selected cohort/session provenance.

- [ ] **Step 1: Write RED shared-account aggregate-risk test**

At one epoch create multiple directional decisions. Process canonical market order and require later requests to see earlier approved/open planned risk through `risk_state_from_paper`; aggregate/correlation limits must veto excess exposure exactly as existing risk engine specifies.

- [ ] **Step 2: Write RED real-book/latency/no-fill tests**

Require reference/depth from recorded book. A book before `earliest_execution_ms` cannot fill a plan; a later valid book may. Insufficient visible depth/no IOC fill creates no position. Never synthesize a better book.

- [ ] **Step 3: Write RED health/staleness tests**

Stale/missing market context, book, execution health, or account inconsistency must produce risk/planning rejection and zero new exposure.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_baseline_paper_openings.py -q
```

- [ ] **Step 5: Implement request/instrument/cost/liquidation builders**

Use native `InstrumentExecutionSpec` metadata from recorded full snapshot, existing minimum native notional, actual bid/ask 25bps depth, and locked risk/execution versions. The liquidation helper is explicitly named surrogate and covered by tests/docstring saying it is not a venue liquidation quote.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest tests/test_baseline_paper_openings.py tests/test_phase7_risk_pipeline.py -q
python -m ruff check src/cocomelon/evidence/baseline.py tests/test_baseline_paper_openings.py
python -m mypy src
git add src/cocomelon/evidence/baseline.py tests/test_baseline_paper_openings.py
git commit -m "feat: paper execute baseline replay entries"
```

---

### Task 10: Manage positions, funding, journal lifecycles, and evaluation facts

**Files:**
- Modify: `src/cocomelon/evidence/baseline.py`
- Test: `tests/test_baseline_replay_lifecycle.py`

**Interfaces:**

`BaselineReplayPipeline` additionally owns per-market lifecycle state containing opening submission, exit plans/attempts/fills/actions, funding accruals, mark observations, equity-before, and latest decision.

- [ ] **Step 1: Write RED mark/position-management tests**

Drive an opened LONG and SHORT through genuine recorded asset-context + L2 rows. Require existing `manage_position` actions, account mark-to-market before risk/management, and closed quantity reaching zero before journal assembly.

- [ ] **Step 2: Write RED funding-boundary tests**

Position open across hourly boundary + exact pre-boundary oracle + recorded `funding_rate` -> one persisted `FundingAccrual`, account update, funding journal observation, lifecycle attribution. Missing/stale funding/oracle -> `FundingGap` observation and replay incomplete; no cash change.

- [ ] **Step 3: Write RED journal reconciliation test**

A fully closed lifecycle must round-trip through `assemble_trade_journal_entry` and preserve entry/exit fees, funding, signed slippage, MFE/MAE marks, equity before/after, strategy/feature IDs, evidence class, and replay lineage. Force an inconsistent lifecycle and require `ReplayInvariantError`, not silent omission.

- [ ] **Step 4: Write RED evaluation-fact tests**

Every strategy decision records `decision_evaluation_fact(decision, feature, replay_run_id=...)`; account state transitions record `account_equity_fact` with appropriate `EquityFactKind`. Same replay restart produces identical fact IDs.

- [ ] **Step 5: Verify RED**

```bash
python -m pytest tests/test_baseline_replay_lifecycle.py -q
```

- [ ] **Step 6: Implement lifecycle/funding/fact orchestration**

Where `ReplayEngine` supplies run ID only when persisting observations, derive the same deterministic run ID through a public helper rather than duplicating its hash formula; refactor `_run_id` to `replay_run_id` in `replay/engine.py` with existing tests preserving identity.

- [ ] **Step 7: Verify GREEN and commit**

```bash
python -m pytest tests/test_baseline_replay_lifecycle.py tests/test_phase8_replay_pipeline.py tests/test_evaluation_facts.py -q
python -m ruff check src/cocomelon/evidence/baseline.py src/cocomelon/replay/engine.py tests/test_baseline_replay_lifecycle.py
python -m mypy src
git add src/cocomelon/evidence/baseline.py src/cocomelon/replay/engine.py tests/test_baseline_replay_lifecycle.py
git commit -m "feat: journal baseline replay lifecycles"
```

---

### Task 11: Add offline production baseline replay CLI and end-to-end Phase 9 handoff

**Files:**
- Modify: `src/cocomelon/evidence/cli_support.py`
- Modify: `src/cocomelon/cli.py`
- Test: `tests/test_evidence_cli.py`
- Create: `tests/test_evidence_bridge_pipeline.py`

**Interfaces:**

```python
def run_baseline_replay_payload(
    bundle_path: Path,
    journal_path: Path,
    execution_path: Path,
    facts_path: Path,
) -> dict[str, object]: ...
```

CLI:

```text
run-baseline-replay --bundle BUNDLE --journal JOURNAL --execution EXECUTION --facts FACTS
```

- [ ] **Step 1: Write RED CLI offline-routing test**

Monkeypatch `Settings.from_env` to raise; command must still complete on fixture bundle because it is routed before online settings. Output includes `network_access: false` and `live_orders: false`.

- [ ] **Step 2: Write RED full bridge fixture**

Build production-shaped recorder rows with real domain normalization shapes, then execute:

```python
bundle = freeze_baseline_replay_bundle(...)
summary = run_baseline_replay_payload(...)
dataset = build_evaluation_dataset(journal, facts, replay_run_ids=(summary["run_id"],), code_revision=...)
```

Require dataset manifest includes the exact replay result digest and non-synthetic decision facts. Fixture outcome is labelled `TEST_FIXTURE_ONLY` and never interpreted as market performance.

- [ ] **Step 3: Write RED deterministic rerun test**

Fresh execution/journal/fact DBs + same bundle yield same result digest/trade/fact/dataset IDs. Reopening same DBs remains idempotent.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_evidence_cli.py tests/test_evidence_bridge_pipeline.py -q
```

- [ ] **Step 5: Implement CLI payload and resource cleanup**

Always close journal/execution/fact stores in `finally`. Summary includes final equity but makes no `edge`/`profitability` conclusion.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest tests/test_evidence_cli.py tests/test_evidence_bridge_pipeline.py -q
python -m ruff check src/cocomelon/evidence src/cocomelon/cli.py tests/test_evidence_cli.py tests/test_evidence_bridge_pipeline.py
python -m mypy src
git add src/cocomelon/evidence src/cocomelon/cli.py tests/test_evidence_cli.py tests/test_evidence_bridge_pipeline.py
git commit -m "feat: run evaluation-ready baseline replay"
```

---

### Task 12: Enforce bridge safety boundaries and close out integration

**Files:**
- Create: `tests/test_evidence_bridge_boundaries.py`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHATGPT_PROJECT_SOURCE.md`
- Modify: this plan only if implementation evidence requires corrected commands/paths

- [ ] **Step 1: Write executable boundary scan**

The test reads `src/cocomelon/evidence/**/*.py` and relevant CLI routing. Require baseline/bundle modules to contain none of:

```text
testnet
Exchange
place_order
create_order
wallet
private_key
signing
withdraw
transfer
userFills
orderUpdates
scikit
sklearn
xgboost
lightgbm
optimizer
grid_search
random_search
```

Permit `InfoClient`/`connect_ws` imports only in the explicitly online recording CLI boundary. Also assert no code constructs L2/trades from candle records.

- [ ] **Step 2: Run focused bridge suite**

```bash
python -m pytest \
  tests/test_evidence_contracts.py \
  tests/test_evidence_recorder.py \
  tests/test_evidence_recording_session.py \
  tests/test_evidence_recording_runner.py \
  tests/test_evidence_bundle.py \
  tests/test_baseline_replay_state.py \
  tests/test_baseline_decision_epochs.py \
  tests/test_baseline_paper_openings.py \
  tests/test_baseline_replay_lifecycle.py \
  tests/test_evidence_cli.py \
  tests/test_evidence_bridge_pipeline.py \
  tests/test_evidence_bridge_boundaries.py \
  -q
```

Expected: all pass.

- [ ] **Step 3: Run full exact-tree verification**

```bash
python -m pip install -e ".[dev]"
python -m compileall -q src tests scripts
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
python -m pip install -e ".[dev,research]"
python -m pytest tests/test_replay_compaction.py tests/test_parquet_replay_source.py -q
```

Expected: all commands exit 0.

- [ ] **Step 4: Update continuity docs honestly**

Record:

- Evidence Bridge engineering capability added;
- exact final head/CI evidence;
- genuine data still external/ignored unless actually collected;
- `REAL BASELINE EDGE: UNMEASURED` remains unchanged until a real corpus is run;
- Phase 10 remains blocked;
- live trading remains disabled.

- [ ] **Step 5: Audit PR**

Require mergeable, `behind_by=0`, expected changed-file surface, no unresolved review threads/comments, no dependency drift, and boundary suite green.

- [ ] **Step 6: Guarded merge**

Mark PR ready and merge with exact expected head SHA only after exact-head CI is green. Verify returned merge SHA is `main`, then compare feature branch -> `main` and require empty file diff except merge commit.

- [ ] **Step 7: Verify post-merge continuity head**

After reconciling actual merge SHA in docs, verify the exact final `main` tree through an observable CI path. Do not claim completion from earlier PR CI alone.

- [ ] **Step 8: Next economic action**

Do **not** start Phase 10. The next action after engineering merge is to run `record-mainnet-evidence` in an environment where the process can persist real mainnet public evidence, freeze/replay that corpus, and feed the result to the existing Phase 9 evaluator.
