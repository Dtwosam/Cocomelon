# October 19 — Capital-matched IOC vs conditional maker ENTRY-MARK accounts

## Why this is a useful *partial* money test

As of authenticated October 19 12:08 UTC, ordinary PAPER worker
#39223537959 on OLD `372dff6d` has **$9,788.8574 equity, -$211.1426
marked net** on $10,000 initial cash; 302 completed trades, two open,
+$32.9299 realized gross, $234.4661 actually paid fees and -$2.9221
funding. The original v3 first-received source was **FAILED**, with
3,778,839 dropped rows and 194,499 clock regressions. It cannot
authenticate a new maker strategy. The entry-mark shadow described
here is **not evidence of source-qualified historical or forward
profitability**.

## What the new paired function actually does

`research.maker_entry_paired_mark.paired_maker_vs_ioc_entry_mark`
takes the *same* original approved PAPER opening plan, same native
instrument/version, source-timed original L2 snapshot, complete
same-market original trades to maker quote expiry, and one later
original `ACTIVE_ASSET_CTX` mark.

- Starts **two independent in-memory PAPER accounts** at exactly
  the same supplied positive Decimal cash, with **zero inherited
  positions**. It refuses any source-integrity failure, wrong
  market/source, future/missing/stale mark, unsupported instrument
  or inconsistent plan/config. The source flag alone is not an
  independently authenticated original mainnet certificate.
- Baseline simulates the unchanged approved marketable IOC against
  the original L2 using `execution.ioc.simulate_ioc` and the same
  original taker fee. A rejected baseline fails the comparison.
- Challenger calls the separately tested `simulate_strict_through_maker_entry`.
  It must reconstruct the source-latency quote and queue, exhaust
  one originally visible queue first, model *no* fills at touch,
  and only conditionally model quantized partial/full fills when
  subsequent original opposing aggressor prints strictly **through**
  that quote. No maker after-expiry or same-millisecond fills;
  no baseline-to-maker transfer, no automatic fallback.
- Reuses the canonical PAPER accounting engine's `empty_account`,
  `apply_opening_fills` and `mark_to_market` on two distinct
  account values. A transient `PaperFill` is constructed
  **only inside isolated research code** for a conditional
  maker fill, with a conspicuous `RESEARCH-ONLY-CONDITIONAL-MAKER-NOT-VENUE`
  label. The shared legacy `PaperFill.taker_fee` field denotes
  the actually charged *model* fee here, at maker rate;
  it is not a taker fee, venue acknowledgement, journal entry
  or ordinary PAPER account fill. These provisional objects are
  **never persisted or returned**.
- Marks both independently at **the same fresh source mark** after
  the candidate order has expired. Outputs per-lane starting cash,
  cash balance, marked equity, fees, unrealized PnL, funding
  (zero in this entry-only interval), position quantity, as well
  as the *conditional entry-period* marked delta. An unfilled
  maker lane keeps original cash and has no position. One can
  easily see a maker missing a positive baseline opportunity,
  even though its trade fees are lower.

### Not a whole-account profitable result

A currently unfilled maker lane may appear to avoid a losing
taker trade and thus show positive *entry-period* delta.
That is not a whole-account challenger with independently
modeled future capacity, missed opportunities, exits, stops,
liquidations, holding periods or funding.

Both lanes are **entry-period only**, not durably funded worker
accounts or entire after-cost replay campaigns. The function
refuses to label its outputs profitable: maker venue fills
unconfirmed, original IOC PAPER-simulated, exit completeness
FALSE, future funding/exits FALSE, independent source custody
FALSE, promotion/EXECUTION authority FALSE, and
`whole_account_positive_edge_verified` FALSE unconditionally.
The user's active PAPER trader and frozen v3 account trial are
untouched; LIVE remains disabled.

Tests cover full LONG and SHORT entry marks, exact maker/taker
fees, missed profitable IOC versus maker no-entry, a genuinely
partial hypothetical maker fill with lower marked equity,
unearned positive delta when declining a losing entry, duplicate
prints, negative/NaN startup capital, stale/future/wrong-source
markets and nonqualifying original capture.

## Next economic hurdle

Use fully original authenticated zero-gap >=72h mainnet source
to connect the two lanes into independent **durable** full
account-lifecycle replay, with stops, exit IOC, funding,
liquidations, reallocation and every later entry governed by
current risk and available capital. Require **both accounts
strictly positive marked after-cost dollars** and a positive
maker-challenger advantage across regimes. No fee-only
retroactive lane earns promotion.
