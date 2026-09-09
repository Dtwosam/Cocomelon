# Cocomelon Project Status

**Last updated:** 2026-09-09  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Current verified main merge:** `d3540593d7a9`  
**Latest verified main CI:** run `34351785499` — success  
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

Latest trusted Evidence Dashboard snapshot, refreshed 2026-09-09 11:12 UTC:

- **30 accepted V4 cohorts**;
- **47 / 100 closed paper trades**;
- **10 / 30 closed-trade days**;
- **3,155 strategy decisions**;
- raw Phase 9 minimums not met;
- economic edge not measured yet;
- live orders disabled.

Current protected scheduled V4 acquisition:

- workflow run `34351227954`;
- `acquire-evidence` is in progress;
- `Record thesis-expiry genuine public mainnet evidence` is in progress;
- observer run `34351237156` is attached and waiting for acquisition completion.

This run must finish naturally. Do not manually dispatch, retry, extend, cancel, or performance-condition it.

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

A frozen challenger can begin untouched validation only after the documented embargo and clean-validation requirements.

## Implemented authoritative V4 synchronization

The authoritative V4 interval/completeness synchronization path is implemented in `.github/workflows/research-v4-registry-sync.yml`. Research finalization/recovery consumes this trusted authority and fails closed when V4 coverage is incomplete or overlap cannot be ruled out.

## Current research state

Latest trusted Research Dashboard snapshot, refreshed 2026-09-09 12:28 UTC:

- candidate: `scheduled-research-root`;
- state: `researching`;
- **3 authenticated checkpoints**;
- **2 closed research trades**;
- **1 closed-trade day**;
- **2 consecutive no-trade checkpoints**;
- cumulative research net PnL: `5.166551389249999999999999978`;
- cumulative mean R: `0.1033388059238969248401543126`;
- posterior threshold not yet available because minimum research trade count is not met.

These economics are touched research only. They are not verified edge and cannot support live promotion.

The most recent scheduled research run `34349940827` failed closed in `prepare-control` because a successful research cohort already existed for the current UTC day. Exit code `77` is the intended duplicate-success guard. No retry is warranted.

## Reliability work merged on 2026-09-09

Recent mainline work hardened research observability without changing strategy, frozen V4 economics, or promotion semantics:

- PR #160 adds research Actions throughput summaries;
- PR #161 validates and persists verified throughput attestations;
- PR #162 renders durable research throughput history;
- PR #163 adds research attempt audit history to the dashboard;
- PR #164 records research workflow failure stages.

Current main head is `d3540593d7a9` and main CI run `34351785499` passed.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Let V4 run `34351227954` finish naturally.
3. Verify observer run `34351237156` remains attached during acquisition and only wakes the existing safe-gap path after the acquisition completes.
4. Do not rerun research run `34349940827`; its duplicate-success guard is correct.
5. On the next eligible research cohort, verify the newly merged throughput, attempt-audit, and failure-stage diagnostics are published from authenticated state without changing checkpoint economics.
6. Continue admitting only clean, complete, flat frozen-runtime V4 evidence through the frozen curator.
7. Let the frozen V4 one-shot evaluate only when its immutable finalization criteria are met; do not inspect or infer interim V4 economics.
8. Advance toward Phase 10 only if the authoritative untouched one-shot eventually reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Hard prohibitions

- Do not use Hyperliquid testnet.
- Do not enable live wallet/order/transfer/withdrawal behavior in the evidence or research lanes.
- Do not manually retry or extend V4 because of an acquisition/economic outcome.
- Do not import V4 economics/history into research.
- Do not weaken provenance, overlap, gap, replay-completeness, flat-exposure, attestation, authentication, one-shot, or daily research-cap gates to accumulate trades faster.
- Do not use nominal cron timing as a substitute for actual V4 run/job/session interval authority.

**LIVE TRADING: DISABLED.**
