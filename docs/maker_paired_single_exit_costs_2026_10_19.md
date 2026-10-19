# October 19 — actual PAPER exit costs in a one-path maker-vs-IOC pair

## Economic question

A cheaper passive entry cannot be called profitable just because a source
print might have crossed its quote or because entry fees were lower.
It must also afford the cost and availability of **closing the actual
quantity**. A missed profitable IOC entry costs potential gross profit;
a maker entry that fills only partially has different exposure and
exit fees. A stop/exit that never fills still leaves marked risk.

Latest authenticated ordinary PAPER Issue #469 at **12:35 UTC**:
worker #39223537959 on **old** `372dff6d`; **$9,780.3465 equity,
-$219.6535 after fees/funding**, 304 cumulative trades, zero open,
gross realized +$18.7836, booked fees $235.5150, funding -$2.9221.
Prospective original capture FAILED with 4,275,117 dropped rows and
244,297 clock regressions. These are not source-qualified results.

A new exact successor #39255842615 was seen at 12:55 UTC with
#1372's source code `6c9f045a`, but **state restore was still in
progress** when checked. Its own account/source heartbeat was not
yet verified; old losses may not be ascribed to the new worker.

## New single-path conditional paired cash experiment

Read-only `maker_entry_paired_exit_cost.py` extends the separately
funded #1371 entry-mark lanes with one same-source **predeclared**
reduce-only IOC exit plan:

1. Preserve the original approved IOC open plan, first original L2
   snapshot, original trade tape to maker quote expiry, original
   source-timed maker quote with original visible queue, venue
   metadata and fees. Before applying any fill, the strict-through
   model independently reconstructs the maker quote from the
   original book and rejects source gaps/clock reversals.
2. Open the baseline and conditional maker into two fresh accounts,
   both with the exact same cash and no pre-existing positions, using
   canonical `execution.ioc.simulate_ioc` and the PAPER accounting
   engine. Original IOC fills pay the taker entry fee; maker
   hypothetical strict-through conditional partial/full entries
   pay modeled maker fee, with **no fill = no position**.
3. An *independently supplied original exit plan*, created after
   maker expiry but **before** the original future exit book, must
   be reduce-only, market/side/config/metadata consistent and
   preapproved for the original IOC position quantity. Adapt only
   requested exit quantity DOWN to the conditional maker position
   size (never increase its source price ceiling, exit timing or
   other risk context). Simulate the SAME exit book and timestamp
   through `simulate_ioc` for both lanes, charge each lane's
   actual conditional taker exit fills, realize gross and fees with
   canonical `apply_reduce_only_fills`. A no-fill exit leaves a
   position open and marked; no retroactive free/ideal close.
4. Use a later matching original `ACTIVE_ASSET_CTX` mark to value
   any residual exposure identically. Report both independent
   cash/equity, realized gross, entry+exit fees, residual positions,
   exact single-path marked delta and whether BOTH positions
   are flat. Baseline profits missed by maker show up as a NEGATIVE
   candidate delta, not removed losing trades.

### What this cannot prove

This is one fixed original exit, not a prospective strategy capable
of controlling its own stop, exit, funding boundaries, subsequent
signals, capital occupancy, liquidation or full portfolio drawdown.
It is **NOT** a third running account, not a genuine maker order,
not independently source-attested and not a valid 72-hour
capital-matched after-cost account trial. Even two positive numbers
from this short path are not a profitable edge. Every report sets
`whole_account_profitable_edge_proven=False`, source authentication
FALSE, real maker fills FALSE and execution/promotion authority FALSE.
The user-facing requirement stays BOTH independently funded full
PAPER accounts strictly positive AFTER ALL costs and maker-delta
positive on clean original 72h+ source. LIVE disabled.

This PR modifies only read-only research and its tests; it does
not alter the baseline strategy, time windows, initial trade risk,
fees, original source timestamps, worker restart or frozen trials.
