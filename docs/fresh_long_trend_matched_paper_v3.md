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
