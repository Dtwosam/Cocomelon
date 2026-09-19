# Natural Research Rollout Validation Plan

**Status:** complete  
**Created:** 2026-09-14  
**Updated:** 2026-09-19  
**Supersedes for active execution:** `2026-09-11-research-single-capture-fanout.md`  
**Scope:** rollout verification only; no strategy, risk, promotion, V4, or live-order rule changes.

## Goal

Validate the completed single-capture root+challenger implementation on naturally eligible research cohorts, without manually creating evidence and without weakening any V4-isolation, daily-cap, provenance, replay-completeness, or promotion guard.

The first natural post-#195 cohort succeeded and passed a retrospective read-only rollout-contract audit, but the old finalizer skipped the independent verifier. PR #197 repaired that enforcement defect. This plan remains active until a naturally eligible **post-#197** cohort executes both verifier gates in-workflow before authoritative checkpoint publication is accepted as rollout-complete.

## Current verified state

- Verified implementation baseline: `cfe993ded68d19d0f4491c05d7d49ac20416722f`.
- Post-merge `main` CI run `34896797631` passed compile, Ruff, mypy, full pytest, and research smoke.
- Research campaign is `workflow_dispatch`-only; safe-gap dispatch owns new launch timing.
- Capture-time V4 overlap protection remains fail-closed and authoritative.
- Protected V4 run `34855303556` completed successfully and was accepted into the V4 corpus.
- Trusted V4 snapshot: **48 accepted cohorts, 83/100 closed trades, 15/30 closed-trade UTC days, 5,045 decisions**.
- Trusted research snapshot: root **6 authenticated checkpoints / 4 trades / 3 days**; challenger **1 authenticated checkpoint / 0 trades / 0 days**.
- Natural campaign `34888205962` succeeded for both candidates and is COUNTED. Its shared capture interval was `[1789415850415, 1789417655787]` ms.
- Refreshed V4 authority covered through `1789417692055` ms and found no overlap with that shared capture.
- A read-only retrospective execution of the fixed-pair rollout-verifier contract passed for `34888205962`.
- The old finalizer nevertheless skipped the verifier in-workflow because successful evaluation did not restore the fan-out plan into finalizer state.
- PR #197 repaired that defect by moving fixed-pair verification before authoritative publication and restoring final-audit fan-out provenance.

## Locked constraints

- No Hyperliquid testnet.
- Mainnet observations only; paper/shadow execution only.
- No manual research dispatch merely to prove rollout behavior.
- No manual V4 retry, extension, cancellation, dispatch, or backfill.
- Actual V4 intervals are authority; nominal cron timing is observational only.
- Preserve the implemented daily research success cap and one recorder invocation per campaign cohort; do not create throughput-driven retries.
- Research must remain disjoint from every actual protected V4 acquisition interval while V4 is blind.
- Root remains required; challenger failure remains auditable and nonfatal to an otherwise valid root checkpoint.
- Failed, contaminated, running, and evaluating attempts are NOT COUNTED.
- Research remains TOUCHED / NON-PROMOTIONAL and may not advance Phase 10 or enable live orders.
- Do not inspect, infer, or import interim V4 economics.

## Task 1: Let the protected V4 window resolve naturally

- [x] Observe run `34855303556` to terminal state without intervention.
- [x] Confirm its actual acquisition interval remains authoritative for research overlap decisions.
- [x] Confirm the normal curator/authority-sync path processed terminal V4 state without manual backfill.

Result: V4 #64 completed successfully, was admitted by curator run `34890051900`, and advanced the trusted corpus to 48 accepted cohorts / 83 trades / 15 closed-trade UTC days.

## Task 2: Verify natural safe-gap launch

On the first naturally eligible post-V4 safe gap:

- [x] Confirm the research campaign event is bot-driven `workflow_dispatch`, not a direct campaign `schedule` event or manual user dispatch.
- [x] Confirm campaign preflight found no active protected V4 acquisition before allowing capture.
- [x] Confirm one-success-per-UTC-day protection remained enforced.
- [x] Confirm no manual retry, extension, cancellation, or backfill created the cohort.
- [ ] Preserve exact parent-dispatch attribution if needed for audit completeness; the adjacent dispatcher run `34888201670` found campaign `34888205962` already active and correctly refused a duplicate dispatch.

Safety result: the campaign was already under bot control, actual V4-active preflight passed, and duplicate dispatch was refused. Exact parent dispatcher attribution is not required to count economics, but remains useful provenance if later tooling exposes it directly.

## Task 3: Verify one authenticated capture fans out correctly

For natural campaign `34888205962`:

- [x] Confirm exactly one authenticated public-mainnet capture source was reused by the fixed pair.
- [x] Confirm root `scheduled-research-root` and challenger `research-r1-exit-15m-v1` share the exact source ID and capture interval.
- [x] Confirm both bind to the same recording-session and source-set digests.
- [x] Confirm replay/evidence runtime provenance uses the authenticated shared capture revision.
- [x] Confirm candidate strategy identity remains independently bound to each immutable candidate code revision and config digest.
- [x] Confirm root uses the immutable 20-minute max-position-age configuration.
- [x] Confirm challenger uses the immutable 15-minute max-position-age configuration.
- [x] Confirm candidate execution remained paper-only, isolated, complete, gap-free, and flat.

The old recorder/canonical `code_revision` mismatch did not recur. No generic mainnet or V4 validator was weakened.

## Task 4: Verify finalization and checkpoint accounting

- [x] Confirm authoritative V4 coverage was synchronized through the shared research interval after capture.
- [x] Confirm the required root attempt succeeded.
- [x] Confirm the challenger attempt succeeded with full authenticated candidate artifact and exact capture/candidate identity match.
- [x] Confirm only authenticated successful checkpoints changed dashboard accounting; both zero-trade checkpoints were counted and prior failed attempts remained NOT COUNTED.
- [x] Confirm no research artifact entered V4, Phase 10, a verified-edge claim, or live-order state.
- [x] Re-run the rollout-verifier contract read-only against archived `34888205962` artifacts and confirm V4 disjointness/completeness, candidate identities/horizons, exact attempts, and decision provenance all pass.
- [x] Confirm a naturally eligible **post-#197** cohort executes `Verify root+challenger rollout contract before authoritative publish` successfully in `evaluate-research`.
- [x] Confirm the same post-#197 cohort executes the independent final rollout verifier successfully before final publication completes.

Natural campaign `35420465214` satisfied both remaining checks: the pre-publication verifier succeeded inside `evaluate-research`, the independent final verifier succeeded, candidate jobs completed under the shared authenticated capture, and dashboard publication completed without manual evidence creation or guard weakening. The rollout-enforcement objective is therefore complete.

## Task 5: Repair only demonstrated rollout defects

The first natural success exposed one concrete enforcement defect: finalization skipped the verifier, and authoritative evaluation state could be published before verifier enforcement.

- [x] Reproduce the exact failing/skipped stage from trusted artifacts/logs.
- [x] Identify root cause before changing workflow behavior.
- [x] Add a focused regression test that failed for the demonstrated defect.
- [x] Make the smallest fix preserving every locked guard.
- [x] Run compile, Ruff, mypy, full pytest, and research smoke.
- [x] Require green PR-context CI and merge the exact reviewed head.
- [x] Require green post-merge `main` CI.

Evidence:

- RED CI `34895660285` failed only the new pre-publication verifier-order contract;
- GREEN branch CI `34896531120` passed;
- PR-context CI `34896661359` passed;
- PR #197 merged as `cfe993ded68d19d0f4491c05d7d49ac20416722f`;
- post-merge `main` CI `34896797631` passed.

## Task 6: Handoff to profitability research

- [x] Close rollout validation after natural production proof.
- [x] Hand subsequent challenger economics and candidate iteration to the next active profitability-research plan.
- [x] Preserve D-023 touched/non-promotional gates, futility thresholds, promising thresholds, lineage, and future clean-validation requirements.

Further accumulation is no longer part of this rollout-verification plan.

## Completion condition

This rollout plan is complete only when a naturally eligible **post-#197** fixed-pair cohort has:

1. passed the pre-publication rollout verifier inside `evaluate-research`;
2. passed the independent final rollout verifier;
3. produced correctly authenticated dashboard accounting without guard weakening or manual evidence creation.

Completion of this plan does **not** establish verified edge, satisfy V4 promotion criteria, advance Phase 10, or authorize live trading.
