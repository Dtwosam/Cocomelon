# Cocomelon Project Status

**Last updated:** 2026-08-26  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified main revision:** `2e64fd6c2a4ed1582330aa17d4eaeaae81c201df`  
**Live trading:** **DISABLED**  
**Real baseline edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

## Current state

The genuine-mainnet evidence path is automated and fail-closed from public Hyperliquid mainnet capture through independent admission, corpus accumulation, counts-only readiness, snapshot freezing, and the locked one-shot Phase 9 OOS evaluation. No real-money order path is enabled or authorized.

The immutable revisions governing the current Campaign V2 research protocol remain:

- **strategy/risk/execution/evidence runtime:** `6de9d86aa7c36fce4f459e0bcc4e004de9215f25`;
- **retry-selection ledger tooling:** `e87a575a755074e36e22729c63c4831b474cf339`;
- **frozen one-shot Phase 9 evaluator:** `629db6294822c97690c006591802f8a47e08652e`.

The scheduled workflow may evolve operationally, but each acquisition checks out the immutable runtime and ledger revisions above. Strategy, risk, sizing, paper execution, economic admission semantics, and the frozen evaluator are not changed by scheduler/dashboard maintenance.

The latest independently verified corpus snapshot contains:

- **2 accepted genuine-mainnet cohorts**;
- **30 strategy decisions**;
- **0 / 100 required untouched OOS closed paper trades**;
- **0 / 30 required closed-trade days**;
- **no economic edge claim**;
- **live orders disabled**.

Those values are readiness/accounting facts only. They do not demonstrate profitability.

## Recent production findings and repairs

Campaign V2 run `32947327826` completed successfully and its curator run `32951339075` safely admitted the second verified corpus cohort. The curator later failed after corpus publication because candidate identity incorrectly depended on a recording-session-bound `config_digest`, so equivalent frozen candidate semantics from separate recording sessions could disagree on `candidate_id`.

PR #81 repaired that defect. Candidate identity now derives from the frozen strategy/risk/execution semantics, code revision, evidence class, fee schedule, feature version, and replay engine rather than the session-bound recording digest. Genuine semantic changes therefore still fail closed, while distinct recording sessions of the same frozen candidate no longer create a false identity conflict. The fix was regression-tested RED/GREEN and merged at `f709a59d955a05a03bbb94173a6e9b185d75a765`.

PR #83 added a GitHub-native, self-updating evidence dashboard and merged at `2e64fd6c2a4ed1582330aa17d4eaeaae81c201df`. Issue #82 is the human-readable tracking page. Its updater accepts counts only from trusted `v2-mainnet-corpus` artifacts produced by the exact curator workflow and shows campaign/curator provenance separately from accepted-corpus progress. Failed or unverified campaign evidence is not counted merely because a workflow ran.

As of this status refresh, Campaign V2 run `32961501478` is still inside its bounded recording step. It must be allowed to finish normally. The curator triggered by its completion is the next production verification of the candidate-identity repair; no economic conclusion should be inferred from the active recording job.

## Locked Phase 9 evidence policy

The merged Phase 9 evaluator remains the authoritative economic gate. Its locked policy requires:

- at least 100 untouched OOS closed trades;
- at least 30 OOS covered days;
- at least 3 eligible walk-forward windows;
- at least 20 trades per eligible walk-forward window;
- at least 20 trades per score bucket;
- at least 60% positive eligible walk-forward windows;
- 95% bootstrap confidence;
- 5-day day-block bootstrap;
- 2,000 bootstrap resamples;
- 6-hour split embargo;
- sampled `NO_TRADE` horizons of 1 hour and 4 hours.

`CANDIDATE_EDGE` additionally requires positive untouched-test mean net R, a bootstrap lower confidence bound above zero, stable positive walk-forward behavior, market positive-PnL concentration no greater than 35%, and seven-day concentration no greater than 50%.

The evaluator exposes the explicit states:

- `INVALID_EVIDENCE`;
- `OOS_CONTAMINATED`;
- `INSUFFICIENT_EVIDENCE`;
- `NO_EDGE_DEMONSTRATED`;
- `CANDIDATE_EDGE`.

Phase 10 remains blocked unless the genuine one-shot Phase 9 result is `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Scheduled genuine-mainnet Campaign V2

`.github/workflows/evidence-campaign-scheduled.yml` is the sole production evidence-acquisition path. It is scheduled at `37 1,4,7,10,13,16,19,22 * * *` UTC and supports manual workflow dispatch. Ordinary repository pushes do not launch the expensive campaign.

Campaign V2 enforces:

- public Hyperliquid **mainnet** only;
- API endpoint `https://api.hyperliquid.xyz`;
- WebSocket endpoint `wss://api.hyperliquid.xyz/ws`;
- paper execution only;
- two independent public-mainnet WebSocket lanes with phased connection startup;
- merged-feed failover/backfill and cross-lane duplicate suppression;
- durable fail-fast handling of genuine merged-feed gaps;
- up to two bounded 45-minute attempts;
- retry only after auditable non-performance rejection for replay incompleteness, dataset incompleteness/gaps, or open replay exposure;
- no PnL, final-equity, profitability, or edge input to retry selection;
- replay/dataset completeness and flat paper exposure before economic admission;
- deterministic retry-lineage persistence through immutable ledger revision `e87a575a755074e36e22729c63c4831b474cf339`;
- 90-day artifact retention;
- serialized campaign execution with `cancel-in-progress=false`.

Lane-local reconnect, duplicate, and anomaly counters remain diagnostics. Covered lane-local defects do not masquerade as merged-feed corruption, while real merged coverage loss remains fatal.

## Genuine-mainnet admission and curator boundary

The offline `cocomelon-mainnet-evidence` surface provides `verify`, `aggregate`, `progress`, `freeze-dataset`, `prepare-phase9-v2`, and `evaluate-phase9-v2`. Regression tests reject testnet, live-order, and caller-supplied API/WS endpoint overrides on this evidence surface.

Attestation fails closed on wrong/non-mainnet endpoints, live-order semantics, incomplete replay evidence, persisted merged gaps, lineage mismatches, reused recording sessions, overlapping cohort windows, conflicting incremental payloads, and right-censored paper exposure.

`.github/workflows/evidence-corpus-curator.yml` listens for completed Campaign V2 runs and serializes corpus mutation. For each source run it:

1. downloads the immutable artifact from the exact workflow run;
2. requires a successful source conclusion and independently verifies the cohort;
3. recomputes and binds retry-selection lineage when required;
4. rejects diagnostic/ineligible evidence without corpus mutation;
5. idempotently aggregates an eligible cohort;
6. writes counts-only progress;
7. preserves intake/selection diagnostics;
8. preserves a successfully aggregated corpus even if a later Phase 9 lifecycle step fails.

The curator checks out current `main` admission/evaluation tooling while acquisition remains pinned to the immutable campaign runtime. Workflow success alone is never treated as an economic claim.

## GitHub evidence dashboard

Issue #82, `Cocomelon Evidence Dashboard`, is the canonical human-readable progress view:

`https://github.com/Dtwosam/Cocomelon/issues/82`

`.github/workflows/evidence-dashboard.yml` refreshes that issue after curator completion and also exposes manual workflow dispatch. The dashboard builder independently resolves a trusted curator run and a trusted `v2-mainnet-corpus` artifact before rendering counts. It displays corpus counts, Phase 9 raw readiness, live-order state, campaign status, curator outcome, artifact provenance, and direct tracking links.

The dashboard is informational only. It cannot enable live trading or change strategy/risk behavior.

## One-shot V2 OOS protocol

The protocol is fixed from the first attested V2 source timestamp:

- 1 calendar day of train bookkeeping;
- 1 calendar day of validation bookkeeping;
- 45 calendar days of untouched test;
- 7-day expanding walk-forward windows stepped every 7 days;
- a locked 6-hour embargo.

Snapshot run selection is calendar-driven and independent of economic performance. Readiness uses only timestamps and counts and does not inspect PnL, net R, bootstrap results, win rate, profit factor, or edge status.

When structurally ready, the path is:

1. build the deterministic selected run set;
2. verify the 100-trade / 30-day / 3-window readiness floor;
3. freeze split, candidate, policy, sensitivity, and walk-forward specifications;
4. hash-bind the journal, facts, attestation, and specification files into snapshot identity;
5. upload `v2-phase9-frozen-snapshot` before economic evaluation;
6. evaluate exactly that snapshot with frozen evaluator revision `629db6294822c97690c006591802f8a47e08652e`;
7. upload the final `v2-phase9-evaluation` artifact.

If the fixed test window closes underpowered, the curator persists readiness-only `v2-phase9-terminal-insufficient` with `edge_status = insufficient_evidence`. It does not reveal performance and does not roll the OOS window forward to mine another result.

## Recent Phase 9 milestones

- PR #65 — recording-time REST polls offloaded from the recorder event loop; immutable Campaign V2 runtime `6de9d86aa7c36fce4f459e0bcc4e004de9215f25`.
- PR #73 — fail-closed deterministic retry ledger; immutable tooling `e87a575a755074e36e22729c63c4831b474cf339`.
- PR #74 — Campaign V2 uses bounded attempt 2 after non-performance completeness/flatness rejection.
- PR #76 — curator intake staging preserved across checkout.
- PR #78 — right-censored retry selection-audit lineage regression coverage.
- PR #79 — fixed Campaign V2 cadence increased to eight UTC windows/day without changing economic selection.
- PR #81 — candidate identity separated from recording-session digest; merged at `f709a59d955a05a03bbb94173a6e9b185d75a765`.
- PR #83 — self-updating trusted GitHub evidence dashboard; merged at `2e64fd6c2a4ed1582330aa17d4eaeaae81c201df`.

Historical engineering detail remains available in Git history and the decision/spec documents; this status file is intentionally focused on the current production evidence boundary.

## Locked safety/product invariants

- Hyperliquid testnet is forbidden.
- Market observation is Hyperliquid mainnet only.
- Default and current execution is paper/shadow.
- No live exchange adapter is enabled or authorized.
- No wallet/private-key signing, transfer, withdrawal, or private-account execution path is part of the evidence campaign.
- Whole-market discovery remains dynamic; eligibility is separate from ranking.
- Explainable deterministic baselines remain first-class before ML; `NO_TRADE` is valid.
- Strategy cannot size positions or send orders; independent risk has final veto.
- No averaging down, martingale, or stopless positions.
- No historical L2/order flow may be fabricated from candles.
- Real-money activation requires explicit later authorization after all promotion gates pass.

## Exact next action

1. Keep Phase 10 and live trading blocked.
2. Let Campaign V2 run `32961501478` finish normally; do not cancel/restart it merely because it uses the bounded second-attempt path.
3. Inspect the curator triggered by that completion. Confirm that the former cross-session candidate-identity conflict no longer occurs; if any infrastructure/accounting defect remains, reproduce it deterministically and repair it with TDD.
4. Verify the dashboard workflow triggered after curator completion and confirm issue #82 reflects only trusted accepted-corpus state.
5. Continue collecting temporally distinct paper-only cohorts at the fixed eight-window UTC cadence using the immutable runtime and retry-ledger tooling.
6. Admit only transport-clean, replay/dataset-complete, flat cohorts through independent curator verification.
7. Accumulate counts-only evidence without early PnL inspection.
8. At the deterministic V2 cutoff, persist either the frozen one-shot snapshot and genuine Phase 9 evaluation or the readiness-only terminal `INSUFFICIENT_EVIDENCE` result.
9. Advance toward Phase 10 only if the genuine one-shot result is `CANDIDATE_EDGE` and every locked promotion criterion passes.

## Profitability and live-trading status

**REAL BASELINE EDGE: UNMEASURED.**

No currently verified result demonstrates repeatable economic edge. `UNMEASURED` is not the same as `NO_EDGE_DEMONSTRATED`.

**LIVE TRADING: DISABLED.**
