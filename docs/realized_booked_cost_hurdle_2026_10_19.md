# October 19 — require real expected gross edge to exceed booked costs

The authenticated worker at October 19 17:43 UTC has $9,769.8311 equity
from $10,000 start, **−$230.1689 marked net after real PAPER
execution fees and funding**, 307 cumulative closes and zero current
session closes. Actual realized gross = **+$11.0970** and actual booked
fees = **$238.3826**, funding cash = **−$2.8833**.

At the *same realized fills*, this is only about $0.036 gross realized
per close, while booked fees average about $0.776 per close and
fee-minus-funding drag averages about $0.786. The underlying strategy
does not meet a gross return hurdle even before making a maker-vs-taker
claim. A zero-cost retrospective trade rejection is never an independent
future profitable account.

## Research-only change

The original PAPER profitability scoreboard now calculates, for the
whole original closed-trade cohort and each existing market/side/strategy
cohort:

- Actual gross realized dollars per completed trade.
- Exact booked cost hurdle per trade = (paid fees − **signed** actual
  funding cash) / trade count.
- Additional gross dollars needed per trade and in the whole cohort to
  reach zero net: max(cost hurdle total − realized gross, 0). Strictly
  positive profitability needs MORE than zero.
- Whether actual booked gross even covers actual fees less funding,
  with null on empty cohorts, retaining negative hurdle where original
  funding credits genuinely exceed the fees.

These are descriptive original completed-trade metrics, not an online
entry-time forecast or approval to automatically filter trades.
Retrospective losers, unverified source rows, open-position marks and
blocked/missed trade capital are never removed to show hypothetical
positive returns. Actual PAPER strategy, sizing, fees, risk, positions,
source and LIVE-disabled mode remain unchanged.

## Required next economic decision

The next PAPER candidate must declare an actual **pre-entry, source-
available prediction of gross price improvement**, with a calibrated
confidence bound, and demonstrate on a *new independent* clean forward
cohort that its gross improvement exceeds venue fees, spread, slippage,
funding and adverse selection by enough to yield positive whole-account
equity. Until such a prediction exists, a ranking/score is NOT a
calibrated dollar edge and cannot override the hurdle.

**This change quantifies the hurdle; it does not create profitable trades.**
