# Phase 6 Independent Risk Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, fail-closed independent risk engine that converts a Phase 5 directional strategy decision into a bounded exposure approval or explicit rejection without placing orders.

**Architecture:** Immutable Decimal-based risk inputs feed a fixed pure-function rule pipeline. Hard vetoes run before sizing; surviving requests receive cost-aware base sizing and are clipped by aggregate risk, correlation, gross leverage, margin, liquidity, liquidation-buffer, and venue-minimum constraints. Phase 6 returns only a risk approval envelope; Phase 7 later translates that envelope into paper execution.

**Tech Stack:** Python 3.12, standard library `dataclasses`, `Decimal`, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-23-phase-6-independent-risk-design.md`

## Global Constraints

- Hyperliquid testnet is forbidden.
- Runtime market observations remain Hyperliquid mainnet only.
- Default execution mode remains paper; live trading remains disabled.
- Risk is independent from strategy conviction and has final veto power.
- Planned account risk per trade is 0.25% of current equity.
- Maximum aggregate planned open risk is 0.75% of current equity.
- Daily realized-loss lockout is 1.00% of day-start equity.
- Rolling weekly drawdown lockout is 3.00% from rolling seven-day peak equity.
- Three consecutive losing trades trigger a 60-minute cooldown.
- Correlation-bucket planned-risk cap is 0.50% of equity.
- System gross leverage ceiling is 3x or lower venue maximum.
- A new position may consume at most 50% of currently available margin.
- New notional may consume at most 10% of the weaker visible 25-bps entry/exit-side notional.
- Liquidation distance must be beyond the stop and at least 2x entry-to-stop distance.
- Unknown crypto markets default to the shared `crypto_beta` correlation bucket.
- Financial, ratio, PnL, notional, and price calculations use `Decimal`.
- Strategy score never increases the 0.25% risk budget.
- No averaging down, same-market add-on entry, pyramiding, martingale, loss-recovery sizing, order placement, wallet/account exchange API, fill simulation, ML, or live execution belongs in Phase 6.

---

### Task 1: Replace the Phase 1 risk placeholder with immutable Decimal contracts

**Files:**
- Modify: `src/cocomelon/domain/risk.py`
- Modify: `src/cocomelon/config.py`
- Test: `tests/test_risk_contracts.py`
- Modify: `tests/test_config.py` only where Decimal defaults require expectation updates.

**Interfaces:**
- Consumes: `MarketId`, Phase 5 `Direction`, `StrategyDecision`.
- Produces: `RiskLimits`, `RiskAccountState`, `OpenPositionRisk`, `RiskHealthState`, `ExecutionCostEstimate`, `LiquidityRiskState`, `RiskRequest`, evolved `RiskDecision`.

- [ ] **Step 1: Write RED contract tests**

Cover exact Decimal defaults, frozen/slotted dataclasses, finite/positive validation, deterministic IDs, matching strategy/request identity, rejection exposure invariants, and no execution/order fields.

Required defaults:

```python
assert RiskLimits().risk_per_trade == Decimal("0.0025")
assert RiskLimits().max_open_risk == Decimal("0.0075")
assert RiskLimits().daily_loss_limit == Decimal("0.01")
assert RiskLimits().weekly_drawdown_limit == Decimal("0.03")
assert RiskLimits().correlation_bucket_risk_limit == Decimal("0.005")
assert RiskLimits().max_gross_leverage == Decimal("3")
assert RiskLimits().max_available_margin_fraction == Decimal("0.50")
assert RiskLimits().max_visible_depth_fraction == Decimal("0.10")
assert RiskLimits().min_liquidation_stop_multiple == Decimal("2")
assert RiskLimits().cooldown_ms == 3_600_000
```

`RiskDecision(approved=False, ...)` must reject any non-zero `approved_risk_amount` or `approved_notional`.

- [ ] **Step 2: Run RED**

```bash
python -m pytest -q tests/test_risk_contracts.py tests/test_config.py
```

Expected: FAIL because the new contracts/defaults do not exist.

- [ ] **Step 3: Implement contracts**

Use canonical deterministic JSON-like serialization of normalized string values plus SHA-256 truncation for IDs, consistent with existing deterministic domain-ID patterns. Validate every Decimal with `is_finite()` and explicit sign/range rules. Keep reason/binding-cap tuples normalized deterministically.

Change existing risk percentage fields in `Settings` to Decimal defaults and add the new Phase 6 risk defaults. Do not add environment-driven live-risk overrides in this phase.

- [ ] **Step 4: Run GREEN**

```bash
python -m pytest -q tests/test_risk_contracts.py tests/test_config.py
python -m ruff check src/cocomelon/domain/risk.py src/cocomelon/config.py tests/test_risk_contracts.py tests/test_config.py
python -m mypy src
```

- [ ] **Step 5: Commit**

Commit message: `feat: add immutable risk domain contracts`

---

### Task 2: Add pure request/stop/freshness validation

**Files:**
- Create: `src/cocomelon/risk/__init__.py`
- Create: `src/cocomelon/risk/validation.py`
- Test: `tests/test_risk_validation.py`

**Interfaces:**
- Consumes: `RiskRequest`.
- Produces: `validate_request(request) -> tuple[str, ...]`; empty tuple means validation passed.

- [ ] **Step 1: Write RED tests**

Cover:

```text
NO_TRADE -> strategy_no_trade
missing directional stop -> missing_stop
LONG stop >= entry -> invalid_stop_side
SHORT stop <= entry -> invalid_stop_side
non-positive entry -> invalid_entry_price
future account/health/liquidity state -> risk_state_inconsistent
state age > max_state_age_ms -> stale_account_state / stale_market_data
market_data_fresh false -> stale_market_data
account_state_fresh false -> stale_account_state
execution_health_ok false -> execution_health_degraded
state_consistent false -> risk_state_inconsistent
```

Validation returns only the first hard-veto reason according to spec precedence.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_risk_validation.py
```

- [ ] **Step 3: Implement minimal validation**

Use request timestamp as the sole decision clock. Do not call `datetime.now()` or wall-clock functions.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python -m pytest -q tests/test_risk_validation.py
python -m ruff check src/cocomelon/risk/validation.py tests/test_risk_validation.py
python -m mypy src
```

Commit: `feat: validate risk requests fail closed`

---

### Task 3: Add exposure, loss-lockout, and cooldown vetoes

**Files:**
- Create: `src/cocomelon/risk/vetoes.py`
- Test: `tests/test_risk_vetoes.py`

**Interfaces:**
- Consumes: `RiskRequest`.
- Produces: `hard_veto_reason(request) -> str | None` after request validation.

- [ ] **Step 1: Write RED tests**

Required exact boundaries:

```python
# same market always blocks new exposure
existing_market_exposure

# daily lockout
daily_realized_pnl <= -(day_start_equity * Decimal("0.01"))

# weekly drawdown
(rolling_7d_peak_equity - equity) / rolling_7d_peak_equity >= Decimal("0.03")

# cooldown
consecutive_losses >= 3 and request.timestamp_ms - last_closed_trade_ms < 3_600_000
```

Also prove three losses at exactly 3_600_000 ms after last close no longer veto, and missing/invalid loss timestamp while cooldown count is active fails closed.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_risk_vetoes.py
```

- [ ] **Step 3: Implement exact vetoes**

No PnL sign guessing: `daily_realized_pnl` is positive for gains, negative for losses. Same-market exposure compares canonical `MarketId` equality.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python -m pytest -q tests/test_risk_vetoes.py
python -m ruff check src/cocomelon/risk/vetoes.py tests/test_risk_vetoes.py
python -m mypy src
```

Commit: `feat: add account risk vetoes`

---

### Task 4: Add cost-aware stop-distance sizing

**Files:**
- Create: `src/cocomelon/risk/sizing.py`
- Test: `tests/test_risk_sizing.py`

**Interfaces:**
- Consumes: entry price, stop price, equity, `ExecutionCostEstimate`, `RiskLimits`.
- Produces: immutable `BaseRiskSizing` with `target_risk_amount`, `stop_distance_fraction`, `effective_loss_fraction`, `raw_notional`.

- [ ] **Step 1: Write exact arithmetic RED tests**

Example:

```python
equity = Decimal("10000")
entry = Decimal("100")
stop = Decimal("99")
costs = ExecutionCostEstimate(
    entry_slippage_fraction=Decimal("0.0005"),
    stop_slippage_fraction=Decimal("0.0010"),
    round_trip_fee_fraction=Decimal("0.0009"),
)

# target risk = 25
# stop fraction = .01
# effective loss = .0124
# raw notional = 25 / .0124
```

Prove a higher strategy score does not enter this function or alter output. Reject invalid/negative costs and zero effective loss.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_risk_sizing.py
```

- [ ] **Step 3: Implement pure Decimal sizing**

Do not quantize internally except where deterministic IDs serialize values. Preserve Decimal precision.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python -m pytest -q tests/test_risk_sizing.py
python -m ruff check src/cocomelon/risk/sizing.py tests/test_risk_sizing.py
python -m mypy src
```

Commit: `feat: add cost-aware risk sizing`

---

### Task 5: Add aggregate and correlation risk capacity

**Files:**
- Create: `src/cocomelon/risk/capacity.py`
- Test: `tests/test_risk_capacity.py`

**Interfaces:**
- Consumes: `RiskRequest`, target risk amount.
- Produces: `RiskCapacity` with remaining aggregate risk, remaining bucket risk, approved risk amount, and binding cap names.

- [ ] **Step 1: Write RED tests**

Cover:

```text
existing planned risk 0.50% equity leaves 0.25% aggregate capacity
existing planned risk 0.75% equity exhausts aggregate capacity
existing same-bucket risk 0.25% equity leaves 0.25% bucket capacity
existing same-bucket risk 0.50% equity exhausts bucket capacity
opposite directions do not net risk
other bucket does not consume target bucket capacity but still consumes aggregate risk
approved risk = min(target, aggregate remaining, bucket remaining)
```

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_risk_capacity.py
```

- [ ] **Step 3: Implement capacity calculation**

Sum only finite non-negative `planned_risk`. Contract validation should make malformed records impossible; capacity still asserts invariants fail closed.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python -m pytest -q tests/test_risk_capacity.py
python -m ruff check src/cocomelon/risk/capacity.py tests/test_risk_capacity.py
python -m mypy src
```

Commit: `feat: cap aggregate and correlated risk`

---

### Task 6: Add leverage, margin, liquidity, and liquidation caps

**Files:**
- Create: `src/cocomelon/risk/market_caps.py`
- Test: `tests/test_risk_market_caps.py`

**Interfaces:**
- Consumes: `RiskRequest`, approved risk amount, effective loss fraction, raw notional.
- Produces: `MarketRiskCaps` with final candidate notional, planned risk, binding caps, and optional rejection reason.

- [ ] **Step 1: Write RED capacity tests**

Exact formulas:

```text
leverage ceiling = equity * min(3, venue_max_leverage)
gross capacity = leverage ceiling - gross_open_notional
margin capacity = available_margin * 0.50 * min(3, venue_max_leverage)
liquidity capacity = min(entry_depth_25bps, exit_depth_25bps) * 0.10
risk notional = approved_risk_amount / effective_loss_fraction
final notional = min(raw_notional, risk notional, gross capacity, margin capacity, liquidity capacity)
```

Prove each independent cap can bind and is recorded deterministically.

- [ ] **Step 2: Write liquidation and venue-minimum RED tests**

LONG requires liquidation below stop and `(entry-liquidation)/(entry-stop) >= 2`. SHORT mirrors this. Missing/invalid liquidation rejects. If final notional is below `venue_min_notional`, reject without upsizing.

- [ ] **Step 3: Verify RED**

```bash
python -m pytest -q tests/test_risk_market_caps.py
```

- [ ] **Step 4: Implement caps**

Return explicit rejection reasons when gross, margin, or liquidity capacity is non-positive. Otherwise allow smaller safe notional and record the binding cap.

- [ ] **Step 5: Verify GREEN and commit**

```bash
python -m pytest -q tests/test_risk_market_caps.py
python -m ruff check src/cocomelon/risk/market_caps.py tests/test_risk_market_caps.py
python -m mypy src
```

Commit: `feat: enforce market and liquidation risk caps`

---

### Task 7: Build the authoritative risk engine pipeline

**Files:**
- Create: `src/cocomelon/risk/engine.py`
- Test: `tests/test_risk_engine.py`

**Interfaces:**
- Consumes: `RiskRequest`.
- Produces: `evaluate_risk(request: RiskRequest) -> RiskDecision`.

- [ ] **Step 1: Write integration RED tests**

Cover one exact safe approval plus every rule stage:

```text
validation veto -> zero exposure
same-market veto -> zero exposure
daily/weekly/cooldown veto -> zero exposure
aggregate exhausted -> zero exposure
bucket exhausted -> zero exposure
gross/margin/liquidity exhausted -> zero exposure
liquidation failure -> zero exposure
venue minimum -> zero exposure
safe request -> approved bounded notional
```

Also prove deterministic repeated evaluation and that changing only Phase 5 score from 65 to 100 leaves approved exposure unchanged when all other inputs are identical.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_risk_engine.py
```

- [ ] **Step 3: Implement fixed pipeline**

Implementation order must exactly match the spec. Use helper constructors for rejected decisions so every rejection has zero exposure and preserves strategy decision ID / market / direction / stop / timestamp.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python -m pytest -q tests/test_risk_engine.py
python -m ruff check src/cocomelon/risk/engine.py tests/test_risk_engine.py
python -m mypy src
```

Commit: `feat: add authoritative risk decision engine`

---

### Task 8: Add correlation-bucket policy and limits adapter

**Files:**
- Create: `src/cocomelon/risk/policy.py`
- Test: `tests/test_risk_policy.py`

**Interfaces:**
- Produces: `default_correlation_bucket(market: MarketId) -> str`; `limits_from_settings(settings: Settings) -> RiskLimits`.

- [ ] **Step 1: Write RED tests**

Require native and HIP-3 crypto markets to default to `crypto_beta` unless an explicit future override is passed through a separate mapping function. Prove all Settings risk defaults convert exactly to `RiskLimits` Decimal values without float round-trip.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/test_risk_policy.py
```

- [ ] **Step 3: Implement policy**

Keep V1 mapping deliberately conservative and simple. Do not invent sector diversification without evidence.

- [ ] **Step 4: Verify GREEN and commit**

```bash
python -m pytest -q tests/test_risk_policy.py
python -m ruff check src/cocomelon/risk/policy.py tests/test_risk_policy.py
python -m mypy src
```

Commit: `feat: add conservative risk policy defaults`

---

### Task 9: Add architectural boundary and property-style invariant tests

**Files:**
- Create: `tests/test_risk_boundaries.py`
- Create: `tests/test_risk_invariants.py`

**Interfaces:**
- Verifies Phase 6 public boundary only; no new runtime API required.

- [ ] **Step 1: Add boundary tests**

Inspect public risk dataclass fields and `src/cocomelon/risk/*.py` source/imports to prove:

```text
no exchange/order placement imports
no wallet/signing/account API imports
no ML dependencies
no fill simulator imports
no transfer/withdrawal concepts
no averaging-down/add-position public method
no martingale/loss-recovery sizing inputs
RiskDecision approved notional cannot exceed any computed cap in integration fixtures
rejected decisions always have zero approved risk and notional
```

- [ ] **Step 2: Add deterministic matrix/invariant tests**

Use a grid of Decimal entries/stops/equities/costs and assert:

```text
approved_risk_amount <= equity * 0.0025
sum existing planned risk + approved risk <= equity * 0.0075
same-bucket risk + approved risk <= equity * 0.005
approved_notional <= visible weak-side depth * 0.10
raising costs never increases approved notional
reducing available margin never increases approved notional
reducing visible depth never increases approved notional
raising strategy score alone never increases approved risk/notional
```

Use deterministic loops, not a new property-testing dependency.

- [ ] **Step 3: Run focused boundary suite**

```bash
python -m pytest -q tests/test_risk_boundaries.py tests/test_risk_invariants.py
python -m ruff check src tests/test_risk_boundaries.py tests/test_risk_invariants.py
python -m mypy src
```

- [ ] **Step 4: Commit**

Commit: `test: enforce independent risk boundaries`

---

### Task 10: Documentation, full verification, and guarded merge

**Files:**
- Modify: `docs/DECISIONS.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHATGPT_PROJECT_SOURCE.md`
- Modify: PR #8 body/state only after verification.

**Interfaces:**
- Produces a verified Phase 6 feature tree ready for guarded merge.

- [ ] **Step 1: Record new Phase 6 decisions**

Add one concise decision entry locking the conservative V1 additions: 0.50% bucket cap, 3x gross ceiling, 50% margin utilization, 10% weak-side 25-bps depth utilization, 2x liquidation/stop buffer, 60-minute three-loss cooldown, and `crypto_beta` default bucket. State explicitly that later relaxation requires evidence and cannot be driven by strategy score.

- [ ] **Step 2: Run focused Phase 6 tests**

```bash
python -m pytest -q \
  tests/test_risk_contracts.py \
  tests/test_risk_validation.py \
  tests/test_risk_vetoes.py \
  tests/test_risk_sizing.py \
  tests/test_risk_capacity.py \
  tests/test_risk_market_caps.py \
  tests/test_risk_engine.py \
  tests/test_risk_policy.py \
  tests/test_risk_boundaries.py \
  tests/test_risk_invariants.py
```

- [ ] **Step 3: Run full repository verification**

```bash
python -m compileall -q src tests scripts
python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q
```

All must pass on Python 3.12 in GitHub Actions.

- [ ] **Step 4: Audit Phase 6 exit criteria line by line**

Explicitly verify:

```text
risk independent from strategy score
0.25% cost-aware sizing
0.75% aggregate cap
1% daily lockout
3% rolling weekly drawdown lockout
three-loss / 60-minute cooldown
0.50% correlation bucket cap
3x gross ceiling
50% available-margin utilization ceiling
10% weak-side 25-bps visible-depth cap
2x liquidation/stop safety buffer
same-market add-on impossible
no martingale/loss-recovery sizing
stale/inconsistent/unhealthy state fails closed
rejected decision always zero exposure
risk code cannot send orders or access wallet/account APIs
no ML/live execution
```

- [ ] **Step 5: Update continuity docs with exact CI evidence**

Record branch head, CI run/job, Python version, compile/Ruff/mypy/pytest results, architecture summary, new locked risk defaults, and exact next Phase 7 objective.

- [ ] **Step 6: Merge only with expected-head protection**

Mark PR ready only after final CI is green. Re-read head/mergeability, then merge with the exact verified head SHA. Verify `main` points to the merge commit and the Phase 6 feature branch has no unmerged runtime diff.

- [ ] **Step 7: Docs-only closeout if needed**

If pre-merge continuity metadata necessarily says merge pending, create/merge a docs-only closeout branch recording the actual Phase 6 merge SHA and making Phase 7 active.
