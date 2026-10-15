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

