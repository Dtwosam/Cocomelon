# Cocomelon Project Status

**Last updated:** 2026-09-11  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Current verified main code merge:** `eaabc164f6d4`  
**Latest verified main CI:** run `34598196411` — success  
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
- no outcome-conditioned retry, extension, cancellation, or forced admission;
- final admission only for clean transport, complete replay/dataset evidence, no gaps, and flat replay exposure;
- live orders disabled.

Phase 10 and any live promotion remain blocked until the frozen untouched evidence lane reaches its immutable promotion criteria. No current verified result demonstrates repeatable economic edge.

## Active V4 evidence progress

Latest trusted Evidence Dashboard snapshot, refreshed 2026-09-11 12:12 UTC:

- **36 accepted V4 cohorts**;
- **58 / 100 closed paper trades**;
- **12 / 30 closed-trade days**;
- **3,785 strategy decisions**;
- raw Phase 9 minimums not met;
- economic edge not measured yet;
- live orders disabled.

The **30 closed-trade-day requirement is currently the dominant calendar gate**. Additional same-day cohorts cannot substitute for missing unique closed-trade days.

Latest completed protected V4 cohort:

- workflow run `34570685217` completed successfully;
- `acquire-evidence` completed successfully after the fixed natural capture;
- offline `verify-evidence` completed successfully;
- attached acquisition-end observer run `34570691858` completed successfully;
- authority synchronization completed successfully;
- curator run `34597000426` accepted source run `34570685217` into the V4 corpus;
- accepted-corpus progress advanced from **35 / 56 / 11 / 3,680** to **36 cohorts / 58 trades / 12 days / 3,785 decisions**;
- latest V4 corpus artifact ID is `10263210137`;
- latest V4 mainnet attestation begins `8ca8efcff38f283d…`.

V4 one-shot state remains **waiting for finalizable snapshot**. No interim V4 economics have been used for research or promotion decisions.

At this verified handoff there are no in-progress `main`-branch workflows. The next scheduled V4 acquisition must still start and finish naturally; do not manually dispatch, retry, extend, cancel, or backfill it.

## Pipeline diagnostics

- Latest Campaign V4: **success** — run `34570685217`.
- Latest V4 curator: **success** — run `34597000426`.
- Latest V4 source intake: **accepted into V4 corpus** — source run `34570685217`.
- Scheduler health currently reports **drift** because the latest scheduled run preceded the nominal 07:37 UTC slot.
- Scheduler drift is observational only. It does not authorize manual backfill, retry, extension, or cancellation.
- Actual run/job/session intervals remain authoritative; nominal cron timing is never used as a substitute for interval authority.

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

Research futility requires at least 20 research trades. `RESEARCH_PROMISING` requires at least 40 trades, at least 7 UTC days, and `P(mu > 0) >= 0.80`; even then, the candidate still requires untouched validation after the documented embargo before any promotion path can be considered.

## Current research state

Latest trusted Research Dashboard snapshot, refreshed 2026-09-11 12:10 UTC:

- candidate: `scheduled-research-root`;
- state: `researching`;
- **5 authenticated checkpoints**;
- **4 closed research trades**;
- **2 long / 2 short**;
- **3 closed-trade days**;
- no-trade streak: **0**;
- cumulative touched research net PnL: `5.401591955399999999999999590`;
- cumulative touched research mean R: `0.0540198086234484624200771524`;
- posterior threshold unavailable because the minimum research trade count has not been met.

These economics are touched research only. They are not verified edge and cannot support live promotion.

The one-success-per-UTC-day research guard remains locked. Do not weaken the daily research-cap gate to accumulate trades faster.

## Candidate execution provenance

PR #181 (`eaabc164f6d4`) closes a research provenance gap that previously prevented honest execution challengers.

The bounded research replay now:

- reconstructs the active candidate's immutable registered `execution_config_json`;
- requires the reconstructed replay config digest to equal the candidate manifest `config_digest`;
- requires a positive bounded exit horizon that fits inside the fixed 30-minute research capture;
- fails closed when an active candidate identity lacks the authoritative restored registry or has malformed/conflicting execution metadata;
- preserves the existing `scheduled-research-root` 20-minute paper expiry as the default when no candidate identity is active;
- binds replay eligibility to the exact frozen candidate config rather than silently comparing every candidate to the root constant.

This change does **not** create, promote, or activate a challenger. It provides the provenance foundation required for safe parallel challenger evaluation on already-authorized research data.

## Implemented authoritative V4 synchronization

The authoritative V4 interval/completeness synchronization path is implemented in `.github/workflows/research-v4-registry-sync.yml`. Research finalization/recovery consumes this trusted authority and fails closed when V4 coverage is incomplete or overlap cannot be ruled out.

## Recent reliability and throughput work

Recent mainline work relevant to the current handoff includes:

- PR #176 refreshed verified status after a successful V4 cohort;
- PR #177 prevents redundant safe-gap wakeups when a protected successor V4 acquisition is present;
- PR #178 deduplicates observer bootstrap attachment when a workflow-run observer is already active;
- PR #179 makes V4 intake diagnostics ignore cancelled/incomplete curator artifacts that lack a valid intake report and extends curator time for offline aggregation;
- PR #180 keeps downloaded V4 transport archives in scratch space so durable intake diagnostics remain lightweight without changing admission semantics;
- PR #181 binds research replay economics to the immutable registered candidate execution config and regression-locks that provenance relationship.

None of these changes alter frozen V4 economics, promotion thresholds, the daily research cap, or live-trading controls.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Continue admitting only clean, complete, flat frozen-runtime V4 evidence through the frozen curator.
3. Let every scheduled V4 acquisition start and finish naturally; do not manually retry, extend, cancel, or backfill a cohort.
4. Observe the implemented authoritative V4 interval/completeness synchronization path before any subsequent research economics are admitted.
5. On the next eligible research cohort, verify the merged candidate-execution binding reconstructs the root candidate's exact registered 20-minute paper replay identity from authoritative state.
6. Build research speed through **safe research data and parallel challenger work**, not through more captures: future challenger fan-out must reuse an already-authorized research recording and must not weaken the one-success-per-UTC-day acquisition gate.
7. Keep each challenger immutable and lineage-aware. A challenger may accumulate touched evidence independently, but no touched result can directly advance Phase 10 or mutate V4 evidence.
8. Let the frozen V4 one-shot evaluate only when immutable finalization criteria are met; do not inspect or infer interim V4 economics.
9. Advance toward Phase 10 only if the authoritative untouched one-shot eventually reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Hard prohibitions

- Do not use Hyperliquid testnet.
- Do not enable live wallet/order/transfer/withdrawal behavior in the evidence or research lanes.
- Do not manually retry or extend V4 because of an acquisition/economic outcome.
- Do not import V4 economics/history into research.
- Do not weaken provenance, overlap, gap, replay-completeness, flat-exposure, attestation, authentication, one-shot, or daily research-cap gates to accumulate trades faster.
- Do not use nominal cron timing as a substitute for actual V4 run/job/session interval authority.

**LIVE TRADING: DISABLED.**
