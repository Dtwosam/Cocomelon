# Dual-Lane Sequential Research and Frozen Validation Design

**Date:** 2026-08-31  
**Status:** approved; review feedback incorporated before implementation  
**Repository:** `Dtwosam/Cocomelon`

## Problem

The current V4 Phase 9 protocol is intentionally performance-blind until its immutable one-shot evaluation. That protects the final claim from tuning bias, but it is inefficient as the only research loop: a clearly weak future candidate could otherwise consume many days before the project learns enough to redesign it.

The project needs two different optimization objectives at the same time:

1. **fast failure detection and rapid research iteration** so obviously weak candidates do not consume a full validation window; and
2. **untouched final validation** so a candidate that survives research can still make a statistically credible economic claim.

Using one lane for both objectives creates a conflict. Repeatedly inspecting interim PnL and changing a candidate can accelerate research, but that same evidence can no longer be treated as untouched out-of-sample proof.

## Decision

Adopt a **dual-lane architecture**:

- **Validation lane:** the existing frozen V4 Phase 9 protocol remains unchanged and performance-blind. It is the authoritative path for any promotion claim.
- **Research lane:** a separate adaptive paper/shadow environment exposes full economics for distinct research candidates, supports precommitted sequential futility checks, and allows rapid challenger iteration.

The governing asymmetry is:

> **Candidates may fail fast. Candidates may not succeed fast.**

A research candidate can be rejected early when operational evidence is invalid or when precommitted economic futility evidence becomes sufficiently strong. Positive early results only justify continued testing; they never authorize promotion, live trading, or reuse of touched observations as final validation evidence.

## Non-negotiable V4 preservation boundary

The active V4 protocol is already accumulating accepted evidence. This design therefore does **not** modify V4 strategy logic, risk rules, execution economics, acquisition schedule, entry window, maximum position age, evidence admission, frozen evaluator, or performance blindness.

The research lane must never:

- reveal V4 interim PnL, mean net R, win rate, profit factor, final equity, bootstrap statistics, or trade-by-trade economics;
- change V4 capture length, retry policy, admission rules, or schedule based on outcomes;
- reclassify a failed V4 cohort;
- manually dispatch a run and treat it as V4 economic evidence;
- tune the frozen V4 candidate from V4 interim outcomes;
- merge research evidence into `v4-mainnet-corpus`;
- advance Phase 10 or enable live orders.

V4 remains the control/validation experiment.

### Hard source-time separation while V4 is blind

Until V4 has a terminal immutable one-shot result, research economics may be computed only from source observations that are provably disjoint from **every actual V4 acquisition session interval**, including accepted, rejected, failed, and diagnostic runs. A different candidate digest or a nominal economics-affecting change is not sufficient isolation because a near-clone could still reconstruct the same V4 entry/exit path.

Allowed research sources before the V4 one-shot is terminal are:

1. historical observations whose source timestamps end before the first accepted V4 evidence interval and are already designated research/touched material; or
2. newly recorded research-only observations whose complete source timestamp interval is proven not to intersect the union of actual V4 acquisition intervals.

Every research batch records `source_start_ms` and `source_end_ms`. Before economics are released, the research evaluator must compare that interval against the authoritative registry of V4 acquisition intervals. If any intersection exists, or if the V4 interval registry is incomplete/ambiguous, the batch becomes `REJECTED_CONTAMINATION`; its economics are not eligible for keep/change/kill decisions.

Scheduler drift is handled by actual recorded source intervals, not nominal cron windows. If a later-discovered V4 interval overlaps a previously admitted research batch, that batch is retroactively marked contaminated for research-decision purposes and descendants inherit the contamination/touched interval. It is never eligible for clean validation evidence.

This is intentionally conservative. Research speed comes from fast evaluation of safe research data and parallel challenger work, not by using V4-hidden observations through an alternate workflow.

## Architecture

### 1. Frozen validation lane

The existing V4 acquisition, curator, corpus, and one-shot evaluator remain the sole authoritative path for the current candidate.

Responsibilities:

- collect genuine public Hyperliquid mainnet evidence under the exact V4 protocol;
- admit only clean, complete, flat, provenance-valid cohorts;
- hide tuning-sensitive economic fields until the final immutable one-shot boundary;
- enforce the existing Phase 9 readiness and `CANDIDATE_EDGE` gates;
- keep live trading disabled.

No implementation in this project may import research-lane results into the V4 corpus or evaluator.

### 2. Adaptive research lane

The research lane is a separate paper/shadow evaluation path with explicit candidate identities such as `research-rN-<candidate-name>`.

Responsibilities:

- run distinct research candidates on allowed mainnet-derived observations;
- expose full economics after each completed research batch/day;
- record fills, fees, funding, slippage, latency, net PnL, net R, drawdown, win/loss distribution, market concentration, exit reasons, signal attribution, and operational failures;
- perform precommitted sequential futility checks;
- stop weak research candidates early;
- produce challenger specifications for later clean validation.

The lane is for **research decisions only**. Its positive results are touched evidence and cannot be used as final promotion evidence.

## Candidate identity, lineage, and touched-data inheritance

Every research candidate must persist an immutable manifest containing:

- `candidate_id`;
- `family_id`;
- `parent_candidate_id` (`null` only for a family root);
- ordered `ancestor_candidate_ids`;
- immutable configuration digest;
- exact code revision;
- exact execution/risk configuration;
- first and last observation timestamps;
- all source artifact/provenance identifiers;
- all local touched intervals;
- inherited union of ancestor touched intervals;
- all performance reports used to make a keep/change/kill decision.

A child candidate must reference an existing parent in the same `family_id`. Its effective touched set is the normalized union of its own touched intervals plus every ancestor's effective touched set. A candidate manifest whose parent/ancestor chain is missing, cyclic, cross-family, or digest-inconsistent is invalid and fails closed.

Any economics-affecting change creates a new `candidate_id` with the prior candidate as parent when that prior candidate informed the change. Renaming, copying, or changing a digest never resets touched history.

Once a candidate or its designer has used an observation for research, that observation is permanently **touched** for that candidate family lineage.

## Clean validation cutover

A challenger selected from research must be frozen with a new immutable candidate identity and freeze timestamp before any future economic validation claim.

The authoritative validation start must satisfy all of the following:

- it is later than the challenger freeze timestamp;
- it is later than the end of every effective inherited touched interval;
- it begins after a **6-hour embargo** following the latest effective touched interval, matching the project's existing split-embargo discipline;
- its source observations do not overlap any touched interval inherited by the candidate family;
- the frozen challenger code/config digest is unchanged for the entire validation claim.

This prevents a strategy from being tuned on an interval and then claiming that same or immediately adjacent interval as untouched evidence.

## Frozen V4 outputs remain opaque

Research tooling may read operational/provenance health exposed by V4, but it must not compute or reconstruct hidden V4 economics. Research jobs must not consume V4 economic artifacts or hidden journal/dataset fields for tuning-sensitive reporting.

Before the V4 one-shot is terminal, the hard source-time separation above is the enforceable non-reconstructability boundary; candidate distinctness alone is not accepted as sufficient isolation.

## Fast-failure model

Research decisions happen after every completed research batch/day, but not every decision is economic.

### Immediate operational rejection

A candidate/run may be rejected immediately, including on day one, for any of the following:

- incomplete or gapped source data;
- accounting or reconciliation failure;
- invalid fills or impossible execution state;
- stale-data trading;
- stop/risk invariant violation;
- unbounded or malformed position sizing;
- unexpected live-order path;
- materially unrealistic execution assumptions;
- corrupted candidate/config provenance;
- source-time overlap with V4 while the V4 performance-blind boundary is active.

Operational rejection does not require a minimum trade count.

### Economic futility rejection

Economic rejection must not be based on an arbitrary sequence of daily PnL peeks. The research lane uses a **precommitted Bayesian sequential futility rule** for triage only.

For each research candidate:

- primary quantity: mean **net R per closed trade**, after fees, funding, slippage, and simulated execution costs;
- minimum sample before an economic futility decision: **20 closed trades**;
- likelihood: trade-level net R values are modeled as `StudentT(nu=5, loc=mu, scale=sigma)`;
- prior for mean expectancy: `mu ~ Normal(0, 0.5)` in R units;
- prior for dispersion: `sigma ~ HalfNormal(1.0)` in R units;
- posterior computation must be deterministic for the same ordered input observations, including a fixed sampler seed and fixed convergence settings if sampling is used;
- rejection condition: after at least 20 closed trades, stop the candidate when `P(mu > 0 | observations) < 0.05`;
- severe-risk override: the candidate may stop sooner when an existing configured hard independent-risk lockout is violated; no new discretionary drawdown threshold is introduced by this design;
- once economically rejected, the candidate ID is terminal and cannot be resumed by selectively discarding losing observations.

The Bayesian sequential rule is chosen for the research lane because repeated posterior updates are part of the declared procedure. It is **not** the statistical method used for final promotion; the existing untouched Phase 9 bootstrap/walk-forward policy remains authoritative for promotion.

### Positive early results and research-promising threshold

Positive early results never promote a candidate.

A candidate becomes `RESEARCH_PROMISING` only when all of the following are true:

- at least **40 closed research trades**;
- at least **7 distinct UTC research days** containing a closed trade;
- `P(mu > 0 | observations) >= 0.80` under the same precommitted research model;
- no unresolved operational integrity or contamination failure;
- no hard independent-risk lockout violation;
- complete execution-cost accounting for the candidate's research observations.

`RESEARCH_PROMISING` only authorizes creation of a frozen challenger specification and future clean-validation cutover. It does not authorize Phase 10, live orders, capital deployment, or an edge claim.

A candidate that remains between the futility and research-promising boundaries stays `RESEARCHING` and continues collecting research evidence.

## Daily research checkpoints

The research lane produces one compact report after each completed UTC research day containing:

- closed trades and cumulative closed trades;
- net PnL and mean net R;
- cost decomposition: fees, funding, spread/slippage, latency impact where measurable;
- drawdown and planned-risk utilization;
- long/short and market concentration;
- stop, opposite-thesis, expiry, reduction, and health-exit counts;
- candidate posterior state: `INSUFFICIENT_TRADES`, `CONTINUE`, `RESEARCH_PROMISING`, or `REJECT_FUTILITY`;
- operational/contamination health state;
- exact candidate/code/data provenance.

Human-readable milestones are day 1, day 3, day 7, day 14, and day 30, but the system evaluates after every completed research day. Economic rejection is trade-count-aware rather than assuming that one calendar day always contains enough information.

## Challenger lifecycle

A research candidate moves through these states:

1. `DRAFT` — configuration exists but no observations consumed.
2. `RESEARCHING` — touched evidence is accumulating and daily economics are visible.
3. `REJECTED_OPERATIONAL` — terminal due to integrity/safety/execution failure.
4. `REJECTED_CONTAMINATION` — batch/candidate evidence is unusable because source-time isolation cannot be proven.
5. `REJECTED_FUTILITY` — terminal due to the precommitted sequential economic rule.
6. `RESEARCH_PROMISING` — the exact threshold above is satisfied; this is not an economic promotion claim.
7. `FROZEN_CHALLENGER` — immutable code/config/cutover timestamp established.
8. `VALIDATING` — future untouched evidence is accumulated under a distinct validation protocol.
9. `VALIDATED_EDGE` or `NO_EDGE` — only an untouched promotion evaluator may assign these terminal economic outcomes.

No state transition from `RESEARCHING` or `RESEARCH_PROMISING` may enable live orders.

## Candidate changes and versioning

Any change that can affect trading economics creates a new research candidate ID, including changes to:

- signal logic or thresholds;
- feature construction;
- market selection/ranking;
- entry/exit behavior;
- stop/invalidation behavior;
- max holding period;
- position sizing or portfolio risk;
- execution assumptions;
- fee/funding/slippage models.

Infrastructure-only correctness fixes may retain a candidate identity only when they provably do not change trading decisions or economics. The change and rationale must be recorded.

## Relationship to Phase 10

This research lane is the foundation for later champion/challenger work, but it does not bypass Phase 9.

If V4 reaches `CANDIDATE_EDGE`, it may become the initial champion according to the existing promotion process. Research challengers can then compete against it offline/shadow, but only a separately frozen challenger with untouched evidence may replace the champion.

If V4 ultimately fails its one-shot evaluation, the research lane should already contain diagnostics and alternative candidates, reducing the time required to choose the next candidate. The failed V4 result remains historical evidence and is not rewritten.

## Safety invariants

- Hyperliquid mainnet observation only for genuine evidence.
- Paper/shadow execution only in both lanes at this stage.
- Live orders remain disabled.
- Strategy code cannot size positions or bypass independent risk.
- Stops remain mandatory.
- No averaging down or martingale behavior.
- No result-conditioned retries that discard bad observations.
- No touched research observation can become untouched validation evidence for the candidate lineage it helped design.
- A positive research result is never sufficient for capital deployment.

## Failure handling

The research lane must fail closed when source integrity, accounting, configuration identity, lineage, source-time isolation, or execution provenance cannot be verified. Failed batches remain diagnostic and are never silently removed from a candidate's research history.

A transport or infrastructure failure can be rerun only as a new explicitly identified research batch; the failed batch remains recorded. Economic losses are not a valid retry reason.

## Testing requirements

Implementation must include automated tests proving at minimum:

1. research artifacts cannot mutate or be admitted to `v4-mainnet-corpus`;
2. V4 hidden economic fields are not read or reconstructed by research jobs;
3. research economics are blocked for any source interval overlapping an actual V4 acquisition interval while V4 is blind;
4. scheduler drift is handled by recorded intervals rather than nominal cron times;
5. candidate/config changes produce new immutable candidate identities;
6. parent/family lineage is persisted, acyclic, same-family, and machine-verifiable;
7. descendant candidates inherit the union of ancestor touched intervals;
8. touched periods are rejected from later clean validation and the 6-hour cutover embargo is enforced;
9. economic futility cannot fire before 20 closed trades;
10. the declared posterior futility rule is deterministic for the same ordered observations;
11. `RESEARCH_PROMISING` cannot occur before 40 trades and 7 closed-trade days;
12. rejected candidates cannot be resumed by deleting observations;
13. positive early results never trigger promotion or live activation;
14. operational/contamination failures can reject immediately and remain auditable;
15. all research workflows keep `live_orders=false`.

## Observability

The existing evidence dashboard remains the authoritative V4 validation tracker.

A separate research status surface shows research candidates and daily results clearly labeled **TOUCHED / NON-PROMOTIONAL**. The research dashboard must never merge its metrics with V4 validation counts or present research profitability as verified economic edge.

## Rollout order

Implementation proceeds in this order:

1. research candidate/provenance contract, lineage validation, and touched-data registry;
2. V4 acquisition-interval registry and hard overlap guard;
3. offline/daily research evaluator with full economics on allowed source periods;
4. sequential futility engine and terminal candidate states;
5. research dashboard/reporting;
6. scheduled/replay research runner isolated from V4 workflows;
7. challenger freeze/cutover contract with inherited touched-period and 6-hour embargo enforcement;
8. integration tests proving V4 isolation and no live-order path.

V4 acquisition continues unchanged throughout implementation.

## Success criteria

The architecture is successful when the project can:

- discover an operationally broken candidate on the first research day and reject it immediately;
- reject a statistically implausible candidate as soon as the precommitted futility boundary is met rather than waiting for a fixed 30-day window;
- continue promising candidates without calling them proven;
- iterate on challengers using fully visible touched research evidence that cannot reconstruct V4-hidden outcomes;
- carry touched history through every descendant candidate;
- freeze a selected challenger and begin a genuinely untouched future validation period only after the inherited touched-data embargo;
- preserve the integrity and performance blindness of the already-running V4 experiment;
- keep live trading disabled until the existing promotion gates are legitimately satisfied.

## Explicit non-goals

This design does not:

- shorten or alter the current V4 one-shot requirements;
- expose current V4 interim profitability;
- authorize real-money trading;
- define a shortcut around untouched OOS validation;
- allow strategy tuning from hidden V4 outcomes;
- treat one profitable day as proof of an edge.
