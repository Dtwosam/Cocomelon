# Cocomelon Project Status

**Last updated:** 2026-09-11  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Current verified main code merge:** `6fc270665f86`
**Latest verified main CI:** run `34654206493` — success
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

Latest trusted Evidence Dashboard snapshot, refreshed 2026-09-11 18:30 UTC:

- **37 accepted V4 cohorts**;
- **60 / 100 closed paper trades**;
- **12 / 30 closed-trade days**;
- **3,890 strategy decisions**;
- raw Phase 9 minimums not met;
- economic edge not measured yet;
- live orders disabled.

The **30 closed-trade-day requirement is currently the dominant calendar gate**. Additional same-day cohorts cannot substitute for missing unique closed-trade days.

Latest completed and accepted protected V4 cohort:

- workflow run `34598433641` completed successfully on its original schedule;
- no manual retry, extension, cancellation, dispatch, or backfill was used;
- curator run `34630832992` accepted source run `34598433641` into the V4 corpus;
- accepted-corpus progress is now **37 cohorts / 60 trades / 12 days / 3,890 decisions**;
- latest V4 corpus artifact ID is `10275789596`;
- latest V4 mainnet attestation begins `d82a8e9d6e5fc758…`.

V4 one-shot state remains **waiting for finalizable snapshot**. No interim V4 economics have been used for research or promotion decisions.

Protected V4 workflow run `34626237790` started naturally at 2026-09-11 17:11 UTC and remains in progress. The next naturally scheduled V4 run `34651521838` is pending behind it. Let the scheduler/concurrency controls resolve both naturally; do not manually retry, extend, cancel, dispatch, or backfill either run. Interim economics remain opaque.

## Pipeline diagnostics

- Latest scheduled Campaign V4: **pending** — run `34651521838`.
- Active Campaign V4: **in progress** — run `34626237790`.
- Latest completed accepted V4 source: **success** — run `34598433641`.
- Latest V4 curator: **success** — run `34630832992`.
- Latest V4 source intake: **accepted into V4 corpus** — source run `34598433641`.
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

## Single-capture research fan-out

PR #183 (`5f8c2dbb4109`) implements the bounded research fan-out path on `main`.

The scheduled research workflow now:

- resolves the required root candidate plus at most one optional registered challenger from authoritative state;
- performs exactly one authenticated public-mainnet capture for the research run;
- writes a candidate-neutral `capture-source.json` and binds that same source interval to every fan-out attempt;
- builds and runs candidate strategy decisions in isolated candidate-keyed jobs without registry or GitHub credentials and with Docker network access disabled;
- materializes each candidate replay from the same authenticated recording using that candidate's immutable execution configuration and code revision;
- serializes authoritative economics/registry updates under the publisher lock;
- treats root failure as fatal while terminalizing optional challenger failure independently;
- preserves the V4-disjointness/completeness checks and the one-success-per-UTC-day research capture gate.

No challenger is implicitly registered or activated by this merge. `RESEARCH_CHALLENGER_CANDIDATE_ID` remains optional and must reference an immutable candidate already present in authoritative research state before it can participate.

## Registered 15-minute research challenger

PR #185 (`873ff4270efb`) adds the fixed-spec, publisher-locked challenger registration path. Registration workflow run `34637024563` completed successfully and published the authoritative candidate `research-r1-exit-15m-v1` as a child of `scheduled-research-root`.

The registered challenger:

- keeps the root strategy code revision and risk configuration;
- changes only the bounded paper max-position-age to **15 minutes** (`900000` ms);
- remains paper-only and **TOUCHED / NON-PROMOTIONAL**;
- inherits the root lineage's effective touched intervals;
- has no local challenger observations at registration time;
- is selected through `RESEARCH_CHALLENGER_CANDIDATE_ID` for future eligible scheduled research fan-out only.

No research capture was manually dispatched to activate it. Future root-vs-challenger evidence must come from naturally eligible scheduled research captures using the same authenticated recording.

## Implemented authoritative V4 synchronization

The authoritative V4 interval/completeness synchronization path is implemented in `.github/workflows/research-v4-registry-sync.yml`. Research finalization/recovery consumes this trusted authority and fails closed when V4 coverage is incomplete or overlap cannot be ruled out.

## Recent reliability and throughput work

Recent mainline work relevant to the current handoff includes:

- PR #176 refreshed verified status after a successful V4 cohort;
- PR #177 prevents redundant safe-gap wakeups when a protected successor V4 acquisition is present;
- PR #178 deduplicates observer bootstrap attachment when a workflow-run observer is already active;
- PR #179 makes V4 intake diagnostics ignore cancelled/incomplete curator artifacts that lack a valid intake report and extends curator time for offline aggregation;
- PR #180 keeps downloaded V4 transport archives in scratch space so durable intake diagnostics remain lightweight without changing admission semantics;
- PR #181 binds research replay economics to the immutable registered candidate execution config and regression-locks that provenance relationship;
- PR #183 reuses one authenticated daily research capture across the required root plus at most one optional registered challenger while keeping candidate economics, provenance, failures, and authoritative registry updates isolated;
- PR #185 registers the fixed 15-minute touched challenger through the publisher-locked authoritative registry path and activates it only for future scheduled research fan-out;
- PR #187 adds a read-only root+challenger rollout verifier and runs it in the scheduled research finalizer whenever an authenticated two-candidate fan-out artifact is present;
- PR #188 hardens that verifier so successful candidate artifacts must match the exact fan-out code/config and authenticated capture identity, and independently reasserts authoritative V4 disjointness/completeness while preserving nonfatal challenger failure;
- PR #189 removes a CI timing flake from the bounded recorder test without changing production recorder behavior.
- PR #191 upgrades GitHub workflow runtime actions to checkout/setup-python v7, removes the Node 20 deprecation path, and regression-locks against reintroducing the deprecated majors without changing workflow semantics.

None of these changes alter frozen V4 economics, promotion thresholds, the daily research cap, or live-trading controls.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Continue admitting only clean, complete, flat frozen-runtime V4 evidence through the frozen curator; do not manually retry, extend, cancel, dispatch, or backfill protected V4 runs.
3. Observe the implemented authoritative V4 interval/completeness synchronization path before any subsequent research economics are admitted, and respect the one-success-per-UTC-day research guard. Scheduled run `34597347820` correctly stopped before capture on 2026-09-11 because a successful research cohort already existed for that UTC day. Do not override or weaken that guard.
4. On the first naturally eligible scheduled research cohort after challenger activation, let the finalizer's `cocomelon.research.rollout_verifier` check that exactly one authenticated public-mainnet capture is reused for both `scheduled-research-root` and `research-r1-exit-15m-v1`; a two-candidate rollout must fail closed if this contract is not satisfied.
5. Require that verification to confirm the root's immutable 20-minute paper replay config and the challenger's immutable 15-minute paper replay config share the same authenticated source interval. Successful candidate decision artifacts must match the exact fan-out code/config identity and the capture's recording/source digests.
6. Require the root result to remain mandatory and challenger failure to remain nonfatal to an otherwise valid root checkpoint. The finalizer must independently reassert authoritative V4 disjointness/completeness for the shared interval before accepting the rollout verification.
7. Keep every challenger result permanently **TOUCHED / NON-PROMOTIONAL**. Apply only the precommitted D-023 futility/promising rules: candidates may fail fast; candidates may not succeed fast.
8. If the challenger becomes `RESEARCH_PROMISING`, freeze a new immutable challenger identity and enforce the inherited touched-period plus 6-hour embargo before any future untouched validation claim.
9. Let the frozen V4 one-shot evaluate only when immutable finalization criteria are met; do not inspect or infer interim V4 economics.
10. Advance toward Phase 10 only if the authoritative untouched one-shot eventually reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Hard prohibitions

- Do not use Hyperliquid testnet.
- Do not enable live wallet/order/transfer/withdrawal behavior in the evidence or research lanes.
- Do not manually retry or extend V4 because of an acquisition/economic outcome.
- Do not import V4 economics/history into research.
- Do not weaken provenance, overlap, gap, replay-completeness, flat-exposure, attestation, authentication, one-shot, or daily research-cap gates to accumulate trades faster.
- Do not use nominal cron timing as a substitute for actual V4 run/job/session interval authority.

**LIVE TRADING: DISABLED.**
