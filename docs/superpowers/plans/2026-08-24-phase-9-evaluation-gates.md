# Phase 9 Evaluation, OOS, and Walk-Forward Research Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, anti-lookahead evaluation system that freezes OOS usage, measures cost-aware baseline performance and uncertainty, runs walk-forward/sensitivity diagnostics, and reports edge or lack of evidence honestly.

**Architecture:** Add immutable evaluation facts beside the Phase 8 journal, freeze dataset/split/candidate/policy manifests before revealing test metrics, and run pure Decimal metric engines offline. Persist low-volume evaluation facts/results in a separate SQLite store and reuse Phase 8 replay evidence without adding network, ML, parameter-search, or live-order capability.

**Tech Stack:** Python 3.12, stdlib dataclasses/`decimal`/`hashlib`/`json`/`sqlite3`/`random`/`statistics`/`pathlib`, existing Phase 4-8 contracts, pytest, Ruff, mypy. PyArrow remains optional research tooling only and is not required by Phase 9 core.

**Spec:** `docs/superpowers/specs/2026-08-24-phase-9-evaluation-gates-design.md`

## Global Constraints

- Hyperliquid testnet is forbidden.
- Phase 9 is offline/read-only with respect to exchange state and Phase 7/8 source state.
- Phase 9 may not add Hyperliquid network clients, wallet/private-key/signing, transfer/withdrawal, private account subscriptions, or live-order capability.
- Phase 9 may not train ML or search/tune strategy parameters.
- `CANDLE_CONTEXT` and `MICROSTRUCTURE` evidence classes remain mechanically distinct.
- Candle data may never become synthetic L2/trade evidence.
- Financial/evaluation arithmetic uses deterministic finite `Decimal` values.
- Untouched OOS boundaries, candidate set, policy, and sensitivity profiles are frozen before test metrics are revealed.
- Reusing a consumed test partition with a changed candidate set/policy is marked `OOS_CONTAMINATED`.
- `NO_TRADE` remains first-class and missed-opportunity analysis never claims executable counterfactual fills.
- Live trading remains disabled and always requires later explicit user authorization.

---

### Task 1: Define immutable Phase 9 evaluation contracts

**Files:**
- Create: `src/cocomelon/domain/evaluation.py`
- Test: `tests/test_evaluation_contracts.py`

**Interfaces:**
- Produces enums `SplitName`, `OOSStatus`, `EdgeEvidenceStatus`, `EquityFactKind`.
- Produces immutable contracts `DecisionEvaluationFact`, `AccountEquityFact`, `TradeEvaluationSample`, `EvaluationPolicy`, `EvaluationDatasetManifest`, `TimePartition`, `FrozenSplitManifest`, `CandidateDefinition`, `FrozenCandidateSet`, `ConfidenceInterval`, `PerformanceMetrics`, `SliceMetrics`, `WalkForwardWindowResult`, `PromotionGatePreview`, `EvaluationResult`.
- All IDs/results use canonical SHA-256-derived digests and finite Decimal strings.

- [ ] **Step 1: Write RED contract determinism tests**

```python
def test_decision_fact_id_ignores_ambient_decimal_context() -> None:
    expected = decision_fact(score=Decimal("72.5")).fact_id
    with localcontext(Context(prec=5, rounding=ROUND_UP)):
        assert decision_fact(score=Decimal("72.5")).fact_id == expected


def test_dataset_manifest_canonicalizes_input_enumeration() -> None:
    first = dataset_manifest(trade_ids=("trade-b", "trade-a"))
    second = dataset_manifest(trade_ids=("trade-a", "trade-b"))
    assert first.manifest_id == second.manifest_id
```

Also require changing replay result digest, evidence class, policy field, score/regime, candidate version, split boundary, sensitivity profile, or semantic sample reference changes the relevant ID.

- [ ] **Step 2: Write RED validation tests**

Require:

- score finite and in `[0, 100]`;
- account equity positive and Decimal-finite;
- partition timestamps ordered;
- train < validation < test with no overlap;
- policy numeric floors positive and `positive_walkforward_fraction` in `(0,1]`;
- SHA/config digest fields exact lowercase SHA-256 where defined;
- result IDs/reason codes nonempty;
- `PerformanceMetrics.profit_factor=None` permitted with explicit unavailable reason.

- [ ] **Step 3: Verify RED**

```bash
python -m pytest tests/test_evaluation_contracts.py -q
```

Expected: import/collection failure because `cocomelon.domain.evaluation` does not exist.

- [ ] **Step 4: Implement the minimal immutable contracts**

Use fixed policy defaults:

```python
@dataclass(frozen=True, slots=True)
class EvaluationPolicy:
    policy_version: str = "phase9-v1"
    min_oos_trades: int = 100
    min_oos_days: int = 30
    min_walkforward_windows: int = 3
    min_trades_per_walkforward_window: int = 20
    min_score_bucket_trades: int = 20
    positive_walkforward_fraction: Decimal = Decimal("0.60")
    bootstrap_confidence: Decimal = Decimal("0.95")
    bootstrap_block_days: int = 5
    bootstrap_resamples: int = 2_000
    split_embargo_ms: int = 6 * 60 * 60 * 1000
    no_trade_horizons_ms: tuple[int, ...] = (
        60 * 60 * 1000,
        4 * 60 * 60 * 1000,
    )
```

Canonical payload/ID code must not read wall clock, random global state, or ambient Decimal context.

- [ ] **Step 5: Verify GREEN + static checks**

```bash
python -m pytest tests/test_evaluation_contracts.py -q
python -m ruff check src/cocomelon/domain/evaluation.py tests/test_evaluation_contracts.py
python -m mypy src
```

- [ ] **Step 6: Commit**

```bash
git add src/cocomelon/domain/evaluation.py tests/test_evaluation_contracts.py
git commit -m "feat: define deterministic evaluation contracts"
```

---

### Task 2: Add read-only Phase 8 accessors and immutable evaluation fact persistence

**Files:**
- Modify: `src/cocomelon/journal/store.py`
- Create: `src/cocomelon/evaluation/__init__.py`
- Create: `src/cocomelon/evaluation/facts.py`
- Create: `src/cocomelon/evaluation/store.py`
- Test: `tests/test_evaluation_facts.py`
- Test: `tests/test_evaluation_store.py`
- Test: `tests/test_journal_store.py`

**Interfaces:**

Add read-only Phase 8 accessors:

```python
class JournalStore:
    def iter_trades(self) -> Iterator[TradeJournalEntry]: ...
    def iter_observations(self) -> Iterator[JournalObservation]: ...
    def load_replay_result(self, run_id: str) -> ReplayResult | None: ...
    def iter_replay_results(self) -> Iterator[ReplayResult]: ...
```

Create fact builders:

```python
def decision_evaluation_fact(
    decision: StrategyDecision,
    feature: FeatureSnapshot,
    *,
    replay_run_id: str,
) -> DecisionEvaluationFact: ...


def account_equity_fact(
    account: PaperAccountState,
    *,
    replay_run_id: str,
    kind: EquityFactKind,
) -> AccountEquityFact: ...
```

Store API:

```python
class EvaluationFactStore:
    def __init__(self, path: str | Path) -> None: ...
    def record_decision_fact(self, fact: DecisionEvaluationFact) -> None: ...
    def record_equity_fact(self, fact: AccountEquityFact) -> None: ...
    def load_decision_fact(self, fact_id: str) -> DecisionEvaluationFact | None: ...
    def load_decision_by_strategy_id(self, decision_id: str, run_id: str) -> DecisionEvaluationFact | None: ...
    def iter_decision_facts(self) -> Iterator[DecisionEvaluationFact]: ...
    def iter_equity_facts(self, run_id: str | None = None) -> Iterator[AccountEquityFact]: ...
    def close(self) -> None: ...
```

- [ ] **Step 1: Write RED Phase 8 accessor tests**

Persist two trades, observations, and replay results in shuffled insertion order. Require deterministic chronological/ID iteration and exact typed replay-result restart reconstruction.

```python
def test_replay_result_round_trips_from_journal_store(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    store.record_manifest(manifest())
    store.begin_run(manifest().manifest_id, result().run_id)
    store.finish_run(result())
    assert store.load_replay_result(result().run_id) == result()
```

- [ ] **Step 2: Write RED decision/account fact tests**

Require `decision_evaluation_fact()` rejects mismatched feature IDs/markets/timestamps and preserves score, lead strategy, reason/signal IDs, trend regime, and volatility regime.

Require `account_equity_fact()` preserves exact state ID/equity/cash/unrealized/fees/funding/notional/position count.

- [ ] **Step 3: Write RED store idempotency/restart/rollback tests**

Same fact retry succeeds; same deterministic ID with a changed canonical payload raises `EvaluationConsistencyError`. Reopen SQLite and require exact typed equality.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_evaluation_facts.py tests/test_evaluation_store.py tests/test_journal_store.py -q
```

- [ ] **Step 5: Implement read-only accessors and fact store**

Schema:

```sql
CREATE TABLE evaluation_decision_facts (... payload_json TEXT NOT NULL);
CREATE TABLE evaluation_equity_facts (... payload_json TEXT NOT NULL);
CREATE TABLE evaluation_dataset_manifests (... payload_json TEXT NOT NULL);
CREATE TABLE evaluation_split_manifests (... payload_json TEXT NOT NULL);
CREATE TABLE evaluation_candidate_sets (... payload_json TEXT NOT NULL);
CREATE TABLE evaluation_oos_consumptions (...);
CREATE TABLE evaluation_results (... payload_json TEXT NOT NULL);
```

Do not import Hyperliquid clients or mutate Phase 8 tables.

- [ ] **Step 6: Verify GREEN**

```bash
python -m pytest tests/test_evaluation_facts.py tests/test_evaluation_store.py tests/test_journal_store.py -q
python -m ruff check src/cocomelon/evaluation src/cocomelon/journal/store.py tests/test_evaluation_facts.py tests/test_evaluation_store.py
python -m mypy src
```

- [ ] **Step 7: Commit**

```bash
git add src/cocomelon/journal/store.py src/cocomelon/evaluation tests/test_evaluation_facts.py tests/test_evaluation_store.py tests/test_journal_store.py
git commit -m "feat: persist immutable evaluation facts"
```

---

### Task 3: Build provenance-complete evaluation datasets

**Files:**
- Create: `src/cocomelon/evaluation/dataset.py`
- Test: `tests/test_evaluation_dataset.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class DatasetBuildResult:
    manifest: EvaluationDatasetManifest
    samples: tuple[TradeEvaluationSample, ...]
    excluded_trade_ids: tuple[str, ...]
    exclusion_reasons: tuple[tuple[str, str], ...]


def build_evaluation_dataset(
    journal: JournalStore,
    facts: EvaluationFactStore,
    *,
    replay_run_ids: Sequence[str],
    code_revision: str,
    allow_mixed_evidence: bool = False,
) -> DatasetBuildResult: ...
```

- [ ] **Step 1: Write RED exact-join tests**

Require trade `strategy_decision_id` + `replay_run_id` joins exactly one decision fact and preserves market/direction/score/strategy/regimes.

A missing fact, market mismatch, direction mismatch, duplicate trade ID, unknown replay result, or replay-result digest mismatch must fail/exclude with a structured reason rather than silently entering primary metrics.

- [ ] **Step 2: Write RED evidence/completeness tests**

- homogeneous candle and microstructure datasets receive the exact evidence label;
- mixed classes reject by default;
- explicit mixed diagnostic mode is labeled mixed/non-primary;
- any included `ReplayResult.data_complete=False` makes primary research readiness false;
- source replay manifest/result IDs and result digests are included in dataset identity.

- [ ] **Step 3: Write RED enumeration determinism tests**

Shuffle replay run order, journal insertion order, fact insertion order, and trade enumeration. Require identical manifest/sample tuple/digest.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_evaluation_dataset.py -q
```

- [ ] **Step 5: Implement builder**

`TradeEvaluationSample` copies only immutable evaluation-relevant values from the validated trade/fact pair; it never recomputes strategy/risk/execution decisions.

Persist the resulting dataset manifest through `EvaluationFactStore.record_dataset_manifest()`.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest tests/test_evaluation_dataset.py tests/test_evaluation_store.py -q
python -m ruff check src/cocomelon/evaluation/dataset.py tests/test_evaluation_dataset.py
python -m mypy src
git add src/cocomelon/evaluation/dataset.py tests/test_evaluation_dataset.py src/cocomelon/evaluation/store.py
git commit -m "feat: freeze provenance-complete evaluation datasets"
```

---

### Task 4: Freeze time splits and mechanically protect untouched OOS

**Files:**
- Create: `src/cocomelon/evaluation/splits.py`
- Modify: `src/cocomelon/evaluation/store.py`
- Test: `tests/test_evaluation_splits.py`
- Test: `tests/test_oos_consumption.py`

**Interfaces:**

```python
def freeze_split_manifest(
    dataset: EvaluationDatasetManifest,
    *,
    train: TimePartition,
    validation: TimePartition,
    test: TimePartition,
    policy: EvaluationPolicy,
) -> FrozenSplitManifest: ...


def split_samples(
    samples: Sequence[TradeEvaluationSample],
    split: FrozenSplitManifest,
) -> Mapping[SplitName, tuple[TradeEvaluationSample, ...]]: ...


def consume_untouched_test(
    store: EvaluationFactStore,
    split: FrozenSplitManifest,
    candidates: FrozenCandidateSet,
    policy: EvaluationPolicy,
) -> OOSStatus: ...
```

- [ ] **Step 1: Write RED chronological-boundary tests**

Require half-open window semantics and full-lifecycle containment. A trade opened before a boundary and closed after it is excluded as `CROSSES_SPLIT_BOUNDARY`.

- [ ] **Step 2: Write RED embargo tests**

For internal boundary `B` and embargo `E`, any trade with lifecycle time inside `[B-E, B+E)` is purged from both neighboring primary partitions. A position lasting longer than `E` that crosses `B` is also purged by lifecycle containment.

- [ ] **Step 3: Write RED OOS consumption tests**

```python
def test_same_candidate_set_can_reproduce_consumed_test(tmp_path: Path) -> None:
    assert consume(...) is OOSStatus.UNTOUCHED
    assert consume(...) is OOSStatus.REPRODUCTION


def test_changed_candidate_set_marks_consumed_test_contaminated(tmp_path: Path) -> None:
    consume(store, split, candidate_set("v1"), policy())
    assert consume(store, split, candidate_set("v2"), policy()) is OOSStatus.CONTAMINATED
```

Changed policy ID or sensitivity-profile set must also contaminate reuse.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_evaluation_splits.py tests/test_oos_consumption.py -q
```

- [ ] **Step 5: Implement and persist frozen split/candidate/consumption records**

OOS consumption key must be based on test-partition semantic digest, not filesystem path.

Do not expose an API that deletes/rewinds OOS consumption in normal runtime.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest tests/test_evaluation_splits.py tests/test_oos_consumption.py tests/test_evaluation_store.py -q
python -m ruff check src/cocomelon/evaluation/splits.py src/cocomelon/evaluation/store.py tests/test_evaluation_splits.py tests/test_oos_consumption.py
python -m mypy src
git add src/cocomelon/evaluation/splits.py src/cocomelon/evaluation/store.py tests/test_evaluation_splits.py tests/test_oos_consumption.py
git commit -m "feat: freeze splits and protect untouched OOS"
```

---

### Task 5: Implement deterministic cost-aware performance metrics

**Files:**
- Create: `src/cocomelon/evaluation/metrics.py`
- Test: `tests/test_evaluation_metrics.py`

**Interfaces:**

```python
def compute_performance_metrics(
    samples: Sequence[TradeEvaluationSample],
    *,
    equity_facts: Sequence[AccountEquityFact] = (),
    equity_curve_complete: bool = False,
) -> PerformanceMetrics: ...
```

- [ ] **Step 1: Write RED expectancy/cost tests**

Frozen Decimal fixture must verify exact totals for gross PnL, fees, funding, signed slippage, net PnL, total/mean/median net R, average winner/loser, win rate, largest win/loss, and holding-duration percentiles.

- [ ] **Step 2: Write RED profit-factor edge cases**

Require normal formula when winners/losses exist. All-win set returns `profit_factor=None` with `NO_LOSING_TRADES`, not infinity. Zero total loss never divides by zero.

- [ ] **Step 3: Write RED drawdown tests**

- realized closed-trade equity curve yields exact maximum drawdown;
- genuine ordered equity facts yield exact mark-to-market drawdown when `equity_curve_complete=True`;
- incomplete equity facts return `account_equity_max_drawdown_fraction=None` with explicit reason rather than silently substituting realized drawdown.

- [ ] **Step 4: Write RED tail/concentration tests**

Require deterministic nearest-rank 5th percentile, 5% expected shortfall, market positive-PnL concentration, strategy concentration, and UTC seven-day positive-PnL concentration.

- [ ] **Step 5: Verify RED**

```bash
python -m pytest tests/test_evaluation_metrics.py -q
```

- [ ] **Step 6: Implement authoritative Decimal metrics**

Use a fixed Decimal context. Sorting/percentile tie behavior must be explicit and tested. Win rate remains descriptive and never drives edge status alone.

- [ ] **Step 7: Verify GREEN and commit**

```bash
python -m pytest tests/test_evaluation_metrics.py -q
python -m ruff check src/cocomelon/evaluation/metrics.py tests/test_evaluation_metrics.py
python -m mypy src
git add src/cocomelon/evaluation/metrics.py tests/test_evaluation_metrics.py
git commit -m "feat: compute deterministic cost-aware evaluation metrics"
```

---

### Task 6: Add deterministic block-bootstrap uncertainty

**Files:**
- Create: `src/cocomelon/evaluation/uncertainty.py`
- Test: `tests/test_evaluation_uncertainty.py`

**Interfaces:**

```python
def mean_net_r_confidence_interval(
    samples: Sequence[TradeEvaluationSample],
    *,
    evaluation_manifest_id: str,
    policy: EvaluationPolicy,
) -> ConfidenceInterval | None: ...
```

- [ ] **Step 1: Write RED deterministic-seed test**

Run the same sample/manifest under hostile ambient global random use and require byte-identical interval/result.

- [ ] **Step 2: Write RED day-block preservation test**

Create trades clustered by UTC day and expose a test helper returning sampled day indices. Require selected 5-day blocks remain contiguous before wrapping/restart logic.

- [ ] **Step 3: Write RED insufficient-evidence test**

Below `min_oos_trades` or `min_oos_days`, return `None`; do not emit a fake zero-width confidence interval.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_evaluation_uncertainty.py -q
```

- [ ] **Step 5: Implement fixed-seed 2,000-resample block bootstrap**

Seed:

```python
seed_bytes = hashlib.sha256(
    f"{evaluation_manifest_id}:mean_net_r".encode("utf-8")
).digest()[:8]
seed = int.from_bytes(seed_bytes, "big")
rng = random.Random(seed)
```

Use nearest-rank percentiles derived from `policy.bootstrap_confidence` and preserve Decimal values in metric calculations.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest tests/test_evaluation_uncertainty.py tests/test_evaluation_metrics.py -q
python -m ruff check src/cocomelon/evaluation/uncertainty.py tests/test_evaluation_uncertainty.py
python -m mypy src
git add src/cocomelon/evaluation/uncertainty.py tests/test_evaluation_uncertainty.py
git commit -m "feat: quantify deterministic evaluation uncertainty"
```

---

### Task 7: Build deterministic walk-forward evaluation

**Files:**
- Create: `src/cocomelon/evaluation/walkforward.py`
- Test: `tests/test_walkforward_evaluation.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class WalkForwardPlan:
    dataset_manifest_id: str
    first_window_start_ms: int
    development_duration_ms: int
    validation_duration_ms: int
    evaluation_duration_ms: int
    step_ms: int
    embargo_ms: int
    expanding: bool
    policy_id: str


def generate_walkforward_windows(
    plan: WalkForwardPlan,
    *,
    dataset_end_ms: int,
) -> tuple[FrozenSplitManifest, ...]: ...


def evaluate_walkforward(
    samples: Sequence[TradeEvaluationSample],
    windows: Sequence[FrozenSplitManifest],
    *,
    policy: EvaluationPolicy,
) -> tuple[WalkForwardWindowResult, ...]: ...
```

- [ ] **Step 1: Write RED anchored/rolling window-generation tests**

Lock exact integer boundaries for expanding and rolling development modes. Windows may never extend beyond dataset end or overlap their own train/validation/evaluation order.

- [ ] **Step 2: Write RED no-leakage tests**

Future samples added after an earlier window evaluation end may not alter that earlier window's included trade IDs or metrics.

- [ ] **Step 3: Write RED readiness/aggregation tests**

A window with fewer than `min_trades_per_walkforward_window` remains in the report but `eligible=False`. Only eligible evaluation partitions count toward positive-window fraction and aggregate walk-forward evidence.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_walkforward_evaluation.py -q
```

- [ ] **Step 5: Implement windows using Task 4 split/purge logic and Task 5 metrics**

Do not fit/tune a strategy in Phase 9 train/validation windows. They define temporal context and future Phase 10-compatible structure only.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest tests/test_walkforward_evaluation.py tests/test_evaluation_splits.py tests/test_evaluation_metrics.py -q
python -m ruff check src/cocomelon/evaluation/walkforward.py tests/test_walkforward_evaluation.py
python -m mypy src
git add src/cocomelon/evaluation/walkforward.py tests/test_walkforward_evaluation.py
git commit -m "feat: evaluate deterministic walk-forward stability"
```

---

### Task 8: Add slice diagnostics and predeclared cost sensitivity

**Files:**
- Create: `src/cocomelon/evaluation/slices.py`
- Create: `src/cocomelon/evaluation/sensitivity.py`
- Test: `tests/test_evaluation_slices.py`
- Test: `tests/test_evaluation_sensitivity.py`

**Interfaces:**

```python
def evaluate_slices(
    samples: Sequence[TradeEvaluationSample],
    *,
    policy: EvaluationPolicy,
) -> tuple[SliceMetrics, ...]: ...


@dataclass(frozen=True, slots=True)
class CostStressProfile:
    profile_id: str
    fee_multiplier: Decimal
    adverse_slippage_multiplier: Decimal
    adverse_funding_multiplier: Decimal
    remove_favorable_slippage: bool
    remove_favorable_funding: bool


def apply_cost_stress(
    sample: TradeEvaluationSample,
    profile: CostStressProfile,
) -> Decimal: ...
```

- [ ] **Step 1: Write RED slice tests**

Require deterministic reports by market, lead strategy, direction, trend regime, volatility regime, UTC hour, evidence class, and fixed 10-point score bucket.

Buckets below `min_score_bucket_trades` remain visible but `research_ready=False`.

- [ ] **Step 2: Write RED score semantics test**

Ensure output field is named `score_bucket`, not probability/calibration probability, and fixed bucket boundaries do not change when sample distribution changes.

- [ ] **Step 3: Write RED sensitivity formula tests**

For each base sample:

```text
reference_gross = gross_realized_pnl + entry_slippage_amount + exit_slippage_amount
stressed_slippage = multiplier * max(total_signed_slippage, 0)
stressed_funding = 0 if funding > 0 and remove_favorable_funding else funding * adverse_multiplier when funding < 0
stressed_net = reference_gross - stressed_fees - stressed_slippage + stressed_funding
```

Handle entry/exit signed slippage separately before summing adverse drag so favorable one leg cannot hide adverse slippage on another.

- [ ] **Step 4: Write RED monotonic-stress regression**

The fixed adverse stress profiles may not improve net PnL relative to the corresponding conservative base reconstruction because of sign mistakes.

- [ ] **Step 5: Verify RED**

```bash
python -m pytest tests/test_evaluation_slices.py tests/test_evaluation_sensitivity.py -q
```

- [ ] **Step 6: Implement fixed profiles**

Provide exactly:

- `base`;
- `fees_1_25x`;
- `adverse_slippage_1_50x`;
- `adverse_funding_1_50x`;
- `combined_stress`.

No API auto-selects the best profile and no grid-search helper exists.

- [ ] **Step 7: Verify GREEN and commit**

```bash
python -m pytest tests/test_evaluation_slices.py tests/test_evaluation_sensitivity.py -q
python -m ruff check src/cocomelon/evaluation/slices.py src/cocomelon/evaluation/sensitivity.py tests/test_evaluation_slices.py tests/test_evaluation_sensitivity.py
python -m mypy src
git add src/cocomelon/evaluation/slices.py src/cocomelon/evaluation/sensitivity.py tests/test_evaluation_slices.py tests/test_evaluation_sensitivity.py
git commit -m "feat: add evaluation slices and cost stress"
```

---

### Task 9: Add lookahead-safe NO_TRADE missed-opportunity diagnostics

**Files:**
- Create: `src/cocomelon/evaluation/no_trade.py`
- Test: `tests/test_no_trade_evaluation.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class NoTradeHorizonOutcome:
    decision_fact_id: str
    horizon_ms: int
    start_mark: Decimal | None
    end_mark: Decimal | None
    end_return_fraction: Decimal | None
    max_up_fraction: Decimal | None
    max_down_fraction: Decimal | None
    complete: bool
    reason_codes: tuple[str, ...]


def evaluate_no_trade_outcomes(
    decisions: Sequence[DecisionEvaluationFact],
    records: Sequence[ReplayRecord],
    *,
    policy: EvaluationPolicy,
    sample_numerator: int,
    sample_denominator: int,
) -> tuple[NoTradeHorizonOutcome, ...]: ...
```

- [ ] **Step 1: Write RED sampling/lookahead tests**

Reuse Phase 8 `should_sample_no_trade()` for deterministic inclusion. A mark received after decision time cannot become the start mark even if its exchange timestamp is earlier.

- [ ] **Step 2: Write RED horizon/gap tests**

For 1h/4h horizons, use only evidence with `available_at_ms > decision.timestamp_ms` and within horizon. Any known data gap intersecting the horizon sets `complete=False`.

- [ ] **Step 3: Write RED no-fabrication test**

Source scan `no_trade.py` and assert it imports no L2 fill simulator and contains no synthetic book/fill construction. Result contract contains mark movement only, never hypothetical PnL/fill fields.

- [ ] **Step 4: Verify RED**

```bash
python -m pytest tests/test_no_trade_evaluation.py -q
```

- [ ] **Step 5: Implement mark-only outcome diagnostics**

Use the latest genuine mark available at/before decision as start mark; later marks determine end and extrema. Missing start/future marks produce unavailable outcomes with reasons.

- [ ] **Step 6: Verify GREEN and commit**

```bash
python -m pytest tests/test_no_trade_evaluation.py tests/test_replay_lookahead.py -q
python -m ruff check src/cocomelon/evaluation/no_trade.py tests/test_no_trade_evaluation.py
python -m mypy src
git add src/cocomelon/evaluation/no_trade.py tests/test_no_trade_evaluation.py
git commit -m "feat: measure no-trade outcomes without fabricated fills"
```

---

### Task 10: Assemble the Phase 9 evaluation engine and edge status

**Files:**
- Create: `src/cocomelon/evaluation/engine.py`
- Modify: `src/cocomelon/evaluation/store.py`
- Test: `tests/test_evaluation_engine.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class EvaluationRequest:
    dataset: EvaluationDatasetManifest
    split: FrozenSplitManifest
    candidates: FrozenCandidateSet
    policy: EvaluationPolicy
    walkforward_plan: WalkForwardPlan
    sensitivity_profiles: tuple[CostStressProfile, ...]


class EvaluationEngine:
    def __init__(
        self,
        journal: JournalStore,
        facts: EvaluationFactStore,
    ) -> None: ...

    def run(self, request: EvaluationRequest) -> EvaluationResult: ...
```

- [ ] **Step 1: Write RED status matrix tests**

Fixtures must produce each status:

- invalid join/evidence -> `INVALID_EVIDENCE`;
- changed candidate on consumed test -> `OOS_CONTAMINATED`;
- <100 OOS trades or <30 days -> `INSUFFICIENT_EVIDENCE`;
- ready sample with nonpositive/lower-CI/walk-forward failure -> `NO_EDGE_DEMONSTRATED`;
- ready positive untouched sample with lower CI > 0 and stable walk-forward/concentration -> `CANDIDATE_EDGE`.

- [ ] **Step 2: Write RED concentration anti-lucky-window tests**

A profitable candidate with >35% positive PnL from one market or >50% from one UTC seven-day bucket cannot receive `CANDIDATE_EDGE`.

- [ ] **Step 3: Write RED promotion-preview tests**

`PromotionGatePreview` reports but does not control execution. Verify exact checks for PF 1.20, drawdown 8%, market 35%, seven-day 50%, trades 500, days 45, unresolved invariants, and always `preview_only is True`.

- [ ] **Step 4: Write RED idempotency test**

Run identical request twice against restarted stores and require the same `EvaluationResult`, evaluation ID/digest, OOS reproduction status, and no duplicate consumption rows.

- [ ] **Step 5: Verify RED**

```bash
python -m pytest tests/test_evaluation_engine.py -q
```

- [ ] **Step 6: Implement orchestration**

Order:

1. load/freeze dataset and facts;
2. validate split/candidate/policy identities;
3. consume OOS partition;
4. split/purge samples;
5. compute train/validation/test metrics;
6. compute test uncertainty;
7. compute walk-forward windows;
8. compute slices/sensitivity;
9. derive edge status;
10. build read-only live-gate preview;
11. persist exact canonical result.

No stage can mutate trading state or select a better strategy parameter.

- [ ] **Step 7: Verify GREEN and commit**

```bash
python -m pytest tests/test_evaluation_engine.py tests/test_evaluation_metrics.py tests/test_evaluation_uncertainty.py tests/test_walkforward_evaluation.py -q
python -m ruff check src/cocomelon/evaluation/engine.py tests/test_evaluation_engine.py
python -m mypy src
git add src/cocomelon/evaluation/engine.py src/cocomelon/evaluation/store.py tests/test_evaluation_engine.py
git commit -m "feat: gate baseline edge with untouched OOS evidence"
```

---

### Task 11: Add offline operator commands

**Files:**
- Modify: `src/cocomelon/cli.py`
- Test: `tests/test_phase9_cli.py`

**Interfaces:**

Add:

```text
cocomelon freeze-evaluation-dataset --journal PATH --facts PATH --run-id ID [--run-id ID...]
cocomelon freeze-evaluation-splits --facts PATH --dataset-id ID --spec PATH
cocomelon evaluate --journal PATH --facts PATH --dataset-id ID --split-id ID --candidate-spec PATH --walkforward-spec PATH
cocomelon inspect-evaluation --facts PATH --evaluation-id ID
```

- [ ] **Step 1: Write RED parser tests**

Require explicit local paths/IDs. Reject unknown network/testnet/live/optimization options. `evaluate` cannot invent split boundaries or candidate policy implicitly.

- [ ] **Step 2: Write RED machine-readable output tests**

Freeze commands print manifest IDs and canonical payloads. Evaluate prints edge status, test/OOS status, counts, result digest, and preview-only promotion checks. Inspect is read-only.

- [ ] **Step 3: Verify RED**

```bash
python -m pytest tests/test_phase9_cli.py -q
```

- [ ] **Step 4: Implement minimal offline routing**

No implicit Hyperliquid fetch, no automatic sensitivity search, no live switch.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest tests/test_phase9_cli.py tests/test_phase8_cli.py tests/test_cli.py -q
python -m ruff check src/cocomelon/cli.py tests/test_phase9_cli.py
python -m mypy src
git add src/cocomelon/cli.py tests/test_phase9_cli.py
git commit -m "feat: expose offline Phase 9 evaluation tooling"
```

---

### Task 12: End-to-end Phase 8 -> Phase 9 research fixture and boundaries

**Files:**
- Create: `tests/test_phase9_evaluation_pipeline.py`
- Create: `tests/test_phase9_boundaries.py`
- Modify: smallest Phase 8 replay test adapter/fact hook only if required to expose already-existing `StrategyDecision`, `FeatureSnapshot`, or `PaperAccountState` values without changing trading formulas.

**Interfaces:**
- Consumes frozen Phase 8 journal/replay output plus Phase 9 decision/account facts.
- Produces deterministic `EvaluationResult` only.

- [ ] **Step 1: Write frozen positive/weak/small evaluation fixtures**

Construct synthetic **evaluation facts/trade results**, not synthetic market microstructure, to test statistics at sufficient sample size:

- 120-trade / >=30-day positive untouched candidate with diversified PnL and stable walk-forward -> `CANDIDATE_EDGE`;
- ready weak candidate -> `NO_EDGE_DEMONSTRATED`;
- 40-trade candidate -> `INSUFFICIENT_EVIDENCE`.

The synthetic layer represents already-closed research outcomes and must never be passed off as historical Hyperliquid fills.

- [ ] **Step 2: Add a genuine small Phase 8 replay -> Phase 9 fact integration test**

Reuse the existing Phase 8 deterministic replay fixture to prove real `StrategyDecision`/`FeatureSnapshot`/paper-account objects create matching Phase 9 facts and join the resulting trade IDs without changing Phase 8 replay digest.

- [ ] **Step 3: Add contaminated/concentrated regressions**

Changed candidate on consumed test -> `OOS_CONTAMINATED`. Profitable but concentrated candidate -> not `CANDIDATE_EDGE`.

- [ ] **Step 4: Add boundary tests**

Source-scan `src/cocomelon/evaluation` and Phase 9 CLI surfaces for:

- `testnet` URLs/capability;
- HTTP/WebSocket/Hyperliquid clients;
- wallet/private key/signing;
- withdraw/transfer;
- live order/cancel capability;
- ML libraries/training;
- grid/random/Bayesian parameter search or objective-maximization loops;
- candle-to-book construction.

Also assert base dependencies remain free of numpy/pandas/sklearn/lightgbm/xgboost additions unless separately justified in a later phase.

- [ ] **Step 5: Verify focused GREEN**

```bash
python -m pytest tests/test_phase9_evaluation_pipeline.py tests/test_phase9_boundaries.py -q
```

- [ ] **Step 6: Run complete core verification**

```bash
python -m pip install -e ".[dev]"
python -m compileall -q src tests scripts
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
```

Expected: PASS on Python 3.12.

- [ ] **Step 7: Run research regression verification**

```bash
python -m pip install -e ".[dev,research]"
python -m pytest tests/test_replay_compaction.py tests/test_parquet_replay_source.py -q
```

Expected: PASS; Phase 9 must not break Phase 8 optional research tooling.

- [ ] **Step 8: Commit**

```bash
git add tests/test_phase9_evaluation_pipeline.py tests/test_phase9_boundaries.py
git commit -m "test: prove deterministic Phase 9 research gates"
```

---

### Task 13: Phase 9 continuity docs, PR audit, and guarded merge

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/CHATGPT_PROJECT_SOURCE.md`
- Modify: `docs/DECISIONS.md` only if implementation changes a genuinely locked product/architecture decision beyond this versioned Phase 9 policy.

- [ ] **Step 1: Audit every Phase 9 exit criterion**

Record concrete evidence for:

- fact/journal reconciliation;
- dataset/split/candidate/policy determinism;
- untouched OOS consumption protection;
- boundary purge/embargo;
- cost-aware metrics and uncertainty;
- walk-forward stability;
- slice/concentration diagnostics;
- fixed sensitivity behavior;
- NO_TRADE evidence safety;
- full core CI;
- Phase 8 research-extra regression;
- Phase 9 source boundaries.

- [ ] **Step 2: Run one evaluation against the available real recorded baseline evidence if the repository has enough persisted local/fixture-accessible data**

Do not fabricate missing real history. Record exactly one honest state:

- `CANDIDATE_EDGE`;
- `NO_EDGE_DEMONSTRATED`;
- `INSUFFICIENT_EVIDENCE`;
- `INVALID_EVIDENCE`.

If the connected environment cannot access a persisted real recording/journal corpus, record that Phase 9 infrastructure is verified but real baseline evidence remains unmeasured; do not substitute synthetic test data as economic proof.

- [ ] **Step 3: Update continuity docs**

Record feature head, PR number, exact CI run/job IDs, Python version, final commands, current evidence status, and live-trading-disabled boundary. Phase 10 becomes active only after Phase 9 merge and only if the build order/edge evidence permits proceeding; no ML model receives live authority.

- [ ] **Step 4: Audit PR surface**

Verify no unrelated files, no secrets, no unresolved review threads, no hidden network/live capability, no parameter optimizer, and branch not unexpectedly behind `main`.

- [ ] **Step 5: Run final CI on the exact closeout head**

Never merge using CI from an earlier head.

- [ ] **Step 6: Guarded merge**

Merge only with expected-head SHA protection after exact-head CI is green and PR is mergeable.

- [ ] **Step 7: Verify post-merge state and reconcile metadata**

Require `main` at returned merge SHA, feature-to-main file diff empty with main ahead only by merge commit, then update continuity docs on `main` with actual merge SHA and next active phase.

Live trading remains disabled regardless of evaluation outcome.
