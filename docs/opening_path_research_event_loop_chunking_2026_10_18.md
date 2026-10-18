# October 18 — Bound optional opening-path research per event-loop turn

## Authenticated production evidence

At 15:54 UTC original PAPER worker #39138965707 was negative
**$263.1220956766538218** net from $10,000 capital, with 291
cumulative closes and **zero fresh worker closes**. Original v3
receive-clock source was ineligible: 247,802 offered / 1,234 written
/ **246,568 dropped** after genuine receive-clock regressions, including
first data-gap → all-mids regression of 137,786 ms. Real L2 source gaps
continued across both redundant WebSocket lanes.

The full last captured heartbeat identified a **3,861 ms** event-loop
lag coinciding with `opening_path_research: observe_snapshots` and
concurrent websocket recovery/refresh. The background opening-opportunity
research actor previously offloaded its *entire active market snapshot*
to one worker-thread computation. Although off-event-loop IO is used,
the thread's Python transform still shares the GIL and may delay
receive processing when historical research marks grow. This is a
targeted plausible bottleneck, **not proof that this operation alone
caused the 3,861 ms delay**.

## Change

The optional opening-path research store retains its original
immutable active-market snapshot, sorted original opportunities,
recorded observed time, price, event source, same-timestamp collision
check, expiration deadline, and independently durable per-opportunity
JSON files. It now evaluates source-mark transformations in bounded
**32-path worker-thread batches**, yielding to the event loop after
every batch even when no marks qualify.

**Crucial parity invariant:** validate the entire unchanged snapshot
first, across every batch, then and only then write the staged
original marks in their original order with the existing awaited
off-thread fsync, atomically indexed after a successful write. A
malformed final-batch mark cannot persist apparently clean earlier
marks. Missing, duplicate/conflicting or out-of-order marks never
become acceptable, and nothing is thinned or reordered.

New tests replay 73 independent exact original paths (68 BTC and
5 ETH) and compare their full saved documents against the original
synchronous path after reopening, assert bounded batches and
off-main-thread computation, demonstrate a monitoring coroutine can
progress during a large update, reject a last-chunk conflict without
any early partial commits, and preserve exact horizon/expired
mark semantics.

No PAPER entry, order, risk, stop, fee, account state, original venue
market record, source-gap handling, WS watchdog, v3 source seal or
LIVE order path is modified. This can help preserve event-loop
responsiveness for forward source capture, but **neither validated
original market coverage nor positive after-cost net PnL is claimed**.
Actual future latency, source-loss and market freshness must improve
under independently authenticated new-worker telemetry before this
optimization is credited with such a result.
