# October 19 — strict-through maker entry PAPER shadow (no execution authority)

## Why this matters to actual PnL

The authenticated ordinary PAPER worker #39223537959 at 11:30 UTC still
runs `372dff6d` and shows $9,804.2980 in marked equity, **-$195.7020
net from $10,000 initial**, 302 lifetime completed trades and two open
positions. Realized gross +$32.9299 has been overwhelmed by
$234.4661 actual taker fees and -$2.9421 funding. Open-mark valuation
is +$8.7764 at this observation. The first-received original v3
feed has FAILED with 3,072,841 dropped records and 162,896 receive
clock regressions. Neither an after-cost profitable source-qualified
maker strategy nor two independently matched PAPER accounts exist.

Fee-only same-fills savings are not enough. Maker queue priority,
missed entries, partial quantities, stops, latency and subsequent
market paths decide whether cheaper execution has any edge. PRs
#1367–#1369 developed *possible* maker quotes/trade-through and
queue-ahead scenarios but did not generate even hypothetical entry
order lifecycles.

## Narrow new modeled entry lifecycle

Pure `simulate_strict_through_maker_entry` now models ONE hypothetical
post-only maker entry from an untouched original approved PAPER IOC
plan, its original source-timed would-be passive quote, native market
metadata, original fee schedule and the complete same-market original
trade tape from quote to expiry.

1. **Strict unchanged approved risk:** requires original plan lineage,
   market, metadata and fee configuration; the supplied original L2\n   book is independently re-parsed to re-create the quote, with exact\n   source event identity, touch price and visible queue size required.\n   BUY quote must remain below
   original stop-safe slippage ceiling and above stop; SELL inverse.
   Requested amount must match original plan and instrument quantum.
   Clip modeled quantity to original requested amount, approved
   **notional**, original planned stop-risk ceiling, and native
   minimum viable order size. No greater exposure or more favorable
   risk treatment than the original IOC is allowed.
2. **Same source and causal contract:** runs the earlier strict
   original tape validator BEFORE modeling anything; rejects missing
   capture/clock continuity, incomplete expiry, duplicate/reversed
   trade prints, wrong market, unrealistic fee, or invalid future
   exchange clock. An external 72h original-source attestation remains
   required; caller flags do not establish such a certificate.
3. **Conservative static queue:** begins behind **one full originally
   displayed best level**. Opposite-aggressor trades AT original
   maker quote may consume queue ahead, but **NEVER** create a modeled
   fill. Opposite-aggressor prints strictly THROUGH bid/ask first
   consume that original queue and only their remainder can generate
   a modeled, size-quantized partial/full entry. No fills on quote
   timestamp ties or after expiry. No automatic IOC fallback,
   retroactive cancellation advantage, maker queue priority claims,
   or partial-fill replacement entry.
4. **Conditional simulated fee only:** reports an isolated modeled
   entry notional and maker fee only on modeled partial quantities;
   full-account candidate net and *realized* savings remain NULL.
   No exit, stop, funding, unrealized marks or further capital
   occupancy is inferred. Zero modeled fill is an honest no-entry,
   not a claimed avoided losing trade or a strategy profit.

**Limits:** This is a deterministic conservative *PAPER hypothesis*,
not an exchange matching-engine fill oracle. A strictly-through trade
may not fill a real resting order at the modeled queue position;
posting an actual order changes the counterfactual tape. Hidden
liquidity, cancellations and book replenishment are unmodeled.
Both input source and venue order acknowledgements remain
independently unverified. This module deliberately never creates
`PaperFill` or `ExecutionAttempt`, mutates PAPER SQLite/cash/positions,
or touches real exchange APIs.

Tests cover no fill despite abundant at-touch prints, multiple
price-through partials, expiry, full modeled quantity without
certifying execution, SHORT opposite aggressor, size quantization,
notional/risk caps, native minimum, incomplete source and malicious
lineage. The next justified step is a separately capital-matched
isolated PAPER account using **actual original data + complete
full-portfolio exit/funding/risk/mark treatment**, with missed
winners retained and BOTH baseline and candidate strictly positive
after all costs over a genuinely zero-gap independently attested
>=72h sample. Until then: **NO PROFITABLE EDGE VERIFIED, LIVE OFF**.
