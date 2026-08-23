# Phase 5 Baseline Strategy Engines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build explainable deterministic trend, breakout, mean-reversion, funding/OI, and real-order-flow strategy engines plus a regime-aware LONG/SHORT/NO_TRADE combiner, without adding risk sizing or execution.

**Architecture:** Three primary engines may originate directional theses; two context engines may reinforce, weaken, or veto but cannot originate trades. All outputs use shared immutable strategy contracts that reference the exact Phase 4 feature snapshot, and the final deterministic combiner preserves Phase 4 eligibility/deep-readiness as hard preconditions.

**Tech Stack:** Python 3.12, stdlib `dataclasses`/`Decimal`, existing Cocomelon Phase 1-4 domain/feature/stream contracts, pytest, Ruff, mypy, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-23-phase-5-baseline-strategies-design.md`

## Global Constraints

- Hyperliquid testnet is forbidden.
- Runtime observations remain Hyperliquid mainnet only.
- Strategy code may propose direction/invalidation only; no quantity, leverage, account equity, risk budget, order type, wallet, signing, fill simulation, or exchange action belongs in Phase 5.
- `NO_TRADE` is a first-class normal result.
- Financial values use `Decimal`.
- Scores are deterministic evidence strengths in `[0, 100]`, not calibrated probabilities.
- Opportunity rank is not directional evidence and is not a required strategy input.
- Order-flow logic may consume only real normalized Phase 3 `TRADE` and `L2_BOOK` events; candles must never be accepted as synthetic order-flow history.
- Every directional final decision references the exact `FeatureSnapshot.snapshot_id` and a valid lead-primary invalidation.
- All decision-time data must be lookahead-safe.
- Each task follows RED -> GREEN -> full relevant verification -> commit.

---

### Task 1: Evolve strategy domain contracts

**Files:**
- Modify: `src/cocomelon/domain/strategy.py`
- Modify: `tests/test_domain.py`
- Create: `tests/test_strategy_contracts.py`

**Interfaces:**
- Consumes: `MarketId`, `PerpMarketSnapshot`, `Candle`, `FeatureSnapshot`, `EligibilityDecision`.
- Produces: `StrategyRole`, evolved `StrategySignal`, `MicrostructureWindow`, `StrategyContext`, `StrategyDecision`.

- [ ] **Step 1: Write failing contract tests**

Add tests that require:

```python
from decimal import Decimal

from cocomelon.domain.strategy import (
    Direction,
    MicrostructureWindow,
    StrategyContext,
    StrategyDecision,
    StrategyRole,
    StrategySignal,
)


def test_directional_primary_requires_decimal_invalidation_and_feature_reference() -> None:
    signal = StrategySignal(
        strategy="trend",
        role=StrategyRole.PRIMARY,
        market=market("BTC"),
        direction=Direction.LONG,
        score=Decimal("75"),
        timestamp_ms=1_000,
        reason_codes=("trend_up", "return_15m_aligned"),
        feature_snapshot_id="feature-1",
        invalidation_price=Decimal("99"),
        veto_directions=(),
    )
    assert signal.signal_id == StrategySignal(**signal_as_kwargs(signal)).signal_id


def test_context_signal_cannot_set_invalidation() -> None:
    with pytest.raises(ValueError, match="context"):
        StrategySignal(
            strategy="order_flow",
            role=StrategyRole.CONTEXT,
            market=market("BTC"),
            direction=Direction.LONG,
            score=Decimal("75"),
            timestamp_ms=1_000,
            reason_codes=("flow_support_long",),
            feature_snapshot_id="feature-1",
            invalidation_price=Decimal("99"),
            veto_directions=(),
        )


def test_context_veto_cannot_include_no_trade() -> None:
    with pytest.raises(ValueError, match="veto"):
        StrategySignal(
            strategy="funding_oi",
            role=StrategyRole.CONTEXT,
            market=market("BTC"),
            direction=Direction.NO_TRADE,
            score=Decimal("100"),
            timestamp_ms=1_000,
            reason_codes=("crowded",),
            feature_snapshot_id="feature-1",
            invalidation_price=None,
            veto_directions=(Direction.NO_TRADE,),
        )


def test_strategy_decision_contains_no_risk_or_order_fields() -> None:
    fields = StrategyDecision.__dataclass_fields__
    forbidden = {"quantity", "leverage", "risk_budget", "order_type", "wallet"}
    assert forbidden.isdisjoint(fields)
```

Update the Phase 1 domain tests so all existing `StrategySignal` constructors use `Decimal`, `StrategyRole`, `feature_snapshot_id`, `reason_codes`, and `veto_directions`.

- [ ] **Step 2: Run contract tests to prove RED**

Run:

```bash
python -m pytest -q tests/test_strategy_contracts.py tests/test_domain.py
```

Expected: FAIL because the new contracts/fields do not exist yet.

- [ ] **Step 3: Implement immutable contracts**

Implement in `domain/strategy.py`:

```python
class StrategyRole(StrEnum):
    PRIMARY = "primary"
    CONTEXT = "context"


@dataclass(frozen=True, slots=True)
class StrategySignal:
    strategy: str
    role: StrategyRole
    market: MarketId
    direction: Direction
    score: Decimal
    timestamp_ms: int
    reason_codes: tuple[str, ...]
    feature_snapshot_id: str
    invalidation_price: Decimal | None
    veto_directions: tuple[Direction, ...]

    @property
    def signal_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class MicrostructureWindow:
    market: MarketId
    start_ms: int
    as_of_ms: int
    trade_count: int
    buy_notional: Decimal
    sell_notional: Decimal
    trade_flow_imbalance: Decimal | None
    latest_book_imbalance: Decimal | None
    book_imbalance_change: Decimal | None
    latest_event_age_ms: int | None
    event_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyContext:
    market_snapshot: PerpMarketSnapshot
    feature_snapshot: FeatureSnapshot
    eligibility: EligibilityDecision
    candles_5m: tuple[Candle, ...]
    candles_15m: tuple[Candle, ...]
    microstructure: MicrostructureWindow | None
    as_of_ms: int


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    market: MarketId
    direction: Direction
    score: Decimal
    timestamp_ms: int
    feature_snapshot_id: str
    lead_strategy: str | None
    invalidation_price: Decimal | None
    signal_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @property
    def decision_id(self) -> str: ...
```

Validation must exactly enforce the spec: finite score range, role/invalidation/veto combinations, matching markets in `StrategyContext`, deterministic normalized reason/signal ordering, and directional-decision requirements.

- [ ] **Step 4: Run contract tests GREEN**

```bash
python -m pytest -q tests/test_strategy_contracts.py tests/test_domain.py
python -m ruff check src/cocomelon/domain/strategy.py tests/test_strategy_contracts.py tests/test_domain.py
python -m mypy src
```

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: evolve strategy domain contracts`

---

### Task 2: Add lookahead-safe candle/reference helpers

**Files:**
- Create: `src/cocomelon/strategies/__init__.py`
- Create: `src/cocomelon/strategies/candles.py`
- Create: `tests/test_strategy_candles.py`

**Interfaces:**
- Consumes: `StrategyContext`, `Candle`, `Direction`.
- Produces: `closed_candles(context, interval)`, `reference_price(context)`, `swing_invalidation(context, direction, window=4)`.

- [ ] **Step 1: Write failing tests**

Cover:

```python
def test_closed_candles_filters_future_end_and_future_receive_time() -> None: ...
def test_closed_candles_rejects_market_or_interval_mismatch() -> None: ...
def test_reference_price_prefers_positive_mid_then_mark() -> None: ...
def test_swing_invalidation_uses_latest_four_closed_15m_candles() -> None: ...
def test_wrong_side_invalidation_returns_none() -> None: ...
```

Use synthetic candles only for candle logic.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_strategy_candles.py
```

Expected: FAIL because `cocomelon.strategies.candles` does not exist.

- [ ] **Step 3: Implement helpers**

Use deterministic `(end_ms, start_ms)` sorting. Include only candles whose `end_ms <= as_of_ms` and `received_at_ms <= as_of_ms`. Reject mismatched market/interval. `reference_price` returns a positive finite `mid_px`, else positive finite `mark_px`, else `None`. Swing invalidation uses the latest four closed 15m candles and returns `None` if it is not strictly below LONG reference or above SHORT reference.

- [ ] **Step 4: Verify GREEN**

```bash
python -m pytest -q tests/test_strategy_candles.py
python -m ruff check src/cocomelon/strategies/candles.py tests/test_strategy_candles.py
python -m mypy src
```

- [ ] **Step 5: Commit**

Commit message: `feat: add strategy candle helpers`

---

### Task 3: Implement trend primary engine

**Files:**
- Create: `src/cocomelon/strategies/trend.py`
- Create: `tests/test_strategy_trend.py`

**Interfaces:**
- Consumes: `StrategyContext`, candle helpers.
- Produces: `evaluate_trend(context: StrategyContext) -> StrategySignal`.

- [ ] **Step 1: Write exact-score RED tests**

Cover aligned UP/DOWN, hard 15m/1h opposition, optional 4h/5m/relative-volume/book points, insufficient candles, and invalid invalidation.

Required exact base scoring:

```text
25 regime
+20 15m aligned
+20 1h aligned
+10 4h aligned
+5 5m aligned
+5 relative_volume_15m >= 1.00
+5 book imbalance >= +0.10 LONG / <= -0.10 SHORT
threshold 65
```

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_strategy_trend.py
```

- [ ] **Step 3: Implement `evaluate_trend`**

Hard requirements: `rankable`, `deep_ready`, trend regime UP/DOWN, 15m+1h returns, four closed 15m candles. Return PRIMARY NO_TRADE with stable reason codes when blocked. Directional signal owns swing invalidation from Task 2.

- [ ] **Step 4: Verify GREEN**

```bash
python -m pytest -q tests/test_strategy_trend.py
python -m mypy src
python -m ruff check src tests/test_strategy_trend.py
```

- [ ] **Step 5: Commit**

Commit message: `feat: add trend strategy baseline`

---

### Task 4: Implement breakout primary engine

**Files:**
- Create: `src/cocomelon/strategies/breakout.py`
- Create: `tests/test_strategy_breakout.py`

**Interfaces:**
- Consumes: `StrategyContext`, closed 15m candle helper, reference-price helper.
- Produces: `evaluate_breakout(context: StrategyContext) -> StrategySignal`.

- [ ] **Step 1: Write RED tests**

Prove the latest trigger candle is excluded from the prior 20-candle range; cover confirmed upside/downside breakout, no breakout, missing expansion confirmation, optional aligned 1h return, future trigger exclusion, and wrong-side invalidation.

Exact scoring:

```text
50 structural close beyond range
+20 relative_volume_15m >= 1.20
+20 range_expansion_15m >= 1.10
+10 aligned 1h return
threshold 70
mandatory at least one expansion confirmation
```

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_strategy_breakout.py
```

- [ ] **Step 3: Implement**

Use exactly 20 prior closed 15m candles plus one latest trigger. LONG invalidation is trigger low; SHORT invalidation is trigger high. Do not relax confirmation to force trades.

- [ ] **Step 4: Verify GREEN**

```bash
python -m pytest -q tests/test_strategy_breakout.py
python -m ruff check src tests/test_strategy_breakout.py
python -m mypy src
```

- [ ] **Step 5: Commit**

Commit message: `feat: add breakout strategy baseline`

---

### Task 5: Implement mean-reversion primary engine

**Files:**
- Create: `src/cocomelon/strategies/mean_reversion.py`
- Create: `tests/test_strategy_mean_reversion.py`

**Interfaces:**
- Consumes: `StrategyContext`, candle helpers.
- Produces: `evaluate_mean_reversion(context: StrategyContext) -> StrategySignal`.

- [ ] **Step 1: Write RED tests**

Cover positive stretch -> SHORT, negative stretch -> LONG, MIXED regime requirement, HIGH/UNKNOWN vol blocks, zero/missing realized vol blocks, exact stretch points, optional range/5m/1h points, and invalidation behavior.

Exact scoring:

```text
45 compatible regime + stretch >= 1.75
+20 stretch >= 2.25
+15 range_expansion_15m >= 1.10
+10 5m return in proposed reversion direction
+10 1h return in proposed reversion direction
threshold 65
```

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_strategy_mean_reversion.py
```

- [ ] **Step 3: Implement**

Use `abs(return_15m) / realized_vol_15m` only for positive finite realized volatility. Emit NO_TRADE outside MIXED + LOW/NORMAL volatility. Use four-candle swing invalidation.

- [ ] **Step 4: Verify GREEN**

```bash
python -m pytest -q tests/test_strategy_mean_reversion.py
python -m ruff check src tests/test_strategy_mean_reversion.py
python -m mypy src
```

- [ ] **Step 5: Commit**

Commit message: `feat: add mean reversion strategy baseline`

---

### Task 6: Build real microstructure windows

**Files:**
- Create: `src/cocomelon/strategies/microstructure.py`
- Create: `tests/test_strategy_microstructure.py`

**Interfaces:**
- Consumes: normalized Phase 3 `StreamEvent` with `StreamKind.TRADE` / `StreamKind.L2_BOOK`.
- Produces: `build_microstructure_window(events, *, market, as_of_ms, window_ms=60_000) -> MicrostructureWindow`.

- [ ] **Step 1: Write RED tests against real Phase 3 fixture structures**

Tests must load and normalize:

```text
tests/fixtures/hyperliquid_ws/trades_btc.json
tests/fixtures/hyperliquid_ws/l2_book_btc.json
```

Then prove:

```python
def test_real_trade_fixture_b_side_counts_as_buy_notional() -> None: ...
def test_real_trade_fixture_a_side_counts_as_sell_notional() -> None: ...
def test_trade_flow_imbalance_is_decimal_and_deterministic() -> None: ...
def test_single_real_book_keeps_book_change_none() -> None: ...
def test_candle_event_is_rejected_as_microstructure_input() -> None: ...
def test_future_received_event_cannot_enter_window() -> None: ...
```

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_strategy_microstructure.py
```

- [ ] **Step 3: Implement deterministic window builder**

Normalize ordering by `(receive_ms, exchange_time_ms or -1, event_key)`. Window bounds are `[as_of_ms-window_ms, as_of_ms]` on receive time. `B` adds `price * size` to buy notional; `A` to sell notional. Reject unsupported stream kinds instead of guessing. Compute signed flow imbalance only when total notional is positive. Derive L2 imbalance from actual book payloads using bid/ask visible size sums; with fewer than two usable books, change is `None`.

- [ ] **Step 4: Verify GREEN**

```bash
python -m pytest -q tests/test_strategy_microstructure.py
python -m ruff check src tests/test_strategy_microstructure.py
python -m mypy src
```

- [ ] **Step 5: Commit**

Commit message: `feat: derive real microstructure strategy windows`

---

### Task 7: Implement funding/OI and order-flow context engines

**Files:**
- Create: `src/cocomelon/strategies/funding_oi.py`
- Create: `src/cocomelon/strategies/order_flow.py`
- Create: `tests/test_strategy_funding_oi.py`
- Create: `tests/test_strategy_order_flow.py`

**Interfaces:**
- Produces: `evaluate_funding_oi(context: StrategyContext) -> StrategySignal`; `evaluate_order_flow(context: StrategyContext) -> StrategySignal`.

- [ ] **Step 1: Write funding/OI RED tests**

Exact behavior order:

```text
OI missing/non-positive -> neutral 0
OI >= 3% and funding >= +0.0002 -> neutral 100, veto LONG
OI >= 3% and funding <= -0.0002 -> neutral 100, veto SHORT
15m+1h positive, OI >= 1%, abs(funding) < 0.0001 -> support LONG 70
15m+1h negative, same -> support SHORT 70
crowded non-extreme -> neutral 50
else neutral 0
```

Assert extreme funding never creates the opposite trade.

- [ ] **Step 2: Write order-flow RED tests**

Exact behavior:

```text
missing/stale/<5 trades/missing flow/book -> neutral 0
flow >= +0.60 and book >= +0.30 -> LONG 100, veto SHORT
flow <= -0.60 and book <= -0.30 -> SHORT 100, veto LONG
flow >= +0.35 and book >= +0.15 -> LONG 75
flow <= -0.35 and book <= -0.15 -> SHORT 75
else neutral 0
max event age 2_000ms
```

- [ ] **Step 3: Verify RED**

```bash
python -m pytest -q tests/test_strategy_funding_oi.py tests/test_strategy_order_flow.py
```

- [ ] **Step 4: Implement both context engines**

Both signals use `StrategyRole.CONTEXT`, never set invalidation, and always reference the exact feature snapshot ID.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest -q tests/test_strategy_funding_oi.py tests/test_strategy_order_flow.py
python -m ruff check src tests/test_strategy_funding_oi.py tests/test_strategy_order_flow.py
python -m mypy src
```

Commit message: `feat: add strategy context engines`

---

### Task 8: Implement deterministic regime-aware decision combiner

**Files:**
- Create: `src/cocomelon/strategies/decision.py`
- Create: `tests/test_strategy_decision.py`

**Interfaces:**
- Consumes: `StrategyContext`, tuple of `StrategySignal`.
- Produces: `combine_signals(context: StrategyContext, signals: Sequence[StrategySignal]) -> StrategyDecision`.

- [ ] **Step 1: Write RED tests for hard preconditions**

Prove `not_rankable`, `not_deep_ready`, no primary thesis, and context-only evidence all result in NO_TRADE.

- [ ] **Step 2: Write exact weighting/conflict/context tests**

Use exact tables from the spec:

```text
UP/DOWN: trend 1.00, breakout 0.90, mean_reversion 0.35
MIXED: trend 0.50, breakout 0.80, mean_reversion 1.00
UNKNOWN: trend 0.50, breakout 0.60, mean_reversion 0.50

HIGH: trend 0.90, breakout 1.00, mean_reversion 0.25
NORMAL: 1.00 all
LOW: trend 0.90, breakout 0.75, mean_reversion 1.00
UNKNOWN: 0.75 all
```

Candidate formula:

```text
effective = raw * trend_regime_weight * volatility_modifier
lead = highest effective, tie strategy name
+5 each extra same-direction qualifying primary, cap +10
lead raw >= 60 and candidate >= 60
opposing gap < 15 -> NO_TRADE primary_conflict
```

Context formula:

```text
veto direction -> NO_TRADE
strength = min(10, (score - 50) / 5) for context score > 50
same direction +strength
opposite -strength
total context adjustment clamp [-10,+10]
final directional threshold >= 65
```

Also test deterministic input permutation and lead-primary invalidation ownership.

- [ ] **Step 3: Verify RED**

```bash
python -m pytest -q tests/test_strategy_decision.py
```

- [ ] **Step 4: Implement `combine_signals`**

Reject mismatched-market/snapshot signals. Deterministically sort signals by `(strategy, signal_id)` for stored evidence. NO_TRADE score is strongest rejected candidate after the last completed stage, else zero.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest -q tests/test_strategy_decision.py
python -m ruff check src tests/test_strategy_decision.py
python -m mypy src
```

Commit message: `feat: add deterministic strategy decision combiner`

---

### Task 9: Add Phase 5 strategy orchestrator

**Files:**
- Create: `src/cocomelon/strategies/engine.py`
- Create: `tests/test_strategy_engine.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class StrategyEvaluation:
    signals: tuple[StrategySignal, ...]
    decision: StrategyDecision


def evaluate_strategies(context: StrategyContext) -> StrategyEvaluation:
    ...
```

- [ ] **Step 1: Write RED integration tests**

Require the engine to run all five families in deterministic name order, preserve individual signals, and return the combiner decision. Include one LONG fixture, one SHORT fixture, and multiple NO_TRADE scenarios.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_strategy_engine.py
```

- [ ] **Step 3: Implement orchestration only**

Call:

```python
evaluate_trend(context)
evaluate_breakout(context)
evaluate_mean_reversion(context)
evaluate_funding_oi(context)
evaluate_order_flow(context)
combine_signals(context, signals)
```

No risk/execution/account imports.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python -m pytest -q tests/test_strategy_engine.py
python -m ruff check src tests/test_strategy_engine.py
python -m mypy src
```

Commit message: `feat: orchestrate baseline strategy evaluation`

---

### Task 10: Phase 5 boundary audit, full verification, and continuity docs

**Files:**
- Create: `tests/test_strategy_boundaries.py`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHATGPT_PROJECT_SOURCE.md`
- Modify: PR #6 body/state only after verification.

**Interfaces:**
- Produces: verified Phase 5 feature tree ready for guarded merge.

- [ ] **Step 1: Add boundary tests**

Tests inspect public dataclass fields and module imports/source layout to prove:

```text
no quantity/leverage/risk budget/order fields in StrategyDecision
strategies package does not import cocomelon.domain.risk
strategies package does not import cocomelon.domain.execution
strategies package does not import exchange/wallet/account APIs
no ML dependency
microstructure builder accepts only TRADE/L2_BOOK
```

- [ ] **Step 2: Run focused Phase 5 suite**

```bash
python -m pytest -q tests/test_strategy_contracts.py tests/test_strategy_candles.py tests/test_strategy_trend.py tests/test_strategy_breakout.py tests/test_strategy_mean_reversion.py tests/test_strategy_microstructure.py tests/test_strategy_funding_oi.py tests/test_strategy_order_flow.py tests/test_strategy_decision.py tests/test_strategy_engine.py tests/test_strategy_boundaries.py
```

- [ ] **Step 3: Run full repository verification**

```bash
python -m compileall -q src tests scripts
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
```

All must pass on Python 3.12 in GitHub Actions.

- [ ] **Step 4: Audit spec exit criteria line by line**

Explicitly verify:

```text
five engines exist
shared immutable StrategySignal exists
deterministic LONG/SHORT/NO_TRADE combiner exists
eligibility/deep-ready cannot be bypassed
NO_TRADE is normal and covered
feature snapshot reference preserved
directional invalidation owned by primary thesis
real Phase 3 trade/L2 fixtures ground order-flow tests
no candle-derived fake microstructure
no risk, paper execution, wallet/account, orders, ML, or live execution
```

- [ ] **Step 5: Update continuity docs with exact CI evidence**

Record branch head, CI run/job, Python version, compile/Ruff/mypy/pytest results, Phase 5 architecture summary, and exact next Phase 6 objective.

- [ ] **Step 6: Merge only with expected-head protection**

Mark PR #6 ready only after final CI is green. Re-read head/mergeability, then merge with the exact verified head SHA. Verify `main` points to the merge commit and the temporary branch contains no unmerged runtime changes.

- [ ] **Step 7: Commit/closeout**

If the merge itself changes continuity metadata, use a docs-only closeout branch/PR just as Phase 4 did. Then Phase 6 — independent risk engine — becomes active.
