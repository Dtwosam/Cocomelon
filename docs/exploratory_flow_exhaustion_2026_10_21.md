# New economic hypothesis and frozen exploratory PAPER experiment — October 21, 2026

> Superseded owner decision2026-10-21: **V1 SHELVED_OPERATIONALLY_DATA_BLOCKED**.
> No paid-source evaluation, collector or infrastructure rescue remains assigned.
> Preserve this historical report and the immutable V1 protocol; economics not
> disproved. [Final free-data decision](free_data_economic_edge_2026_10_21.md).

**NO NEW ECONOMIC PROGRESS. No new edge or prospective profit is established.**
The owner's current request explicitly permits an economically reasoned, unproven
PAPER trial. Profitability, 72-hour maturity and sufficient samples are validation
requirements, not prerequisites for beginning exploratory testing. Earlier
historical-admission wording is superseded only for this distinction; old rejected
experiments, source failures and promotion gates remain intact.

## A–B. What actual winners and losers teach

All 321 available canonical original closes were reopened read-only. There were
91 winners (+$1,517.707747 booked net), including 43 LONG and 48 SHORT, against
230 losers (-$1,866.437748), totaling -$348.730001. Winners captured substantial
actual-fill movement; 78 winners also exited by MARK_STOP_TRIGGERED, so that exit
label alone is not a failed-thesis diagnosis. 221 losses were negative before
fees; refunding every recorded fee still leaves -$99.905098. Banning LONGs,
removing stops or optimizing fee savings cannot follow from these descriptions.

The selected early path subset also contains favorable excursions subsequently
surrendered, but missing executable paths prevent causal alternative-exit claims.
Funding is incomplete for 117 trades: missing funding cash is UNKNOWN. The 321
canonical closes differ from newer heartbeat counters. See the full
[winning/losing evidence and three participant explanations](../research/experiments/flow-exhaustion-v1/economic-lessons.md),
which distinguishes fresh read-only arithmetic from inherited artifact custody.
No historical parameter grid, winner subset or ideal exit trained this policy.

## C. Three explanations and the selected mechanism

1. Temporary immediacy demand displaces prices while liquidity suppliers bear
   inventory risk; subsequent visible liquidity recovery may precede reversal.
2. Durable informed or allocation demand repeatedly consumes liquidity and
   establishes a new price level; this could explain sustained winners and why
   indiscriminate fading loses.
3. Risk-constrained leveraged holders reduce positions, amplifying pressure while
   liquidity withdraws; recovery may occur only after inventory adjustment ends.

Choose the first for a new observable trial. WHO: immediacy-seeking buyers/sellers
and competing liquidity suppliers. WHY: takers pay price concessions for urgent
inventory changes; limited risk-bearing capacity can permit temporary impact.
WHEN: a directional tape burst displaces price but additional pressure fails to
extend it, depth at the affected prices recovers, then opposing flow responds.
WHAT: genuine receipt-ordered signed executions and L2 snapshots, ordinary market
eligibility, and timely funding. HOW: fade only after that entire sequence, with
predefined invalidation beyond the observed extreme and target at the pre-burst
price. PROFIT: capture a portion of temporary impact exceeding all execution
costs. FAILURE: demand contains durable information, displayed recovery is fleeting,
or delayed execution and costs consume normalization.

These are conjectures, not observed identities, motives or confirmed historical
causation. The prior temporary-pressure discussion was historical DATA-BLOCKED,
not a failed return test. This policy requires executed flow and *pre-entry visible
depth recovery at the same prices*, distinguishing it from rejected static book
imbalance, candle reclaim, delayed-repricing, rank-filter and fee-saving rules.
Book snapshots cannot identify the same maker replenishing, hidden liquidity,
cancellations, TWAPs or forced liquidations. No such causal claim is made.

## D. Exact policy

The immutable [complete trial protocol](../research/experiments/flow-exhaustion-v1/protocol.json)
and its [SHA256](../research/experiments/flow-exhaustion-v1/protocol.sha256) are
binding. Initial values reflect an economic scale to test, not historical tuning.

| Component | Frozen rule |
| --- | --- |
| Assets | All eligible native Hyperliquid perps; preserve existing active/volume/OI/margin/spread/depth/freshness and risk gates. No favorite-coin list or HIP-3 fee assumption. |
| Selection | Evaluate all observed eligible markets; qualified candidates use canonical-key lexical queue, first passing independent risk/venue constraints; at most one IOC attempt per epoch. Retain all capacity-blocked, risk-rejected and NO_TRADE decisions. This queue is deterministic, not a fitted alpha rank. |
| Schedule | Evaluate every 30s UTC using ten prior one-minute tape bins, then 60s pressure and 30s confirmation. Inputs available by decision time only; never sort original receipt regressions away. |
| Pressure | At least 20 trades; notional >=3x prior mean minute; >=70% one aggressor side; signed anchor-to-last-pressure-mid displacement >=40bp. |
| Absorption proxy | All confirmation mids remain within 5bp beyond the pressure extreme. Visible depth in a fixed 10bp support band at the extreme is >=1.5x at the last book before the measured response window AND latest book; original-direction executions inside that band before the response window total >=initial band depth. This is observed recovery, not order-level proof. |
| Opposing response | Latest mid reverses >=10bp from extreme; last 10s have >=5 trades and >=55% opposing notional. |
| Direction | LONG after qualifying sell pressure; SHORT after qualifying buy pressure. Otherwise NO_TRADE with explicit reasons. |
| Stop/target | Stop 10bp beyond pressure extreme mid; target pre-pressure anchor mid. Stop distance <=100bp; target room >=2x stop distance AND >=2x cost reserve. No averaging, trailing or breakeven parameter changes. |
| Costs | Reserve 9bp roundtrip base taker fees + full current spread +10bp slippage +two hours of absolute current-hour funding. This is a hurdle, not an expected return. Book actual delayed IOC fills, fees and funding; never subtract fill-embedded spread/slippage twice. |
| Size | Risk including cost reserve <=0.10% equity; notional <=25% equity; <=5% observed contra depth within25bp. Round down to venue precision. Existing independent risk/margin approvals may reduce/reject. |
| Entries | One open position and one pending opening trial-wide; at most six actual openings/UTC day; same-market 1h cooldown. Entry expires2s after decision, no chase. |
| Exits | Protective reduce-only stop first, target second, 30 min maximum hold third. Keep managing partial fills and failed exits until genuinely filled; stops are not guaranteed prices. |
| Disable | Source/clock/book/funding/state/health uncertainty blocks new exposure; preserve exits. Three losing trades trigger1h cooldown. At $9,950 marked equity, permanently disable further v1 entries, preserving positions/losses. Existing 1% daily and 3% weekly guards remain. |

Original received timestamps must be nondecreasing globally; exchange timestamps
nondecreasing within each kind/market stream. Both timestamps on the latest book
must be <=1s old; source-to-receipt lag <=2s, inter-book gap <=2s. Completeness and
eligibility are external authenticated obligations; a caller boolean, source label
or locally generated digest does not prove a clean venue feed. No candle-derived
microstructure or missing-funding zero substitution is permitted.

For scale only: a 40bp favorable move on $1,000 notional is $4 gross before $0.90
base fees, actual spread/slippage and funding. That arithmetic is neither an
expectancy estimate nor an observed return. The 3x/70%/1.5x/time thresholds are
untested initial hypotheses and may produce few entries; zero entries is not
profit. The response window deliberately trades confirmation for adverse-selection
risk; this tradeoff must be measured without retuning the running experiment.

## E. Independent experiment and learning contract

Reserve two separate simulated $10,000 account ledgers: this candidate and a
capital-matched NO_TRADE control with zero cash yield. Neither borrows custody,
margin, risk or state from the ordinary account. Use the existing paper execution
adapter's 250ms latency, fresh books, visible-depth partial fills/no-fills, taker
fees and bounded IOC slippage, plus actual funding/oracle reconciliation. Record
all decisions, blocked/no-fill/partial orders, fills, reasons, current stop/target,
open positions, cash/margin and every event-time whole-account equity observation.

Before prospective outputs, an immutable activation receipt must bind the code
SHA, protocol SHA, account IDs, isolated roots, source lineage, fee/risk settings,
resource lease and a future first-entry boundary at least six hours after release.
Warmup precedes that boundary. Never backdate or move a boundary after outcomes.

Review all outcomes after14 calendar days. At least40 nonoverlapping lifecycle
components, five markets, ten LONG and ten SHORT components, and ten components
in each fixed chronological third are necessary for this symmetric trial. If
insufficient, permit exactly one unchanged extension to28 days; then INCONCLUSIVE
if still insufficient. At least72 hours complete authenticated original prospective
source, positive absolute after-all-cost whole-account equity above $10,000,
positive matched-control difference, positive net in every chronological third,
maximum peak-to-trough drawdown <=0.5% (separate from the fixed $9,950 entry-disable floor),
and a positive one-sided95% lower bootstrap bound on component net return are
necessary before a validated-edge claim. Use 5,000 resamples / seed 1258 of fixed 48-hour calendar clusters anchored at the
entry boundary, including zero-trade clusters (seven clusters at 14 days / fourteen
at28 days); the one-sided5th percentile of resampled component-return means must
be positive. Any empty resample or UNKNOWN component prevents inference. Component
return is after-all-cost realized cash divided by equity immediately before its
first fill. Nonoverlap does not prove independence, and dependence can persist
beyond 48 hours. Chronological thirds use equal elapsed time and marked whole-account
equity changes; component first-fill assignment is only for counts/attribution.
No extension/reset rescues sufficient-sample economic/source failure. Report gross/cost/funding/net, open equity, drawdown,
profit factor, risk-adjusted returns and side/market/winner concentration. Winner
removal is sensitivity, not alone a disproof of a positively skewed mechanism.
Existing independent OOS/walk-forward/shadow promotion gates still apply.

Do not change parameters after a few losses. At the fixed review, classify signal
failure (no normalization), execution failure (normalization not captured), cost
failure (captured move insufficient), or source-inconclusive. Retain/reject based
on the entire frozen account; any revised hypothesis gets a separately frozen,
independent forward test with all unsuccessful evidence preserved.

## F. Implementation and verification

A pure research-only module implements event-derived entry decisions, conservative
quantity, and stop/target/time exit priority. Synthetic fixtures test both sides,
missing mechanism legs and adversarial source/cost inputs; they are not PAPER
trades. There is no production strategy import, runner, trading workflow, account creation,
ordinary-worker change or PR #1392 activation in this change. Exact verification
results and immutable CI heads are recorded in STATUS and the PR; no CI success
is economic evidence.

## G–H. Activation and actual results

**BLOCKED FOR OPERATIONAL ISOLATION. Not running.** The current user authorizes a
safe trial, but the repository has no reviewed standalone arbitrary-policy
launcher with a separately durable NO_TRADE control. Existing paired machinery
is a frozen same-strategy admission-filter experiment embedded in ordinary-worker
custody, and its failed ledgers must not be reused. Reusing continuous-paper.yml
would implicate ordinary account restore, handoff, permissions and Issue #469.

A separate in-process quota does not prove shared-IP headroom; Issue #469 explicitly
blocks another three-market REST observer for insufficient peak headroom. Its
current failed original-clock/L2 source cannot certify an inherited trial feed.
These are operational blockers, not proof-profit-first admission requirements.
A new independently recorded source could qualify prospectively. No hosting,
collector or general framework is built to bypass the blocker. PR #1392 remains
open/inactive subject to its separate account/order/protection safety restrictions.

Candidate prospective observations/orders/fills: **0**. Gross PnL, costs, funding,
net PnL and equity: **NOT AVAILABLE**, not zero-profit results. The $10,000/$10,000
figures are frozen future allocations, not activated or real funded accounts.

Authenticated ordinary-account context at 2026-10-21 09:33:13.495UTC: worker
39572026775/head528c10e071c808dd8c305822a2a378ad17e7bb9f, predecessor 39543863546,
three open positions, equity $9,700.904543, whole-account net -$299.095457,
fees $258.140202, signed booked funding -$3.162855 and 332 heartbeat closes. The actual
paper job is in_progress after exact predecessor restore. Source remains
nonqualifying. This is point-in-time operational telemetry, separate from the 321
canonical historical trades and from the nonexistent new account. Refresh Issue #469
before quoting current values. See [authenticated aggregate snapshot](../research/experiments/flow-exhaustion-v1/evidence-snapshot.json).

## I. Next economic decision

The policy is now concrete enough to test without requiring prior profits. Safely
establish a narrowly scoped independent launcher/source/control custody and resource
proof before activation; do not dispatch or duplicate the ordinary trader. After
that, run unchanged until the fixed review and let genuine after-cost account
outcomes retain, revise or reject the mechanism. Today the justified decision is
**prepare for launch, no activation or profitable-edge claim**. LIVE remains disabled.
