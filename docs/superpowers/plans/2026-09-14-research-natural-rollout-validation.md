# Natural Research Rollout Validation Plan

**Status:** active  
**Created:** 2026-09-14  
**Supersedes for active execution:** `2026-09-11-research-single-capture-fanout.md`  
**Scope:** rollout verification only; no strategy, risk, promotion, V4, or live-order rule changes.

## Goal

Validate the completed single-capture root+challenger implementation on the first naturally eligible post-PR-#195 research cohort, without manually creating evidence and without weakening any V4-isolation, daily-cap, provenance, replay-completeness, or promotion guard.

The 2026-09-11 fan-out implementation plan is retained as implementation history. Its architecture is now present on `main` through PRs #183, #185, #187, #188, #193, and #195. This plan owns the remaining rollout-validation work.

## Current verified state

- Verified implementation baseline: `4772df1660eeb85cb771d3086d3b1665e06fe4ba`.
- Post-merge CI run `34861704259` passed compile, Ruff, mypy, full pytest, and research smoke.
- Research campaign is `workflow_dispatch`-only; safe-gap dispatch owns new launch timing.
- Capture-time V4 overlap protection remains fail-closed and authoritative.
- Protected V4 campaign run `34855303556` began naturally at 2026-09-14 14:23:33 UTC and is currently in its fixed 5h15m acquisition stage.
- Trusted V4 progress snapshot: 47 accepted cohorts, 80/100 closed trades, 15/30 closed-trade UTC days, 4,940 decisions.
- Trusted research snapshot: root 5 authenticated checkpoints / 4 trades / 3 days; challenger 0 authenticated checkpoints.
- Research run `34851584868` is NOT COUNTED; it correctly failed closed when V4 acquisition #64 became active during capture.
- No natural post-#195 root+challenger checkpoint has yet been authenticated.

## Locked constraints

- No Hyperliquid testnet.
- Mainnet observations only; paper/shadow execution only.
- No manual research dispatch merely to prove rollout behavior.
- No manual V4 retry, extension, cancellation, dispatch, or backfill.
- Actual V4 intervals are authority; nominal cron timing is observational only.
- Exactly one research observation capture per eligible UTC day.
- Research must remain disjoint from every actual protected V4 acquisition interval while V4 is blind.
- Root remains required; challenger failure remains auditable and nonfatal to an otherwise valid root checkpoint.
- Failed, contaminated, running, and evaluating attempts are NOT COUNTED.
- Research remains TOUCHED / NON-PROMOTIONAL and may not advance Phase 10 or enable live orders.
- Do not inspect, infer, or import interim V4 economics.

## Task 1: Let the protected V4 window resolve naturally

- [ ] Observe run `34855303556` to terminal state without intervention.
- [ ] Confirm its acquisition interval remains authoritative for research overlap decisions.
- [ ] Confirm the normal curator/authority-sync path processes terminal V4 state without manual backfill.

No code change is justified merely because research is blocked while protected V4 acquisition is active.

## Task 2: Verify natural safe-gap launch

On the first naturally eligible post-V4 safe gap:

- [ ] Confirm `Research Daily Gap Dispatcher` wakes naturally through its schedule or V4-completion event.
- [ ] Confirm it finds no active protected V4 acquisition before dispatching research.
- [ ] Confirm the research campaign event is `workflow_dispatch`, not a direct campaign `schedule` event.
- [ ] Confirm one-success-per-UTC-day protection is still enforced.
- [ ] Confirm no manual dispatch, retry, extension, cancellation, or backfill created the cohort.

If no safe gap exists, NO_ACTION is correct.

## Task 3: Verify one authenticated capture fans out correctly

For the first natural root+challenger cohort:

- [ ] Confirm exactly one `record-mainnet-evidence` capture attempt.
- [ ] Confirm root `scheduled-research-root` and challenger `research-r1-exit-15m-v1` share the exact source ID and capture interval.
- [ ] Confirm both bind to the same recording-session and source-set digests.
- [ ] Confirm replay/evidence runtime provenance uses the authenticated shared capture revision.
- [ ] Confirm candidate strategy identity remains independently bound to each immutable candidate code revision and config digest.
- [ ] Confirm root uses the immutable 20-minute max-position-age configuration.
- [ ] Confirm challenger uses the immutable 15-minute max-position-age configuration.
- [ ] Confirm candidate execution remains paper-only, isolated, complete, gap-free, and flat.

The old recorder/canonical `code_revision` mismatch must not recur. Do not weaken the generic mainnet validator to make a cohort pass.

## Task 4: Verify finalization and checkpoint accounting

- [ ] Confirm authoritative V4 coverage is synchronized through the shared research interval after capture.
- [ ] Confirm `rollout_verifier` independently reasserts V4 disjointness/completeness.
- [ ] Confirm the root result is mandatory.
- [ ] If challenger succeeds, require its full authenticated candidate artifact and exact capture/candidate identity match.
- [ ] If challenger fails or is contaminated, require that state to remain auditable and nonfatal to a valid root result.
- [ ] Confirm only authenticated successful checkpoints change dashboard trade/day/economic totals.
- [ ] Confirm failed or contaminated attempts remain explicitly NOT COUNTED.
- [ ] Confirm no research artifact enters V4, Phase 10, a verified-edge claim, or live-order state.

## Task 5: Repair only demonstrated rollout defects

If a natural cohort exposes a concrete defect:

- [ ] Reproduce the exact failing stage from trusted artifacts/logs.
- [ ] Identify root cause before changing code or workflow behavior.
- [ ] Add a focused regression test that fails for the demonstrated defect.
- [ ] Make the smallest fix that preserves every locked guard.
- [ ] Run compile, Ruff, mypy, full pytest, and research smoke.
- [ ] Require green PR-context CI and merge the exact reviewed head.
- [ ] Require green post-merge `main` CI.

Do not change code merely to increase research throughput or to avoid a legitimate fail-closed rejection.

## Task 6: Continue natural research accumulation after rollout verification

After the first authenticated rollout is verified:

- [ ] Continue using naturally eligible shared captures only.
- [ ] Keep root and challenger economics independent despite shared observations.
- [ ] At 20 closed research trades, apply the precommitted futility posterior rule; reject if `P(mu > 0) < 0.05`.
- [ ] Do not label a candidate `RESEARCH_PROMISING` before at least 40 closed research trades, 7 distinct closed-trade UTC days, `P(mu > 0) >= 0.80`, complete costs, and clean integrity/risk state.
- [ ] Treat any positive research result as TOUCHED / NON-PROMOTIONAL.
- [ ] If a challenger legitimately becomes `RESEARCH_PROMISING`, freeze a new immutable challenger identity and enforce inherited touched periods plus the 6-hour embargo before future untouched validation.

## Completion condition

This rollout plan is complete when a naturally eligible post-#195 cohort has been fully authenticated through finalization and the trusted research dashboard correctly accounts for root/challenger terminal state without any guard weakening or manual evidence creation.

Completion of this plan does **not** establish verified edge, satisfy V4 promotion criteria, advance Phase 10, or authorize live trading.
