# October 18 — Keep optional capacity-release research fsync off the PAPER L2 loop

At the 2026-10-18 16:34 UTC independently authenticated PAPER heartbeat,
worker #39138965707 had $9,752.22 marked equity from $10,000
(**-$247.78 net**), 291 cumulative closed trades, and three open
short positions. Original v3 market source remains irreversibly failed
on genuine clock regressions and market-data gaps, with 854,936 rows
offered, 1,234 written and 853,702 dropped. The market-data pipeline
also measured a 292ms maximum for **optional**
`position_book_capacity_release_book` inside the L2 observer, and
798ms maximum for position mark processing. These are independently
measured *latency*, not verified trading edge.

## Implementation

The existing source-bound original-capacity-release research observer
`CapacityReleaseBookCapture` remains the sole evidence business-logic
and durable JSON writer. Genuine PAPER runtime now wraps it in
`AsyncCapacityReleaseBookCapture`, with exactly one daemon background
thread and bounded **1,024-message FIFO**. Both rejected-opening trace
registration and matching original L2 book observation are submitted
in one original event-loop order, so an evidence book can never
overtake the opening-plan registration that made it eligible.

The original book receive time, exchange timestamp, market, book
levels, source, position identities, eligible original window,
matching timing/fees/risk assumptions and per-file fsync are
unchanged. PAPER event processing only enqueues immutable arguments:
it no longer waits for research-specific disk stat, canonical JSON
or repeated fsync on the actual trade/mark path. PAPER's own execution,
account and stop evidence stay synchronous/unchanged.

**No silent loss:** if the research queue fills, a worker raises or
the optional close exceeds a bounded five-second drain, the error
remains sticky. No later records may restore apparently complete
research after an unknown skipped receipt. A clean natural shutdown
waits for FIFO completion before the original optional evidence
summary, and an abnormal shutdown also attempts a bounded close.
Thread waits always run off the event loop; an exceptionally slow
research disk cannot veto the already committed authoritative PAPER
account handoff. Noncertifying incomplete records remain on disk
for independent audit, never made clean by copying, reordering or
backfilling records.

## Verification

Focused tests require the full original durable registration, pending
plan and execution-book evidence to match the prior synchronous
writer *after an independent restart*, prove that a deliberately
blocked synchronous research callback no longer stalls event-loop
progress, and inject permanent queue overflow, a disk write failure
and a drain timeout. The original direct synchronous capture and
its complete existing integrity tests are unchanged.

This cannot repair old and current original-v3 received-clock
regressions or market-source gaps, cannot certify 72h of contiguous
source and cannot prove positive after-cost PnL. The improvement to
actual L2 responsiveness must be independently measured on a future
naturally started worker. Current PAPER strategy, positions, stops,
fees, funding, execution, risk and LIVE-off authority are unchanged.
