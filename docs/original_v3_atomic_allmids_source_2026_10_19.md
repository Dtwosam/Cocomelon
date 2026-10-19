# October 19 — preserve atomic first-received allMids frames before source capture

## Profit dependency and actual evidence

Authenticated ordinary PAPER worker **#39223537959** at **12:28 UTC**
still runs **old `372dff6d`**. The $10,000 account has **$9,780.3465
equity / -$219.6535 total net**, 304 completed trades, zero open
positions, realized gross **+$18.7836**, actual booked fees
**$235.5150** and funding **-$2.9221**. No positive after-cost strategy.

The prospective original v3 journal is **permanently FAILED**
(`original_received_clock_regression`). At that heartbeat,
4,183,370 offers / 30,577 durable originals / **4,152,793 dropped**,
with 211,876 original-vs-PAPER clock regressions. Of these 210,000
were `all_mids` family observations; 3,417 were adjacent-original
backward edges. The gap/source readouts are diagnostics, not a new
72h source certificate.

## Reproduced ordering hole

The mainnet WebSocket sends a single `allMids` frame. The
normalizer creates many original per-market children with **the
same original receive timestamp**. Historically the supervisor
sent each child via an independently locked
`RedundantStreamMux.on_event`, releasing mux serialization
between children. A second asynchronous source or gap on either
lane could be accepted between BTC@2000 and ETH@2000. A later
record at 2400 between those children then makes the true second
frame child regress against the preceding accepted source and
PAPER clock. The original recorder must permanently fail that
capture rather than rewriting/clamping source timestamps.
Deferring only the allMids **recovery** notice until frame
completion (#1362/#1366) did NOT exclude unrelated lane arrivals.

## Narrow PAPER-only source fix

- Optional `all_mids_frame_dispatch_guard` in
  `WebSocketSupervisor` wraps the FULL normalized original frame:
  each event's existing source-gap persistence, dedup/freshness
  acknowledgements, same original event sink and deferred
  supervisor recovered gap, then the existing complete-frame
  mux and restored/rotation checkpoint notices.
- `RedundantStreamMux.serialize_all_mids_frame_dispatch`
  holds its single existing ingress serialization lock
  *across the whole source frame*. A task-owned reentrancy
  path allows that SAME supervisor task to call `on_event`,
  `on_gap` and `complete_all_mids_frame` without deadlock.
  Other tasks/lane sources cannot overtake the frame. The
  actual receive, venue exchange, gap and event payload data
  are **unchanged**, as are source-failure and restart rules.
- Guard is opt-in only for the real PAPER mainnet redundant
  supervisor; independent stand-alone mux/supervisor callers
  retain previous APIs and behavior. Failure/cancellation
  always releases ownership and the lock. No failed child
  can acknowledge a completed frame or heal a source gap.
- Concurrency tests force an independently arriving L2 event
  while the first child is awaiting its sink: allMids BTC,
  allMids ETH, then existing gap-close, THEN the later L2.
  Error and task cancellation tests require no premature
  gap-close, no deadlock, identical retry event identities
  and completion only after the last child. No fixture or
  source timestamp was sorted, moved or "fixed".

## Negative gates and remaining risks

This removes a *known permitted* source-reordering mechanism.
It does NOT prove the old 211,876 regressions were all due
to frame interleaving, repair any earlier lost data, prove
per-stream original completeness, eliminate other mux/backfill
source gaps, or certify 72-hour clean L2. Frame-wide
serialization can increase the wait of concurrently arriving
L2 data under a large allMids frame; **latency/missed source
will need independent real-worker measurement after natural
handoff**. Existing strict source gap/freshness and negative
eligibility gates remain unchanged. An incomplete/failed
future original run must still report FAILED, never PASS.

No strategy, risk, exits, fees, funding, frozen research
filter, original journal artifact, cash or LIVE permission
was modified. Profit research remains gated on a NEW
genuine originally received mainnet source and separately
funded fully marked after-cost PAPER accounts, both strictly
positive with positive challenger uplift.
