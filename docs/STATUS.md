# Cocomelon Project Status

**Last updated:** 2026-08-25  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`  
**Verified main revision:** `93fc14fc2f771d686714be6d661686c71a26bc86`  
**Live trading:** **DISABLED**  
**Real baseline edge:** **UNMEASURED**  
**Phase 10:** **BLOCKED**

## Current state

The engineering path through genuine-mainnet evidence collection, attestation, accumulation, and a one-shot Phase 9 OOS evaluation is automated and fail-closed. The public-mainnet transport path has crossed its previous failure boundary in both a bounded redundant-lane smoke and a full 45-minute Campaign V2 capture with zero merged gaps, duplicates, anomalies, or reconnects.

The three immutable revisions that matter for the current research campaign are:

- **Campaign V2 strategy/risk/execution/evidence runtime revision:** `6de9d86aa7c36fce4f459e0bcc4e004de9215f25`;
- **Campaign retry-selection ledger tooling revision:** `e87a575a755074e36e22729c63c4831b474cf339`;
- **Frozen one-shot Phase 9 evaluator revision:** `629db6294822c97690c006591802f8a47e08652e`.

The current campaign runtime revision includes lane-wide standby-readiness transport semantics, 15-second redundant WebSocket connection spacing, and recording-time REST polling offloaded from the asyncio event loop. The scheduled workflow itself may evolve operationally, but every evidence capture checks out the immutable runtime revision above. Retry-selection auditing is pinned separately to the immutable ledger revision. Untouched-test snapshot preparation and evaluation remain bound to the frozen evaluator revision. Strategy, risk, sizing, and paper execution are not changed by the scheduler or curator.

Immediate paper-only Campaign V2 run `32880737422` completed its first full 45-minute capture from the immutable runtime. The capture was transport-clean and replay/dataset complete, but it was correctly excluded from economics because one PUMP paper position remained open at the replay horizon (`opened_positions = 1`, `closed_positions = 0`). The run therefore failed the locked flat-exposure gate rather than being admitted to the corpus. No PnL-based retry or admission decision was made.

PRs #73 and #74 subsequently made the already-budgeted second 45-minute attempt usable for this exact non-performance failure mode. A transport-clean attempt is now probed offline for replay completeness, dataset completeness/gaps, and flat exposure before it may become `CLEAN_ATTEMPT`. If it is right-censored or incomplete, that reason is persisted in the deterministic selection-audit ledger and the workflow may spend attempt 2. Final canonical replay and all economic-admission assertions still run unchanged after selection.

No real-money order path is enabled or authorized.

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

The evaluator exposes the explicit evidence states:

- `INVALID_EVIDENCE`;
- `OOS_CONTAMINATED`;
- `INSUFFICIENT_EVIDENCE`;
- `NO_EDGE_DEMONSTRATED`;
- `CANDIDATE_EDGE`.

Phase 10 remains blocked unless a genuine one-shot Phase 9 result satisfies the locked policy.

## Scheduled genuine-mainnet Campaign V2

`.github/workflows/evidence-campaign-scheduled.yml` is the sole production evidence-acquisition path. It is scheduled at `37 1,7,13,19 * * *` UTC and also supports manual workflow dispatch. Ordinary repository pushes do not launch the expensive campaign.

Campaign V2 is pinned to `6de9d86aa7c36fce4f459e0bcc4e004de9215f25` and enforces:

- public Hyperliquid **mainnet** only;
- API endpoint `https://api.hyperliquid.xyz`;
- WebSocket endpoint `wss://api.hyperliquid.xyz/ws`;
- paper execution only;
- two independent public-mainnet WebSocket lanes;
- 15-second connection phasing between redundant lanes;
- merged-feed failover/backfill and cross-lane duplicate suppression;
- lane-wide session readiness after subscription setup is proven by live data;
- immediate readiness revocation when a lane disconnects;
- recording-time REST context/funding calls offloaded from the asyncio WebSocket loop and serialized behind an async lock;
- durable fail-fast termination when the merged feed records a real gap;
- up to two bounded 45-minute acquisition attempts;
- zero merged gaps, duplicates, and anomalies for an economically eligible capture;
- an offline in-loop admission probe that may reject an attempt only for replay incompleteness, dataset incompleteness/gaps, or open replay exposure;
- deterministic persistence of those retry reasons through immutable ledger revision `e87a575a755074e36e22729c63c4831b474cf339`;
- no PnL, final-equity, profitability, or edge input to retry selection;
- replay and dataset completeness;
- flat paper exposure at replay end;
- final canonical replay and flatness assertions after attempt selection;
- 90-day artifact retention;
- serialized campaign execution with `cancel-in-progress=false`.

Lane-local reconnect, duplicate, and anomaly counters remain preserved as transport diagnostics. They are not silently erased, but covered lane-local defects do not masquerade as merged-feed corruption. Real merged coverage loss remains fatal.

## Genuine-mainnet admission boundary

The dedicated offline `cocomelon-mainnet-evidence` surface provides:

- `verify` — independently validate one downloaded genuine-mainnet cohort;
- `aggregate` — idempotently append eligible cohorts to the attested corpus;
- `progress` — counts-only corpus readiness without revealing PnL;
- `freeze-dataset` — freeze the exact attested run set;
- `prepare-phase9-v2` — create the deterministic one-shot Phase 9 snapshot candidate;
- `evaluate-phase9-v2` — consume only a ready frozen snapshot through the existing Phase 9 evaluator.

The command surface is local/offline only. Regression tests explicitly reject `--testnet`, `--live`, `--api-url`, and `--ws-url`, including value-bearing API/WS forms.

Genuine-mainnet attestation rejects or fails closed on, among other things:

- wrong/non-mainnet endpoints;
- live-order semantics;
- incomplete replay evidence;
- persisted merged data gaps;
- metadata/replay lineage mismatches;
- reused recording-session IDs across distinct runs;
- overlapping cohort time windows;
- conflicting incremental source payloads;
- right-censored paper exposure at cohort end.

Existing attested aggregates are re-verified when they are read for append, progress, or freeze operations.

The curator requires a successful source campaign before a verified artifact may mutate the corpus. Post-introduction retry-selection audit lineage is recomputed from the persisted attempt ledger and now explicitly binds the source repository, `main` branch, production Campaign V2 workflow ID/path, exact workflow run ID, and authoritative trigger-head SHA. The curator requires ledger revision `e87a575a755074e36e22729c63c4831b474cf339` for new Campaign V2 evidence.

## Automatic corpus curator

`.github/workflows/evidence-corpus-curator.yml` listens for completed Campaign V2 runs and serializes corpus mutation.

For each campaign completion it:

1. downloads the immutable campaign artifact from the exact source run;
2. requires a successful source workflow conclusion and independently verifies the cohort;
3. recomputes and binds the retry-selection audit when required;
4. rejects diagnostic/ineligible evidence without mutating the corpus;
5. idempotently aggregates an eligible cohort into the latest `v2-mainnet-corpus` artifact;
6. writes counts-only progress;
7. preserves intake diagnostics;
8. preserves a successfully aggregated corpus even if a later Phase 9 lifecycle step fails.

The curator checks out current `main` evaluation/admission tooling, while acquisition itself remains fixed to the immutable runtime. The curator does not make an economic claim from workflow success alone.

## One-shot V2 OOS protocol

PR #39 introduced a deterministic one-shot Phase 9 protocol. PR #40 permanently pinned the evaluator used by that protocol. PR #41 added a terminal underpowered-evidence state. PR #42 strengthened the offline CLI regression boundary.

The V2 protocol is fixed from the first attested V2 source timestamp:

- 1 calendar day of train bookkeeping;
- 1 calendar day of validation bookkeeping;
- 45 calendar days of untouched test;
- 7-day expanding walk-forward evaluation windows stepped every 7 days;
- the locked 6-hour embargo remains in force.

Snapshot run selection is calendar-driven and independent of performance. All attested sources beginning before the fixed 47-day protocol cutoff are selected, plus at most the first source needed to bridge the cutoff. Later cohorts cannot roll the V2 test window forward.

Readiness uses only timestamps and counts. It does **not** inspect PnL, net R, bootstrap results, win rate, profit factor, or edge status.

A ready one-shot path is:

1. create a snapshot candidate from the deterministic selected run set;
2. verify the locked 100-trade / 30-day / 3-window readiness floor;
3. freeze split, candidate, policy, sensitivity, and walk-forward specifications;
4. hash-bind the copied journal, facts, attestation, and specification files into the snapshot identity;
5. upload `v2-phase9-frozen-snapshot` **before** economic evaluation;
6. evaluate that exact snapshot with frozen evaluator revision `629db6294822c97690c006591802f8a47e08652e`;
7. upload the final `v2-phase9-evaluation` artifact.

The bootstrap path is deterministic for a fixed evaluation lineage, so a retry cannot obtain a new favorable bootstrap draw.

If the fixed test window completes but the count/day/walk-forward readiness floor is not met, the curator does **not** reveal performance metrics and does **not** keep retrying OOS evaluation indefinitely. It persists a readiness-only `v2-phase9-terminal-insufficient` artifact with `edge_status = insufficient_evidence` and blocks later V2 OOS attempts.

## Genuine-mainnet transport qualification and diagnostics

### Gap-free REST-offload heartbeat qualification

The bounded heartbeat workflow was promoted to runtime revision `6de9d86aa7c36fce4f459e0bcc4e004de9215f25` after a deterministic regression reproduced event-loop starvation from synchronous REST polling.

GitHub Actions run `32878425117` then completed successfully on genuine public Hyperliquid mainnet with:

- 98 seconds elapsed;
- 2,972 recorded real mainnet events;
- 0 merged gaps;
- 0 duplicate events;
- 0 anomalies;
- 0 reconnects;
- 2 healthy redundant WebSocket lanes;
- `network_access = true` for public data capture;
- `live_orders = false`.

Lane 0 connected in roughly 386 ms. Lane 1 started approximately 15 seconds later and connected in roughly 352 ms. Both lanes became session-ready and neither disconnected during the capture. This is transport qualification only and makes no economic claim.

### First transport-clean 45-minute Campaign V2 cohort

GitHub Actions run `32880737422` completed the first full 45-minute Campaign V2 capture on immutable runtime `6de9d86aa7c36fce4f459e0bcc4e004de9215f25`.

Verified capture/replay facts included:

- 46,408 genuine public Hyperliquid mainnet market events;
- 0 merged gaps;
- 0 duplicate events;
- 0 anomalies;
- 0 reconnects;
- 2 redundant WebSocket lanes;
- complete offline replay;
- complete evaluation dataset with empty `gap_refs`;
- 15 strategy decisions;
- 1 risk approval;
- 1 execution attempt;
- 1 paper fill;
- 1 opened PUMP short position;
- 0 closed positions/trades;
- `network_access = false` and `live_orders = false` during replay.

The position opened roughly five minutes into the session and remained open for about 40 minutes without reaching the baseline's existing exit conditions. The cohort was therefore **transport-qualified but economically excluded** with `economic_ineligibility_reasons = ["open_exposure"]`. It did not mutate the economic corpus and makes no edge claim.

This run exposed an operational inefficiency rather than a transport/accounting defect: the old scheduler selected the first transport-clean attempt before checking flatness, so its already-budgeted second attempt was never used. PRs #73/#74 now make that retry decision explicit, deterministic, and non-performance-based.

### Earlier spaced-lane diagnostic

Before the REST-offload fix, run `32859045430` proved connection spacing successfully de-phased redundant lanes but still recorded 62 gap rows after one lane disconnected. That evidence isolated standby/readiness and event-loop scheduling defects; it is diagnostic-only and excluded from economics.

### First 30-minute cohort

GitHub Actions run `32770800218` produced genuine public Hyperliquid mainnet, paper-only evidence from the earlier pinned revision `571c13bfe0bab0312940617540ec973ee3eee3c5`.

Verified activity included:

- 360,404 recorded market events;
- 0 duplicate events;
- 0 anomalies;
- 1 WebSocket reconnect;
- 60 durable gap records;
- 10 strategy decisions;
- 2 risk approvals;
- 1 execution attempt;
- 3 partial fills;
- 1 opened position;
- 0 closed positions/trades.

The replay was incomplete and ended with open ENA short exposure. The cohort is diagnostic-only and cannot support an economic claim.

### Legacy 45-minute retry cohort

The later legacy run `32781582212` attempted two independent 45-minute captures before redundant WebSocket acquisition was introduced. Each attempt recorded roughly 550k events with zero duplicates/anomalies but suffered one socket reconnect and 60 durable gap records. Both attempts were diagnostic-only and excluded from economics.

Those repeated single-socket failures motivated the merged redundant-mainnet acquisition architecture now used by Campaign V2.

## Major Phase 9 evidence milestones

- PR #21 — replay execution-activity accounting repair — merged at `ed3cae5af4a7b971babecec28448675c19d10bf6`.
- PR #23 — fixed-revision evidence-store aggregation — merged at `d404fa8c077c2721de55eda7f7fb2854d590ce4f`.
- PR #25 — genuine-mainnet attestation/economic boundary — merged at `ef3c728e310be6a5b1ed94934a77453fba9c63cd`.
- PR #27 — offline single-cohort verifier — merged at `7be48ed59aa073015042881cbfbe75caa7e08f08`.
- PR #28 — counts-only attested-corpus progress — merged at `ae31c1f7445fb8622a393e5e6223157a6c0cf54b`.
- PR #29 — fail-fast durable-gap watcher — merged at `390d4ba39abe4fe3f476af68587f13f2371d9cba`.
- PR #34 — flat-exposure economic admission — merged at `f6bc36ca...`.
- PR #35 — redundant public-mainnet WebSocket acquisition — merged at `5fa4a6d2...`.
- PR #36 — merged-feed vs transport-health semantics — merged at `7cf19ab8...`.
- PR #37 — scheduled Campaign V2 — merged at `be925d25...`.
- PR #38 — automatic verified evidence-corpus curator — merged at `b36b4d5a...`.
- PR #39 — frozen one-shot V2 OOS snapshot/evaluation protocol — merged at `629db6294822c97690c006591802f8a47e08652e`.
- PR #40 — immutable evaluator pin — merged at `61371d16ffaa56f961e61637c94da68b7b54d020`.
- PR #41 — terminal underpowered V2 state — merged at `c63973592e52992319218e6804673457ff813258`.
- PR #42 — offline Phase 9 CLI regression hardening — merged at `bedd05cfafe5e22b358fc49d0d3e67855c28ca80`.
- PR #50 — durable selection-audit archive canonical revalidation.
- PR #51 — durable Phase 9 final-state canonical revalidation.
- PR #54 — repinned evidence workflows to the spaced redundant-WebSocket cohort.
- PR #65 — offloaded recording-time REST polls from the recorder event loop — runtime merge `6de9d86aa7c36fce4f459e0bcc4e004de9215f25`.
- PR #66 — promoted the REST-offload runtime to the genuine mainnet heartbeat smoke.
- PR #67 — promoted the transport-qualified runtime to the 45-minute scheduled Campaign V2.
- PR #68 — added the bounded one-shot launch hook used to start run `32880737422` immediately.
- PR #69 — removed the one-shot launch hook and permanently guarded against ordinary push-triggered 45-minute campaigns — merged at `47a4e9d48396eb313fc663613cd4ea372e18750e`.
- PR #70 — refreshed Phase 9 status after the immediate campaign launch.
- PR #71 — bound curator intake to authoritative Campaign V2 repository/branch/workflow provenance — merged at `cd65d5e91ca0d66f36e5b7d8c07b8f6c9ef1e61b`.
- PR #72 — bound selection audits to the exact source workflow run ID — merged at `029fff54de7eb87d42d4ce7b16fceabbfb0fceb1`.
- PR #73 — added fail-closed deterministic ledger support for non-performance right-censor retry reasons; immutable tooling revision `e87a575a755074e36e22729c63c4831b474cf339`, merged at `91c3f38595b33557076a21897f6fb9672bcc8c79`.
- PR #74 — made Campaign V2 spend its second bounded attempt after transport-clean completeness/flatness rejection and repinned the curator to the new ledger — merged at `93fc14fc2f771d686714be6d661686c71a26bc86`.

PR #22, the earlier PR-triggered evidence runner, was closed without merging after the scheduled Campaign V2 superseded it. Obsolete PR #24 was also closed after its attestation design was superseded by later merged hardening.

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
2. Let scheduled Campaign V2 continue collecting temporally distinct paper-only cohorts at immutable runtime `6de9d86aa7c36fce4f459e0bcc4e004de9215f25` using immutable retry-ledger tooling `e87a575a755074e36e22729c63c4831b474cf339`.
3. For each run, admit only an attempt that is transport-clean, replay/dataset complete, and flat at the replay horizon; use attempt 2 only after an auditable non-performance rejection of attempt 1.
4. Let the curator independently verify source workflow provenance, retry-selection lineage, and cohort eligibility before any corpus mutation.
5. Accumulate the corpus and report counts-only progress without early PnL inspection.
6. At the deterministic V2 cutoff, persist either:
   - the frozen ready one-shot snapshot followed by the genuine Phase 9 evaluation; or
   - the readiness-only terminal `INSUFFICIENT_EVIDENCE` result.
7. Only if the genuine one-shot result is `CANDIDATE_EDGE` and all locked promotion criteria pass may the approved build order advance toward Phase 10.

## Profitability and live-trading status

**REAL BASELINE EDGE: UNMEASURED.**

No currently verified result in this status document demonstrates repeatable economic edge. `UNMEASURED` is not the same as `NO_EDGE_DEMONSTRATED`.

**LIVE TRADING: DISABLED.**
