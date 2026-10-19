# October 19 — freeze a NO-FILL-CERTIFICATE markout stress test

## Discovery from actual PAPER-produced prospective artifact

Exact closed predecessor worker #39255842615 published GitHub artifact
`continuous-paper-momentum-pullback-forward-markout-39255842615-1`,
artifact ID **12206128007**, containing
`prospective-momentum-pullback-forward-markout-summary.json`.

Its frozen research candidate (`prospective-momentum-pullback-entry-v1`)
shows 2,749 prospective opportunities, only **286 risk approved**,
**16 admitted** and 270 blocked. At 60 minutes all 16 were settled,
with **0.246497% mean directional MARK-to-MARK return**, 4 LONG and
12 SHORT across 13 markets. Blocked mean markout was 0.028107%.

A simple after-fee thought experiment DOES NOT produce a tradable edge:

- The first chronological group of four admitted observations averaged
  **−1.098954% gross** at one hour, before venue fees, spread or funding.
- The positive aggregate is market-concentrated. Omit GRASS (three
  admitted observations), and the remaining optimistic one-hour
  fee-adjusted mean is approximately **−0.0100%** at 4.5 bps taker
  fee per side, with still-perfect mark-priced entry and exit.
- The 15-minute observed admitted mean was only **0.069274%** gross,
  BELOW two 4.5 bps fee legs even before entry/exit spreads and funding.
- The one-hour sample count **16** is far below the 40-admission
  *minimum research screening sample* and 72-hour independently
  complete source requirements. The parent v3 original market recorder
  remains permanently FAILED from receive-clock regressions.

All horizons (5, 15, 60 minutes) were examined. The one-hour
observation is retrospective selection among horizons, **not** a
precommitted future holding-time parameter.

## Implemented bounded research rejection contract

The offline `audit_momentum_pullback_fee_stability.py` command consumes a
local copy of the intact original prospective summary and writes a
SHA256-labelled local diagnostic. It is NOT an independent GitHub/
exchange source authentication receipt.

For *all* original frozen horizons, it takes every admitted opportunity
in original chronological order, preserves unsettled rows as explicit
missingness, verifies candidate/decision/target clock integrity, and
computes an **optimistically favorable hypothetical**:

```text
entry mark-value = 1 per unit notional
exit mark-value = 1 + directional_return, LONG
                = 1 - directional_return, SHORT
optimistic normalized net =
    directional_return - taker_fee_rate * (1 + exit mark-value)
```

It then applies four contiguous original chronological blocks and
leave-one-entire-market-out stresses. Conditional positive screening
would require at least 40 admitted rows, at least four markets,
zero missing markouts, strictly positive mean hypothetical net in all
four blocks and positive hypothetical net after dropping each market.
**Even if all conditional tests pass, promotion stays false.**

This ignores REAL spread, marketable entry/exit slip, queue priority,
maker no-fills, size rounding, unavailable full books, hourly funding,
position overlap, liquidity, stop/exit behavior, mark latency and
capital locked in unmatched opportunities. Perfect mark fills are NOT
an executable order simulation. The actual book/funding observations
have not passed a 72h source completeness audit. Therefore no local
conditional markout result can grant positive whole-account after-cost
equity authority.

## Practical next-money objective

Do not tune a threshold to squeeze these 16 rows into a backtested
winner. Freeze a genuinely NEW prospective entry/exit rule and cost
envelope **before it sees future trades**. Require complete true
first-received original L2/trades and hourly funding, independent
signed matched PAPER cash accounts, explicit trading fees, entry/exit
spread and slippage, missed fills, opportunity cost and strict positive
absolute marked PnL. Preserve all failed earlier cadence/timing/
cost>0.25R candidates without restarting/rescaling accounts.

No active strategy, positions, fees, risk limits, market observations
or LIVE permission changed.
