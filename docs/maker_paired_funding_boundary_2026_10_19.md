# October 19 — Funding cannot disappear from maker-versus-IOC PAPER exits

## The economic flaw fixed

The research-only single-exit matched PAPER comparison from PR #1373
charged real configured entry and closing fees, but silently treated
all intervals as **zero funding**, even when the original position was
held across an hourly mainnet funding boundary. That can inflate
reported maker-vs-taker equity and systematically favor a lane that
had an open position earning/owing true funding. A missed maker
winner is particularly sensitive: the baseline remains funded
while the nonfilled candidate correctly holds cash.

This repair does **not** remove real exchange costs, change a single
LIVE/PAPER order or prove a profitable edge. It eliminates a false
source of hypothetical positive PnL.

## Fixed and fail-closed contract

- Determine the first canonical hourly funding boundary after the
  baseline's *actual simulated IOC opening fill*, not the
  strategy-decision clock. If the common planned exit crosses one
  boundary, original pre-boundary oracle `ACTIVE_ASSET_CTX` and
  exact mainnet-info `FundingRate` are now REQUIRED inputs.
- Use the existing `reconcile_funding_boundary` engine for each
  account's own open position. It enforces original oracle
  freshness/time, original hour-boundary funding record and exact
  market. Then charge the canonical
  `apply_funding_accrual` cash delta to the **separately funded**
  maker and IOC accounts BEFORE either attempts an exit.
  LONG funding paid/received, SHORT inverse sign, partial quantity
  proportionate. A lane with no entry has no position and pays zero;
  a lane first filled after the hourly boundary also owes none
  for that earlier boundary.
- Missing, future-dated, wrong-market, stale, forged-source or
  post-exit funding is an error, **not** default $0.
  Funding evidence on a trade without a crossed boundary is
  rejected; two or more crossed hourly boundaries are refused
  until a multi-hour complete funding ledger is separately built.
  The mainnet oracle event must have the original WS source,
  while the funding-rate event must come from the named mainnet
  information source. The caller's source-clean boolean is NOT
  treated as an external source certificate.
- The existing original exit book/plan, original market mark,
  baseline/maker independent entry costs and real conditional
  taker exit costs remain untouched. Return each lane's
  cumulative funding and whether a single boundary was costed.
  Whole-account qualified profitability and trading authority
  ALWAYS remain FALSE.

## Independent evidence and limits

At the last authenticated 2026-10-19 **13:52 UTC** PAPER Issue #469,
active worker #39255842615 still ran #1372 SHA `6c9f045a`:
starting $10,000, equity **$9,801.6048**, marked after-cost
PnL **-$198.3952**, 305 completed trades, two open,
booked trading fees **$236.9523**, realized gross **+$18.7206**,
funding **-$2.9221**. Source capture is permanently FAILED,
with **829,822 dropped rows** and 24,770 receive-clock
regressions; the newly merged gap reason attribution code
has not yet been adopted by this worker. Those data are NOT
a qualified after-cost maker strategy.

The funding-aware comparison remains a single-path, single-hour,
*conditional* original maker-entry/reduce-only original exit
research account. It does not model multiple trades, risk
reallocation, stops, liquidations, multiple-hour funding,
adverse queue fill uncertainty or a forward 72h verified source.
Every report still explicitly denies actual venue maker fills,
source authentication, whole-account positive edge and execution
or promotion authority. No strategy, frozen challenger, PAPER
runtime, worker restart, LIVE, source gaps or risk limits changed.

**Economic gate:** new independent zero-gap >=72h original
mainnet source, both full account forward PAPER ledgers
absolutely positive AFTER all fees, funding, slippage and
unrealized marks, plus maker challenger uplift across regimes.
Until verified, NO PROFITABLE EDGE; LIVE OFF.
