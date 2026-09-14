# Cocomelon Project Status

**Last updated:** 2026-09-14  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified implementation baseline:** `4772df1660eeb85cb771d3086d3b1665e06fe4ba`  
**Latest verified baseline CI:** run `34861704259` — success  
**Live trading:** **DISABLED**  
**Real baseline edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

## Current production state

The authoritative promotion lane remains frozen **V4 thesis-expiry genuine-mainnet evidence**. The system continues to use public Hyperliquid mainnet observations with paper/shadow execution only.

Frozen V4 contract remains unchanged:

- 45-minute entry window (`2700` seconds);
- exact 4-hour maximum position age (`14400` seconds);
- fixed 5h15m total capture (`18900` seconds);
- nominal schedule `37 1,7,13,19 * * *` UTC;
- one acquisition attempt per cohort;
- schedule-triggered economic acquisition only;
- no outcome-conditioned retry, extension, cancellation, manual dispatch, or backfill;
- final admission only for clean transport, complete replay/dataset evidence, no gaps, and flat replay exposure;
- live orders disabled.

Phase 10 and any live promotion remain blocked until the frozen untouched evidence lane reaches its immutable criteria. No current verified result demonstrates repeatable economic edge.

## Active V4 evidence progress

Latest trusted Evidence Dashboard snapshot, refreshed **2026-09-14 14:54 UTC**:

- **47 accepted V4 cohorts**;
- **80 / 100 closed paper trades**;
- **15 / 30 closed-trade days**;
- **4,940 strategy decisions**;
- raw Phase 9 minimums not met;
- economic edge not measured yet;
- live orders disabled.

The **30 closed-trade-day requirement remains the dominant raw calendar gate**. Additional same-day cohorts cannot substitute for missing unique closed-trade days.

Latest accepted protected V4 state:

- latest accepted source run: `34816026778`;
- latest successful V4 curator: `34847022204`;
- latest V4 corpus artifact ID: `10349141260`;
- latest V4 mainnet attestation begins `ec98d5ae0d653954…`;
- V4 one-shot state: **waiting for finalizable snapshot**.

Protected V4 workflow run `34855303556` (run #64) started naturally at **2026-09-14 14:23:33 UTC** and is currently in the fixed 5h15m recording stage. The acquisition job has a 330-minute timeout. Let it finish under the frozen scheduler/concurrency controls; do not manually retry, extend, cancel, dispatch, or backfill it.

Nominal scheduler timing is observational only. Actual run/job/session intervals remain authoritative and nominal cron drift is never a backfill signal.

## Research lane: D-023

Research remains permanently **TOUCHED / NON-PROMOTIONAL** and exists to reject weak ideas faster without contaminating frozen promotion evidence.

Locked rule: **candidates may fail fast; candidates may not succeed fast**.

Research may not:

- inspect or reconstruct hidden V4 economics;
- overlap actual V4 acquisition intervals;
- turn `RESEARCH_PROMISING` into direct promotion;
- mutate `v4-mainnet-corpus`;
- advance Phase 10;
- enable live orders.

Research futility requires at least 20 closed research trades. `RESEARCH_PROMISING` requires at least 40 closed research trades, at least 7 distinct closed-trade UTC days, `P(mu > 0) >= 0.80`, no integrity/contamination/hard-risk issues, and complete costs. Even then, the candidate still requires a frozen specification, inherited touched-period handling, the documented embargo, and future untouched validation before any promotion path can be considered.

## Current research state

Latest trusted Research Dashboard snapshot, refreshed **2026-09-14 14:24 UTC**:

### `scheduled-research-root`

- state: `researching`;
- **5 authenticated checkpoints**;
- **4 closed research trades**;
- **2 long / 2 short**;
- **3 closed-trade days**;
- no-trade streak: **0**;
- cumulative touched research net PnL: `5.401591955399999999999999590`;
- cumulative touched research mean R: `0.0540198086234484624200771524`;
- posterior threshold unavailable because the minimum research trade count has not been met.

### `research-r1-exit-15m-v1`

- state: `draft`;
- **0 authenticated checkpoints**;
- no authenticated challenger trades yet.

These economics are touched research only. They are not verified edge and cannot support live promotion.

Research run `34851584868` was **NOT COUNTED**. It reached the repaired shared-capture provenance path but the capture-control overlap watcher correctly failed closed when protected V4 acquisition run #64 became active during the 30-minute research capture. That rejection is evidence-integrity behavior, not a research checkpoint.

The one-success-per-UTC-day research guard remains locked. Do not weaken the daily research-cap, overlap, provenance, or completeness gates to accumulate trades faster.

## Single-capture root + challenger rollout

The bounded root+challenger architecture is implemented on `main`:

- PR #183 introduced one authenticated research capture shared by the required root and at most one registered challenger;
- PR #185 registered the fixed `research-r1-exit-15m-v1` challenger as a child of `scheduled-research-root`;
- PR #187 added the read-only root+challenger rollout verifier;
- PR #188 hardened artifact identity, capture digest, and authoritative V4-disjointness verification;
- PR #193 fixed candidate materialization so replay/evidence runtime provenance stays bound to the authenticated shared capture revision while candidate strategy revision remains independently authenticated;
- PR #195 removed the campaign's redundant direct cron so new research captures launch only through the safe-gap dispatcher using actual V4 acquisition state.

The root remains the immutable 20-minute bounded paper replay. The challenger changes only max position age to 15 minutes. Both remain paper-only and **TOUCHED / NON-PROMOTIONAL**.

The research campaign itself is now `workflow_dispatch`-only. `.github/workflows/research-daily-gap-dispatcher.yml` owns natural launch timing, runs a periodic safe-gap check, and also wakes on completion of the protected V4 campaign. Capture-time overlap watching remains the final fail-closed authority.

A natural post-#195 root+challenger cohort has **not yet produced an authenticated checkpoint**. The current protected V4 #64 acquisition correctly blocks research until an actual safe gap exists. Do not manually dispatch a research cohort merely to prove the rollout.

## Reliability state

Recent verified reliability changes include:

- PR #189 removed a bounded-recorder CI timing flake without changing production recorder behavior;
- PR #191 upgraded checkout/setup-python workflow actions to v7 and regression-locked against deprecated runtime majors;
- PR #193 repaired shared-capture replay revision provenance without changing the generic mainnet or V4 validators;
- PR #194 upgraded artifact upload/download actions to Node 24 majors and passed the Phase 9 heartbeat smoke;
- PR #195 eliminated the delayed direct-research-cron race while preserving all overlap, daily-cap, V4, promotion, and live guards.

Verified `main` CI for the #195 merge is run `34861704259`: compile, Ruff, mypy, full pytest, and research smoke all succeeded.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Let protected V4 run `34855303556` finish naturally; do not manually retry, extend, cancel, dispatch, or backfill V4.
3. Continue admitting only clean, complete, flat frozen-runtime V4 evidence through the frozen curator and keep interim V4 economics opaque.
4. On the next naturally eligible research safe gap, let the dispatcher launch the campaign without manual intervention.
5. Require the rollout verifier to prove exactly one authenticated public-mainnet capture is reused by `scheduled-research-root` and `research-r1-exit-15m-v1`, with exact candidate code/config identity and recording/source digests.
6. Require the root result to remain mandatory and challenger failure to remain nonfatal to an otherwise valid root checkpoint.
7. Count only authenticated successful research checkpoints; failed, contaminated, running, and evaluating attempts remain **NOT COUNTED**.
8. Apply only the precommitted D-023 futility/promising rules. Do not infer edge from the current four-trade research sample.
9. Let the frozen V4 one-shot evaluate only when immutable finalization criteria are met; do not inspect or infer interim V4 economics.
10. Advance toward Phase 10 only if the authoritative untouched one-shot eventually reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Hard prohibitions

- Do not use Hyperliquid testnet.
- Do not enable live wallet/order/transfer/withdrawal behavior in the evidence or research lanes.
- Do not manually retry, extend, cancel, dispatch, or backfill V4 based on outcome.
- Do not import V4 economics/history into research.
- Do not weaken provenance, overlap, gap, replay-completeness, flat-exposure, attestation, authentication, one-shot, or daily research-cap gates to accumulate trades faster.
- Do not use nominal cron timing as a substitute for actual V4 run/job/session interval authority.

**LIVE TRADING: DISABLED.**
