# October 19 — complete source-witnessed hourly funding for maker-vs-IOC PAPER

## The money problem

PR #1375 fixed a silent zero-funding assumption on a single hourly crossing,
but deliberately refused a trade that survived two or more boundaries.
A full after-cost shadow account cannot responsibly compare a multi-hour maker
holding period with IOC if any intervening hour is missing, duplicated, stale,
out of order, or modeled at a free zero rate.

## Research-only behavior

- Accept the legacy single original pre-hour oracle / exact mainnet-info
  FundingRate pair for **one crossed hour**. Also accept an explicit ordered
  tuple of original oracle/funding pairs for **every crossed hour**, but never
  both interfaces at once.
- Enumerate actual crossed hourly boundaries starting strictly after the
  baseline IOC fill. Require **exactly one distinct original pair per hour**.
  Require strictly advancing oracle receipt and funding-record receipt,
  correct market/source, valid canonical funding timestamps, and funding
  records that arrived during the relevant original hour before the exit.
  Call the unchanged canonical funding reconciliation on each source pair.
- Charge each separate PAPER cash ledger using its *own* position quantity and
  side. An unfunded maker no-fill remains cash. Partial maker fill earns/pays
  only its actual hypothetical conditional quantity; baseline cash is not
  skipped. Original bid/ask, exit plan, exit fill fees and mark all stay fixed.
- Expose the exact ordered boundary times, oracle event keys, rate receipt
  times and count in the study output. Keep the existing single-hour output
  fields backward-compatible for exactly one hour.
- Reject missing second-hour evidence, switched hour order, repeated hour,
  wrong market, late funding, and any extra proof where no hour was crossed.
  No empty observation, source-integrity boolean or hypothetical fill grants
  genuine venue-fill or independent source certification.

## Not a trading performance improvement yet

This is a bounded **single-position path accounting** improvement, not a
portfolio replay, real maker execution, venue-wide source certification, or
strategy profitability result. Original v3 mainnet source remains known failed.
There is no permission to change deployed PAPER trading, to force a worker
restart, or to enable LIVE execution.

The economic proof still requires a **new genuinely clean original 72-hour
source**, two *independently funded* full-account forward PAPER histories,
all executed/missed entries and exits, actual funding across every hour,
paid fees/slippage/open marks, **strict positive after-cost marked equity in
both lanes**, and a robust positive maker uplift across periods/markets.

**Current verdict: NO PROFITABLE EDGE VERIFIED. LIVE DISABLED.**
