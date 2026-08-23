# Phase 7 Paper Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic paper execution and position management against real recorded Hyperliquid mainnet observations while preserving the Phase 6 risk approval as a hard ceiling.

**Architecture:** Replace Phase 1 float execution placeholders with immutable Decimal contracts, normalize public execution-critical market context, then add pure order-planning, L2 IOC simulation, accounting, funding, position-management, and persistence kernels. SQLite holds only operational lifecycle state and references recorded Phase 3 market evidence. Live exchange action, wallet, signing, transfer, withdrawal, private-account APIs, and ML remain absent.

**Tech Stack:** Python 3.12, standard-library dataclasses/`decimal`/`sqlite3`, pytest, Ruff, mypy, existing Hyperliquid normalized market/event contracts.

**Spec:** `docs/superpowers/specs/2026-08-23-phase-7-paper-execution-design.md`

## Global Constraints

- Hyperliquid testnet is forbidden.
- Runtime observations are Hyperliquid mainnet only.
- Phase 7 is paper-only; no live action endpoint, wallet, private key, signing, transfer, withdrawal, or private account API.
- New exposure requires `RiskDecision.approved=True` and may fill less than but never more than `approved_notional` or `approved_risk_amount`.
- Entries/exits use marketable IOC semantics; unsupported passive maker fills are forbidden.
- Financial arithmetic uses a fixed 28-digit Decimal context; quantity/cap conversion rounds down where upward rounding could breach risk.
- Initial latency is 250 ms; max L2 age 1,000 ms; max public asset-context age 5,000 ms; funding reconciliation grace 300,000 ms.
- Initial IOC slippage guard is 25 bps.
- Initial versioned native-perp taker-fee assumption is `Decimal("0.00045")`.
- Initial versioned native-perp minimum notional is `Decimal("10")`.
- Initial execution support is native validator-operated Hyperliquid perps only (`MarketId.dex == ""`); unsupported namespaces fail closed.
- `activeAssetCtx` is public market data only; do not add user-address subscriptions or private account reads.
- Funding uses actual public funding-history records paired with lookahead-safe pre-boundary oracle context; missing evidence is surfaced, never interpolated.

## Current checkpoint

- Task 1 initial Decimal execution contracts: GREEN in CI.
- Task 2 initial risk-bounded order planner: GREEN in CI run `32664932215`, job `97256756783`, head `9a58b51c665980cd62ae65cbe1090b946d46c539`.
- The final approved spec was tightened after the first plan draft. Task 2A below is mandatory reconciliation before IOC work.

---

### Task 1: Decimal execution contracts and deterministic IDs — COMPLETE

**Files:**
- Modify: `src/cocomelon/domain/execution.py`
- Test: `tests/test_execution_contracts.py`

**Interfaces:**
- Produces lifecycle enums and immutable execution-domain contracts with deterministic IDs.

- [x] RED contract tests.
- [x] Minimal Decimal implementation.
- [x] Focused/static/full CI GREEN.

### Task 2: Risk-approved opening-order planner — COMPLETE

**Files:**
- Create: `src/cocomelon/execution/__init__.py`
- Create: `src/cocomelon/execution/planner.py`
- Test: `tests/test_execution_planner.py`

**Interface:**

```python
plan_opening_order(
    risk_decision: RiskDecision,
    instrument: InstrumentExecutionSpec,
    config: PaperExecutionConfig,
    reference_price: Decimal,
    created_at_ms: int,
) -> PaperOrderPlan | PlanningRejection
```

- [x] RED tests for direction mapping, namespace rejection, lot rounding, minimum notional, latency, notional ceiling, and hostile Decimal context.
- [x] Minimal pure planner.
- [x] Full CI GREEN at the checkpoint above.

### Task 2A: Reconcile contracts/planner with the final approved spec

**Files:**
- Modify: `src/cocomelon/domain/execution.py`
- Modify: `src/cocomelon/execution/planner.py`
- Modify: `tests/test_execution_contracts.py`
- Modify: `tests/test_execution_planner.py`

**Interfaces:**
- `PaperExecutionConfig` additionally exposes `max_asset_ctx_age_ms=5_000` and `funding_reconciliation_grace_ms=300_000`.
- Opening `PaperOrderPlan` additionally preserves Phase 6 `stop_distance_fraction`, `effective_loss_fraction`, and `approved_risk_amount_ceiling`.
- `PaperOrderPlan.cost_buffer_fraction` returns `effective_loss_fraction - stop_distance_fraction` and must be finite/non-negative.

- [ ] **Step 1: Write RED tests**

Add tests that require the two new config defaults, require an opening plan to preserve the exact Phase 6 stop/effective-loss fractions and risk ceiling, reject `effective_loss_fraction < stop_distance_fraction`, and prove `cost_buffer_fraction` is identical under hostile ambient Decimal context.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_execution_contracts.py tests/test_execution_planner.py -q`
Expected: FAIL because these final-spec fields are absent.

- [ ] **Step 3: Implement minimal reconciliation**

Carry values directly from `RiskDecision`; do not recompute or loosen them in the planner. Include them in deterministic plan ID payloads.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_execution_contracts.py tests/test_execution_planner.py tests/test_risk_contracts.py tests/test_risk_engine.py -q`
Then run compileall, Ruff, mypy, and full pytest.

- [ ] **Step 5: Commit**

Commit: `fix: align paper plan with risk envelope spec`

### Task 3: Normalize public `activeAssetCtx` execution context

**Files:**
- Modify: `src/cocomelon/domain/stream.py`
- Modify: `src/cocomelon/hyperliquid/ws_protocol.py`
- Modify subscription builder/supervisor file that currently validates public subscriptions.
- Test: `tests/test_ws_protocol.py`
- Test the subscription manager file already covering public subscription validation.

**Interfaces:**
- Add `StreamKind.ACTIVE_ASSET_CTX`.
- Accept public subscription `{"type": "activeAssetCtx", "coin": <wire-name>}`.
- Normalize payload keys exactly to `mark_px`, `mid_px`, `oracle_px`, `funding`, `open_interest` using `Decimal`; preserve `exchange_time_ms=None` when upstream provides no timestamp.

- [ ] **Step 1: Write RED tests**

Use a fixture shaped like current official `activeAssetCtx`: market coin plus perp context fields. Assert native/HIP-3 canonical market parsing, Decimal normalization, receive-time preservation, deterministic event key, and no invented exchange timestamp. Assert user/private subscriptions remain rejected.

- [ ] **Step 2: Verify RED**

Run focused WebSocket protocol/subscription tests.

- [ ] **Step 3: Implement minimal public-only normalization/subscription support**

Do not add user address, wallet, order updates, fills, or account subscriptions.

- [ ] **Step 4: Verify GREEN + full CI and commit**

Commit: `feat: normalize public active asset context`

### Task 4: L2-aware IOC simulator with Phase 6 envelope preservation

**Files:**
- Create: `src/cocomelon/execution/ioc.py`
- Test: `tests/test_paper_ioc.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class IocSimulation:
    attempt: ExecutionAttempt
    fills: tuple[PaperFill, ...]

simulate_ioc(
    plan: PaperOrderPlan,
    l2_event: StreamEvent,
    instrument: InstrumentExecutionSpec,
    config: PaperExecutionConfig,
) -> IocSimulation
```

- [ ] **Step 1: Write RED tests using actual Phase 3 normalized L2 shapes**

Cover BUY asks ascending, SELL bids descending, input-order invariance, latency cutoff, same-market check, crossed/invalid/future/stale book rejection, 25-bps guard, FULL/PARTIAL/NO_FILL, no hidden-depth extrapolation, taker fee per recorded level fill, and IOC remainder cancellation.

Also prove cumulative fill notional never exceeds `approved_notional_ceiling` and cumulative planned loss never exceeds `approved_risk_amount_ceiling`, using:

```text
actual_stop_fraction = abs(avg_fill - stop) / avg_fill
actual_effective_fraction = actual_stop_fraction + plan.cost_buffer_fraction
planned_loss = cumulative_fill_notional * actual_effective_fraction
```

If the next level would breach either envelope, clip the final level to the largest safe lot-rounded quantity; never upsize.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_paper_ioc.py -q`.

- [ ] **Step 3: Implement pure deterministic simulator**

No wall clock, network calls, random latency, maker fills, trade-tape inference, or candle fallback.

- [ ] **Step 4: Verify GREEN + full CI and commit**

Commit: `feat: simulate risk-bounded visible-book IOC fills`

### Task 5: Position/accounting state, rolling peak, and Phase 6 adapter

**Files:**
- Extend: `src/cocomelon/domain/execution.py`
- Create: `src/cocomelon/execution/accounting.py`
- Test: `tests/test_paper_accounting.py`

**Interfaces:**
- Finalize immutable `PaperPosition`, `PaperAccountState`, and rolling-peak candidate contract.
- Pure transitions for opening, reduce-only reduction/close, mark-to-market, and account recomputation.
- Produce `risk_state_from_paper(...) -> tuple[RiskAccountState, tuple[OpenPositionRisk, ...]]`.

- [ ] **Step 1: Write RED tests**

Require weighted-average partial entry, LONG/SHORT realized PnL, entry/exit fee debit, reduce-only no-flip invariant, current stop never absent, unrealized mark PnL, `equity=cash+unrealized`, gross notional, conservative reserved margin, available margin, same-day net realized cash PnL, closed-trade loss-streak increment/reset, and partial reductions not changing the streak.

Add exact rolling-seven-day monotonic-queue tests: tail eviction on higher equity, head expiry after seven days, restart-serializable candidates, and current head equals the true maximum in the retained window.

- [ ] **Step 2: Verify RED**

Run focused accounting tests.

- [ ] **Step 3: Implement minimal pure transitions/adapters**

No method may add to an existing position. Opening a same-market position when one exists raises/rejects.

- [ ] **Step 4: Verify GREEN + risk integration regressions and commit**

Commit: `feat: account for paper positions and risk state`

### Task 6: Funding reconciliation from actual public evidence

**Files:**
- Extend domain execution contracts with immutable `FundingAccrual`/gap record.
- Create: `src/cocomelon/execution/funding.py`
- Test: `tests/test_paper_funding.py`

**Interfaces:**

```python
funding_cash_delta(signed_quantity, oracle_price, funding_rate) -> Decimal
reconcile_funding_boundary(position, boundary_ms, oracle_ctx, funding_record, now_ms, config)
```

- [ ] **Step 1: Write RED tests**

Cover positive/negative funding for long/short, position-open-across-boundary requirement, exact market/time match, oracle observation received at/before boundary, deterministic idempotent event ID, unresolved grace period, gap becoming account-inconsistent after 300,000 ms, and no interpolation from candles/current rates.

- [ ] **Step 2: Verify RED**

Run focused tests.

- [ ] **Step 3: Implement using public funding-history `FundingRate` plus normalized pre-boundary `ACTIVE_ASSET_CTX` oracle evidence**

- [ ] **Step 4: Verify GREEN + full CI and commit**

Commit: `feat: reconcile paper funding from public evidence`

### Task 7: Deterministic position manager and reduce-only exit planning

**Files:**
- Create: `src/cocomelon/execution/manager.py`
- Extend: `src/cocomelon/execution/planner.py`
- Test: `tests/test_position_manager.py`

**Interfaces:**

```python
evaluate_position(...) -> PositionAction
plan_reduce_only_order(position, action, instrument, config, reference_price, created_at_ms)
    -> PaperOrderPlan | PlanningRejection
```

- [ ] **Step 1: Write RED tests**

Lock precedence: emergency health exit > mark stop > opposite fresh strategy thesis > tighter same-direction invalidation > explicit validated reduction > HOLD. `NO_TRADE` alone must HOLD. LONG stop only ratchets upward; SHORT only downward. All reduction/exit plans are `reduce_only=True`, round quantity down, cannot exceed/flip the current position, and use the same latency/IOC path.

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement minimal manager/reduce-only planner**

- [ ] **Step 4: Verify GREEN + full CI and commit**

Commit: `feat: manage paper positions and exits`

### Task 8: SQLite operational store and restart reconciliation

**Files:**
- Create: `src/cocomelon/execution/store.py`
- Test: `tests/test_execution_store.py`

**Interfaces:**
- `PaperExecutionStore(path)` creates/migrates only Phase 7 operational tables.
- Atomic methods persist plan, attempt+fills+position+account, funding event+account, stop/action events.
- `load_and_reconcile()` reconstructs/validates materialized state and returns fail-closed health.

- [ ] **Step 1: Write RED tests**

Require tables `paper_meta`, `paper_order_plans`, `paper_execution_attempts`, `paper_fills`, `paper_positions`, `paper_position_events`, `paper_funding_events`, `paper_account_state`, and rolling-peak candidates. Test transaction rollback on injected failure, deterministic uniqueness/idempotency, duplicate L2/funding application, restart equality, materialized-state mismatch failure, and one active position per market.

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement stdlib `sqlite3` store with explicit transactions**

Never persist a successful in-memory fill if its durable transaction rolled back.

- [ ] **Step 4: Verify GREEN + full CI and commit**

Commit: `feat: persist and recover paper execution state`

### Task 9: Narrow paper adapter and unattended Phase 7 pipeline

**Files:**
- Create: `src/cocomelon/execution/interface.py`
- Create: `src/cocomelon/execution/paper.py`
- Create/modify the smallest orchestration module needed to compose existing scanner/strategy/risk boundaries.
- Test: `tests/test_phase7_paper_pipeline.py`

**Interfaces:**
- Narrow protocol contains paper/live-compatible trading semantics only: submit IOC plan, consume eligible observation, request reduce-only close/reduction, read execution health/current paper state.
- `PaperExecutionAdapter` composes planner, IOC, accounting, funding, manager, and store; it does not call a real exchange.

- [ ] **Step 1: Write RED end-to-end tests**

Use deterministic recorded/fixture mainnet evidence for LONG and SHORT: Phase 5 directional decision -> Phase 6 approval -> plan -> post-latency L2 -> partial/full paper position -> mark/thesis/stop manager -> reduce-only IOC close -> reconciled account. Also cover NO_TRADE, risk reject, NO_FILL, restart replay, and duplicate observation not creating duplicate exposure.

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement smallest orchestration**

Open positions are managed/reconciled before new scanner entries. Failures block new exposure but do not block safe exit attempts when usable market data exists.

- [ ] **Step 4: Verify GREEN + full CI and commit**

Commit: `feat: integrate unattended paper execution lifecycle`

### Task 10: Boundary audit, closeout, guarded merge

**Files:**
- Create/extend: `tests/test_execution_boundaries.py`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHATGPT_PROJECT_SOURCE.md`
- Modify: `docs/DECISIONS.md` only if implementation introduces a genuine new locked decision.

- [ ] **Step 1: Add/verify boundary tests**

Assert execution source contains no private key, signing, real order submission, withdraw/transfer, private user/account API, testnet path, ML dependency, candle-to-L2 fill fabrication, or passive-maker fill path. Assert paper/live abstraction exposes no generic exchange-client escape hatch.

- [ ] **Step 2: Run complete verification**

Editable install, `python -m compileall -q src tests scripts`, Ruff, mypy, full pytest under Python 3.12.

- [ ] **Step 3: Audit every Phase 7 exit criterion line by line**

Do not mark complete if accounting, restart/recovery, risk-envelope, IOC evidence, or end-to-end lifecycle criteria are missing.

- [ ] **Step 4: Update continuity docs with exact head/CI evidence**

- [ ] **Step 5: Inspect PR threads/diff, mark ready, and merge with expected-head SHA protection**

- [ ] **Step 6: Verify `main`, reconcile docs-only merge metadata if necessary, and activate Phase 8**

Live trading remains disabled.
