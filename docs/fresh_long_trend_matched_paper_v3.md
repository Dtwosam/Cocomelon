# Fresh LONG-trend-only matched PAPER research v3

## Why this is a new experiment

The authenticated completed original worker #38737278661 published 246
closed trades at a negative booked after-cost result (approximately
−$156.08), with 96 historical LONG trend closes totaling −$151.64 net.
Those historical losers are DISCOVERY, not a valid forward matched-account
candidate. The old both-side trend v1/v2 paired accounts have torn signed
witness/SQLite checkpoints and **MUST NOT BE REPAIRED OR REUSED**. The frozen
SHORT rank and quarter-R cost gates also failed their strict screens.

This v3 candidate is a deliberately narrow economic hypothesis: could
**not opening LONG trend-led trades** (while retaining **SHORT trend
and ALL other strategies**) improve the net-after-fees/funding and marked
whole-account path of an independently simulated risk/capital-matched
paper portfolio?

## Fixed before any eligible opening

- Trial ID: `fresh-long-trend-admission-matched-paper-v3`
- Fixed freeze: **2026-10-16 00:00 UTC**
- Required embargo: **six hours**
- First eligible opening: **2026-10-16 06:00 UTC**
- Frozen dimensions: `("lead_strategy", "direction")`
- Frozen blocked values: `("trend", "long")`
- Other strategies and directions: **unchanged**
- Minimum observation horizon: **72 hours**, not a statistical sufficiency
  certificate; then separately require meaningful trade counts, source/venue
  continuity, independent marked equity/fee/funding checks, regime/diversity,
  proper return distribution and out-of-sample/account-level review.
- Historical source pin (DISCOVERY only): original worker #38737278661,
  scoreboard artifact 11982185958, SHA-256
  `37150b47e701c3ab8c1af23808254f305b443862c90c040b0a49fe002a9a1d93`.
- Original v1/v2 accounts and prior source-gap records: **excluded**.

## Genuine L2 exchange-time admission

Original PAPER `ReplayRecord.available_at_ms` is the received-time clock;
it is **not** proof that the underlying exchange L2 book was fresh. Before
the independent new baseline/challenger accounts are constructed, the v3
source audit now checks every recorded `l2_book` in original warmup **and**
forward observations. Each book must carry an actual exchange timestamp,
which may lag its original received timestamp by **at most 15,000 ms** or
lead it by **at most 1,000 ms** for bounded clock skew. For each market,
original L2 exchange timestamps must never decrease in received order.
Same-millisecond exchange timestamps are allowed; the original ordering
is not rearranged and source clocks are never overwritten or clamped.

The local report includes per-market maximum observed L2 source lag,
maximum clock skew, and exact original L2 records verified. Every
violation **fails before creation of either paired PAPER account**,
even where the manifest claims 72 hours of otherwise dense L2 receives.
The 15-second bound is conservative source-freshness screening, not a
claim that the venue feed is independently authenticated. Gaps, unstable
receive clocks, torn v1/v2 evidence and missing original 72-hour market
coverage continue to fail closed. Strategy, fee, funding, mark and risk
settings are unchanged; LIVE and automatic promotion remain disabled.

## The implemented one-shot offline research entry point

`cocomelon.research.fresh_long_trend_forward_pair.run_digest_pinned_long_trend_matched_paper`

Requires a caller-supplied `ReplayManifest`, its exact independently
obtained manifest ID, the associated original segment folder, the normal
`BaselineReplayConfig`, a fixed selected market cohort, and a completely
new empty research-account directory. It first rehashes/checks all recorded
segments through the existing pinned microstructure loader; ONLY THEN
creates two separate `PaperExecutionAdapter`/fact stores via the
`LossContextPairedPortfolioShadow` engine. Original source records, stop
management, risk rules, strategy decisions and fee/funding model are
identical across both independent accounts, with only the new candidate's
predeclared LONG trend admission predicate different.

The comparison reports actual independent simulated paper account equity,
realized net, drawdown and admitted/blocked opens; no naive historical
skip-cash credit. Every execution is paper-only. Missing/malformed source,
late-start manifest, duplicate market selection and nonempty/reused account
directories refuse to create or reset the pair.

**Current status:** The future frozen start has NOT occurred when this
code was authored; there are ZERO qualifying original prospective market
records, no new live v3 worker campaign and no certified v3 outcome yet.
The one-shot runner does not preserve a safe incremental signed checkpoint,
authenticate its GitHub/venue archive by itself, ensure every received
exchange event was captured, or certify inter-worker market gap closure.
Therefore its source and signed-account certification booleans ALWAYS
remain false and no output grants strategy admission, promotion authority
or LIVE execution. This is a runnable independent new-paper research
foundation, not a release of the failing old research or a trading change.

Next implementation step before any promotion: independently bind the
post-embargo original GitHub source archive, original first-seen decision
lineage and exact manifest identity; implement full original market-gap
continuity and independent terminal account sign/review across a genuine
72-hour+ forward horizon, without time-selecting winners or rewriting
historical source.

## October 15: new local terminal whole-account parity guard

The one-shot engine now **checkpoints both PAPER execution adapters**
and signs a *local self-digest* over the checkpoint JSON only after the
same exact source-record stream has been consumed by both lanes. Once
both SQLite stores have CLOSED, a separate read-only module reopens
each database with SQLite \`mode=ro&immutable=1\`, requires SQLite
integrity and exact recomputed account \`state_id\`, original on-disk
paired signed checkpoint parity, materialized positions and rolling
equity peaks, and checks actual fill fees plus actual accrued funding
cash against all original ledger rows. It independently reconciles
cash = initial cash + realized gross − fees + funding, whole marked
equity = cash + unrealized mark, and the original reported drawdown,
open positions, realized and marked net against each real account.
Both lanes must use the EXACT same initial capital. Any mismatch throws
a diagnostic failure with **no economic verdict**.

This is a **strictly local** cash-and-state integrity guard: neither a
self-hash nor a read-only SQLite equality check authenticates GitHub,
the venue, the market-data gap stream, external signing keys, original
rank history or handoffs across real workers. Even if the trial shows
a mathematically positive result, the module sets
\`72h_forward_profitability_certified=false\`,
\`study_promotable=false\` and \`execution_authority=false\`.
A positive relative challenger advantage with both accounts losing
is NOT a positive absolute strategy edge. Keep old torn v1/v2 sources
quarantined and preserve all new failure snapshots.


## Original L2 and gap admission — before allocating the two PAPER accounts

The v3 source preflight now demands one actual captured **post-embargo
`l2_book` observation for EVERY selected market**, with the first L2
within five minutes of the fixed six-hour embargo boundary and no more
than five minutes between that market's consecutive received L2 records.
Any source DATA_GAP record across replay warmup or forward records, or
ANY declared source gap in the pinned replay manifest, rejects the whole
candidate study **before** either paper account is created. The preflight
does not waive gaps that occurred before the embargo but could taint the
warmup or original first-seen entry decisions.

The local 72-hour observation age is measured from **the earliest final L2
timestamp across all selected markets**, not from a manifest's nominal end,
a funding/candle/context update after books went stale, or a gap record.
Terminal account/funding processing still occurs at the actual LAST
received replay timestamp so the equity mark and finalization clock do
not regress.

A local SHA-256 over the exact canonical replayed record sequence, selected
market first/last book times, observed L2 counts and gap policy now
accompany the economic report. These facts are **LOCAL replay checks**,
not a cryptographic exchange capture guarantee, source-feed completeness
certificate or a new trial promotion path: unrecorded exchange events,
worker handoff source loss and source archive origin remain subject to
independent verification. The 72-hour age alone never admits profitability.


## Original GitHub upload binding — read-only offline v3 runner

New `cocomelon.research.fresh_long_trend_github_origin.run_original_zip_bound_fresh_long_trend_paper` performs an exact offline GitHub worker/source ZIP binding **before** invoking the existing v3 independent paired PAPER replay. Its inputs are original worker-run JSON, jobs JSON and artifact metadata fetched *independently* from GitHub, the original artifact ZIP and the unmodified local microstructure segment directory, the exact precommitted replay manifest and ID, selected markets, risk config and a new empty account root. The archive name is `continuous-paper-v3-microstructure-<run_id>-<run_attempt>`; it must come from `main` `Continuous Mainnet Paper Trader`, have a completed exact run/attempt, completed PAPER job, successful `Run continuous paper trader` step and independently completed `Upload frozen v3 original microstructure source` step.

The uploaded ZIP must have **exactly** `replay-manifest.json` (`{manifest_id,manifest}`) and one `microstructure/<segment.relative_path>` for every pinned original `SourceSegment`, no extra/duplicate/unsafe members. Original ZIP whole SHA-256 must match its GitHub published digest, run/artifact IDs/head SHA/branch must agree, and every original ZIP segment must byte-hash identically to both the local unmodified replay segment and the pinned `ReplayManifest`. The ZIP and local recording are read-only. Archive upload must chronologically follow the recorded forward source timestamps.

**Not yet available:** the continuous PAPER worker does not produce this exact v3 source artifact or its upload step yet, and the current original live worker head predates this research. This code establishes a strict **future collector contract**, not a claim of real post–October 16 06:00 UTC capture. Supplied JSON metadata can itself be forged unless independently retrieved from GitHub; the wrapper always reports independent metadata/venue authentication, signed cross-worker continuity, positive account profit and promotion as FALSE. Even a locally valid ZIP must still pass the separate recorded-gap/L2 gate and independent after-cost accounting, and can never turn LIVE on.


## No retrospective market-cohort cherry-picking

The complete original pinned forward microstructure recording determines the market universe. The caller cannot submit a reduced `selected_markets` containing only favorable observed returns: the source preflight rejects EVERY omitted forward market with a recorded original normalized event (L2, market snapshot or other market-specific event) before constructing either PAPER account. The same no-gap/L2 freshness and original-row SHA constraints apply. This alone cannot prove the recorder captured the entire precommitted market universe; that must be independently verified from its original worker setup and source receipts. No change to frozen LONG trend predicate, ordinary execution or LIVE gates.


## Producer of the required original v3 source artifact

The mainnet PAPER worker now supports `V3_CAPTURE_ORIGINAL_SOURCE=1` **only inside PAPER execution**. It records the exact `ReplayRecord` stream already delivered to the baseline pipeline (including REST-delivered normalized market contexts and witnessed DATA_GAP records), using a bounded non-blocking queue and a background durable writer in `$RUNNER_TEMP/v3-original-capture-<run_id>-<attempt>`. Every original market event, source/venue timestamps, original event key and JSON payload is recorded; it does not synthesize fills or rankings. Any queue loss, writer fault or unclosed worker makes the post-exit source seal fail. The source journal is deliberately **not a trading checkpoint or a 72h multi-worker signed chain**.

Once the normal PAPER successor has been dispatched, the uploader reads an exact complete terminal capture receipt, checks identity against `GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT` and `GITHUB_SHA`, and compacts the original journal to standard `events/` and `gaps/` replay recorder segment files with full byte hashes, exact row counts and a `ReplayManifest`. It declines upload before the prospective post-embargo L2 exists. The upload uses GitHub `actions/upload-artifact` on the directory containing **exactly** `replay-manifest.json` and `microstructure/<segment.relative_path>`, creating the outer original artifact ZIP already expected by the offline origin check in #1262. The repository's ordinary PAPER source strategy, fees, risk and any signed older economic histories are left unchanged.

Each artifact covers **one originating worker only**. Independent source verification still needs to tie GitHub's published original ZIP SHA, run, attempt, head, job upload step to the archived bytes; reconstruct **authenticated** uninterrupted handoffs across many workers; and verify venue coverage, original L2 completeness, full selected cohort, 72h forward matched accounts and absolute net-after-cost profitability. Current negative PAPER PnL is not an edge certificate.


## Original receive clocks are immutable research input

The actual PAPER execution engine may clamp an out-of-order new received
timestamp to its prior clock for safe account processing, including when
restoring an earlier worker's checkpoint. The separate v3 original input
collector is intentionally stricter: it is now offered the **unchanged**
incoming ReplayRecord before any PAPER receive-clock correction, with the
prior PAPER timestamp supplied as an independent bound. It records the
first regressing market/event key and both source/previous timestamps, sets
a permanent original-source failure, and refuses sealing into a publishable
original ZIP. No source-time correction, backdating, event repair or gap
waiver can turn a bad capture into valid forward evidence. An original
receive-clock failure affects research only; PAPER trading continues under
its existing monotonic safety policy. Duplicate event-key handling remains
the original PAPER intake policy, not a proof of full exchange delivery.


## Original worker execution economics are not replay defaults

The sealed v3 `ReplayManifest` now contains the exact original PAPER
worker's immutable `BaselineReplayConfig.config_digest` and explicitly
recorded `execution_config_version`, `fee_schedule_id`, feature/strategy,
risk and replay engine versions, captured before the worker's first
received source event. A deferred seal must NEVER instantiate its own
default `PaperExecutionConfig()` to replace those original economics.

The offline v3 paired research runner checks ALL identities against the
actual intended `BaselineReplayConfig` before looking at source rows or
opening PAPER accounts. A different taker fee, liquidation/risk budget,
IOC slippage or starting cash—even with a conveniently unchanged fee
schedule ID—changes the full canonical configuration digest and is
rejected. Baseline and challenger still use identical PAPER account
economics, but this check does not externally authenticate GitHub metadata
or venue completeness, and a locally consistent v3 replay is still not
a verified 72-hour profitable strategy.


## Receipt order is part of original market-source evidence

The original physical PAPER source worker records a global JSONL consumption
sequence and commits an entire original journal SHA-256 in its terminal
receipt before the sealer runs. The sealer checks that exact writer-thread
SHA against every original journal byte before assigning ordinals; a
retrospectively reordered original journal is rejected even when counts
and timestamps match. This is a LOCAL digest and not an externally signed
venue attestation. Sealing splits normalized events into `events/<date>/<kind>/<market>`
segments. The v3 sealer writes a global `original_receipt_ordinal` (1..N)
onto each original emitted segment row before its segment SHA-256 is
sealed and GitHub uploads the containing ZIP. Generic `canonical_record_order`
sorts equal-millisecond observations by event type/market/key; those
tie-breakers **are not** proof of the original PAPER receipt sequence.

Before v3 constructs new baseline/candidate accounts, a separate read-only
validator re-reads every SHA-pinned segment, verifies a unique contiguous
ordinal for every record, checks source timestamp monotonicity in the actual
original ordinal sequence, and verifies the complete population against
the separately validated source loader. The paper simulation consumes
this reconstructed original order, including equal-timestamp ties.
Missing, duplicated, out-of-range or reordered ordinals fail closed.
No old ordinal-less ZIP can be reconstructed using hindsight sorting and
used as a qualified prospective v3 market source.

This is not proof that every venue event was captured, nor a signed
cross-worker ordering chain. Those independent gates and the 72h
net-after-fee/funding whole-account screen remain mandatory and unproven.


## October 16 — proactive ORIGINAL recorder byte/row budget refusal

The prospective original PAPER collector now shares the source sealer's strict
480 MiB original-journal byte ceiling and 5,000,000-row ceiling. Before each
async fsynced batch, the writer counts the exact canonical original JSONL bytes
and refuses an over-budget batch, marking the run irreversibly nonqualifying.
The untouched PAPER trading pipeline and account continue. Authenticated
operational heartbeats expose only **persisted** source bytes/rows and remaining
archive budget, distinct from pending queue rows; post-handoff terminal bytes
must reconcile with the original journal before source sealing. A missing,
dropped, over-budget or incompletely closed recorder never creates a
qualifying v3 original ZIP. These counters are not proof of original venue
completeness, multi-worker receipt continuity or prospective profitability.
No strategy or risk change and no LIVE authority.

## October 16 — preserve raw-clock anomaly classifications, not false replay time

On authenticated PAPER #38882371037 at 10:03 UTC, the original-v3
recorder was active but already permanently failed source integrity:
10,784 original offers, 3,542 writes, 7,241 drops and 55
raw receive-clock regressions. The existing PAPER record pump may clamp
late-arriving normalized event timestamps for operational continuity; that
clock cannot be reinterpreted as true original first-received research
evidence. The follow-on research-only diagnostic distinguishes raw timestamps
older than the preceding source offer from timestamps older than the
existing PAPER pipeline clock (including a restored predecessor checkpoint).
It reports fixed-vocabulary first failure classification, event kind and
maximum backward delta, without copying event keys, payload or paths into
operational status. Failure remains irreversible for the present worker,
and **no valid missing original source is repaired by these counters**.
Do not replay this worker as a successful v3 economic sample.

## October 16 — original v3 terminal clock diagnostics survive handoff

After a genuine PAPER worker stops, its separate nonqualifying original source
diagnostic now publishes the first fixed-vocabulary event-clock regression
cause, whitelisted event kind, maximum backward milliseconds, and the separate
original-source versus PAPER-clock regression totals **only for a terminal
whose run, attempt, and SHA match the requesting GitHub worker**. Missing
legacy fields remain unavailable; foreign or malformed terminals do not
donate their data. The collector also reports offered rows not yet durably
written or counted dropped. This includes in-flight writes during live status
and becomes a residual on failed close. The failure does not certify or repair
any original venue records, economics, worker continuity or LIVE orders.

## October 16 — original v3 source ZIP binds a declared predecessor (not a certified chain)

Each genuine PAPER worker now passes its GitHub dispatch predecessor run ID
and attempt, if supplied, to the separate original research source recorder.
The pair must be complete, numeric, positive, and must not point at the
current run. A malformed predecessor affects only the research recorder,
never the normal PAPER positions, risk or graceful handoff.

At close, the worker's SHA- and row-reconciled original market-data ZIP now
also contains `source-handoff-receipt.json` naming the current
run/attempt/head, the exact declared predecessor run/attempt (or explicit
nulls), original journal writer SHA, source record count, timestamp window,
and original startup market cohort. Offline GitHub source checking requires
this exact ZIP member and rejects inconsistent worker identity, segment
population/times, omitted L2 source markets, forged source/venue continuity
authority flags and malformed predecessor declarations. The whole GitHub
artifact ZIP digest is still mandatory. Older source ZIPs lacking this
member remain unqualified; do not backfill history.

**Declaration is not independent handoff proof.** GitHub workflow input,
predecessor resume ZIP, state IDs, gap witness, signed account continuity,
72-hour actual common-market observation and both absolute-positive
after-cost PAPER accounts must be separately authenticated. The
fixed LONG-trend-only research rule, live PAPER positions, sizing,
execution costs and LIVE-disabled boundary are unchanged.

## October 16 — independent negative preflight for ordered v3 worker source links

The new read-only `fresh_long_trend_source_chain.py` checks a chronological
sequence of **already independently checked per-worker original GitHub ZIP
receipts and matching pinned source manifests**. It refuses a missing or
malformed worker linkage, duplicate worker ID/artifact/outer SHA/manifest,
source clock overlap, a declared source-handoff gap greater than five minutes,
a changed original PAPER strategy/risk/fee/feature/engine identity, or
a source manifest with declared gaps. It allows an explicit first worker
with a predecessor outside the studied slice, but records that predecessor
as unauthenticated external dependency. All changes are offline and
nonqualifying: this function does not browse GitHub, ingest exchange L2,
authenticate a signed resume artifact, prove market-level coverage, or
run either PAPER trading account.

A 72-hour *nominal manifest* span is deliberately NOT equivalent to
72 hours of observed continuous L2 on all selected markets. All the output's
independent chain/market/after-cost profit/execution/promotion flags remain
FALSE even for a locally self-consistent chain. Original source ZIPs can
only feed this preflight after separate exact-outer-ZIP and receipt checks.

## October 16 — direct L2 first-received clock and PAPER offer-age attribution

Authenticated recovered PAPER worker #38890963241 at 11:36 UTC was
running on merged `0ae483ef`, with $9,741.22 total equity, -$258.78
after-cost whole-account PnL on 259 closed trades, no open positions and
LIVE disabled. Its original v3 recorder had 51,278 source offers,
1,363 writes, 49,915 permanent drops, **781 raw-clock regressions**
(186 behind the immediately preceding original offer, 781 behind
PAPER's prior clock), and a 24,741ms maximum backwards jump. This
source remains **invalid**; there is no 72h economic experiment result.

The new prospective negative-only diagnostic now separates L2 receive
timestamp regressions within the same original source+market+event-kind
stream from those attributable to only cross-market/source interleaving.
It preserves a bounded 512-stream high-water table (with saturation
counter), and measures the age between each L2 record's ORIGINAL local
received timestamp and when the genuine PAPER record pump offered it to
the research writer: counts above 1s, 5s and 15s, future-dated receive
timestamp count, and largest observed age. This can distinguish event
loop backlog/late delivery from independent interleaving without making
up a venue timestamp or copying raw keys/paths into the heartbeat.
Original recorded bytes, timestamps, per-worker SHA and order, trading
decision logic, fees, positions, risk, and outcome are untouched.
A raw clock regression STILL permanently disqualifies the research
archive. No operational status can grant market L2 completeness,
after-cost positive paired equity or LIVE permission.

## October 16 — historical gap boundary is NOT actual receipt time

The genuine #38899067717 heartbeat reported 184 original-receive clock
regressions with the first offending original `data_gap` only 49ms
backwards, while L2 source-to-PAPER offer age peaked at **7ms**
and same-L2-stream clock regressions were **zero**. This rules out
the hypothesis that the initial failure necessarily required a multi-
second L2 backlog.

In genuine workers **before** merged PR #1293, `_record_from_gap`
sets `ReplayRecord.available_at_ms` to the DATA_GAP start (for OPEN)
or end (for CLOSED). Those are historical coverage boundaries, not
first-receipt timestamps. The resulting delayed notification could
therefore regress behind later received market events.

From PR #1293 onward, **newly started** PAPER workers construct each live
gap record inside the serialized record-pump lock using its actual
observation time. The original `started_ms` and `ended_ms` stay unchanged
in the original immutable gap payload; old source artifacts are NEVER
rewritten, and offline boundary-time callers retain their old semantics.
The research recorder still rejects true receive-clock regressions
(including reordered L2), while any genuine source DATA_GAP still
disqualifies the frozen v3 zero-gap trial. Receipt-time correction is
not a venue-completeness claim or permission to erase a gap.

The next negative-only diagnostic separates original DATA_GAP OPEN
versus CLOSED offers, counts their original boundary age at the
actual PAPER offer (>1s, >15s, future-boundary), and reports the
first failing gap stage without raw source identifiers or market payload.
Terminal diagnostic fields are bound to exact originating run/attempt/SHA
and otherwise remain unknown. **This measures where source-clock
semantics differ; it does not reconstruct a missing exchange event,
create original first-received evidence, complete the v3 source,
validate 72h paired economics, or enable LIVE orders.**
