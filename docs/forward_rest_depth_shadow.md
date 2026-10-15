# Default-off public 20-depth REST PAPER shadow (phase 1)

**State: implementation only — NOT activated in the autonomous PAPER worker.**

The anonymous public REST /info l2Book endpoint provided **180 distinct
20x20 source books per market** in [the 2026-10-14 controlled 3-minute
probe](https://github.com/Dtwosam/Cocomelon/actions/runs/38645458026),
with ~99.8% time at exchange-age under 3 seconds. The ordinary public
20-level WebSocket simultaneously offered ~49%. This is promising **source
quality**, not signed completeness or a demonstrated trading edge.

This phase implements reusable in-process quota machinery and an
**independent, nonexecuting, disabled-by-default** observer. It does not
connect its books to strategy signals, fill simulation, recovery, account
state, signed DATA_GAPs, balances or exchange orders.

## API budget design

The already-existing \`RollingRateBudget\` now supports thread-safe atomic
\`try_acquire(weight, reserve_remaining=...)\`: it immediately returns
\`false\` when the reservation would exceed a 60-second rolling ceiling,
rather than blocking, sleeping or retrying. Existing required public
\`InfoClient.post_info\` readers retain blocking \`acquire\` semantics.
The lock is **not** held across their necessary wait.

\`InfoClient.try_shadow_l2_book(market)\` performs **one** anonymous REST
l2Book request with weight 2, no retry, and a bounded 4-second timeout
only if the same underlying \`RollingRateBudget\` that already governs
mandatory InfoClient reads has spare capacity. It preserves a
**300-weight reserve** on a normal 1000-weight rolling budget for
higher-priority paper reads. Unknown/injected rate-budget implementations
fail closed without an HTTP request.

The observer has an **additional independent 360-weight/rolling-minute
slice cap**, frozen to BLUR/BOME/CASHCAT with >=1 second between ticks.
Missed ticks never generate catch-up bursts. On shared quota exhaustion it
records \`shared_budget_skipped\` and never calls the transport.
An HTTP error consumes the weight reservation and is never retried.

**Crucial limitation:** in-process budget-sharing only covers calls using
the **same InfoClient/RollingRateBudget object**. It does *not* account
for other processes or external parties on a shared NAT/public IP.
The research experiment cannot certify shared-IP headroom without
separately verifying actual co-location and accounting all API callers.
Running a separate observer process alongside a PAPER worker is therefore
**not an approved operating configuration**. There is no automatic
workflow or default activation for this shadow. Any later co-located
worker integration must pass that additional gate before enabling network
traffic.

## Observer evidence

\`RestDepthShadow\` accepts only frozen three-market snapshots, parses
them with the existing public L2 protocol parser, and measures per-market
**20 bid + 20 ask level** source-age coverage at the existing 3s and 5s
age limits. Repeated cached responses never reset the unique source clock.
Shallow books, future-dated timestamps, protocol errors, regressions,
quota-skipped reads and no-response intervals cannot be certified as fresh
full-depth evidence. Its append-only receipts include each attempted
market/elapsed-time, separate skipped/error records, source-clock age,
counts and source message hash; summary files checksum the entire JSONL.

For isolated offline experimentation only, with PAPER mode explicitly set:

    COCOMELON_EXECUTION_MODE=paper \
      python -m cocomelon.research.forward_rest_depth_shadow

With the default CLI arguments it performs **zero network calls** and
writes **no artifact**. The \`--enable\` flag permits a stand-alone
single-window observation, but it is research-only and **does not share**
the running PAPER worker's quota or claim source authority. Do not
activate this separate process on the same public IP as another
Hyperliquid client until aggregate limits are independently established.

No receipt from this observer repairs existing signed market gaps,
becomes an authoritative trading order book, changes an account, or
qualifies a trade. A positive standalone run does not prove exchange
source completeness, in-worker rate headroom, after-cost profitability
or any LIVE trading permission.

## Next qualification gate

Wire the observer **default-off** to the existing PAPER worker's single
InfoClient reader, verify all IP-coincident REST request sources, and
record a prospective multi-day shadow with independent market receipts
and account continuity. Keep original dual-WS signed source events
authoritative. Do not change 3-second signed stale or 5-second strategy
freshness rules.

Tracking: [Issue #1243](https://github.com/Dtwosam/Cocomelon/issues/1243).
