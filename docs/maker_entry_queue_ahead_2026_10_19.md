# October 19 — maker queue-ahead sensitivity, not fabricated fill PnL

## Current cash evidence

At the latest authenticated ordinary PAPER worker #39223537959
(Oct 19 11:05 UTC), equity is **$9,799.4451**, **-$200.5549**
marked after all costs on a $10,000 starting account. 302
cumulative closes, 2 open positions, +$32.9299 realized gross,
$234.4661 booked trading fees and -$2.9421 funding.
The actual worker still runs old `372dff6d`, not recently merged
cost research. Strict original v3 source is already permanently
FAILED on receipt-clock regression, with 2,606,253 dropped
original observations. No verified maker fee saving or net edge.

Previous [PR #1367](https://github.com/Dtwosam/Cocomelon/pull/1367)
counted an original opposite-aggressor print at/beyond a
hypothetical best-bid/ask quote as an **optimistic maximum possible**
entry quantity, never a fill. [PR #1368](https://github.com/Dtwosam/Cocomelon/pull/1368)
proved by an unaltered closed trade cohort sensitivity that simply
counting cheaper *original* entries can fail even before one
profitable entry is missed.

## This step

The pure research function `maker_entry_queue_ahead_sensitivity`
takes that source-validated original quote and the COMPLETE
chronological exact-market original trade tape through its expiry.
It calls #1367's fail-closed duplicate, clock, gap, source,
window and lineage validator BEFORE calculating anything.

It separates:
- Original opposite-aggressor prints **at** passive best touch;
- Prints **strictly through** best touch (past the proposed bid/ask);
- Matching prints arriving at the same millisecond as the
  quote (excluded because order/queue causal sequence is unknown);
- Prints after quote expiry (excluded).

For sensitivity only, it assumes a passive hypothetical order
would start **behind 0x, 1x, or 2x** the originally displayed
same-price queue at its original quoted touch. Under a STATIC
simplified FIFO market, prints at the quote would consume that
assumed queue first, while prints strictly through the quote
count as additional potential executable volume. It caps each
scenario at original requested quantity and separately calculates
the *conditional* single-entry maker/taker notional fee difference.

These scenarios are NEITHER valid lower bounds NOR confirmed
upper bounds on real fills. A real book can have cancellations,
hidden liquidity, missing printed trades, changed venue state
after placing a hypothetical order, fee-tier differences,
adverse selection, re-pricing, partial or no fill. Cancellations
can improve queue rank; hidden priority and counterfactual
order effects can worsen it. 0x is deliberately optimistic.

Every report keeps maker actually resting FALSE, guaranteed
fill quantity **ZERO**, realized fee saving **NULL**,
candidate after-cost equity **NULL**, external original source
authentication FALSE, and all execution/promotion authority FALSE.
The output is an economic *uncertainty surface*, not account PnL.

## Additional evidence-integrity fix

`quote_research_only_maker_entry` now checks **every** original
L2 level rather than using the first array entry uncritically.
Bids must be strictly descending and asks strictly ascending;
prices and amounts must be positive exact Decimals and arrays
bounded, or the original quote fails closed. This avoids
accidentally crediting a passive fill at an incorrectly selected
best price from malformed/misordered original book rows.

No baseline PAPER account or fee booking changes, no forced
deployment, no frozen source/hypothesis mutation, and LIVE off.
The next genuine economic trial must carry independent real
book/trade continuity, queue-aware maker entry/no-entry with
realistic timing, exits/stops, funding and all open marks through
two matched after-cost PAPER accounts. Both original/challenger
account results must be strictly positive with challenger
uplift and 72h+ independently attested continuity.
