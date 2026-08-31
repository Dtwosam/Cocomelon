# Dual-Lane Sequential Research and Frozen Validation Design

**Date:** 2026-08-31  
**Status:** design approved in principle; pending written-spec review before implementation  
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
- **Research lane:** a separate adaptive paper/shadow environment exposes full daily economics for distinct research candidates, supports precommitted sequential futility checks, and allows rapid challenger iteration.

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

Until V4 has a terminal immutable one-shot result, the research lane must not run an economically identical V4 clone for performance inspection. Research candidates must have a distinct candidate/configuration digest and at least one predeclared economics-affecting difference from frozen V4. This prevents an alternate workflow from reconstructing the hidden V4 result indirectly.

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

- run distinct research candidates on genuine mainnet-derived observations;
- expose full economics after each completed research batch/day;
- record fills, fees, funding, slippage, latency, net PnL, net R, drawdown, win/loss distribution, market concentration, exit reasons, signal attribution, and operational failures;
- perform precommitted sequential futility checks;
- stop weak research candidates early;
- produce challenger specifications for later clean validation.

The lane is for **research decisions only**. Its positive results are touched evidence and cannot be used as final promotion evidence.

## Data and contamination rules

### Research observations are permanently tagged as touched

Every research candidate must persist:

- candidate ID and immutable configuration digest;
- first observation timestamp;
- last observation timestamp;
- exact code revision;
- exact execution/risk configuration;
- all source artifact/provenance identifiers;
- the set of markets and periods used for research;
- all performance reports used to make a keep/change/kill decision.

Once a candidate or its designer has used an observation for research, that observation is **touched** for that candidate family.

### Clean validation starts after candidate freeze

A challenger that is selected from research must be frozen with a new immutable candidate identity before any future economic validation claim. Its authoritative OOS validation dataset begins only after the candidate freeze/cutover timestamp and excludes the observations that informed its design.

This prevents a strategy from being tuned on an interval and then claiming that same interval as untouched evidence.

### Frozen V4 outputs remain opaque

Research tooling may read operational/provenance health exposed by V4, but it must not compute or reconstruct hidden V4 economics. Research jobs must not consume V4 economic artifacts or hidden journal/dataset fields for tuning-sensitive reporting.

Research candidates must be explicitly distinct from the frozen V4 identity as defined above.

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
- corrupted candidate/config provenance.

Operational rejection does not require a minimum trade count.

### Economic futility rejection

Economic rejection must not be based on an arbitrary sequence of daily PnL peeks. The research lane will use a **precommitted Bayesian sequential futility rule** for triage only.

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
- no unresolved operational integrity failure;
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
- operational health state;
- exact candidate/code/data provenance.

Human-readable milestones are day 1, day 3, day 7, day 14, and day 30, but the system evaluates after every completed research day. Economic rejection is trade-count-aware rather than assuming that one calendar day always contains enough information.

## Challenger lifecycle

A research candidate moves through these states:

1. `DRAFT` — configuration exists but no observations consumed.
2. `RESEARCHING` — touched evidence is accumulating and daily economics are visible.
3. `REJECTED_OPERATIONAL` — terminal due to integrity/safety/execution failure.
4. `REJECTED_FUTILITY` — terminal due to the precommitted sequential economic rule.
5. `RESEARCH_PROMISING` — the exact threshold above is satisfied; this is not an economic promotion claim.
6. `FROZEN_CHALLENGER` — immutable code/config/cutover timestamp established.
7. `VALIDATING` — future untouched evidence is accumulated under a distinct validation protocol.
8. `VALIDATED_EDGE` or `NO_EDGE` — only an untouched promotion evaluator may assign these terminal economic outcomes.

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
- No touched research observation can become untouched validation evidence for the candidate it helped design.
- A positive research result is never sufficient for capital deployment.

## Failure handling

The research lane must fail closed when source integrity, accounting, configuration identity, or execution provenance cannot be verified. Failed batches remain diagnostic and are never silently removed from a candidate's research history.

A transport or infrastructure failure can be rerun only as a new explicitly identified research batch; the failed batch remains recorded. Economic losses are not a valid retry reason.

## Testing requirements

Implementation must include automated tests proving at minimum:

1. research artifacts cannot mutate or be admitted to `v4-mainnet-corpus`;
2. V4 hidden economic fields are not read or reconstructed by research jobs;
3. an economically identical V4 clone is blocked from the research lane until the V4 one-shot is terminal;
4. candidate/config changes produce new immutable candidate identities;
5. touched periods are persisted and rejected from later clean validation for that candidate family;
6. economic futility cannot fire before 20 closed trades;
7. the declared posterior futility rule is deterministic for the same ordered observations;
8. `RESEARCH_PROMISING` cannot occur before 40 trades and 7 closed-trade days;
9. rejected candidates cannot be resumed by deleting observations;
10. positive early results never trigger promotion or live activation;
11. operational failures can reject immediately and remain auditable;
12. all research workflows keep `live_orders=false`.

## Observability

The existing evidence dashboard remains the authoritative V4 validation tracker.

A separate research status surface should show research candidates and daily results clearly labeled **TOUCHED / NON-PROMOTIONAL**. The research dashboard must never merge its metrics with V4 validation counts or present research profitability as verified economic edge.

## Rollout order

Implementation should proceed in this order:

1. research candidate/provenance contract and touched-data registry;
2. offline/daily research evaluator with full economics;
3. sequential futility engine and terminal candidate states;
4. research dashboard/reporting;
5. scheduled research runner isolated from V4 workflows;
6. challenger freeze/cutover contract for future untouched validation;
7. integration tests proving V4 isolation and no live-order path.

V4 acquisition continues unchanged throughout implementation.

## Success criteria

The architecture is successful when the project can:

- discover an operationally broken candidate on the first research day and reject it immediately;
- reject a statistically implausible candidate as soon as the precommitted futility boundary is met rather than waiting for a fixed 30-day window;
- continue promising candidates without calling them proven;
- iterate on challengers using fully visible touched research evidence;
- freeze a selected challenger and begin a genuinely untouched future validation period;
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
