# October 19 — partial maker fills may straddle funding

## Actual profit-model failure

The maker-first single-exit paired PAPER simulator models independent capital
and fees, including every crossed hourly funding record. Its maker entry
`conditional_fills` can contain **multiple trade-through prints** across the
hour. Canonical `apply_opening_fills` aggregates all prints into one
`PaperPosition` and assigns its `opened_at_ms` to the **latest print**.
The existing `_fund_one_lane` treats a position opened after the hour as
not owing funding. That is correct for a single late fill, but WRONG when
the position was partially filled before the hour and completed afterwards.

With a 0.5 BTC conditional pre-hour fill and a subsequent 1 BTC post-hour
fill, positive funding at 0.1% and oracle $100 would charge the true early
lot $0.05 but mistakenly charge the consolidated candidate **$0**.
A fake maker profit can result even with otherwise complete hourly evidence.
This is a research-model defect, not proof of an actual mainnet fill.

## Bounded fail-closed fix

Before any funding accrual, compute the earliest and latest genuine
conditional maker fill receipt times from the validated original trade-through
tape. If a required hourly boundary falls within that interval
(`first_fill < boundary <= last_fill`), raise a precise research error.
No caller may reinterpret the skipped partial lot as cost-free cash.
All-pre-hour maker fills retain complete modeled funding; all-after-hour
maker fills correctly owe no funding for that earlier hour. Both long
and short hypothetical maker paths use the same restriction. The original
IOC cash account, canonical funding reconciliation, source timestamps,
risk controls, and all ordinary PAPER orders are unchanged.

A future per-lot original fill chronology and venue-aware funding engine may
remove this restriction, but only after independently complete evidence.

## Profitability acceptance is unchanged

No clean 72-hour original source or independently authenticated, whole-account
after-cost profitable maker challenger has been verified. No production
strategy or order changed and no LIVE execution is enabled. This patch
**prevents a false profit claim** rather than creating a profitable edge.
