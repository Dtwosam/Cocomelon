# October 19 — How much fee saving survives missed winning trades?

## Actual economic blocker

Authenticated Oct 19 10:40 UTC ordinary PAPER #39223537959
(old deployed `372dff6d`) has $9,790.6863 marked equity from $10,000,
**-$209.3137 whole-account net**, 302 completed trades, **two open
positions** with -$4.8063 combined unrealized marks, $234.4661
booked fees, +$32.9299 realized gross and -$2.9711 funding.
No retrospective deletion of losing fills may count as improvement.
The original source recorder remains FAILED: 2,130,624 dropped rows
and 92,019 clock regressions at that heartbeat.

Even if an opening order could genuinely rest at a better price and
pay maker fees, the system can lose a profitable trade by waiting for
a fill. Headline maker/taker fee differences do not tell us how much
profitable turnover the candidate can afford to miss.

## New bounded original-closed-journal test

`maker_entry_cost_budget.maker_entry_closed_trade_cost_budget`
accepts **every original completed trade in a specified cohort**,
its original plan identity, its prospectively timestamped maker
best-bid/ask quote and independent original-trade-through witness
created by `maker_entry_feasibility`. The function:

1. Checks every trade has one same-market, same-side, identical
   opening-plan witness; no missing or extra rows, wrong fee
   schedule, impossible book size, forged realized maker fee
   saving, assumed fills, expired-after-real-exit quotes or
   invented authority. Trade fee/gross/funding/net must reconcile.
2. Computes the **fee-only same-original-fill ceiling** if all
   original entry fees were discounted from observed taker
   schedule to a predeclared lower maker fee. It deliberately
   leaves all original exits at their REAL taker fees, holds
   all original entry/exit prices, funding and gross unchanged,
   and never calls the result a booked return.
3. Subtracts original **positive** hypothetical trade
   contributions from that optimistic result to stress the
   loss if the largest winning trade—or the three largest
   winners—never received a maker fill. This is an adversarial
   *no-replacement* cash stress, not a forward queue simulation,
   a post hoc trade-selection rule, or a reliable probability
   that those winners would actually miss.
4. Reports how many original trade-through prints still
   **rule out full original size** at the proposed passive
   quote, with no claim that the others would fill.
   Always sets guaranteed fills to zero, realized maker
   savings/whole-account maker PnL to NULL, outside-source
   authentication and execution/promotion authority to FALSE.

This is *closed-journal-only cash*. It excludes any currently
open exposures, their funding/mark, replacements after missed
entries, position overlaps, capital occupancy, partial-maker
plus taker fallbacks, and any actual maker queue priority.
It does not run on the FAILED old source or certify original
market completeness. Even a favorable resulting fee-only
closed cohort **cannot promote a strategy**.

## Required next economic experiment

A new independent verified original-feed campaign, with >=72h
continuity, would need to run capital-matched PAPER accounts
with original IOC baseline and a maker-first candidate that
carries forward actual queue-aware fill/no-fill, missed
winners, delay, cancellation, stops, liquidations, funding,
and every exit fee. Both fully marked after-cost accounts
must be **strictly profitable**, with candidate advantage
and chronological stability, before further consideration.
No LIVE permission has changed.

The new stress module and tests are pure read-only research;
this PR does not change a PAPER trade, size, risk limit,
account, frozen forward cohort, data source, restart,
or fee booking.
