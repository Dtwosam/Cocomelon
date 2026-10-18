# Fresh v3 LONG-trend after-cost economic hurdle

This report is read-only **local** economics for the already frozen
`fresh-long-trend-admission-matched-paper-v3` prospective challenger.
It does not alter the candidate, trade the journal, create independent
source custody, or certify a clean >72h interval.

## Why the extra money reconciliation matters

A candidate can beat an underwater baseline yet still lose actual money.
A drop in fees can improve relative equity even if the original gross
trade selection is negative. A favorable closed-trade sum can also hide
open positions that are losing on their current marks.

The pure `fresh_long_trend_economic_hurdle` reads only the result of
`audit_fresh_v3_paired_accounts`, which separately reopens both local
PAPER SQLite execution stores and matches fill/funding cash, state hashes,
positions, cash, marked equity and signed local self-digest. It independently
decomposes the entire candidate-minus-baseline marked net-PnL delta into:

- realized gross PnL difference;
- trading fee savings or additional expense;
- booked funding cash difference;
- marked unrealized position PnL difference.

All dollar values remain exact Decimal text, with only the genuine
28-digit PAPER booking precision residual (1E-18 maximum) allowed.
Each account shows how many additional **net** dollars it would need merely
to reach zero, whether 100% theoretical refund of its already booked fees
would still leave it negative, and the extra gross dollar shortfall even
after that refund. The fee-refund arithmetic is **not** an executable
maker-order strategy and creates no free fills.

The local screening requires **both** account absolute marked after-cost
results to be strictly positive and the candidate to outperform baseline
after ALL costs. It is an informational screen, **not** a source
qualification, minimum sample certificate, signed inter-worker checkpoint
or promotion decision. The returned authority flags remain hard false even
when the synthetic unit test's candidate and baseline are positive.
Open positions are explicitly flagged because subsequent marks can change
the outcome.

## Production blocking evidence

As of October 18, authentic original v3 PAPER source has already failed
on original receive-clock regression, with millions of offered records
not durably written. Therefore a fresh independently authenticated
72-hour+ forward v3 matched-account result **does not yet exist**. Test
numbers in this module are artificial unit cases, never market data.
The original separate $10,000 PAPER account remains under water, with
LIVE disabled. No strategy should be changed based on this local report.

When a clean independent source exists, run the existing pinned v3
one-shot replay, inspect the new `locally_reconciled_after_cost_profitability_hurdle`
alongside original pair audit and source attestations, and refuse any
result with negative absolute account PnL or missing external proof.
