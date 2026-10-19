# October 19 — mux aggregate recovery CLOSE at original first-received witness

## Exact remaining observed source failure

At October 19 ~21:03 UTC, authenticated ongoing PAPER worker
#39292750327 on old SHA `5ed178dd` had **$9,774.40 equity,
−$225.60 actual marked after-cost PnL** from its $10,000 start,
308 completed trades, **$239.95 booked fees**, $6.18 gross realized
and about −$2.84 signed funding. LIVE was disabled.

Its original mainnet v3 source was permanently FAILED:
**3,518,204 offered / 11,500 written / 3,506,704 dropped**
because first-observed receive timestamps regress.
Original-adjacent backward-clock predecessors included
**closed:recovered=1,484**, closed:other=1,457, and
closed:recovered_after_rotation_witness=229. The previous PR #1389
only corrected a narrowly verified *named* witness class and is
not adopted by this active older worker.

## Causal explanation for aggregate mux recovered CLOSE

The redundant stream mux holds a serialized, strict original ingress lock.
Its `_close_aggregate_gap_if_needed` only emits its own `recovered`
aggregate CLOSE after a genuinely accepted same-stream WS event
that witnessed recovery, or after an authenticated supervisor recovery
notice following that accepted witness. It saves the exact aggregate
gap `ended_ms` before awaiting the downstream gap sink, and exact
failed writes retry with the SAME saved boundaries. The `ended_ms`
is the original first-received recovery clock already frozen by
accepted WS/supervisor evidence, not the time future disk I/O
finishes.

But the old live `gap_sink` forwarded that `DataGap` into the generic
record pump, which resampled **wall clock AFTER pump lock acquisition**.
A successor actual WebSocket packet can have its first-received
clock fixed while the prior gap fsync is waiting:

```text
original accepted aggregate recovery market witness: receive=2990
mux aggregate recovered CLOSE: first-witness=2990, fsync finishes=3500
new packet: first-received=3000
old source observations: 2990,3500,3000 -> false regression
new source observations: 2990,2990,3000 -> no false regression
```

This PR changes ONLY the mux aggregate `reason='recovered'`,
`ended_ms != None` receipt path: convert that source recovery
marker to a `ReplayRecord` with observation time equal to its
already frozen **original accepted recovery witness** `ended_ms`.
The mux still emits EXACTLY the same gap with unchanged original
coverage `started_ms`, `ended_ms` and `reason`.
This does not change source market packets' first-received UTC,
venue exchange timestamps, book prices, their event keys, fill
simulations or positioning. Standby source loss/open gaps, unrelated
CLOSED:other, stale, disconnect, overflow and recovery anomalies
remain ordinary live pump-time observations and negative source
evidence.

The regression tests hold simulated fsync at 3500, prove exact
recorded market witness and next packet timestamps 2990 and 3000
with recovered gap observation at 2990, and reject non-mux,
unwitnessed and OPEN records from the exceptional receipt path.
Generic gap routing is still independently required in the
runtime's structural contract.

## Economic and source limits

This is NOT an order-execution adjustment, fee reduction, funding
discount, source rewrite, historical restart or profit certificate.
It only repairs a causal async scheduling clock inflation for a
proven first-received source witness.

It cannot repair already terminal-FAILED historical original
source archives, or validate missing original event windows:
genuine source DATA_GAP records still disqualify a supposedly
gap-free 72h study. Other *true* source clock inversions, raw
cross-stream scheduling, and `closed:other` remain possible and
must fail source integrity. The active PAPER worker runs an older
SHA until safe natural worker succession (no forced restart).

Only a **NEW** independently observed market source of >=72h,
two truly separate capital-matched PAPER accounts and **strictly
positive absolute whole-account after-cost equity**, including
realistic maker/IOC misses, spread, slippage, paid fees, funding
and inventory/margin costs, can validate a profitable edge.

LIVE disabled. No risk loosening or reset of cumulative losses.
