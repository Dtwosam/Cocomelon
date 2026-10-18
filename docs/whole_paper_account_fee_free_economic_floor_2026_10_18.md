# October 18 — Actual whole-account profit floor, even if fees vanished

The user goal is **positive marked whole-account PnL after every fee,
funding charge, spread/slippage, stop and open-position mark**. Relative
filter improvement or an isolated winning trade is insufficient.
At the last authenticated PAPER status (2026-10-18 14:46 UTC),
worker #39120486505 has **291 cumulative closes** and:

| Original PAPER account component | Actual dollars |
| --- | ---: |
| Starting cash | $10,000 |
| Realized gross PnL | −$33.75662000000000000000000317 |
| All execution fees | $227.00025559890 |
| Funding cash | −$2.3652200777538218 |
| Open-position unrealized PnL | $0 |
| Marked whole-account net | **−$263.122095676653821799999999** |

This proves the current loss is **not explainable solely by trading
fees**: even if *every* paid fee were hypothetically refunded with
the **same realized fills, funding, and open marks**, net would remain
**−$36.12184007775382180000000317**. The system still needs at
least **$263.122095676653821799999999 of additional full-account
net dollars to reach zero**; the refund scenario still needs
**$36.12184007775382180000000317** of gross improvement. Strict
profit requires *more than* breakeven, not merely equality.

## Code / scope

The Issue #469 live-status renderer now displays four mechanically
reconciled, non-authoritative lines immediately after actual realized
gross/fees/funding:

1. Total extra **after-cost** dollars to reach zero.
2. **Same-fills** marked net assuming execution fees were *all* refunded,
   not a candidate forecast, not lower fees from an unverified broker.
3. Whether even that impossible fee-free rebate is losing and how
   much gross improvement it would still require.
4. Strict positive marked PnL flag and explicit **NOT CERTIFIED**
   72-hour source, edge and LIVE authority.

The calculations use exact Decimal strings and higher internal
arithmetic precision. They check the received account's equity,
starting cash, marked net, realized gross, accumulated fees, funding,
and unrealized position PnL against **both independent accounting
identities**, allowing only a 1e-15 dollar tolerance for 28-digit
bookkeeping representations. Missing, malformed, nonfinite, negative
fees, wrong cash, or inconsistent totals show UNAVAILABLE, **never**
positive economics. A synthetic gain in unit tests remains
uncertified. No source gaps, failed v3 archives or inherited bad
shadow accounts are promoted.

This does not change **one** actual PAPER entry, risk/cooldown,
fee amount, stop, slippage, funding booking, position, source record,
worker identity, account reset, execution mode or LIVE permission.
It exposes which economic shortfall future independent matched
whole-account experiments must actually beat. It is not evidence
that the frozen LONG-trend challenger is positive.

## Next economically material proof

Restore true original market source with zero dropped records and
genuine clock/gap continuity over >=72h across separately verified
worker and account handoffs, run the frozen unchanged baseline vs
LONG+trend-only abstention in two independent capital-matched PAPER
accounts, and require **both absolute marked after-cost accounts
positive, plus positive candidate delta** with chronological stability.
Do not use a fee-only narrative to justify trading changes when the
actual fee-free same-fills portfolio still loses.
