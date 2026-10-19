# October 19 — Maker-first entry probe: trade-through is not a fill

## Economics: why "just use maker" is not enough

Authenticated ordinary PAPER worker #39223537959 (2026-10-19 10:13
UTC, running **old** `372dff6d`) has $9,796.5351 marked equity from
$10,000 starting capital, 302 historical completed trades, booked
gross +$32.9299, paid taker fees $233.4237 and funding -$2.9711.
The same already-executed positions would be **+$29.9587** only if
every dollar of fee were refunded. That is not a trading strategy.

Hyperliquid official standard base native perps rates are 0.045% taker
and 0.015% maker; see
https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees .
At exactly the SAME historical fills and without execution/funding drift,
reclassifying **every entry and exit as maker** saves at most two thirds
of booked taker fees, ~ $155.62, leaving about **-$47.85**.
For actual break-even from the current same-fills evidence,
~ **87.17%** of all fees would need to disappear with no changed
fills/marks/funding. Genuine resting orders can miss winners, lose
queue priority and fill adversely; there is no $155.62 booked saving
or maker-account PnL here. Fee tier, rebates and deployer fees must be
independently verified for any future real candidate.

## New narrow research-only code

`research.maker_entry_feasibility` uses only the original plan and
actual received mainnet L2 at/after its latency to quote a hypothetical
**passive BUY at best bid or SELL at best ask**. A crossing/locked,
stale, future, wrong-market or malformed book fails closed. It requires
an explicitly supplied, *positive* maker fee strictly below the actual
PAPER taker rate (0/negative maker rebates are deliberately outside
this first policy). The fee difference is the upper conditional
**single-entry** dollar saving **if the entire original requested size
were filled** at the untouched bid/ask. It is never booked to equity.

For a bounded, completely captured exact-market original TRADE tape,
the second function scans actual aggressor directions and traded prices
after the quote and before expiry. BUY quotes inspect original SELL
aggressors at/below the bid; SELL quotes inspect BUY aggressors
at/above the ask. Strict receive-time monotonicity, unique source
event identities, clean caller source gate and fully observed expiry
are required. Equal-millisecond prints are excluded because original
causal ordering is ambiguous. A trade-through yields only an
**upper bound on possibly executable quantity**; the guaranteed
maker fill is ALWAYS ZERO without independent venue order/queue
acknowledgements. A large nearby print is not a queue fill.

The result deliberately reports maker realized fee savings and
candidate after-cost PnL as **NULL**, has no submission path,
execution authority, or promotion authority, and always reports
external source authentication FALSE. In particular, this module
cannot provide the missing proof of a maker account's equity.
Tests verify crossed/wrong/stale L2, past/future/duplicate trade
tape, absence of trades, both sides, post-expiry prints, and
same-millisecond ordering ambiguity.

## Only economically meaningful next admission

1. Obtain independent, originally captured zero-gap market L2 plus
   trades, original stream receipts, and signed multi-worker identity;
   old permanently failed source is ineligible.
2. Quantify *actual* entry participation under venue-confirmed
   post-only orders or genuine conservative queue-accountable PAPER
   execution; count missed, adverse and delayed fills including stops.
3. Independently match starting cash and all after-fee, funding,
   slippage, unrealized-mark and risk/capacity outcomes against
   unchanged baseline, across future >=72h source and market regimes.
   Require **absolute positive equity on both accounts, plus positive
   challenger advantage**, not only cheaper hypothetical fees.
4. No changes to ordinary PAPER decisions, risk, stop, funding,
   historical source, existing frozen v3 study or LIVE permissions.

**CURRENT OUTCOME: candidate fillability and positive net edge are
UNVERIFIED. LIVE DISABLED.**
