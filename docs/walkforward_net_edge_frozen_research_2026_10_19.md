# October 19 — frozen research hypothesis: after-cost *prior-close* net expectancy

## Economic purpose

The authenticated Hyperliquid PAPER account was approximately **$9,775.26** against
$10,000 initial equity (−$224.74 after paid fees and funding) at 19:08 UTC.
307 actual completed trades booked **$239.51 fees** for about **$11.10 gross**
realized profit. Merely cutting nominal fees or rejecting trades using 0.25R
cost did not create positive capital-matched returns: a frozen 170-trade
cost>0.25R screen actually worsened the same-trade comparison.

This is a **NEW research hypothesis**, not a replay of that failed price or
momentum-pullback filter. Can a strategy distinguish entry contexts with
reliably positive actual net R, using only completed original PAPER account
trades strictly known BEFORE the attempted entry? The candidate will
decline research admissions if prior actual, after-cost, capital-normalized
return in the same direction is not robustly positive.

## Frozen non-leaking rule

`src/cocomelon/research/prospective_net_edge_admission.py` provides the
pure research contract. A state carries its prospective freeze time and
**six-hour embargo**. Only **baseline trades BOTH opened and closed after forward start** and
**strictly closed before the target opportunity's opening time** may enter the
training window. A position opened before the forward start but held
through it remains OLD discovery and cannot vote, even if it closed
later. Delayed overlapping positions, including their future exits,
cannot vote. Every actual unfiltered baseline outcome remains in
the reference, even when a prior hypothetical candidate would have
declined it. No hidden re-weighting of losses, fake zero-cost fills, or
time-forward return leaks.

The rule uses the latest **80** closed actual trades of the **same direction**,
requiring at least **40** and **four distinct markets**. It computes the
minimum of all four consecutive closed-trade block mean net-R values,
the leave-one-market-out mean net-R values, and a leave-largest-winner-out
mean net-R. Only an empirical stress floor **strictly above +0.05 R** can
produce research admission. R is normalized by the actually logged
initial risk and is AFTER actual entry fees, exit fees and hourly funding,
not a gross markout. These are empirical sensitivity bounds, **NOT**
calibrated probabilities or formal prediction confidence intervals.
Nothing retrospectively adjusts the four blocks or direction.

A read-only walk-forward diagnostic consumes authentic unchanged
`TradeJournalEntry` objects, labels future opportunity decisions by
opening timestamp, and reports only the *original same-fill skipped-trade
cash arithmetic*. Its output permanently flags independent capital-
matched PAPER accounts, source continuity and positive real net equity
as **UNVERIFIED**. It must NEVER authorize executing its decision in the
running worker.

## Limits and real next-money gate

A history-only signal may well block every new opportunity. Zero trades
means zero gross opportunity and does NOT count as profitability. A
favorable historical net-R has unknown stationarity, fill costs, market
impact, funding changes, different opportunity occupancy, portfolio
cash availability or adverse selection in a future shadow account.

The real next step is to freeze an independent capital-matched baseline
and challenger at a NEW clean original-source start; each must record
both actual paid entry and exit fees, realistic source-backed spread,
slippage, funding, overlapping margin, missed fills and zero-trade
decisions. Require genuinely positive marked whole-account equity from
starting capital and robust positive uplift over baseline. The old v3
source is still FAILED; no promotion can occur until a fresh original
72-hour window passes.

No ordinary PAPER orders, position stops, margin, risk, existing source
timestamps, worker continuation or LIVE authorization change.
