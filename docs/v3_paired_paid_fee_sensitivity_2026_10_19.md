# October 19 — Exact booked-fee sensitivity for a frozen v3 matched PAPER pair

## Falsifiable economic question

The latest authenticated October 19 09:40 UTC PAPER heartbeat (#39223537959,
old deployed `372dff6d`) reports a $10,000 starting account, $9,796.5351
whole marked equity (**-$203.4649 net**), 302 cumulative closed trades,
+$32.9299 realized gross, $233.4237 booked fees and -$2.9711 funding.
Its same-fills fee-refund arithmetic is +$29.9587. The actual account
remains negative; a fee refund is **not** an accessible venue fill or edge.

The central question for the already-frozen Oct 16 v3 prospective LONG
trend abstention pair is whether a candidate's full-account net advantage
survives realistic booked execution costs, and how much of the advantage
comes from different fee turnover rather than improved realized/marked
non-fee economics. The existing independent local SQLite account audit is
a prerequisite and is never replaced by historical skip-cash arithmetic.

## Implemented diagnostic

`fresh_long_trend_economic_hurdle` now calculates, separately for each
matched account, the exact booked-fee coverage from gross + funding +
unrealized marks, and the fraction of fees that would need to be refunded
just to reach **zero**, not strict profit. A value above 1 means even a
100% refund cannot break even; a fee-free result equal to zero is still
not positive. With zero fees and an already-negative account, the refund
fraction is undefined, never zero.

It also applies the *same* fixed 0%, 25%, 50%, 75%, and 100% hypothetical
refund of **each lane's own actual booked fees**, holding actual source
rows, original fills, position marks, funding, starts and exits unchanged.
Every scenario reports baseline marked net, candidate marked net, paired
difference, both-accounts-positive flag, candidate-advantage flag and
explicit false execution/promotion authority. The 0% row must equal actual
booked economics and the 100% row removes the fee-savings component from
the candidate-versus-baseline delta. This is sensitivity math, **not** a
simulated maker-order execution or proof that fewer original trades would
free capital for other winners.

## Decision boundary

The sensitivity report has no effect on PAPER orders or on the frozen
LONG-trend candidate. Even if the candidate is ahead at the real 0% fee
refund and falls behind when fully fee-refunded, only a *fee-attributed*
relative improvement has been identified, not a positive independent edge.
The full v3 condition still requires independently authenticated
uninterrupted zero-gap mainnet observations for >=72h, two new capital-
matched independently verified PAPER execution accounts, both **strictly
positive** marked after-cost cash, forward sample/regime stability and
a strictly positive candidate advantage. No retrospective bad-trade
deletions or nonzero rebate assumptions can satisfy it.

Current original v3 source coverage is invalid from receipt-clock
regressions and genuine L2 gaps, and the future paired experiment is NOT
CERTIFIED. LIVE stays OFF.
