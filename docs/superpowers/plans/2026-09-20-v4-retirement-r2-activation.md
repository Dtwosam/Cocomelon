# V4 Retirement and R2 Activation Implementation Plan

**Date:** 2026-09-20  
**Spec:** `docs/superpowers/specs/2026-09-20-v4-retirement-r2-activation-design.md`

## Global constraints

- Hyperliquid mainnet data only.
- Paper/shadow execution only; live remains disabled.
- Keep 0.25% per-trade planned risk and every existing hard risk invariant unchanged.
- Do not cancel or alter an already-running V4 acquisition.
- Do not manually dispatch research economic acquisition for validation.
- R2's revealed-V4 tuning window must be permanently represented in touched lineage.
- All candidate/authority failures fail closed.

## Task 1 — Lock the new decision and regression contract

Files:
- `docs/DECISIONS.md`
- `docs/research-r2-short-trend-quality-v1.json`
- `tests/test_research_candidate_registration.py`
- `tests/test_research_single_capture_fanout_workflow.py`
- `tests/test_research_fanout_rollout_verifier.py`
- `tests/test_scheduled_evidence_campaign_v4.py`
- `tests/test_evidence_dashboard_v4.py`

Write tests first for:
- V4 development-history import into R2 touched lineage.
- fail-closed incomplete V4 authority.
- exact-repeat candidate registration idempotence and immutable mismatch rejection.
- R2 spec identity, code revision, 20-minute horizon, and cutoff.
- campaign fanout and both verifier gates targeting R2.
- rollout verifier CLI accepting an authorized R2 challenger ID.
- absence of future V4 cron acquisition.
- retired scheduler-health state when the workflow has no schedule.

Run focused tests and confirm RED for missing behavior.

## Task 2 — Implement provenance-safe R2 registration

Files:
- `src/cocomelon/research/registry.py`
- `src/cocomelon/research/registration.py`
- `docs/research-r2-short-trend-quality-v1.json`

Implement:
- authoritative V4 development-history copy through a declared cutoff;
- exact immutable-match idempotence for repeat registration;
- optional `v4_touched_through_ms` parsing/validation;
- R2 immutable spec.

Run focused registration/registry tests to GREEN.

## Task 3 — Activate R2 in the research control plane

Files:
- `.github/workflows/research-candidate-register.yml`
- `.github/workflows/research-campaign-scheduled.yml`
- `src/cocomelon/research/rollout_verifier.py`
- affected workflow/verifier tests.

Implement:
- narrow main push trigger for R2 registration;
- trusted registration-run acceptance for push/main or explicit workflow_dispatch, retaining exact head-SHA validation;
- source-controlled R2 challenger ID;
- R2 target-pair checks;
- verifier CLI `--challenger-candidate-id` used at both authority gates.

Run focused workflow/verifier tests to GREEN.

## Task 4 — Retire future V4 acquisition cleanly

Files:
- `.github/workflows/evidence-campaign-v4-scheduled.yml`
- `scripts/apply_v4_scheduler_health.py`
- V4 workflow/dashboard tests.

Remove the cron schedule while retaining the manual path's refusal to create economic evidence. Add scheduler-health detection for a schedule-less retired workflow so the dashboard reports retirement, not stale delivery.

Run focused V4 tests to GREEN.

## Task 5 — Reconcile source of truth and verify branch

Files:
- `docs/STATUS.md`
- `docs/CHATGPT_PROJECT_SOURCE.md`
- old rollout plan status if needed.

Record:
- V4 is touched/retired, not untouched promotion evidence;
- latest historical counts are informational only;
- #205 R2 seam and this activation transition;
- R1/root touched research economics;
- R2 forward research is the active economic path;
- Phase 10/live remain blocked.

Run:
- `python -m compileall -q src tests scripts`
- `python -m ruff check src tests scripts`
- `python -m mypy src`
- `python -m pytest -q`
- research replay smoke tests.

Open a PR only after branch CI is green. Require independent PR-context CI and a whole-diff review before exact-head squash merge.

## Task 6 — Production verification

After merge:
- verify post-main CI;
- verify the automatic R2 registration workflow succeeds and publishes authoritative registry;
- verify research dashboard can see R2 after registry publication;
- verify no new scheduled V4 economic run is created from the retired workflow;
- do not manually dispatch a research cohort;
- wait for the safe-gap dispatcher to launch the next natural root+R2 cohort, then require both rollout verifier gates before counting it.
