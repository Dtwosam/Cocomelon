# Phase 7 Paper Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic paper execution and position management against real recorded Hyperliquid mainnet observations while preserving the Phase 6 risk approval as a hard ceiling.

**Architecture:** Replace Phase 1 float execution placeholders with immutable Decimal contracts, then add pure order-planning, L2 IOC simulation, position/accounting, funding, and exit kernels. Persist only operational lifecycle state in SQLite, referencing recorded Phase 3 market evidence. Keep all live exchange action, wallet, signing, transfer, and withdrawal capability absent.

**Tech Stack:** Python 3.12, dataclasses, `decimal.Decimal`, SQLite, pytest, Ruff, mypy, existing Hyperliquid normalized market/event contracts.

**Spec:** `docs/superpowers/specs/2026-08-23-phase-7-paper-execution-design.md`

## Global Constraints

- Hyperliquid testnet is forbidden.
- Runtime observations are Hyperliquid mainnet only.
- Phase 7 is paper-only; no live action endpoint, wallet, private key, signing, transfer, withdrawal, or private account API.
- New exposure requires `RiskDecision.approved=True` and may fill less than but never more than `approved_notional`.
- Entries/exits use marketable IOC semantics; unsupported passive maker fills are forbidden.
- Authoritative financial arithmetic uses fixed-context `Decimal`; quantity/cap rounding is downward where upward rounding could breach risk.
- Initial deterministic latency is 250 ms.
- Initial max eligible L2 age is 1,000 ms.
- Initial IOC slippage guard is 25 bps from execution reference price.
- Initial versioned native-perp taker-fee assumption is `Decimal("0.00045")`.
- Initial versioned native-perp minimum notional assumption is `Decimal("10")`.
- Initial execution support is native validator-operated Hyperliquid perps only (`MarketId.dex == ""`); unsupported namespaces fail closed.

---

### Task 1: Decimal execution contracts and deterministic IDs

**Files:**
- Modify: `src/cocomelon/domain/execution.py`
- Create: `tests/test_execution_contracts.py`

**Interfaces:**
- Produces: `PaperExecutionConfig`, `InstrumentExecutionSpec`, `PaperOrderPlan`, `ExecutionAttempt`, `PaperFill`, `PaperPosition`, `PaperAccountState`, `PositionAction` and lifecycle enums.
- Produces: deterministic ID properties using canonical payloads and fixed Decimal validation helpers.

- [ ] **Step 1: Write failing contract tests**

Cover immutable Decimal storage, finite/positive validation, deterministic IDs, versioned defaults, native-perp support state, reduce-only/action enum validity, and hostile ambient Decimal context independence.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `pytest tests/test_execution_contracts.py -q`
Expected: FAIL because the new Phase 7 contracts do not yet exist.

- [ ] **Step 3: Implement minimal Decimal contracts**

Replace float placeholders only as required by the tests. Preserve legacy names only where compatibility is genuinely needed; do not keep float fields authoritative.

- [ ] **Step 4: Run focused + nearest regression checks**

Run: `pytest tests/test_execution_contracts.py tests/test_risk_contracts.py tests/test_risk_boundaries.py -q`
Expected: PASS.

- [ ] **Step 5: Run compile/Ruff/mypy for changed slice and commit**

Run: `python -m compileall -q src tests && ruff check src tests && mypy src`
Commit: `feat: add Phase 7 execution contracts`

### Task 2: Risk-approved order planning and size precision

**Files:**
- Create: `src/cocomelon/execution/planner.py`
- Create: `src/cocomelon/execution/__init__.py`
- Create: `tests/test_execution_planner.py`

**Interfaces:**
- Consumes: `RiskDecision`, `PaperExecutionConfig`, `InstrumentExecutionSpec`.
- Produces: `plan_opening_order(risk_decision, instrument, config, reference_price, created_at_ms) -> PaperOrderPlan | PlanningRejection`.

- [ ] **Step 1: Write failing tests**

Prove LONG->BUY, SHORT->SELL, rejected/NO_TRADE decisions fail closed, HIP-3/non-native execution is rejected, raw quantity is rounded down to `10^-sz_decimals`, rounded reference notional never exceeds `approved_notional`, zero/below-min-notional results reject without upsizing, and hostile Decimal context cannot increase quantity.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `pytest tests/test_execution_planner.py -q`
Expected: FAIL because planner module/API is missing.

- [ ] **Step 3: Implement minimal pure planner**

Use a local fixed 28-digit Decimal context and `ROUND_DOWN` for risk-ceiling quantity conversion. No network/state access.

- [ ] **Step 4: Run focused + risk regressions**

Run: `pytest tests/test_execution_planner.py tests/test_execution_contracts.py tests/test_risk_contracts.py tests/test_risk_boundaries.py -q`
Expected: PASS.

- [ ] **Step 5: Static checks and commit**

Commit: `feat: plan risk-bounded paper orders`

### Task 3: L2-aware marketable IOC simulator

**Files:**
- Create: `src/cocomelon/execution/ioc.py`
- Create: `tests/test_paper_ioc.py`

**Interfaces:**
- Consumes: `PaperOrderPlan`, normalized same-market L2 evidence, `PaperExecutionConfig`.
- Produces: `simulate_ioc(...) -> ExecutionAttempt` plus immutable `PaperFill` rows.

- [ ] **Step 1: Write failing IOC tests**

Prove BUY walks asks ascending; SELL walks bids descending; each visible level is capped; no synthetic hidden depth; 25-bps boundary prevents worse fills; insufficient depth yields PARTIAL; empty/out-of-bound depth yields NO_FILL; stale/crossed/malformed/mismatched evidence rejects; execution waits until `created_at_ms + latency_ms`; actual fill quantity never exceeds plan quantity.

- [ ] **Step 2: Confirm RED**

Run: `pytest tests/test_paper_ioc.py -q`

- [ ] **Step 3: Implement pure deterministic book walk**

Use only evidence available in the selected recorded L2 snapshot. IOC remainder is cancelled. No maker fill path exists.

- [ ] **Step 4: Run focused suite + static checks and commit**

Commit: `feat: simulate visible-book IOC fills`

### Task 4: Fees, positions, reduce-only accounting, and account equity

**Files:**
- Create: `src/cocomelon/execution/accounting.py`
- Create: `tests/test_paper_accounting.py`

**Interfaces:**
- Consumes: prior `PaperAccountState`, fills, position state, mark price.
- Produces: immutable next account/position state.

- [ ] **Step 1: Write failing accounting tests**

Prove fee=`fill_notional*taker_fee_rate`; LONG and SHORT weighted entries; partial entry quantity only; correct LONG/SHORT realized PnL sign; partial exits preserve remainder; reduce-only cannot flip; fees hit cash/equity; unrealized PnL marks correctly; equity=`cash+unrealized`; replay of same events yields same IDs.

- [ ] **Step 2: Confirm RED**

Run: `pytest tests/test_paper_accounting.py -q`

- [ ] **Step 3: Implement pure state transitions**

No add-on exposure helper is exposed. Opening state is created only from an opening fill tied to an approved plan.

- [ ] **Step 4: Run focused + nearest regressions and commit**

Commit: `feat: account for paper fills and positions`

### Task 5: Funding and mark-to-market lifecycle

**Files:**
- Create: `src/cocomelon/execution/funding.py`
- Create: `tests/test_paper_funding.py`

**Interfaces:**
- Produces: immutable `FundingAccrual` and `apply_funding(...)` transition.

- [ ] **Step 1: Write failing tests**

Cover long/short signed funding cash flow, actual timestamped evidence only, no future lookahead, gap/no-evidence behavior, fee/funding separation, net equity reconciliation.

- [ ] **Step 2: Confirm RED**

Run: `pytest tests/test_paper_funding.py -q`

- [ ] **Step 3: Implement event-driven funding accounting and commit**

Commit: `feat: account for paper funding`

### Task 6: Position manager and risk-reducing exits

**Files:**
- Create: `src/cocomelon/execution/manager.py`
- Create: `tests/test_position_manager.py`

**Interfaces:**
- Produces: deterministic `PositionAction` decisions and reduce-only exit plans.

- [ ] **Step 1: Write failing tests**

Cover hard-stop trigger from mark price, emergency exit on execution/data-health failure, thesis exit, bounded reduction, stop tightening only in risk-reducing direction, HOLD, and impossible widening/removing stop.

- [ ] **Step 2: Confirm RED**

Run: `pytest tests/test_position_manager.py -q`

- [ ] **Step 3: Implement minimal deterministic manager and commit**

Commit: `feat: manage paper position exits`

### Task 7: SQLite lifecycle persistence and restart reconciliation

**Files:**
- Create: `src/cocomelon/execution/store.py`
- Create: `tests/test_execution_store.py`

**Interfaces:**
- Persists immutable plan/attempt/fill/funding/position/account transitions with deterministic unique IDs.
- Reconstructs current state by deterministic ordered replay.

- [ ] **Step 1: Write failing persistence tests**

Prove atomic fill+position+account transaction, duplicate event idempotency, crash/restart replay equivalence, no duplicate positions, same event stream -> same state ID, rollback on injected failure.

- [ ] **Step 2: Confirm RED**

Run: `pytest tests/test_execution_store.py -q`

- [ ] **Step 3: Implement SQLite schema/store and commit**

Commit: `feat: persist paper execution lifecycle`

### Task 8: End-to-end paper runtime integration

**Files:**
- Modify/create the smallest existing runtime orchestration files required after inspecting current collector/scanner/strategy/risk boundaries.
- Create: `tests/test_phase7_paper_pipeline.py`

**Interfaces:**
- Scanner -> Phase 5 strategy -> Phase 6 risk -> Phase 7 planner -> recorded L2 IOC -> account/position -> reduce-only exit.

- [ ] **Step 1: Write failing deterministic pipeline test**

Use recorded/fixture mainnet observations only. Assert unattended LONG and SHORT paths, NO_TRADE/rejected-risk no-exposure paths, partial-fill path, stop exit path, and no duplicate state after replay.

- [ ] **Step 2: Confirm RED**

Run: `pytest tests/test_phase7_paper_pipeline.py -q`

- [ ] **Step 3: Wire minimal orchestration without adding live exchange capability**

- [ ] **Step 4: Run focused pipeline and full test suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 5: Static/security boundary audit**

Run compile/Ruff/mypy and source scans proving the paper execution package does not import wallet/signing/exchange-action/transfer/withdrawal capability.

- [ ] **Step 6: Commit**

Commit: `feat: integrate Phase 7 paper execution pipeline`

### Task 9: Phase 7 closeout and status evidence

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/DECISIONS.md` only if implementation creates a real new architectural decision.

- [ ] **Step 1: Run complete CI-equivalent verification on Python 3.12**

Run editable install, compileall, Ruff, mypy, and full pytest.

- [ ] **Step 2: Audit exit criteria**

Explicitly verify scanner -> decision -> risk -> paper order -> fill -> position -> exit, accounting reconciliation, no unsupported maker fills, and failure-injection duplicate-position protection.

- [ ] **Step 3: Update STATUS with exact test/CI/commit evidence**

Do not mark Phase 7 complete until all criteria pass.

- [ ] **Step 4: Final branch diff/review and commit**

Commit: `docs: close out Phase 7 paper execution`
