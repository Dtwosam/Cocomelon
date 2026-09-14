# Cocomelon Project Status

**Last updated:** 2026-09-14  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified implementation baseline:** `567491b8f115bfb5fcc7965e5201d751736851a9`  
**Latest verified baseline CI:** run `34903119463` — success  
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

Latest trusted Evidence Dashboard snapshot, refreshed **2026-09-14 22:15 UTC**:

- **48 accepted V4 cohorts**;
- **83 / 100 closed paper trades**;
- **15 / 30 closed-trade days**;
- **5,045 strategy decisions**;
- raw Phase 9 minimums not met;
- economic edge not measured yet;
- live orders disabled.

The **30 closed-trade-day requirement remains the dominant raw calendar gate**. Additional same-day cohorts cannot substitute for missing unique closed-trade days.

Latest accepted protected V4 state:

- latest accepted source run: `34855303556`;
- source run #64 started naturally at **2026-09-14 14:23:33 UTC**, completed successfully at **19:57:58 UTC**, and was accepted into the V4 corpus;
- latest successful V4 curator: `34890051900`;
- latest V4 corpus artifact ID: `10366517631`;
- latest V4 mainnet attestation begins `eb5d2ae18e7e1d26…`;
- V4 one-shot state: **waiting for finalizable snapshot**.

The configured **2026-09-14 19:37 UTC** V4 acquisition slot was not observed. Its 90-minute scheduler-health grace expired at 21:07 UTC, and the trusted dashboard now reports **stale — configured 19:37 UTC slot not observed**. This is scheduler observability only: the missed economic slot is not retried, manually dispatched, extended, or backfilled. Scheduled delivery later resumed for the non-economic V4 authority-sync workflow at 22:08 UTC. The next frozen nominal V4 slot is **2026-09-15 01:37 UTC**.

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

Research futility requires at least 20 closed research trades. `RESEARCH_PROMISING` requires at least 40 closed research trades, at least 7 distinct closed-trade UTC days, `P(mu > 0) >= 0.80`, no integrity/contamination/hard-risk issues, and complete costs. Even then, the candidate still requires a frozen specification, inherited touched-period handling, the documented 6-hour embargo, and future untouched validation before any promotion path can be considered.

## Current research state

Latest trusted Research Dashboard snapshot, refreshed **2026-09-14 20:31 UTC**:

### `scheduled-research-root`

- state: `researching`;
- **6 authenticated checkpoints**;
- **4 closed research trades**;
- **2 long / 2 short**;
- **3 closed-trade days**;
- no-trade streak: **1**;
- cumulative touched research net PnL: `5.401591955399999999999999590`;
- cumulative touched research mean R: `0.0540198086234484624200771524`;
- posterior threshold unavailable because the minimum research trade count has not been met.

### `research-r1-exit-15m-v1`

- state: `researching`;
- **1 authenticated checkpoint**;
- **0 closed research trades**;
- **0 closed-trade days**;
- no-trade streak: **1**;
- cumulative touched research net PnL: `0`;
- posterior unavailable.

These economics are touched research only. They are not verified edge and cannot support live promotion.

The successful research cohort `34888205962` already consumed the one-success-per-UTC-day allowance for **2026-09-14 UTC**. No second successful research cohort should be created that day merely to exercise the new verifier gate. The next post-#197 rollout proof must come from a naturally eligible later UTC-day safe gap.

## First natural root + challenger cohort

Research run `34888205962` was the first successful naturally controlled post-#195 root+challenger cohort:

- campaign event: `workflow_dispatch` by `github-actions[bot]`, not a direct campaign schedule;
- one shared public-mainnet capture source: `research-mainnet-34888205962-1`;
- authenticated capture interval: `[1789415850415, 1789417655787]` ms, approximately **19:57:30–20:27:35 UTC**;
- authoritative V4 completeness extended through `1789417692055` ms, beyond the capture end;
- refreshed authority found no protected V4 overlap;
- root used the immutable 20-minute max-position-age configuration;
- challenger used the immutable 15-minute max-position-age configuration;
- both candidate attempts succeeded and are **COUNTED**;
- both produced zero new closed trades in this cohort.

The campaign's prepare, capture, authority-refresh, candidate-decision, evaluation, finalization, and dashboard jobs all completed successfully. The same-day success guard and active-V4 preflight remained enabled.

A read-only retrospective audit of the archived run artifact passed the full fixed-pair rollout-verifier contract: exact candidate identities and horizons, shared source/interval, recording/source digests, candidate code/config identity, exact attempt state, decision artifacts, and authoritative V4 disjointness/completeness all matched.

However, the old workflow's finalizer **skipped** `Verify root+challenger rollout contract` because the successful evaluation path did not restore `research-fanout.json` into the finalizer state. Therefore this cohort is contract-consistent and remains counted, but it did not prove that the verifier was an in-workflow publication gate.

## Implemented authoritative V4 synchronization

The authoritative V4 interval/completeness synchronization path is implemented in `.github/workflows/research-v4-registry-sync.yml`. Research capture, evaluation, and finalization consume this trusted authority and fail closed when actual V4 coverage is incomplete or overlap cannot be ruled out. Nominal cron timing is not a substitute for this authority.

## Rollout verification enforcement

PR #197 fixed the demonstrated publication-order defect and merged as `cfe993ded68d19d0f4491c05d7d49ac20416722f`:

- the fixed root+15m rollout verifier now runs inside `evaluate-research` **before** the first authoritative research-registry upload;
- a failed evaluation/verifier cannot restore post-evaluation registry state for fallback publication;
- finalization restores the isolated fan-out plan so the independent final audit cannot silently skip;
- fallback publication after successful evaluation is gated on final verifier success;
- the fixed 20m/15m verifier is scoped to the intended immutable candidate pair.

No strategy, market-data, execution, risk, V4 acquisition, promotion, or live-order rule changed.

Verification evidence for #197:

- RED CI `34895660285` failed only the new pre-publication verifier contract after compile, Ruff, mypy, and research smoke passed;
- GREEN branch CI `34896531120` passed compile, Ruff, mypy, full pytest, and research smoke;
- PR-context CI `34896661359` passed both `test` and `research` jobs;
- post-merge `main` CI `34896797631` passed compile, Ruff, mypy, full pytest, and research smoke.

## Reliability state

Recent verified reliability changes include:

- PR #189 removed a bounded-recorder CI timing flake without changing production recorder behavior;
- PR #191 upgraded checkout/setup-python workflow actions to v7 and regression-locked against deprecated runtime majors;
- PR #193 repaired shared-capture replay revision provenance without changing the generic mainnet or V4 validators;
- PR #194 upgraded artifact upload/download actions to Node 24 majors and passed the Phase 9 heartbeat smoke;
- PR #195 eliminated the delayed direct-research-cron race while preserving all overlap, daily-cap, V4, promotion, and live guards;
- PR #197 made root+challenger rollout verification an authoritative publication gate and preserved safe pre-evaluation fallback semantics;
- PR #201 added successful `main` CI completion as an independent evidence-dashboard wakeup so scheduler-health reporting does not rely solely on schedule delivery;
- PR #202 kept that CI wakeup outside trusted evidence-event provenance, preserving strict curator/one-shot provenance validation.

Verified production evidence for the scheduler-observability path:

- #201 merge `01205a649174e790d1b06085bd7ec86677a81c18` exposed the expected provenance boundary when CI-triggered dashboard run `34902592041` correctly rejected a CI run ID as invalid evidence provenance;
- #202 RED CI `34902730316` failed only the new CI-provenance-isolation contract;
- #202 GREEN branch CI `34902861595` and PR-context CI `34903021344` passed compile, Ruff, mypy, full pytest, and research smoke;
- #202 merged as `567491b8f115bfb5fcc7965e5201d751736851a9`;
- post-merge `main` CI `34903119463` passed compile, Ruff, mypy, full pytest, and research smoke;
- push-triggered dashboard run `34903119502` passed end-to-end;
- decisive CI-triggered dashboard `workflow_run` `34903200802` passed end-to-end and refreshed issue #82 while keeping CI outside evidence provenance.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Continue admitting only clean, complete, flat frozen-runtime V4 evidence through the frozen curator and keep interim V4 economics opaque.
3. Do not manually retry, extend, cancel, dispatch, or backfill the missed 2026-09-14 19:37 UTC V4 slot or any later V4/research evidence based on outcome.
4. Let the next frozen V4 slot at 2026-09-15 01:37 UTC occur naturally; scheduler health may observe it but must not synthesize it.
5. Observe the implemented authoritative V4 interval/completeness synchronization path before admitting any subsequent research economics, and require actual interval coverage/disjointness rather than nominal cron assumptions.
6. Let the next naturally eligible post-#197 research safe gap on a later UTC day launch through the dispatcher.
7. Require `Verify root+challenger rollout contract before authoritative publish` to succeed before any new fixed-pair research registry checkpoint can become authoritative.
8. Require the independent final rollout verifier to succeed for that cohort; otherwise do not count it as successful rollout validation.
9. Count only authenticated successful research checkpoints; failed, contaminated, running, and evaluating attempts remain **NOT COUNTED**.
10. At 20 closed research trades, apply only the precommitted futility rule; do not infer edge from the current four-trade root sample or zero-trade challenger sample.
11. Do not label a candidate `RESEARCH_PROMISING` before at least 40 closed research trades, 7 distinct closed-trade UTC days, `P(mu > 0) >= 0.80`, complete costs, and clean integrity/risk state.
12. Let the frozen V4 one-shot evaluate only when immutable finalization criteria are met; do not inspect or infer interim V4 economics.
13. Advance toward Phase 10 only if the authoritative untouched one-shot eventually reaches `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Hard prohibitions

- Do not use Hyperliquid testnet.
- Do not enable live wallet/order/transfer/withdrawal behavior in the evidence or research lanes.
- Do not manually retry, extend, cancel, dispatch, or backfill V4 based on outcome.
- Do not import V4 economics/history into research.
- Do not weaken provenance, overlap, gap, replay-completeness, flat-exposure, attestation, authentication, one-shot, or daily research-cap gates to accumulate trades faster.
- Do not use nominal cron timing as a substitute for actual V4 run/job/session interval authority.

**LIVE TRADING: DISABLED.**
