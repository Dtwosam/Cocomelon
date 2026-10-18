# Frozen v3 LONG-trend matched PAPER across worker handoffs

The original genuine PAPER trader naturally hands off after about four hours,
while the frozen LONG-trend v3 prospective experiment requires **72 hours
of actual shared first-received market evidence**. The one-archive v3 offline
runner cannot join workers, and a 72h nominal manifest is not 72h L2.

`run_frozen_long_trend_multiworker_paper` is a **new, research-only offline
orchestrator** that preserves the October 16 frozen candidate exactly. It
does not create a v4 hypothesis or move the six-hour embargo.

1. Require at least two different original worker GitHub/manifest identities.
   Reject duplicated artifacts, broken declared predecessor links,
   overlapping timestamps, source gaps, long handoff silence and changes to
   the full original PAPER fee/risk/strategy/execution digest.
2. Independently validate each recorded worker's original sealed source
   segments and first-received ordinals. Process **one worker at a time**,
   never concatenate huge 72h feeds into a fake 1-worker manifest.
3. Stream across every handoff into the existing original v3 L2/source audit,
   rejecting any DATA_GAP, timestamp regression, stale/future exchange-time
   book, market omission or forward L2 silence above five minutes. Require
   72h of **common original L2 observation** for all selected markets.
4. **Before accounts exist**, complete the full source/market/audit pass.
   Only then build completely new baseline and unchanged LONG-trend-exclusion
   PAPER accounts with identical starting cash, risk, inputs, costs, funding
   and stops. A second byte-pinned read must reproduce the first audit's
   full chronological source digest and row count, otherwise there is **no
   economic report**. Partial accounts remain nonpromotable evidence.
5. Reopen both closed PAPER SQLite accounts read-only and reconcile exact
   fills, fees, funding, realized gross, open PnL and marked equity. Report
   the locally computed absolute after-cost net and dollars-to-breakeven
   for each lane, plus the candidate-minus-baseline delta.

The frozen source-check helper now accepts an **iterable of verified rows**
instead of requiring a complete multiworker tuple, preserving the original
single-worker logic. The memory limit is the largest individual 4h archive,
not the full 72h stream; precommitted 100M combined row ceiling prevents
unbounded work.

## Evidence limits

The supplied GitHub metadata still requires independent off-process
retrieval and verification, including the complete original ZIP digests.
Local chain consistency cannot independently attest the real exchange
feed, source event completeness, actual predecessor restore signatures
or external continuous account custody. Crucially, original v3 market
captures from the running campaign already have FAILED due to real clock
regressions, dropped records and market-data gaps. They MUST NOT be fed
to this runner or considered repaired. Synthetic tests are never source
or strategy evidence.

All independent venue, external interworker signature, positive edge,
promotion and execution authority booleans remain false even when a
synthetic 72h paired test has equal accounts and passing local parity.
A green CI build does NOT mean positive PAPER PnL. LIVE stays disabled;
ordinary PAPER positions, stops and accrued losses remain unchanged.
