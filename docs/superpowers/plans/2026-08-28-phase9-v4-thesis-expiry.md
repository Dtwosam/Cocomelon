# Phase 9 V4 Thesis-Expiry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a distinct V4 paper candidate with a precommitted four-hour thesis-expiry exit so every eligible entry has a finite economic lifecycle inside a fixed evidence capture window.

**Architecture:** Add an optional max-position-age rule to the existing paper position manager with a backward-compatible `None` default, then add V4-specific replay configuration identities that opt into a four-hour expiry. Merge the core runtime first; production V4 acquisition/curation/Phase-9 activation is a separate pinning change that references the exact merged runtime SHA.

**Tech Stack:** Python 3.12, dataclasses/Decimal, pytest, Ruff, mypy, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-28-phase9-v4-thesis-expiry-design.md`

## Global Constraints

- Hyperliquid mainnet evidence only; testnet forbidden.
- Paper execution only; live orders remain disabled.
- V2/V3 behavior and persisted identities must remain unchanged.
- V4 max position age is exactly `14_400_000` ms (4 hours).
- V4 entry window is exactly `2700` seconds and capture window is exactly `18_900` seconds.
- V4 execution config version is `phase7-v2-4h-thesis-expiry`.
- V4 replay engine version is `phase8-v3-thesis-expiry`.
- V4 replay config version is `phase9-baseline-replay-v3-thesis-expiry`.
- Exit priority is health, stop, opposite fresh thesis, thesis expiry, stop tightening, explicit reduction, hold.
- Expiry uses `EXIT_THESIS` / `MAX_HOLD_EXPIRED` and must use normal reduce-only latency/IOC/depth/slippage/fee mechanics.
- No PnL or performance metric may influence acquisition/admission/capture length.
- Locked Phase 9 economic thresholds do not change.

---

### Task 1: Lock backward-compatible position-age semantics

**Files:**
- Modify: `src/cocomelon/domain/execution.py`
- Modify: `src/cocomelon/execution/manager.py`
- Test: `tests/test_position_manager.py`
- Test: `tests/test_domain.py`

**Interfaces:**
- Consumes: `PaperExecutionConfig`, `PaperPosition`, existing `evaluate_position(...)`.
- Produces: optional `PaperExecutionConfig.max_position_age_ms: int | None` and `MAX_HOLD_EXPIRED` exit behavior.

- [ ] **Step 1: Write failing tests**

Add tests requiring:

```python
def test_position_age_limit_defaults_to_disabled() -> None:
    assert PaperExecutionConfig().max_position_age_ms is None


def test_position_age_limit_must_be_positive_when_set() -> None:
    with pytest.raises(ValueError, match="max_position_age_ms"):
        PaperExecutionConfig(max_position_age_ms=0)


def test_expired_position_exits_thesis_after_four_hours() -> None:
    config = PaperExecutionConfig(max_position_age_ms=14_400_000)
    action = evaluate_position(
        position_with_opened_at_ms(1_000),
        mark_event=fresh_non_stop_mark(),
        strategy_decision=None,
        strategy_fresh=False,
        critical_health=False,
        explicit_reduction_quantity=None,
        config=config,
        timestamp_ms=14_401_000,
    )
    assert action.action_type is PositionActionType.EXIT_THESIS
    assert action.reason_codes == ("MAX_HOLD_EXPIRED",)


def test_stop_has_priority_over_position_age_expiry() -> None:
    ...


def test_fresh_opposite_thesis_has_priority_over_position_age_expiry() -> None:
    ...
```

Use the existing position/mark/decision test helpers in `tests/test_position_manager.py`; do not invent a second fixture system.

- [ ] **Step 2: Run RED**

Run full CI. Expected: only new position-age tests fail because the config field and expiry branch do not exist.

- [ ] **Step 3: Implement minimal config field and manager branch**

In `PaperExecutionConfig` add:

```python
max_position_age_ms: int | None = None
```

Validate `<= 0` as invalid when non-`None`.

In `evaluate_position`, after fresh-opposite-thesis handling and before same-direction stop tightening, add:

```python
if (
    config.max_position_age_ms is not None
    and timestamp_ms - position.opened_at_ms >= config.max_position_age_ms
):
    return PositionAction(
        action_type=PositionActionType.EXIT_THESIS,
        market=position.market,
        quantity=position.quantity,
        new_stop_price=None,
        reason_codes=("MAX_HOLD_EXPIRED",),
        timestamp_ms=timestamp_ms,
    )
```

- [ ] **Step 4: Run GREEN verification**

Run compile, Ruff, mypy, full pytest, and research tests.

- [ ] **Step 5: Commit**

Commit message: `feat: add optional paper thesis expiry`.

---

### Task 2: Add immutable V4 replay configuration

**Files:**
- Modify: `src/cocomelon/evidence/cli_support.py`
- Test: `tests/test_evidence_cli.py`
- Test: `tests/test_lifecycle_replay.py` or the existing lifecycle replay test module that owns protocol configuration assertions.

**Interfaces:**
- Consumes: `BaselineReplayConfig`, `PaperExecutionConfig`, existing V2/V3 lifecycle-aware replay helpers.
- Produces: V4 constants and a V4-specific replay-config path without changing existing helper outputs.

- [ ] **Step 1: Write failing identity/config tests**

Require exact constants:

```python
THESIS_EXPIRY_MS = 14_400_000
THESIS_EXPIRY_REPLAY_ENGINE_VERSION = "phase8-v3-thesis-expiry"
THESIS_EXPIRY_CONFIG_VERSION = "phase9-baseline-replay-v3-thesis-expiry"
THESIS_EXPIRY_EXECUTION_CONFIG_VERSION = "phase7-v2-4h-thesis-expiry"
```

Require V4 replay config to contain:

```python
PaperExecutionConfig(
    config_version="phase7-v2-4h-thesis-expiry",
    max_position_age_ms=14_400_000,
)
```

while ordinary `replay_config_for_protocol(..., lifecycle_aware=False/True)` remains unchanged.

- [ ] **Step 2: Run RED**

Expected: only the new V4 config tests fail.

- [ ] **Step 3: Implement a distinct V4 helper**

Add:

```python
def thesis_expiry_replay_config(starting_cash: Decimal) -> BaselineReplayConfig:
    return BaselineReplayConfig(
        starting_cash=starting_cash,
        execution=PaperExecutionConfig(
            config_version=THESIS_EXPIRY_EXECUTION_CONFIG_VERSION,
            max_position_age_ms=THESIS_EXPIRY_MS,
        ),
        replay_engine_version=THESIS_EXPIRY_REPLAY_ENGINE_VERSION,
        config_version=THESIS_EXPIRY_CONFIG_VERSION,
    )
```

Do not overload V2/V3 booleans or mutate their constants.

- [ ] **Step 4: Add V4 freeze plumbing**

Extend `freeze_baseline_replay_payload` with a distinct keyword such as `thesis_expiry: bool = False`; reject `thesis_expiry=True` unless `lifecycle_aware=True`, and select the V4 config only in that explicit path. Persist `entry_window_ms=2_700_000` and `max_position_age_ms=14_400_000` in the returned operational payload.

- [ ] **Step 5: Verify GREEN**

Run compile, Ruff, mypy, full pytest, research tests.

- [ ] **Step 6: Commit**

Commit message: `feat: add V4 thesis-expiry replay identity`.

---

### Task 3: Prove finite lifecycle through the real paper adapter

**Files:**
- Create or modify: `tests/test_thesis_expiry_lifecycle.py`
- Modify only if required by a demonstrated defect: `src/cocomelon/execution/paper.py` or `src/cocomelon/evidence/lifecycle.py`

**Interfaces:**
- Consumes: V4 replay config, existing pending reduce-only latency behavior.
- Produces: regression proof that expiry is a real reduce-only exit and cannot bypass execution latency.

- [ ] **Step 1: Write an integration-style failing test**

Construct an open paper position whose mark never hits the stop and whose strategy does not reverse. Before 4h it must HOLD. At 4h it must create `EXIT_THESIS/MAX_HOLD_EXPIRED`; the first same-snapshot IOC may return `LATENCY_NOT_ELAPSED`; a later book update after 250ms must retry the same pending reduce-only plan and close normally if depth permits.

- [ ] **Step 2: Run RED or confirm existing implementation already satisfies the contract**

If the new test passes immediately after Tasks 1-2, keep it as coverage and make no production change. If it fails, diagnose root cause before modifying code.

- [ ] **Step 3: Verify all execution/account/journal invariants**

Assert no new exposure, correct lineage, normal taker fee/slippage rules, flat final account, and journal exit reason `MAX_HOLD_EXPIRED`.

- [ ] **Step 4: Run full GREEN verification and commit**

Commit message: `test: cover V4 thesis-expiry lifecycle` unless a production defect requires a more specific message.

---

### Task 4: Merge core runtime before activation

**Files:**
- No additional production files.

**Interfaces:**
- Produces: one immutable merged runtime SHA for all V4 acquisition/evaluation provenance.

- [ ] **Step 1:** Run compile, Ruff, mypy, full pytest, research tests on branch head.
- [ ] **Step 2:** Open PR with explicit statement that V2/V3 defaults are unchanged and V4 is not active yet.
- [ ] **Step 3:** Require exact PR CI green.
- [ ] **Step 4:** Merge and verify post-merge main CI green.
- [ ] **Step 5:** Record merged runtime SHA for activation.

---

### Task 5: Activate V4 acquisition in a separate pinning PR

**Files:**
- Create: `.github/workflows/evidence-campaign-v4-scheduled.yml`
- Create: `.github/workflows/evidence-corpus-curator-v4.yml`
- Modify: `.github/workflows/evidence-campaign-scheduled.yml` to remove scheduled V3 triggers while retaining manual audit capability.
- Add/modify tests following existing scheduled-campaign and curator workflow test patterns.

**Interfaces:**
- Consumes: exact merged runtime SHA from Task 4.
- Produces: scheduled V4 mainnet paper evidence and isolated `v4-mainnet-corpus`.

- [ ] **Step 1: RED workflow tests**

Require V4 campaign identity `v4-thesis-expiry-mainnet`, entry `2700`, capture `18900`, one attempt, paper-only mainnet, exact runtime pin, V4 replay/config/execution identities, and final flatness. Require V3 to have no `schedule:` trigger after V4 activation.

- [ ] **Step 2: Implement V4 campaign**

Use fixed schedule `37 1,7,13,19 * * *`, capture `18_900` seconds, job timeout below the hosted-runner hard ceiling, `deep-limit 5`, fixed 45-minute new-exposure cutoff, and V4 freeze/replay mode. Never retry or extend based on outcome.

- [ ] **Step 3: Implement isolated V4 curator**

Clone the provenance/admission shape of V3 but require the exact V4 protocol and write only `v4-mainnet-corpus`. V2/V3 corpus artifacts must never be imported.

- [ ] **Step 4: Verify GREEN and merge exact activation PR**

Run full CI, exact PR CI, merge, post-merge CI.

---

### Task 6: Add distinct V4 Phase 9 one-shot and dashboard handoff

**Files:**
- Add V4 evaluator wrapper/module following `mainnet_phase9_v3.py` pattern.
- Create `.github/workflows/phase9-v4-one-shot.yml`.
- Modify dashboard scripts/workflow/tests to make V4 active and V3 historical.
- Modify `docs/STATUS.md`.

**Interfaces:**
- Consumes: trusted `v4-mainnet-corpus` and exact V4 runtime/protocol.
- Produces: distinct V4 frozen snapshot/evaluation/final state with unchanged locked economic policy.

- [ ] **Step 1: RED tests for exact V4 provenance and identities**
- [ ] **Step 2: Implement V4 Phase 9 wrapper using the unchanged statistical engine**
- [ ] **Step 3: Add append-once V4 one-shot state and workflow**
- [ ] **Step 4: Update issue #82 dashboard to V4 active / V3 historical without exposing interim PnL**
- [ ] **Step 5: Update `docs/STATUS.md` with exact merged runtime/evaluator/activation SHAs**
- [ ] **Step 6: Run full CI, exact PR CI, merge, and production-verify dashboard plus first scheduled-run readiness**
